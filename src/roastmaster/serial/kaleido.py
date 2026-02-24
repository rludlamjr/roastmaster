"""Kaleido M1 Lite serial driver.

Implements the :class:`~roastmaster.serial.protocol.RoasterDevice` protocol
over a serial (USB) or WebSocket connection to the Kaleido M1 Lite roaster.

Protocol (verified against Artisan's ``kaleido.py``)
----------------------------------------------------
The Kaleido uses a **text-based, newline-delimited** message protocol. The
same format is used over both serial and WebSocket transports.

**Outgoing** (RoastMaster → Kaleido)::

    {[TAG]}\n               # command with no value (e.g. PI ping)
    {[TAG value]}\n         # command with value  (e.g. HP 80)

**Incoming** (Kaleido → RoastMaster)::

    {sid[,var:value]*}\n    # status + zero or more variable updates

There is **no checksum** and **no binary framing**. Messages are plain
ASCII text terminated by ``\\n``.

Key tags
--------
=========  ====  ============================================
 Tag       Dir   Description
=========  ====  ============================================
 PI        →     Ping (no value, elicits ``sid`` response)
 TU        ↔     Temperature unit (``C`` or ``F``)
 SC        →     Start guard (``AR``)
 CL        →     Close guard / end session (``AR``)
 RD        →     Read data stream (``A0``)
 HP        ↔     Heater power 0-100 %
 FC        ↔     Fan/air speed 0-100
 RC        ↔     Drum speed 0-100
 AH        ↔     Auto-heat PID: 0 = off, 1 = on
 TS        ↔     Target/setpoint temperature (°C or °F)
 HS        ↔     Heating switch: 0 = off, 1 = on
 BT        ←     Bean temperature
 ET        ←     Environment temperature
 AT        ←     Ambient temperature
 SN        ←     Serial number
 EV        →     Event marker (e.g. ``2`` = turning point)
=========  ====  ============================================

Init sequence
~~~~~~~~~~~~~
1. Send ``PI`` pings until a valid ``sid`` response arrives (retry 1 s).
2. Send ``TU F`` (or ``TU C``) to set the temperature unit.
3. Send ``SC AR`` to open the session guard.

Temperature polling
~~~~~~~~~~~~~~~~~~~
Send ``{[RD A0]}\\n`` to request a broadcast of all current sensor values.
The machine responds with a message containing ``BT``, ``ET``, ``AT``,
``TS``, ``HP``, ``FC``, ``RC``, etc.

Reference
~~~~~~~~~
Protocol details were derived from Artisan's open-source Kaleido driver:
``src/artisanlib/kaleido.py``
(https://github.com/artisan-roaster-scope/artisan, GPL-3.0).

Our implementation is a clean-room reimplementation: only the factual
protocol specification (message format, tag names, init sequence) has been
used. No Artisan code has been copied.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

import serial

from roastmaster.serial.protocol import RoasterReading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tag classifications (matches Artisan's intVar / strVar / floatVar)
# ---------------------------------------------------------------------------

_INT_VARS: frozenset[str] = frozenset({"sid", "HP", "FC", "RC", "AH", "HS", "EV", "CS"})
_STR_VARS: frozenset[str] = frozenset({"TU", "SC", "CL", "SN"})


def _is_int_var(tag: str) -> bool:
    return tag in _INT_VARS


def _is_str_var(tag: str) -> bool:
    return tag in _STR_VARS


# ---------------------------------------------------------------------------
# Pure message helpers (no I/O — unit-testable)
# ---------------------------------------------------------------------------


def create_msg(tag: str, value: str | None = None) -> str:
    """Build an outgoing command message.

    Examples::

        create_msg('PI')        -> '{[PI]}\\n'
        create_msg('HP', '80')  -> '{[HP 80]}\\n'
        create_msg('TU', 'F')   -> '{[TU F]}\\n'
        create_msg('TS', '185.5') -> '{[TS 186]}\\n'

    Value encoding follows Artisan's ``create_msg()`` conventions:

    * String tags (TU, SC, CL, SN): value sent as-is.
    * Float tags (BT, ET, AT, TS, etc.): ``f'{float(v):.0f}'`` — the
      Kaleido expects integers for these (decimals removed).
    * Int tags (HP, FC, RC, AH, HS, EV, CS): ``f'{float(v):.1f}'`` with
      trailing zeros stripped — the Kaleido expects up to one decimal.
    """
    if value is None:
        return f"{{[{tag}]}}\n"

    encoded = value
    if not _is_str_var(tag):
        try:
            if _is_int_var(tag):
                # intVar: Kaleido expects up to one decimal
                encoded = f"{float(value):.1f}".rstrip("0").rstrip(".")
            else:
                # floatVar: Kaleido expects integers (no decimals)
                encoded = f"{float(value):.0f}"
        except ValueError:
            pass  # keep original string (e.g. "A0" for RD)
    return f"{{[{tag} {encoded}]}}\n"


def parse_response(message: str) -> tuple[int, dict[str, str | int | float]]:
    """Parse an incoming Kaleido response message.

    Args:
        message: Raw message string (with or without surrounding whitespace).
            Expected format: ``{sid[,var:value]*}``.

    Returns:
        A ``(sid, state)`` tuple where *sid* is the device status integer
        and *state* is a dict mapping variable names to typed values.

    Raises:
        ValueError: If the message cannot be parsed.

    Examples::

        parse_response('{5,BT:185.3,ET:220.1}')
        -> (5, {'BT': 185.3, 'ET': 220.1})

        parse_response('{0,SN:K12345}')
        -> (0, {'SN': 'K12345'})
    """
    msg = message.strip()
    if len(msg) < 3 or not msg.startswith("{") or not msg.endswith("}"):
        raise ValueError(f"Invalid Kaleido message: {message!r}")

    inner = msg[1:-1]
    parts = inner.split(",")

    try:
        sid = int(round(float(parts[0])))
    except (ValueError, IndexError) as e:
        raise ValueError(f"Cannot parse sid from: {message!r}") from e

    state: dict[str, str | int | float] = {}
    for part in parts[1:]:
        kv = part.split(":", 1)
        if len(kv) != 2:
            continue
        var, raw_value = kv
        if _is_int_var(var):
            try:
                state[var] = int(round(float(raw_value)))
            except ValueError:
                state[var] = raw_value
        elif _is_str_var(var):
            state[var] = raw_value
        else:
            try:
                state[var] = float(raw_value)
            except ValueError:
                state[var] = raw_value

    return sid, state


# ---------------------------------------------------------------------------
# Serial configuration defaults
# ---------------------------------------------------------------------------

_DEFAULT_BAUD_RATE = 9600
_DEFAULT_BYTESIZE = serial.EIGHTBITS
_DEFAULT_PARITY = serial.PARITY_ODD
_DEFAULT_STOPBITS = serial.STOPBITS_ONE
_DEFAULT_TIMEOUT = 0.4

# Timing
_INIT_TIMEOUT = 6.0  # total init sequence timeout
_PING_TIMEOUT = 1.2  # timeout for a single command/response exchange
_PING_RETRY_DELAY = 1.0  # delay between ping retries
_READ_TIMEOUT = 5.0  # seconds (used for offline heuristics/logging)
_SEND_TIMEOUT = 0.6  # request/await timeout (Artisan-style)

# Reader/writer thread management
_JOIN_TIMEOUT = 1.0


# ---------------------------------------------------------------------------
# KaleidoDevice
# ---------------------------------------------------------------------------


class KaleidoDevice:
    """Serial driver for the Kaleido M1 Lite coffee roaster.

    Implements the :class:`~roastmaster.serial.protocol.RoasterDevice`
    protocol over a USB-serial connection using the Kaleido ASCII text
    protocol.

    Usage::

        device = KaleidoDevice(port="/dev/ttyUSB0")
        device.connect()
        reading = device.read_temperatures()
        device.set_heater(80)
        device.disconnect()

    All control values (heater, drum, fan) are percentages in the range
    0-100.  Temperatures in :class:`~roastmaster.serial.protocol.RoasterReading`
    are always in Fahrenheit.
    """

    def __init__(
        self,
        port: str,
        baud_rate: int = _DEFAULT_BAUD_RATE,
        temp_unit: str = "F",
        *,
        serial_factory: type[serial.Serial] = serial.Serial,
    ) -> None:
        self._port = port
        self._baud_rate = baud_rate
        self._temp_unit = temp_unit
        self._serial_factory = serial_factory
        self._serial: serial.Serial | None = None
        self._connected: bool = False
        self._running: bool = False

        self._lock = threading.Lock()

        # Cached state from last device response (updated by reader thread)
        self._state: dict[str, str | int | float] = {}

        # Outgoing write queue (writer thread)
        self._write_queue: queue.Queue[str | None] | None = None

        # Awaited variable updates (Artisan-style request correlation)
        self._single_await_var_prefix = "!"
        self._pending_requests: dict[str, threading.Event] = {}

        # De-duplication: last sent payload per tag to avoid spamming the roaster
        self._last_sent: dict[str, str] = {}

        # Threads
        self._reader_thread: threading.Thread | None = None
        self._writer_thread: threading.Thread | None = None

        # If True, log raw traffic at INFO
        self._log_traffic = False

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Open the serial port and run the init handshake.

        The init sequence sends PI pings until the device responds, then
        sets the temperature unit and opens the session guard.

        Raises:
            serial.SerialException: If the port cannot be opened.
            TimeoutError: If the device does not respond within the timeout.
        """
        logger.info("Connecting to Kaleido on %s at %d baud", self._port, self._baud_rate)
        self._serial = self._serial_factory(
            port=self._port,
            baudrate=self._baud_rate,
            bytesize=_DEFAULT_BYTESIZE,
            parity=_DEFAULT_PARITY,
            stopbits=_DEFAULT_STOPBITS,
            timeout=_DEFAULT_TIMEOUT,
            xonxoff=False,
            rtscts=False,
            dsrdtr=False,
        )

        self._reset_state()
        self._start_io_threads()
        try:
            self._init_handshake()
        except Exception:
            # Ensure we don't leave background threads running on failed connect.
            self._stop_io_threads()
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:  # noqa: BLE001
                    pass
            self._serial = None
            self._connected = False
            raise
        self._connected = True
        sn = self._state.get("SN", "unknown")
        logger.info("Connected to Kaleido (SN: %s)", sn)

    def disconnect(self) -> None:
        """Send the close guard and close the serial port."""
        try:
            if self._serial is not None and self._serial.is_open:
                try:
                    # Artisan-style: send "end safety guard" and (best effort)
                    # await SN as a single-var reply.
                    self._send_request(
                        "CL",
                        "AR",
                        var="SN",
                        timeout=2 * _SEND_TIMEOUT,
                        single_request=True,
                    )
                except Exception:  # noqa: BLE001
                    pass  # best-effort close
        finally:
            self._stop_io_threads()
            if self._serial is not None:
                try:
                    self._serial.close()
                except Exception:  # noqa: BLE001
                    pass
            if self._serial is not None:
                logger.info("Disconnected from Kaleido on %s", self._port)
            self._serial = None
            self._connected = False
            self._reset_state()

    @property
    def connected(self) -> bool:
        return (
            self._connected
            and self._serial is not None
            and bool(getattr(self._serial, "is_open", False))
            and self._running
        )

    # ------------------------------------------------------------------
    # Temperature reading
    # ------------------------------------------------------------------

    def read_temperatures(self) -> RoasterReading:
        """Request a data broadcast and return BT/ET.

        Sends ``{[RD A0]}`` and parses the response for BT and ET values.

        Returns:
            :class:`~roastmaster.serial.protocol.RoasterReading` with BT and
            ET in Fahrenheit.

        Raises:
            RuntimeError: If not connected.
            ValueError: If the response does not contain BT and ET.
        """
        self._require_connected()
        timestamp = time.time()
        res = self._send_request("RD", "A0", var="BT", timeout=_PING_TIMEOUT)
        if res is None:
            raise TimeoutError("Timed out waiting for Kaleido RD response")

        with self._lock:
            bt = self._state.get("BT")
            et = self._state.get("ET")

        if bt is None or et is None:
            raise ValueError(
                f"Response missing BT/ET (state: {self._state})"
            )

        return RoasterReading(
            bean_temp=float(bt),
            env_temp=float(et),
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------
    # Control commands
    # ------------------------------------------------------------------

    def set_heater(self, power: int) -> None:
        """Set heater/burner power (0-100 %)."""
        _validate_percent("power", power)
        self._require_connected()
        self._send_deduped("HP", create_msg("HP", str(power)))

    def set_drum(self, speed: int) -> None:
        """Set drum rotation speed (0-100)."""
        _validate_percent("speed", speed)
        self._require_connected()
        self._send_deduped("RC", create_msg("RC", str(speed)))

    def set_fan(self, speed: int) -> None:
        """Set fan/air speed (0-100)."""
        _validate_percent("speed", speed)
        self._require_connected()
        self._send_deduped("FC", create_msg("FC", str(speed)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_handshake(self) -> None:
        """Run the PI → TU → SC AR init sequence."""
        deadline = time.monotonic() + _INIT_TIMEOUT

        # Step 1: ping until we get a sid response
        while time.monotonic() < deadline:
            try:
                sid = self._send_request("PI", var="sid", timeout=_PING_TIMEOUT)
                if sid is not None and self.get_state("sid") is not None:
                    break
            except (TimeoutError, ValueError):
                pass
            time.sleep(_PING_RETRY_DELAY)
        else:
            raise TimeoutError("Kaleido did not respond to PI ping within timeout")

        # Step 2: set temperature unit
        try:
            self._send_request(
                "TU",
                self._temp_unit,
                var="TU",
                timeout=_PING_TIMEOUT,
                single_request=True,
            )
        except Exception:  # noqa: BLE001
            pass  # best-effort

        # Step 3: start session guard
        try:
            self._send_request(
                "SC",
                "AR",
                var="SC",
                timeout=_PING_TIMEOUT,
                single_request=True,
            )
        except Exception:  # noqa: BLE001
            pass  # best-effort

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError(
                "KaleidoDevice is not connected. Call connect() first."
            )

    def __repr__(self) -> str:
        status = "connected" if self.connected else "disconnected"
        return f"KaleidoDevice(port={self._port!r}, status={status})"

    # ------------------------------------------------------------------
    # Artisan-style comm primitives (clean-room implementation)
    # ------------------------------------------------------------------

    def set_logging(self, enabled: bool) -> None:
        """Enable raw traffic logging (INFO).

        Useful for debugging real-device communication, especially over Bluetooth.
        """
        self._log_traffic = enabled

    def get_state(self, var: str) -> str | int | float | None:
        """Return the current state for a given variable (Artisan-style defaults)."""
        with self._lock:
            if var in self._state:
                return self._state[var]
        if var in {"sid", "TU", "SC", "CL", "SN"}:
            return None
        if _is_int_var(var):
            return -1
        return -1.0

    def _reset_state(self) -> None:
        with self._lock:
            self._state = {}
            self._pending_requests = {}
            self._last_sent = {}

    def _start_io_threads(self) -> None:
        if self._running:
            return
        if self._serial is None:
            raise RuntimeError("Serial port is not open")
        self._running = True
        self._write_queue = queue.Queue()

        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="KaleidoSerialReader",
            daemon=True,
        )
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            name="KaleidoSerialWriter",
            daemon=True,
        )
        self._reader_thread.start()
        self._writer_thread.start()

    def _stop_io_threads(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._write_queue is not None:
            try:
                self._write_queue.put_nowait(None)
            except Exception:  # noqa: BLE001
                pass

        for t in (self._reader_thread, self._writer_thread):
            if t is not None and t.is_alive():
                t.join(timeout=_JOIN_TIMEOUT)

        self._reader_thread = None
        self._writer_thread = None
        self._write_queue = None

        with self._lock:
            # Unblock any pending send_request waiters so we don't hang on shutdown.
            pending = list(self._pending_requests.values())
            self._pending_requests.clear()
        for ev in pending:
            ev.set()

    def _writer_loop(self) -> None:
        assert self._serial is not None
        assert self._write_queue is not None
        while self._running:
            try:
                msg = self._write_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if msg is None:
                    break
                if self._log_traffic:
                    logger.info("TX: %s", msg.strip())
                self._serial.write(msg.encode("utf-8"))
                self._serial.flush()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Writer loop error: %s", exc)
                break
            finally:
                try:
                    self._write_queue.task_done()
                except Exception:  # noqa: BLE001
                    pass

    def _reader_loop(self) -> None:
        assert self._serial is not None
        while self._running:
            try:
                raw = self._serial.readline()
            except Exception as exc:  # noqa: BLE001
                logger.debug("Reader loop error: %s", exc)
                break

            if not raw:
                continue

            try:
                message = raw.decode("utf-8", errors="replace").strip()
            except Exception:  # noqa: BLE001
                continue

            if not message:
                continue
            if self._log_traffic:
                logger.info("RX: %s", message)
            self._process_message(message)

        # If we exit the reader loop unexpectedly, mark disconnected and stop writer too.
        self._connected = False
        self._running = False
        if self._write_queue is not None:
            try:
                self._write_queue.put_nowait(None)
            except Exception:  # noqa: BLE001
                pass

    def _process_message(self, message: str) -> None:
        msg = message.strip()
        if len(msg) < 3 or not msg.startswith("{") or not msg.endswith("}"):
            return

        # Determine whether this was a "single-var reply" (Artisan uses this to disambiguate awaits)
        parts = msg[1:-1].split(",")
        single_res = len(parts[1:]) == 1

        try:
            sid, state = parse_response(msg)
        except ValueError:
            return

        # Update sid and clear any waiters on sid
        with self._lock:
            self._state["sid"] = sid
        self._clear_request("sid")

        for var, value in state.items():
            with self._lock:
                self._state[var] = value
            clear_var = f"{self._single_await_var_prefix}{var}" if single_res else var
            self._clear_request(clear_var)

    def _add_request(self, var: str) -> threading.Event:
        with self._lock:
            ev = self._pending_requests.get(var)
            if ev is None:
                ev = threading.Event()
                self._pending_requests[var] = ev
            return ev

    def _clear_request(self, var: str) -> None:
        ev: threading.Event | None = None
        with self._lock:
            ev = self._pending_requests.pop(var, None)
        if ev is not None:
            ev.set()

    def _send(self, message: str) -> None:
        if not self._running or self._write_queue is None:
            raise RuntimeError("Kaleido I/O threads not running")
        self._write_queue.put(message)

    def _send_deduped(self, tag: str, message: str) -> None:
        """Send a message but avoid re-sending identical payloads for the same tag."""
        with self._lock:
            if self._last_sent.get(tag) == message:
                return
            self._last_sent[tag] = message
        self._send(message)

    def _send_request(
        self,
        target: str,
        value: str | None = None,
        *,
        var: str | None = None,
        timeout: float | None = None,
        single_request: bool = False,
    ) -> str | None:
        """Send a message and await an updated value for *var* (Artisan-style)."""
        if timeout is None:
            timeout = _SEND_TIMEOUT

        variable = target if var is None else var
        await_var = (
            f"{self._single_await_var_prefix}{variable}"
            if var is None or single_request
            else variable
        )

        ev = self._add_request(await_var)
        self._send(create_msg(target, value))
        if not ev.wait(timeout):
            # Prevent unbounded growth of pending requests on repeated timeouts.
            with self._lock:
                if self._pending_requests.get(await_var) is ev:
                    self._pending_requests.pop(await_var, None)
            return None
        return str(self.get_state(variable))


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _validate_percent(name: str, value: int) -> None:
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be 0-100, got {value}")
