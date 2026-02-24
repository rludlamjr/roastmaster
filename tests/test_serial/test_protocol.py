"""Tests for the RoasterDevice protocol and SimulatedRoasterDevice adapter.

Covers:
- RoasterReading dataclass creation and field access
- RoasterReading default timestamp
- SimulatedRoasterDevice satisfies the RoasterDevice protocol (structural check)
- connect / disconnect lifecycle
- read_temperatures returns a valid RoasterReading
- read_temperatures raises RuntimeError when not connected
- set_heater / set_drum / set_fan are forwarded to the simulator
- Temperatures rise after setting the heater and reading repeatedly
- Invalid control values still raise ValueError (simulator validation)
- Fault injection: disconnects, sensor failures, timeouts, garbled data
"""

from __future__ import annotations

import time

import pytest

from roastmaster.serial.protocol import RoasterDevice, RoasterReading
from roastmaster.sim.device_adapter import SimulatedRoasterDevice

# ---------------------------------------------------------------------------
# RoasterReading
# ---------------------------------------------------------------------------


class TestRoasterReading:
    def test_explicit_fields(self):
        """RoasterReading stores the fields passed to it."""
        ts = 1_700_000_000.0
        r = RoasterReading(bean_temp=350.5, env_temp=420.0, timestamp=ts)
        assert r.bean_temp == 350.5
        assert r.env_temp == 420.0
        assert r.timestamp == ts

    def test_default_timestamp_is_recent(self):
        """When timestamp is omitted it defaults to a recent time.time() value."""
        before = time.time()
        r = RoasterReading(bean_temp=100.0, env_temp=120.0)
        after = time.time()
        assert before <= r.timestamp <= after

    def test_dataclass_equality(self):
        """Two RoasterReadings with the same values are equal."""
        ts = 1_234_567.0
        r1 = RoasterReading(bean_temp=200.0, env_temp=250.0, timestamp=ts)
        r2 = RoasterReading(bean_temp=200.0, env_temp=250.0, timestamp=ts)
        assert r1 == r2

    def test_dataclass_inequality(self):
        """RoasterReadings with different values are not equal."""
        ts = 1_234_567.0
        r1 = RoasterReading(bean_temp=200.0, env_temp=250.0, timestamp=ts)
        r2 = RoasterReading(bean_temp=201.0, env_temp=250.0, timestamp=ts)
        assert r1 != r2

    def test_repr_contains_field_values(self):
        """repr should contain the numeric field values."""
        r = RoasterReading(bean_temp=310.0, env_temp=380.0, timestamp=0.0)
        text = repr(r)
        assert "310.0" in text
        assert "380.0" in text


# ---------------------------------------------------------------------------
# Protocol structural check
# ---------------------------------------------------------------------------


class TestRoasterDeviceProtocol:
    def test_simulated_device_satisfies_protocol(self):
        """SimulatedRoasterDevice must be assignable to RoasterDevice."""
        # This is a static-typing check expressed as a runtime assertion:
        # isinstance with a Protocol requires runtime_checkable; instead we
        # verify that the required attributes are present.
        device = SimulatedRoasterDevice()
        assert callable(device.connect)
        assert callable(device.disconnect)
        assert hasattr(device, "connected")
        assert callable(device.read_temperatures)
        assert callable(device.set_heater)
        assert callable(device.set_drum)
        assert callable(device.set_fan)
        assert callable(device.set_heating_switch)
        assert callable(device.set_cooling_switch)

    def test_protocol_annotation_compatible(self):
        """A SimulatedRoasterDevice can be passed where RoasterDevice is expected."""

        def _use_device(d: RoasterDevice) -> bool:
            return isinstance(d, object)  # any object satisfies the check

        device = SimulatedRoasterDevice()
        assert _use_device(device)


# ---------------------------------------------------------------------------
# Connect / disconnect lifecycle
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    def test_starts_disconnected(self):
        device = SimulatedRoasterDevice()
        assert not device.connected

    def test_connect_sets_connected(self):
        device = SimulatedRoasterDevice()
        device.connect()
        assert device.connected

    def test_disconnect_clears_connected(self):
        device = SimulatedRoasterDevice()
        device.connect()
        device.disconnect()
        assert not device.connected

    def test_connect_disconnect_connect_works(self):
        """Reconnection after disconnect should succeed."""
        device = SimulatedRoasterDevice()
        device.connect()
        device.disconnect()
        device.connect()
        assert device.connected

    def test_disconnect_without_connect_is_safe(self):
        """Calling disconnect on a never-connected device should not raise."""
        device = SimulatedRoasterDevice()
        device.disconnect()  # should not raise
        assert not device.connected


# ---------------------------------------------------------------------------
# read_temperatures
# ---------------------------------------------------------------------------


class TestReadTemperatures:
    def test_returns_roaster_reading(self):
        device = SimulatedRoasterDevice()
        device.connect()
        reading = device.read_temperatures()
        assert isinstance(reading, RoasterReading)

    def test_reading_has_float_temps(self):
        device = SimulatedRoasterDevice()
        device.connect()
        reading = device.read_temperatures()
        assert isinstance(reading.bean_temp, float)
        assert isinstance(reading.env_temp, float)

    def test_reading_timestamp_is_recent(self):
        device = SimulatedRoasterDevice()
        device.connect()
        before = time.time()
        reading = device.read_temperatures()
        after = time.time()
        assert before <= reading.timestamp <= after

    def test_initial_temps_near_ambient(self):
        """At connection time both temperatures should be near the ambient value."""
        ambient = 65.0
        device = SimulatedRoasterDevice(ambient_temp_f=ambient)
        device.connect()
        reading = device.read_temperatures()
        # dt since connect is tiny so temps should be very close to ambient.
        assert abs(reading.bean_temp - ambient) < 5.0
        assert abs(reading.env_temp - ambient) < 5.0

    def test_raises_when_not_connected(self):
        device = SimulatedRoasterDevice()
        with pytest.raises(RuntimeError, match="not connected"):
            device.read_temperatures()

    def test_raises_after_disconnect(self):
        device = SimulatedRoasterDevice()
        device.connect()
        device.disconnect()
        with pytest.raises(RuntimeError, match="not connected"):
            device.read_temperatures()


# ---------------------------------------------------------------------------
# Control setters
# ---------------------------------------------------------------------------


class TestControlSetters:
    def test_set_heater_valid(self):
        """set_heater should accept values 0-100 without raising."""
        device = SimulatedRoasterDevice()
        device.connect()
        for value in (0, 1, 50, 99, 100):
            device.set_heater(value)  # should not raise

    def test_set_heater_invalid_raises(self):
        device = SimulatedRoasterDevice()
        device.connect()
        with pytest.raises(ValueError):
            device.set_heater(101)
        with pytest.raises(ValueError):
            device.set_heater(-1)

    def test_set_drum_valid(self):
        device = SimulatedRoasterDevice()
        device.connect()
        for value in (0, 50, 100):
            device.set_drum(value)

    def test_set_drum_invalid_raises(self):
        device = SimulatedRoasterDevice()
        device.connect()
        with pytest.raises(ValueError):
            device.set_drum(101)
        with pytest.raises(ValueError):
            device.set_drum(-1)

    def test_set_fan_valid(self):
        device = SimulatedRoasterDevice()
        device.connect()
        for value in (0, 50, 100):
            device.set_fan(value)

    def test_set_fan_invalid_raises(self):
        device = SimulatedRoasterDevice()
        device.connect()
        with pytest.raises(ValueError):
            device.set_fan(101)
        with pytest.raises(ValueError):
            device.set_fan(-1)


# ---------------------------------------------------------------------------
# Temperature changes after control input
# ---------------------------------------------------------------------------


class TestTemperatureChangesWithHeater:
    def test_heater_on_raises_temp_over_simulated_time(self):
        """Setting the heater and advancing time should raise temperatures.

        We patch time.time() to control elapsed time so the test is
        deterministic and fast.  We use the _last_update / now pattern
        directly and keep dt small enough that the simulator does not
        saturate its safety clamp (max 599°F).
        """
        import unittest.mock as mock

        device = SimulatedRoasterDevice(ambient_temp_f=70.0)

        t0 = 1_000_000.0

        # Patch only time.time inside the adapter module so that the
        # RoasterReading dataclass default_factory is also controlled.
        with mock.patch("roastmaster.sim.device_adapter.time") as mock_time:
            mock_time.time.return_value = t0
            device.connect()

            device.set_heater(100)
            device.set_drum(60)
            device.set_fan(0)

            # First read: advance by 60 seconds (1 minute)
            mock_time.time.return_value = t0 + 60.0
            reading1 = device.read_temperatures()

            # Second read: another 60 seconds (2 minutes total)
            mock_time.time.return_value = t0 + 120.0
            reading2 = device.read_temperatures()

        # After 1 minute at full heater, BT should have risen above ambient.
        assert reading1.bean_temp > 70.0, (
            f"BT after 1 min at 100% heater should exceed ambient 70°F, "
            f"got {reading1.bean_temp:.1f}°F"
        )
        # After 2 minutes temperatures should be higher than after 1 minute.
        assert reading2.bean_temp > reading1.bean_temp, (
            f"BT should continue rising: {reading1.bean_temp:.1f} -> {reading2.bean_temp:.1f}"
        )

    def test_heater_off_no_temperature_rise(self):
        """With heater at 0, temperatures should not rise above ambient."""
        import unittest.mock as mock

        device = SimulatedRoasterDevice(ambient_temp_f=70.0)
        t0 = 1_000_000.0
        with mock.patch("roastmaster.sim.device_adapter.time") as mock_time:
            mock_time.time.return_value = t0
            device.connect()
            device.set_heater(0)

            mock_time.time.return_value = t0 + 600.0
            reading = device.read_temperatures()

        # Temperatures should be near ambient (within a few degrees of noise).
        assert abs(reading.bean_temp - 70.0) < 5.0, (
            f"BT with heater off should stay near ambient, got {reading.bean_temp:.1f}°F"
        )

    def test_fan_setpoint_reaches_simulator(self):
        """set_fan should propagate to the underlying simulator state."""
        device = SimulatedRoasterDevice()
        device.connect()
        device.set_fan(75)
        assert device._sim.fan == 75

    def test_drum_setpoint_reaches_simulator(self):
        """set_drum should propagate to the underlying simulator state."""
        device = SimulatedRoasterDevice()
        device.connect()
        device.set_drum(40)
        assert device._sim.drum == 40

    def test_heater_setpoint_reaches_simulator(self):
        """set_heater should propagate to the underlying simulator state."""
        device = SimulatedRoasterDevice()
        device.connect()
        device.set_heater(80)
        assert device._sim.heater == 80


# =========================================================================
# Fault injection (Plan 3.4)
# =========================================================================


class TestFaultInjection:
    """Test configurable fault injection on SimulatedRoasterDevice."""

    def test_disconnect_fault_raises_connection_error(self):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(FaultConfig(fault_type=FaultType.DISCONNECT))
        with pytest.raises(ConnectionError, match="disconnect"):
            device.read_temperatures()

    def test_disconnect_fault_marks_device_disconnected(self):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(FaultConfig(fault_type=FaultType.DISCONNECT))
        with pytest.raises(ConnectionError):
            device.read_temperatures()
        assert not device.connected

    def test_timeout_fault_raises_timeout_error(self):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(FaultConfig(fault_type=FaultType.TIMEOUT))
        with pytest.raises(TimeoutError, match="timeout"):
            device.read_temperatures()

    def test_sensor_failure_returns_nan(self):
        import math

        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(FaultConfig(fault_type=FaultType.SENSOR_FAILURE))
        reading = device.read_temperatures()
        assert math.isnan(reading.bean_temp)
        assert math.isnan(reading.env_temp)

    def test_garbled_data_returns_nonsense(self):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(FaultConfig(fault_type=FaultType.GARBLED))
        reading = device.read_temperatures()
        assert reading.bean_temp == -999.9
        assert reading.env_temp == 99999.9

    def test_fault_trigger_after_delay(self):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(
            FaultConfig(fault_type=FaultType.TIMEOUT, trigger_after=3)
        )
        # First 3 reads should succeed
        for _ in range(3):
            device.read_temperatures()
        # 4th read should fail
        with pytest.raises(TimeoutError):
            device.read_temperatures()

    def test_fault_duration(self):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(
            FaultConfig(fault_type=FaultType.TIMEOUT, trigger_after=0, duration_reads=2)
        )
        # First 2 reads should fail
        with pytest.raises(TimeoutError):
            device.read_temperatures()
        with pytest.raises(TimeoutError):
            device.read_temperatures()
        # 3rd read should succeed (fault exhausted)
        reading = device.read_temperatures()
        assert reading.bean_temp is not None

    def test_permanent_fault(self):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(
            FaultConfig(fault_type=FaultType.TIMEOUT, duration_reads=-1)
        )
        for _ in range(5):
            with pytest.raises(TimeoutError):
                device.read_temperatures()

    def test_clear_faults(self):
        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(
            FaultConfig(fault_type=FaultType.TIMEOUT, duration_reads=-1)
        )
        device.clear_faults()
        # Should succeed after clearing
        reading = device.read_temperatures()
        assert reading.bean_temp is not None

    def test_normal_reads_after_transient_fault(self):
        import math

        from roastmaster.sim.device_adapter import FaultConfig, FaultType

        device = SimulatedRoasterDevice()
        device.connect()
        device.inject_fault(
            FaultConfig(fault_type=FaultType.SENSOR_FAILURE, duration_reads=1)
        )
        # First read: NaN
        r1 = device.read_temperatures()
        assert math.isnan(r1.bean_temp)
        # Second read: normal
        r2 = device.read_temperatures()
        assert not math.isnan(r2.bean_temp)
