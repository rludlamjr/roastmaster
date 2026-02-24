# RoastMaster - Retro Coffee Roasting Control System

## Project Overview

RoastMaster is a custom coffee roasting control system designed to run headless on a
Raspberry Pi, replacing a laptop running Artisan. It features a physical hardware control
panel (buttons and rotary encoders) and outputs to a CRT monitor via the Pi's composite
video out, with a 1980s-era retro aesthetic.

### Target Hardware
- **Roaster**: Kaleido M1 Lite (serial protocol via USB or Bluetooth)
- **Computer**: Raspberry Pi (composite video out to CRT)
- **Display**: CRT monitor via composite (NTSC, low resolution ~320x240 or 640x480)
- **Controls**: Physical buttons and rotary encoders (final hardware TBD, abstracted in software)

### Design Principles
- **Hybrid approach**: Port Artisan's battle-tested Kaleido serial protocol and PID logic
  rather than reverse-engineering from scratch. Build everything else fresh and lean.
- **Retro aesthetic**: The UI should look like it was written in the 1980s. Phosphor green
  or amber monochrome palette, chunky bitmap fonts, simple line-drawn graphs, minimal chrome.
- **Hardware abstraction**: All physical inputs go through an abstraction layer so we can
  develop on Mac with keyboard/mouse simulation and deploy to Pi with real hardware.
- **MVP-first**: Focus on the core roasting workflow before adding advanced features.

### MVP Feature Set
1. Connect to Kaleido M1 Lite, read Bean Temperature (BT) and Environment Temperature (ET)
2. Display real-time roasting curve on CRT (BT, ET, RoR)
3. Manual control of burner power, drum speed, and airflow via hardware panel
4. Mark key roast events: Charge, Turning Point, First Crack, Second Crack, Drop
5. Save and load roast profiles
6. Basic PID auto-control mode (ported from Artisan)

---

## Architecture

```
+------------------+     +------------------+     +------------------+
|   Hardware       |     |   Core Engine    |     |   Display        |
|   Abstraction    |---->|                  |---->|   (pygame)       |
|   Layer (HAL)    |     |   - Roast FSM    |     |                  |
|                  |     |   - PID Control  |     |   - Roast curve  |
|  Dev: keyboard   |     |   - RoR calc     |     |   - Temps/RoR    |
|  Pi:  GPIO/enc   |     |   - Event mgmt   |     |   - Controls     |
+------------------+     |   - Profile I/O  |     |   - Events       |
                         +------------------+     +------------------+
                                |
                                v
                         +------------------+
                         |   Kaleido Serial |
                         |   Driver         |
                         |   (from Artisan) |
                         |                  |
                         |  Dev: simulator  |
                         |  Pi:  pyserial   |
                         +------------------+
```

### Module Breakdown

| Module | Responsibility | Key Dependencies |
|--------|---------------|-----------------|
| `roastmaster/hal/` | Hardware abstraction for inputs | `gpiozero` (Pi), `pygame` (dev) |
| `roastmaster/serial/` | Kaleido serial protocol driver | `pyserial` |
| `roastmaster/engine/` | Core roast logic, FSM, PID, RoR | None (pure logic) |
| `roastmaster/display/` | CRT rendering, retro UI | `pygame` |
| `roastmaster/profiles/` | Save/load roast profiles | `json` / filesystem |
| `roastmaster/sim/` | Simulators for dev without hardware | None |
| `roastmaster/config/` | App configuration | `toml` or `json` |
| `roastmaster/app.py` | Main application loop | All modules |

---

## Development Environment (Mac)

The dev environment must allow full development and testing on a Mac without a
Raspberry Pi or Kaleido roaster connected.

### Setup
- **Python 3.11+** via pyenv or system Python
- **Virtual environment** managed with `uv` (fast, modern Python package manager)
- **pygame** for display (works natively on Mac, same code runs on Pi)
- **pytest** for testing
- **Ruff** for linting/formatting

### Simulators for Mac Development
1. **Roaster Simulator** (`roastmaster/sim/roaster_sim.py`)
   - Simulates Kaleido serial responses with realistic temperature curves
   - Responds to control commands (burner/drum/air) with physically plausible behavior
   - Can inject faults for testing error handling
   - Runs as either an in-process mock or a virtual serial port for integration testing

2. **Hardware Input Simulator** (`roastmaster/sim/input_sim.py`)
   - Maps keyboard keys to hardware buttons (e.g., F1=Charge, F2=FC, F3=Drop)
   - Maps mouse scroll or arrow keys to rotary encoder inputs
   - Displayed as an overlay or separate panel showing current mappings

3. **Display runs natively**
   - pygame window on Mac displays at the same resolution as the CRT
   - Optional: CRT shader/scanline effect for authentic preview on Mac

### Project Structure
```
roastmaster/
  pyproject.toml          # Project config, dependencies, scripts
  README.md               # Quick start for developers
  PLAN.md                 # This file
  src/
    roastmaster/
      __init__.py
      app.py              # Main application entry point & game loop
      config.py           # Configuration management
      hal/
        __init__.py
        base.py           # Abstract input interface
        keyboard.py       # Mac dev: keyboard/mouse input backend
        gpio.py           # Pi: GPIO/encoder input backend
      serial/
        __init__.py
        kaleido.py        # Kaleido serial protocol driver (ported from Artisan)
        protocol.py       # Low-level serial packet handling
      engine/
        __init__.py
        roast.py          # Roast state machine (idle, preheat, roasting, cooling)
        pid.py            # PID controller (ported from Artisan)
        ror.py            # Rate of Rise calculation and smoothing
        events.py         # Roast event management (charge, FC, drop, etc.)
      display/
        __init__.py
        renderer.py       # Main display renderer (pygame)
        widgets.py        # Reusable UI components (graph, gauges, text)
        fonts.py          # Bitmap font loading and rendering
        theme.py          # Color palette and retro styling constants
      profiles/
        __init__.py
        manager.py        # Save/load/list roast profiles
        schema.py         # Profile data format
      sim/
        __init__.py
        roaster_sim.py    # Simulated Kaleido roaster
        input_sim.py      # Keyboard-to-hardware-input mapping
  tests/
    __init__.py
    test_engine/
    test_serial/
    test_display/
    test_profiles/
  assets/
    fonts/                # Bitmap/pixel fonts for retro look
    profiles/             # Sample roast profiles
  scripts/
    run_dev.sh            # Launch in dev mode on Mac
    run_pi.sh             # Launch in production mode on Pi
```

---

## Development Phases

### Phase 1: Project Scaffolding & Dev Environment
> Goal: Get a working dev environment with a pygame window showing a placeholder screen.

**Tasks:**

- [x] **1.1** Initialize Python project with `pyproject.toml`, configure `uv`, set up
  virtual environment, add core dependencies (pygame, pyserial, pytest, ruff)
- [x] **1.2** Create the project directory structure (all `__init__.py` files, empty modules)
- [x] **1.3** Create a minimal `app.py` main loop that opens a pygame window at 640x480,
  fills it with a dark background, and displays "ROASTMASTER v0.1" in a retro font
- [x] **1.4** Set up pytest with a basic smoke test that imports the main modules
- [x] **1.5** Create `run_dev.sh` script that activates venv and launches the app in dev mode
- [x] **1.6** Add ruff config to `pyproject.toml` and verify linting passes

**Acceptance criteria**: Running `python -m roastmaster` opens a pygame window with retro
text on a dark background. Tests pass. Linting passes.

---

### Phase 2: Retro Display System
> Goal: Build the CRT rendering engine with the 1980s aesthetic.

**Tasks:**

- [x] **2.1** Define the retro color theme in `theme.py`: phosphor green/amber palette,
  background color, grid colors, text colors. Support switching between green and amber modes.
- [x] **2.2** Find or create a suitable bitmap/pixel font (8x8 or similar). Implement font
  loading and text rendering in `fonts.py`. Must support digits, letters, and basic symbols.
- [x] **2.3** Build the graph widget in `widgets.py`: a real-time scrolling line graph that
  draws temperature curves over time. Should look like an oscilloscope trace. Features:
  - X axis = time (minutes:seconds)
  - Y axis = temperature (Fahrenheit or Celsius, configurable)
  - Grid lines (dotted or dashed, subtle)
  - Multiple traces in different shades (BT, ET, RoR)
  - Smooth scrolling as time progresses
- [x] **2.4** Build additional widgets: numeric readout displays (current BT, ET, RoR as
  large numbers), status bar (roast phase, elapsed time), control indicators (burner %,
  drum %, air %)
- [x] **2.5** Build the main screen layout in `renderer.py`: compose all widgets into the
  roasting screen. Layout should be:
  - Top: large numeric readouts (BT, ET, RoR)
  - Center: roasting curve graph (takes most of the screen)
  - Bottom: control indicators and roast phase/timer
- [x] **2.6** Feed the display with fake/random data to verify rendering. Add optional
  scanline effect for extra retro feel.

**Acceptance criteria**: The pygame window shows a convincing 1980s-style roasting display
with animated fake data. Readable, functional, and aesthetically retro.

---

### Phase 3: Roaster Simulator
> Goal: Build a realistic Kaleido roaster simulator for development without hardware.

**Tasks:**

- [x] **3.1** Clone the Artisan repo (`git clone https://github.com/artisan-roaster-scope/artisan.git`
  into a `reference/` directory) and study `src/artisanlib/kaleido.py`, `comm.py`, and
  `pid.py`. Document the exact Kaleido protocol: ASCII text message format, command tags,
  response parsing, timing requirements, and init sequence. Write this
  up as `docs/kaleido-protocol.md`. Key finding: the protocol uses ASCII text frames
  (`{[TAG value]}\n`), NOT binary frames. No checksum.
- [x] **3.2** Implement the roaster physics model in `roaster_sim.py`: simulate realistic
  bean temperature curves based on burner power, drum speed, and airflow inputs.
  - Start cold (~ambient)
  - Heat response follows thermal dynamics (lag, momentum)
  - First crack occurs around 385-400F
  - Cooling when burner off
- [x] **3.3** Implement the simulated serial interface: the simulator speaks the same
  protocol as the real Kaleido, so the driver code doesn't know the difference.
  Two modes:
  - In-process mock (for unit tests and fast dev) — implemented via SimulatedRoasterDevice
  - Virtual serial port pair (for integration testing the full serial stack) — deferred
- [x] **3.4** Add configurable fault injection: disconnects, garbled data, timeouts,
  sensor failures. Implemented in `sim/device_adapter.py` via `FaultConfig` / `FaultType`.
  Supports trigger delays, duration, and permanent faults.

**Acceptance criteria**: The roaster simulator produces realistic temperature curves that
respond to control inputs. It can be used in place of a real Kaleido for all development.

---

### Phase 4: Kaleido Serial Driver
> Goal: Port Artisan's Kaleido serial communication code.

**Tasks:**

- [x] **4.1** Clean-room reimplementation of Kaleido protocol in `serial/kaleido.py`:
  ASCII text message format verified against Artisan source. Handles:
  - Connection setup (USB serial, 9600 baud default, 8-O-1)
  - PI/TU/SC init handshake sequence
  - Reading BT and ET via `{[RD A0]}\n` data request
  - Sending heater power (HP), drum speed (RC), fan speed (FC) commands
  - CL AR teardown on disconnect
- [x] **4.2** Create an abstract serial device interface so the driver and simulator are
  interchangeable (dependency injection / duck typing).
- [x] **4.3** Write integration tests using the roaster simulator from Phase 3.
- [ ] **4.4** Test with real Kaleido hardware (requires Pi or USB connection to Mac).
  Document any protocol quirks discovered.

**Acceptance criteria**: The serial driver can communicate with both the simulator and
(when available) the real Kaleido M1. All protocol commands work correctly.

---

### Phase 5: Core Roasting Engine
> Goal: Build the roast state machine, PID controller, and RoR calculation.

**Tasks:**

- [x] **5.1** Implement the roast state machine in `engine/roast.py`:
  - States: IDLE, PREHEAT, CHARGE, ROASTING, COOLING, DONE
  - Transitions triggered by user events or conditions
  - Tracks elapsed time, phase durations
- [x] **5.2** Implement roast event management in `engine/events.py`:
  - Events: Charge, Turning Point (auto-detected), Dry End, First Crack, Second Crack, Drop
  - Each event records timestamp and temperature
  - Turning Point auto-detection: first local minimum of BT after Charge
- [x] **5.3** Implement Rate of Rise calculation in `engine/ror.py`:
  - Calculate dBT/dt and dET/dt
  - Apply smoothing (moving average or similar, study Artisan's approach)
  - Handle edge cases (startup noise, event transitions)
- [x] **5.4** Port Artisan's PID controller into `engine/pid.py`:
  - Standard PID with configurable Kp, Ki, Kd
  - Anti-windup
  - Manual/auto switching (bumpless transfer)
  - Target temperature or target RoR modes
- [x] **5.5** Wire the engine together: roast loop reads temps from serial driver, updates
  state machine, calculates RoR, runs PID (if in auto mode), sends control commands back
  to roaster.
- [x] **5.6** Write comprehensive tests for all engine components using the simulator.

**Acceptance criteria**: A complete simulated roast can run from preheat through cooling,
with correct state transitions, RoR calculations, and PID control responding to the sim.

---

### Phase 6: Hardware Abstraction Layer & Input
> Goal: Build the input system with keyboard simulation for dev and GPIO for Pi.

**Tasks:**

- [x] **6.1** Define the abstract input interface in `hal/base.py`:
  - Button events: press, release, long-press
  - Encoder events: increment, decrement (with acceleration)
  - Named inputs: CHARGE, FC, SC, DROP, BURNER_UP, BURNER_DOWN, DRUM_UP, DRUM_DOWN,
    AIR_UP, AIR_DOWN, MODE_TOGGLE (manual/auto), PROFILE_SAVE, PROFILE_LOAD
- [x] **6.2** Implement the keyboard backend in `hal/keyboard.py`:
  - Map pygame keyboard events to the abstract input interface
  - Display a help overlay showing current key mappings (toggle with F12 or similar)
  - Default mappings:
    - F1=Charge, F2=FC, F3=SC, F4=Drop
    - Up/Down arrows = Burner power
    - Left/Right arrows = Airflow
    - +/- = Drum speed
    - M = Toggle manual/auto
    - S = Save profile, L = Load profile
- [x] **6.3** Implement the GPIO backend in `hal/gpio.py` (stub for now, full implementation
  when hardware is ready):
  - Button inputs via GPIO with debouncing
  - Rotary encoder inputs via GPIO
  - Map physical controls to the abstract input interface
- [x] **6.4** Wire HAL into the main app loop: inputs flow through HAL -> engine -> display.
- [x] **6.5** Test the full input -> engine -> display pipeline with keyboard controls.

**Acceptance criteria**: On Mac, keyboard controls drive the full roasting workflow.
The same app code will work on Pi with GPIO controls by swapping the HAL backend.

---

### Phase 7: Profile Management
> Goal: Save and load roast profiles for repeatability and review.

**Tasks:**

- [x] **7.1** Define the profile data schema in `profiles/schema.py`:
  - Metadata: roast date, coffee name/origin, weight, notes
  - Time series: arrays of (timestamp, BT, ET, RoR, burner%, drum%, air%)
  - Events: list of (event_type, timestamp, temperature)
  - Settings: PID parameters, control mode used
- [x] **7.2** Implement save/load in `profiles/manager.py`:
  - Save to JSON files in a profiles directory
  - List available profiles
  - Load a profile as a background reference curve
- [x] **7.3** Display background profile on the roast curve graph (as a dimmer trace)
  so the user can follow a previous successful roast. Implemented in `GraphWidget.set_reference()`
  with `REF_BT`, `REF_ET`, `REF_ROR` dim trace colours.
- [x] **7.4** Add a simple profile browser UI screen (list of profiles, select to load).
  Navigate with hardware buttons / keyboard arrows. Implemented as `ProfileBrowser` widget
  with overlay rendering, UP/DOWN navigation, Enter to select, L to cancel.

**Acceptance criteria**: User can save a completed roast, load it later as a reference,
and see it as a background trace during a new roast.

---

### Phase 8: Integration, Polish & Pi Deployment
> Goal: Bring it all together, polish the experience, and deploy to Raspberry Pi.

**Tasks:**

- [x] **8.1** Full integration test: run a complete simulated roast from IDLE through
  DONE using all real modules (not mocks). Verify data flow end-to-end.
  Implemented in `tests/test_e2e.py` — 5 tests covering complete lifecycle, mode toggle,
  profile browser, data integrity, and fault injection during roast.
- [x] **8.2** Error handling and resilience:
  - `_safe_sample()` wrapper with try/except around device reads
  - `_is_valid_reading()` rejects NaN and out-of-range sensor values
  - Consecutive error counter with "SENSOR OFFLINE" escalation
  - SIGINT handler for clean Ctrl-C shutdown
  - try/finally in main loop ensures device disconnect and pygame cleanup
  - Error handling around profile save/load operations
- [ ] **8.3** Performance profiling on Pi (when available):
  - Ensure pygame rendering is smooth at target frame rate
  - Ensure serial polling doesn't introduce latency
  - Optimize if needed (reduce draw calls, lower resolution, etc.)
- [ ] **8.4** Pi-specific setup:
  - Configure composite video output (resolution, overscan)
  - Auto-start on boot (systemd service)
  - Read-only filesystem protection (prevent SD card corruption)
- [ ] **8.5** Create deployment script: builds the project, copies to Pi, installs
  dependencies, configures services.
- [ ] **8.6** Test with real Kaleido M1 Lite hardware. Document setup procedure.

**Acceptance criteria**: RoastMaster runs reliably on a Raspberry Pi, displays correctly
on a CRT via composite out, communicates with the Kaleido M1 Lite, and can complete a
full roast cycle.

---

## Task Dependency Graph

```
Phase 1 (Scaffolding)
  |
  +---> Phase 2 (Display) --------+
  |                                |
  +---> Phase 3 (Simulator) --+   |
  |                            |   |
  +---> Phase 6 (HAL/Input) --+---+--> Phase 8 (Integration)
                               |   |
       Phase 4 (Serial) ------+   |
           |                       |
           v                       |
       Phase 5 (Engine) ----------+
           |                       |
           v                       |
       Phase 7 (Profiles) --------+
```

Phases 2, 3, and 6 can proceed in parallel after Phase 1.
Phase 4 needs Phase 3 (simulator for testing).
Phase 5 needs Phase 4 (serial driver).
Phase 7 needs Phase 5 (engine produces data to save).
Phase 8 needs everything.

---

## Technical Notes

### Kaleido Protocol (VERIFIED against Artisan source)

See `docs/kaleido-protocol.md` for the full specification.

**Transport**: WebSocket (`ws://host:80/ws`) or Serial (9600 baud, 8-O-1 default).
Same message format over both transports.

**Message format**: ASCII text, newline-delimited. **NOT binary frames.**
- Outgoing: `{[TAG]}\n` or `{[TAG value]}\n`
- Incoming: `{sid,var:value,var:value,...}\n`
- **No checksum, no binary framing.**

**Key commands (tags)**:
- `PI` — Ping (init handshake)
- `TU F` — Set temperature unit to Fahrenheit
- `SC AR` — Start session guard
- `RD A0` — Request all sensor data (BT, ET, AT, HP, FC, RC, etc.)
- `HP 80` — Set heater power to 80%
- `FC 50` — Set fan/air speed to 50
- `RC 60` — Set drum speed to 60
- `AH 1` — Enable PID auto-heat
- `TS 185` — Set target temperature to 185°

**Init sequence**: PI → TU → SC AR (must complete before polling)

**Temperature encoding**: ASCII decimal floats (e.g. `BT:185.3`), NOT binary.

**NOTE**: The original plan assumed a binary frame protocol with XOR checksum.
This was incorrect — verified by reading Artisan's `kaleido.py` source.

### Key Artisan Source Files to Study
| File | Purpose |
|------|---------|
| `src/artisanlib/kaleido.py` | Kaleido serial driver - THE critical file |
| `src/artisanlib/comm.py` | Communication dispatcher, device routing |
| `src/artisanlib/pid.py` | PID controller implementation |
| `src/artisanlib/main.py` | Sampling loop, slider->command wiring |

### Licensing Strategy
Artisan is **GPL-3.0**. Our approach:
- **Clean-room protocol implementation**: Study Artisan's source to understand the Kaleido
  protocol (factual information, not copyrightable), then write our own driver from that
  understanding. This avoids GPL obligations on our code.
- **PID from textbook**: PID is a well-known algorithm. Implement from first principles,
  not by copying Artisan's code.
- **RoR from standard math**: Finite difference with smoothing is standard signal processing.
- **Serial traffic capture**: Optionally sniff actual serial traffic between Artisan and
  the Kaleido to confirm protocol details independently.
- This means we can choose our own license (MIT, Apache 2.0, etc.) if we want.
- If at any point we decide to directly copy/port Artisan code instead, the project must
  adopt GPL-3.0.

### Display Resolution & Refresh
- Target: 640x480 @ 30fps (or 320x240 doubled) via composite NTSC
- pygame renders to a surface at native resolution, outputs to framebuffer on Pi
- On Mac dev: pygame window at same resolution

### Retro Aesthetic Guidelines
- **Colors**: Monochrome phosphor palette. Primary: green (#33FF33) or amber (#FFB000)
  on black (#000000 or #0A0A0A). Use brightness variations for emphasis, not hue.
- **Fonts**: 8x8 or 8x16 bitmap pixel font. No antialiasing. All caps optional.
- **Lines**: 1px lines for graphs. Dotted grid. No gradients or transparency.
- **Animation**: Simple, functional. Blinking cursor/indicators. Scrolling graph.
  No transitions or effects (except optional scanlines).
- **Layout**: Dense, information-rich. Like a scientific instrument, not a consumer app.
