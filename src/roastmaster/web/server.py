"""Built-in web page: live roast view, roast log, notes and exports.

Runs inside the roastmaster process on a background thread using only the
standard library.  Open ``http://<pi-address>:8080`` from a phone or laptop
on the same network.

Routes
------
GET  /                        live roast + current-roast form + roast log
GET  /live/fragment           live panel HTML (polled by the page)
GET  /live/chart.svg          live roast chart
POST /live                    set coffee / batch weight / notes for the roast in progress
GET  /roast/<id>              roast detail + edit form
POST /roast/<id>              save edits (coffee, weights, rating, notes, tasting notes)
POST /roast/<id>/email        email the report (if email is configured)
GET  /roast/<id>.json         raw profile
GET  /roast/<id>.csv          per-second samples
GET  /roast/<id>.html         standalone report
GET  /roasts.csv              one row per roast, for spreadsheets / comparison
GET  /coffees                 coffee library (plans) + add-a-coffee form
POST /coffees                 add a coffee (draft plan until developed with Claude)
GET  /coffee/<id>             plan, reasoning, target curve, and every roast of it
GET  /coffee/<id>.txt         plan + all roast summaries as text (paste to Claude)
GET  /coffee/<id>.json        the plan file
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
import socket
import threading
import urllib.parse
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from roastmaster.display.units import f_to_c, f_to_c_delta
from roastmaster.engine.analysis import fmt_time
from roastmaster.export.report import (
    STYLE,
    esc,
    findings_html,
    html_report,
    metrics_table_html,
    phase_bar_html,
    phases_table_html,
    plan_summary_html,
    samples_csv,
    summary_csv,
    summary_row,
    svg_chart,
    text_summary,
)
from roastmaster.profiles.coffees import Coffee, CoffeeLibrary, rest_text, rest_window
from roastmaster.profiles.manager import ProfileManager
from roastmaster.profiles.schema import RoastProfile
from roastmaster.web.live import LiveState

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")

# Called with a profile to email; returns an error string or "" on success.
EmailFn = Callable[[RoastProfile], str]


def local_ip() -> str:
    """Best-effort LAN address of this machine (no packets are sent)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


_NAV = "<p class=nav><a href='/'>Roast log</a><a href='/coffees'>Coffees</a></p>"


def _page(title: str, body: str, *, script: str = "") -> bytes:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title><style>{STYLE}</style></head><body>
{_NAV}{body}{f"<script>{script}</script>" if script else ""}</body></html>""".encode()


def _parse_float(v: str) -> float | None:
    try:
        return float(v) if v.strip() else None
    except ValueError:
        return None


def _parse_rating(v: str) -> int | None:
    try:
        r = int(float(v))
    except ValueError:
        return None
    return max(1, min(10, r))


class _Handler(BaseHTTPRequestHandler):
    # Injected by make_server()
    profiles: ProfileManager
    live: LiveState
    email_fn: EmailFn | None
    coffees: CoffeeLibrary

    server_version = "CONAR255/1.0"

    def log_message(self, fmt: str, *args: object) -> None:  # route to logging
        logger.debug("web: " + fmt, *args)

    # -- helpers ----------------------------------------------------------

    def _send(self, body: bytes, ctype: str = "text/html; charset=utf-8",
              status: int = 200, filename: str | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def _not_found(self) -> None:
        self._send(_page("Not found", "<h1>Not found</h1><a href='/'>Home</a>"), status=404)

    def _form(self) -> dict[str, str]:
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(min(n, 100_000)).decode("utf-8", "replace")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw, keep_blank_values=True).items()}

    def _load(self, roast_id: str) -> RoastProfile | None:
        if not _ID_RE.match(roast_id):
            return None
        try:
            p = self.profiles.load(roast_id)
        except (OSError, ValueError, KeyError):
            return None
        p.roast_id = p.roast_id or roast_id
        return p

    # -- routing ----------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/":
                return self._index()
            if path == "/live/fragment":
                return self._send(self._live_fragment().encode())
            if path == "/live/chart.svg":
                return self._live_chart()
            if path == "/coffees":
                return self._coffees_page()
            m = re.match(r"^/coffee/([^/]+?)(\.txt|\.json)?$", path)
            if m:
                c = self.coffees.get(m.group(1))
                if c is None:
                    return self._not_found()
                if m.group(2) == ".json":
                    return self._send(json.dumps(c.to_dict(), indent=2).encode(),
                                      "application/json", filename=f"{c.id}.json")
                if m.group(2) == ".txt":
                    return self._send(self._coffee_text(c).encode(),
                                      "text/plain; charset=utf-8")
                return self._coffee_page(c)
            if path == "/roasts.csv":
                return self._send(summary_csv(self.profiles.load_all()).encode(),
                                  "text/csv; charset=utf-8", filename="roasts.csv")
            m = re.match(r"^/roast/([^/]+?)(\.json|\.csv|\.html)?$", path)
            if m:
                p = self._load(m.group(1))
                if p is None:
                    return self._not_found()
                ext = m.group(2)
                if ext == ".json":
                    return self._send(json.dumps(p.to_dict(), indent=1).encode(),
                                      "application/json", filename=f"{p.roast_id}.json")
                if ext == ".csv":
                    return self._send(samples_csv(p).encode(), "text/csv; charset=utf-8",
                                      filename=f"{p.roast_id}_samples.csv")
                if ext == ".html":
                    return self._send(html_report(p).encode(), filename=f"{p.roast_id}.html")
                return self._detail(p)
            return self._not_found()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001 — never let a page error take down the app
            logger.exception("web GET %s failed", path)
            self._send(b"Internal error", "text/plain", status=500)

    def do_POST(self) -> None:  # noqa: N802
        path = urllib.parse.urlparse(self.path).path
        try:
            if path == "/live":
                return self._post_live()
            if path == "/coffees":
                return self._post_coffee()
            m = re.match(r"^/roast/([^/]+)/email$", path)
            if m:
                return self._post_email(m.group(1))
            m = re.match(r"^/roast/([^/]+)$", path)
            if m:
                return self._post_roast(m.group(1))
            return self._not_found()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001
            logger.exception("web POST %s failed", path)
            self._send(b"Internal error", "text/plain", status=500)

    # -- pages ------------------------------------------------------------

    def _index(self) -> None:
        snap = self.live.snapshot()
        meta = snap.meta
        coffees = self.profiles.recent_coffees()
        options = "".join(f"<option value='{esc(c)}'>" for c in coffees)
        plan_opts = "<option value=''>(no plan)</option>" + "".join(
            f"<option value='{esc(c.id)}'{' selected' if c.id == snap.coffee_id else ''}>"
            f"{esc(c.name)}{' (draft)' if c.status == 'draft' else ''}</option>"
            for c in self.coffees.all()
        )
        roasts = self.profiles.load_all()
        rows = []
        for p in roasts:
            r = summary_row(p)
            rows.append(
                f"<tr><td><a href='/roast/{esc(p.roast_id)}'>{esc(p.roast_date)}</a></td>"
                f"<td>{esc(p.coffee) or '<span class=muted>-</span>'}</td>"
                f"<td class=num>{esc(r['total_time'])}</td>"
                f"<td class=num>{esc(r['fc_time'])} {esc(r['fc_bt_c'])}</td>"
                f"<td class=num>{esc(r['dtr_pct'])}</td>"
                f"<td class=num>{esc(r['dev_delta_c'])}</td>"
                f"<td class=num>{esc(r['weight_loss_pct'])}</td>"
                f"<td class=num>{esc(r['rating'])}</td>"
                f"<td>{'crash ' if r['crash'] else ''}{'flick' if r['flicks'] else ''}</td>"
                f"<td>{self._ready_cell(p)}</td></tr>"
            )
        table = (
            "<div class=scroll><table><tr><th>Date</th><th>Coffee</th><th>Time</th>"
            "<th>FC (C)</th><th>DTR%</th><th>Dev&Delta;C</th><th>Loss%</th><th>Rating</th>"
            f"<th>RoR</th><th>Espresso</th></tr>{''.join(rows)}</table></div>"
            if rows else "<p class=muted>No saved roasts yet.</p>"
        )
        body = f"""
<h1>CONAR 255 &middot; ROAST LOG</h1>
<h2>Live</h2>
<div id="live">{self._live_fragment()}</div>
<img id="chart" src="/live/chart.svg" alt="" style="width:100%">
<h2>This roast</h2>
<form method="post" action="/live">
<label>Coffee plan</label><select name="coffee_id">{plan_opts}</select>
<div class="grid">
<div><label>Coffee name (if no plan)</label>
  <input name="coffee" list="coffees" value="{esc(meta.get('coffee', ''))}"
  placeholder="e.g. Reserva del Patron"><datalist id="coffees">{options}</datalist></div>
<div><label>Green weight (g)</label><input name="weight_g" inputmode="decimal"
  value="{esc(meta.get('weight_g', ''))}"></div>
</div>
<label>Roast notes (what you're trying)</label>
<textarea name="notes" rows="2">{esc(meta.get('notes', ''))}</textarea>
<p><button>Save</button></p>
</form>
<h2>Roasts</h2>
<p><a href="/roasts.csv">Download all roasts (CSV)</a></p>
{table}
"""
        script = """
async function tick(){
  try{
    const r = await fetch('/live/fragment'); if(r.ok){
      document.getElementById('live').innerHTML = await r.text(); }
    document.getElementById('chart').src = '/live/chart.svg?t=' + Date.now();
  }catch(e){}
}
setInterval(tick, 3000);
"""
        self._send(_page("Roast log", body, script=script))

    def _live_fragment(self) -> str:
        snap = self.live.snapshot()
        a = snap.analysis

        def c(v: float | None) -> str:
            return f"{f_to_c(v):.1f}" if v is not None else "--"

        ror = f"{f_to_c_delta(snap.ror_f):.1f}" if snap.ror_f is not None else "--"
        head = (
            f"<div class=grid><div>State <b>{esc(snap.fsm_phase)}</b></div>"
            f"<div>BT <b>{c(snap.bt_f)} C</b></div><div>ET {c(snap.et_f)} C</div>"
            f"<div>RoR <b>{ror}</b> C/min</div>"
        )
        if a is None or not a.charged:
            return head + "</div><p class=muted>Waiting for CHARGE.</p>"
        head += (
            f"<div>Time <b>{fmt_time(a.end_s)}</b></div>"
            f"<div>Phase <b>{esc(a.current_phase)}</b></div>"
            + (f"<div>DTR <b>{a.dtr_pct:.1f}%</b></div>" if a.dtr_pct is not None else "")
            + "</div>"
        )
        label = "Drop now would give:" if a.live else "Final:"
        link = ""
        if not a.live and snap.roast_id:
            link = f"<p><a href='/roast/{esc(snap.roast_id)}'>Open saved roast &rarr;</a></p>"
        return (head + phase_bar_html(a) + plan_summary_html(a)
                + f"<p class=muted>{label}</p>"
                + metrics_table_html(a) + "<h2>Findings</h2>" + findings_html(a) + link)

    def _live_chart(self) -> None:
        snap = self.live.snapshot()
        if snap.analysis is None or not snap.analysis.charged:
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 1" width="100%"'
                   ' height="1"></svg>')
        else:
            p = RoastProfile(samples=snap.samples, events=snap.events)
            svg = svg_chart(p, snap.analysis)
        self._send(svg.encode(), "image/svg+xml")

    def _detail(self, p: RoastProfile, message: str = "") -> None:
        a = p.analyze()
        email_btn = ""
        if self.email_fn is not None:
            email_btn = (f"<form method='post' action='/roast/{esc(p.roast_id)}/email' "
                         "style='display:inline'><button>Email report</button></form>")
        rating = "" if p.rating is None else str(p.rating)
        roasted = "" if p.roasted_weight_g is None else f"{p.roasted_weight_g:g}"
        msg = f"<p class=warn>{esc(message)}</p>" if message else ""
        plan_opts = "<option value=''>(no plan)</option>" + "".join(
            f"<option value='{esc(c.id)}'{' selected' if c.id == p.coffee_id else ''}>"
            f"{esc(c.name)}</option>"
            for c in self.coffees.all()
        )
        body = f"""
<p><a href="/">&larr; All roasts</a></p>
<h1>{esc(p.coffee or 'Roast')} &middot; {esc(p.roast_date)}</h1>
{self._ready_html(p)}
{msg}
{phase_bar_html(a)}
{plan_summary_html(a)}
{svg_chart(p, a)}
<h2>Findings</h2>{findings_html(a)}
<h2>Notes &amp; cup</h2>
<form method="post" action="/roast/{esc(p.roast_id)}">
<label>Coffee plan (change it if the wrong coffee was picked; uses that plan's current
version)</label><select name="coffee_id">{plan_opts}</select>
<div class="grid">
<div><label>Coffee</label><input name="coffee" value="{esc(p.coffee)}"></div>
<div><label>Green weight (g)</label><input name="weight_g" inputmode="decimal"
  value="{esc(f'{p.weight_g:g}' if p.weight_g else '')}"></div>
<div><label>Roasted weight (g)</label><input name="roasted_weight_g" inputmode="decimal"
  value="{esc(roasted)}"></div>
<div><label>Rating (1-10)</label><input name="rating" inputmode="numeric"
  value="{esc(rating)}"></div>
</div>
<label>Roast notes</label><textarea name="notes" rows="2">{esc(p.notes)}</textarea>
<label>Tasting notes (shot recipe, flavour, what's missing)</label>
<textarea name="tasting_notes" rows="5">{esc(p.tasting_notes)}</textarea>
<p><button>Save</button> {email_btn}</p>
</form>
<h2>Key numbers</h2>{metrics_table_html(a)}
<h2>Phases</h2>{phases_table_html(a)}
<h2>Download</h2>
<p><a href="/roast/{esc(p.roast_id)}.html">Report (HTML)</a> &middot;
<a href="/roast/{esc(p.roast_id)}.csv">Samples (CSV)</a> &middot;
<a href="/roast/{esc(p.roast_id)}.json">Raw (JSON)</a></p>
"""
        self._send(_page(f"Roast {p.roast_id}", body))

    # -- resting ---------------------------------------------------------

    def _rest_for(self, p: RoastProfile) -> dict:
        """Rest guidance for a roast: its plan snapshot, else the coffee's current plan."""
        rest = (p.plan or {}).get("rest") or {}
        if not rest and p.coffee_id:
            coffee = self.coffees.get(p.coffee_id)
            rest = coffee.rest if coffee else {}
        return rest

    def _ready_cell(self, p: RoastProfile) -> str:
        """Short 'when can I pull shots' status for the roast log."""
        win = rest_window(self._rest_for(p), p.roast_date)
        if win is None:
            return ""
        start, best, end = win
        today = dt.date.today()
        if today < start:
            return f"from {start:%b %d}"
        if today <= end:
            return "<span class=good>ready</span>" + (
                f" (best {best:%b %d})" if best and today < best else "")
        return "<span class=muted>past best</span>"

    def _ready_html(self, p: RoastProfile) -> str:
        rest = self._rest_for(p)
        win = rest_window(rest, p.roast_date)
        if win is None:
            return ""
        start, best, end = win
        best_txt = f", best around <b>{best:%a %b %d}</b>" if best else ""
        note = rest.get("note", "")
        note = f"<br><span class=muted>{esc(note)}</span>" if note else ""
        return (f"<p>Rest before espresso: {esc(rest_text(rest))}. Ready from "
                f"<b>{start:%a %b %d}</b>{best_txt}, at its best until {end:%a %b %d}.{note}</p>")

    # -- coffees ---------------------------------------------------------

    def _roasts_of(self, coffee_id: str) -> list[RoastProfile]:
        return [p for p in self.profiles.load_all() if p.coffee_id == coffee_id]

    def _coffees_page(self) -> None:
        rows = []
        for c in self.coffees.all():
            pl = c.plan
            n = len(self._roasts_of(c.id))
            dtr = (pl.drop_s - pl.fc_s) / pl.drop_s * 100
            rows.append(
                f"<tr><td><a href='/coffee/{esc(c.id)}'>{esc(c.name)}</a>"
                f"{' <span class=warn>draft</span>' if c.status == 'draft' else ''}</td>"
                f"<td>{esc(c.process)}</td><td class=num>{fmt_time(pl.fc_s)}</td>"
                f"<td class=num>{fmt_time(pl.drop_s)}</td><td class=num>{dtr:.0f}%</td>"
                f"<td class=num>v{c.version}</td><td class=num>{n}</td></tr>"
            )
        table = (
            "<div class=scroll><table><tr><th>Coffee</th><th>Process</th><th>FC</th>"
            "<th>Drop</th><th>DTR</th><th>Plan</th><th>Roasts</th></tr>"
            f"{''.join(rows)}</table></div>" if rows else "<p class=muted>No coffees yet.</p>"
        )
        body = f"""
<h1>COFFEES</h1>
{table}
<h2>Add a coffee</h2>
<p class=muted>Adds it with a generic starting plan (marked draft) so you can pick it on
the roaster straight away. Share the product link with Claude to develop a proper plan.</p>
<form method="post" action="/coffees">
<div class="grid">
<div><label>Name</label><input name="name" required placeholder="e.g. Kenya Nyeri AA"></div>
<div><label>Short name (CRT)</label><input name="short" maxlength="16"></div>
<div><label>Process</label><input name="process" placeholder="washed / natural / honey"></div>
<div><label>Altitude (m)</label><input name="altitude_m" inputmode="numeric"></div>
</div>
<label>Product page URL</label><input name="source_url">
<label>Vendor tasting notes</label><textarea name="vendor_notes" rows="2"></textarea>
<p><button>Add coffee</button></p>
</form>
"""
        self._send(_page("Coffees", body))

    def _coffee_page(self, c: Coffee) -> None:
        pl = c.plan
        chart = _plan_svg(c)
        steps = "".join(f"<li>{esc(st)}</li>" for st in c.steps)
        history = "".join(
            f"<li>v{esc(h.get('version'))} {esc(h.get('date'))}: {esc(h.get('note'))}</li>"
            for h in c.history
        )
        roast_rows = []
        for p in self._roasts_of(c.id):
            r = summary_row(p)
            roast_rows.append(
                f"<tr><td><a href='/roast/{esc(p.roast_id)}'>{esc(p.roast_date)}</a></td>"
                f"<td class=num>v{esc(r['plan_version'])}</td>"
                f"<td class=num>{esc(r['fc_time'])} ({esc(r['fc_vs_plan_s'] or '--')}s)</td>"
                f"<td class=num>{esc(r['total_time'])} ({esc(r['drop_vs_plan_s'] or '--')}s)</td>"
                f"<td class=num>{esc(r['dtr_pct'])}</td><td class=num>{esc(r['dev_delta_c'])}</td>"
                f"<td class=num>{esc(r['rating'])}</td><td>{esc(p.tasting_notes)}</td></tr>"
            )
        roasts = (
            "<div class=scroll><table><tr><th>Roast</th><th>Plan</th><th>FC (vs plan)</th>"
            "<th>Drop (vs plan)</th><th>DTR%</th><th>Dev&Delta;C</th><th>Rating</th>"
            f"<th>Tasting notes</th></tr>{''.join(roast_rows)}</table></div>"
            if roast_rows else "<p class=muted>Not roasted yet.</p>"
        )
        dtr = (pl.drop_s - pl.fc_s) / pl.drop_s * 100
        rest_section = ""
        if rest_text(c.rest):
            rest_section = (f"<h2>Rest before espresso</h2><p><b>{esc(rest_text(c.rest))}</b>. "
                            f"{esc(c.rest.get('note', ''))}</p>")
        body = f"""
<h1>{esc(c.name)}{' <span class=warn>(draft plan)</span>' if c.status == 'draft' else ''}</h1>
<p class=muted>{esc(c.origin)} &middot; {esc(c.process)}
{f"&middot; {c.altitude_m:g} m" if c.altitude_m else ""} &middot; {esc(c.variety)}
{f"&middot; <a href='{esc(c.source_url)}'>product page</a>" if c.source_url else ""}</p>
<p>{esc(c.vendor_notes)}</p>
<h2>Goal: {esc(c.goal)} &middot; plan v{c.version}</h2>
{chart}
<div class=scroll><table>
<tr><th>Preheat SV</th><td class=num>{pl.preheat_sv_c:g} C</td>
    <th>Charge BT</th><td class=num>{pl.charge_bt_c:g} C</td></tr>
<tr><th>Turning point</th><td class=num>{fmt_time(pl.tp_s)} @ {pl.tp_bt_c:g} C</td>
    <th>Dry end</th><td class=num>{fmt_time(pl.dry_end_s)}</td></tr>
<tr><th>First crack</th><td class=num>{fmt_time(pl.fc_s)} @ {pl.fc_bt_c:g} C</td>
    <th>Drop</th><td class=num>{fmt_time(pl.drop_s)} @ {pl.drop_bt_c:g} C</td></tr>
<tr><th>DTR</th><td class=num>{dtr:.1f}%</td>
    <th>Dev &Delta;T</th><td class=num>{pl.drop_bt_c - pl.fc_bt_c:.1f} C</td></tr>
</table></div>
<h2>Why</h2><p>{esc(c.rationale)}</p>
{rest_section}
<h2>How to fly it</h2><ol>{steps}</ol>
<h2>Roasts of this coffee</h2>{roasts}
<p><a href="/coffee/{esc(c.id)}.txt">Plan + all roasts as text</a> (paste this to Claude to
tune the plan) &middot; <a href="/coffee/{esc(c.id)}.json">Plan file</a></p>
<h2>Plan history</h2><ul>{history}</ul>
"""
        self._send(_page(c.name, body))

    def _coffee_text(self, c: Coffee) -> str:
        out = [f"COFFEE PLAN {c.id} v{c.version}", json.dumps(c.to_dict(), indent=2), ""]
        for p in reversed(self._roasts_of(c.id)):
            out += ["=" * 70, text_summary(p)]
        return "\n".join(out)

    def _post_coffee(self) -> None:
        f = self._form()
        name = f.get("name", "").strip()[:80]
        if not name:
            return self._redirect("/coffees")
        alt = _parse_float(f.get("altitude_m", ""))
        c = self.coffees.add_draft(
            name,
            short=(f.get("short", "").strip() or name)[:16].upper(),
            process=f.get("process", "").strip()[:60],
            altitude_m=alt,
            source_url=f.get("source_url", "").strip()[:300],
            vendor_notes=f.get("vendor_notes", "").strip()[:1000],
        )
        self._redirect(f"/coffee/{c.id}")

    # -- actions ----------------------------------------------------------

    def _post_live(self) -> None:
        f = self._form()
        fields: dict[str, object] = {}
        if "coffee_id" in f:
            cid = f["coffee_id"].strip()
            if cid == "" or self.coffees.get(cid) is not None:
                fields["coffee_id"] = cid
        if "coffee" in f:
            fields["coffee"] = f["coffee"].strip()[:80]
        if "weight_g" in f:
            w = _parse_float(f["weight_g"])
            if w is not None:
                fields["weight_g"] = w
        if "notes" in f:
            fields["notes"] = f["notes"].strip()[:2000]
        self.live.submit_meta(**fields)
        self._redirect("/")

    def _post_roast(self, roast_id: str) -> None:
        p = self._load(roast_id)
        if p is None:
            return self._not_found()
        f = self._form()
        p.coffee = f.get("coffee", p.coffee).strip()[:80]
        plan_changed = False
        cid = f.get("coffee_id", p.coffee_id).strip()
        if cid != p.coffee_id:
            coffee = self.coffees.get(cid) if cid else None
            if cid == "" or coffee is not None:
                # Reassign the roast: its coffee, id and the plan it is judged against
                plan_changed = True
                p.coffee_id = coffee.id if coffee else ""
                p.plan = coffee.snapshot() if coffee else {}
                if coffee is not None:
                    p.coffee = coffee.name
        p.weight_g = _parse_float(f.get("weight_g", "")) or 0.0
        p.roasted_weight_g = _parse_float(f.get("roasted_weight_g", ""))
        p.rating = _parse_rating(f.get("rating", ""))
        p.notes = f.get("notes", p.notes).strip()[:2000]
        p.tasting_notes = f.get("tasting_notes", p.tasting_notes).strip()[:5000]
        p.analysis = p.analyze().to_dict()
        self.profiles.save(p, filename=p.roast_id)
        # Keep the roast loop's copy in step if this is the roast in progress
        if self.live.snapshot().roast_id == p.roast_id:
            meta: dict[str, object] = {"coffee": p.coffee, "weight_g": p.weight_g,
                                       "notes": p.notes}
            if plan_changed:
                meta["coffee_id"] = p.coffee_id
            self.live.submit_meta(**meta)
        self._redirect(f"/roast/{p.roast_id}")

    def _post_email(self, roast_id: str) -> None:
        p = self._load(roast_id)
        if p is None:
            return self._not_found()
        if self.email_fn is None:
            return self._detail(p, "Email is not configured.")
        err = self.email_fn(p)
        self._detail(p, f"Email failed: {err}" if err else "Email sent.")


def _plan_svg(c: Coffee) -> str:
    """Target curve of a plan, drawn like a roast chart."""
    from roastmaster.engine.analysis import analyze_roast

    plan = c.plan_targets()
    a = analyze_roast([], [], plan=None)
    a.plan = plan
    a.charged = False
    return svg_chart(RoastProfile(samples=[], events=[]), a)


class RoastWebServer:
    """Owns the HTTP server thread."""

    def __init__(
        self,
        profiles: ProfileManager,
        live: LiveState,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        email_fn: EmailFn | None = None,
        coffees: CoffeeLibrary | None = None,
    ) -> None:
        handler = type("RoastHandler", (_Handler,), {
            "profiles": profiles, "live": live, "email_fn": staticmethod(email_fn)
            if email_fn else None,
            "coffees": coffees or CoffeeLibrary(),
        })
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="roast-web", daemon=True
        )

    @property
    def port(self) -> int:
        return self._httpd.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{local_ip()}:{self.port}"

    def start(self) -> None:
        self._thread.start()
        logger.info("Web page at %s", self.url)

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
