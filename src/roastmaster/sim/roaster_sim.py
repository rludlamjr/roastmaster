"""Kaleido M1 Lite roaster physics simulator.

Simulates realistic coffee roasting temperature curves for development and testing
without physical hardware. Uses first-order thermal dynamics to model the heat
transfer between the heating element, drum environment (ET), and beans (BT).

Physics model:
- The heating element raises ET with a relatively fast time constant.
- ET drives BT through convection/conduction with a slower time constant.
- Fan speed increases heat transfer (convection) which both raises ET faster
  (more air movement through the drum) and cools BT relative to ET (the hotter
  air passes through more rapidly, increasing the ET-BT differential).
- Drum speed affects mixing efficiency: higher drum speed improves heat
  distribution but slightly reduces peak heat transfer to beans.
- First crack region (~385-400F) adds a small thermal absorption effect as
  endothermic steam/CO2 release temporarily flattens the BT curve.
- Small Gaussian noise is added to both sensors to mimic real thermocouple jitter.
"""

import random

# ---------------------------------------------------------------------------
# Thermal constants  (all temperatures in Fahrenheit)
# ---------------------------------------------------------------------------

# The ET time constant (seconds): how quickly the drum environment responds to
# a heater change. Smaller = faster response.
_ET_TIME_CONSTANT = 25.0

# The BT time constant (seconds): beans are thermally massive and respond slowly.
_BT_TIME_CONSTANT = 45.0

# Maximum temperature the heater can drive the ET to at 100% power (°F).
_MAX_HEATER_TARGET_ET = 570.0

# Ambient-to-heater-target scaling: at 0% power, heater target is ambient.
# At 100% power, it is _MAX_HEATER_TARGET_ET.

# Steady-state ET-BT offset driven by convection at zero fan (°F).
# Even with no fan the drum environment is hotter than the beans.
_BASE_ET_BT_OFFSET = 30.0

# Additional ET-BT offset per 1% of fan speed (°F / %).
_FAN_ET_BT_OFFSET_PER_PCT = 0.7

# Fan cooling factor on BT: each 1% of fan cools BT toward ambient by this
# fraction per second (very small - mostly affects the *differential* not BT directly).
_FAN_BT_COOLING_PER_PCT_PER_SEC = 0.0003

# Drum-speed mixing factor: higher drum speed multiplies the ET->BT heat transfer
# coefficient. Range 0.85 (drum=0) to 1.0 (drum=100).
_DRUM_HEAT_TRANSFER_MIN = 0.85
_DRUM_HEAT_TRANSFER_MAX = 1.00

# First-crack absorption: applied when BT is in [385, 400] °F as a negative
# delta that partially counteracts the rise.
_FIRST_CRACK_LOW_F = 385.0
_FIRST_CRACK_HIGH_F = 400.0
_FIRST_CRACK_ABSORPTION = 0.08  # fraction of net BT delta absorbed

# Sensor noise standard deviation (°F).
_BT_NOISE_STD = 0.3
_ET_NOISE_STD = 0.5


class RoasterSimulator:
    """Physics-based simulator for the Kaleido M1 Lite coffee roaster.

    All temperatures are in Fahrenheit. Call :meth:`update` regularly with the
    elapsed wall-clock delta (seconds) to advance the simulation. Read current
    temperatures via the :attr:`bean_temp` and :attr:`env_temp` properties.

    Example usage::

        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(80)
        sim.set_drum(60)
        sim.set_fan(20)

        for _ in range(600):          # 10 minutes at 1-second steps
            sim.update(1.0)
            print(sim.bean_temp, sim.env_temp)
    """

    def __init__(self, ambient_temp_f: float = 70.0) -> None:
        """Initialise the simulator.

        Args:
            ambient_temp_f: Starting (and ambient/room) temperature in Fahrenheit.
                Temperatures will decay toward this value when the heater is off.
        """
        self._ambient = ambient_temp_f

        # Internal (true) temperatures - noise is added only on readout.
        self._bt: float = ambient_temp_f
        self._et: float = ambient_temp_f

        # Control inputs (0-100).
        self._heater: int = 0
        self._drum: int = 0
        self._fan: int = 0

        # Seed the PRNG for reproducible noise if desired; by default use
        # system entropy so each run is different.
        self._rng = random.Random()

    # ------------------------------------------------------------------
    # Control setters
    # ------------------------------------------------------------------

    def set_heater(self, power: int) -> None:
        """Set heater power.

        Args:
            power: Heater power in the range 0-100 (percent).

        Raises:
            ValueError: If power is outside [0, 100].
        """
        if not 0 <= power <= 100:
            raise ValueError(f"Heater power must be 0-100, got {power}")
        self._heater = int(power)

    def set_drum(self, speed: int) -> None:
        """Set drum rotation speed.

        Args:
            speed: Drum speed in the range 0-100 (percent).

        Raises:
            ValueError: If speed is outside [0, 100].
        """
        if not 0 <= speed <= 100:
            raise ValueError(f"Drum speed must be 0-100, got {speed}")
        self._drum = int(speed)

    def set_fan(self, speed: int) -> None:
        """Set fan/airflow speed.

        Args:
            speed: Fan speed in the range 0-100 (percent).

        Raises:
            ValueError: If speed is outside [0, 100].
        """
        if not 0 <= speed <= 100:
            raise ValueError(f"Fan speed must be 0-100, got {speed}")
        self._fan = int(speed)

    # ------------------------------------------------------------------
    # Simulation step
    # ------------------------------------------------------------------

    def update(self, dt: float) -> None:
        """Advance the simulation by *dt* seconds.

        This uses Euler integration of first-order ODEs for ET and BT.
        For typical usage with dt <= 1.0 s this is accurate enough; for
        larger dt values the simulation remains stable but less precise.

        Args:
            dt: Time step in seconds. Should be positive.
        """
        if dt <= 0:
            return

        heater_pct = self._heater / 100.0   # 0.0 – 1.0
        fan_pct = self._fan / 100.0         # 0.0 – 1.0
        drum_pct = self._drum / 100.0       # 0.0 – 1.0

        # ----------------------------------------------------------------
        # 1. Compute the heater's target ET
        # ----------------------------------------------------------------
        # At 0% the heater target is ambient; at 100% it is _MAX_HEATER_TARGET_ET.
        heater_target_et = self._ambient + heater_pct * (_MAX_HEATER_TARGET_ET - self._ambient)

        # ----------------------------------------------------------------
        # 2. Update ET using first-order lag toward heater_target_et
        # ----------------------------------------------------------------
        # dET/dt = (heater_target_et - ET) / tau_ET
        et_error = heater_target_et - self._et
        d_et = (et_error / _ET_TIME_CONSTANT) * dt
        self._et += d_et

        # ----------------------------------------------------------------
        # 3. Compute the effective BT target
        # ----------------------------------------------------------------
        # The BT is driven toward (ET - offset), where offset grows with fan speed
        # to model the increased ET-BT differential from faster airflow.
        et_bt_offset = _BASE_ET_BT_OFFSET + fan_pct * 100.0 * _FAN_ET_BT_OFFSET_PER_PCT
        bt_target = self._et - et_bt_offset

        # Clamp bt_target so it cannot go below ambient (prevents negative runaway).
        bt_target = max(bt_target, self._ambient)

        # ----------------------------------------------------------------
        # 4. Drum-speed heat-transfer coefficient
        # ----------------------------------------------------------------
        # Higher drum speed = better mixing = slightly more efficient heat transfer.
        drum_transfer = (
            _DRUM_HEAT_TRANSFER_MIN
            + drum_pct * (_DRUM_HEAT_TRANSFER_MAX - _DRUM_HEAT_TRANSFER_MIN)
        )

        # ----------------------------------------------------------------
        # 5. Update BT using first-order lag toward bt_target
        # ----------------------------------------------------------------
        bt_error = bt_target - self._bt
        d_bt = (bt_error / _BT_TIME_CONSTANT) * drum_transfer * dt

        # ----------------------------------------------------------------
        # 6. Fan direct cooling of BT
        # ----------------------------------------------------------------
        # High fan pulls cooler air through the drum and strips heat from beans.
        fan_cooling = (
            fan_pct * 100.0 * _FAN_BT_COOLING_PER_PCT_PER_SEC * (self._bt - self._ambient) * dt
        )
        d_bt -= fan_cooling

        # ----------------------------------------------------------------
        # 7. First-crack thermal absorption
        # ----------------------------------------------------------------
        # Exothermic/endothermic chemistry during first crack temporarily
        # absorbs some of the energy, flattening the BT rise.
        if _FIRST_CRACK_LOW_F <= self._bt <= _FIRST_CRACK_HIGH_F and d_bt > 0:
            d_bt *= (1.0 - _FIRST_CRACK_ABSORPTION)

        self._bt += d_bt

        # ----------------------------------------------------------------
        # 8. Safety clamps (should not be reached in normal use)
        # ----------------------------------------------------------------
        self._bt = max(self._ambient - 5.0, min(self._bt, 599.0))
        self._et = max(self._ambient - 5.0, min(self._et, 599.0))

    # ------------------------------------------------------------------
    # Temperature readouts (with sensor noise)
    # ------------------------------------------------------------------

    @property
    def bean_temp(self) -> float:
        """Current bean temperature (BT) in Fahrenheit, with sensor noise."""
        noise = self._rng.gauss(0.0, _BT_NOISE_STD)
        return round(self._bt + noise, 1)

    @property
    def env_temp(self) -> float:
        """Current drum environment temperature (ET) in Fahrenheit, with sensor noise."""
        noise = self._rng.gauss(0.0, _ET_NOISE_STD)
        return round(self._et + noise, 1)

    # ------------------------------------------------------------------
    # Accessors for internal (noiseless) state - useful in tests
    # ------------------------------------------------------------------

    @property
    def bean_temp_true(self) -> float:
        """True (noise-free) bean temperature in Fahrenheit."""
        return self._bt

    @property
    def env_temp_true(self) -> float:
        """True (noise-free) environment temperature in Fahrenheit."""
        return self._et

    @property
    def heater(self) -> int:
        """Current heater power setting (0-100)."""
        return self._heater

    @property
    def drum(self) -> int:
        """Current drum speed setting (0-100)."""
        return self._drum

    @property
    def fan(self) -> int:
        """Current fan speed setting (0-100)."""
        return self._fan

    def __repr__(self) -> str:
        return (
            f"RoasterSimulator("
            f"BT={self._bt:.1f}°F, ET={self._et:.1f}°F, "
            f"heater={self._heater}%, drum={self._drum}%, fan={self._fan}%)"
        )
