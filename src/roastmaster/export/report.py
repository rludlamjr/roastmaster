"""Roast reports: summary rows, CSV, text summary, SVG chart, HTML.

Everything here is presentation of a saved ``RoastProfile`` plus its
``RoastAnalysis``; all output temperatures are Celsius.
"""

from __future__ import annotations

import csv
import html
import io

from roastmaster.display.units import f_to_c, f_to_c_delta
from roastmaster.engine.analysis import RoastAnalysis, fmt_time
from roastmaster.profiles.schema import RoastProfile

# Columns of the one-row-per-roast log (roasts.csv)
SUMMARY_COLUMNS = [
    "roast_id", "date", "coffee", "coffee_id", "plan_version", "green_g", "roasted_g",
    "weight_loss_pct", "rating",
    "total_time", "charge_bt_c", "tp_time", "tp_bt_c", "dry_end_time", "dry_end_bt_c",
    "fc_time", "fc_bt_c", "drop_bt_c", "drying_pct", "maillard_pct", "dtr_pct",
    "dev_time", "dev_delta_c", "ror_fc_c", "ror_drop_c", "crash", "flicks",
    "avg_burner_drying", "avg_burner_maillard", "avg_burner_dev",
    "plan_fc_time", "plan_drop_time", "fc_vs_plan_s", "drop_vs_plan_s",
    "findings", "notes", "tasting_notes",
]


def _c(v: float | None) -> str:
    return f"{f_to_c(v):.1f}" if v is not None else ""


def _cd(v: float | None) -> str:
    return f"{f_to_c_delta(v):.1f}" if v is not None else ""


def _num(v: float | None, fmt: str = "{:.1f}") -> str:
    return fmt.format(v) if v is not None else ""


def summary_row(profile: RoastProfile, a: RoastAnalysis | None = None) -> dict[str, str]:
    """Flat, Celsius, human-readable summary of one roast."""
    a = a or profile.analyze()
    dry, mai, dev = a.phase("DRYING"), a.phase("MAILLARD"), a.phase("DEVELOPMENT")
    return {
        "roast_id": profile.roast_id,
        "date": profile.roast_date,
        "coffee": profile.coffee,
        "coffee_id": profile.coffee_id,
        "plan_version": str(profile.plan.get("version", "")) if profile.plan else "",
        "green_g": _num(profile.weight_g or None, "{:g}"),
        "roasted_g": _num(profile.roasted_weight_g, "{:g}"),
        "weight_loss_pct": _num(a.weight_loss_pct),
        "rating": "" if profile.rating is None else str(profile.rating),
        "total_time": fmt_time(a.end_s) if a.charged else "",
        "charge_bt_c": _c(a.charge_bt_f),
        "tp_time": fmt_time(a.turning_point.time_s) if a.turning_point else "",
        "tp_bt_c": _c(a.turning_point.bt_f) if a.turning_point else "",
        "dry_end_time": fmt_time(a.dry_end.time_s) if a.dry_end else "",
        "dry_end_bt_c": _c(a.dry_end.bt_f) if a.dry_end else "",
        "fc_time": fmt_time(a.first_crack.time_s) if a.first_crack else "",
        "fc_bt_c": _c(a.first_crack.bt_f) if a.first_crack else "",
        "drop_bt_c": _c(a.end_bt_f) if not a.live else "",
        "drying_pct": _num(dry.pct if dry else None),
        "maillard_pct": _num(mai.pct if mai else None),
        "dtr_pct": _num(a.dtr_pct),
        "dev_time": fmt_time(a.dev_time_s) if a.dev_time_s is not None else "",
        "dev_delta_c": _cd(a.dev_delta_f),
        "ror_fc_c": _cd(a.ror_fc_f),
        "ror_drop_c": _cd(a.ror_end_f) if not a.live else "",
        "crash": "yes" if a.crash else "",
        "flicks": " ".join(fmt_time(t) for t in a.flick_times_s),
        "avg_burner_drying": _num(dry.avg_burner if dry else None, "{:.0f}"),
        "avg_burner_maillard": _num(mai.avg_burner if mai else None, "{:.0f}"),
        "avg_burner_dev": _num(dev.avg_burner if dev else None, "{:.0f}"),
        "plan_fc_time": fmt_time(a.plan.fc_s) if a.plan else "",
        "plan_drop_time": fmt_time(a.plan.drop_s) if a.plan else "",
        "fc_vs_plan_s": _num(a.fc_vs_plan_s, "{:+.0f}"),
        "drop_vs_plan_s": _num(a.drop_vs_plan_s, "{:+.0f}"),
        "findings": "; ".join(f.short for f in a.findings),
        "notes": profile.notes,
        "tasting_notes": profile.tasting_notes,
    }


def summary_csv(profiles: list[RoastProfile]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=SUMMARY_COLUMNS)
    w.writeheader()
    for p in profiles:
        w.writerow(summary_row(p))
    return buf.getvalue()


def samples_csv(profile: RoastProfile) -> str:
    """Per-second samples, time relative to CHARGE, Celsius."""
    charge = next((e for e in profile.events if e.event_type == "CHARGE"), None)
    t0 = charge.elapsed if charge else 0.0
    marks = {round(e.elapsed): e.event_type for e in profile.events}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_s", "bt_c", "et_c", "ror_c_per_min", "burner", "drum", "air",
                "setpoint_c", "heater_reported", "event"])
    for s in profile.samples:
        w.writerow([
            f"{s.elapsed - t0:.0f}", f"{f_to_c(s.bt):.1f}", f"{f_to_c(s.et):.1f}",
            _cd(s.ror), f"{s.burner:.0f}", f"{s.drum:.0f}", f"{s.air:.0f}",
            _c(s.sv), _num(s.hp, "{:.0f}"), marks.get(round(s.elapsed), ""),
        ])
    return buf.getvalue()


def text_summary(profile: RoastProfile, a: RoastAnalysis | None = None) -> str:
    """Plain-text summary, e.g. for an email body."""
    a = a or profile.analyze()
    r = summary_row(profile, a)
    lines = [
        f"Roast {profile.roast_id or ''}  {profile.roast_date}",
        f"Coffee: {profile.coffee or '(not set)'}",
        (f"Plan: {profile.plan.get('coffee_id')} v{profile.plan.get('version')} "
         f"(FC {r['plan_fc_time']}, drop {r['plan_drop_time']}; actual FC "
         f"{r['fc_vs_plan_s'] or '--'} s, drop {r['drop_vs_plan_s'] or '--'} s vs plan)")
        if a.plan else "Plan: none",
        f"Batch: {r['green_g'] or '?'} g green"
        + (f" -> {r['roasted_g']} g roasted ({r['weight_loss_pct']}% loss)"
           if r["roasted_g"] else ""),
        "",
        f"Total time   {r['total_time']}",
        f"Charge BT    {r['charge_bt_c']} C",
        f"Turning pt   {r['tp_time']} @ {r['tp_bt_c']} C",
        f"Dry end      {r['dry_end_time']} @ {r['dry_end_bt_c']} C"
        + (" (auto)" if a.dry_end_auto else ""),
        f"First crack  {r['fc_time']} @ {r['fc_bt_c']} C",
        f"Drop         {r['total_time']} @ {r['drop_bt_c']} C",
        "",
        "Phases:",
    ]
    for p in a.phases:
        avg_ror = f"{f_to_c_delta(p.avg_ror_f):.1f}" if p.avg_ror_f is not None else "--"
        burner = f"{p.avg_burner:.0f}%" if p.avg_burner is not None else "--"
        lines.append(
            f"  {p.name:<12} {fmt_time(p.duration_s):>5}  {p.pct or 0:5.1f}%  "
            f"{f_to_c(p.start_bt_f):5.1f} -> {f_to_c(p.end_bt_f):5.1f} C  "
            f"avg RoR {avg_ror} C/min  burner {burner}"
        )
    lines += [
        "",
        f"DTR          {r['dtr_pct']}%",
        f"Dev time     {r['dev_time']}",
        f"Dev delta-T  {r['dev_delta_c']} C",
        f"RoR at FC    {r['ror_fc_c']} C/min",
        f"RoR at drop  {r['ror_drop_c']} C/min",
        f"RoR crash    {'YES' if a.crash else 'no'}",
        f"RoR flicks   {r['flicks'] or 'none'}",
        "",
        "Findings:",
    ]
    lines += [f"  [{f.level.upper()}] {f.detail}" for f in a.findings] or ["  (none)"]
    from roastmaster.profiles.coffees import rest_text, rest_window

    rest = (profile.plan or {}).get("rest") or {}
    win = rest_window(rest, profile.roast_date)
    if win is not None:
        start, best, end = win
        lines += ["", f"Rest before espresso: {rest_text(rest)}. Ready {start:%a %b %d}"
                      + (f", best ~{best:%a %b %d}" if best else "") + f", until {end:%a %b %d}."]
    if profile.rating is not None:
        lines += ["", f"Rating: {profile.rating}/10"]
    if profile.notes:
        lines += ["", "Roast notes:", profile.notes]
    if profile.tasting_notes:
        lines += ["", "Tasting notes:", profile.tasting_notes]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# SVG chart
# ---------------------------------------------------------------------------

_PHASE_FILL = {"DRYING": "#1b3a1b", "MAILLARD": "#3a331b", "DEVELOPMENT": "#3a1f1b"}


def svg_chart(
    profile: RoastProfile,
    a: RoastAnalysis | None = None,
    *,
    width: int = 720,
    height: int = 360,
) -> str:
    """Roast curve (BT, ET, RoR) with phase bands and event markers."""
    a = a or profile.analyze()
    charge = next((e for e in profile.events if e.event_type == "CHARGE"), None)
    t0 = charge.elapsed if charge else (profile.samples[0].elapsed if profile.samples else 0.0)
    end = a.end_s if a.charged else (profile.samples[-1].elapsed - t0 if profile.samples else 1)
    # Show a little of the cooling tail after drop
    t_max = max(60.0, end + (60.0 if not a.live else 0.0))
    if a.plan is not None:
        t_max = max(t_max, a.plan.drop_s + 30.0)
    pts = [s for s in profile.samples if 0 <= s.elapsed - t0 <= t_max]

    ml, mr, mt, mb = 44, 44, 12, 28
    pw, ph = width - ml - mr, height - mt - mb
    temp_lo, temp_hi = 20.0, 250.0
    ror_lo, ror_hi = -5.0, 30.0

    def x(t: float) -> float:
        return ml + t / t_max * pw

    def yt(c: float) -> float:
        return mt + (1 - (c - temp_lo) / (temp_hi - temp_lo)) * ph

    def yr(r: float) -> float:
        r = max(ror_lo, min(ror_hi, r))
        return mt + (1 - (r - ror_lo) / (ror_hi - ror_lo)) * ph

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="100%" font-family="monospace" font-size="11">',
        f'<rect width="{width}" height="{height}" fill="#050805"/>',
    ]
    for p in a.phases:
        band_w = max(0.0, x(p.end_s) - x(p.start_s))
        out.append(
            f'<rect x="{x(p.start_s):.1f}" y="{mt}" width="{band_w:.1f}" height="{ph}" '
            f'fill="{_PHASE_FILL.get(p.name, "#111")}" opacity="0.6"/>'
        )
    # Grid
    for c in range(50, 251, 50):
        out.append(f'<line x1="{ml}" x2="{ml + pw}" y1="{yt(c):.1f}" y2="{yt(c):.1f}" '
                   f'stroke="#1e3a1e" stroke-width="1"/>')
        out.append(f'<text x="{ml - 4}" y="{yt(c) + 4:.1f}" fill="#3c8c3c" '
                   f'text-anchor="end">{c}</text>')
    for r in range(0, 31, 10):
        out.append(f'<text x="{ml + pw + 4}" y="{yr(r) + 4:.1f}" fill="#b07c00">{r}</text>')
    step = 60
    for t in range(0, int(t_max) + 1, step):
        out.append(f'<line x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{mt}" y2="{mt + ph}" '
                   f'stroke="#132813" stroke-width="1"/>')
        out.append(f'<text x="{x(t):.1f}" y="{height - 10}" fill="#3c8c3c" '
                   f'text-anchor="middle">{t // 60}</text>')
    out.append(f'<text x="{ml + pw}" y="{height - 1}" fill="#3c8c3c" '
               f'text-anchor="end">min</text>')

    def poly(coords: list[tuple[float, float]], color: str, w: float = 1.5) -> None:
        if len(coords) > 1:
            d = " ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in coords)
            out.append(f'<polyline points="{d}" fill="none" stroke="{color}" '
                       f'stroke-width="{w}"/>')

    if a.plan is not None:
        plan_pts = [(x(t), yt(f_to_c(bt))) for t, bt, _ in a.plan.curve[::5]]
        plan_ror = [(x(t), yr(f_to_c_delta(r))) for t, _, r in a.plan.curve[::5]
                    if t >= a.plan.tp_s]
        for coords, color in ((plan_pts, "#6e96ff"), (plan_ror, "#46609f")):
            if len(coords) > 1:
                d = " ".join(f"{cx:.1f},{cy:.1f}" for cx, cy in coords)
                out.append(f'<polyline points="{d}" fill="none" stroke="{color}" '
                           f'stroke-width="1.5" stroke-dasharray="5 4"/>')
        for label, t in (("DE", a.plan.dry_end_s), ("FC", a.plan.fc_s),
                         ("DROP", a.plan.drop_s)):
            at = a.plan.at(t)
            if at is None:
                continue
            cx, cy = x(t), yt(f_to_c(at[0]))
            out.append(f'<rect x="{cx - 4:.1f}" y="{cy - 4:.1f}" width="8" height="8" '
                       f'fill="none" stroke="#6e96ff"/>')
            out.append(f'<text x="{cx:.1f}" y="{cy + 16:.1f}" fill="#6e96ff" '
                       f'text-anchor="middle">{label} {fmt_time(t)}</text>')
    poly([(x(s.elapsed - t0), yt(f_to_c(s.et))) for s in pts], "#1eb41e", 1.2)
    poly([(x(s.elapsed - t0), yt(f_to_c(s.bt))) for s in pts], "#33ff33", 2.0)
    poly([(x(t), yr(f_to_c_delta(r))) for t, r in a.ror_curve], "#ffb000", 1.5)

    marks = [("CHG", 0.0, a.charge_bt_f)]
    for label, ev in (("TP", a.turning_point), ("DE", a.dry_end), ("FC", a.first_crack),
                      ("SC", a.second_crack), ("DROP", a.drop)):
        if ev is not None:
            marks.append((label, ev.time_s, ev.bt_f))
    for label, t, bt in marks:
        if bt is None:
            continue
        cx, cy = x(t), yt(f_to_c(bt))
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.5" fill="#ffb000"/>')
        out.append(f'<text x="{cx:.1f}" y="{cy - 7:.1f}" fill="#ffb000" '
                   f'text-anchor="middle">{label} {fmt_time(t)}</text>')
    out.append(f'<text x="{ml + 6}" y="{mt + 14}" fill="#33ff33">BT</text>'
               f'<text x="{ml + 30}" y="{mt + 14}" fill="#1eb41e">ET</text>'
               f'<text x="{ml + 54}" y="{mt + 14}" fill="#ffb000">RoR C/min</text>'
               + (f'<text x="{ml + 130}" y="{mt + 14}" fill="#6e96ff">- - plan</text>'
                  if a.plan is not None else ""))
    out.append("</svg>")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

STYLE = """
:root { color-scheme: dark; }
body { background:#050805; color:#33ff33; font-family: ui-monospace, Menlo, monospace;
       margin:0; padding:12px 16px 40px; max-width:980px; margin-inline:auto; }
a { color:#ffb000; }
h1,h2 { font-weight:normal; letter-spacing:1px; }
h1 { font-size:1.3em; } h2 { font-size:1.05em; border-bottom:1px solid #1e5a1e;
     padding-bottom:3px; margin-top:1.6em; }
table { border-collapse:collapse; width:100%; }
td, th { padding:4px 8px; border-bottom:1px solid #123012; text-align:left;
         vertical-align:top; }
th { color:#1eb41e; font-weight:normal; }
.scroll { overflow-x:auto; }
.num { text-align:right; font-variant-numeric: tabular-nums; }
.low, .high { color:#ffb000; } .ok { color:#33ff33; }
.bad { color:#ff5a3c; } .warn { color:#ffb000; } .info { color:#1eb41e; }
.good { color:#33ff33; }
.bar { display:flex; height:26px; border:1px solid #1e5a1e; margin:6px 0 2px; }
.bar div { min-width:0; display:flex; align-items:center; justify-content:center; font-size:.8em;
           overflow:hidden; white-space:nowrap; color:#cfe; }
.DRYING { background:#1b4a1b; } .MAILLARD { background:#5a4a14; }
.DEVELOPMENT { background:#6a2a1b; }
input, textarea, select { background:#0b140b; color:#33ff33; border:1px solid #1e5a1e;
       font:inherit; padding:6px; width:100%; box-sizing:border-box; }
button { background:#1e5a1e; color:#dfd; border:0; padding:8px 14px; font:inherit;
         cursor:pointer; }
label { display:block; margin:8px 0 2px; color:#1eb41e; }
.grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
        gap:4px 16px; }
.muted { color:#1e8a1e; font-size:.9em; }
.nav a { margin-right:14px; }
select { background:#0b140b; color:#33ff33; border:1px solid #1e5a1e; font:inherit;
         padding:6px; width:100%; }
"""


def esc(v: object) -> str:
    return html.escape("" if v is None else str(v))


def phase_bar_html(a: RoastAnalysis) -> str:
    if not a.phases or a.end_s <= 0:
        return ""
    cells = "".join(
        f'<div class="{p.name}" style="flex:{max(p.duration_s, 0.001):.1f}">'
        f'{esc(p.name[:3])} {fmt_time(p.duration_s)} ({p.pct or 0:.0f}%)</div>'
        for p in a.phases
    )
    return f'<div class="bar">{cells}</div>'


def plan_summary_html(a: RoastAnalysis) -> str:
    """One-line comparison with the coffee's plan."""
    if a.plan is None:
        return ""
    pl = a.plan

    def d(v: float | None) -> str:
        return "--" if v is None else f"{'+' if v >= 0 else '-'}{fmt_time(abs(v))}"

    parts = [
        f"Plan <b>{esc(pl.label)}</b>: dry end {fmt_time(pl.dry_end_s)}, FC "
        f"{fmt_time(pl.fc_s)} @ {f_to_c(pl.fc_bt_f):.0f} C, drop {fmt_time(pl.drop_s)} @ "
        f"{f_to_c(pl.drop_bt_f):.0f} C (DTR {pl.dtr_pct:.0f}%)."
    ]
    if a.live and a.bt_vs_plan_f is not None:
        parts.append(f"Now: BT {f_to_c_delta(a.bt_vs_plan_f):+.1f} C vs plan"
                     + (f", RoR {f_to_c_delta(a.ror_vs_plan_f):+.1f}"
                        if a.ror_vs_plan_f is not None else "") + ".")
    else:
        parts.append(f"Actual vs plan: dry end {d(a.dry_end_vs_plan_s)}, FC "
                     f"{d(a.fc_vs_plan_s)}, drop {d(a.drop_vs_plan_s)}.")
    return f"<p style='color:#6e96ff'>{' '.join(parts)}</p>"


def metrics_table_html(a: RoastAnalysis) -> str:
    def row(label: str, value: str, key: str | None = None, target: str = "") -> str:
        cls = a.status.get(key, "") if key else ""
        return (f'<tr><th>{esc(label)}</th><td class="num {cls}">{esc(value)}</td>'
                f'<td class="muted">{esc(target)}</td></tr>')

    from roastmaster.engine.analysis import DEFAULT_TARGETS as T

    def ev(p) -> str:
        return f"{fmt_time(p.time_s)} @ {f_to_c(p.bt_f):.1f} C" if p else "--"

    rows = [
        row("Total time", fmt_time(a.end_s), "total_time",
            f"{fmt_time(T.total_time_s[0])}-{fmt_time(T.total_time_s[1])}"),
        row("Charge BT", f"{f_to_c(a.charge_bt_f):.1f} C" if a.charge_bt_f else "--"),
        row("Turning point", ev(a.turning_point)),
        row("Dry end" + (" (auto)" if a.dry_end_auto else ""), ev(a.dry_end), None,
            f"{T.dry_end_c:g} C"),
        row("First crack", ev(a.first_crack)),
        row("Drop" if not a.live else "Now", ev(a.drop) if a.drop else
            f"{fmt_time(a.end_s)} @ {_c(a.end_bt_f)} C"),
        row("DTR", f"{a.dtr_pct:.1f}%" if a.dtr_pct is not None else "--", "dtr",
            f"{T.dtr_pct[0]:g}-{T.dtr_pct[1]:g}%"),
        row("Dev time", fmt_time(a.dev_time_s) if a.dev_time_s is not None else "--",
            "dev_time", f"{fmt_time(T.dev_time_s[0])}-{fmt_time(T.dev_time_s[1])}"),
        row("Dev delta-T", f"{_cd(a.dev_delta_f)} C" if a.dev_delta_f is not None else "--",
            "dev_delta", f"{T.dev_delta_c[0]:g}-{T.dev_delta_c[1]:g} C"),
        row("RoR at FC", f"{_cd(a.ror_fc_f)} C/min" if a.ror_fc_f is not None else "--",
            "ror_fc", f"{T.ror_fc_c[0]:g}-{T.ror_fc_c[1]:g}"),
        row("RoR at drop" if not a.live else "RoR now",
            f"{_cd(a.ror_end_f)} C/min" if a.ror_end_f is not None else "--",
            "ror_drop", f"{T.ror_drop_c[0]:g}-{T.ror_drop_c[1]:g}"),
        row("RoR crash", "YES" if a.crash else "no"),
        row("RoR flicks", " ".join(fmt_time(t) for t in a.flick_times_s) or "none"),
        row("Weight loss",
            f"{a.weight_loss_pct:.1f}%" if a.weight_loss_pct is not None else "--",
            "weight_loss", f"{T.weight_loss_pct[0]:g}-{T.weight_loss_pct[1]:g}%"),
    ]
    return f'<div class="scroll"><table>{"".join(rows)}</table></div>'


def phases_table_html(a: RoastAnalysis) -> str:
    rows = "".join(
        f"<tr><td>{esc(p.name)}</td><td class='num'>{fmt_time(p.duration_s)}</td>"
        f"<td class='num'>{p.pct or 0:.1f}%</td>"
        f"<td class='num'>{f_to_c(p.start_bt_f):.0f}&rarr;{f_to_c(p.end_bt_f):.0f} C</td>"
        f"<td class='num'>{_cd(p.avg_ror_f) or '--'}</td>"
        f"<td class='num'>{_num(p.avg_burner, '{:.0f}') or '--'}</td></tr>"
        for p in a.phases
    )
    return ("<div class='scroll'><table><tr><th>Phase</th><th>Time</th><th>%</th>"
            "<th>BT</th><th>Avg RoR</th><th>Avg burner</th></tr>"
            f"{rows}</table></div>")


def findings_html(a: RoastAnalysis) -> str:
    if not a.findings:
        return "<p class='muted'>No findings yet.</p>"
    items = "".join(
        f"<li class='{esc(f.level)}'><b>{esc(f.short)}</b><br>"
        f"<span class='muted'>{esc(f.detail)}</span></li>"
        for f in a.findings
    )
    return f"<ul>{items}</ul>"


def html_report(profile: RoastProfile, a: RoastAnalysis | None = None) -> str:
    """Self-contained HTML report (used as an email attachment)."""
    a = a or profile.analyze()
    title = f"Roast {profile.roast_id} {profile.coffee}".strip()
    notes = ""
    if profile.notes:
        notes += f"<h2>Roast notes</h2><p>{esc(profile.notes)}</p>"
    if profile.tasting_notes:
        notes += f"<h2>Tasting notes</h2><p>{esc(profile.tasting_notes)}</p>"
    rating = f" &middot; rating {profile.rating}/10" if profile.rating is not None else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{STYLE}</style></head><body>
<h1>{esc(profile.coffee or 'Roast')} &middot; {esc(profile.roast_date)}{rating}</h1>
{phase_bar_html(a)}
{plan_summary_html(a)}
{svg_chart(profile, a)}
<h2>Findings</h2>{findings_html(a)}
<h2>Key numbers</h2>{metrics_table_html(a)}
<h2>Phases</h2>{phases_table_html(a)}
{notes}
</body></html>"""
