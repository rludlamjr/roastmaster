"""Roast event management: manual marks and auto-detection of key moments."""

from dataclasses import dataclass
from enum import Enum, auto


class EventType(Enum):
    CHARGE = auto()
    TURNING_POINT = auto()   # Auto-detected: first BT minimum after charge
    DRY_END = auto()         # Optional manual mark
    FIRST_CRACK = auto()
    SECOND_CRACK = auto()
    DROP = auto()


@dataclass
class RoastEvent:
    event_type: EventType
    elapsed: float      # seconds since charge
    temperature: float  # BT at event time


# Number of consecutive rising readings required to confirm turning point
_TP_CONFIRM_READINGS = 3
# A real turning point follows the charge dip: BT must have fallen at least this
# far below its post-charge high, and not in the first few seconds. Without this,
# BT still creeping up for a moment after CHARGE (steady preheat, probe lag) was
# taken as a turning point at 0:00.
_TP_MIN_DIP_F = 15.0
_TP_MIN_DELAY_S = 10.0


class EventManager:
    """Tracks key events during a roast, including auto-detection of turning point."""

    def __init__(self) -> None:
        self.events: list[RoastEvent] = []
        self._bt_history: list[tuple[float, float]] = []  # (elapsed, bt)
        self._tp_detected = False
        # Track consecutive readings that are higher than the candidate minimum
        self._tp_candidate: tuple[float, float] | None = None  # (elapsed, bt) of candidate min
        self._rising_count = 0

    def mark_event(
        self, event_type: EventType, elapsed: float, temperature: float
    ) -> RoastEvent:
        """Manually mark an event.

        If an event of the same type already exists, the existing record is
        replaced by the new one (last-write-wins).
        """
        event = RoastEvent(event_type=event_type, elapsed=elapsed, temperature=temperature)
        # Replace any existing event of this type
        self.events = [e for e in self.events if e.event_type != event_type]
        self.events.append(event)
        return event

    def update_bt(self, elapsed: float, bt: float) -> RoastEvent | None:
        """Feed BT data for auto-detection.

        Returns a RoastEvent if a turning point is detected, otherwise None.
        The turning point is the first local minimum of bean temperature after
        CHARGE: BT must fall to a minimum then rise for at least
        _TP_CONFIRM_READINGS consecutive readings before the TP is confirmed.
        """
        if self._tp_detected:
            return None

        self._bt_history.append((elapsed, bt))

        if len(self._bt_history) < 2:
            return None

        prev_elapsed, prev_bt = self._bt_history[-2]

        if self._tp_candidate is None:
            # Still descending: update candidate whenever we see a new minimum
            if bt <= prev_bt:
                # Temperature still falling or flat — current point is our best candidate
                self._tp_candidate = (elapsed, bt)
                self._rising_count = 0
            else:
                # First rise: make the previous point the candidate
                self._tp_candidate = (prev_elapsed, prev_bt)
                self._rising_count = 1
        else:
            if bt > self._bt_history[-2][1]:
                # Still rising
                self._rising_count += 1
            else:
                # Fell back again — reset candidate to this new low
                self._tp_candidate = (elapsed, bt)
                self._rising_count = 0

        if self._rising_count >= _TP_CONFIRM_READINGS and self._tp_candidate is not None:
            tp_elapsed, tp_bt = self._tp_candidate
            start_elapsed = self._bt_history[0][0]
            peak_bt = max(t for _, t in self._bt_history)
            if tp_bt > peak_bt - _TP_MIN_DIP_F or tp_elapsed - start_elapsed < _TP_MIN_DELAY_S:
                # Not the charge dip yet (e.g. BT still creeping up just after CHARGE)
                self._tp_candidate = None
                self._rising_count = 0
                return None
            self._tp_detected = True
            return self.mark_event(EventType.TURNING_POINT, tp_elapsed, tp_bt)

        return None

    def get_event(self, event_type: EventType) -> RoastEvent | None:
        """Get a specific event if it has been recorded."""
        for event in self.events:
            if event.event_type == event_type:
                return event
        return None

    def reset(self) -> None:
        """Clear all events for a new roast."""
        self.events = []
        self._bt_history = []
        self._tp_detected = False
        self._tp_candidate = None
        self._rising_count = 0


# A late CHARGE press: cold beans make BT plunge (several degrees per second),
# which a preheat drifting up or down never does. The plunge must also have
# dropped BT by at least _LATE_CHARGE_MIN_DROP_F by the time CHARGE is pressed.
_LATE_CHARGE_MIN_DROP_F = 20.0
_LATE_CHARGE_PLUNGE_F_PER_S = 3.0  # ~1.7 C/s; charging is ~4 C/s, preheat drift ~0.05
_LATE_CHARGE_WINDOW_S = 120.0


def find_charge_drop(
    history: list[tuple[float, float]],
    *,
    min_drop_f: float = _LATE_CHARGE_MIN_DROP_F,
    plunge_f_per_s: float = _LATE_CHARGE_PLUNGE_F_PER_S,
    window_s: float = _LATE_CHARGE_WINDOW_S,
) -> tuple[float, float] | None:
    """When CHARGE is pressed after the beans went in, find when they really did.

    ``history`` is (elapsed, bt_f) up to now. Looks in the last ``window_s``
    seconds for the start of a charge plunge (BT falling faster than
    ``plunge_f_per_s``) after which BT ended up at least ``min_drop_f`` lower.
    Returns the (elapsed, bt_f) of the reading just before the plunge, or None
    when CHARGE was pressed on time.
    """
    if len(history) < 3:
        return None
    now_t, now_bt = history[-1]
    recent = [p for p in history if p[0] >= now_t - window_s]
    for (t0, bt0), (t1, bt1) in zip(recent, recent[1:], strict=False):
        dt = t1 - t0
        if dt <= 0:
            continue
        if (bt0 - bt1) / dt >= plunge_f_per_s and bt0 - now_bt >= min_drop_f:
            return t0, bt0
    return None
