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

## Adding a coffee (with Claude)

1. Add it on the web page (or just send Claude the product link).
2. Claude writes `coffees/<id>.json` from the origin, process, altitude and cup notes,
   checks the curve (the test suite rejects plans whose RoR doesn't fall steadily),
   and commits it.
3. `git pull` on the Pi. The coffee appears in the list next start/reset.

## The current plans (v2, 2026-09-29)

| Coffee | Charge | TP | Dry end | FC | Drop | DTR | Dev ΔT |
|---|---|---|---|---|---|---|---|
| Ethiopia Limu G2 (washed, 1,900 m) | 195 °C | 0:42 | 3:50 | 7:15 @ 189 | 8:50 @ 198.5 | 17.9% | 9.5 |
| Honduras 18 Rabbit yellow honey (1,400 m) | 185 °C | 0:42 | 3:45 | 7:00 @ 188 | 8:40 @ 198.5 | 19.2% | 10.5 |
| Peru decaf Sol y Café (water process) | 180 °C | 0:42 | 3:55 | 5:45 @ 172 | 7:10 @ 182 | 19.8% | 10 |
| Peru Finca La Esperanza (washed, medium roast) | 188 °C | 0:42 | 3:45 | 7:30 @ 188 | 9:40 @ 203 | 22.4% | 15 |
| Brazil Oberon Cerrado (natural, medium roast) | 182 °C | 0:42 | 3:50 | 7:20 @ 186 | 9:30 @ 200 | 22.8% | 14 |
| PNG Mile High A (washed, 1,600 m, light) | 190 °C | 0:42 | 3:50 | 7:15 @ 188 | 8:50 @ 197.5 | 17.9% | 9.5 |
| India Monsooned Malabar AA (monsooned, medium) | 175 °C | 0:42 | 4:15 | 7:05 @ 182 | 9:05 @ 195 | 22.0% | 13 |
| Sumatra Mandheling G1 (wet hulled, dark) | 190 °C | 0:42 | 4:05 | 7:30 @ 188 | 10:25 @ 211 | 28.0% | 23 |

v2 comes from the first real roasts on 2026-09-29. The turning point on this drum is about
0:40, not 1:00. First crack showed at 188.9 °C for the Honduras and 172 °C for the decaf;
decaf cracks low. Every plan now needs a steady 10+ minute preheat and a lower burner at
charge. Burner steps start about 2 minutes before FC, because burner changes take roughly
45-60 s to show in RoR. The Limu FC (189) is still an estimate.
