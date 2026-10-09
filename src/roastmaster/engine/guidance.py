"""Live burner / air / drum guidance from a coffee plan.

A plan's ``controls`` list says what the knobs should be at each point of the
roast, keyed to bean temperature rather than the clock::

    [{"at": "charge", "burner": 70, "air": 30, "drum": 90},
     {"bt_c": 150, "burner": 60, "air": 40},           # dry end
     {"bt_c": 165, "burner": 52, "air": 50},
     {"bt_c": 178, "burner": 45},
     {"at": "fc", "burner": 40, "air": 55},
     {"at": "fc", "after_s": 30, "burner": 35}]

Keying to BT adapts to running ahead or behind for free: a slow roast reaches
165 C later, so its step comes later. Two more adjustments make it usable on
a roaster whose RoR answers a burner change ~45-60 s later:

* **Lead.** A BT step is due when BT *projected* ``LEAD_S`` seconds ahead at
  the current RoR reaches the step temperature, so the change has taken
  effect by the time the beans get there.
* **RoR correction.** From dry end on, actual RoR is compared with the plan's
  RoR *at the same bean temperature*; running hot lowers the target burner
  (about ``GAIN`` points per C/min), running cold raises it. Near first crack
  the correction may only lower the burner: adding heat late is what makes
  development run hot.

Everything here is Celsius and seconds since CHARGE.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LEAD_S = 45.0          # machine lag to anticipate
GAIN = 3.0             # burner points per C/min of RoR error
DEAD_BAND_C = 0.75     # ignore RoR errors smaller than this (C/min)
MAX_CUT = 15.0         # largest correction downward (points)
MAX_ADD = 8.0          # largest correction upward (points)
# After first crack RoR keeps falling on its own and earlier cuts are still
# landing; chasing the lagging RoR hard is what causes crashes.
GAIN_AFTER_FC = 2.0
MAX_CUT_AFTER_FC = 10.0
MIN_BURNER = 20.0
SMOOTH_TAU_S = 25.0    # time constant for smoothing the correction
NO_ADD_BEFORE_FC_C = 25.0  # within this many C of planned FC, never add heat
DRY_END_C = 150.0

CHANNELS = ("burner", "air", "drum")


@dataclass(frozen=True)
class ControlStep:
    trigger: str               # "charge" | "bt" | "fc"
    bt_c: float | None = None  # for "bt"
    after_s: float = 0.0       # for "fc": seconds after first crack
    burner: float | None = None
    air: float | None = None
    drum: float | None = None

    @classmethod
    def from_dict(cls, d: dict) -> ControlStep:
        if "bt_c" in d:
            trigger = "bt"
        elif d.get("at") in ("charge", "fc"):
            trigger = d["at"]
        else:
            raise ValueError(f"control step needs 'bt_c' or 'at': charge|fc, got {d}")
        def num(k: str) -> float | None:
            return float(d[k]) if d.get(k) is not None else None
        return cls(trigger=trigger, bt_c=num("bt_c"), after_s=float(d.get("after_s", 0)),
                   burner=num("burner"), air=num("air"), drum=num("drum"))


def parse_controls(raw: list[dict] | None) -> list[ControlStep]:
    return [ControlStep.from_dict(d) for d in (raw or [])]


@dataclass
class Guidance:
    """Where the knobs should be now, and what changes next."""

    burner: float | None = None       # target, including the RoR correction
    air: float | None = None
    drum: float | None = None
    scheduled_burner: float | None = None  # target before the correction
    correction: float = 0.0
    next_change: dict = field(default_factory=dict)  # channel -> value for the next step
    next_in_s: float | None = None    # seconds until the next step is due

    def target(self, channel: str) -> float | None:
        return getattr(self, channel)


def plan_ror_by_bt(
    curve: list[tuple[float, float, float]], tp_s: float
) -> list[tuple[float, float]]:
    """(bt_c, ror_c) pairs after the turning point, BT increasing."""
    out: list[tuple[float, float]] = []
    for t, bt, ror in curve:
        if t > tp_s and (not out or bt > out[-1][0]):
            out.append((bt, ror))
    return out


def _interp(pairs: list[tuple[float, float]], x: float) -> float | None:
    if not pairs:
        return None
    if x <= pairs[0][0]:
        return pairs[0][1]
    for (x0, y0), (x1, y1) in zip(pairs, pairs[1:], strict=False):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pairs[-1][1]


def compute_guidance(
    steps: list[ControlStep],
    *,
    charged: bool,
    dropped: bool,
    t: float,
    bt_c: float | None,
    ror_c: float | None,
    tp_passed: bool,
    fc_t: float | None,
    fc_bt_plan_c: float,
    plan_ror: list[tuple[float, float]],
    lead_s: float = LEAD_S,
) -> Guidance | None:
    """Targets for this moment. ``fc_t`` is first crack's time since charge, if marked."""
    if not steps or dropped:
        return None
    g = Guidance()

    if not charged:
        # Before charge: show the settings to charge with
        for s in steps:
            if s.trigger == "charge":
                g.burner, g.air, g.drum = s.burner, s.air, s.drum
        g.scheduled_burner = g.burner
        return g

    ror = max(ror_c or 0.0, 0.0)
    projected = (bt_c or 0.0) + ror * lead_s / 60.0

    def due(s: ControlStep) -> bool:
        if s.trigger == "charge":
            return True
        if not tp_passed or bt_c is None:
            return False
        if s.trigger == "bt":
            return projected >= (s.bt_c or 0.0)
        # first crack: the marked event, or the planned FC temperature if not marked yet
        if fc_t is not None:
            return t >= fc_t + s.after_s  # already timed from first crack: no extra lead
        # Not marked yet: the FC step itself is anticipated from the planned FC
        # temperature; steps timed *after* FC wait for the FCS press.
        return s.after_s == 0 and projected >= fc_bt_plan_c

    def eta(s: ControlStep) -> float | None:
        if s.trigger == "fc" and fc_t is not None:
            return max(0.0, fc_t + s.after_s - t)
        if s.trigger == "fc" and s.after_s:
            return None  # waits for first crack to be marked
        target_bt = s.bt_c if s.trigger == "bt" else fc_bt_plan_c
        if target_bt is None or ror < 0.5 or not tp_passed:
            return None
        return max(0.0, (target_bt - projected) / (ror / 60.0))

    for s in steps:
        if due(s):
            for ch in CHANNELS:
                if getattr(s, ch) is not None:
                    setattr(g, ch, getattr(s, ch))
        else:
            g.next_change = {ch: getattr(s, ch) for ch in CHANNELS if getattr(s, ch) is not None}
            g.next_in_s = eta(s)
            break
    g.scheduled_burner = g.burner

    # RoR correction, from dry end on
    if (g.burner is not None and tp_passed and bt_c is not None and ror_c is not None
            and bt_c >= DRY_END_C):
        planned = _interp(plan_ror, bt_c)
        if planned is not None:
            err = ror_c - planned  # positive = running hot
            if abs(err) >= DEAD_BAND_C:
                after_fc = fc_t is not None
                gain = GAIN_AFTER_FC if after_fc else GAIN
                cut = MAX_CUT_AFTER_FC if after_fc else MAX_CUT
                corr = max(-cut, min(MAX_ADD, -gain * err))
                if bt_c >= fc_bt_plan_c - NO_ADD_BEFORE_FC_C or after_fc:
                    corr = min(corr, 0.0)
                g.correction = corr
                g.burner = _clamp_burner(g.burner + corr)
    return g


def _clamp_burner(value: float) -> float:
    return max(MIN_BURNER, min(100.0, value))


class GuidanceTracker:
    """compute_guidance() with the RoR correction smoothed over time.

    RoR is noisy second to second; an unsmoothed correction makes the target
    jump around. Feed it once per sample.
    """

    def __init__(self, steps: list[ControlStep], plan_ror: list[tuple[float, float]],
                 fc_bt_plan_c: float, tau_s: float = SMOOTH_TAU_S) -> None:
        self.steps = steps
        self.plan_ror = plan_ror
        self.fc_bt_plan_c = fc_bt_plan_c
        self.tau_s = tau_s
        self._corr = 0.0
        self._last_t: float | None = None

    def reset(self) -> None:
        self._corr = 0.0
        self._last_t = None

    def update(self, *, charged: bool, dropped: bool, t: float, bt_c: float | None,
               ror_c: float | None, tp_passed: bool, fc_t: float | None) -> Guidance | None:
        g = compute_guidance(self.steps, charged=charged, dropped=dropped, t=t, bt_c=bt_c,
                             ror_c=ror_c, tp_passed=tp_passed, fc_t=fc_t,
                             fc_bt_plan_c=self.fc_bt_plan_c, plan_ror=self.plan_ror)
        if g is None or not charged:
            self.reset()
            return g
        dt = 1.0 if self._last_t is None else max(0.0, t - self._last_t)
        self._last_t = t
        self._corr += (g.correction - self._corr) * min(1.0, dt / self.tau_s)
        g.correction = round(self._corr)
        if g.scheduled_burner is not None:
            g.burner = _clamp_burner(g.scheduled_burner + g.correction)
        return g


def coach_text(g: Guidance | None, burner: float, air: float) -> str:
    """One short CRT line: what to do now, or what's coming."""
    if g is None:
        return ""
    if g.burner is not None and abs(burner - g.burner) >= 5:
        return f"BURN TO {g.burner:.0f}% NOW"
    if g.air is not None and abs(air - g.air) >= 10:
        return f"AIR TO {g.air:.0f}% NOW"
    nxt = g.next_change
    if g.next_in_s is not None and g.next_in_s <= 30 and nxt:
        what = (f"BURN {nxt['burner']:.0f}%" if "burner" in nxt
                else f"AIR {nxt['air']:.0f}%" if "air" in nxt else "")
        if what:
            s = int(round(g.next_in_s))
            return f"{what} IN {s // 60}:{s % 60:02d}"
    return ""
