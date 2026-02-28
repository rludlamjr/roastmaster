"""GPIO input backend for Raspberry Pi hardware.

TEMPORARY: Breadboard prototype using toggle switches and RC timing for pots.
This will be replaced with proper ADC (MCP3008) reads once the chip arrives.
The RC timing approach reads potentiometers by charging a capacitor through
the pot resistance and measuring how long the GPIO pin takes to go HIGH.

Hardware wiring:
  Heat switch -> GPIO 17 (toggle to GND, internal pull-up)
  Cool switch -> GPIO 27 (toggle to GND, internal pull-up)
  Mode switch -> GPIO 22 (toggle to GND, internal pull-up)
  Burner pot  -> GPIO 5  (10K pot + 0.1uF cap, RC timing)
  Drum pot    -> GPIO 6  (10K pot + 0.1uF cap, RC timing)
  Air pot     -> GPIO 13 (10K pot + 0.1uF cap, RC timing)
"""

from __future__ import annotations

import logging
import time

from roastmaster.hal.base import InputEvent, InputState

logger = logging.getLogger(__name__)

# --- Conditional gpiod import ---
try:
    import gpiod  # type: ignore[import-untyped]
    from gpiod.line import Bias, Direction, Edge, Value  # type: ignore[import-untyped]

    _GPIOD_AVAILABLE = True
except ImportError:
    _GPIOD_AVAILABLE = False

# ---------------------------------------------------------------------------
# TEMPORARY pin assignments — breadboard prototype
# ---------------------------------------------------------------------------
_CHIP = "/dev/gpiochip4"

# Toggle switches (pull-up, active-low)
_HEAT_PIN = 17
_COOL_PIN = 27
_MODE_PIN = 22
_SWITCH_PINS = (_HEAT_PIN, _COOL_PIN, _MODE_PIN)
_DEBOUNCE_US = 50_000  # 50 ms kernel debounce

# Potentiometer RC timing
_BURNER_PIN = 5
_DRUM_PIN = 6
_AIR_PIN = 13
_POT_PINS = (_BURNER_PIN, _DRUM_PIN, _AIR_PIN)

# RC timing constants (TEMPORARY — tuned for 10K pot + 0.1uF cap)
_DISCHARGE_S = 0.005  # 5 ms discharge time
_RC_MAX_NS = 1_500_000  # ~1.5 ms full-scale (10K * 0.1uF ~ 1ms tau)
_RC_TIMEOUT_NS = 3_000_000  # give up after 3 ms
_POT_READ_INTERVAL_S = 0.1  # read pots at 10 Hz

# Map switch pins to toggle events
_SWITCH_EVENT_MAP = {
    _HEAT_PIN: InputEvent.HEAT_TOGGLE,
    _COOL_PIN: InputEvent.COOL_TOGGLE,
    _MODE_PIN: InputEvent.MODE_TOGGLE,
}


# ---------------------------------------------------------------------------
# Pure helper — extracted for testability
# ---------------------------------------------------------------------------


def _ns_to_percent(elapsed_ns: int) -> int:
    """Map RC charge time in nanoseconds to 0-100 percentage (clamped).

    TEMPORARY: Calibrated for 10K pot + 0.1uF cap breadboard prototype.
    """
    if elapsed_ns <= 0:
        return 0
    if elapsed_ns >= _RC_MAX_NS:
        return 100
    return int(round(elapsed_ns * 100 / _RC_MAX_NS))


# ---------------------------------------------------------------------------
# GPIOInput class
# ---------------------------------------------------------------------------


class GPIOInput:
    """Raspberry Pi GPIO input backend — breadboard prototype.

    Reads toggle switches via gpiod edge detection and potentiometers via
    RC timing (discharge cap, measure charge time). Falls back to no-op
    mode if gpiod is not available (e.g. macOS development).
    """

    def __init__(self) -> None:
        self._available = False
        self._switch_request = None
        self._state = InputState()
        self._last_pot_read = 0.0

        if not _GPIOD_AVAILABLE:
            logger.warning("gpiod not available — GPIO backend in no-op mode")
            return

        try:
            self._setup_switches()
            self._available = True
            logger.info("GPIO backend initialized (breadboard prototype)")
        except Exception:
            logger.exception("Failed to initialize GPIO — falling back to no-op")
            self._available = False

    @property
    def available(self) -> bool:
        """True if GPIO hardware is accessible."""
        return self._available

    def _setup_switches(self) -> None:
        """Request switch lines with edge detection, pull-up, and debounce."""
        config = {
            tuple(_SWITCH_PINS): gpiod.LineSettings(
                direction=Direction.INPUT,
                edge_detection=Edge.BOTH,
                bias=Bias.PULL_UP,
                active_low=True,
                debounce_period=gpiod.line.clock.Duration.from_microseconds(
                    _DEBOUNCE_US
                )
                if hasattr(gpiod.line, "clock")
                else None,
            )
        }

        # Fallback: some gpiod versions use a simpler debounce API
        try:
            self._switch_request = gpiod.request_lines(
                _CHIP,
                consumer="roastmaster-switches",
                config={
                    tuple(_SWITCH_PINS): gpiod.LineSettings(
                        direction=Direction.INPUT,
                        edge_detection=Edge.BOTH,
                        bias=Bias.PULL_UP,
                        active_low=True,
                        debounce_period=_DEBOUNCE_US,
                    )
                },
            )
        except TypeError:
            # Older gpiod API — try without debounce_period kwarg
            self._switch_request = gpiod.request_lines(
                _CHIP,
                consumer="roastmaster-switches",
                config=config,
            )

    def _read_pot_rc(self, pin: int) -> int:
        """Read a single pot via RC timing.

        TEMPORARY: Uses release/re-request per cycle to avoid
        reconfigure_lines bugs in some gpiod versions.

        1. Request pin as OUTPUT LOW — discharge cap for 5ms
        2. Release pin
        3. Request pin as INPUT — measure time until HIGH
        4. Release pin
        5. Convert elapsed time to 0-100
        """
        # Phase 1: Discharge the capacitor
        discharge_req = gpiod.request_lines(
            _CHIP,
            consumer="roastmaster-pot-discharge",
            config={
                pin: gpiod.LineSettings(
                    direction=Direction.OUTPUT,
                    output_value=Value.INACTIVE,
                )
            },
        )
        time.sleep(_DISCHARGE_S)
        discharge_req.release()

        # Phase 2: Time the charge
        charge_req = gpiod.request_lines(
            _CHIP,
            consumer="roastmaster-pot-charge",
            config={
                pin: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    bias=Bias.DISABLED,
                )
            },
        )

        start_ns = time.monotonic_ns()
        timeout_ns = start_ns + _RC_TIMEOUT_NS

        while time.monotonic_ns() < timeout_ns:
            if charge_req.get_value(pin) == Value.ACTIVE:
                elapsed_ns = time.monotonic_ns() - start_ns
                charge_req.release()
                return _ns_to_percent(elapsed_ns)

        # Timed out — treat as maximum resistance
        charge_req.release()
        return 100

    def _read_all_pots(self) -> None:
        """Read all three pots and update internal state."""
        self._state.burner = self._read_pot_rc(_BURNER_PIN)
        self._state.drum = self._read_pot_rc(_DRUM_PIN)
        self._state.air = self._read_pot_rc(_AIR_PIN)

    def poll_events(self) -> list[InputEvent]:
        """Poll for switch edge events and update pot readings.

        Returns a list of InputEvents from switch toggles. Pot values
        are updated in-place on self._state at 10 Hz.
        """
        if not self._available:
            return []

        events: list[InputEvent] = []

        # Check switch edges (non-blocking)
        if self._switch_request is not None:
            try:
                if self._switch_request.wait_edge_events(timeout=0):
                    for edge in self._switch_request.read_edge_events():
                        pin = edge.line_offset
                        if pin in _SWITCH_EVENT_MAP:
                            events.append(_SWITCH_EVENT_MAP[pin])
            except Exception:
                logger.exception("Error reading switch events")

        # Read pots at 10 Hz (not every frame)
        now = time.monotonic()
        if now - self._last_pot_read >= _POT_READ_INTERVAL_S:
            self._last_pot_read = now
            try:
                self._read_all_pots()
            except Exception:
                logger.exception("Error reading pots")

        return events

    @property
    def state(self) -> InputState:
        """Current control state from GPIO hardware."""
        return self._state

    def close(self) -> None:
        """Release all gpiod line requests."""
        if self._switch_request is not None:
            try:
                self._switch_request.release()
            except Exception:
                logger.exception("Error releasing switch lines")
            self._switch_request = None
        self._available = False
        logger.info("GPIO backend closed")
