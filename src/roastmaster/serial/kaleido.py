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
_READ_TIMEOUT = 5.0  # data read timeout (triggers disconnect)


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
    ) -> None:
        self._port = port
        self._baud_rate = baud_rate
        self._temp_unit = temp_unit
        self._serial: serial.Serial | None = None
        self._connected: bool = False
        # Cached state from last device response
        self._state: dict[str, str | int | float] = {}

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
        self._serial = serial.Serial(
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
        self._state = {}
        self._init_handshake()
        self._connected = True
        sn = self._state.get("SN", "unknown")
        logger.info("Connected to Kaleido (SN: %s)", sn)

    def disconnect(self) -> None:
        """Send the close guard and close the serial port."""
        if self._serial is not None and self._serial.is_open:
            try:
                self._send_and_recv(create_msg("CL", "AR"))
            except Exception:  # noqa: BLE001
                pass  # best-effort close
            self._serial.close()
            logger.info("Disconnected from Kaleido on %s", self._port)
        self._serial = None
        self._connected = False
        self._state = {}

    @property
    def connected(self) -> bool:
        return self._connected and self._serial is not None and self._serial.is_open

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
        self._send_and_recv(create_msg("RD", "A0"))

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
        self._send(create_msg("HP", str(power)))

    def set_drum(self, speed: int) -> None:
        """Set drum rotation speed (0-100)."""
        _validate_percent("speed", speed)
        self._require_connected()
        self._send(create_msg("RC", str(speed)))

    def set_fan(self, speed: int) -> None:
        """Set fan/air speed (0-100)."""
        _validate_percent("speed", speed)
        self._require_connected()
        self._send(create_msg("FC", str(speed)))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _init_handshake(self) -> None:
        """Run the PI → TU → SC AR init sequence."""
        assert self._serial is not None
        deadline = time.monotonic() + _INIT_TIMEOUT

        # Step 1: ping until we get a sid response
        while time.monotonic() < deadline:
            try:
                self._send_and_recv(create_msg("PI"))
                if "sid" in self._state:
                    break
            except (serial.SerialTimeoutException, ValueError):
                pass
            time.sleep(_PING_RETRY_DELAY)
        else:
            raise TimeoutError("Kaleido did not respond to PI ping within timeout")

        # Step 2: set temperature unit
        self._send_and_recv(create_msg("TU", self._temp_unit))

        # Step 3: start session guard
        self._send_and_recv(create_msg("SC", "AR"))

    def _send(self, message: str) -> None:
        """Write a message to the serial port (fire-and-forget)."""
        assert self._serial is not None
        self._serial.write(message.encode("utf-8"))
        self._serial.flush()
        logger.debug("Sent: %s", message.strip())

    def _recv(self) -> str:
        """Read one newline-terminated message from the serial port.

        Raises:
            serial.SerialTimeoutException: If no complete line arrives
                within the configured timeout.
        """
        assert self._serial is not None
        # Temporarily increase timeout for reads that expect a response
        old_timeout = self._serial.timeout
        self._serial.timeout = _PING_TIMEOUT
        try:
            raw = self._serial.readline()
        finally:
            self._serial.timeout = old_timeout

        if not raw:
            raise serial.SerialTimeoutException("No response from Kaleido")

        message = raw.decode("utf-8", errors="replace").strip()
        logger.debug("Recv: %s", message)
        return message

    def _send_and_recv(self, message: str) -> tuple[int, dict[str, str | int | float]]:
        """Send a command and parse the response, updating internal state."""
        self._send(message)
        response = self._recv()
        sid, state = parse_response(response)
        self._state["sid"] = sid
        self._state.update(state)
        return sid, state

    def _require_connected(self) -> None:
        if not self.connected:
            raise RuntimeError(
                "KaleidoDevice is not connected. Call connect() first."
            )

    def __repr__(self) -> str:
        status = "connected" if self.connected else "disconnected"
        return f"KaleidoDevice(port={self._port!r}, status={status})"


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _validate_percent(name: str, value: int) -> None:
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be 0-100, got {value}")
