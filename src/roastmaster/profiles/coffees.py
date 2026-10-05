"""Coffee library: per-coffee roast plans with a target curve.

Each coffee is a JSON file in ``coffees/`` (see ``docs/coffee-plans.md``).
A plan is written as *milestones* — turning point, dry end, first crack and
drop (time + BT) — and the target curve is derived from them: RoR is taken
as piecewise linear through the knots

    TP (0) -> peak -> dry end -> first crack -> drop

and the knot values are solved so the integrated BT curve passes exactly
through the dry-end, first-crack and drop milestones, with RoR at drop set
to ``dev_ror_ratio`` x RoR at first crack (a smooth, steadily declining
finish).  Tweaking a plan therefore means moving a milestone ("FC 15 s
later") — the curve follows.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import threading
from dataclasses import dataclass, field, fields, replace
from pathlib import Path

from roastmaster.display.units import c_to_f
from roastmaster.engine.analysis import DEFAULT_TARGETS, PlanTargets, Targets

logger = logging.getLogger(__name__)

_DEFAULT_DIR = Path("coffees")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,79}$")


# ---------------------------------------------------------------------------
# Plan and curve maths
# ---------------------------------------------------------------------------


@dataclass
class RoastPlan:
    """Milestones for one coffee (times in seconds since CHARGE, temps in C)."""

    preheat_sv_c: float = 190.0     # roaster setpoint to preheat to
    charge_bt_c: float = 190.0      # BT reading to charge at
    tp_s: float = 60.0
    tp_bt_c: float = 96.0
    peak_s: float = 120.0           # when RoR should peak
    dry_end_s: float = 240.0        # BT reaches the dry-end threshold
    fc_s: float = 420.0
    fc_bt_c: float = 185.0
    drop_s: float = 520.0
    drop_bt_c: float = 195.0
    dev_ror_ratio: float = 0.5      # RoR at drop / RoR at FC

    @classmethod
    def from_dict(cls, d: dict) -> RoastPlan:
        names = {f.name for f in fields(cls)}
        return cls(**{k: float(v) for k, v in d.items() if k in names})

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def _integral(knots: list[tuple[float, float]], t_end: float) -> float:
    """Integral of a piecewise-linear function from the first knot to t_end."""
    total = 0.0
    for (t0, r0), (t1, r1) in zip(knots, knots[1:], strict=False):
        if t_end <= t0 or t1 <= t0:
            break
        te = min(t_end, t1)
        re_ = r0 + (r1 - r0) * (te - t0) / (t1 - t0)
        total += (r0 + re_) / 2.0 * (te - t0)
    return total


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (small dense systems)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[p][c]) < 1e-12:
            raise ValueError("plan milestones are inconsistent")
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c], strict=True)]
    return [m[i][n] / m[i][i] for i in range(n)]


def ror_knots(plan: RoastPlan, dry_end_c: float) -> list[tuple[float, float]]:
    """RoR (C/min) knots from TP to drop that satisfy the plan milestones."""
    ts = [plan.tp_s, plan.peak_s, plan.dry_end_s, plan.fc_s, plan.drop_s]
    if ts != sorted(ts) or len(set(ts)) != len(ts):
        raise ValueError("plan times must increase: tp < peak < dry end < fc < drop")

    def basis(j: int) -> list[tuple[float, float]]:
        return [(t, 1.0 if i == j else 0.0) for i, t in enumerate(ts)]

    rows = [
        [_integral(basis(j), t_end) / 60.0 for j in (1, 2, 3, 4)]
        for t_end in (plan.dry_end_s, plan.fc_s, plan.drop_s)
    ]
    rhs = [dry_end_c - plan.tp_bt_c, plan.fc_bt_c - plan.tp_bt_c, plan.drop_bt_c - plan.tp_bt_c]
    rows.append([0.0, 0.0, -plan.dev_ror_ratio, 1.0])
    rhs.append(0.0)
    peak, de, fc, drop = _solve(rows, rhs)
    return list(zip(ts, [0.0, peak, de, fc, drop], strict=True))


def target_curve(plan: RoastPlan, dry_end_c: float) -> list[tuple[float, float, float]]:
    """Target (t_s, bt_c, ror_c_per_min) at 1 s steps from CHARGE to drop."""
    knots = ror_knots(plan, dry_end_c)
    out: list[tuple[float, float, float]] = []
    t = 0
    span = plan.charge_bt_c - plan.tp_bt_c
    while t <= plan.drop_s:
        if t <= plan.tp_s:
            # Charge dip: BT falls from the charge reading to the turning point
            u = 1.0 - t / plan.tp_s
            bt = plan.tp_bt_c + span * u * u
            ror = -2.0 * span * u / plan.tp_s * 60.0
        else:
            bt = plan.tp_bt_c + _integral(knots, t) / 60.0
            ror = _interp(knots, t)
        out.append((float(t), bt, ror))
        t += 1
    return out


def _interp(knots: list[tuple[float, float]], t: float) -> float:
    for (t0, r0), (t1, r1) in zip(knots, knots[1:], strict=False):
        if t0 <= t <= t1:
            return r0 + (r1 - r0) * (t - t0) / (t1 - t0)
    return knots[-1][1]


# ---------------------------------------------------------------------------
# Coffee
# ---------------------------------------------------------------------------


@dataclass
class Coffee:
    id: str
    name: str
    short: str = ""                   # CRT label (<= ~16 chars)
    status: str = "active"            # "active" | "draft" (needs a proper plan)
    version: int = 1
    source_url: str = ""
    origin: str = ""
    process: str = ""
    altitude_m: float | None = None
    variety: str = ""
    vendor_notes: str = ""
    goal: str = "Bright, fruity light roast for espresso"
    rationale: str = ""
    plan: RoastPlan = field(default_factory=RoastPlan)
    # Overrides for analysis Targets, e.g. {"dtr_pct": [16, 20]}
    targets: dict = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)   # how to fly the roast
    # Resting before espresso: {"min_days", "best_days", "max_days", "note"}
    rest: dict = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        return self.short or self.name

    @classmethod
    def from_dict(cls, d: dict) -> Coffee:
        return cls(
            id=str(d["id"]),
            name=str(d.get("name", d["id"])),
            short=str(d.get("short", "")),
            status=str(d.get("status", "active")),
            version=int(d.get("version", 1)),
            source_url=str(d.get("source_url", "")),
            origin=str(d.get("origin", "")),
            process=str(d.get("process", "")),
            altitude_m=d.get("altitude_m"),
            variety=str(d.get("variety", "")),
            vendor_notes=str(d.get("vendor_notes", "")),
            goal=str(d.get("goal", cls.goal)),
            rationale=str(d.get("rationale", "")),
            plan=RoastPlan.from_dict(d.get("plan", {})),
            targets=dict(d.get("targets", {})),
            steps=list(d.get("steps", [])),
            rest=dict(d.get("rest") or {}),
            history=list(d.get("history", [])),
        )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "short": self.short,
            "status": self.status,
            "version": self.version,
            "source_url": self.source_url,
            "origin": self.origin,
            "process": self.process,
            "altitude_m": self.altitude_m,
            "variety": self.variety,
            "vendor_notes": self.vendor_notes,
            "goal": self.goal,
            "rationale": self.rationale,
            "plan": self.plan.to_dict(),
            "targets": self.targets,
            "steps": self.steps,
            "rest": self.rest,
            "history": self.history,
        }

    # -- derived -------------------------------------------------------

    def analysis_targets(self) -> Targets:
        """Default Targets with this coffee's overrides applied."""
        valid = {f.name for f in fields(Targets)}
        overrides = {}
        for k, v in self.targets.items():
            if k not in valid:
                continue
            overrides[k] = tuple(float(x) for x in v) if isinstance(v, list) else float(v)
        return replace(DEFAULT_TARGETS, **overrides)

    def curve(self) -> list[tuple[float, float, float]]:
        return target_curve(self.plan, self.analysis_targets().dry_end_c)

    def plan_targets(self) -> PlanTargets:
        """Target curve + milestones in the engine's units (F)."""
        p = self.plan
        return PlanTargets(
            curve=[(t, c_to_f(bt), ror * 1.8) for t, bt, ror in self.curve()],
            tp_s=p.tp_s,
            dry_end_s=p.dry_end_s,
            fc_s=p.fc_s,
            fc_bt_f=c_to_f(p.fc_bt_c),
            drop_s=p.drop_s,
            drop_bt_f=c_to_f(p.drop_bt_c),
            charge_bt_f=c_to_f(p.charge_bt_c),
            label=self.label,
        )

    def snapshot(self) -> dict:
        """What gets stored with a roast: the plan as it was that day."""
        return {
            "coffee_id": self.id,
            "version": self.version,
            "name": self.name,
            "plan": self.plan.to_dict(),
            "targets": self.targets,
            "rest": self.rest,
        }

    @classmethod
    def from_snapshot(cls, snap: dict) -> Coffee:
        return cls(
            id=str(snap.get("coffee_id", "")),
            name=str(snap.get("name", "")),
            version=int(snap.get("version", 1)),
            plan=RoastPlan.from_dict(snap.get("plan", {})),
            targets=dict(snap.get("targets", {})),
            rest=dict(snap.get("rest") or {}),
        )


def rest_text(rest: dict) -> str:
    """'10-21 days (best ~14)', or '' when the plan has no rest guidance."""
    if not rest or "min_days" not in rest or "max_days" not in rest:
        return ""
    text = f"{rest['min_days']}-{rest['max_days']} days"
    if rest.get("best_days") is not None:
        text += f" (best ~{rest['best_days']})"
    return text


def rest_window(rest: dict, roast_date: str) -> tuple[dt.date, dt.date | None, dt.date] | None:
    """(ready from, best, end of best window) for a roast made on roast_date ('YYYY-MM-DD ...')."""
    if not rest_text(rest):
        return None
    try:
        day = dt.date.fromisoformat(roast_date[:10])
    except ValueError:
        return None
    best = rest.get("best_days")
    return (
        day + dt.timedelta(days=int(rest["min_days"])),
        day + dt.timedelta(days=int(best)) if best is not None else None,
        day + dt.timedelta(days=int(rest["max_days"])),
    )


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:60] or "coffee"


def draft_coffee(name: str, **info: object) -> Coffee:
    """A new coffee with a generic light-roast plan, marked draft."""
    values: dict = {
        "id": slugify(name),
        "name": name,
        "short": name[:16].upper(),
        "status": "draft",
        "rationale": "Generic starting plan — share the product page with Claude to "
                     "develop a proper one.",
        "steps": [
            "Preheat to the SV shown, charge 170 g at the charge BT.",
            "High burner through drying, then step down gradually after dry end.",
            "Aim to reach first crack with RoR still falling smoothly; no big cuts at FC.",
        ],
    }
    allowed = {f.name for f in fields(Coffee)} - {"id", "name", "status"}
    values.update({k: v for k, v in info.items() if k in allowed and v not in (None, "")})
    return Coffee(**values)


# ---------------------------------------------------------------------------
# Library (directory of JSON files)
# ---------------------------------------------------------------------------


class CoffeeLibrary:
    def __init__(self, directory: Path | str | None = None) -> None:
        self._dir = Path(directory) if directory else _DEFAULT_DIR
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return self._dir

    def all(self) -> list[Coffee]:
        """All coffees, active first, then by name."""
        out: list[Coffee] = []
        if not self._dir.is_dir():
            return out
        for path in sorted(self._dir.glob("*.json")):
            try:
                coffee = Coffee.from_dict(json.loads(path.read_text()))
                coffee.curve()  # validate the plan
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("Skipping coffee %s: %s", path.name, exc)
                continue
            out.append(coffee)
        out.sort(key=lambda c: (c.status != "active", c.name.lower(), c.id))
        return out

    def get(self, coffee_id: str) -> Coffee | None:
        if not _ID_RE.match(coffee_id or ""):
            return None
        path = self._dir / f"{coffee_id}.json"
        try:
            return Coffee.from_dict(json.loads(path.read_text()))
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def save(self, coffee: Coffee) -> Path:
        if not _ID_RE.match(coffee.id):
            raise ValueError(f"bad coffee id {coffee.id!r}")
        path = self._dir / f"{coffee.id}.json"
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(coffee.to_dict(), indent=2) + "\n")
            tmp.replace(path)
        return path

    def add_draft(self, name: str, **info: object) -> Coffee:
        coffee = draft_coffee(name, **info)
        base, n = coffee.id, 2
        while (self._dir / f"{coffee.id}.json").exists():
            coffee.id = f"{base}-{n}"
            n += 1
        self.save(coffee)
        return coffee
