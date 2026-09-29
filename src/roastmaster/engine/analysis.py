"""Roast phase analysis: phase splits, development metrics and diagnostics.

Pure functions over the recorded samples and events of a roast.  Works both
live (no DROP yet — the analysis answers "what if I dropped right now?") and
after the roast is finished.

Phases (times relative to CHARGE):

    DRYING      CHARGE   -> DRY END   (DRY END auto-detected at a BT threshold
                                       unless marked manually)
    MAILLARD    DRY END  -> FIRST CRACK
    DEVELOPMENT FIRST CRACK -> DROP

All temperatures are Fahrenheit internally, like the rest of the engine.
Targets are expressed in Celsius (the roaster is set up in C) and converted.
``RoastAnalysis.to_dict()`` produces a Celsius summary for logs and export.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from roastmaster.display.units import c_to_f, f_to_c, f_to_c_delta

# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Targets:
    """Target ranges used to flag a roast.

    Defaults are starting points for light roasts for espresso on a Kaleido
    M1 Lite with ~170 g batches.  The M1's bean probe reads low (first crack
    typically shows ~180-190 C), so absolute temperature targets are kept
    loose and most checks are on times, ratios and RoR shape instead.
    Tune these once you have a few roasts logged against tasting notes.
    """

    dry_end_c: float = 150.0                          # BT that ends drying
    total_time_s: tuple[float, float] = (480.0, 630.0)  # 8:00 - 10:30
    dtr_pct: tuple[float, float] = (16.0, 22.0)
    dev_time_s: tuple[float, float] = (70.0, 120.0)
    dev_delta_c: tuple[float, float] = (8.0, 15.0)    # drop BT - FC BT
    drying_pct: tuple[float, float] = (35.0, 50.0)
    ror_fc_c: tuple[float, float] = (6.0, 12.0)       # C/min at first crack
    ror_drop_c: tuple[float, float] = (2.5, 7.0)      # C/min at drop
    weight_loss_pct: tuple[float, float] = (12.0, 14.5)
    # RoR crash: falls by more than this fraction within crash_window_s of FC
    crash_fraction: float = 0.5
    crash_min_drop_c: float = 2.0                     # ignore tiny absolute drops
    crash_window_s: float = 60.0
    # RoR flick: rises this much above its running minimum after peaking
    flick_rise_c: float = 1.5


DEFAULT_TARGETS = Targets()


@dataclass
class PlanTargets:
    """A coffee's planned roast (see profiles/coffees.py), in engine units (F)."""

    curve: list[tuple[float, float, float]]  # (t_s since charge, bt_f, ror_f)
    tp_s: float
    dry_end_s: float
    fc_s: float
    fc_bt_f: float
    drop_s: float
    drop_bt_f: float
    charge_bt_f: float
    label: str = ""

    def at(self, t: float) -> tuple[float, float] | None:
        """Planned (bt_f, ror_f) at time t, or None outside the plan."""
        if not self.curve or t < 0 or t > self.curve[-1][0]:
            return None
        i = min(int(round(t)), len(self.curve) - 1)
        _, bt, ror = self.curve[i]
        return bt, ror

    @property
    def dtr_pct(self) -> float:
        return (self.drop_s - self.fc_s) / self.drop_s * 100.0 if self.drop_s else 0.0

# Window (seconds) for the least-squares RoR used by the analysis.
_ROR_SPAN_S = 30.0


# ---------------------------------------------------------------------------
# Input protocols (ProfileSample / ProfileEvent / RoastEvent all satisfy these)
# ---------------------------------------------------------------------------


class _Sample(Protocol):
    elapsed: float
    bt: float
    burner: float


class _Event(Protocol):
    elapsed: float
    temperature: float

    @property
    def event_type(self) -> Any: ...


def _event_name(event: _Event) -> str:
    et = event.event_type
    return str(getattr(et, "name", et))


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class EventPoint:
    time_s: float  # seconds since CHARGE
    bt_f: float


@dataclass
class PhaseStats:
    name: str
    start_s: float
    end_s: float
    start_bt_f: float
    end_bt_f: float
    pct: float | None = None
    avg_ror_f: float | None = None
    avg_burner: float | None = None

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass
class Finding:
    level: str   # "bad" | "warn" | "info" | "good"
    short: str   # CRT-friendly (<= 34 chars, glyph-safe)
    detail: str  # full explanation for web / email


@dataclass
class RoastAnalysis:
    charged: bool = False
    live: bool = True          # True until DROP is marked
    end_s: float = 0.0         # DROP time, or "now" when live
    end_bt_f: float | None = None
    charge_bt_f: float | None = None
    turning_point: EventPoint | None = None
    dry_end: EventPoint | None = None
    dry_end_auto: bool = False
    first_crack: EventPoint | None = None
    second_crack: EventPoint | None = None
    drop: EventPoint | None = None
    phases: list[PhaseStats] = field(default_factory=list)
    current_phase: str = ""    # "DRYING" | "MAILLARD" | "DEVELOPMENT" | ""
    dtr_pct: float | None = None
    dev_time_s: float | None = None
    dev_delta_f: float | None = None
    ror_fc_f: float | None = None
    ror_end_f: float | None = None
    ror_peak_f: float | None = None
    ror_min_after_fc_f: float | None = None
    crash: bool = False
    flick_times_s: list[float] = field(default_factory=list)
    weight_loss_pct: float | None = None
    # metric key -> "ok" | "low" | "high"
    status: dict[str, str] = field(default_factory=dict)
    findings: list[Finding] = field(default_factory=list)
    # Per-sample (time_s, ror_f) curve used by the analysis (for charts)
    ror_curve: list[tuple[float, float]] = field(default_factory=list)
    # Comparison with the coffee's plan (positive = hotter / later than plan)
    plan: PlanTargets | None = None
    bt_vs_plan_f: float | None = None
    ror_vs_plan_f: float | None = None
    dry_end_vs_plan_s: float | None = None
    fc_vs_plan_s: float | None = None
    drop_vs_plan_s: float | None = None

    def phase(self, name: str) -> PhaseStats | None:
        for p in self.phases:
            if p.name == name:
                return p
        return None

    # -- Serialisation (Celsius, rounded, flat-ish for logs/CSV) -----------

    def to_dict(self) -> dict:
        def c(v: float | None) -> float | None:
            return round(f_to_c(v), 1) if v is not None else None

        def cd(v: float | None) -> float | None:
            return round(f_to_c_delta(v), 1) if v is not None else None

        def ev(p: EventPoint | None) -> dict | None:
            if p is None:
                return None
            return {"time_s": round(p.time_s, 1), "bt_c": c(p.bt_f)}

        return {
            "charged": self.charged,
            "live": self.live,
            "total_time_s": round(self.end_s, 1),
            "charge_bt_c": c(self.charge_bt_f),
            "end_bt_c": c(self.end_bt_f),
            "turning_point": ev(self.turning_point),
            "dry_end": ev(self.dry_end),
            "dry_end_auto": self.dry_end_auto,
            "first_crack": ev(self.first_crack),
            "second_crack": ev(self.second_crack),
            "drop": ev(self.drop),
            "phases": [
                {
                    "name": p.name,
                    "start_s": round(p.start_s, 1),
                    "end_s": round(p.end_s, 1),
                    "duration_s": round(p.duration_s, 1),
                    "pct": round(p.pct, 1) if p.pct is not None else None,
                    "start_bt_c": c(p.start_bt_f),
                    "end_bt_c": c(p.end_bt_f),
                    "avg_ror_c": cd(p.avg_ror_f),
                    "avg_burner": round(p.avg_burner, 1) if p.avg_burner is not None else None,
                }
                for p in self.phases
            ],
            "dtr_pct": round(self.dtr_pct, 1) if self.dtr_pct is not None else None,
            "dev_time_s": round(self.dev_time_s, 1) if self.dev_time_s is not None else None,
            "dev_delta_c": cd(self.dev_delta_f),
            "ror_fc_c": cd(self.ror_fc_f),
            "ror_drop_c": cd(self.ror_end_f),
            "ror_peak_c": cd(self.ror_peak_f),
            "ror_min_after_fc_c": cd(self.ror_min_after_fc_f),
            "crash": self.crash,
            "flick_times_s": [round(t, 1) for t in self.flick_times_s],
            "weight_loss_pct": (
                round(self.weight_loss_pct, 1) if self.weight_loss_pct is not None else None
            ),
            "status": dict(self.status),
            "vs_plan": None if self.plan is None else {
                "bt_c": cd(self.bt_vs_plan_f),
                "ror_c": cd(self.ror_vs_plan_f),
                "dry_end_s": self.dry_end_vs_plan_s,
                "fc_s": self.fc_vs_plan_s,
                "drop_s": self.drop_vs_plan_s,
            },
            "findings": [
                {"level": f.level, "short": f.short, "detail": f.detail} for f in self.findings
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def fmt_time(seconds: float | None) -> str:
    """Format seconds as M:SS (or '--' for None)."""
    if seconds is None:
        return "--"
    s = int(round(max(0.0, seconds)))
    return f"{s // 60}:{s % 60:02d}"


def _ror_curve(points: list[tuple[float, float]], span_s: float) -> list[tuple[float, float]]:
    """Least-squares slope (deg/min) over a centred window at each point.

    The window is truncated at the ends of the data, so the final values are
    trailing — the same view a live roaster sees.
    """
    out: list[tuple[float, float]] = []
    n = len(points)
    half = span_s / 2.0
    lo = 0
    hi = 0
    for i in range(n):
        t = points[i][0]
        while lo < n and points[lo][0] < t - half:
            lo += 1
        while hi < n and points[hi][0] <= t + half:
            hi += 1
        window = points[lo:hi]
        if len(window) < 5 or window[-1][0] - window[0][0] < span_s * 0.4:
            continue
        mt = sum(p[0] for p in window) / len(window)
        mb = sum(p[1] for p in window) / len(window)
        num = sum((p[0] - mt) * (p[1] - mb) for p in window)
        den = sum((p[0] - mt) ** 2 for p in window)
        if den > 0:
            out.append((t, num / den * 60.0))
    return out


def _value_at(curve: list[tuple[float, float]], t: float) -> float | None:
    """Value of the curve point nearest to time t."""
    if not curve:
        return None
    best = min(curve, key=lambda p: abs(p[0] - t))
    return best[1] if abs(best[0] - t) <= _ROR_SPAN_S else None


def _bt_at(points: list[tuple[float, float]], t: float) -> float:
    return min(points, key=lambda p: abs(p[0] - t))[1]


def _classify(value: float | None, rng: tuple[float, float]) -> str | None:
    if value is None:
        return None
    if value < rng[0]:
        return "low"
    if value > rng[1]:
        return "high"
    return "ok"


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def analyze_roast(
    samples: list[_Sample],
    events: list[_Event],
    *,
    now: float | None = None,
    targets: Targets = DEFAULT_TARGETS,
    green_weight_g: float | None = None,
    roasted_weight_g: float | None = None,
    plan: PlanTargets | None = None,
) -> RoastAnalysis:
    """Analyse a roast.

    Parameters
    ----------
    samples, events:
        Recorded data.  ``elapsed`` values are on the session clock (not
        relative to CHARGE); the CHARGE event anchors them.
    now:
        Session clock "now" for live analysis.  Defaults to the last sample.
    """
    result = RoastAnalysis()
    ev = {_event_name(e): e for e in events}

    charge = ev.get("CHARGE")
    if charge is None or not samples:
        return result
    t0 = charge.elapsed
    result.charged = True
    result.charge_bt_f = charge.temperature

    drop = ev.get("DROP")
    if drop is not None:
        result.live = False
        end_s = drop.elapsed - t0
    else:
        end_clock = now if now is not None else samples[-1].elapsed
        end_s = end_clock - t0

    # Samples within the roast window, relative to charge
    rel = [s for s in samples if 0.0 <= s.elapsed - t0 <= end_s + 0.5]
    points = [(s.elapsed - t0, s.bt) for s in rel]
    if len(points) < 2:
        return result
    end_s = max(end_s, 0.0)
    result.end_s = end_s
    result.end_bt_f = drop.temperature if drop is not None else points[-1][1]

    def rel_point(name: str) -> EventPoint | None:
        e = ev.get(name)
        if e is None or e.elapsed - t0 > end_s + 0.5:
            return None
        return EventPoint(e.elapsed - t0, e.temperature)

    result.first_crack = rel_point("FIRST_CRACK")
    result.second_crack = rel_point("SECOND_CRACK")
    if drop is not None:
        result.drop = EventPoint(end_s, drop.temperature)

    # Turning point: marked/auto-detected event, else the BT minimum in the first 3 min
    tp = rel_point("TURNING_POINT")
    if tp is None:
        early = [p for p in points if p[0] <= 180.0]
        if early:
            t_min, bt_min = min(early, key=lambda p: p[1])
            # Only trust it once BT has clearly started rising again
            if points[-1][1] > bt_min + 2.0 and t_min > 0:
                tp = EventPoint(t_min, bt_min)
    result.turning_point = tp

    # Dry end: marked event, else first crossing of the threshold after TP
    dry_end = rel_point("DRY_END")
    if dry_end is None:
        threshold = c_to_f(targets.dry_end_c)
        after = tp.time_s if tp is not None else 30.0
        for t, bt in points:
            if t > after and bt >= threshold:
                dry_end = EventPoint(t, bt)
                result.dry_end_auto = True
                break
    result.dry_end = dry_end

    # RoR curve and derived values
    curve = _ror_curve(points, _ROR_SPAN_S)
    result.ror_curve = curve
    after_tp = [r for t, r in curve if tp is not None and t >= tp.time_s]
    result.ror_peak_f = max(after_tp) if after_tp else None
    result.ror_end_f = curve[-1][1] if curve else None

    # Phases
    fc = result.first_crack
    bounds: list[tuple[str, float, float | None]] = []
    de_t = dry_end.time_s if dry_end is not None else None
    fc_t = fc.time_s if fc is not None else None
    bounds.append(("DRYING", 0.0, de_t if de_t is not None else (fc_t if fc_t else end_s)))
    if de_t is not None:
        bounds.append(("MAILLARD", de_t, fc_t if fc_t is not None else end_s))
    if fc_t is not None:
        bounds.append(("DEVELOPMENT", fc_t, end_s))

    for name, start, stop in bounds:
        stop = end_s if stop is None else stop
        seg = [s for s in rel if start <= s.elapsed - t0 <= stop]
        # RoR before the turning point is just the charge dip — leave it out
        ror_from = max(start, tp.time_s) if tp is not None else start
        seg_ror = [r for t, r in curve if ror_from <= t <= stop]
        start_bt = charge.temperature if start == 0.0 else _bt_at(points, start)
        result.phases.append(
            PhaseStats(
                name=name,
                start_s=start,
                end_s=stop,
                start_bt_f=start_bt,
                end_bt_f=_bt_at(points, stop),
                pct=(stop - start) / end_s * 100.0 if end_s > 0 else None,
                avg_ror_f=sum(seg_ror) / len(seg_ror) if seg_ror else None,
                avg_burner=sum(s.burner for s in seg) / len(seg) if seg else None,
            )
        )
    result.current_phase = result.phases[-1].name if result.phases else ""

    # Development metrics
    if fc is not None:
        result.dev_time_s = end_s - fc.time_s
        result.dtr_pct = result.dev_time_s / end_s * 100.0 if end_s > 0 else None
        result.dev_delta_f = (result.end_bt_f or fc.bt_f) - fc.bt_f
        result.ror_fc_f = _value_at(curve, fc.time_s)
        post_fc = [(t, r) for t, r in curve if t > fc.time_s]
        if post_fc:
            result.ror_min_after_fc_f = min(r for _, r in post_fc)
        # Crash: big RoR fall shortly after FC
        if result.ror_fc_f is not None and result.ror_fc_f > 0:
            window = [r for t, r in post_fc if t <= fc.time_s + targets.crash_window_s]
            if window:
                fall = result.ror_fc_f - min(window)
                if (
                    fall >= result.ror_fc_f * targets.crash_fraction
                    and fall >= targets.crash_min_drop_c * 1.8
                ):
                    result.crash = True

    # Flicks: RoR rebounds after it has peaked and started falling
    if curve and tp is not None:
        rise_f = targets.flick_rise_c * 1.8
        peak_idx = None
        best = None
        for i, (t, r) in enumerate(curve):
            if t >= tp.time_s and (best is None or r > best):
                best, peak_idx = r, i
        if peak_idx is not None:
            running_min = curve[peak_idx][1]
            armed = True
            for t, r in curve[peak_idx + 1:]:
                if r < running_min:
                    running_min = r
                    armed = True
                elif armed and r - running_min >= rise_f:
                    result.flick_times_s.append(t)
                    armed = False
                    running_min = r

    # Weight loss
    if green_weight_g and roasted_weight_g and green_weight_g > 0:
        result.weight_loss_pct = (green_weight_g - roasted_weight_g) / green_weight_g * 100.0

    if plan is not None:
        _compare_plan(result, plan)

    _evaluate(result, targets)
    return result


def _compare_plan(a: RoastAnalysis, plan: PlanTargets) -> None:
    a.plan = plan
    now = plan.at(a.end_s) if a.live else None
    if now is not None and a.end_bt_f is not None:
        a.bt_vs_plan_f = a.end_bt_f - now[0]
        if a.ror_end_f is not None and a.end_s > plan.tp_s:
            a.ror_vs_plan_f = a.ror_end_f - now[1]
    if a.dry_end is not None:
        a.dry_end_vs_plan_s = round(a.dry_end.time_s - plan.dry_end_s, 1)
    if a.first_crack is not None:
        a.fc_vs_plan_s = round(a.first_crack.time_s - plan.fc_s, 1)
    if not a.live:
        a.drop_vs_plan_s = round(a.end_s - plan.drop_s, 1)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def _evaluate(a: RoastAnalysis, tg: Targets) -> None:
    """Fill in status and findings, most severe first."""
    st = a.status
    bad: list[Finding] = []
    warn: list[Finding] = []
    info: list[Finding] = []

    def rng(r: tuple[float, float], unit: str = "") -> str:
        return f"{r[0]:g}-{r[1]:g}{unit}"

    if a.first_crack is None:
        if not a.live:
            info.append(Finding(
                "info", "NO FC MARKED",
                "First crack was not marked, so development metrics (DTR, dev time, "
                "dev delta-T) can't be computed. Press FCS at the first audible pops.",
            ))

    # Total time (only meaningful once FC has happened or roast finished)
    if a.first_crack is not None or not a.live:
        s = _classify(a.end_s, tg.total_time_s)
        if s == "low" and a.live:
            s = None  # still going — not "fast" yet
        if s:
            st["total_time"] = s
        if s == "low" and not a.live:
            warn.append(Finding(
                "warn", "FAST ROAST",
                f"Total time {fmt_time(a.end_s)} is under the "
                f"{fmt_time(tg.total_time_s[0])}-{fmt_time(tg.total_time_s[1])} target. "
                "Fast light roasts often taste grassy/sour or uneven (roasty outside, "
                "underdeveloped inside). Lower charge energy or burner in Maillard.",
            ))
        elif s == "high":
            warn.append(Finding(
                "warn", "LONG ROAST: FLAT RISK",
                f"Total time {fmt_time(a.end_s)} is over the "
                f"{fmt_time(tg.total_time_s[1])} target. Long, slow roasts tend to taste "
                "flat, papery or 'baked' with muted acidity and sweetness. Use more heat "
                "early (charge / drying) so you can coast later.",
            ))

    # DTR / development
    s = _classify(a.dtr_pct, tg.dtr_pct)
    if s:
        st["dtr"] = s
    if s == "low" and not a.live:
        bad.append(Finding(
            "bad", "DTR LOW: UNDERDEVELOPED",
            f"Development time ratio {a.dtr_pct:.1f}% is below the {rng(tg.dtr_pct, '%')} "
            "target. Expect sour, grassy, peanut or hay notes and fast, thin espresso "
            "shots. Drop later, or ease the heat down more gently through first crack.",
        ))
    elif s == "high":
        warn.append(Finding(
            "warn", "DTR HIGH: MUTED/ROASTY",
            f"Development time ratio {a.dtr_pct:.1f}% is above the {rng(tg.dtr_pct, '%')} "
            "target for a light roast. Acidity and origin character get muted and roast "
            "flavours creep in. Drop earlier.",
        ))

    s = _classify(a.dev_time_s, tg.dev_time_s)
    if s:
        st["dev_time"] = s

    dev_delta_c = f_to_c_delta(a.dev_delta_f) if a.dev_delta_f is not None else None
    s = _classify(dev_delta_c, tg.dev_delta_c)
    if s:
        st["dev_delta"] = s
    if s == "low" and not a.live and dev_delta_c is not None:
        warn.append(Finding(
            "warn", "DEV DT LOW",
            f"BT rose only {dev_delta_c:.1f} C between first crack and drop "
            f"(target {rng(tg.dev_delta_c, ' C')}). Even with good DTR, a small rise means "
            "little development — usually from RoR falling too low after FC.",
        ))
    elif s == "high" and dev_delta_c is not None:
        warn.append(Finding(
            "warn", "DEV DT HIGH",
            f"BT rose {dev_delta_c:.1f} C after first crack (target "
            f"{rng(tg.dev_delta_c, ' C')}). That's heading toward a medium roast.",
        ))

    # Drying share
    drying = a.phase("DRYING")
    if drying is not None and drying.pct is not None and a.first_crack is not None:
        s = _classify(drying.pct, tg.drying_pct)
        if s:
            st["drying_pct"] = s
        if s == "high":
            warn.append(Finding(
                "warn", "LONG DRYING: LOW EARLY HEAT",
                f"Drying took {drying.pct:.0f}% of the roast ({fmt_time(drying.duration_s)}). "
                "A slow start leaves too little momentum for Maillard and development and "
                "is a common cause of flat cups. Charge hotter or run more burner early "
                "(Kaleido's own guide recommends high heat in the early stages).",
            ))
        elif s == "low":
            info.append(Finding(
                "info", "SHORT DRYING",
                f"Drying took only {drying.pct:.0f}% of the roast. Very aggressive starts "
                "can scorch or give uneven development on a small drum.",
            ))

    # RoR at FC
    ror_fc_c = f_to_c_delta(a.ror_fc_f) if a.ror_fc_f is not None else None
    s = _classify(ror_fc_c, tg.ror_fc_c)
    if s:
        st["ror_fc"] = s
    if s == "high" and ror_fc_c is not None:
        warn.append(Finding(
            "warn", "HOT INTO FC",
            f"RoR was {ror_fc_c:.1f} C/min at first crack (target "
            f"{rng(tg.ror_fc_c, ' C/min')}). Hitting FC fast makes development hard to "
            "control and often leads to a crash-then-flick. Start reducing heat earlier.",
        ))
    elif s == "low" and ror_fc_c is not None:
        warn.append(Finding(
            "warn", "LOW ROR AT FC",
            f"RoR was only {ror_fc_c:.1f} C/min at first crack (target "
            f"{rng(tg.ror_fc_c, ' C/min')}). Low momentum through crack tends to stall "
            "and bake the roast.",
        ))

    # Crash
    if a.crash and a.ror_fc_f is not None and a.ror_min_after_fc_f is not None:
        bad.append(Finding(
            "bad", "ROR CRASH AFTER FC",
            f"RoR fell from {f_to_c_delta(a.ror_fc_f):.1f} to "
            f"{f_to_c_delta(a.ror_min_after_fc_f):.1f} C/min within "
            f"{tg.crash_window_s:.0f} s of first crack. A crash is the classic cause of "
            "flat, dull, 'boring' cups. Reduce heat before FC (30-60 s ahead, in small "
            "steps) instead of cutting hard at FC, and avoid large airflow jumps.",
        ))

    # Flicks (mainly matter late in the roast)
    fc_t = a.first_crack.time_s if a.first_crack is not None else None
    late = [t for t in a.flick_times_s if fc_t is not None and t >= fc_t - 30.0]
    if late:
        bad.append(Finding(
            "bad", f"ROR FLICK {fmt_time(late[0])}",
            f"RoR rose again at {', '.join(fmt_time(t) for t in late)} after it had been "
            "falling. Late flicks add roasty, bitter or smoky notes and usually follow "
            "a crash where heat was added back. Aim for a smooth, steadily declining RoR.",
        ))
    elif a.flick_times_s:
        info.append(Finding(
            "info", f"ROR BUMP {fmt_time(a.flick_times_s[0])}",
            f"RoR rose again at {', '.join(fmt_time(t) for t in a.flick_times_s)} before "
            "first crack. Usually minor, but a smoothly declining RoR is the goal.",
        ))

    # RoR at drop
    if not a.live and a.first_crack is not None:
        ror_end_c = f_to_c_delta(a.ror_end_f) if a.ror_end_f is not None else None
        s = _classify(ror_end_c, tg.ror_drop_c)
        if s:
            st["ror_drop"] = s
        if s == "low" and ror_end_c is not None:
            warn.append(Finding(
                "warn", "STALLED AT DROP",
                f"RoR was {ror_end_c:.1f} C/min at drop. A stalled finish tends to bake "
                "out sweetness. Keep a little more heat through development.",
            ))

    # Weight loss
    s = _classify(a.weight_loss_pct, tg.weight_loss_pct)
    if s:
        st["weight_loss"] = s
    if s and s != "ok" and a.weight_loss_pct is not None:
        what = "lighter" if s == "low" else "darker"
        warn.append(Finding(
            "warn", f"WEIGHT LOSS {a.weight_loss_pct:.1f}%",
            f"Weight loss {a.weight_loss_pct:.1f}% is outside the "
            f"{rng(tg.weight_loss_pct, '%')} light-espresso range — the roast is {what} "
            "than intended.",
        ))

    if a.live:
        # Development numbers only grow while roasting; "low" isn't a problem yet
        for key in ("dtr", "dev_time", "dev_delta"):
            if st.get(key) == "low":
                st[key] = "ok"

    # Against the coffee's plan
    if a.plan is not None:
        def when(delta: float) -> str:
            return f"{fmt_time(abs(delta))} {'LATE' if delta > 0 else 'EARLY'}"

        if a.bt_vs_plan_f is not None and abs(f_to_c_delta(a.bt_vs_plan_f)) >= 4.0:
            d = f_to_c_delta(a.bt_vs_plan_f)
            info.append(Finding(
                "info", f"BT {abs(d):.0f}C {'AHEAD OF' if d > 0 else 'BEHIND'} PLAN",
                f"BT is {abs(d):.1f} C {'above' if d > 0 else 'below'} the plan curve right "
                "now. Nudge the burner " + ("down." if d > 0 else "up."),
            ))
        if a.fc_vs_plan_s is not None and abs(a.fc_vs_plan_s) >= 30:
            warn.append(Finding(
                "warn", f"FC {when(a.fc_vs_plan_s)}",
                f"First crack came {when(a.fc_vs_plan_s).lower()} versus the plan "
                f"({fmt_time(a.plan.fc_s)}). "
                + ("More heat in Maillard (or a hotter charge) next time."
                   if a.fc_vs_plan_s > 0 else
                   "Less heat in Maillard (or a cooler charge) next time."),
            ))
        if a.drop_vs_plan_s is not None and abs(a.drop_vs_plan_s) >= 30:
            info.append(Finding(
                "info", f"DROP {when(a.drop_vs_plan_s)}",
                f"Dropped {when(a.drop_vs_plan_s).lower()} versus the plan "
                f"({fmt_time(a.plan.drop_s)}).",
            ))

    a.findings = bad + warn + info
    if not a.live and a.first_crack is not None and not bad and not warn:
        a.findings.append(Finding(
            "good", "ALL METRICS IN TARGET",
            "Every tracked metric is within its target range. If the cup still "
            "disappoints, note what's missing (sweetness, acidity, body) — the next "
            "lever is usually charge temperature or the shape of the RoR curve.",
        ))
