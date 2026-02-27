# Kaleido (Artisan‑Style) Serial Comms — Development Tasks

Goal: make RoastMaster’s Kaleido communications behave like Artisan’s **KaleidoPort** in the ways that matter for safety and correctness:

- continuous inbound processing of device messages
- request/response correlation (await specific variable updates)
- robust against interleaved replies (control acks arriving between `RD` polls)
- predictable timeouts and clean shutdown (`CL AR`)

This document is intentionally concrete: each task has acceptance criteria and a suggested test.

---

## 0) Decision: “Use Artisan code directly” vs. “Clean‑room match”

### Option A — Directly reuse Artisan’s `KaleidoPort` implementation
Pros:
- maximum behavior fidelity
- already battle‑tested on Kaleido hardware

Cons / blockers:
- **GPL‑3.0** code reuse likely makes RoastMaster a derivative work (project licensing impact).
- Artisan’s `KaleidoPort` depends on `websockets` and `pymodbus`’s serial asyncio transport (and Artisan’s threading/event‑loop wrappers).
- Integrating it without pulling in the broader Artisan stack requires careful extraction.

Acceptance criteria:
- RoastMaster uses an imported/vendored `KaleidoPort` (minimal modifications), with tests verifying:
  - `RD A0` works reliably while sending control commands
  - `CL AR` is issued on disconnect
  - no regressions in existing unit tests

### Option B — Clean‑room implementation that matches Artisan’s architecture
Pros:
- avoids GPL contamination while still matching the important behaviors
- keeps dependencies minimal (only `pyserial`)
- can be tailored for a headless Raspberry Pi runtime

Cons:
- requires thorough testing against real Kaleido hardware to confirm parity

Acceptance criteria:
- RoastMaster implements the same *observable* behavior as Artisan for:
  - state tracking
  - request awaiting (including “single‑var response” semantics)
  - resilience to interleaved messages

Recommended for this repo today: **Option B**, unless you explicitly decide to relicense RoastMaster under GPL‑compatible terms.

---

## 1) Implement an Artisan‑style comm core (continuous reader + request/await)

### 1.1 Create an always‑on reader loop
Implementation tasks:
- Add a background reader that continuously `readline()`s and processes every `{...}` message.
- Parse `sid` and all `var:value` updates, updating an in‑memory `state` dict.

Acceptance criteria:
- Any message received from the device updates `state` (including replies to control commands).
- `read_temperatures()` no longer assumes “the next line after `RD` contains `BT/ET`”.

Suggested tests:
- Unit test using a fake serial device that sends `{sid,HP:...}` between `RD` responses and verify `read_temperatures()` still returns valid `BT/ET`.

### 1.2 Implement `send_msg()` and `send_request()` semantics
Implementation tasks:
- `send_msg(tag, value)` queues/writes a command without blocking.
- `send_request(tag, value, var=...)` waits for **a specific var update** (like Artisan’s `send_request()`).
- Support Artisan’s “single response” behavior:
  - requests awaiting a single `var:value` response should only complete when a response contains exactly one var/value pair (besides `sid`).

Acceptance criteria:
- `send_request('RD','A0', var='BT')` completes on a multi‑var broadcast containing `BT`.
- `send_request('CL','AR', var='SN', single_request=True)` completes only on a single‑var `SN` response (if that’s what the device emits).

Suggested tests:
- Fake serial: verify `send_request(..., single_request=True)` does **not** complete on a multi‑var message containing the same var.

### 1.3 Init + teardown handshake parity
Implementation tasks:
- Implement the initialization loop:
  1) repeat `PI` until `sid` is received (with retry delay)
  2) send `TU`
  3) send `SC AR`
- Implement teardown:
  - best‑effort `CL AR` on disconnect (optionally awaiting `SN`)

Acceptance criteria:
- Connect completes without relying on “one recv per send”.
- Disconnect does not hang even if the roaster is already offline.

Suggested tests:
- Fake serial: validate connect order and that disconnect sends `CL AR`.

---

## 2) Prevent control‑message flooding (keeps comm stable)

Even with an always‑on reader, continuously sending identical `HP/RC/FC` values at 30 fps is unnecessary load and increases failure surface area (especially over Bluetooth serial).

Implementation tasks:
- Add driver‑level de‑duplication: don’t enqueue a command if it encodes to the same payload as the last sent for that tag.
- Optionally add a minimum send interval per tag (e.g. 10–20 Hz cap) for future hardware encoder bursts.

Acceptance criteria:
- In steady state (no knob movement), control traffic stops (or reduces to a low keepalive, if desired).

Suggested tests:
- Unit test: call `set_heater(50)` repeatedly and verify only one write occurs.

---

## 3) Update docs to match reality (avoid future protocol regressions)

Implementation tasks:
- Fix `docs/kaleido-protocol.md` “Variable Types and Value Encoding” to match actual Artisan behavior:
  - `intVar` tags encode as integers (`.0f`)
  - “float” tags encode with up to one decimal (then strip)
  - (or rename the categories in the doc to avoid confusion)

Acceptance criteria:
- Docs match `reference/artisan/src/artisanlib/kaleido.py:create_msg()`
- Docs match `src/roastmaster/serial/kaleido.py:create_msg()` and unit tests

Suggested tests:
- None (doc‑only), but keep existing `tests/test_serial/test_kaleido.py` as the executable spec.

---

## 4) Regression test plan

Must pass:
- `pytest` (entire suite)

Add coverage:
- interleaved message handling (control ack + `RD` broadcast)
- request/await single‑response behavior
- de‑duplication / rate limiting

Hardware smoke test (recommended when you have the roaster connected):
- Run `roastmaster --test` and verify:
  - stable temperature reads over 5–10 minutes
  - no disconnects / stuck reads
- Run manual mode with small control changes and confirm:
  - roaster responds correctly
  - readings remain stable while controlling

