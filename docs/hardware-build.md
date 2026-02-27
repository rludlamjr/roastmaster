# RoastMaster Hardware Build Guide

## Overview

This document covers the hardware build for the RoastMaster control panel — a
physical enclosure with switches, potentiometers, LED indicators, and analog
VU meters connected to a Raspberry Pi. The Pi runs the RoastMaster software
and communicates with the Kaleido M1 Lite roaster over USB serial.

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
                    |  DRUM   [===]                   |
                    |                                |
                    |  [CHG] [FCS] [FCE]  (@) BROWSE  |
                    |  [SCS] [SCE] [DRP]  [SAVE]     |
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
| **Option B:** Composite CRT | Any small CRT with RCA/composite in | 1 | $0-30 | Ultimate retro look. RPi outputs composite via 3.5mm jack |
| HDMI cable (short) | 30cm-50cm | 1 | $5 | For panel-mount display |

**Recommendation:** A 7" HDMI IPS display is the practical choice. If you find
a small composite CRT (old security monitor, etc.), the RPi's composite output
at 640x480 would give an authentic retro feel.

---

## 3. Input Controls

### 3a. Toggle Switches (4)

Standard panel-mount toggle switches. ON/OFF (SPST) for power; ON/OFF (SPST)
for the rest, read via GPIO.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Toggle switch — POWER | SPST ON/OFF, panel-mount, 6A rated | 1 | $3 | Inline with 5V power to Pi. NOT a GPIO switch (see shutdown notes below) |
| Toggle switch — HEATER | SPST ON/OFF, panel-mount | 1 | $2 | GPIO input. Sends HS command to Kaleido |
| Toggle switch — COOLING | SPST ON/OFF, panel-mount | 1 | $2 | GPIO input. Sends CS command to Kaleido |
| Toggle switch — MODE | SPST ON/OFF, panel-mount | 1 | $2 | GPIO input. Manual/Auto PID toggle |
| 10K pull-up resistors | 1/4W through-hole | 4 | $1 (pack) | One per GPIO-connected toggle (internal pull-ups also available) |

**Power switch note:** The power switch should NOT just cut power to the Pi —
that risks SD card corruption. Options:

1. **Recommended:** Wire the power toggle to a GPIO pin AND inline power. A
   shutdown script detects the toggle going OFF, runs `sudo shutdown -h now`,
   then the switch physically cuts power after a 5-second delay (use a simple
   RC timer + relay, or just wait and flip).
2. **Simple:** Just use `systemctl poweroff` from the UI (press Q to quit, Pi
   shuts down), then flip the power switch.

### 3b. Potentiometers (3)

The Raspberry Pi has no analog inputs, so we need an external ADC. The
MCP3008 is an 8-channel, 10-bit SPI ADC — perfect for reading 3 pots with
room to spare.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Potentiometer — BURNER | 10K linear (B10K), panel-mount | 1 | $3 | Maps to 0-100% heater power |
| Potentiometer — AIR | 10K linear (B10K), panel-mount | 1 | $3 | Maps to 0-100% fan speed |
| Potentiometer — DRUM | 10K linear (B10K), panel-mount | 1 | $3 | Maps to 0-100% drum speed |
| Knobs | Aluminium or bakelite, 6mm shaft | 3 | $5 (pack) | Retro look — chicken-head or pointer knobs |
| MCP3008 | 8-ch 10-bit SPI ADC, DIP-16 | 1 | $4 | Reads all 3 pots. 5 spare channels |
| 16-pin DIP socket | For MCP3008 | 1 | $0.50 | Allows replacement without desoldering |
| 0.1 uF ceramic capacitor | Decoupling cap for MCP3008 | 1 | $0.10 | Place close to VDD pin |

**Wiring:** Each pot: one outer pin to 3.3V, other outer pin to GND, wiper
(center) to an MCP3008 analog input channel (CH0-CH2).

### 3c. Momentary Push Buttons (6)

Panel-mount momentary push buttons for roast event marking.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| Momentary push button — CHARGE | Normally open, panel-mount | 1 | $2 | Marks charge event |
| Momentary push button — FCS | Normally open, panel-mount | 1 | $2 | First Crack Start |
| Momentary push button — FCE | Normally open, panel-mount | 1 | $2 | First Crack End (*) |
| Momentary push button — SCS | Normally open, panel-mount | 1 | $2 | Second Crack Start |
| Momentary push button — SCE | Normally open, panel-mount | 1 | $2 | Second Crack End (*) |
| Momentary push button — DROP | Normally open, panel-mount | 1 | $2 | Marks drop / end of roast |
| 10K pull-up resistors | 1/4W through-hole | 6 | $1 (pack) | One per button (or use RPi internal pull-ups) |
| 0.1 uF ceramic capacitors | Debounce caps | 6 | $1 (pack) | One per button, wired across switch terminals |

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
| LED indicator — HEATER | Red/amber, 8mm panel-mount | 1 | $2 | GPIO-driven. Lit when heater switch is ON |
| LED indicator — COOLING | Blue, 8mm panel-mount | 1 | $2 | GPIO-driven. Lit when cooling switch is ON |
| LED indicator — ROASTING | Green, 8mm panel-mount | 1 | $2 | GPIO-driven. Lit during ROASTING phase |
| LED indicator — FIRST CRACK | Yellow, 8mm panel-mount | 1 | $2 | GPIO-driven. Lit after FC event |
| 220 ohm resistors | 1/4W, current limiting for LEDs | 5 | $1 (pack) | ~(3.3V - 2.0V) / 220R = 6mA per LED |

**Tip:** Many panel-mount LED holders come with built-in resistors for 12V.
For 3.3V operation, get "bare" LED holders and add your own 220R resistors,
or buy 3.3V-rated panel-mount indicators.

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
meters plus 5 for the LEDs. A PCA9685 gives us 16 channels of 12-bit PWM
over I2C, using only 2 GPIO pins.

| Part | Spec | Qty | Est. Price | Notes |
|------|------|-----|-----------|-------|
| PCA9685 breakout | 16-ch 12-bit PWM, I2C | 1 | $6 | Adafruit #815 or generic. Drives all meters + LEDs |
| RC low-pass filter resistors | 10K 1/4W | 3 | $0.30 | One per meter channel |
| RC low-pass filter caps | 10 uF electrolytic, 16V | 3 | $0.50 | Smooths PWM into DC for meter needle |
| Current limiting resistors | Value depends on meter (see calc below) | 3 | $0.30 | Sets full-scale deflection current |

**Meter drive circuit (per meter):**
```
PCA9685 ch. ---[10K]---+---[R_limit]---[METER]--- GND
                        |
                     [10uF]
                        |
                       GND
```
The 10K + 10uF RC filter (tau = 100ms) smooths the PWM into a steady DC
voltage. The limiting resistor `R_limit` sets the full-scale current:

- For a 0-1mA meter at 3.3V: R_limit = 3.3V / 1mA = 3.3K (use 3.3K or 3.6K)
- For a 0-500uA meter at 3.3V: R_limit = 3.3V / 500uA = 6.6K (use 6.8K)

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
| 29 | GPIO5 | Heater ON/OFF toggle |
| 31 | GPIO6 | Cooling ON/OFF toggle |
| 33 | GPIO13 | Mode Manual/Auto toggle |

### Momentary Button Inputs (active LOW with pull-ups)
| RPi Pin | GPIO | Function |
|---------|------|----------|
| 36 | GPIO16 | CHARGE button |
| 37 | GPIO26 | FCS (First Crack Start) button |
| 38 | GPIO20 | FCE (First Crack End) button |
| 40 | GPIO21 | SCS (Second Crack Start) button |
| 35 | GPIO19 | SCE (Second Crack End) button |
| 32 | GPIO12 | DROP button |
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
| CH3-CH7 | Spare |

### Power
| RPi Pin | Function |
|---------|----------|
| 1 | 3.3V out (for pots, pull-ups, MCP3008 VDD) |
| 2 | 5V out (for PCA9685 V+, VU meters if needed) |
| 6, 9, 14, etc. | GND (use multiple for clean grounding) |

**Total GPIO used:** 20 pins (4 SPI + 2 I2C + 3 toggles + 7 buttons + 3 encoder + 1 save).
Well within the Pi's 26 usable GPIO pins, with 6 spare.

---

## 9. Software Changes Required

The GPIO HAL module (`src/roastmaster/hal/gpio.py`) needs to be implemented
to read physical controls instead of keyboard input. Key changes:

| Area | Change |
|------|--------|
| `InputEvent` enum | Add `FIRST_CRACK_END`, `SECOND_CRACK_END`, `HEATER_TOGGLE`, `COOLING_TOGGLE` |
| `EventType` enum | Add `FIRST_CRACK_END`, `SECOND_CRACK_END` |
| `gpio.py` HAL | Read MCP3008 for pot values, GPIO for switches/buttons, rotary encoder for navigation |
| `app.py` | Handle new events (HS/CS commands, crack end marking) |
| `app.py` | Drive PCA9685 for VU meters and LEDs each frame |
| `app.py` | Encoder push opens/confirms profile browser; SAVE button triggers auto-save |
| `config.py` | Add GPIO pin assignments, PCA9685 channel map, encoder pins |

The GPIO HAL will present the same interface as `KeyboardInput` — the rest
of the application doesn't need to change. The rotary encoder maps directly
to existing `NAV_UP`/`NAV_DOWN`/`CONFIRM`/`PROFILE_LOAD` events that the
profile browser already handles.

---

## 10. Bill of Materials Summary

| Category | Items | Est. Total |
|----------|-------|-----------|
| Core platform (Pi, PSU, SD) | 3 | $75 |
| Display | 1 | $35-55 |
| Toggle switches | 4 | $12 |
| Potentiometers + knobs | 3+3 | $14 |
| Momentary buttons (events + save) | 7 | $14 |
| Rotary encoder + knob | 1+1 | $5 |
| MCP3008 ADC + socket | 2 | $5 |
| PCA9685 PWM driver | 1 | $6 |
| LED indicators | 5 | $12 |
| VU meters | 3 | $25-45 |
| Resistors, caps, passives | assorted | $5 |
| Wiring, connectors, cable | assorted | $30 |
| Enclosure | 1 | $15-30 |
| USB cable (to Kaleido) | 1 | $5 |
| **TOTAL** | | **~$260-310** |

All parts are readily available from Amazon, Adafruit, SparkFun, Mouser,
or AliExpress.

---

## 11. Prototyping Order

Recommended build sequence:

1. **Breadboard phase:** Wire MCP3008 + 1 pot, 2 buttons, 1 LED on a
   breadboard. Implement `gpio.py` HAL and verify pot reads and button
   events work with the RoastMaster software.

2. **Add PCA9685 + 1 VU meter:** Verify PWM-to-meter driving works.
   Calibrate R_limit for your specific meter.

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
            +--------+--------+
            |        |        |
         [POT_1]  [POT_2]  [POT_3]
            |        |        |
          CH0      CH1      CH2
            |        |        |
         +--+--------+--------+--+
         |        MCP3008         |
         |  VDD=3.3V  VREF=3.3V  |
         |  CLK=GPIO11            |
         |  DOUT=GPIO9            |
         |  DIN=GPIO10            |
         |  CS=GPIO8              |
         +------------------------+


         +------------------------+
         |       PCA9685          |
         |  VCC=3.3V  V+=5V      |
         |  SDA=GPIO2             |
         |  SCL=GPIO3             |
         +--+-----+-----+--------+
            |     |     |
          ch0   ch1   ch2        ch3-ch6 -> LEDs (via 220R)
            |     |     |
         [10K] [10K] [10K]      <-- RC filter R
            |     |     |
            +     +     +
         [10uF][10uF][10uF]    <-- RC filter C
            |     |     |
         [R_lim][R_lim][R_lim] <-- sets full-scale current
            |     |     |
         [VU_BT][VU_ET][VU_RoR]
            |     |     |
           GND   GND   GND
```
