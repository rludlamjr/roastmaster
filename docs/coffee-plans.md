# Coffee plans

Each coffee you buy gets a **plan**: target milestones, a target curve drawn on the
graph, per-coffee target ranges for the analysis, and step-by-step burner/air guidance.
Plans live in `coffees/<id>.json` (committed to the repo).

## On the roaster

- **At start-up and after RESET** a *WHICH COFFEE?* list appears. Turn the knob, push
  to select. Pick **NEW / BLANK** for a coffee with no plan. The list doesn't block
  anything: HEAT, COOL and PREHEAT work underneath it, and CHARGE closes it and keeps
  the current choice.
- **Encoder push on the graph** re-opens the list at any time.
- The **graph** shows the plan as a dotted blue BT line and a fainter RoR line, with
  square markers at the planned dry end, FC and drop, aligned to your CHARGE.
- **Phase screen** (DEBUG switch): a blue `PLAN` line with the target times, and
  `VS PLAN BT +2.1 ROR -0.8` live (after the roast: `FC +0:20 DROP -0:05`).
  Push the encoder to page PHASES → PLAN → SYSTEM. The PLAN page shows the milestones
  and the how-to-fly-it steps. Turning the knob on these pages does nothing, so a stray
  touch mid-roast can't switch the plan; change coffee with the list (push on the graph).
- Findings add `BT 5C BEHIND PLAN` (live) and `FC 0:40 LATE` / `DROP ... EARLY`.

Each saved roast stores a snapshot of the plan version it was roasted against, so
comparing roasts stays honest after a plan is tuned.

## On the web page

- **Roast log → Coffee plan**: choose the plan from your phone during the roast.
- **Coffees**: every plan, and an **Add a coffee** form. A coffee added there gets a
  generic *draft* plan so you can use it immediately.
- **Coffee page**: the plan, the reasoning, the steps, and *every roast of that
  coffee* with FC/drop versus plan, DTR, dev ΔT, rating and tasting notes.
  **"Plan + all roasts as text"** gives everything in one block. Paste it to Claude
  to tune the plan.

## How a plan works

A plan is written as milestones (times in seconds since CHARGE, temperatures in °C):

```json
"plan": {
  "preheat_sv_c": 200, "charge_bt_c": 200,
  "tp_s": 60,  "tp_bt_c": 100,
  "peak_s": 120,
  "dry_end_s": 240,
  "fc_s": 435, "fc_bt_c": 186,
  "drop_s": 530, "drop_bt_c": 195.5,
  "dev_ror_ratio": 0.5
}
```

The curve is derived from these. RoR is modelled as straight segments through
TP → peak → dry end → FC → drop. The values are solved so the BT curve passes exactly
through the dry-end (150 °C), FC and drop milestones, with RoR at drop = half the RoR at
FC. The result always has a smoothly falling RoR, so **tuning is just moving a
milestone** ("FC 15 s later", "drop 2 °C hotter"). `targets` overrides the analysis
ranges (DTR, dev ΔT, total time...) for that coffee.

When a plan changes, bump `version` and add a `history` entry saying why.

## Resting before espresso

Each plan has a `rest` section: how many days the beans need after roasting before they're
good for espresso.

```json
"rest": {"min_days": 10, "best_days": 14, "max_days": 21,
         "note": "Dense, light-roasted washed Ethiopian degasses slowly..."}
```

It shows on the PLAN page (`REST BEFORE ESPRESSO: 10-21 DAYS (BEST 14)`) and on the coffee's
web page. Each roast's page turns it into dates ("Ready from Thu Oct 12, best around Mon Oct
16"), and the roast log's **Espresso** column says *from Oct 12*, *ready* or *past best*. The
rest is stored with each roast's plan snapshot, so changing it later doesn't rewrite old
roasts. Lighter and denser roasts need longer; dark roasts, naturals and decaf are ready (and
fade) sooner.

| Coffee | Rest (days) | Best |
|---|---|---|
| Ethiopia Limu G2 | 10-21 | ~14 |
| Honduras 18 Rabbit | 7-18 | ~10 |
| PNG Mile High A | 8-21 | ~12 |
| Peru Finca La Esperanza | 5-16 | ~8 |
| Brazil Oberon Cerrado | 4-14 | ~7 |
| India Monsooned Malabar | 5-18 | ~8 |
| Sumatra Mandheling G1 | 3-12 | ~5 |
| Peru decaf Sol y Café | 4-14 | ~7 |

## Adding a coffee (with Claude)

1. Add it on the web page (or just send Claude the product link).
2. Claude writes `coffees/<id>.json` from the origin, process, altitude and cup notes,
   checks the curve (the test suite rejects plans whose RoR doesn't fall steadily),
   and commits it.
3. `git pull` on the Pi. The coffee appears in the list next start/reset.

## The current plans (2026-10-02)

| Coffee | Plan | Charge | TP | Dry end | FC | Drop | DTR | Dev ΔT |
|---|---|---|---|---|---|---|---|---|
| Ethiopia Limu G2 (washed, light) | v3 | 195 °C | 0:36 @ 110 | 3:30 | 7:20 @ 189 | 8:55 @ 198.5 | 17.8% | 9.5 |
| Honduras 18 Rabbit yellow honey (light) | v3 | 185 °C | 0:36 @ 110 | 3:35 | 7:15 @ 188 | 8:55 @ 198.5 | 18.7% | 10.5 |
| PNG Mile High A (washed, light) | v2 | 190 °C | 0:36 @ 112 | 3:25 | 7:20 @ 188 | 8:55 @ 197.5 | 17.8% | 9.5 |
| Peru Finca La Esperanza (washed, medium) | v2 | 188 °C | 0:36 @ 108 | 3:45 | 7:15 @ 188 | 9:20 @ 203 | 22.3% | 15 |
| Brazil Oberon Cerrado (natural, medium) | v2 | 182 °C | 0:36 @ 108 | 3:40 | 7:20 @ 186 | 9:30 @ 200 | 22.8% | 14 |
| India Monsooned Malabar AA (medium) | v2 | 175 °C | 0:38 @ 115 | 3:20 | 6:25 @ 182 | 8:15 @ 195 | 22.2% | 13 |
| Sumatra Mandheling G1 (wet hulled, dark) | v3 | 190 °C | 0:36 @ 110 | 3:35 | 7:00 @ 183 | 10:00 @ 206 | 30.0% | 23 |
| Peru decaf Sol y Café (water process) | v3 | 180 °C | 0:36 @ 100 | 3:40 | 5:45 @ 172 | 7:10 @ 182 | 19.8% | 10 |

The opening is fitted to five real roasts (2026-09-29 to 10-02). On this roaster the turning
point comes at about 0:35 and is shallow (108-116 °C BT), and RoR is highest right after it
and only falls. Dry end lands around 3:35 and first crack around 7:15-7:25 at 187-189 °C
(decaf: 172 °C). Plans are built with `peak_s` = `tp_s` + 8 to reflect that. Don't cut heat
in the first 3 minutes to chase the line: a stalled Maillard followed by more heat is what
makes development run hot.
