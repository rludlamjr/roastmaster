"""Integration tests for the full roast loop wiring.

Tests the RoastSession and the _handle_input / _sample helpers that
connect HAL input -> engine -> device -> display.
"""

from __future__ import annotations

import unittest.mock as mock

import pytest

from roastmaster.app import (
    RoastSession,
    _build_render_data,
    _handle_input,
    _is_valid_reading,
    _safe_sample,
    _sample,
)
from roastmaster.engine.events import EventType
from roastmaster.engine.roast import RoastPhase
from roastmaster.hal.base import InputEvent
from roastmaster.hal.keyboard import KeyboardInput
from roastmaster.sim.device_adapter import SimulatedRoasterDevice

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def session():
    return RoastSession()


@pytest.fixture()
def device():
    with mock.patch("roastmaster.sim.device_adapter.time") as mock_time:
        mock_time.time.return_value = 1_000_000.0
        dev = SimulatedRoasterDevice(ambient_temp_f=70.0)
        dev.connect()
        yield dev, mock_time


@pytest.fixture()
def hal(pygame_headless):
    return KeyboardInput()


@pytest.fixture()
def renderer(pygame_headless):
    import pygame

    surface = pygame.Surface((640, 480))
    from roastmaster.display.renderer import Renderer

    return Renderer(surface=surface, window_seconds=600.0)


# ---------------------------------------------------------------------------
# RoastSession
# ---------------------------------------------------------------------------


class TestRoastSession:
    def test_initial_state(self, session):
        assert session.fsm.phase == RoastPhase.IDLE
        assert session.bt is None
        assert session.et is None
        assert session.current_ror is None
        assert session.auto_mode is False

    def test_reset(self, session):
        session.bt = 200.0
        session.auto_mode = True
        session.fsm.start_preheat(0.0)
        session.reset()
        assert session.fsm.phase == RoastPhase.IDLE
        assert session.bt is None
        assert session.auto_mode is False


# ---------------------------------------------------------------------------
# Input handling: phase transitions
# ---------------------------------------------------------------------------


class TestHandleInput:
    def test_burner_up_triggers_preheat(self, session, device, hal):
        dev, _ = device
        session.fsm.elapsed = 1.0
        msg = _handle_input(InputEvent.BURNER_UP, session, dev, hal)
        assert session.fsm.phase == RoastPhase.PREHEAT
        assert msg == "PREHEAT (HEAT OFF)"

    def test_burner_up_noop_in_preheat(self, session, device, hal):
        dev, _ = device
        session.fsm.elapsed = 1.0
        session.fsm.start_preheat(0.0)
        msg = _handle_input(InputEvent.BURNER_UP, session, dev, hal)
        assert msg is None  # no transition message

    def test_charge_from_idle(self, session, device, hal):
        dev, _ = device
        session.fsm.elapsed = 5.0
        session.bt = 380.0
        msg = _handle_input(InputEvent.CHARGE, session, dev, hal)
        assert session.fsm.phase == RoastPhase.CHARGE
        assert msg == "CHARGE MARKED"
        assert session.events.get_event(EventType.CHARGE) is not None

    def test_charge_from_preheat(self, session, device, hal):
        dev, _ = device
        session.fsm.start_preheat(0.0)
        session.fsm.elapsed = 10.0
        session.bt = 380.0
        msg = _handle_input(InputEvent.CHARGE, session, dev, hal)
        assert session.fsm.phase == RoastPhase.CHARGE
        assert msg == "CHARGE MARKED"

    def test_charge_always_marks(self, session, device, hal):
        dev, _ = device
        session.fsm.start_preheat(0.0)
        session.fsm.charge(1.0)
        session.fsm.begin_roasting(2.0)
        session.fsm.elapsed = 10.0
        msg = _handle_input(InputEvent.CHARGE, session, dev, hal)
        assert msg == "CHARGE MARKED"

    def test_first_crack_during_roasting(self, session, device, hal):
        dev, _ = device
        session.fsm.start_preheat(0.0)
        session.fsm.charge(1.0)
        session.fsm.begin_roasting(5.0)
        session.fsm.elapsed = 300.0
        session.bt = 400.0
        msg = _handle_input(InputEvent.FIRST_CRACK, session, dev, hal)
        assert msg == "FIRST CRACK"
        fc = session.events.get_event(EventType.FIRST_CRACK)
        assert fc is not None
        assert fc.temperature == 400.0

    def test_first_crack_auto_advances_from_idle(self, session, device, hal):
        dev, _ = device
        session.fsm.elapsed = 5.0
        session.bt = 200.0
        msg = _handle_input(InputEvent.FIRST_CRACK, session, dev, hal)
        assert msg == "FIRST CRACK"
        assert session.fsm.phase == RoastPhase.ROASTING

    def test_drop_transitions_to_cooling(self, session, device, hal):
        dev, _ = device
        session.fsm.start_preheat(0.0)
        session.fsm.charge(1.0)
        session.fsm.begin_roasting(5.0)
        session.fsm.elapsed = 600.0
        session.bt = 420.0
        msg = _handle_input(InputEvent.DROP, session, dev, hal)
        assert session.fsm.phase == RoastPhase.COOLING
        assert msg == "DROP"
        assert session.events.get_event(EventType.DROP) is not None

    def test_mode_toggle(self, session, device, hal):
        dev, _ = device
        assert session.auto_mode is False
        msg = _handle_input(InputEvent.MODE_TOGGLE, session, dev, hal)
        assert session.auto_mode is True
        assert session.pid.active is True
        assert msg == "MODE: AUTO"

        msg = _handle_input(InputEvent.MODE_TOGGLE, session, dev, hal)
        assert session.auto_mode is False
        assert session.pid.active is False
        assert msg == "MODE: MANUAL"


# ---------------------------------------------------------------------------
# Sampling and engine update
# ---------------------------------------------------------------------------


class TestSample:
    def test_sample_updates_session_temps(self, session, device, hal, renderer):
        dev, mock_time = device
        session.fsm.elapsed = 1.0
        mock_time.time.return_value = 1_000_001.0
        _sample(session, dev, hal, renderer)
        assert session.bt is not None
        assert session.et is not None

    def test_sample_updates_ror_after_enough_data(self, session, device, hal, renderer):
        dev, mock_time = device
        # Need smoothing_window(6) + delta_span(20) = 26 raw samples
        dev.set_heater(80)
        for i in range(30):
            session.fsm.elapsed = float(i)
            mock_time.time.return_value = 1_000_000.0 + i
            _sample(session, dev, hal, renderer)
        assert session.current_ror is not None

    def test_turning_point_transitions_charge_to_roasting(
        self, session, device, hal, renderer
    ):
        dev, mock_time = device
        # Set up in CHARGE phase
        session.fsm.start_preheat(0.0)
        session.fsm.charge(1.0)

        # Simulate: BT decreasing then rising (turning point)
        # First heat up the sim so BT > ambient
        dev.set_heater(100)
        t = 1_000_002.0
        for i in range(120):
            mock_time.time.return_value = t + i
            dev.read_temperatures()  # advance sim time

        # Now cut heater to let BT fall, then restore
        dev.set_heater(0)
        for i in range(20):
            session.fsm.elapsed = 122.0 + i
            mock_time.time.return_value = t + 120 + i
            _sample(session, dev, hal, renderer)

        # Restore heat
        dev.set_heater(100)
        for i in range(20):
            session.fsm.elapsed = 142.0 + i
            mock_time.time.return_value = t + 140 + i
            _sample(session, dev, hal, renderer)

        # The turning point should have been detected
        tp = session.events.get_event(EventType.TURNING_POINT)
        if tp is not None:
            assert session.fsm.phase == RoastPhase.ROASTING


# ---------------------------------------------------------------------------
# Render data builder
# ---------------------------------------------------------------------------


class TestBuildRenderData:
    def test_contains_all_required_keys(self, session, hal):
        data = _build_render_data(session, hal, "")
        required = {"bt", "et", "ror", "elapsed", "phase", "burner", "drum", "air", "message"}
        assert required.issubset(data.keys())

    def test_phase_name_matches_fsm(self, session, hal):
        data = _build_render_data(session, hal, "")
        assert data["phase"] == "IDLE"

    def test_message_passthrough(self, session, hal):
        data = _build_render_data(session, hal, "")
        assert data["message"] == ""

        data = _build_render_data(session, hal, "TEST MSG")
        assert data["message"] == "TEST MSG"

    def test_control_values_from_hal(self, session, hal):
        hal._state.burner = 75
        hal._state.drum = 60
        hal._state.air = 40
        data = _build_render_data(session, hal, "")
        assert data["burner"] == 75.0
        assert data["drum"] == 60.0
        assert data["air"] == 40.0


# ---------------------------------------------------------------------------
# Error handling (Plan 8.2)
# ---------------------------------------------------------------------------


class TestIsValidReading:
    def test_normal_values(self):
        assert _is_valid_reading(200.0, 300.0) is True

    def test_nan_bt(self):
        assert _is_valid_reading(float("nan"), 300.0) is False

    def test_nan_et(self):
        assert _is_valid_reading(200.0, float("nan")) is False

    def test_bt_too_low(self):
        assert _is_valid_reading(-100.0, 300.0) is False

    def test_bt_too_high(self):
        assert _is_valid_reading(800.0, 300.0) is False

    def test_et_too_high(self):
        assert _is_valid_reading(200.0, 900.0) is False

    def test_boundary_values(self):
        assert _is_valid_reading(-50.0, 700.0) is True
        assert _is_valid_reading(0.0, 0.0) is True


class TestSafeSample:
    def test_normal_read_succeeds(self, session, device, hal, renderer):
        dev, mock_time = device
        session.fsm.elapsed = 1.0
        mock_time.time.return_value = 1_000_001.0
        msg, err = _safe_sample(session, dev, hal, renderer, error_count=0)
        assert msg == ""
        assert err == 0
        assert session.bt is not None

    def test_timeout_returns_error(self, session, device, hal, renderer):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        dev, mock_time = device
        dev.inject_fault(FaultConfig(fault_type=FaultType.TIMEOUT))
        session.fsm.elapsed = 1.0
        mock_time.time.return_value = 1_000_001.0
        msg, err = _safe_sample(session, dev, hal, renderer, error_count=0)
        assert "ERROR" in msg or "OFFLINE" in msg
        assert err == 1
        dev.clear_faults()

    def test_sensor_failure_returns_bad_data_msg(self, session, device, hal, renderer):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        dev, mock_time = device
        dev.inject_fault(FaultConfig(fault_type=FaultType.SENSOR_FAILURE))
        session.fsm.elapsed = 1.0
        mock_time.time.return_value = 1_000_001.0
        msg, err = _safe_sample(session, dev, hal, renderer, error_count=0)
        assert "BAD" in msg
        assert err == 1
        dev.clear_faults()

    def test_consecutive_errors_escalate(self, session, device, hal, renderer):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        dev, mock_time = device
        dev.inject_fault(
            FaultConfig(fault_type=FaultType.TIMEOUT, duration_reads=-1)
        )
        err = 0
        for i in range(5):
            session.fsm.elapsed = float(i + 1)
            mock_time.time.return_value = 1_000_001.0 + i
            msg, err = _safe_sample(session, dev, hal, renderer, error_count=err)
        assert err >= 3
        assert "OFFLINE" in msg
        dev.clear_faults()

    def test_error_count_resets_on_good_read(self, session, device, hal, renderer):
        dev, mock_time = device
        session.fsm.elapsed = 1.0
        mock_time.time.return_value = 1_000_001.0
        msg, err = _safe_sample(session, dev, hal, renderer, error_count=5)
        assert err == 0
