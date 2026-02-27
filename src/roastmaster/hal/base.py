"""Abstract input interface for the Hardware Abstraction Layer."""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Protocol


class InputEvent(Enum):
    """All possible input events from physical buttons/knobs or keyboard simulation."""

    # Roast event buttons
    CHARGE = auto()  # Mark charge (beans in)
    FIRST_CRACK = auto()  # Mark first crack
    SECOND_CRACK = auto()  # Mark second crack
    DROP = auto()  # Mark drop (beans out)

    # Control adjustments
    BURNER_UP = auto()
    BURNER_DOWN = auto()
    DRUM_UP = auto()
    DRUM_DOWN = auto()
    AIR_UP = auto()
    AIR_DOWN = auto()

    # Device toggles (Kaleido: HS/CS)
    HEAT_TOGGLE = auto()  # Toggle heating switch
    COOL_TOGGLE = auto()  # Toggle cooling switch

    # Roaster PID / setpoint (Kaleido: AH/TS)
    ROASTER_PID_TOGGLE = auto()  # Toggle roaster PID (auto heat) mode
    SETPOINT_UP = auto()  # Increase roaster temperature setpoint
    SETPOINT_DOWN = auto()  # Decrease roaster temperature setpoint
    SETPOINT_PREHEAT = auto()  # Set a preheat setpoint

    # Mode
    MODE_TOGGLE = auto()  # Toggle manual/auto

    # Profile
    PROFILE_SAVE = auto()
    PROFILE_LOAD = auto()

    # Navigation (profile browser)
    NAV_UP = auto()
    NAV_DOWN = auto()
    CONFIRM = auto()

    # System
    QUIT = auto()
    HELP_TOGGLE = auto()
    UNIT_TOGGLE = auto()
    ROAST_RESET = auto()


@dataclass
class InputState:
    """Snapshot of current control positions."""

    burner: int = field(default=0)  # 0-100
    drum: int = field(default=50)  # 0-100
    air: int = field(default=50)  # 0-100


class InputBackend(Protocol):
    """Protocol defining the interface all input backends must implement."""

    def poll_events(self) -> list[InputEvent]:
        """Return list of input events since last poll."""
        ...

    @property
    def state(self) -> InputState:
        """Current control state."""
        ...
