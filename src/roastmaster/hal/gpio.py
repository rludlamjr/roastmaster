"""GPIO input backend for Raspberry Pi hardware.

This module is a stub placeholder. It will be implemented once the physical
Pi hardware (buttons, rotary encoders, etc.) is wired and ready for testing.
All methods raise NotImplementedError to make it obvious when this backend is
used before the implementation is complete.
"""

from roastmaster.hal.base import InputEvent, InputState


class GPIOInput:
    """Raspberry Pi GPIO input backend.

    Reads physical button presses and rotary encoder positions via RPi.GPIO
    and translates them into InputEvents.  Not yet implemented — will be
    built when Pi hardware is available.
    """

    def poll_events(self) -> list[InputEvent]:
        """Return list of input events since last poll.

        Not yet implemented.
        """
        raise NotImplementedError("GPIO backend is not yet implemented.")

    @property
    def state(self) -> InputState:
        """Current control state read from hardware encoders.

        Not yet implemented.
        """
        raise NotImplementedError("GPIO backend is not yet implemented.")
