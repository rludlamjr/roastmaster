"""Simulator adapter implementing the RoasterDevice protocol.

Wraps :class:`~roastmaster.sim.roaster_sim.RoasterSimulator` so that it can
be used anywhere the real :class:`~roastmaster.serial.kaleido.KaleidoDevice`
would be used, without any changes to the rest of the application.

The adapter is responsible for:
- Managing a "connected" lifecycle (connect / disconnect).
- Advancing the physics simulation by the wall-clock time elapsed since the
  last :meth:`read_temperatures` call.
- Translating simulator outputs into
  :class:`~roastmaster.serial.protocol.RoasterReading` objects.
- Optional fault injection for testing error-handling paths.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

from roastmaster.serial.protocol import RoasterReading
from roastmaster.sim.roaster_sim import RoasterSimulator

# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------


class FaultType(Enum):
    """Types of faults that can be injected into the simulator."""

    DISCONNECT = auto()     # Simulate a serial disconnect
    SENSOR_FAILURE = auto()  # Return NaN for sensor readings
    TIMEOUT = auto()         # Raise TimeoutError on read
    GARBLED = auto()         # Return nonsensical temperature values


@dataclass
class FaultConfig:
    """Configuration for fault injection on the simulated device.

    Faults are triggered after a set number of reads (``trigger_after``).
    Once triggered, the fault persists for ``duration_reads`` consecutive
    reads, then deactivates.  Set ``duration_reads`` to -1 for a permanent
    fault.
    """

    fault_type: FaultType
    trigger_after: int = 0      # activate after this many reads
    duration_reads: int = 1     # how many reads the fault lasts (-1 = permanent)

    # Internal counters (managed by the adapter)
    _reads_until_trigger: int = field(init=False, default=0)
    _remaining: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self._reads_until_trigger = self.trigger_after
        self._remaining = self.duration_reads

_MAX_SUBSTEP = 1.0  # seconds – keep Euler integration stable


class SimulatedRoasterDevice:
    """Adapter: wraps :class:`RoasterSimulator` to implement the RoasterDevice protocol.

    The underlying :class:`RoasterSimulator` is **not** modified; this class
    purely provides the lifecycle and I/O interface expected by the protocol.

    Usage::

        device = SimulatedRoasterDevice(ambient_temp_f=70.0)
        device.connect()
        reading = device.read_temperatures()
        device.set_heater(80)
        device.set_drum(60)
        device.set_fan(20)
        reading = device.read_temperatures()
        device.disconnect()

    Time advances automatically: each call to :meth:`read_temperatures`
    measures the elapsed wall-clock time since the previous call (or since
    :meth:`connect`) and advances the simulation by that delta.  Large
    elapsed intervals are broken into sub-steps of at most
    :data:`_MAX_SUBSTEP` seconds to keep the Euler integrator stable.
    """

    def __init__(self, ambient_temp_f: float = 70.0) -> None:
        """Initialise the adapter and its underlying simulator.

        Args:
            ambient_temp_f: Starting and ambient room temperature in Fahrenheit.
                Defaults to 70.0°F (a typical indoor environment).
        """
        self._sim = RoasterSimulator(ambient_temp_f)
        self._connected: bool = False
        self._last_update: float = time.time()
        self._faults: list[FaultConfig] = []
        self._read_count: int = 0

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Mark the simulated device as connected.

        Resets the internal time reference so that the first
        :meth:`read_temperatures` call does not accumulate stale elapsed time.
        """
        self._connected = True
        self._last_update = time.time()

    def disconnect(self) -> None:
        """Mark the simulated device as disconnected."""
        self._connected = False

    @property
    def connected(self) -> bool:
        """``True`` when the simulated device is connected."""
        return self._connected

    # ------------------------------------------------------------------
    # Fault injection API
    # ------------------------------------------------------------------

    def inject_fault(self, fault: FaultConfig) -> None:
        """Schedule a fault to occur during future reads."""
        self._faults.append(fault)

    def clear_faults(self) -> None:
        """Remove all scheduled faults."""
        self._faults.clear()

    def _check_faults(self) -> FaultType | None:
        """Check if any fault should fire on this read, and return its type.

        Returns None if no fault is active.
        """
        for fault in self._faults:
            if fault._reads_until_trigger > 0:
                fault._reads_until_trigger -= 1
                continue
            # Fault is triggered
            if fault._remaining == 0:
                continue  # already exhausted
            if fault._remaining > 0:
                fault._remaining -= 1
            # _remaining == -1 means permanent
            return fault.fault_type
        return None

    # ------------------------------------------------------------------
    # Temperature reading
    # ------------------------------------------------------------------

    def read_temperatures(self) -> RoasterReading:
        """Advance the simulation and return the current temperatures.

        The simulation is advanced by the wall-clock time elapsed since the
        previous call (or since :meth:`connect`).

        Returns:
            A :class:`~roastmaster.serial.protocol.RoasterReading` populated
            with the current simulated BT and ET (including sensor noise) and
            the current wall-clock timestamp.

        Raises:
            RuntimeError: If the device is not connected.
        """
        if not self._connected:
            raise RuntimeError(
                "SimulatedRoasterDevice is not connected. Call connect() first."
            )

        self._read_count += 1
        fault = self._check_faults()

        if fault == FaultType.DISCONNECT:
            self._connected = False
            raise ConnectionError("Simulated serial disconnect")

        if fault == FaultType.TIMEOUT:
            raise TimeoutError("Simulated read timeout")

        now = time.time()
        dt = now - self._last_update
        # Sub-step to keep the Euler integrator stable for large dt values.
        while dt > 0:
            step = min(dt, _MAX_SUBSTEP)
            self._sim.update(step)
            dt -= step
        self._last_update = now

        if fault == FaultType.SENSOR_FAILURE:
            return RoasterReading(
                bean_temp=float("nan"),
                env_temp=float("nan"),
                timestamp=now,
            )

        if fault == FaultType.GARBLED:
            return RoasterReading(
                bean_temp=-999.9,
                env_temp=99999.9,
                timestamp=now,
            )

        return RoasterReading(
            bean_temp=self._sim.bean_temp,
            env_temp=self._sim.env_temp,
            timestamp=now,
        )

    # ------------------------------------------------------------------
    # Control setters - delegate directly to the simulator
    # ------------------------------------------------------------------

    def set_heater(self, power: int) -> None:
        """Set heater/burner power.

        Args:
            power: Heater power in the range 0-100 (percent).

        Raises:
            ValueError: If *power* is outside [0, 100] (raised by the
                underlying simulator).
        """
        self._sim.set_heater(power)

    def set_drum(self, speed: int) -> None:
        """Set drum rotation speed.

        Args:
            speed: Drum speed in the range 0-100 (percent).

        Raises:
            ValueError: If *speed* is outside [0, 100] (raised by the
                underlying simulator).
        """
        self._sim.set_drum(speed)

    def set_fan(self, speed: int) -> None:
        """Set fan/air speed.

        Args:
            speed: Fan speed in the range 0-100 (percent).

        Raises:
            ValueError: If *speed* is outside [0, 100] (raised by the
                underlying simulator).
        """
        self._sim.set_fan(speed)

    def set_heating_switch(self, enabled: bool) -> None:
        """No-op for the simulator (real devices may gate heater output)."""
        return None

    def set_cooling_switch(self, enabled: bool) -> None:
        """No-op for the simulator."""
        return None

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"SimulatedRoasterDevice({self._sim!r}, status={status})"
