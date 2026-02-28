# GPIO Breadboard Wiring — Prototype

**TEMPORARY** — This wiring is for the breadboard prototype using RC timing
for potentiometers. It will be replaced once the MCP3008 ADC arrives.

## Parts Needed

- 3x toggle switches (SPST or SPDT)
- 3x 10K linear potentiometers
- 3x 0.1µF ceramic capacitors
- Jumper wires
- Breadboard

## Toggle Switches

Toggle switches connect to GND with internal pull-ups enabled in software.
No external resistors needed — the Pi's internal pull-ups handle it.

| Control      | GPIO Pin | Board Pin | Wiring                      |
|-------------|----------|-----------|------------------------------|
| Heat switch | GPIO 17  | Pin 11    | One leg to GPIO 17, other to GND |
| Cool switch | GPIO 27  | Pin 13    | One leg to GPIO 27, other to GND |
| Mode switch | GPIO 22  | Pin 15    | One leg to GPIO 22, other to GND |

**GND** — Use any ground pin (Pin 6, 9, 14, 20, 25, 30, 34, 39).

Switch ON = shorted to GND = active (software reads as active-low).

```
  GPIO pin ──── [switch] ──── GND
                (toggle)
```

## Potentiometers (RC Timing)

Each pot uses a 0.1µF cap to form an RC circuit. The software discharges the
cap, then times how long it takes to charge back up through the pot resistance.
Higher resistance = longer charge time = higher percentage reading.

| Control    | GPIO Pin | Board Pin |
|-----------|----------|-----------|
| Burner pot | GPIO 5   | Pin 29    |
| Drum pot   | GPIO 6   | Pin 31    |
| Air pot    | GPIO 13  | Pin 33    |

### Wiring per pot

```
  3.3V ──── [pot wiper (middle pin)] ──── GPIO pin
                                             │
                                         [0.1µF cap]
                                             │
                                            GND
```

Step by step for each pot:

1. **Pot outer pin 1** → 3.3V (Pin 1 or Pin 17)
2. **Pot outer pin 3** → GND
3. **Pot wiper (middle pin)** → GPIO pin (see table above)
4. **0.1µF cap** between the GPIO pin and GND (as close to the Pi as possible)

### How it works

The software cycles through three phases per pot read:
1. Drive GPIO LOW (output) for 5ms — discharges the cap
2. Switch GPIO to input — cap charges through pot resistance
3. Time how long until GPIO reads HIGH — maps to 0-100%

Full rotation of pot = ~1.5ms charge time = 100%.
Reads happen at 10Hz (not every frame) to keep things responsive.

## Pin Reference

```
                    Pi Header (top-down, USB ports at bottom)
                    ┌─────────────────────┐
            3.3V  1 │ ●               ● │ 2   5V
           SDA  3 │ ●               ● │ 4   5V
           SCL  5 │ ●               ● │ 6   GND
               7 │ ●               ● │ 8
           GND  9 │ ●               ● │ 10
  HEAT  GPIO17 11 │ ◉               ● │ 12
  COOL  GPIO27 13 │ ◉               ● │ 14  GND
  MODE  GPIO22 15 │ ◉               ● │ 16
          3.3V 17 │ ●               ● │ 18
              19 │ ●               ● │ 20  GND
              21 │ ●               ● │ 22
              23 │ ●               ● │ 24
          GND 25 │ ●               ● │ 26
              27 │ ●               ● │ 28
  BURN  GPIO5  29 │ ◉               ● │ 30  GND
  DRUM  GPIO6  31 │ ◉               ● │ 32
  AIR   GPIO13 33 │ ◉               ● │ 34  GND
              35 │ ●               ● │ 36
              37 │ ●               ● │ 38
          GND 39 │ ●               ● │ 40
                    └─────────────────────┘

  ◉ = pins used by this project
```

## Testing

On the Pi with switches and pots wired up:
```
uv run roastmaster --sim --gpio
```

On Mac (no GPIO hardware):
```
uv run roastmaster --sim --gpio
# Falls back to keyboard-only with a warning — no crash
```

## Notes

- The RC timing approach is approximate — don't expect lab-grade precision
- Pot readings may jitter ±2-3%. The 10Hz polling rate smooths this out
- If a pot reads stuck at 0 or 100, check the cap orientation and connections
- The MCP3008 ADC will replace this with proper 10-bit analog reads later
