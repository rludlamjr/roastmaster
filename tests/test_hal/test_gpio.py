"""Tests for the GPIO input backend and hybrid input compositor."""

from unittest.mock import MagicMock, patch

from roastmaster.hal.base import InputEvent, InputState
from roastmaster.hal.gpio import _adc_to_percent
from roastmaster.hal.hybrid import HybridInput

# ---------------------------------------------------------------------------
# _adc_to_percent — pure function tests
# ---------------------------------------------------------------------------


class TestAdcToPercent:
    """Test the MCP3008 ADC to percentage conversion."""

    def test_zero_returns_zero(self):
        assert _adc_to_percent(0) == 0

    def test_negative_returns_zero(self):
        assert _adc_to_percent(-100) == 0

    def test_max_returns_100(self):
        assert _adc_to_percent(1023) == 100

    def test_overflow_returns_100(self):
        assert _adc_to_percent(2000) == 100

    def test_half_scale(self):
        result = _adc_to_percent(512)
        assert result == 50

    def test_quarter_scale(self):
        result = _adc_to_percent(256)
        assert result == 25

    def test_small_value(self):
        result = _adc_to_percent(10)
        assert result == 1

    def test_just_below_max(self):
        result = _adc_to_percent(1022)
        assert result == 100  # rounds to 100


# ---------------------------------------------------------------------------
# GPIOInput fallback (no gpiod available)
# ---------------------------------------------------------------------------


class TestGPIOInputFallback:
    """Verify GPIOInput enters no-op mode when gpiod is unavailable."""

    def test_not_available(self):
        with patch("roastmaster.hal.gpio._GPIOD_AVAILABLE", False):
            from roastmaster.hal.gpio import GPIOInput

            gpio = GPIOInput()
            assert gpio.available is False

    def test_pots_not_available(self):
        with patch("roastmaster.hal.gpio._GPIOD_AVAILABLE", False):
            from roastmaster.hal.gpio import GPIOInput

            gpio = GPIOInput()
            assert gpio.pots_available is False

    def test_poll_events_returns_empty(self):
        with patch("roastmaster.hal.gpio._GPIOD_AVAILABLE", False):
            from roastmaster.hal.gpio import GPIOInput

            gpio = GPIOInput()
            assert gpio.poll_events() == []

    def test_state_returns_defaults(self):
        with patch("roastmaster.hal.gpio._GPIOD_AVAILABLE", False):
            from roastmaster.hal.gpio import GPIOInput

            gpio = GPIOInput()
            state = gpio.state
            assert isinstance(state, InputState)
            assert state.burner == 0
            assert state.drum == 50
            assert state.air == 50
            assert state.scroll == 100

    def test_close_is_safe(self):
        with patch("roastmaster.hal.gpio._GPIOD_AVAILABLE", False):
            from roastmaster.hal.gpio import GPIOInput

            gpio = GPIOInput()
            gpio.close()  # should not raise


# ---------------------------------------------------------------------------
# HybridInput — event merging and delegation
# ---------------------------------------------------------------------------


class TestHybridInput:
    """Test that HybridInput correctly merges events and delegates state."""

    def test_merges_events_from_both_backends(self):
        keyboard = MagicMock()
        gpio = MagicMock()
        keyboard.poll_events.return_value = [InputEvent.CHARGE]
        gpio.poll_events.return_value = [InputEvent.HEAT_TOGGLE]

        hybrid = HybridInput(keyboard=keyboard, gpio=gpio)
        events = hybrid.poll_events()

        assert InputEvent.CHARGE in events
        assert InputEvent.HEAT_TOGGLE in events
        assert len(events) == 2

    def test_gpio_events_come_first(self):
        keyboard = MagicMock()
        gpio = MagicMock()
        keyboard.poll_events.return_value = [InputEvent.QUIT]
        gpio.poll_events.return_value = [InputEvent.COOL_TOGGLE]

        hybrid = HybridInput(keyboard=keyboard, gpio=gpio)
        events = hybrid.poll_events()

        assert events[0] == InputEvent.COOL_TOGGLE
        assert events[1] == InputEvent.QUIT

    def test_empty_events_from_both(self):
        keyboard = MagicMock()
        gpio = MagicMock()
        keyboard.poll_events.return_value = []
        gpio.poll_events.return_value = []

        hybrid = HybridInput(keyboard=keyboard, gpio=gpio)
        assert hybrid.poll_events() == []

    def test_state_delegates_to_gpio_when_pots_available(self):
        keyboard = MagicMock()
        gpio = MagicMock()
        gpio.pots_available = True
        gpio_state = InputState(burner=42, drum=77, air=15)
        gpio.state = gpio_state

        hybrid = HybridInput(keyboard=keyboard, gpio=gpio)
        assert hybrid.state is gpio_state
        assert hybrid.state.burner == 42
        assert hybrid.state.drum == 77
        assert hybrid.state.air == 15

    def test_state_falls_back_to_keyboard_when_pots_unavailable(self):
        keyboard = MagicMock()
        gpio = MagicMock()
        gpio.pots_available = False
        kb_state = InputState(burner=30, drum=60, air=80)
        keyboard.state = kb_state

        hybrid = HybridInput(keyboard=keyboard, gpio=gpio)
        assert hybrid.state is kb_state
        assert hybrid.state.burner == 30

    def test_state_falls_back_when_gpio_has_no_pots_available_attr(self):
        keyboard = MagicMock()
        gpio = MagicMock(spec=[])  # no attributes
        gpio.poll_events = MagicMock(return_value=[])
        kb_state = InputState(burner=10, drum=20, air=30)
        keyboard.state = kb_state

        hybrid = HybridInput(keyboard=keyboard, gpio=gpio)
        assert hybrid.state is kb_state


class TestHybridInputClose:
    """Verify close propagates to GPIO backend."""

    def test_close_calls_gpio_close(self):
        keyboard = MagicMock()
        gpio = MagicMock()

        hybrid = HybridInput(keyboard=keyboard, gpio=gpio)
        hybrid.close()

        gpio.close.assert_called_once()

    def test_close_safe_without_gpio_close_method(self):
        keyboard = MagicMock()
        gpio = object()  # no close method

        hybrid = HybridInput(keyboard=keyboard, gpio=gpio)
        hybrid.close()  # should not raise
