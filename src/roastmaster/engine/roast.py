"""Roast state machine for tracking the roast lifecycle."""

from enum import Enum, auto


class RoastPhase(Enum):
    IDLE = auto()      # No roast in progress
    PREHEAT = auto()   # Warming up the drum before charging beans
    CHARGE = auto()    # Beans just dropped in, temp falling
    ROASTING = auto()  # Main roast phase
    COOLING = auto()   # Heater off, cooling beans
    DONE = auto()      # Roast complete


# Valid transitions: maps current phase to the set of phases it may transition to
_VALID_TRANSITIONS: dict[RoastPhase, set[RoastPhase]] = {
    RoastPhase.IDLE: {RoastPhase.PREHEAT},
    RoastPhase.PREHEAT: {RoastPhase.CHARGE},
    RoastPhase.CHARGE: {RoastPhase.ROASTING},
    RoastPhase.ROASTING: {RoastPhase.COOLING},
    RoastPhase.COOLING: {RoastPhase.DONE},
    RoastPhase.DONE: set(),
}


class RoastStateMachine:
    """Finite state machine tracking the phases of a coffee roast."""

    def __init__(self) -> None:
        self.phase = RoastPhase.IDLE
        self.phase_start_time: float = 0.0   # elapsed time when current phase began
        self.roast_start_time: float = 0.0   # elapsed time when CHARGE happened
        self.elapsed: float = 0.0            # total elapsed time in seconds

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition(self, new_phase: RoastPhase, elapsed: float) -> None:
        """Validate and perform a phase transition."""
        allowed = _VALID_TRANSITIONS.get(self.phase, set())
        if new_phase not in allowed:
            raise ValueError(
                f"Invalid transition: {self.phase.name} -> {new_phase.name}. "
                f"Allowed from {self.phase.name}: "
                f"{[p.name for p in allowed] if allowed else 'none'}"
            )
        self.elapsed = elapsed
        self.phase = new_phase
        self.phase_start_time = elapsed

    # ------------------------------------------------------------------
    # Public transition methods
    # ------------------------------------------------------------------

    def start_preheat(self, elapsed: float) -> None:
        """Transition to PREHEAT."""
        self._transition(RoastPhase.PREHEAT, elapsed)

    def charge(self, elapsed: float) -> None:
        """Mark CHARGE - beans in the drum. Starts the roast timer."""
        self._transition(RoastPhase.CHARGE, elapsed)
        self.roast_start_time = elapsed

    def begin_roasting(self, elapsed: float) -> None:
        """Transition from CHARGE to ROASTING (typically after turning point)."""
        self._transition(RoastPhase.ROASTING, elapsed)

    def start_cooling(self, elapsed: float) -> None:
        """Mark DROP - begin cooling."""
        self._transition(RoastPhase.COOLING, elapsed)

    def finish(self, elapsed: float) -> None:
        """Roast is done."""
        self._transition(RoastPhase.DONE, elapsed)

    def reset(self) -> None:
        """Reset to IDLE for a new roast."""
        self.phase = RoastPhase.IDLE
        self.phase_start_time = 0.0
        self.roast_start_time = 0.0
        self.elapsed = 0.0

    # ------------------------------------------------------------------
    # Derived time properties
    # ------------------------------------------------------------------

    @property
    def roast_elapsed(self) -> float:
        """Seconds since CHARGE (the meaningful roast time)."""
        return self.elapsed - self.roast_start_time

    @property
    def phase_elapsed(self) -> float:
        """Seconds in the current phase."""
        return self.elapsed - self.phase_start_time
