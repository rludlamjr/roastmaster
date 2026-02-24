"""Rate of Rise (RoR) calculator for bean temperature."""

from collections import deque


class RoRCalculator:
    """Calculates the rate of temperature change in degrees per minute.

    Algorithm:
    1. Raw samples are smoothed with a simple moving average of width
       ``smoothing_window``.
    2. RoR is computed as the slope across ``delta_span`` smoothed samples:
       RoR = (smoothed[-1] - smoothed[-delta_span]) / (time_diff / 60)
    """

    def __init__(self, smoothing_window: int = 6, delta_span: int = 20) -> None:
        if smoothing_window < 1:
            raise ValueError("smoothing_window must be >= 1")
        if delta_span < 1:
            raise ValueError("delta_span must be >= 1")
        self.smoothing_window = smoothing_window
        self.delta_span = delta_span
        # Raw (elapsed, temp) samples — keep enough to fill smoothing window + delta_span
        self._raw_samples: deque[tuple[float, float]] = deque(
            maxlen=smoothing_window + delta_span
        )
        # Smoothed (elapsed, temp) samples — keep delta_span + 1 entries
        self._smoothed_samples: deque[tuple[float, float]] = deque(
            maxlen=delta_span + 1
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_sample(self, elapsed: float, temperature: float) -> None:
        """Add a new temperature sample and recompute the smoothed buffer."""
        self._raw_samples.append((elapsed, temperature))

        # Compute a new smoothed point if we have enough raw data.
        # The smoothed point is centred on the *most recent* window of raw
        # samples; its timestamp is the timestamp of the newest sample.
        if len(self._raw_samples) >= self.smoothing_window:
            window = list(self._raw_samples)[-self.smoothing_window :]
            avg_temp = sum(t for _, t in window) / self.smoothing_window
            # Use the timestamp of the newest sample in the window
            newest_elapsed = window[-1][0]
            self._smoothed_samples.append((newest_elapsed, avg_temp))

    @property
    def current_ror(self) -> float | None:
        """Current rate of rise in degrees/minute.

        Returns None if there are not enough data points to compute a result.
        """
        if len(self._smoothed_samples) < self.delta_span + 1:
            return None

        samples = list(self._smoothed_samples)
        t0, temp0 = samples[-(self.delta_span + 1)]
        t1, temp1 = samples[-1]

        time_diff = t1 - t0
        if time_diff == 0:
            return None

        return (temp1 - temp0) / (time_diff / 60.0)

    def reset(self) -> None:
        """Clear all samples."""
        self._raw_samples.clear()
        self._smoothed_samples.clear()
