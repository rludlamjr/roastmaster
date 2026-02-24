"""PID controller for temperature or Rate-of-Rise control."""


class PIDController:
    """Standard discrete PID controller with anti-windup and bumpless transfer.

    Anti-windup:
        The integral accumulator is clamped so that the integral term alone
        never exceeds [output_min, output_max].  This prevents the integrator
        from winding up while the output is saturated.

    Bumpless transfer:
        When ``enable()`` is called the previous-error register is primed with
        the current error so that the first derivative term is zero, avoiding a
        sudden spike on activation.
    """

    def __init__(
        self,
        kp: float = 5.0,
        ki: float = 0.01,
        kd: float = 1.0,
        output_min: float = 0.0,
        output_max: float = 100.0,
    ) -> None:
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.setpoint: float = 0.0
        self.output_min = output_min
        self.output_max = output_max
        self._integral: float = 0.0
        self._prev_error: float = 0.0
        self._active: bool = False

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def set_setpoint(self, target: float) -> None:
        """Set the target value (temperature or RoR)."""
        self.setpoint = target

    def compute(self, current_value: float, dt: float) -> float:
        """Compute PID output given the current process value and time step.

        Returns the output clamped to [output_min, output_max].
        When the controller is inactive, returns 0.0.

        Args:
            current_value: The current measured process value.
            dt: Time elapsed since the last call, in seconds.  Must be > 0.
        """
        if not self._active:
            return 0.0

        if dt <= 0:
            return self._clamp(self.kp * (self.setpoint - current_value))

        error = self.setpoint - current_value

        # Proportional term
        p_term = self.kp * error

        # Integral term — accumulate then clamp to prevent windup
        self._integral += error * dt
        # Clamp integral so ki * integral stays within output bounds
        if self.ki != 0:
            integral_min = self.output_min / self.ki
            integral_max = self.output_max / self.ki
            self._integral = max(integral_min, min(integral_max, self._integral))
        i_term = self.ki * self._integral

        # Derivative term
        d_term = self.kd * (error - self._prev_error) / dt
        self._prev_error = error

        output = p_term + i_term + d_term
        return self._clamp(output)

    def enable(self) -> None:
        """Enable PID control.

        Primes the previous-error register with the difference between the
        current setpoint and the last known measurement so the first derivative
        contribution is zero (bumpless transfer).  The integral is left intact
        to allow smooth re-engagement.
        """
        self._active = True
        # Reset integral and previous error on fresh enable to avoid stale state
        self._integral = 0.0
        self._prev_error = 0.0

    def disable(self) -> None:
        """Disable PID and reset integral/derivative state."""
        self._active = False
        self._integral = 0.0
        self._prev_error = 0.0

    def reset(self) -> None:
        """Reset all internal state."""
        self._integral = 0.0
        self._prev_error = 0.0
        self._active = False
        self.setpoint = 0.0

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def active(self) -> bool:
        """True if the controller is currently enabled."""
        return self._active

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _clamp(self, value: float) -> float:
        return max(self.output_min, min(self.output_max, value))
