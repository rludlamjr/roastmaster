"""Tests for the HAL base definitions and keyboard input backend."""

import pygame

from roastmaster.hal.base import InputEvent, InputState
from roastmaster.hal.keyboard import STEP, KeyboardInput, map_key_to_event

# ---------------------------------------------------------------------------
# InputEvent enum
# ---------------------------------------------------------------------------


class TestInputEvent:
    """Verify the InputEvent enum has all required members."""

    expected_members = [
        "CHARGE",
        "FIRST_CRACK",
        "SECOND_CRACK",
        "DROP",
        "BURNER_UP",
        "BURNER_DOWN",
        "DRUM_UP",
        "DRUM_DOWN",
        "AIR_UP",
        "AIR_DOWN",
        "HEAT_TOGGLE",
        "COOL_TOGGLE",
        "ROASTER_PID_TOGGLE",
        "SETPOINT_UP",
        "SETPOINT_DOWN",
        "SETPOINT_PREHEAT",
        "MODE_TOGGLE",
        "PROFILE_SAVE",
        "PROFILE_LOAD",
        "NAV_UP",
        "NAV_DOWN",
        "CONFIRM",
        "QUIT",
        "HELP_TOGGLE",
        "UNIT_TOGGLE",
        "ROAST_RESET",
    ]

    def test_all_members_present(self):
        actual = {e.name for e in InputEvent}
        for name in self.expected_members:
            assert name in actual, f"InputEvent.{name} is missing"

    def test_member_count(self):
        """Guard against accidentally adding extra members without review."""
        assert len(InputEvent) == len(self.expected_members)

    def test_members_are_unique(self):
        values = [e.value for e in InputEvent]
        assert len(values) == len(set(values))


# ---------------------------------------------------------------------------
# InputState dataclass
# ---------------------------------------------------------------------------


class TestInputState:
    def test_default_burner(self):
        assert InputState().burner == 0

    def test_default_drum(self):
        assert InputState().drum == 50

    def test_default_air(self):
        assert InputState().air == 50

    def test_custom_values(self):
        s = InputState(burner=20, drum=80, air=30)
        assert s.burner == 20
        assert s.drum == 80
        assert s.air == 30


# ---------------------------------------------------------------------------
# KeyboardInput instantiation
# ---------------------------------------------------------------------------


class TestKeyboardInputInstantiation:
    def test_can_be_instantiated(self):
        kb = KeyboardInput()
        assert kb is not None

    def test_initial_state_matches_defaults(self):
        kb = KeyboardInput()
        assert kb.state.burner == 0
        assert kb.state.drum == 50
        assert kb.state.air == 50

    def test_state_is_input_state_instance(self):
        kb = KeyboardInput()
        assert isinstance(kb.state, InputState)


# ---------------------------------------------------------------------------
# Key mapping (pure function, no pygame event loop required)
# ---------------------------------------------------------------------------


class TestMapKeyToEvent:
    """Test map_key_to_event with raw pygame key constants."""

    def test_f1_maps_to_charge(self):
        assert map_key_to_event(pygame.K_F1) is InputEvent.CHARGE

    def test_f2_maps_to_first_crack(self):
        assert map_key_to_event(pygame.K_F2) is InputEvent.FIRST_CRACK

    def test_f3_maps_to_second_crack(self):
        assert map_key_to_event(pygame.K_F3) is InputEvent.SECOND_CRACK

    def test_f4_maps_to_drop(self):
        assert map_key_to_event(pygame.K_F4) is InputEvent.DROP

    def test_up_arrow_maps_to_burner_up(self):
        assert map_key_to_event(pygame.K_UP) is InputEvent.BURNER_UP

    def test_down_arrow_maps_to_burner_down(self):
        assert map_key_to_event(pygame.K_DOWN) is InputEvent.BURNER_DOWN

    def test_left_arrow_maps_to_air_down(self):
        assert map_key_to_event(pygame.K_LEFT) is InputEvent.AIR_DOWN

    def test_right_arrow_maps_to_air_up(self):
        assert map_key_to_event(pygame.K_RIGHT) is InputEvent.AIR_UP

    def test_plus_maps_to_drum_up(self):
        assert map_key_to_event(pygame.K_PLUS) is InputEvent.DRUM_UP

    def test_equals_maps_to_drum_up(self):
        """Equals key is the unshifted plus on most keyboards."""
        assert map_key_to_event(pygame.K_EQUALS) is InputEvent.DRUM_UP

    def test_minus_maps_to_drum_down(self):
        assert map_key_to_event(pygame.K_MINUS) is InputEvent.DRUM_DOWN

    def test_h_maps_to_heat_toggle(self):
        assert map_key_to_event(pygame.K_h) is InputEvent.HEAT_TOGGLE

    def test_c_maps_to_cool_toggle(self):
        assert map_key_to_event(pygame.K_c) is InputEvent.COOL_TOGGLE

    def test_m_maps_to_mode_toggle(self):
        assert map_key_to_event(pygame.K_m) is InputEvent.MODE_TOGGLE

    def test_p_maps_to_roaster_pid_toggle(self):
        assert map_key_to_event(pygame.K_p) is InputEvent.ROASTER_PID_TOGGLE

    def test_left_bracket_maps_to_setpoint_down(self):
        assert map_key_to_event(pygame.K_LEFTBRACKET) is InputEvent.SETPOINT_DOWN

    def test_right_bracket_maps_to_setpoint_up(self):
        assert map_key_to_event(pygame.K_RIGHTBRACKET) is InputEvent.SETPOINT_UP

    def test_t_maps_to_setpoint_preheat(self):
        assert map_key_to_event(pygame.K_t) is InputEvent.SETPOINT_PREHEAT

    def test_s_maps_to_profile_save(self):
        assert map_key_to_event(pygame.K_s) is InputEvent.PROFILE_SAVE

    def test_l_maps_to_profile_load(self):
        assert map_key_to_event(pygame.K_l) is InputEvent.PROFILE_LOAD

    def test_q_maps_to_quit(self):
        assert map_key_to_event(pygame.K_q) is InputEvent.QUIT

    def test_escape_maps_to_quit(self):
        assert map_key_to_event(pygame.K_ESCAPE) is InputEvent.QUIT

    def test_f12_maps_to_help_toggle(self):
        assert map_key_to_event(pygame.K_F12) is InputEvent.HELP_TOGGLE

    def test_return_maps_to_confirm(self):
        assert map_key_to_event(pygame.K_RETURN) is InputEvent.CONFIRM

    def test_u_maps_to_unit_toggle(self):
        assert map_key_to_event(pygame.K_u) is InputEvent.UNIT_TOGGLE

    def test_r_maps_to_roast_reset(self):
        assert map_key_to_event(pygame.K_r) is InputEvent.ROAST_RESET

    def test_unmapped_key_returns_none(self):
        # K_a is not in the mapping
        assert map_key_to_event(pygame.K_a) is None

    def test_another_unmapped_key_returns_none(self):
        assert map_key_to_event(pygame.K_SPACE) is None


# ---------------------------------------------------------------------------
# State adjustment via process_key_event
# ---------------------------------------------------------------------------


class TestStateAdjustment:
    """Test that key presses update state correctly via process_key_event."""

    # --- Burner ---

    def test_burner_up_increases_burner(self):
        kb = KeyboardInput()
        kb.process_key_event(pygame.K_UP)
        assert kb.state.burner == STEP

    def test_burner_down_decreases_burner(self):
        kb = KeyboardInput()
        # Raise first so we have room to go down
        kb.process_key_event(pygame.K_UP)
        kb.process_key_event(pygame.K_UP)
        before = kb.state.burner
        kb.process_key_event(pygame.K_DOWN)
        assert kb.state.burner == before - STEP

    def test_burner_clamps_at_zero(self):
        kb = KeyboardInput()
        # Default burner is 0; pressing down should not go negative
        kb.process_key_event(pygame.K_DOWN)
        assert kb.state.burner == 0

    def test_burner_clamps_at_one_hundred(self):
        kb = KeyboardInput()
        # Press UP enough times to overflow 100
        for _ in range(30):
            kb.process_key_event(pygame.K_UP)
        assert kb.state.burner == 100

    # --- Drum ---

    def test_drum_up_increases_drum(self):
        kb = KeyboardInput()
        before = kb.state.drum
        kb.process_key_event(pygame.K_PLUS)
        assert kb.state.drum == before + STEP

    def test_drum_equals_key_increases_drum(self):
        """Equals (unshifted +) should also increase drum."""
        kb = KeyboardInput()
        before = kb.state.drum
        kb.process_key_event(pygame.K_EQUALS)
        assert kb.state.drum == before + STEP

    def test_drum_down_decreases_drum(self):
        kb = KeyboardInput()
        before = kb.state.drum
        kb.process_key_event(pygame.K_MINUS)
        assert kb.state.drum == before - STEP

    def test_drum_clamps_at_zero(self):
        kb = KeyboardInput()
        for _ in range(30):
            kb.process_key_event(pygame.K_MINUS)
        assert kb.state.drum == 0

    def test_drum_clamps_at_one_hundred(self):
        kb = KeyboardInput()
        for _ in range(30):
            kb.process_key_event(pygame.K_PLUS)
        assert kb.state.drum == 100

    # --- Air ---

    def test_air_up_increases_air(self):
        kb = KeyboardInput()
        before = kb.state.air
        kb.process_key_event(pygame.K_RIGHT)
        assert kb.state.air == before + STEP

    def test_air_down_decreases_air(self):
        kb = KeyboardInput()
        before = kb.state.air
        kb.process_key_event(pygame.K_LEFT)
        assert kb.state.air == before - STEP

    def test_air_clamps_at_zero(self):
        kb = KeyboardInput()
        for _ in range(30):
            kb.process_key_event(pygame.K_LEFT)
        assert kb.state.air == 0

    def test_air_clamps_at_one_hundred(self):
        kb = KeyboardInput()
        for _ in range(30):
            kb.process_key_event(pygame.K_RIGHT)
        assert kb.state.air == 100

    # --- Non-adjustment keys do not change state ---

    def test_non_adjustment_key_does_not_change_state(self):
        kb = KeyboardInput()
        before = InputState(
            burner=kb.state.burner, drum=kb.state.drum, air=kb.state.air
        )
        kb.process_key_event(pygame.K_F1)  # CHARGE — not an adjustment
        assert kb.state.burner == before.burner
        assert kb.state.drum == before.drum
        assert kb.state.air == before.air

    def test_unmapped_key_does_not_change_state(self):
        kb = KeyboardInput()
        before = InputState(
            burner=kb.state.burner, drum=kb.state.drum, air=kb.state.air
        )
        kb.process_key_event(pygame.K_a)
        assert kb.state.burner == before.burner
        assert kb.state.drum == before.drum
        assert kb.state.air == before.air


# ---------------------------------------------------------------------------
# poll_events with mock pygame events
# ---------------------------------------------------------------------------


class MockKeyEvent:
    """Minimal fake pygame KEYDOWN event for use in poll_events tests."""

    def __init__(self, key: int) -> None:
        self.type = pygame.KEYDOWN
        self.key = key


class MockQuitEvent:
    """Minimal fake pygame QUIT event."""

    def __init__(self) -> None:
        self.type = pygame.QUIT


class TestPollEvents:
    """Test poll_events by injecting events directly into pygame's queue."""

    def _post(self, *events) -> None:
        """Post mock-compatible events into pygame's event queue."""
        for ev in events:
            pygame.event.post(pygame.event.Event(ev.type, {"key": getattr(ev, "key", 0)}))

    def test_poll_returns_charge_for_f1(self):
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        kb = KeyboardInput()
        result = kb.poll_events()
        assert InputEvent.CHARGE in result

    def test_poll_returns_quit_for_escape(self):
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
        kb = KeyboardInput()
        result = kb.poll_events()
        assert InputEvent.QUIT in result

    def test_poll_returns_quit_for_pygame_quit_event(self):
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.QUIT))
        kb = KeyboardInput()
        result = kb.poll_events()
        assert InputEvent.QUIT in result

    def test_poll_updates_state_via_arrow_key(self):
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_UP))
        kb = KeyboardInput()
        kb.poll_events()
        assert kb.state.burner == STEP

    def test_poll_ignores_unmapped_keys(self):
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_a))
        kb = KeyboardInput()
        result = kb.poll_events()
        assert result == []

    def test_poll_returns_empty_list_when_no_events(self):
        pygame.event.clear()
        kb = KeyboardInput()
        result = kb.poll_events()
        assert result == []

    def test_poll_handles_multiple_events(self):
        pygame.event.clear()
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F1))
        pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_F2))
        kb = KeyboardInput()
        result = kb.poll_events()
        assert InputEvent.CHARGE in result
        assert InputEvent.FIRST_CRACK in result
