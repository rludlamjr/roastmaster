"""Hybrid input backend — merges keyboard and GPIO inputs.

When running with --gpio, this compositor reads events from both the
keyboard (for roast-event keys like F1=CHARGE that have no physical button)
and GPIO (for toggle switches and potentiometers). Pot state always comes
from GPIO when available, since that's the physical ground truth.
"""

from __future__ import annotations

from roastmaster.hal.base import InputEvent, InputState


class HybridInput:
    """Compositor that merges events from keyboard and GPIO backends.

    Both backends are duck-typed (poll_events, state, optional close).
    """

    def __init__(self, keyboard: object, gpio: object) -> None:
        self._keyboard = keyboard
        self._gpio = gpio

    def poll_events(self) -> list[InputEvent]:
        """Poll both backends and merge their event lists."""
        events: list[InputEvent] = []
        events.extend(self._gpio.poll_events())  # type: ignore[union-attr]
        events.extend(self._keyboard.poll_events())  # type: ignore[union-attr]
        return events

    @property
    def state(self) -> InputState:
        """Pot state from GPIO (ground truth for physical controls)."""
        return self._gpio.state  # type: ignore[union-attr]

    def close(self) -> None:
        """Shut down the GPIO backend."""
        if hasattr(self._gpio, "close"):
            self._gpio.close()  # type: ignore[union-attr]
