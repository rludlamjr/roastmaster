# RoastMaster Hardware Build Guide

## Overview

This document covers the hardware build for the RoastMaster control panel — a
physical enclosure with switches, potentiometers, LED indicators, and analog
VU meters connected to a Raspberry Pi. The Pi runs the RoastMaster software
and communicates with the Kaleido M1 Lite roaster over USB serial.

For a concrete stripboard implementation of the MCP3008 + PCA9685 interface,
see `docs/stripboard-interface-board.md`.

```
                    +-------------------------------+
                    |       ROASTMASTER PANEL        |
                    |                                |
 Kaleido M1 Lite   |  [VU: BT]  [VU: ET]  [VU:RoR] |
 (USB serial) ---->|                                |
                    |  (o) PWR  (o) HEAT  (o) COOL   |
                    |  (o) MODE                      |
                    |                                |
                    |  BURNER [===]  AIR [===]        |
                    |  DRUM   [===]  SCROLL [===]    |
                    |                                |
                    |  [CHG] [FCS] [FCE]  (@) BROWSE  |
                    |  [SCS] [SCE] [DRP]  [SAVE]     |
                    |  [RST]                          |
                    |                                |
                    |  * PWR  * HEAT  * COOL         |
                    |  * ROAST  * FC                  |
                    |                                |
                    |  +------[640x480 LCD]------+   |
                    |  |                         |   |
                    |  +-------------------------+   |
                    +-------------------------------+
                                   |
                            Raspberry Pi 4/5

  Legend: (o) = toggle switch   [XX] = momentary button
          [===] = potentiometer  (@) = rotary encoder
          * = LED indicator
```

---

## Safety (Read First)

This panel is a convenience controller, **not** a safety system. Keep the
Kaleido’s own controls accessible and be ready to stop a roast from the roaster
itself if anything behaves unexpectedly.

- **Safe defaults on connect:** RoastMaster should connect with **heat and
  cooling commanded OFF** (`HS=0`, `CS=0`) and **heater power at 0** (`HP=0`)
  until the operator explicitly enables heat.
- **Maintained toggle switches:** Treat HEAT/COOL/MODE/POWER as *requests* and
  act only on **state changes** (edge-detect). On startup, ignore any toggle
  that is already ON until it has been turned OFF at least once (“arm”
  behavior). This prevents “surprise heat” after a reboot.
- **Emergency stop:** If you want a true hard stop, add a separate physical
  E‑STOP that removes power from the **roaster**, not just the Pi.
- **Don’t hard-cut Pi power:** Abruptly removing 5V can corrupt the microSD.
  Use an orderly shutdown or a dedicated soft-power board/HAT.

---

## 1. Core Platform

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Raspberry Pi 4 Model B (4GB) | ARM Cortex-A72, 4GB RAM | 1 | $55 | RPi 5 also works. 2GB sufficient but 4GB recommended |
| microSD card | 32GB+ Class 10 / A1 | 1 | $10 | For Raspberry Pi OS + RoastMaster |
| USB-C power supply | 5V 3A (RPi 4) or 5V 5A (RPi 5) | 1 | $10 | Official RPi PSU recommended |
| Heat sinks / fan | Passive or active cooling | 1 | $5 | Pi will be in an enclosure near a hot roaster |

---

## 2. Display

The RoastMaster UI is a 640x480 pygame application. Options:

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| **Option A:** 7" HDMI LCD | 800x480 or 1024x600, HDMI input | 1 | $35-55 | Easiest option. Mount in panel |
| **Option B:** Composite CRT | Any small CRT with RCA/composite in | 1 | $0-30 | Retro look. Pi 4/3/Zero can output composite via TRRS; Pi 5 needs HDMI→composite |
| HDMI cable (short) | 30cm-50cm | 1 | $5 | For panel-mount display |

**Recommendation:** A 7" HDMI IPS display is the practical choice. If you find
a small composite CRT (old security monitor, etc.), composite at ~640x480 can
give an authentic retro feel (easy on Pi 4/3/Zero; Pi 5 typically requires an
HDMI→composite adapter).

---

## 3. Input Controls

### 3a. Toggle Switches (4)

Standard panel-mount toggle switches. All switches are read via GPIO; the
POWER switch can optionally also be used with a dedicated soft-power board.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Toggle switch — POWER | SPST ON/OFF, panel-mount | 1 | $3 | GPIO input used as a shutdown request / soft-power signal (recommended); don’t hard-cut Pi 5V |
| Toggle switch — HEATER | SPST ON/OFF, panel-mount | 1 | $2 | GPIO input. Sends HS command to Kaleido |
| Toggle switch — COOLING | SPST ON/OFF, panel-mount | 1 | $2 | GPIO input. Sends CS command to Kaleido |
| Toggle switch — MODE | SPST ON/OFF, panel-mount | 1 | $2 | GPIO input. Manual/AUTO (RoastMaster software control) |
| 10K pull-up resistors | 1/4W through-hole | 4 | $1 (pack) | One per GPIO-connected toggle (internal pull-ups also available) |

**Power switch note (important):** Don’t wire a toggle directly inline with
the Raspberry Pi’s 5V rail unless you use a purpose-built “soft power”
module/HAT. Abruptly cutting 5V can corrupt the microSD.

Recommended options:

1. **Soft power module/HAT (best):** Use a Pi power management board that
   supports safe shutdown and latching power.
2. **GPIO shutdown request (simple):** Use the POWER toggle as a GPIO input
   only. When switched OFF, the Pi runs `shutdown -h now`. After it halts, you
   can remove USB‑C power.
3. **Manual shutdown (simplest):** Quit the app and run `systemctl poweroff`,
   then remove power.

### 3b. Potentiometers (3)

The Raspberry Pi has no analog inputs, so we need an external ADC. The
MCP3008 is an 8-channel, 10-bit SPI ADC — perfect for reading 3 pots with
room to spare.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Potentiometer — BURNER | 10K linear (B10K), panel-mount | 1 | $3 | Maps to 0-100% heater power |
| Potentiometer — AIR | 10K linear (B10K), panel-mount | 1 | $3 | Maps to 0-100% fan speed |
| Potentiometer — DRUM | 10K linear (B10K), panel-mount | 1 | $3 | Maps to 0-100% drum speed |
| Potentiometer — SCROLL | 10K linear (B10K), panel-mount | 1 | $3 | Graph time-axis scroll. Center = live view, left = scroll back |
| Knobs | Aluminium or bakelite, 6mm shaft | 4 | $5 (pack) | Retro look — chicken-head or pointer knobs |
| MCP3008 | 8-ch 10-bit SPI ADC, DIP-16 | 1 | $4 | Reads all 4 pots. 4 spare channels |
| 16-pin DIP socket | For MCP3008 | 1 | $0.50 | Allows replacement without desoldering |
| 0.1 uF ceramic capacitor | Decoupling cap for MCP3008 | 1 | $0.10 | Place close to VDD pin |

**Wiring:** Each pot: one outer pin to 3.3V, other outer pin to GND, wiper
(center) to an MCP3008 analog input channel (CH0-CH3).

**SCROLL pot behavior:** The ADC value (0-1023) maps to the graph time axis.
The upper ~10% of travel (~920-1023) snaps to "live" mode (graph tracks
current time). Below that, the value maps proportionally across the roast
timeline, scrolling the graph left into history. A deadband of ~10 ADC
counts prevents jitter.

### 3c. Momentary Push Buttons (7)

Panel-mount momentary push buttons for roast event marking and system control.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Momentary push button — CHARGE | Normally open, panel-mount | 1 | $2 | Marks charge event |
| Momentary push button — FCS | Normally open, panel-mount | 1 | $2 | First Crack Start |
| Momentary push button — FCE | Normally open, panel-mount | 1 | $2 | First Crack End (*) |
| Momentary push button — SCS | Normally open, panel-mount | 1 | $2 | Second Crack Start |
| Momentary push button — SCE | Normally open, panel-mount | 1 | $2 | Second Crack End (*) |
| Momentary push button — DROP | Normally open, panel-mount | 1 | $2 | Marks drop / end of roast |
| Momentary push button — RESET | Normally open, panel-mount | 1 | $2 | Resets roast (clears data, returns to idle) |
| 10K pull-up resistors | 1/4W through-hole | 7 | $1 (pack) | One per button (or use RPi internal pull-ups) |
| 0.1 uF ceramic capacitors | Debounce caps | 7 | $1 (pack) | One per button, wired across switch terminals |

**(*) Software note:** The current software has single `FIRST_CRACK` and
`SECOND_CRACK` events. We will need to add `FIRST_CRACK_END` and
`SECOND_CRACK_END` events to the engine to support the separate start/end
buttons.

**Debouncing:** Each button gets a 0.1 uF cap across its terminals for
hardware debouncing. The GPIO HAL will also implement software debounce
(~50ms lockout) as a second layer.

### 3d. Rotary Encoder + Save Button (Profile Management)

A rotary encoder with integrated push-button for browsing and loading saved
roast profiles. A separate momentary SAVE button provides one-press saving.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Rotary encoder with push switch | KY-040 or EC11, 20 detents/rev, panel-mount | 1 | $3 | Rotate = scroll profile list, push = select/confirm |
| Knob for encoder | Aluminium, 6mm D-shaft | 1 | $2 | Match the pot knobs for consistency |
| Momentary push button — SAVE | Normally open, panel-mount | 1 | $2 | One press saves current roast profile |
| 10K pull-up resistors | 1/4W through-hole | 3 | incl. | For CLK, DT, and SW pins (or use RPi internal pull-ups) |
| 0.1 uF ceramic capacitors | Debounce / filtering | 2 | incl. | One on CLK, one on DT to suppress contact bounce |

**How it works:**

The encoder has 3 signals: CLK, DT (direction), and SW (push button).

| Action | Signal | Software Event |
|--------|--------|---------------|
| Rotate clockwise | CLK/DT quadrature | `NAV_DOWN` (next profile) |
| Rotate counter-clockwise | CLK/DT quadrature | `NAV_UP` (previous profile) |
| Push (click) | SW goes LOW | `PROFILE_LOAD` (first push opens browser) or `CONFIRM` (second push loads selection) |

**Profile load workflow:**
1. Push encoder → profile browser opens on screen with "CANCEL" at top
2. Rotate to scroll through saved profiles
3. Push to load the highlighted profile as a reference overlay
4. (Or scroll to CANCEL and push to dismiss)

**Profile save workflow:**
1. Press the SAVE button at any time during or after a roast
2. Profile is auto-saved with a timestamp filename (e.g. `2026-02-24_143022.json`)
3. Status bar shows "SAVED: 2026-02-24_143022.json" for 3 seconds

Naming profiles is best done after the roast over SSH (`mv` the file), since
letter-by-letter input on a rotary encoder is tedious and error-prone during
a live roast.

**Wiring:**
```
  3.3V ----[10K]----+---- CLK (GPIO pin)
                    |
                 [0.1uF]
                    |
                   GND

  3.3V ----[10K]----+---- DT  (GPIO pin)
                    |
                 [0.1uF]
                    |
                   GND

  3.3V ----[10K]----+---- SW  (GPIO pin)
                    |
               [ENCODER]
                    |
                   GND
```

---

## 4. Output: LED Indicators

Panel-mount LED indicator lights for at-a-glance status.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| LED indicator — POWER | Green, 8mm or 12mm panel-mount, 3.3V | 1 | $2 | Wired directly to 3.3V rail (no GPIO needed) |
| LED indicator — HEATER | Red/amber, 8mm panel-mount | 1 | $2 | PCA9685-driven (PWM capable). Lit when heat is enabled |
| LED indicator — COOLING | Blue, 8mm panel-mount | 1 | $2 | PCA9685-driven (PWM capable). Lit when cooling is enabled |
| LED indicator — ROASTING | Green, 8mm panel-mount | 1 | $2 | PCA9685-driven. Lit during ROASTING phase |
| LED indicator — FIRST CRACK | Yellow, 8mm panel-mount | 1 | $2 | PCA9685-driven. Lit after FC event |
| Series resistors (if needed) | 220–1K ohm, 1/4W | 4-5 | $1 (pack) | Many panel indicators include a resistor; add one for bare LEDs |

**Tip:** Many panel-mount indicators are sold as “12V” and include a resistor.
If you want to drive indicators directly from the PCA9685 (3.3V logic), either
buy 3.3V indicators/bare LEDs + resistors, or add a transistor driver stage
with a 12V rail.

**Indicator wiring (typical, push-pull):** `PCA9685 channel -> resistor -> LED -> GND`.
If you choose open-drain outputs instead, wire the LED to `VCC` and let the
PCA9685 sink current.

---

## 5. Output: Analog VU Meters

Three analog panel meters driven by PWM, displaying BT, ET, and RoR in
real-time. This is the centerpiece of the retro aesthetic.

### Meters

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Analog panel meter — BT | DC 0-500 uA (or 0-1mA), ~45mm or 85mm | 1 | $8-15 | Bean Temperature. Label/scale: 0-500F |
| Analog panel meter — ET | DC 0-500 uA (or 0-1mA), ~45mm or 85mm | 1 | $8-15 | Environment Temperature. Label/scale: 0-500F |
| Analog panel meter — RoR | DC 0-500 uA (or 0-1mA), ~45mm or 85mm | 1 | $8-15 | Rate of Rise. Label/scale: 0-30 deg/min |

**Sourcing:** Search for "85C1 analog panel meter" or "DC microammeter panel
mount" on Amazon/eBay/AliExpress. The 85C1 series is inexpensive and comes in
various full-scale deflection ratings. The 0-500 uA or 0-1mA versions are
ideal for PWM driving.

**Custom scales:** You can print custom face plates (0-500F for BT/ET,
0-30 for RoR) on card stock and glue them over the existing scale.

### PWM Driver

The RPi only has 2 hardware PWM channels, but we need at least 3 for the
meters plus several for the LEDs. A PCA9685 gives us 16 channels of 12-bit PWM
over I2C, using only 2 GPIO pins.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| PCA9685 breakout | 16-ch 12-bit PWM, I2C | 1 | $6 | Adafruit #815 or generic. Drives all meters + LEDs |
| Series resistors (per meter) | Value depends on meter (see calc below) | 3 | $0.30 | Sets full-scale deflection current (and limits PWM edge current) |
| Smoothing capacitors (optional) | 1–10 uF, 16V | 3 | $0.50 | Often optional (meter movement is slow); add if you see jitter/buzz |

**Meter drive circuit (per meter, recommended):**
```
PCA9685 ch. ---[R_series]---+---[METER]--- GND
                            |
                         [C_smooth] (optional)
                            |
                           GND
```

**Sizing `R_series`:** Use the PCA9685 logic voltage (`VCC`, typically 3.3V)
and your meter’s full-scale deflection current (`I_fsd`). Also account for the
meter’s own coil resistance (`R_meter`, measure with a multimeter):

`R_series ≈ (VCC / I_fsd) - R_meter`

Examples (assumes `VCC=3.3V`):
- 0–1 mA meter with `R_meter=650Ω` → `R_series≈3.3k-0.65k≈2.7k` (use 2.7k)
- 0–500 µA meter with `R_meter=650Ω` → `R_series≈6.6k-0.65k≈5.9k` (try 5.6k–6.2k)

If you don’t know `R_meter`, start with a **larger** resistor value to protect
the meter, then decrease until full-scale reads correctly.

**PCA9685 output mode:** Prefer totem-pole (push-pull) outputs for this use.
Most PCA9685 libraries default to this. If you configure open-drain outputs,
you’ll need a pull-up and slightly different wiring.

The PCA9685 duty cycle (0-4095) maps linearly to the meter reading:
- BT meter: 0 = 0F, 4095 = 500F
- ET meter: 0 = 0F, 4095 = 500F
- RoR meter: 0 = 0 deg/min, 4095 = 30 deg/min

---

## 6. Interconnect and Wiring

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| GPIO breakout + ribbon cable | 40-pin T-cobbler or equivalent | 1 | $8 | Brings Pi GPIO to breadboard/PCB |
| Prototype PCB / perfboard | 70x90mm or larger, double-sided | 1-2 | $3 | Solder components. Or use breadboard for prototyping |
| Screw terminal blocks | 2-pin, 3-pin, 5.08mm pitch | 10 | $5 | Clean connections for switches, pots, meters |
| Hookup wire | 22 AWG stranded, assorted colors | 1 roll | $8 | Panel wiring |
| DuPont connectors + crimps | Male/female, assorted | 1 kit | $8 | For GPIO and breakout board connections |
| USB-A to USB-B cable | For Kaleido serial connection | 1 | $5 | Connects Pi to Kaleido's USB port |
| Standoffs / spacers | M2.5, nylon or brass | 1 kit | $5 | Mount Pi and PCB in enclosure |
| Heat shrink tubing | Assorted sizes | 1 pack | $5 | Insulate solder joints |

---

## 7. Enclosure

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Project enclosure | Metal or wood, ~300x200x100mm | 1 | $15-30 | Aluminium enclosures look great. Or build a wooden box for vintage feel |
| Panel label material | Dymo label maker, engraving, or printed overlay | 1 | $5-10 | Label all controls |

**Layout suggestion:** Meters across the top, display in the center, toggles
and knobs in the middle row, event buttons along the bottom. See the ASCII
diagram at the top of this document.

---

## 8. GPIO Pin Allocation

### SPI Bus (MCP3008 ADC)
| RPi Pin | GPIO | Function |
|---------|------|----------|
| 19 | GPIO10 (MOSI) | SPI data to MCP3008 |
| 21 | GPIO9 (MISO) | SPI data from MCP3008 |
| 23 | GPIO11 (SCLK) | SPI clock |
| 24 | GPIO8 (CE0) | MCP3008 chip select |

### I2C Bus (PCA9685 PWM driver)
| RPi Pin | GPIO | Function |
|---------|------|----------|
| 3 | GPIO2 (SDA) | I2C data |
| 5 | GPIO3 (SCL) | I2C clock |

### Toggle Switch Inputs (active LOW with pull-ups)
| RPi Pin | GPIO | Function |
|---------|------|----------|
| 16 | GPIO23 | Power toggle (shutdown request / soft power) |
| 29 | GPIO5 | Heater ON/OFF toggle |
| 31 | GPIO6 | Cooling ON/OFF toggle |
| 33 | GPIO13 | Mode MANUAL/AUTO toggle |

### Momentary Button Inputs (active LOW with pull-ups)
| RPi Pin | GPIO | Function |
|---------|------|----------|
| 36 | GPIO16 | CHARGE button |
| 37 | GPIO26 | FCS (First Crack Start) button |
| 38 | GPIO20 | FCE (First Crack End) button |
| 40 | GPIO21 | SCS (Second Crack Start) button |
| 35 | GPIO19 | SCE (Second Crack End) button |
| 32 | GPIO12 | DROP button |
| 12 | GPIO18 | RESET button |
| 22 | GPIO25 | SAVE button |

### Rotary Encoder (Profile Browser)
| RPi Pin | GPIO | Function |
|---------|------|----------|
| 11 | GPIO17 | Encoder CLK (rotation) |
| 13 | GPIO27 | Encoder DT (direction) |
| 15 | GPIO22 | Encoder SW (push button) |

### PCA9685 Channel Allocation
| Channel | Function |
|---------|----------|
| 0 | VU Meter: Bean Temperature (BT) |
| 1 | VU Meter: Environment Temperature (ET) |
| 2 | VU Meter: Rate of Rise (RoR) |
| 3 | LED: Heater ON |
| 4 | LED: Cooling ON |
| 5 | LED: Roasting active |
| 6 | LED: First Crack |
| 7-15 | Spare |

### MCP3008 Channel Allocation
| Channel | Function |
|---------|----------|
| CH0 | Potentiometer: Burner |
| CH1 | Potentiometer: Air |
| CH2 | Potentiometer: Drum |
| CH3 | Potentiometer: Scroll (graph time axis) |
| CH4-CH7 | Spare |

### Power
| RPi Pin | Function |
|---------|----------|
| 1 | 3.3V out (for pots, pull-ups, MCP3008 VDD) |
| 2 | 5V out (for PCA9685 V+, VU meters if needed) |
| 6, 9, 14, etc. | GND (use multiple for clean grounding) |

**Total GPIO used:** 21 pins (4 SPI + 2 I2C + 4 toggles + 8 buttons + 3 encoder).
Well within the Pi's usable GPIO, with room to spare.

---

## 9. Software + Pi Setup

### 9a. Software work required

Current status:
- Keyboard backend exists (`src/roastmaster/hal/keyboard.py`).
- GPIO backend is a stub (`src/roastmaster/hal/gpio.py`).

To support this panel:
- Implement `GPIOInput` to read switches/buttons/encoder with debouncing,
  **edge-detect**, and startup “arm” behavior for maintained toggles.
- Read pots via MCP3008 (SPI) with smoothing/deadband and calibration to
  0–100% for burner/air/drum.
- (Optional) Drive PCA9685 outputs (I2C) for panel LEDs + analog meters.
- (Optional) Add `FIRST_CRACK_END` / `SECOND_CRACK_END` event types if wiring
  those extra buttons; otherwise omit them or map them to existing events.

### 9b. Raspberry Pi OS setup checklist

- Enable **SPI** + **I2C** (`raspi-config` → Interface Options), then reboot.
- Ensure your user can access buses (`spi` / `i2c` groups) if needed.
- Verify hardware:
  - MCP3008 via `/dev/spidev0.0`
  - PCA9685 via `i2cdetect -y 1` (commonly shows as `0x40`)
- Disable display blanking/power-saving for kiosk-style use.
- Make the Kaleido port stable with a `udev` rule (e.g. symlink `/dev/kaleido`)
  so it doesn’t jump between `/dev/ttyUSB0`, `/dev/ttyUSB1`, etc.
- Autostart RoastMaster with a `systemd` service and log to `logs/` for post-run
  review.

---

## 10. Bill of Materials Summary

| Category | Items | Est. Total |
|----------|-------|-----------|
| Core platform (Pi, PSU, SD) | 3 | $75 |
| Display | 1 | $35-55 |
| Toggle switches | 4 | $12 |
| Potentiometers + knobs | 4+4 | $17 |
| Momentary buttons (events + reset + save) | 8 | $16 |
| Rotary encoder + knob | 1+1 | $5 |
| MCP3008 ADC + socket | 2 | $5 |
| PCA9685 PWM driver | 1 | $6 |
| LED indicators | 5 | $12 |
| VU meters | 3 | $25-45 |
| Resistors, caps, passives | assorted | $5 |
| Wiring, connectors, cable | assorted | $30 |
| Enclosure | 1 | $15-30 |
| USB cable (to Kaleido) | 1 | $5 |
| **TOTAL** | | **~$265-315** |

All parts are readily available from Amazon, Adafruit, SparkFun, Mouser,
or AliExpress.

---

## 11. Prototyping Order

Recommended build sequence:

1. **Breadboard phase:** Wire MCP3008 + 1 pot, 2 buttons, 1 LED on a
   breadboard. Implement `gpio.py` HAL and verify pot reads and button
   events work with the RoastMaster software.

2. **Add PCA9685 + 1 VU meter:** Verify PWM-to-meter driving works.
   Calibrate `R_series` for your specific meter.

3. **Full breadboard:** Wire all controls and verify end-to-end with
   the simulator before connecting to real hardware.

4. **Panel build:** Transfer to perfboard/PCB, mount everything in the
   enclosure, do final wiring.

5. **Live test:** Connect to Kaleido via USB, use `--test` mode first
   (read-only), then go live.

---

## 12. Circuit Schematic (Simplified)

```
                    3.3V
                     |
                   [10K]  <-- pull-up
                     |
  GPIO pin ----------+------[BUTTON]------GND
                     |
                  [0.1uF]  <-- debounce cap
                     |
                    GND


                    3.3V
                     |
            +--------+--------+--------+
            |        |        |        |
         [POT_1]  [POT_2]  [POT_3]  [POT_4]
         BURNER    AIR      DRUM     SCROLL
            |        |        |        |
          CH0      CH1      CH2      CH3
            |        |        |        |
         +--+--------+--------+--------+--+
         |           MCP3008               |
         |  VDD=3.3V  VREF=3.3V           |
         |  CLK=GPIO11                     |
         |  DOUT=GPIO9                     |
         |  DIN=GPIO10                     |
         |  CS=GPIO8                       |
         +--+------------------------------+


         +------------------------+
         |       PCA9685          |
         |  VCC=3.3V  V+=5V      |
         |  SDA=GPIO2             |
         |  SCL=GPIO3             |
         +--+-----+-----+--------+
            |     |     |
          ch0   ch1   ch2        ch3-ch6 -> LEDs (via resistors)
            |     |     |
        [R_series][R_series][R_series]  <-- sets full-scale current
            |       |       |
         [VU_BT] [VU_ET] [VU_RoR]
            |       |       |
           GND     GND     GND

        (Optional: add C_smooth across each meter to reduce PWM ripple)
```
