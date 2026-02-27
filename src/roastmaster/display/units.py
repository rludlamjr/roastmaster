"""Temperature unit conversion functions.

All internal data is stored in Fahrenheit. These pure functions convert
at the display boundary only.
"""


def f_to_c(fahrenheit: float) -> float:
    """Convert an absolute temperature from Fahrenheit to Celsius."""
    return (fahrenheit - 32.0) * 5.0 / 9.0


def f_to_c_delta(delta_f: float) -> float:
    """Convert a rate/delta (e.g. RoR) from F to C."""
    return delta_f / 1.8


def c_to_f(celsius: float) -> float:
    """Convert an absolute temperature from Celsius to Fahrenheit."""
    return celsius * 9.0 / 5.0 + 32.0
