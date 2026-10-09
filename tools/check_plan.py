#!/usr/bin/env python3
"""Check a CONAR 255 coffee plan file. Usage: python3 check_plan.py my-coffee.json"""
import json
import re
import sys
import unicodedata
from pathlib import Path

CRT_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .-/%+|[]?!><:=(),_'~")
PLAN_KEYS = ["preheat_sv_c", "charge_bt_c", "tp_s", "tp_bt_c", "peak_s", "dry_end_s",
             "fc_s", "fc_bt_c", "drop_s", "drop_bt_c"]
RANGE_KEYS = ["total_time_s", "dtr_pct", "dev_time_s", "dev_delta_c", "drying_pct",
              "ror_fc_c", "ror_drop_c", "weight_loss_pct"]


def integral(knots, t_end):
    total = 0.0
    for (t0, r0), (t1, r1) in zip(knots, knots[1:]):
        if t_end <= t0:
            break
        te = min(t_end, t1)
        total += (r0 + r0 + (r1 - r0) * (te - t0) / (t1 - t0)) / 2 * (te - t0)
    return total


def solve(a, b):
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


def ror_knots(p, dry_end_c):
    ts = [p["tp_s"], p["peak_s"], p["dry_end_s"], p["fc_s"], p["drop_s"]]
    ratio = p.get("dev_ror_ratio", 0.5)

    def basis(j):
        return [(t, 1.0 if i == j else 0.0) for i, t in enumerate(ts)]

    rows = [[integral(basis(j), t) / 60 for j in (1, 2, 3, 4)]
            for t in (p["dry_end_s"], p["fc_s"], p["drop_s"])]
    rhs = [dry_end_c - p["tp_bt_c"], p["fc_bt_c"] - p["tp_bt_c"], p["drop_bt_c"] - p["tp_bt_c"]]
    return solve(rows + [[0, 0, -ratio, 1]], rhs + [0])


def mmss(s):
    return f"{int(s) // 60}:{int(s) % 60:02d}"


def check_controls(controls, errors, warnings):
    if not controls:
        warnings.append("no 'controls': the roaster won't show burner/air targets while roasting")
        return
    if not isinstance(controls, list) or not isinstance(controls[0], dict) \
            or controls[0].get("at") != "charge":
        errors.append('\'controls\' must be a list starting with {"at": "charge", ...}')
        return
    bts, burners = [], []
    for c in controls:
        if not isinstance(c, dict) or not ("bt_c" in c or c.get("at") in ("charge", "fc")):
            errors.append(f"control step needs 'bt_c' or 'at': charge|fc, got {c}")
            continue
        for k in ("burner", "air", "drum"):
            if k in c and not (isinstance(c[k], (int, float)) and 0 <= c[k] <= 100):
                errors.append(f"control {k} must be 0-100, got {c}")
        if "bt_c" in c:
            bts.append(c["bt_c"])
        if "burner" in c:
            burners.append(c["burner"])
    if bts != sorted(bts) or (bts and bts[0] != 150):
        errors.append("control 'bt_c' steps must rise, starting at 150 (dry end)")
    if burners != sorted(burners, reverse=True):
        errors.append("control burner values must only step down")


def check(path):
    errors, warnings = [], []
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [f"not readable JSON: {e}"], [], None
    cid = d.get("id", "")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", str(cid)):
        errors.append("id must be lowercase letters, digits and hyphens (max 80)")
    if Path(path).stem != cid:
        errors.append(f"file name must be {cid}.json")
    for key in ("name", "short", "rationale"):
        if not str(d.get(key, "")).strip():
            errors.append(f"'{key}' is missing or empty")
    if not isinstance(d.get("version"), int) or d["version"] < 1:
        errors.append("'version' must be a whole number >= 1")
    if d.get("status", "active") not in ("active", "draft"):
        errors.append("'status' must be 'active' or 'draft'")
    short = str(d.get("short", ""))
    if len(short) > 16:
        errors.append(f"'short' is {len(short)} characters (max 16)")
    steps = d.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("'steps' must be a non-empty list of strings")
        steps = []
    if len(steps) > 8:
        warnings.append(f"{len(steps)} steps; only about 8 fit on the PLAN page")
    for label, text in [("short", short)] + [(f"step {i + 1}", s) for i, s in enumerate(steps)]:
        shown = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode()
        bad = sorted({ch for ch in shown.upper() if ch not in CRT_OK})
        if bad:
            warnings.append(f"{label}: the CRT shows a box for {' '.join(bad)}")
    for i, s in enumerate(steps):
        if len(str(s)) > 72:
            warnings.append(f"step {i + 1} is {len(s)} characters; keep steps under ~70")
    rest = d.get("rest")
    if not rest:
        warnings.append("no 'rest' section: the roaster won't show when it's ready for espresso")
    elif not (isinstance(rest, dict)
              and all(isinstance(rest.get(k), int) for k in ("min_days", "best_days", "max_days"))
              and 1 <= rest["min_days"] <= rest["best_days"] <= rest["max_days"] <= 45):
        errors.append("'rest' needs whole-number min_days <= best_days <= max_days (1-45)")
    check_controls(d.get("controls"), errors, warnings)
    if not isinstance(d.get("history"), list) or not d["history"]:
        errors.append("'history' must list at least one {version, date, note}")

    p = d.get("plan")
    if not isinstance(p, dict):
        return errors + ["'plan' object is missing"], warnings, None
    for key in PLAN_KEYS:
        if not isinstance(p.get(key), (int, float)):
            errors.append(f"plan.{key} must be a number")
    if errors:
        return errors, warnings, None

    targets = d.get("targets", {})
    for key, value in targets.items():
        if key in RANGE_KEYS and not (isinstance(value, list) and len(value) == 2
                                      and value[0] <= value[1]):
            errors.append(f"targets.{key} must be [low, high]")
    times = [p["tp_s"], p["peak_s"], p["dry_end_s"], p["fc_s"], p["drop_s"]]
    if any(b <= a for a, b in zip(times, times[1:])):
        return errors + ["plan times must increase: tp_s < peak_s < dry_end_s < fc_s < drop_s"], \
            warnings, None
    if not 25 <= p["tp_s"] <= 50:
        warnings.append(f"tp_s {p['tp_s']:g} s: this roaster turns at about 30-45 s")
    dry_end_c = float(targets.get("dry_end_c", 150))
    peak, de, fc, drop = ror_knots(p, dry_end_c)
    if not peak > de > fc > drop > 0:
        errors.append(f"RoR must fall steadily after the peak (got {peak:.1f} > {de:.1f} > "
                      f"{fc:.1f} > {drop:.1f} C/min); move milestones")
    if not 15 <= peak <= 30:
        errors.append(f"peak RoR {peak:.1f} C/min is outside 15-30")
    if not 5 <= fc <= 12:
        errors.append(f"RoR at first crack {fc:.1f} C/min is outside 5-12")
    dtr = (p["drop_s"] - p["fc_s"]) / p["drop_s"] * 100
    lo, hi = targets.get("dtr_pct", [16, 22])
    if not lo <= dtr <= hi:
        errors.append(f"plan DTR {dtr:.1f}% is outside its targets.dtr_pct [{lo}, {hi}]")
    rest_txt = (f" | rest {rest['min_days']}-{rest['max_days']} days (best ~{rest['best_days']})"
                if isinstance(rest, dict) and rest.get("best_days") else "")
    summary = (f"{d.get('name')} v{d.get('version')}: TP {mmss(p['tp_s'])} @ {p['tp_bt_c']:g}, "
               f"dry end {mmss(p['dry_end_s'])}, FC {mmss(p['fc_s'])} @ {p['fc_bt_c']:g}, "
               f"drop {mmss(p['drop_s'])} @ {p['drop_bt_c']:g} C | DTR {dtr:.1f}%, "
               f"dev dT {p['drop_bt_c'] - p['fc_bt_c']:.1f} C | RoR peak {peak:.1f}, "
               f"dry end {de:.1f}, FC {fc:.1f}, drop {drop:.1f} C/min{rest_txt}")
    return errors, warnings, summary


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("usage: python3 check_plan.py <plan.json> [more.json ...]")
    failed = False
    for path in sys.argv[1:]:
        errors, warnings, summary = check(path)
        print(f"== {path}")
        if summary:
            print("   " + summary)
        for w in warnings:
            print("   WARNING: " + w)
        for e in errors:
            print("   ERROR: " + e)
        print("   OK" if not errors else "   NOT VALID")
        failed |= bool(errors)
    sys.exit(1 if failed else 0)
