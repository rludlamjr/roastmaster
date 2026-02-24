"""Tests for the Kaleido ASCII text protocol driver.

Covers the pure message helpers (create_msg, parse_response) and the
KaleidoDevice class construction and validation. I/O tests require a
mock serial port or real hardware.

Protocol reference: docs/kaleido-protocol.md
"""

from __future__ import annotations

import queue
import threading
import time

import pytest

from roastmaster.serial.kaleido import (
    KaleidoDevice,
    _is_int_var,
    _is_str_var,
    _validate_percent,
    create_msg,
    parse_response,
)

# =========================================================================
# Tag classification
# =========================================================================


class TestTagClassification:
    def test_int_vars(self):
        for tag in ("sid", "HP", "FC", "RC", "AH", "HS", "EV", "CS"):
            assert _is_int_var(tag), f"{tag} should be int var"

    def test_str_vars(self):
        for tag in ("TU", "SC", "CL", "SN"):
            assert _is_str_var(tag), f"{tag} should be str var"

    def test_float_vars_are_neither(self):
        for tag in ("BT", "ET", "AT", "TS"):
            assert not _is_int_var(tag)
            assert not _is_str_var(tag)


# =========================================================================
# create_msg
# =========================================================================


class TestCreateMsg:
    def test_no_value(self):
        assert create_msg("PI") == "{[PI]}\n"

    def test_string_value(self):
        assert create_msg("TU", "F") == "{[TU F]}\n"
        assert create_msg("TU", "C") == "{[TU C]}\n"
        assert create_msg("SC", "AR") == "{[SC AR]}\n"
        assert create_msg("CL", "AR") == "{[CL AR]}\n"

    def test_int_value(self):
        assert create_msg("HP", "80") == "{[HP 80]}\n"
        assert create_msg("FC", "50") == "{[FC 50]}\n"
        assert create_msg("RC", "60") == "{[RC 60]}\n"
        assert create_msg("AH", "1") == "{[AH 1]}\n"
        assert create_msg("AH", "0") == "{[AH 0]}\n"

    def test_int_value_with_decimal(self):
        # intVar tags preserve up to one decimal (Artisan convention)
        assert create_msg("HP", "75.7") == "{[HP 75.7]}\n"
        assert create_msg("HP", "80.0") == "{[HP 80]}\n"  # trailing .0 stripped

    def test_float_value_rounded_to_int(self):
        # floatVar tags are sent as integers (Artisan convention)
        assert create_msg("TS", "185.0") == "{[TS 185]}\n"
        assert create_msg("TS", "185.5") == "{[TS 186]}\n"

    def test_read_data_stream(self):
        assert create_msg("RD", "A0") == "{[RD A0]}\n"

    def test_event_marker(self):
        assert create_msg("EV", "2") == "{[EV 2]}\n"

    def test_all_messages_end_with_newline(self):
        for msg in [create_msg("PI"), create_msg("HP", "50"), create_msg("TU", "F")]:
            assert msg.endswith("\n")

    def test_all_messages_have_braces(self):
        for msg in [create_msg("PI"), create_msg("HP", "50"), create_msg("TU", "F")]:
            stripped = msg.strip()
            assert stripped.startswith("{[")
            assert stripped.endswith("]}")


# =========================================================================
# parse_response
# =========================================================================


class TestParseResponse:
    def test_sid_only(self):
        sid, state = parse_response("{5}")
        assert sid == 5
        assert state == {}

    def test_single_var(self):
        sid, state = parse_response("{5,TU:C}")
        assert sid == 5
        assert state == {"TU": "C"}

    def test_multiple_vars(self):
        sid, state = parse_response("{5,BT:185.3,ET:220.1,AT:24.5}")
        assert sid == 5
        assert state["BT"] == pytest.approx(185.3)
        assert state["ET"] == pytest.approx(220.1)
        assert state["AT"] == pytest.approx(24.5)

    def test_int_vars_parsed(self):
        sid, state = parse_response("{3,HP:75,FC:50,RC:60}")
        assert sid == 3
        assert state["HP"] == 75
        assert state["FC"] == 50
        assert state["RC"] == 60
        assert isinstance(state["HP"], int)

    def test_str_vars_parsed(self):
        sid, state = parse_response("{0,SN:K12345}")
        assert sid == 0
        assert state["SN"] == "K12345"

    def test_float_vars_parsed(self):
        sid, state = parse_response("{5,TS:185.5}")
        assert sid == 5
        assert state["TS"] == pytest.approx(185.5)
        assert isinstance(state["TS"], float)

    def test_auto_heat_mode(self):
        _, state = parse_response("{5,AH:1}")
        assert state["AH"] == 1
        assert isinstance(state["AH"], int)

    def test_full_broadcast(self):
        msg = "{5,BT:200.5,ET:250.3,AT:25.0,TS:185.0,HP:80,FC:40,RC:60,AH:1,HS:1}"
        sid, state = parse_response(msg)
        assert sid == 5
        assert state["BT"] == pytest.approx(200.5)
        assert state["ET"] == pytest.approx(250.3)
        assert state["HP"] == 80
        assert state["AH"] == 1

    def test_whitespace_stripped(self):
        sid, state = parse_response("  {5,BT:100.0}  \n")
        assert sid == 5
        assert state["BT"] == pytest.approx(100.0)

    def test_sid_float_rounded(self):
        sid, _ = parse_response("{5.0}")
        assert sid == 5

    def test_invalid_no_braces(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_response("5,BT:100")

    def test_invalid_too_short(self):
        with pytest.raises(ValueError, match="Invalid"):
            parse_response("{}")

    def test_invalid_bad_sid(self):
        with pytest.raises(ValueError, match="Cannot parse sid"):
            parse_response("{abc}")

    def test_malformed_var_skipped(self):
        sid, state = parse_response("{5,BADENTRY,BT:100.0}")
        assert sid == 5
        assert state == {"BT": pytest.approx(100.0)}

    def test_roundtrip_with_create_msg_tags(self):
        _, state = parse_response("{5,HP:80}")
        assert state["HP"] == 80


# =========================================================================
# KaleidoDevice construction
# =========================================================================


class TestKaleidoDeviceConstruction:
    def test_default_construction(self):
        dev = KaleidoDevice(port="/dev/ttyUSB0")
        assert dev._port == "/dev/ttyUSB0"
        assert dev._baud_rate == 9600
        assert dev._temp_unit == "F"
        assert dev.connected is False

    def test_custom_baud_rate(self):
        dev = KaleidoDevice(port="/dev/ttyUSB0", baud_rate=115200)
        assert dev._baud_rate == 115200

    def test_celsius_mode(self):
        dev = KaleidoDevice(port="/dev/ttyUSB0", temp_unit="C")
        assert dev._temp_unit == "C"

    def test_repr_disconnected(self):
        dev = KaleidoDevice(port="/dev/ttyUSB0")
        r = repr(dev)
        assert "disconnected" in r
        assert "/dev/ttyUSB0" in r


# =========================================================================
# KaleidoDevice not-connected guards
# =========================================================================


class TestKaleidoNotConnected:
    def test_read_temperatures_raises(self):
        dev = KaleidoDevice(port="/dev/null")
        with pytest.raises(RuntimeError, match="not connected"):
            dev.read_temperatures()

    def test_set_heater_raises(self):
        dev = KaleidoDevice(port="/dev/null")
        with pytest.raises(RuntimeError, match="not connected"):
            dev.set_heater(50)

    def test_set_drum_raises(self):
        dev = KaleidoDevice(port="/dev/null")
        with pytest.raises(RuntimeError, match="not connected"):
            dev.set_drum(50)

    def test_set_fan_raises(self):
        dev = KaleidoDevice(port="/dev/null")
        with pytest.raises(RuntimeError, match="not connected"):
            dev.set_fan(50)


# =========================================================================
# Validation
# =========================================================================


class TestValidation:
    def test_heater_too_low(self):
        dev = KaleidoDevice(port="/dev/null")
        dev._connected = True
        dev._serial = True  # fake to pass connected check
        with pytest.raises(ValueError, match="0-100"):
            dev.set_heater(-1)

    def test_heater_too_high(self):
        dev = KaleidoDevice(port="/dev/null")
        dev._connected = True
        dev._serial = True
        with pytest.raises(ValueError, match="0-100"):
            dev.set_heater(101)

    def test_drum_out_of_range(self):
        dev = KaleidoDevice(port="/dev/null")
        dev._connected = True
        dev._serial = True
        with pytest.raises(ValueError, match="0-100"):
            dev.set_drum(200)

    def test_fan_out_of_range(self):
        dev = KaleidoDevice(port="/dev/null")
        dev._connected = True
        dev._serial = True
        with pytest.raises(ValueError, match="0-100"):
            dev.set_fan(-5)

    def test_validate_percent_helper(self):
        _validate_percent("test", 0)
        _validate_percent("test", 100)
        with pytest.raises(ValueError):
            _validate_percent("test", -1)
        with pytest.raises(ValueError):
            _validate_percent("test", 101)


# =========================================================================
# Artisan-style comm behavior (threaded reader + request/await)
# =========================================================================


class FakeSerial:
    """A minimal fake serial port for exercising KaleidoDevice I/O logic.

    It responds to writes by enqueueing appropriate Kaleido protocol reply lines.
    """

    def __init__(self, *args, **kwargs):
        self.timeout = float(kwargs.get("timeout", 0.4))
        self.is_open = True
        self._rx: queue.Queue[bytes] = queue.Queue()
        self.writes: list[str] = []
        self._lock = threading.Lock()

        # Behavior toggles (tests can override after construction)
        self.delay_rd_s: float = 0.0
        self.hp_single_var_reply: bool = True

    def write(self, data: bytes) -> int:
        text = data.decode("utf-8", errors="replace")
        with self._lock:
            self.writes.append(text)
        self._handle_write(text)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.is_open = False

    def readline(self) -> bytes:
        if not self.is_open:
            return b""
        try:
            return self._rx.get(timeout=self.timeout)
        except queue.Empty:
            return b""

    # ------------------------------
    # Protocol simulation
    # ------------------------------

    def _enqueue(self, line: str, *, delay_s: float = 0.0) -> None:
        payload = (line.strip() + "\n").encode("utf-8")
        if delay_s <= 0:
            self._rx.put(payload)
            return

        def _delayed_put() -> None:
            self._rx.put(payload)

        threading.Timer(delay_s, _delayed_put).start()

    def _handle_write(self, msg: str) -> None:
        stripped = msg.strip()
        if not stripped.startswith("{[") or not stripped.endswith("]}"):
            return

        inner = stripped[2:-2]
        if " " in inner:
            tag, value = inner.split(" ", 1)
        else:
            tag, value = inner, None

        # Minimal handshake + polling responses
        if tag == "PI":
            self._enqueue("{5}")
        elif tag == "TU":
            self._enqueue(f"{{5,TU:{value}}}")
        elif tag == "SC":
            self._enqueue("{5,SC:AR}")
        elif tag == "RD":
            # Broadcast BT/ET + control echo.
            self._enqueue(
                "{5,BT:200.5,ET:250.3,AT:25.0,TS:185.0,HP:80,FC:40,RC:60,AH:1,HS:1}",
                delay_s=self.delay_rd_s,
            )
        elif tag == "HP":
            if self.hp_single_var_reply:
                self._enqueue(f"{{5,HP:{value}}}")
            else:
                # Multi-var reply should NOT satisfy single-var awaits ("!HP").
                self._enqueue(f"{{5,HP:{value},BT:199.9}}")
        elif tag == "FC":
            self._enqueue(f"{{5,FC:{value}}}")
        elif tag == "RC":
            self._enqueue(f"{{5,RC:{value}}}")
        elif tag == "CL":
            self._enqueue("{5,SN:K12345}")


class TestArtisanStyleComm:
    def test_read_temperatures_survives_interleaved_control_reply(self):
        """A control reply arriving before RD must not break BT/ET reads."""

        fake = FakeSerial()
        fake.delay_rd_s = 0.05  # make RD reply arrive after HP reply

        dev = KaleidoDevice(port="FAKE", serial_factory=lambda **kw: fake)  # type: ignore[arg-type]
        dev.connect()
        dev.set_heater(80)

        reading = dev.read_temperatures()
        assert reading.bean_temp == pytest.approx(200.5)
        assert reading.env_temp == pytest.approx(250.3)

        dev.disconnect()

    def test_control_deduplication_avoids_spam(self):
        fake = FakeSerial()
        dev = KaleidoDevice(port="FAKE", serial_factory=lambda **kw: fake)  # type: ignore[arg-type]
        dev.connect()

        for _ in range(10):
            dev.set_fan(40)

        # Give the writer thread a moment to flush.
        time.sleep(0.05)

        fc_writes = [w for w in fake.writes if w.strip().startswith("{[FC ")]
        assert len(fc_writes) == 1

        dev.disconnect()

    def test_single_request_waits_for_single_var_reply(self):
        fake = FakeSerial()
        fake.hp_single_var_reply = False  # respond with multi-var
        dev = KaleidoDevice(port="FAKE", serial_factory=lambda **kw: fake)  # type: ignore[arg-type]
        dev.connect()

        res = dev._send_request("HP", "80", var="HP", timeout=0.2, single_request=True)
        assert res is None

        dev.disconnect()
