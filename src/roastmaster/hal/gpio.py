"""GPIO input backend for Raspberry Pi hardware.

Reads physical controls matching the production stripboard interface board
(docs/stripboard-interface-board-inputs-only.md):

  Toggle switches (active-LOW, internal pull-up):
    GPIO23 → POWER (shutdown request)
    GPIO5  → HEAT
    GPIO6  → COOL
    GPIO13 → MODE

  Momentary buttons (active-LOW, internal pull-up):
    GPIO16 → CHARGE
    GPIO26 → FCS (First Crack Start)
    GPIO21 → SCS (Second Crack Start)
    GPIO12 → DROP
    GPIO25 → SAVE
    GPIO20 → RESET

  Rotary encoder:
    GPIO17 → CLK (quadrature rotation)
    GPIO27 → DT  (quadrature direction)
    GPIO22 → SW  (push button)

  Potentiometers via MCP3008 SPI ADC (optional — graceful fallback):
    CH0 → BURNER
    CH1 → AIR
    CH2 → DRUM

Safety: Toggle switches use "arm" behaviour for HEAT, COOL, and MODE.
Switches that are ON at startup are ignored until they are turned OFF once,
preventing surprise heat/cool after a reboot.
"""

from __future__ import annotations

import logging
import os
import time

from roastmaster.hal.base import InputEvent, InputState

logger = logging.getLogger(__name__)

# --- Conditional imports ---------------------------------------------------

try:
    import gpiod  # type: ignore[import-untyped]
    from gpiod.line import Bias, Direction, Edge, Value  # type: ignore[import-untyped]

    _GPIOD_AVAILABLE = True
except ImportError:
    _GPIOD_AVAILABLE = False

try:
    import spidev  # type: ignore[import-untyped]

    _SPIDEV_AVAILABLE = True
except ImportError:
    _SPIDEV_AVAILABLE = False


def _detect_chip() -> str:
    """Auto-detect the GPIO chip device path.

    Pi 3B/4: /dev/gpiochip0
    Pi 5:    /dev/gpiochip4
    """
    for path in ("/dev/gpiochip0", "/dev/gpiochip4"):
        if os.path.exists(path):
            return path
    return "/dev/gpiochip0"


_CHIP = _detect_chip()
_DEBOUNCE_US = 50_000  # 50 ms kernel debounce (buttons/toggles)
_ENC_DEBOUNCE_US = 5_000  # 5 ms for rotary encoder (needs fast response)

# ---------------------------------------------------------------------------
# Pin assignments — matches stripboard-interface-board-inputs-only.md
# ---------------------------------------------------------------------------

# Toggle switches (active-LOW, pull-up)
_POWER_PIN = 23
_HEAT_PIN = 5
_COOL_PIN = 6
_MODE_PIN = 13
_UNIT_PIN = 19   # C/F display toggle (GPIO19, Pi physical pin 35)
_DEBUG_PIN = 24  # Debug/info panel toggle (GPIO24, Pi physical pin 18)
_MUSIC_PIN = 4   # Background music toggle (GPIO4, Pi physical pin 7)
_TOGGLE_PINS = (
    _POWER_PIN, _HEAT_PIN, _COOL_PIN, _MODE_PIN,
    _UNIT_PIN, _DEBUG_PIN, _MUSIC_PIN,
)

# Pins subject to startup arm behaviour (NOT power — it should respond immediately)
_ARMABLE_PINS = frozenset((_HEAT_PIN, _COOL_PIN, _MODE_PIN))

_TOGGLE_EVENT_MAP: dict[int, InputEvent] = {
    _HEAT_PIN: InputEvent.HEAT_TOGGLE,
    _COOL_PIN: InputEvent.COOL_TOGGLE,
    _MODE_PIN: InputEvent.MODE_TOGGLE,
    _UNIT_PIN: InputEvent.UNIT_TOGGLE,
    _DEBUG_PIN: InputEvent.HELP_TOGGLE,
    _MUSIC_PIN: InputEvent.MUSIC_TOGGLE,
}

# Momentary buttons (active-LOW, pull-up, press = falling edge)
_CHARGE_PIN = 16
_FCS_PIN = 26
_SCS_PIN = 21
_DROP_PIN = 12
_SAVE_PIN = 25
_RESET_PIN = 20
_BUTTON_PINS = (_CHARGE_PIN, _FCS_PIN, _SCS_PIN, _DROP_PIN, _SAVE_PIN, _RESET_PIN)

_BUTTON_EVENT_MAP: dict[int, InputEvent] = {
    _CHARGE_PIN: InputEvent.CHARGE,
    _FCS_PIN: InputEvent.FIRST_CRACK,
    _SCS_PIN: InputEvent.SECOND_CRACK,
    _DROP_PIN: InputEvent.DROP,
    _SAVE_PIN: InputEvent.PROFILE_SAVE,
    _RESET_PIN: InputEvent.ROAST_RESET,
}

# Rotary encoder
_ENC_CLK_PIN = 17
_ENC_DT_PIN = 27
_ENC_SW_PIN = 22

# MCP3008 SPI ADC
_MCP3008_SPI_BUS = 0
_MCP3008_SPI_DEVICE = 0  # CE0
_MCP3008_SPI_SPEED = 1_000_000  # 1 MHz (safe at 3.3V)
_POT_READ_INTERVAL_S = 0.1  # read pots at 10 Hz
_ADC_DEADBAND = 10  # ignore ADC jitter smaller than this (out of 1023)

# MCP3008 channel assignments (match stripboard wiring)
_CH_BURNER = 0
_CH_AIR = 1
_CH_DRUM = 2
_CH_SCROLL = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _adc_to_percent(raw: int) -> int:
    """Convert a 10-bit MCP3008 reading (0-1023) to 0-100, clamped."""
    if raw <= 0:
        return 0
    if raw >= 1023:
        return 100
    return int(round(raw * 100 / 1023))


# ---------------------------------------------------------------------------
# GPIOInput class
# ---------------------------------------------------------------------------


class GPIOInput:
    """Raspberry Pi GPIO input backend — production hardware.

    Reads toggle switches, momentary buttons, and a rotary encoder via
    gpiod edge detection, and potentiometers via MCP3008 SPI ADC.

    Falls back to no-op mode if gpiod is not available (e.g. macOS dev).
    MCP3008 is optional — if absent, pot state stays at defaults and the
    HybridInput compositor will fall back to keyboard control.
    """

    def __init__(self) -> None:
        self._available = False
        self._pots_available = False
        self._toggle_request: object | None = None
        self._button_request: object | None = None
        self._encoder_request: object | None = None
        self._spi: object | None = None
        self._state = InputState()
        self._last_pot_read = 0.0
        self._last_adc = [0, 0, 0, 1023]  # raw ADC values for deadband (scroll defaults high = live)

        # Arm state for toggle switches (safety: prevent surprise heat on boot)
        self._armed: dict[int, bool] = {}

        if not _GPIOD_AVAILABLE:
            logger.warning("gpiod not available — GPIO backend in no-op mode")
            return

        try:
            self._setup_toggles()
            self._setup_buttons()
            self._setup_encoder()
            self._available = True
            logger.info("GPIO backend initialized (production hardware)")
        except Exception:
            logger.exception("Failed to initialize GPIO — falling back to no-op")
            self._available = False

        # MCP3008 is optional — pots use keyboard fallback if absent
        self._init_mcp3008()

    # --- Properties --------------------------------------------------------

    @property
    def available(self) -> bool:
        """True if GPIO hardware is accessible."""
        return self._available

    @property
    def pots_available(self) -> bool:
        """True if MCP3008 ADC is providing pot readings."""
        return self._pots_available

    # --- Setup methods -----------------------------------------------------

    def _setup_toggles(self) -> None:
        """Configure toggle switch lines with edge detection and pull-ups.

        Also reads initial switch positions to set up arm behaviour.
        """
        from datetime import timedelta

        self._toggle_request = gpiod.request_lines(
            _CHIP,
            consumer="roastmaster-toggles",
            config={
                tuple(_TOGGLE_PINS): gpiod.LineSettings(
                    direction=Direction.INPUT,
                    edge_detection=Edge.BOTH,
                    bias=Bias.PULL_UP,
                    active_low=True,
                    debounce_period=timedelta(microseconds=_DEBOUNCE_US),
                )
            },
        )

        # Initialize arm state for safety-critical toggles.
        # active_low=True: ACTIVE = switch closed (ON), INACTIVE = switch open (OFF)
        for pin in _ARMABLE_PINS:
            val = self._toggle_request.get_value(pin)
            is_on = val == Value.ACTIVE
            self._armed[pin] = not is_on  # armed if currently OFF
            if is_on:
                logger.info(
                    "Toggle GPIO%d is ON at startup — armed after first OFF",
                    pin,
                )

    def _setup_buttons(self) -> None:
        """Configure momentary button lines with falling-edge detection."""
        from datetime import timedelta

        self._button_request = gpiod.request_lines(
            _CHIP,
            consumer="roastmaster-buttons",
            config={
                tuple(_BUTTON_PINS): gpiod.LineSettings(
                    direction=Direction.INPUT,
                    edge_detection=Edge.FALLING,
                    bias=Bias.PULL_UP,
                    active_low=True,
                    debounce_period=timedelta(microseconds=_DEBOUNCE_US),
                )
            },
        )

    def _setup_encoder(self) -> None:
        """Configure rotary encoder lines.

        CLK: falling-edge detection for quadrature decoding.
        DT:  input only (read as level when CLK fires).
        SW:  falling-edge detection for push button.
        """
        from datetime import timedelta

        self._encoder_request = gpiod.request_lines(
            _CHIP,
            consumer="roastmaster-encoder",
            config={
                _ENC_CLK_PIN: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    edge_detection=Edge.BOTH,
                    bias=Bias.PULL_UP,
                    debounce_period=timedelta(microseconds=_ENC_DEBOUNCE_US),
                ),
                _ENC_DT_PIN: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    edge_detection=Edge.NONE,
                    bias=Bias.PULL_UP,
                ),
                _ENC_SW_PIN: gpiod.LineSettings(
                    direction=Direction.INPUT,
                    edge_detection=Edge.FALLING,
                    bias=Bias.PULL_UP,
                    active_low=True,
                    debounce_period=timedelta(microseconds=_DEBOUNCE_US),
                ),
            },
        )

    def _init_mcp3008(self) -> None:
        """Try to initialise MCP3008 SPI ADC. Non-fatal if absent."""
        if not _SPIDEV_AVAILABLE:
            logger.info("spidev not available — pot control via keyboard only")
            return

        try:
            spi = spidev.SpiDev()
            spi.open(_MCP3008_SPI_BUS, _MCP3008_SPI_DEVICE)
            spi.max_speed_hz = _MCP3008_SPI_SPEED
            spi.mode = 0

            # Sanity read — if SPI bus is open but no chip, this may return
            # garbage but won't error.  We accept that for now.
            self._spi_read_channel(spi, 0)

            self._spi = spi
            self._pots_available = True
            logger.info("MCP3008 ADC initialized on SPI0.0")
        except Exception:
            logger.info("MCP3008 ADC not available — pot control via keyboard only")

    @staticmethod
    def _spi_read_channel(spi: object, channel: int) -> int:
        """Read a single MCP3008 channel. Returns 0-1023."""
        adc = spi.xfer2([1, (8 + channel) << 4, 0])  # type: ignore[union-attr]
        return ((adc[1] & 3) << 8) + adc[2]

    # --- Poll methods ------------------------------------------------------

    def _poll_toggles(self, events: list[InputEvent]) -> None:
        """Read toggle switch edge events.

        Applies arm behaviour to HEAT, COOL, MODE: switches that are ON at
        startup are suppressed until they are turned OFF once.  POWER toggle
        emits QUIT only when the switch goes to OFF (safe shutdown).
        """
        if self._toggle_request is None:
            return
        try:
            if not self._toggle_request.wait_edge_events(timeout=0):
                return
            for edge in self._toggle_request.read_edge_events():
                pin = edge.line_offset

                if pin == _POWER_PIN:
                    # Only emit QUIT when switch goes to OFF (INACTIVE = open)
                    current = self._toggle_request.get_value(pin)
                    if current == Value.INACTIVE:
                        events.append(InputEvent.QUIT)
                    continue

                if pin in _ARMABLE_PINS:
                    if not self._armed.get(pin, True):
                        # Not armed yet — arm on OFF transition
                        current = self._toggle_request.get_value(pin)
                        if current == Value.INACTIVE:
                            self._armed[pin] = True
                            logger.info("Toggle GPIO%d armed", pin)
                        continue  # suppress event while unarmed

                # Emit the toggle event (armable pins reach here only when armed)
                if pin in _TOGGLE_EVENT_MAP:
                    events.append(_TOGGLE_EVENT_MAP[pin])
        except Exception:
            logger.exception("Error reading toggle events")

    def _poll_buttons(self, events: list[InputEvent]) -> None:
        """Read momentary button press events (falling edge only)."""
        if self._button_request is None:
            return
        try:
            if not self._button_request.wait_edge_events(timeout=0):
                return
            for edge in self._button_request.read_edge_events():
                pin = edge.line_offset
                if pin in _BUTTON_EVENT_MAP:
                    events.append(_BUTTON_EVENT_MAP[pin])
        except Exception:
            logger.exception("Error reading button events")

    def _poll_encoder(self, events: list[InputEvent]) -> None:
        """Read rotary encoder events.

        CLK edge (both rising and falling) + DT level → rotation direction.
        On CLK falling edge: DT HIGH = CW, DT LOW = CCW.
        On CLK rising edge:  DT LOW = CW, DT HIGH = CCW (inverted).
        SW falling edge → profile load / confirm.
        """
        if self._encoder_request is None:
            return
        try:
            if not self._encoder_request.wait_edge_events(timeout=0):
                return
            for edge in self._encoder_request.read_edge_events():
                pin = edge.line_offset

                if pin == _ENC_CLK_PIN:
                    dt_val = self._encoder_request.get_value(_ENC_DT_PIN)
                    clk_val = self._encoder_request.get_value(_ENC_CLK_PIN)
                    # XOR: when CLK and DT match → one direction, differ → other
                    if (clk_val == Value.ACTIVE) == (dt_val == Value.ACTIVE):
                        events.append(InputEvent.NAV_UP)
                    else:
                        events.append(InputEvent.NAV_DOWN)

                elif pin == _ENC_SW_PIN:
                    events.append(InputEvent.PROFILE_LOAD)
        except Exception:
            logger.exception("Error reading encoder events")

    def _poll_pots(self) -> None:
        """Read potentiometers via MCP3008 SPI ADC at 10 Hz."""
        if self._spi is None:
            return
        try:
            raw = [
                self._spi_read_channel(self._spi, _CH_BURNER),
                self._spi_read_channel(self._spi, _CH_AIR),
                self._spi_read_channel(self._spi, _CH_DRUM),
                self._spi_read_channel(self._spi, _CH_SCROLL),
            ]

            # Apply deadband: only update if change exceeds threshold
            for i in range(4):
                if abs(raw[i] - self._last_adc[i]) >= _ADC_DEADBAND:
                    self._last_adc[i] = raw[i]

            self._state.burner = _adc_to_percent(self._last_adc[0])
            self._state.air = _adc_to_percent(self._last_adc[1])
            self._state.drum = _adc_to_percent(self._last_adc[2])
            self._state.scroll = _adc_to_percent(self._last_adc[3])
        except Exception:
            logger.exception("Error reading MCP3008")

    # --- Public interface --------------------------------------------------

    def poll_events(self) -> list[InputEvent]:
        """Poll all GPIO inputs and return pending events.

        Toggle/button/encoder events are returned as a list.
        Pot values are updated in-place on self._state at 10 Hz.
        """
        if not self._available:
            return []

        events: list[InputEvent] = []

        self._poll_toggles(events)
        self._poll_buttons(events)
        self._poll_encoder(events)

        # Read pots at 10 Hz (not every frame)
        now = time.monotonic()
        if now - self._last_pot_read >= _POT_READ_INTERVAL_S:
            self._last_pot_read = now
            self._poll_pots()

        return events

    @property
    def state(self) -> InputState:
        """Current control state from GPIO hardware."""
        return self._state

    def close(self) -> None:
        """Release all gpiod line requests and close SPI."""
        for name in ("_toggle_request", "_button_request", "_encoder_request"):
            req = getattr(self, name, None)
            if req is not None:
                try:
                    req.release()
                except Exception:
                    logger.exception("Error releasing %s", name)
                setattr(self, name, None)

        if self._spi is not None:
            try:
                self._spi.close()  # type: ignore[union-attr]
            except Exception:
                logger.exception("Error closing SPI")
            self._spi = None

        self._pots_available = False
        self._available = False
        logger.info("GPIO backend closed")
