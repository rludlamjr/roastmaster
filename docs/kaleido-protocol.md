# Kaleido Device Communication Protocol

This document describes the wire protocol used by Kaleido roaster machines, as observed in Artisan's open-source implementation. It is intended as clean-room reference documentation of the factual protocol, not a reproduction of any implementation.

Source references point to functions and line numbers in:
`reference/artisan/src/artisanlib/kaleido.py` (the `KaleidoPort` class, Marko Luther, 2023)
and supplementary files `canvas.py` and `comm.py` where noted.

---

## 1. Transport Layer

The protocol supports two transport options. Both carry identical message content; only the framing and connection mechanism differ.

### 1.1 WebSocket

- URL: `ws://<host>:<port>/<path>`
- Default host: `127.0.0.1` (configurable)
- Default port: `80`
- Default path: `ws`
- Full default URL: `ws://127.0.0.1:80/ws`
- The `websockets` Python library is used for the connection.
- Messages are received as either `str` or `bytes`; if `bytes`, decoded as UTF-8.
- After sending a message the writer yields to the event loop with a 0.1 second sleep.

Source: `ws_connect()` lines 287-342; `start()` lines 603-606; `ws_write()` lines 237-241.

### 1.2 Serial (RS-232 / USB-Serial)

- Library: `pyserial` (via `pymodbus.transport.serialtransport.create_serial_connection`)
- Port: user-configurable (e.g. `COM4`, `/dev/ttyUSB0`)
- Baud rate: user-configurable; Artisan global default is `9600`
- Data bits: `8`
- Parity: `O` (Odd)
- Stop bits: `1`
- Read timeout: `0.4 s`
- Messages are newline-delimited; the serial reader uses `readline()`.
- Received bytes are decoded as UTF-8 and stripped of surrounding whitespace.

Source: `serial_connect()` lines 432-507; `serial_handle_reads()` lines 376-382; Artisan `serialport` defaults in `comm.py` lines 262-266; connection construction in `canvas.py` lines 13344-13352.

### 1.3 Transport selection

If a `SerialSettings` dict is provided to `start()`, serial transport is used; otherwise WebSocket is used. The two transports are mutually exclusive for a single session.

Source: `start()` lines 617-623.

---

## 2. Message Format

All messages are plain ASCII text, newline-terminated (`\n`). There is no binary framing, no length prefix, and no checksum.

### 2.1 Host-to-device (outgoing commands)

Commands that carry no value:

```
{[TAG]}\n
```

Commands that carry a value:

```
{[TAG value]}\n
```

The tag and value are separated by a single space inside the brackets. There is no separator between the brackets and the enclosing braces.

Examples:

```
{[PI]}\n
{[TU C]}\n
{[SC AR]}\n
{[HP 75]}\n
{[RD A0]}\n
```

Source: `create_msg()` lines 514-532.

### 2.2 Device-to-host (incoming data)

All responses from the device share a single format:

```
{sid,var:value,var:value,...}\n
```

Fields:

- The message is wrapped in `{` and `}`.
- The first element is `sid`, an integer 0-10 representing device status.
- Subsequent elements are `var:value` pairs separated by commas.
- Each `var:value` pair has the variable name and its value separated by a colon with no surrounding spaces.

A response may contain one or many `var:value` pairs after the `sid`. Artisan uses the count of pairs to determine whether a response is a "single-variable reply" (used for request/reply synchronisation) versus a full broadcast.

Examples:

```
{0,BT:185.3,ET:210.0,AT:22.4,TS:200.0,HP:60,FC:50,RC:40,AH:0,HS:1}\n
{1,SN:K12345}\n
{4,HP:75}\n
```

Source: `process_message()` lines 198-214.

---

## 3. Variable Types and Value Encoding

Variables are categorised into three types. The category governs both how outgoing values are formatted and how incoming values are parsed.

### 3.1 Integer variables

Set membership: `sid`, `HP`, `FC`, `RC`, `AH`, `HS`, `EV`, `CS`

Outgoing encoding: `f'{float(value):.0f}'`
This converts the value to a float, formats with zero decimal places (rounds to nearest integer), and produces a plain integer string (e.g. `"75"`, `"0"`, `"1"`).

Incoming parsing: `int(round(float(value)))` — the string is parsed as float and rounded to int.

Source: `intVar()` lines 131-132; `create_msg()` lines 523-525; `set_state()` lines 183-183.

### 3.2 Float variables

All variables that are neither integer nor string variables (i.e. `BT`, `ET`, `AT`, `TS` and any unrecognised tag).

Outgoing encoding: `f'{float(value):.1f}'.rstrip('0').rstrip('.')`
This formats to one decimal place then strips trailing zeros and any trailing decimal point. Examples: `185.3` → `"185.3"`, `200.0` → `"200"`, `185.30` → `"185.3"`.

Incoming parsing: `float(value)`. If conversion fails the raw string is stored as-is.

Source: `floatVar()` lines 135-136; `create_msg()` lines 526-528; `set_state()` lines 186-191.

### 3.3 String variables

Set membership: `TU`, `SC`, `CL`, `SN`

Outgoing encoding: the value is sent as-is with no numeric conversion attempted.

Incoming parsing: stored as a plain string.

Source: `strVar()` lines 139-140; `create_msg()` lines 519-521; `set_state()` lines 184-185.

---

## 4. Command Reference (Host to Device)

| Tag | Value | Description |
|-----|-------|-------------|
| `PI` | (none) | Ping. Device responds with a status message. Used to verify the connection is alive. |
| `TU` | `C` or `F` | Set temperature unit. Sent once during initialisation. |
| `SC` | `AR` | Start guard / open session. Sent after `TU` to begin a monitored session. |
| `CL` | `AR` | Close guard / end session. Sent during teardown. Device responds with `SN`. |
| `RD` | `A0` | Read all device data. Triggers a full sensor broadcast from the device. |
| `HP` | `0`-`100` | Set heater power as a percentage integer. |
| `FC` | `0`-`100` | Set fan / air speed as a percentage integer. |
| `RC` | `0`-`100` | Set drum speed as a percentage integer. |
| `AH` | `0` or `1` | PID auto-heat: `1` = on, `0` = off. |
| `TS` | float | Set PID target / setpoint temperature. Encoded as a float (one decimal, trailing zeros stripped). |
| `EV` | `2` | Mark turning point event. Value `2` signifies TP. |
| `HS` | `0` or `1` | Heating switch: `1` = on, `0` = off. |

Notes:

- `RD A0` is the polling mechanism. There is no unsolicited push; the host must send `RD A0` to receive fresh sensor data.
- `_default_data_stream` is the constant `'A0'`, confirming the data stream identifier (line 62).
- `EV 2` for turning point is the only documented `EV` value in Artisan's implementation (`markTP()` line 597).

Source: `create_msg()` lines 514-532; `getBTET()` line 95; `markTP()` line 597; `pidON()`/`pidOFF()` lines 144-153; `setSV()` lines 155-158; `stop()` line 631.

---

## 5. Data Variable Reference (Device to Host)

| Variable | Type | Range / Format | Description |
|----------|------|----------------|-------------|
| `sid` | int | 0-10 | Device status code. Lower 4 bits encode roast event flags (see Section 7). |
| `BT` | float | decimal | Bean temperature. |
| `ET` | float | decimal | Environmental / exhaust temperature. |
| `AT` | float | decimal | Ambient temperature. |
| `TS` | float | decimal | Target / setpoint temperature (PID). |
| `HP` | int | 0-100 | Current heater power percentage. |
| `FC` | int | 0-100 | Current fan / air speed percentage. |
| `RC` | int | 0-100 | Current drum speed percentage. |
| `AH` | int | 0 or 1 | Auto-heat (PID) mode: `1` = active, `0` = off. |
| `HS` | int | 0 or 1 | Heating switch state: `1` = on, `0` = off. |
| `SN` | string | — | Device serial number. Returned in response to `CL AR` and during initialisation. |
| `TU` | string | `C` or `F` | Temperature unit currently in use on the device. |

The `State` TypedDict (lines 37-48) and the accessor methods `getBTET()`, `getSVAT()`, `getDrumAH()`, `getHeaterFan()` (lines 92-125) confirm this complete set of tracked variables.

Artisan treats an unknown state (variable not yet received) as follows:
- `sid`, `TU`, `SC`, `CL`, `SN`: `None`
- Integer variables: `-1`
- Float variables: `-1.0`

Source: `get_state()` lines 164-172.

---

## 6. Session Lifecycle

### 6.1 Initialisation sequence

The initialisation is identical for both WebSocket and Serial transports. It is performed synchronously (outside the normal read/write queue) before the read and write handler coroutines are started.

**Step 1 — Ping loop**

Send `{[PI]}\n` and wait up to `ping_timeout` (1.2 s) for any response. A valid response sets `sid` in state. If no response, wait `ping_retry_delay` (1.0 s) and retry. The entire ping loop is bounded by `init_timeout` (6.0 s). Continue until `sid` is not `None`.

**Step 2 — Set temperature unit**

Send `{[TU C]}\n` or `{[TU F]}\n` (mode string from caller). Wait up to `ping_timeout` for a response. Timeout is logged but does not abort the sequence.

**Step 3 — Start guard**

Send `{[SC AR]}\n`. Wait up to `ping_timeout` for a response. Timeout is logged but does not abort.

After these three steps, the read and write handler tasks are started and normal polling begins.

Source: `ws_initialize()` lines 261-285; `serial_initialize()` lines 408-430; `ws_connect()` lines 299-309; `serial_connect()` lines 453-464.

### 6.2 Normal operation (polling)

The caller drives data collection by periodically calling `getBTET()`, which issues `{[RD A0]}\n` if `sid` and `TU` are both set (confirming initialisation is complete). The device responds with a full sensor broadcast. Artisan's default sample interval for this is 1.5 seconds.

Source: `getBTET()` lines 92-104; CSV parser sampling interval comment line 885.

### 6.3 Teardown

`stop()` sends `{[CL AR]}\n` using `send_request('CL', 'AR', 'SN', ...)`, which waits for a response containing the `SN` variable before returning. The wait timeout is `2 * send_timeout` (1.2 s). After the request completes (or times out), `_running` is set to `False`, the async loop thread and write queue references are cleared, and state is reset.

Source: `stop()` lines 628-635.

### 6.4 Reconnection

Both WebSocket and Serial transports implement an automatic reconnect loop. After any disconnection or error, state is reset via `resetReadings()`, any `disconnected_handler` callback is invoked, and the loop sleeps for `reconnect_delay` (0.5 s) before attempting a new connection.

Source: `ws_connect()` lines 329-342; `serial_connect()` lines 499-507.

---

## 7. SID Event Flags

The `sid` value returned in every device message encodes roast phase events in its lower 4 bits:

```
event_flag = sid & 15
```

| Event flag value | Roast event |
|-----------------|-------------|
| 1 | Charge (beans loaded) |
| 2 | Turning Point (TP) |
| 3 | Dry End |
| 4 | First Crack Start (FCs) |
| 5 | First Crack End (FCe) |
| 6 | Second Crack Start (SCs) |
| 7 | Second Crack End (SCe) |
| 8 | Drop (beans discharged) |
| 9 | Cool |

The upper bits of `sid` (above the lower 4) encode other device status information not broken down in Artisan's implementation.

Artisan guards against spurious event triggers by checking that:
- Each event is only fired once (the corresponding `timeindex` slot is still at its unset value).
- For Drop (flag 8): at least 7 minutes have elapsed since Charge.
- TP (flag 2) is noted in the source but currently commented out in Artisan's processing.

Each event flag can be independently enabled or disabled via user configuration (`kaleidoEventFlags`, a list of 7 booleans corresponding to Charge, Dry, FCs, FCe, SCs, SCe, Drop). All flags default to `False` in Artisan.

Source: `comm.py` lines 2144-2164; `main.py` lines 1841.

---

## 8. Timing Constants

All constants are `Final` attributes set in `KaleidoPort.__init__()` (lines 63-71).

| Constant | Value | Description |
|----------|-------|-------------|
| `_open_timeout` | 6.0 s | Maximum time allowed for the transport connection to open. |
| `_init_timeout` | 6.0 s | Maximum time allowed for the entire initialisation sequence (ping + TU + SC). |
| `_ping_timeout` | 1.2 s | Timeout for a single ping send-and-receive cycle; also used as the response wait timeout for each step of initialisation. |
| `_send_timeout` | 0.6 s | Timeout for placing a message onto the write queue. |
| `_read_timeout` | 5.0 s | Timeout for receiving any message from the device during normal operation. |
| `_ping_retry_delay` | 1.0 s | Sleep between ping retries during initialisation. |
| `_reconnect_delay` | 0.5 s | Sleep before attempting to reconnect after a disconnection. |
| `send_button_timeout` | 1.2 s | Timeout used for UI-triggered send operations (e.g. slider changes). |

---

## 9. Concurrency Model

Artisan's implementation runs all I/O in a dedicated asyncio event loop managed by `AsyncLoopThread`. The main (UI) thread communicates with it via `asyncio.run_coroutine_threadsafe()`.

There are two categories of outgoing message:

**Fire-and-forget (`send_msg`)**: Puts the formatted message on the `asyncio.Queue` and returns immediately after the queue put completes (or times out at `send_timeout`).

**Request-reply (`send_request`)**: Puts the message on the queue, registers an `asyncio.Event` keyed to the expected response variable, and blocks the calling thread until either the event is set (the response variable appears in a device message) or the timeout elapses.

The `_pending_requests` dict maps variable names to `asyncio.Event` objects. `process_message()` calls `clear_request()` for each variable it processes, which sets the corresponding event and wakes any waiting thread.

For request-reply synchronisation with commands that return a single `var:value` pair, the await variable is prefixed with `_single_await_var_prefix` (`'!'`). This prevents a broadcast response containing the same variable from prematurely clearing the lock for a targeted request.

Source: `send_msg()` lines 534-548; `send_request()` lines 572-594; `write_await()` lines 551-566; `add_request()` lines 216-220; `clear_request()` lines 222-225; `process_message()` lines 198-214.

---

## 10. PID Control Interface

The Kaleido device has an on-board PID controller. Artisan exposes it through three commands:

- **Enable PID**: Send `{[AH 1]}\n`. Only sent if `AH` state is currently `0` (avoids redundant commands).
- **Disable PID**: Send `{[AH 0]}\n`. Only sent if `AH` state is currently `1`.
- **Set setpoint**: Send `{[TS <value>]}\n` where `<value>` is encoded as a float with one decimal, trailing zeros stripped. Only sent if the new setpoint differs from the current `TS` state.

Source: `pidON()` lines 144-148; `pidOFF()` lines 150-153; `setSV()` lines 155-158.

---

## 11. Kaleido CSV File Format

In addition to the live protocol, Kaleido machines can export roast data as CSV files. Artisan's `extractProfileKaleidoCSV()` function (lines 642-916) documents the structure of these files.

The file is divided into named sections using `[{SECTIONNAME}]` markers.

Known sections:

| Section | Content |
|---------|---------|
| `CookDate` | Roast date and time, format `YY-MM-DD HH:MM:SS` |
| `Comment` | Roast title / comment string |
| `DATA` | Comma-separated time-series rows (see below) |
| `StartBeansIn` | Charge event: `<temp>@<MM:SS>` |
| `TurntoYellow` | Dry End event: `<temp>@<MM:SS>` |
| `1stBoomStart` | First Crack Start event: `<temp>@<MM:SS>` |
| `1stBoomEnd` | First Crack End event: `<temp>@<MM:SS>` |
| `2ndBoomStart` | Second Crack Start event: `<temp>@<MM:SS>` |
| `2ndBoomEnd` | Second Crack End event: `<temp>@<MM:SS>` |
| `BeansColdDown` | Drop event: `<temp>@<MM:SS>` |

The `DATA` section has a header row followed by data rows. Columns (0-indexed):

| Index | Name | Type | Description |
|-------|------|------|-------------|
| 0 | Index | int | Row number (skipped) |
| 1 | Time | int | Time in milliseconds from roast start |
| 2 | BT | float | Bean temperature |
| 3 | ET | float | Environmental temperature |
| 4 | RoR | float | Rate of Rise in C/30s (note: Artisan expects C/60s, so multiply by 2) |
| 5 | SV | float | Setpoint value |
| 6 | HPM | string | Heat mode: `M` = manual, `A` = PID/auto |
| 7 | HP | float | Heat power percentage |
| 8 | SM | float | Fan / air percentage |
| 9 | RL | float | Drum rotation percentage |
| 10 | PS | string | Power status: `O` = on, `C` = off (read but not mapped to events) |

File encoding: UTF-8 preferred; fallback order is `gbk`, `gb2312`, `latin-1`, then UTF-8 with errors ignored (to handle Chinese character sets common in Kaleido firmware).

The CSV sampling interval is 1.5 seconds (line 885).

Source: `extractProfileKaleidoCSV()` lines 642-916.

---

## 12. Known Ambiguities and Implementation Notes

- **TP event flag (sid & 15 == 2)**: The Turning Point event flag is decoded but its processing is commented out in Artisan's `comm.py` (line 2147-2148) with the note that it is "unclear what those machines exactly report and when." Do not rely on flag value 2 for automated TP marking.

- **sid upper bits**: Only the lower 4 bits of `sid` are documented as event flags. The meaning of the upper bits is not specified in Artisan's implementation beyond storing the raw integer.

- **CS variable**: `CS` appears in the `intVar()` set (line 132) alongside `HP`, `FC`, `RC`, `AH`, `HS`, `EV`. It is not present in the `State` TypedDict and no outgoing command for `CS` is documented. Its meaning is unknown from this source alone.

- **EV values beyond 2**: Only `EV 2` (Turning Point) is used in Artisan's implementation. Whether other `EV` values are valid is not documented here.

- **Write queue sentinel**: An empty string `''` is used as a sentinel value to stop the write handler coroutine cleanly. Implementations must not enqueue an empty string as a real message.

- **Serial timeout parameter**: The `timeout` field of `SerialSettings` is passed to `create_serial_connection` and controls the underlying serial read timeout (default `0.4 s`). This is distinct from the protocol-level `_read_timeout` (5.0 s) applied via `asyncio.wait_for` on `readline()`.
