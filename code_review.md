# RoastMaster vs. Artisan (Kaleido M1 Lite) — Code Review

Scope: review the **Artisan reference implementation** in `reference/artisan/` and compare it to the current RoastMaster implementation in `src/roastmaster/`, with emphasis on:

- Serial communication safety/robustness for **Kaleido M1 Lite** over USB/Bluetooth serial
- Control methodology (manual + “auto/PID”)
- Saving/loading profiles and **automating** a roast from a saved profile

Update: the highest-risk serial-communication deviations highlighted below were addressed on
branch `kaleido-comm-artisan-style` (continuous reader + request/await correlation + per-tag
control de-duplication), with regression tests. The profile/PID gaps remain.

---

## Executive summary (risk-focused)

### Highest-risk deviations

1. **Serial comm interleaving / unread replies (fixed on `kaleido-comm-artisan-style`).**
   - Before: `src/roastmaster/app.py` called `set_heater/set_drum/set_fan` every loop tick (target 30 fps),
     while the driver wrote without continuously draining replies; `read_temperatures()` assumed the next line
     after `RD A0` contained `BT/ET`.
   - After: `src/roastmaster/serial/kaleido.py` now runs a continuous reader + write queue, parses all inbound
     messages, and `read_temperatures()` awaits a `BT` update after `RD A0`. Control writes are de-duplicated
     per tag to avoid spamming the roaster.
   - Remaining deltas vs Artisan: no auto-reconnect loop and no WebSocket transport; implementation is
     thread-based rather than asyncio.

2. **Profile save/load is currently not suitable for reliable replay/automation.**
   - Saving: profiles are built with empty `name` and saved without filename → default stem becomes `untitled` → repeated saves will overwrite `profiles/untitled.json`. (`src/roastmaster/app.py`, `src/roastmaster/profiles/manager.py`)
   - Time base: `ProfileSample.elapsed` is documented as “seconds since charge”, but RoastMaster records `session.fsm.elapsed` (time since app start), not `session.fsm.roast_elapsed`. (`src/roastmaster/app.py`, `src/roastmaster/engine/roast.py`, `src/roastmaster/profiles/schema.py`)
   - Automation: RoastMaster currently loads profiles only for **graph overlay** (`renderer.set_reference_profile`) and does not apply control values back to the roaster.

3. **“AUTO” mode is not equivalent to Artisan’s PID approach and appears incomplete.**
   - RoastMaster PID setpoint is never set in the app loop, so enabling AUTO will likely drive toward a default setpoint of `0.0` (and clamp outputs), which is not a meaningful roasting control mode. (`src/roastmaster/app.py`, `src/roastmaster/engine/pid.py`)
   - Artisan’s Kaleido PID integration uses the **machine’s** PID (`AH`/`TS`) when configured (`reference/artisan/src/artisanlib/pid_control.py` + `reference/artisan/src/artisanlib/kaleido.py`), rather than a new, ad-hoc controller.

---

## 1) Serial communication (Kaleido over serial)

### 1.1 What Artisan does (reference behavior)

Key implementation: `reference/artisan/src/artisanlib/kaleido.py` (`KaleidoPort`)

- Uses an **async loop + continuous reader** (`serial_handle_reads`) that `readline()`s and calls `process_message()` for *every* incoming line.
- Uses a **write queue** and separates:
  - fire-and-forget `send_msg()` (enqueue write)
  - request/response `send_request()` (enqueue write + wait for a specific variable update using an `asyncio.Event`)
- Performs the Kaleido init handshake:
  1. Ping (`PI`) until a valid `sid` appears
  2. Set temperature unit (`TU`)
  3. Start guard (`SC AR`)
- Implements reconnect loops, timeouts, and state reset on disconnect.

### 1.2 What RoastMaster does (current behavior)

Key implementation: `src/roastmaster/serial/kaleido.py` (`KaleidoDevice`)

- Synchronous `pyserial.Serial`, with background threads for I/O (continuous reader + queued writer).
- Performs init handshake (PI → TU → SC AR) via request/await while the reader thread runs.
- Reads temperatures by sending `RD A0` and awaiting a `BT` state update, then returning `BT/ET` from shared state.
- Control commands (`HP/RC/FC`) are queued and de-duplicated; replies/updates are continuously read/parsed.

### 1.3 Major deviation: handling of replies / message ordering

Artisan’s design strongly suggests this assumption:

> the device can emit messages in response to **multiple kinds of commands**, and the host must continuously read/process them to keep state coherent.

Before the comm refactor, RoastMaster assumed:

> the next line read after `RD A0` is *the* sensor broadcast containing `BT/ET`.

That is fragile if the device replies to `HP/FC/RC` with `{sid,HP:..., ...}` updates (or any other status line)
that can arrive between the `RD` write and the next `readline()`.

On `kaleido-comm-artisan-style`, RoastMaster continuously reads/processes all messages and uses an Artisan-style
request/await mechanism to wait for the expected variable update, making interleaving safe. De-duplication also
reduces unnecessary outbound traffic.

### 1.4 Serial settings (good alignment)

Artisan’s global defaults in `reference/artisan/src/artisanlib/comm.py` (`serialport.__init__`) are:

- baud `9600`, bytesize `8`, parity `O`, stopbits `1`, timeout `0.4`

RoastMaster defaults in `src/roastmaster/serial/kaleido.py` match those values.

### 1.5 Protocol encoding: potential documentation mismatch

RoastMaster code + tests implement the same encoding behavior as Artisan’s `create_msg()` (notably: `HP/FC/RC` allow one decimal, `TS` is rounded to an integer when encoded via `create_msg()`).

Previously, `docs/kaleido-protocol.md` described the opposite encoding. This has been corrected on
`kaleido-comm-artisan-style` to match:

- `reference/artisan/src/artisanlib/kaleido.py:create_msg()`
- `src/roastmaster/serial/kaleido.py:create_msg()`
- `tests/test_serial/test_kaleido.py`

This is primarily a maintenance trap (a future implementation based on the doc could break compatibility).

---

## 2) Control methodology (manual + auto/PID)

### 2.1 Artisan’s control pattern (relevant parts)

Artisan generally:

- Sends roaster control commands as *discrete actions* (slider/button actions), not continuously every UI frame.
- Keeps a continuously running comm loop (so acknowledgements/state updates are processed).
- For Kaleido specifically, it supports:
  - Direct control updates via Kaleido commands (via event actions and `kaleidoSendMessage*` slots in `reference/artisan/src/artisanlib/main.py`)
  - Optional **Kaleido PID mode**: toggling auto-heat (`AH`) and setting setpoint (`TS`) (`reference/artisan/src/artisanlib/pid_control.py` + `reference/artisan/src/artisanlib/kaleido.py`)

### 2.2 RoastMaster’s current control pattern (problematic for serial safety)

In `src/roastmaster/app.py` main loop:

- Step 3 transmits:
  - heater (unless AUTO, or COOLING/DONE)
  - drum (always)
  - fan (always)
- This happens every frame (target `FPS`), not at the 1 Hz sampling rate.

In `src/roastmaster/serial/kaleido.py`:

- `set_heater/set_drum/set_fan` enqueue de-duplicated writes; a continuous reader parses replies/updates.

Net effect: the app still *calls* setters every frame, but de-duplication + continuous inbound processing
substantially reduces the risk of backlog/interleaving issues (especially over Bluetooth serial).

### 2.3 RoastMaster AUTO mode is not Artisan-equivalent and likely incomplete

RoastMaster:

- Enables AUTO with `m` and then runs `pid.compute(session.current_ror, 1.0)` and sets heater to the result.
- Does not set `PIDController.setpoint` anywhere in the app loop.

So AUTO currently doesn’t map to any of Artisan’s proven behaviors:

- Artisan internal PID has extensive configuration and safety features.
- Artisan external Kaleido PID uses `AH`/`TS` (machine PID).

Even if RoastMaster’s PID were correct, the “AUTO” integration still needs a defined target (RoR setpoint schedule, temperature setpoint schedule, or background-follow strategy).

---

## 3) Profiles: save/load + automation/replay

### 3.1 What Artisan provides (background playback)

Artisan supports “background profiles” and can **replay** selected background events by:

- time
- BT
- ET
- mixed modes

with additional guardrails (e.g., fallback to time before TP, avoid replaying after DROP, optional ramping to avoid discontinuities).

The core logic lives in `reference/artisan/src/artisanlib/canvas.py` (see `playbackevent()` region; search for `backgroundPlaybackEvents`, `replayType`, `specialeventplaybackramp`).

This is the closest existing “battle-tested” implementation of profile automation in the repo.

### 3.2 What RoastMaster currently does

RoastMaster has:

- A JSON profile schema (`src/roastmaster/profiles/schema.py`)
- A filesystem manager (`src/roastmaster/profiles/manager.py`)
- UI flow to load a profile and show it as a **reference overlay** (`src/roastmaster/app.py`, `src/roastmaster/display/renderer.py`)

RoastMaster does **not** currently:

- apply loaded control values back to the device
- implement playback modes (by time/BT/ET)
- implement ramping/guardrails like Artisan’s

### 3.3 Obvious issues in current save/load behavior

1. **Profiles overwrite by default**: `RoastSession.build_profile()` creates `RoastProfile()` without setting `name`; `ProfileManager.save()` derives filename from `profile.name` → `untitled.json`.
2. **Elapsed time base mismatch**:
   - Schema/docstrings indicate “since charge”
   - App records “since app start”
   - This will break any attempt to replay “from charge” unless corrected or compensated.

---

## 4) Alignment with your stated requirement (“use Artisan core engine unchanged”)

Your requirement: “use the core engine of Artisan, especially serial communication, more or less unchanged.”

Current RoastMaster status:

- The Kaleido protocol is *implemented to look like* Artisan’s protocol, but it is not architecturally equivalent to Artisan’s `KaleidoPort` (no continuous reader loop, no request correlation, no reconnect loop).
- The control methodology differs substantially (continuous write spam vs. discrete action sends + continuous read processing).
- The PID and profile playback subsystems are not ported from Artisan.

If the goal is maximum safety/compatibility with Kaleido’s real-world behavior, the most important missing property in RoastMaster today is **Artisan-style continuous inbound processing** of device messages.

---

## Suggested next steps (non-code)

1. **Capture a real serial transcript** while running Artisan with your Kaleido M1 Lite:
   - Verify whether `HP/FC/RC` commands generate replies, and what those replies look like.
   - This will confirm whether RoastMaster’s current “single-line RD response” assumption is valid.
2. Decide on a compatibility approach:
   - **Port/Reuse** Artisan’s `KaleidoPort` behavior more directly (note: GPL implications if you copy code into non-GPL project), or
   - Implement an equivalent architecture: background reader + state machine + request/await mechanism.
3. Define the intended automation mode (to match Artisan semantics):
   - “Replay events by time” (easy baseline)
   - “Replay by BT/ET” (needs monotonicity/TP rules like Artisan)
   - Optional ramping between events
4. Fix the profile fundamentals before automation:
   - stable naming/versioning (no accidental overwrite)
   - consistent time base (charge-relative vs absolute)
   - explicit control events vs. per-sample control snapshots (either can work, but replay logic differs)
