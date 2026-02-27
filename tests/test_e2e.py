"""End-to-end integration test: complete simulated roast IDLE -> DONE.

Plan 8.1: Run a complete simulated roast using all real modules (not mocks,
except for time control) and verify data flow end-to-end.

This test exercises the full stack:
  HAL -> Engine (FSM, RoR, Events, PID) -> Device (SimulatedRoasterDevice)
  -> Display (Renderer) -> Profile (save/load/reference)
"""

from __future__ import annotations

import unittest.mock as mock

import pygame
import pytest

from roastmaster.app import RoastSession, _build_render_data, _handle_input, _sample
from roastmaster.display.renderer import Renderer
from roastmaster.engine.events import EventType
from roastmaster.engine.roast import RoastPhase
from roastmaster.hal.base import InputEvent
from roastmaster.hal.keyboard import KeyboardInput
from roastmaster.profiles.manager import ProfileManager
from roastmaster.sim.device_adapter import SimulatedRoasterDevice


@pytest.fixture()
def e2e_env(pygame_headless, tmp_path):
    """Create a fully wired environment for e2e testing.

    Returns a dict with all components needed for a complete roast.
    Time is mocked so we can advance it deterministically.
    """
    with mock.patch("roastmaster.sim.device_adapter.time") as mock_time:
        t0 = 1_000_000.0
        mock_time.time.return_value = t0

        device = SimulatedRoasterDevice(ambient_temp_f=70.0)
        device.connect()

        hal = KeyboardInput()
        surface = pygame.Surface((640, 480))
        renderer = Renderer(surface=surface, window_seconds=600.0)
        session = RoastSession()
        profile_mgr = ProfileManager(directory=tmp_path / "profiles")

        yield {
            "device": device,
            "hal": hal,
            "renderer": renderer,
            "session": session,
            "profile_mgr": profile_mgr,
            "mock_time": mock_time,
            "t0": t0,
        }


def _advance_time(env, seconds: float, *, heater: int = 0) -> None:
    """Advance simulation time by `seconds`, sampling at 1 Hz."""
    device = env["device"]
    session = env["session"]
    hal = env["hal"]
    renderer = env["renderer"]
    mock_time = env["mock_time"]
    t0 = env["t0"]

    device.set_heater(heater)

    current_elapsed = session.fsm.elapsed
    for i in range(int(seconds)):
        elapsed = current_elapsed + i + 1
        session.fsm.elapsed = elapsed
        mock_time.time.return_value = t0 + elapsed
        _sample(session, device, hal, renderer)


class TestFullRoastE2E:
    """Complete roast lifecycle from IDLE through all phases."""

    def test_complete_roast_lifecycle(self, e2e_env):
        env = e2e_env
        session = env["session"]
        device = env["device"]
        hal = env["hal"]
        renderer = env["renderer"]
        profile_mgr = env["profile_mgr"]
        mock_time = env["mock_time"]
        t0 = env["t0"]

        # ----------------------------------------------------------
        # 1. Start in IDLE
        # ----------------------------------------------------------
        assert session.fsm.phase == RoastPhase.IDLE

        # ----------------------------------------------------------
        # 2. BURNER_UP -> transitions to PREHEAT
        # ----------------------------------------------------------
        hal._state.burner = 80
        session.fsm.elapsed = 1.0
        msg = _handle_input(InputEvent.BURNER_UP, session, device, hal)
        assert session.fsm.phase == RoastPhase.PREHEAT
        assert msg == "PREHEAT (HEAT OFF)"

        # ----------------------------------------------------------
        # 3. Preheat the roaster for 120 seconds
        # ----------------------------------------------------------
        _advance_time(env, 120, heater=80)
        assert session.bt is not None
        assert session.bt > 70.0  # should be warming

        # ----------------------------------------------------------
        # 4. CHARGE -> transitions to CHARGE phase
        # ----------------------------------------------------------
        session.fsm.elapsed = 121.0
        msg = _handle_input(InputEvent.CHARGE, session, device, hal)
        assert session.fsm.phase == RoastPhase.CHARGE
        assert msg == "CHARGE MARKED"
        charge_event = session.events.get_event(EventType.CHARGE)
        assert charge_event is not None

        # ----------------------------------------------------------
        # 5. Manually transition to ROASTING (in real use the turning
        #    point detector does this, but it requires specific temp
        #    dynamics that are hard to guarantee in a fast test)
        # ----------------------------------------------------------
        session.fsm.begin_roasting(session.fsm.elapsed)
        assert session.fsm.phase == RoastPhase.ROASTING

        # ----------------------------------------------------------
        # 6. Roast for 300 seconds (5 min) at high heat
        # ----------------------------------------------------------
        _advance_time(env, 300, heater=80)
        assert session.bt > 100.0  # should be well above ambient

        # Check that RoR has been computed
        assert session.current_ror is not None

        # Check that samples are being recorded
        assert len(session.samples) > 400  # preheat + charge + roasting

        # ----------------------------------------------------------
        # 7. Mark FIRST CRACK
        # ----------------------------------------------------------
        session.fsm.elapsed = 421.0
        msg = _handle_input(InputEvent.FIRST_CRACK, session, device, hal)
        assert msg == "FIRST CRACK"
        fc = session.events.get_event(EventType.FIRST_CRACK)
        assert fc is not None
        assert fc.temperature == session.bt

        # ----------------------------------------------------------
        # 8. Mark SECOND CRACK
        # ----------------------------------------------------------
        _advance_time(env, 60, heater=70)
        session.fsm.elapsed = 481.0
        msg = _handle_input(InputEvent.SECOND_CRACK, session, device, hal)
        assert msg == "SECOND CRACK"
        sc = session.events.get_event(EventType.SECOND_CRACK)
        assert sc is not None

        # ----------------------------------------------------------
        # 9. DROP -> transitions to COOLING
        # ----------------------------------------------------------
        session.fsm.elapsed = 482.0
        msg = _handle_input(InputEvent.DROP, session, device, hal)
        assert session.fsm.phase == RoastPhase.COOLING
        assert msg == "DROP"
        drop_event = session.events.get_event(EventType.DROP)
        assert drop_event is not None

        # ----------------------------------------------------------
        # 10. Verify render data works throughout
        # ----------------------------------------------------------
        data = _build_render_data(session, hal, "DROP")
        assert data["phase"] == "COOLING"
        assert data["bt"] is not None
        assert data["et"] is not None
        assert "DROP" in data["message"]

        # Render a frame to verify no crashes
        renderer.render(data)

        # ----------------------------------------------------------
        # 11. Save the profile
        # ----------------------------------------------------------
        profile = session.build_profile()
        assert len(profile.samples) > 0
        assert len(profile.events) >= 4  # CHARGE, FC, SC, DROP

        path = profile_mgr.save(profile, filename="e2e_test_roast")
        assert path.exists()

        # ----------------------------------------------------------
        # 12. Load the profile back
        # ----------------------------------------------------------
        loaded = profile_mgr.load("e2e_test_roast")
        assert len(loaded.samples) == len(profile.samples)
        assert len(loaded.events) == len(profile.events)

        # Check profile list
        profiles = profile_mgr.list_profiles()
        assert "e2e_test_roast" in profiles

        # ----------------------------------------------------------
        # 13. Set loaded profile as reference and render with it
        # ----------------------------------------------------------
        renderer.set_reference_profile(loaded.samples)
        assert renderer._graph.has_reference
        renderer.render(data)

        # ----------------------------------------------------------
        # 14. Verify device is still connected and functional
        # ----------------------------------------------------------
        assert device.connected
        mock_time.time.return_value = t0 + 600.0
        reading = device.read_temperatures()
        assert reading.bean_temp is not None

    def test_mode_toggle_during_roast(self, e2e_env):
        """Test switching between manual and auto PID during a roast."""
        env = e2e_env
        session = env["session"]
        device = env["device"]
        hal = env["hal"]

        # Start preheat
        hal._state.burner = 80
        session.fsm.elapsed = 1.0
        _handle_input(InputEvent.BURNER_UP, session, device, hal)
        assert session.fsm.phase == RoastPhase.PREHEAT

        # Toggle to auto mode
        msg = _handle_input(InputEvent.MODE_TOGGLE, session, device, hal)
        assert msg == "MODE: AUTO"
        assert session.auto_mode is True
        assert session.pid.active is True

        # Toggle back to manual
        msg = _handle_input(InputEvent.MODE_TOGGLE, session, device, hal)
        assert msg == "MODE: MANUAL"
        assert session.auto_mode is False

    def test_profile_browser_flow(self, e2e_env):
        """Test the full profile browser workflow: save, browse, select, load."""
        env = e2e_env
        session = env["session"]
        renderer = env["renderer"]
        profile_mgr = env["profile_mgr"]

        # Create some sample data and save profiles
        _advance_time(env, 10, heater=50)
        for name in ["ethiopia", "colombia", "kenya"]:
            profile = session.build_profile()
            profile.name = name
            profile_mgr.save(profile, filename=name)

        # Open browser
        profiles = profile_mgr.list_profiles()
        renderer.show_browser(profiles)
        assert renderer.browser_visible
        assert renderer.browser.profiles == ["colombia", "ethiopia", "kenya"]

        # Navigate down
        renderer.browser.move_down()
        assert renderer.browser.selected_name == "ethiopia"

        # Select and load
        selected = renderer.browser.selected_name
        loaded = profile_mgr.load(selected)
        renderer.set_reference_profile(loaded.samples)
        renderer.hide_browser()

        assert not renderer.browser_visible
        assert renderer._graph.has_reference

    def test_data_integrity_through_pipeline(self, e2e_env):
        """Verify data flows correctly through the entire pipeline."""
        env = e2e_env
        session = env["session"]
        hal = env["hal"]
        renderer = env["renderer"]

        # Set control values
        hal._state.burner = 65
        hal._state.drum = 70
        hal._state.air = 35

        # Advance to get some data
        _advance_time(env, 30, heater=65)

        # Build render data and verify it matches
        data = _build_render_data(session, hal, "TEST")
        assert data["burner"] == 65.0
        assert data["drum"] == 70.0
        assert data["air"] == 35.0
        assert data["bt"] == session.bt
        assert data["et"] == session.et
        assert data["ror"] == session.current_ror
        assert data["phase"] == session.fsm.phase.name

        # Render should not crash
        renderer.render(data)

    def test_fault_during_roast(self, e2e_env):
        """Test that fault injection triggers expected errors during a roast."""
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        env = e2e_env
        device = env["device"]
        session = env["session"]
        mock_time = env["mock_time"]
        t0 = env["t0"]

        # Start with some normal operation
        _advance_time(env, 5, heater=50)

        # Inject a timeout fault
        device.inject_fault(
            FaultConfig(fault_type=FaultType.TIMEOUT, duration_reads=1)
        )

        # Next read should fail
        session.fsm.elapsed = 6.0
        mock_time.time.return_value = t0 + 6.0
        with pytest.raises(TimeoutError):
            device.read_temperatures()

        # After the transient fault, reads should succeed again
        device.clear_faults()
        mock_time.time.return_value = t0 + 7.0
        reading = device.read_temperatures()
        assert reading.bean_temp is not None
