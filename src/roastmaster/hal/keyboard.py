"""Keyboard input backend for Mac development using pygame key events."""

import pygame

from roastmaster.hal.base import InputEvent, InputState

STEP = 5  # Percentage step per key press
_MIN = 0
_MAX = 100

# Map pygame key constants to InputEvents for simple one-to-one mappings.
# Arrow keys and +/- are handled separately because they also update state.
_KEY_TO_EVENT: dict[int, InputEvent] = {
    pygame.K_F1: InputEvent.CHARGE,
    pygame.K_F2: InputEvent.FIRST_CRACK,
    pygame.K_F3: InputEvent.SECOND_CRACK,
    pygame.K_F4: InputEvent.DROP,
    pygame.K_UP: InputEvent.BURNER_UP,
    pygame.K_DOWN: InputEvent.BURNER_DOWN,
    pygame.K_LEFT: InputEvent.AIR_DOWN,
    pygame.K_RIGHT: InputEvent.AIR_UP,
    pygame.K_PLUS: InputEvent.DRUM_UP,
    pygame.K_EQUALS: InputEvent.DRUM_UP,
    pygame.K_MINUS: InputEvent.DRUM_DOWN,
    pygame.K_h: InputEvent.HEAT_TOGGLE,
    pygame.K_c: InputEvent.COOL_TOGGLE,
    pygame.K_p: InputEvent.ROASTER_PID_TOGGLE,
    pygame.K_LEFTBRACKET: InputEvent.SETPOINT_DOWN,
    pygame.K_RIGHTBRACKET: InputEvent.SETPOINT_UP,
    pygame.K_t: InputEvent.SETPOINT_PREHEAT,
    pygame.K_m: InputEvent.MODE_TOGGLE,
    pygame.K_s: InputEvent.PROFILE_SAVE,
    pygame.K_l: InputEvent.PROFILE_LOAD,
    pygame.K_RETURN: InputEvent.CONFIRM,
    pygame.K_q: InputEvent.QUIT,
    pygame.K_ESCAPE: InputEvent.QUIT,
    pygame.K_F12: InputEvent.HELP_TOGGLE,
    pygame.K_u: InputEvent.UNIT_TOGGLE,
    pygame.K_r: InputEvent.ROAST_RESET,
}

# Events that modify state and the field/direction they affect.
# direction: +1 = up, -1 = down
_STATE_ADJUSTMENTS: dict[InputEvent, tuple[str, int]] = {
    InputEvent.BURNER_UP: ("burner", +1),
    InputEvent.BURNER_DOWN: ("burner", -1),
    InputEvent.DRUM_UP: ("drum", +1),
    InputEvent.DRUM_DOWN: ("drum", -1),
    InputEvent.AIR_UP: ("air", +1),
    InputEvent.AIR_DOWN: ("air", -1),
}


def _clamp(value: int) -> int:
    return max(_MIN, min(_MAX, value))


def map_key_to_event(key: int) -> InputEvent | None:
    """Map a pygame key constant to an InputEvent, or None if unmapped.

    This pure function contains the key-mapping logic and is separated from
    pygame event processing so it can be tested without a running display.
    """
    return _KEY_TO_EVENT.get(key)


class KeyboardInput:
    """Keyboard-driven input backend for development on Mac.

    Processes pygame KEYDOWN events and translates them into InputEvents,
    while maintaining a running InputState that tracks burner/drum/air levels.
    """

    def __init__(self) -> None:
        self._state = InputState()

    def poll_events(self) -> list[InputEvent]:
        """Drain pygame's event queue and return all recognised InputEvents.

        State (burner/drum/air) is updated as a side-effect of adjustment events.
        """
        events: list[InputEvent] = []

        for pg_event in pygame.event.get():
            if pg_event.type == pygame.QUIT:
                events.append(InputEvent.QUIT)
                continue

            if pg_event.type != pygame.KEYDOWN:
                continue

            input_event = map_key_to_event(pg_event.key)
            if input_event is None:
                continue

            events.append(input_event)
            self._apply_adjustment(input_event)

        return events

    def process_key_event(self, key: int) -> InputEvent | None:
        """Process a single key constant (int) and update state.

        Returns the corresponding InputEvent, or None if the key is unmapped.
        This method is useful for testing without a full pygame event loop.
        """
        input_event = map_key_to_event(key)
        if input_event is not None:
            self._apply_adjustment(input_event)
        return input_event

    def _apply_adjustment(self, event: InputEvent) -> None:
        """Update internal state for adjustment events."""
        if event not in _STATE_ADJUSTMENTS:
            return
        field_name, direction = _STATE_ADJUSTMENTS[event]
        current = getattr(self._state, field_name)
        setattr(self._state, field_name, _clamp(current + direction * STEP))

    @property
    def state(self) -> InputState:
        """Current snapshot of control positions."""
        return self._state
