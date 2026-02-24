"""Abstract roaster device interface.

Defines the RoasterReading dataclass and the RoasterDevice Protocol that both
the real Kaleido serial driver and the simulator adapter implement.  Any code
that wants to talk to *a* roaster (real or simulated) should type-hint against
RoasterDevice so that the two backends are interchangeable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RoasterReading:
    """A single temperature reading from the roaster.

    Attributes:
        bean_temp: Bean temperature (BT) in Fahrenheit.
        env_temp: Drum environment temperature (ET) in Fahrenheit.
        timestamp: Wall-clock time when the reading was taken (``time.time()``).
    """

    bean_temp: float
    env_temp: float
    timestamp: float = field(default_factory=time.time)


class RoasterDevice(Protocol):
    """Abstract interface for any roaster connection (real or simulated).

    Both :class:`~roastmaster.serial.kaleido.KaleidoDevice` and
    :class:`~roastmaster.sim.device_adapter.SimulatedRoasterDevice` satisfy
    this protocol so they can be used interchangeably throughout the
    application.
    """

    def connect(self) -> None:
        """Establish a connection to the roaster."""
        ...

    def disconnect(self) -> None:
        """Close the connection to the roaster."""
        ...

    @property
    def connected(self) -> bool:
        """``True`` when the device is currently connected."""
        ...

    def read_temperatures(self) -> RoasterReading:
        """Read the current BT and ET from the roaster.

        Returns:
            A :class:`RoasterReading` populated with the current sensor values
            and the current wall-clock timestamp.
        """
        ...

    def set_heater(self, power: int) -> None:
        """Set the heater/burner power.

        Args:
            power: Heater power in the range 0-100 (percent).
        """
        ...

    def set_drum(self, speed: int) -> None:
        """Set the drum rotation speed.

        Args:
            speed: Drum speed in the range 0-100 (percent).
        """
        ...

    def set_fan(self, speed: int) -> None:
        """Set the fan/air speed.

        Args:
            speed: Fan speed in the range 0-100 (percent).
        """
        ...

    def set_heating_switch(self, enabled: bool) -> None:
        """Enable/disable the roaster's heating system (if supported).

        On the Kaleido M1 Lite this maps to the ``HS`` tag (heating switch).
        """
        ...

    def set_cooling_switch(self, enabled: bool) -> None:
        """Enable/disable the roaster's cooling system (if supported).

        On the Kaleido M1 Lite this maps to the ``CS`` tag (cooling switch).
        """
        ...

    def set_pid_mode(self, enabled: bool) -> None:
        """Enable/disable the roaster's internal PID / auto-heat mode (if supported).

        On the Kaleido M1 Lite this maps to the ``AH`` tag (auto heating).
        """
        ...

    def set_setpoint(self, temp: float) -> None:
        """Set the roaster's temperature setpoint / SV (if supported).

        On the Kaleido M1 Lite this maps to the ``TS`` tag (target temperature).
        """
        ...

    def mark_event(self, code: int) -> None:
        """Send a roaster-side event marker (if supported).

        On the Kaleido M1 Lite this maps to the ``EV`` tag.
        """
        ...
