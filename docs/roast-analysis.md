# Roast analysis, logging & export

What this adds (no hardware changes):

1. **Phase screen** on the CRT: drying / Maillard / development split, DTR, dev ΔT,
   RoR at first crack and at drop, crash/flick detection, and plain-language findings.
2. **Every roast is saved automatically** at DROP as `profiles/<date>_<time>.json`
   (previously every save overwrote `profiles/untitled.json`).
3. **A web page** on the Pi for the live roast, the roast log, notes, weights,
   ratings and CSV export.
4. **Optional email** of each roast report.

## Using it while roasting

| Control | What it does now |
|---|---|
| DEBUG toggle switch | Main graph ⇄ **phase screen** |
| Encoder push (graph) | Open the *WHICH COFFEE?* list (also shown at start-up and RESET) |
| Encoder turn (phase screen) | Change the coffee plan for this roast |
| Encoder push (phase screen) | Page: PHASES → PLAN → SYSTEM |
| DROP | Marks drop **and saves the roast** |
| SAVE | Saves again (includes the cooling tail) and emails it if set up |
| RESET | Saves any unsaved data (and auto-emails if set up) before clearing |
| POWER off | Same as RESET, then shuts down |

The info panel under the graph now shows the roast phase (`DRYING`, `MAILLARD`) and
during development the live DTR (`DEV 14.2%`) plus dev ΔT, so you can time the drop
without leaving the graph. The timer shows time since CHARGE.

Keyboard (dev on Mac): F12 = phase screen, PgUp/PgDn = coffee, L = coffee list / next page.

Coffee plans (target curves per coffee) are described in `coffee-plans.md`.

**Dry end** is auto-detected when BT passes 150 °C after the turning point.

## The web page

With the app running, open **`http://<pi-address>:8080`** on your phone (the address is
on the system page: phase screen → push the encoder). Since the Pi is only on while
roasting:

- **During the roast**: type the coffee name, batch weight and what you're trying.
  The page shows the live phase bar, "drop now would give…" numbers and a chart.
- **After the roast**: open it from the list and add the roasted weight.
- **Tasting notes**: add them next time the Pi is on (every past roast is editable),
  or reply to the emailed report and paste your notes to Claude with it.
- **Download all roasts (CSV)**: one row per roast with every metric plus your
  rating and tasting notes. This is the file to share with Claude to compare roasts.

Options: `--web-port 8080` (default), `--web-port 0` to disable.

## Email (optional)

Create `~/.config/roastmaster/email.toml` on the Pi:

```toml
smtp_host = "smtp.gmail.com"
smtp_port = 465
username  = "you@gmail.com"
password  = "xxxx xxxx xxxx xxxx"  # Gmail app password (Google Account → Security →
                                   # 2-Step Verification → App passwords)
to        = "you@gmail.com"
auto_send = true                   # email when a roast is finalized (RESET / power off)
```

Each email has a text summary in the body plus three attachments: an HTML report
(chart included, open in any browser), per-second samples as CSV, and the raw JSON.
SAVE always emails, and so does the "Email report" button on the web page.
`chmod 600` the file, since it holds a password.

## What the numbers mean

| Metric | Target (light / espresso) | Why it matters |
|---|---|---|
| Total time | 8:00–10:30 | Too fast → grassy/uneven; too slow → flat, baked |
| Drying % | 35–50% | Long drying = too little early energy → dull cups |
| DTR (dev time ÷ total) | 16–22% | Low → sour/grassy/peanut; high → muted, roasty |
| Dev time | 1:10–2:00 | Absolute time after FC |
| Dev ΔT (drop BT − FC BT) | 8–15 °C | How far past FC you actually went |
| RoR at FC | 6–12 °C/min | Too hot → hard to control; too low → stalls |
| RoR at drop | 2.5–7 °C/min | Below ~2 = stalled finish (bakes out sweetness) |
| RoR crash | none | RoR falls > 50% within 60 s of FC. The #1 cause of "boring" cups |
| RoR flick | none after FC | RoR rising again late. Roasty/bitter, usually after a crash |
| Weight loss | 12–14.5% | Best cheap measure of roast degree. Weigh before & after |

Targets are in `Targets` in `src/roastmaster/engine/analysis.py`. They are **starting
points**: once a few roasts are logged against tasting notes we can move them.

## Kaleido M1 notes that shaped this

- **The bean probe reads low.** M1 owners commonly see first crack at ~180–190 °C BT,
  well below the ~196 °C textbook value, and it varies between units. So nothing here
  depends on absolute FC temperature; checks are on times, ratios, ΔT and RoR shape.
  If dry end at 150 °C lands visibly late for your machine, lower `dry_end_c`.
- **Small drum, low thermal mass, fast response.** Heat changes show up in RoR within
  seconds. That makes crashes and flicks easy to cause (cutting heat hard at FC is the
  classic one) and is why crash/flick detection is front and centre.
- **Kaleido's own guide** recommends preheat ~180 °C SV, high heat early, "BT should
  develop at a slow pace", and first crack at 75–80% of total time (i.e. DTR 20–25%).
  For light espresso we aim a little lower (16–22%) but watch sour/underdeveloped
  notes; with a lever machine like the Europiccola, underdeveloped light roasts are
  hard to extract, so err toward the upper half of the DTR range at first.
- 170 g is a bit above Kaleido's 150 g reference batch, which slows everything down a
  little. More charge heat (or a slightly hotter preheat) compensates.

## Files

- `profiles/<id>.json`: the roast (samples, events, your notes, analysis summary in °C)
- Pull everything to a Mac: `scp -r <user>@<pi-address>:<app dir>/profiles ./roasts`
