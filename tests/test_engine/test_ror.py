"""Tests for RoRCalculator."""

import pytest

from roastmaster.engine.ror import RoRCalculator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def feed_linear(
    calc: RoRCalculator,
    rate_per_min: float,
    n_samples: int = 20,
    interval_s: float = 5.0,
    start_temp: float = 150.0,
    start_elapsed: float = 0.0,
) -> None:
    """Feed linearly increasing samples at the given rate (degrees/minute)."""
    rate_per_sec = rate_per_min / 60.0
    for i in range(n_samples):
        elapsed = start_elapsed + i * interval_s
        temp = start_temp + rate_per_sec * (elapsed - start_elapsed)
        calc.add_sample(elapsed, temp)


# ---------------------------------------------------------------------------
# Not enough data returns None
# ---------------------------------------------------------------------------


def test_no_samples_returns_none():
    calc = RoRCalculator()
    assert calc.current_ror is None


def test_insufficient_samples_returns_none():
    calc = RoRCalculator(smoothing_window=6, delta_span=5)
    # Need smoothing_window + delta_span samples to have delta_span+1 smoothed points
    for i in range(5):
        calc.add_sample(float(i * 5), 150.0 + i)
    assert calc.current_ror is None


def test_exactly_enough_samples_returns_value():
    """Once we have delta_span+1 smoothed points, current_ror should return a float."""
    calc = RoRCalculator(smoothing_window=3, delta_span=2)
    # Need smoothing_window + delta_span = 5 samples to get 3 smoothed points
    for i in range(5):
        calc.add_sample(float(i * 5), 150.0 + i * 0.5)
    result = calc.current_ror
    assert result is not None
    assert isinstance(result, float)


# ---------------------------------------------------------------------------
# Constant temperature gives RoR of 0
# ---------------------------------------------------------------------------


def test_constant_temperature_ror_is_zero():
    calc = RoRCalculator(smoothing_window=3, delta_span=3)
    for i in range(20):
        calc.add_sample(float(i * 5), 175.0)
    assert calc.current_ror == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Linearly increasing temperature gives correct RoR
# ---------------------------------------------------------------------------


def test_linear_increase_correct_ror():
    """10 deg/min rate with 5-second intervals should return ~10 deg/min."""
    calc = RoRCalculator(smoothing_window=3, delta_span=3)
    feed_linear(calc, rate_per_min=10.0, n_samples=20, interval_s=5.0)
    ror = calc.current_ror
    assert ror is not None
    assert ror == pytest.approx(10.0, rel=0.05)


def test_linear_increase_higher_rate():
    calc = RoRCalculator(smoothing_window=3, delta_span=3)
    feed_linear(calc, rate_per_min=20.0, n_samples=20, interval_s=5.0)
    ror = calc.current_ror
    assert ror is not None
    assert ror == pytest.approx(20.0, rel=0.05)


def test_linear_decrease_negative_ror():
    calc = RoRCalculator(smoothing_window=3, delta_span=3)
    feed_linear(calc, rate_per_min=-5.0, n_samples=20, interval_s=5.0)
    ror = calc.current_ror
    assert ror is not None
    assert ror == pytest.approx(-5.0, rel=0.05)


# ---------------------------------------------------------------------------
# Smoothing reduces noise
# ---------------------------------------------------------------------------


def test_larger_smoothing_window_reduces_noise():
    """With noisy data, a larger window should give a result closer to true rate."""
    import random

    random.seed(42)
    rate = 10.0  # deg/min
    rate_per_sec = rate / 60.0
    interval = 5.0
    n = 30
    noise_amplitude = 2.0

    # Small smoothing window (more susceptible to noise)
    calc_small = RoRCalculator(smoothing_window=2, delta_span=3)
    # Large smoothing window (less susceptible to noise)
    calc_large = RoRCalculator(smoothing_window=8, delta_span=3)

    for i in range(n):
        elapsed = float(i * interval)
        temp = 150.0 + rate_per_sec * elapsed + random.uniform(-noise_amplitude, noise_amplitude)
        calc_small.add_sample(elapsed, temp)
        calc_large.add_sample(elapsed, temp)

    ror_small = calc_small.current_ror
    ror_large = calc_large.current_ror

    assert ror_small is not None
    assert ror_large is not None
    # Both should be in the right ballpark
    assert abs(ror_small - rate) < 15.0
    assert abs(ror_large - rate) < 10.0


# ---------------------------------------------------------------------------
# Reset clears state
# ---------------------------------------------------------------------------


def test_reset_makes_ror_none():
    calc = RoRCalculator(smoothing_window=3, delta_span=3)
    feed_linear(calc, rate_per_min=10.0, n_samples=20)
    assert calc.current_ror is not None
    calc.reset()
    assert calc.current_ror is None


def test_reset_allows_fresh_start():
    calc = RoRCalculator(smoothing_window=3, delta_span=3)
    feed_linear(calc, rate_per_min=10.0, n_samples=20)
    calc.reset()
    feed_linear(calc, rate_per_min=5.0, n_samples=20)
    ror = calc.current_ror
    assert ror is not None
    assert ror == pytest.approx(5.0, rel=0.05)


# ---------------------------------------------------------------------------
# Different delta_span values produce different results
# ---------------------------------------------------------------------------


def test_different_delta_span_produces_different_smoothing():
    """A larger delta_span averages across more time, affecting short-term noise."""
    calc_short = RoRCalculator(smoothing_window=3, delta_span=2)
    calc_long = RoRCalculator(smoothing_window=3, delta_span=6)

    # Feed linearly increasing then stepped data.
    # Read RoR shortly after the rate change so the two calculators
    # haven't both fully converged to the new rate yet.
    for i in range(19):
        elapsed = float(i * 5)
        if i < 15:
            temp = 150.0 + (10.0 / 60.0) * elapsed  # 10 deg/min
        else:
            temp = 150.0 + (10.0 / 60.0) * (15 * 5) + (20.0 / 60.0) * ((i - 15) * 5)
        calc_short.add_sample(elapsed, temp)
        calc_long.add_sample(elapsed, temp)

    ror_short = calc_short.current_ror
    ror_long = calc_long.current_ror

    assert ror_short is not None
    assert ror_long is not None
    # Shortly after the rate change the short span should have adapted
    # while the long span still straddles the transition.
    assert ror_short != pytest.approx(ror_long, rel=0.01)


def test_smaller_delta_span_more_responsive():
    """Smaller delta_span should track a rate change faster than a larger one."""
    calc_short = RoRCalculator(smoothing_window=2, delta_span=2)
    calc_long = RoRCalculator(smoothing_window=2, delta_span=8)

    # Feed data at 10 deg/min for a long while, then switch to 30 deg/min
    interval = 5.0
    for i in range(30):
        elapsed = float(i * interval)
        temp = 150.0 + (10.0 / 60.0) * elapsed
        calc_short.add_sample(elapsed, temp)
        calc_long.add_sample(elapsed, temp)

    # Now switch to 30 deg/min — only feed a few samples so the long
    # delta_span hasn't fully converged while the short one has.
    base_temp = 150.0 + (10.0 / 60.0) * (29 * interval)
    base_elapsed = 29 * interval
    for i in range(1, 6):
        elapsed = base_elapsed + i * interval
        temp = base_temp + (30.0 / 60.0) * (i * interval)
        calc_short.add_sample(elapsed, temp)
        calc_long.add_sample(elapsed, temp)

    ror_short = calc_short.current_ror
    ror_long = calc_long.current_ror

    assert ror_short is not None
    assert ror_long is not None
    # Short delta_span should be closer to 30, long one slower to respond
    assert abs(ror_short - 30.0) < abs(ror_long - 30.0)


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_invalid_smoothing_window_raises():
    with pytest.raises(ValueError):
        RoRCalculator(smoothing_window=0)


def test_invalid_delta_span_raises():
    with pytest.raises(ValueError):
        RoRCalculator(delta_span=0)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_single_sample_not_enough():
    calc = RoRCalculator(smoothing_window=1, delta_span=1)
    calc.add_sample(0.0, 150.0)
    # With smoothing_window=1 we get a smoothed point immediately, but need
    # delta_span+1=2 smoothed points, so still None
    assert calc.current_ror is None


def test_smoothing_window_1_delta_span_1_two_samples():
    """Minimal configuration: 2 samples with identical times → None (div-by-zero guard)."""
    calc = RoRCalculator(smoothing_window=1, delta_span=1)
    calc.add_sample(0.0, 150.0)
    calc.add_sample(0.0, 155.0)  # same timestamp
    assert calc.current_ror is None
