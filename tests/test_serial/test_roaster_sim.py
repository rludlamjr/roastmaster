"""Tests for the RoasterSimulator physics model.

Covers:
- Initial conditions (starts at ambient)
- Heater-on: BT and ET rise over time
- Heater-off: temperatures decay back toward ambient
- Fan speed: cooling effect on BT
- Physical safety bounds (no negatives, no runaway above 600°F)
- Realistic temperature progression over a simulated roast
- Full roast cycle: preheat -> charge -> roast to first crack -> cool down
"""

import math

import pytest

from roastmaster.sim.roaster_sim import RoasterSimulator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _advance(sim: RoasterSimulator, total_seconds: float, dt: float = 1.0) -> None:
    """Drive the simulator forward by *total_seconds* using *dt*-second steps."""
    steps = math.ceil(total_seconds / dt)
    for _ in range(steps):
        sim.update(dt)


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

class TestInitialState:
    def test_starts_at_ambient_default(self):
        sim = RoasterSimulator()
        # Default ambient is 70°F; noise is tiny, so both temps should be close.
        assert abs(sim.bean_temp_true - 70.0) < 0.01
        assert abs(sim.env_temp_true - 70.0) < 0.01

    def test_starts_at_custom_ambient(self):
        sim = RoasterSimulator(ambient_temp_f=50.0)
        assert abs(sim.bean_temp_true - 50.0) < 0.01
        assert abs(sim.env_temp_true - 50.0) < 0.01

    def test_initial_heater_drum_fan_zero(self):
        sim = RoasterSimulator()
        assert sim.heater == 0
        assert sim.drum == 0
        assert sim.fan == 0

    def test_noisy_readout_close_to_true(self):
        """The public bean_temp and env_temp properties include noise but should
        stay within a reasonable range of the true value."""
        sim = RoasterSimulator()
        for _ in range(100):
            assert abs(sim.bean_temp - sim.bean_temp_true) < 5.0
            assert abs(sim.env_temp - sim.env_temp_true) < 5.0


# ---------------------------------------------------------------------------
# Heater behaviour
# ---------------------------------------------------------------------------

class TestHeaterOn:
    def test_heater_100_raises_et(self):
        """At full power ET must rise significantly within 5 minutes."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        _advance(sim, 300)  # 5 minutes
        assert sim.env_temp_true > 200.0, (
            f"ET should exceed 200°F after 5 min at 100% heater, got {sim.env_temp_true:.1f}°F"
        )

    def test_heater_100_raises_bt(self):
        """BT must rise substantially within 5 minutes at full power."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        _advance(sim, 300)
        assert sim.bean_temp_true > 150.0, (
            f"BT should exceed 150°F after 5 min at 100% heater, got {sim.bean_temp_true:.1f}°F"
        )

    def test_et_rises_faster_than_bt(self):
        """ET should always be hotter than BT when the heater is running."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(80)
        _advance(sim, 60)  # give it 1 minute to diverge
        assert sim.env_temp_true > sim.bean_temp_true, (
            "ET should exceed BT when heater is on"
        )

    def test_bt_increases_monotonically_with_heater(self):
        """With heater on and no fan, BT should increase every update step."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        sim.set_drum(60)
        sim.set_fan(0)
        prev_bt = sim.bean_temp_true
        # Skip the very first few steps (negligible movement); check over 30 steps.
        for i in range(120):
            sim.update(1.0)
            current_bt = sim.bean_temp_true
            assert current_bt >= prev_bt - 0.001, (
                f"BT decreased at step {i}: {prev_bt:.2f} -> {current_bt:.2f}"
            )
            prev_bt = current_bt

    def test_higher_heater_produces_higher_temps(self):
        """50% heater should produce lower temperatures than 100% heater
        after the same elapsed time."""
        sim_low = RoasterSimulator(ambient_temp_f=70.0)
        sim_high = RoasterSimulator(ambient_temp_f=70.0)
        sim_low.set_heater(50)
        sim_high.set_heater(100)
        _advance(sim_low, 300)
        _advance(sim_high, 300)
        assert sim_high.bean_temp_true > sim_low.bean_temp_true
        assert sim_high.env_temp_true > sim_low.env_temp_true

    def test_full_power_reaches_first_crack_range_in_reasonable_time(self):
        """At 100% heater, BT must reach the first-crack zone (385°F) within
        15 minutes - consistent with a real roast."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        sim.set_drum(60)
        sim.set_fan(20)
        _advance(sim, 900)  # 15 minutes
        assert sim.bean_temp_true >= 385.0, (
            f"BT should reach 385°F within 15 min at 100% heater, "
            f"got {sim.bean_temp_true:.1f}°F"
        )


# ---------------------------------------------------------------------------
# Heater off / cooling
# ---------------------------------------------------------------------------

class TestHeaterOff:
    def test_heater_off_from_ambient_stays_at_ambient(self):
        """Starting cold with no heater should not change temperature."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        _advance(sim, 60)
        assert abs(sim.bean_temp_true - 70.0) < 1.0
        assert abs(sim.env_temp_true - 70.0) < 1.0

    def test_heater_off_causes_cooling(self):
        """After reaching elevated temperature, turning heater off should
        cause temperatures to decline."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        _advance(sim, 300)  # heat up for 5 minutes
        peak_bt = sim.bean_temp_true
        peak_et = sim.env_temp_true
        assert peak_bt > 100.0  # confirm it heated up

        sim.set_heater(0)
        _advance(sim, 300)  # cool for 5 minutes
        assert sim.bean_temp_true < peak_bt, "BT should decrease after heater off"
        assert sim.env_temp_true < peak_et, "ET should decrease after heater off"

    def test_temperature_decays_toward_ambient(self):
        """With heater off for long enough, temperatures should approach ambient."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        _advance(sim, 300)
        sim.set_heater(0)
        sim.set_fan(0)
        _advance(sim, 1200)  # 20 minutes of cooling
        # Should be significantly closer to ambient than the peak.
        assert sim.bean_temp_true < 200.0, (
            f"BT should decay substantially after 20 min cooling, "
            f"got {sim.bean_temp_true:.1f}°F"
        )
        assert sim.env_temp_true < 200.0


# ---------------------------------------------------------------------------
# Fan effects
# ---------------------------------------------------------------------------

class TestFanSpeed:
    def test_high_fan_cools_bt_relative_to_low_fan(self):
        """Higher fan speed should result in lower BT after the same elapsed
        time, when starting from an elevated temperature."""
        sim_no_fan = RoasterSimulator(ambient_temp_f=70.0)
        sim_high_fan = RoasterSimulator(ambient_temp_f=70.0)

        # Heat both up identically first.
        for sim in (sim_no_fan, sim_high_fan):
            sim.set_heater(80)
            sim.set_drum(60)
            sim.set_fan(0)
            _advance(sim, 300)

        peak_no_fan = sim_no_fan.bean_temp_true
        peak_high_fan = sim_high_fan.bean_temp_true
        # Both should have risen the same amount (same settings, same steps).
        assert abs(peak_no_fan - peak_high_fan) < 1.0, "Peaks should match before fan diverges"

        # Now apply high fan to one and keep the other as is.
        sim_high_fan.set_fan(80)
        _advance(sim_no_fan, 120)
        _advance(sim_high_fan, 120)

        assert sim_high_fan.bean_temp_true < sim_no_fan.bean_temp_true, (
            "High fan should produce lower BT than no fan"
        )

    def test_fan_increases_et_bt_differential(self):
        """With high fan, the ET-BT gap should be larger than with low fan."""
        sim_low = RoasterSimulator(ambient_temp_f=70.0)
        sim_high = RoasterSimulator(ambient_temp_f=70.0)

        for sim in (sim_low, sim_high):
            sim.set_heater(80)
            sim.set_drum(60)
        sim_low.set_fan(10)
        sim_high.set_fan(80)

        _advance(sim_low, 300)
        _advance(sim_high, 300)

        diff_low = sim_low.env_temp_true - sim_low.bean_temp_true
        diff_high = sim_high.env_temp_true - sim_high.bean_temp_true

        assert diff_high > diff_low, (
            f"High fan ET-BT diff ({diff_high:.1f}) should exceed "
            f"low fan ET-BT diff ({diff_low:.1f})"
        )


# ---------------------------------------------------------------------------
# Physical bounds
# ---------------------------------------------------------------------------

class TestPhysicalBounds:
    def test_temps_never_negative(self):
        """Temperatures must always be physically plausible (above -50°F)."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(0)
        sim.set_fan(100)
        _advance(sim, 600)
        assert sim.bean_temp_true > -50.0
        assert sim.env_temp_true > -50.0

    def test_temps_never_exceed_600f(self):
        """Even at maximum heater, temperatures must stay below 600°F."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        sim.set_fan(0)
        sim.set_drum(0)
        _advance(sim, 3600)  # 1 hour at full blast
        assert sim.bean_temp_true < 600.0, (
            f"BT exceeded 600°F: {sim.bean_temp_true:.1f}°F"
        )
        assert sim.env_temp_true < 600.0, (
            f"ET exceeded 600°F: {sim.env_temp_true:.1f}°F"
        )

    def test_et_above_bt_during_heating(self):
        """ET should always be warmer than BT once heating has started."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(80)
        sim.set_fan(20)
        # After a brief warm-up, ET > BT should hold.
        _advance(sim, 30)  # 30 s is enough to see the divergence
        for _ in range(300):
            sim.update(1.0)
            assert sim.env_temp_true >= sim.bean_temp_true - 0.1, (
                f"ET ({sim.env_temp_true:.1f}) should not fall below "
                f"BT ({sim.bean_temp_true:.1f}) during heating"
            )

    def test_noisy_readout_within_physical_bounds(self):
        """Noisy public readouts must also stay within physical bounds."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        for _ in range(600):
            sim.update(1.0)
            assert -50.0 < sim.bean_temp < 600.0
            assert -50.0 < sim.env_temp < 600.0

    def test_invalid_heater_raises(self):
        sim = RoasterSimulator()
        with pytest.raises(ValueError):
            sim.set_heater(101)
        with pytest.raises(ValueError):
            sim.set_heater(-1)

    def test_invalid_drum_raises(self):
        sim = RoasterSimulator()
        with pytest.raises(ValueError):
            sim.set_drum(101)
        with pytest.raises(ValueError):
            sim.set_drum(-1)

    def test_invalid_fan_raises(self):
        sim = RoasterSimulator()
        with pytest.raises(ValueError):
            sim.set_fan(101)
        with pytest.raises(ValueError):
            sim.set_fan(-1)


# ---------------------------------------------------------------------------
# Multi-step curve shape
# ---------------------------------------------------------------------------

class TestCurveShape:
    def test_bt_curve_is_concave_during_heating(self):
        """The rate of rise should slow as BT approaches its asymptote.
        After an initial ramp, the increment per step should decrease."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        sim.set_fan(0)
        sim.set_drum(60)

        # Collect BT deltas over time.
        deltas = []
        prev = sim.bean_temp_true
        for _ in range(300):
            sim.update(1.0)
            deltas.append(sim.bean_temp_true - prev)
            prev = sim.bean_temp_true

        # The average delta in the first 60 steps should exceed the average
        # in steps 240-300 (curve should be flattening out).
        early_avg = sum(deltas[10:60]) / 50
        late_avg = sum(deltas[240:300]) / 60
        assert early_avg > late_avg, (
            f"RoR should decrease as BT approaches asymptote "
            f"(early avg {early_avg:.3f} vs late avg {late_avg:.3f})"
        )

    def test_zero_dt_no_change(self):
        """A zero time-step should not change any temperatures."""
        sim = RoasterSimulator()
        sim.set_heater(100)
        bt_before = sim.bean_temp_true
        et_before = sim.env_temp_true
        sim.update(0.0)
        sim.update(-1.0)  # negative dt also ignored
        assert sim.bean_temp_true == bt_before
        assert sim.env_temp_true == et_before


# ---------------------------------------------------------------------------
# First-crack behaviour
# ---------------------------------------------------------------------------

class TestFirstCrack:
    def test_ror_dips_in_first_crack_zone(self):
        """The BT rate of rise should be slightly reduced inside the
        first-crack zone (385-400°F) compared to just below it.

        Uses 95% heater so the BT asymptote is well above 400°F and the
        curve passes cleanly through the first-crack zone within ~2 minutes.
        """
        sim = RoasterSimulator(ambient_temp_f=70.0)
        # 95% heater with these fan/drum settings has an asymptote above 400°F,
        # so BT will actually traverse the first-crack zone in ~2 minutes.
        sim.set_heater(95)
        sim.set_drum(60)
        sim.set_fan(10)

        # Advance until BT reaches ~375°F (just below first crack zone).
        # At 95% heater this takes ~100 seconds from cold start.
        for _ in range(300):
            sim.update(1.0)
            if sim.bean_temp_true >= 375.0:
                break

        assert sim.bean_temp_true >= 375.0, (
            f"BT did not reach 375°F in 300 steps, got {sim.bean_temp_true:.1f}°F"
        )

        # Measure delta over next 10 steps just below first crack zone.
        bt_start_below = sim.bean_temp_true
        for _ in range(10):
            sim.update(1.0)
        delta_below_fc = sim.bean_temp_true - bt_start_below

        # Continue into first crack zone.
        for _ in range(200):
            sim.update(1.0)
            if sim.bean_temp_true >= 387.0:
                break

        assert sim.bean_temp_true >= 387.0, (
            f"BT did not reach 387°F (first crack zone), got {sim.bean_temp_true:.1f}°F"
        )

        bt_start_fc = sim.bean_temp_true
        for _ in range(10):
            sim.update(1.0)
        delta_in_fc = sim.bean_temp_true - bt_start_fc

        # The delta inside first crack should be less than outside.
        assert delta_in_fc < delta_below_fc, (
            f"RoR in first-crack zone ({delta_in_fc:.2f}) should be less than "
            f"below it ({delta_below_fc:.2f})"
        )


# ---------------------------------------------------------------------------
# Full simulated roast
# ---------------------------------------------------------------------------

class TestFullRoast:
    """Simulate a complete roast cycle and verify realistic outcomes at each phase."""

    def test_full_roast_cycle(self):
        """Run a full cold-start -> preheat -> roast to first crack -> cool-down
        cycle and assert that temperatures at each milestone are physically realistic.

        This test uses a single simulator instance continuously (no bean charge
        event reset, since the simulator models the thermal mass of the drum
        environment as a whole).  A typical development workflow would start the
        simulator cold and drive it through the full temperature arc.
        """
        sim = RoasterSimulator(ambient_temp_f=70.0)

        # ------------------------------------------------------------------
        # Phase 1: Preheat - heat the drum to roasting temperature.
        # Use 100% heater for 8 minutes; ET and BT should both rise well
        # above ambient.
        # ------------------------------------------------------------------
        sim.set_heater(100)
        sim.set_drum(60)
        sim.set_fan(20)
        _advance(sim, 480)  # 8 minutes

        et_preheat = sim.env_temp_true
        bt_preheat = sim.bean_temp_true
        assert et_preheat > 300.0, (
            f"ET after preheat should exceed 300°F, got {et_preheat:.1f}°F"
        )
        assert bt_preheat > 200.0, (
            f"BT after preheat should exceed 200°F, got {bt_preheat:.1f}°F"
        )
        assert et_preheat > bt_preheat, "ET must be hotter than BT during preheat"

        # ------------------------------------------------------------------
        # Phase 2: Charge - mark the moment beans are loaded.
        # Reduce heater to a typical mid-roast level and slightly lower fan
        # (common practice to preserve heat after charge).
        # ------------------------------------------------------------------
        sim.set_heater(80)
        sim.set_fan(15)

        # ------------------------------------------------------------------
        # Phase 3: Roast - BT continues to rise toward first crack (~390°F).
        # At 80% heater the asymptote for BT with 15% fan is above 390°F,
        # so BT may stabilise or continue rising depending on starting point.
        # We advance for 3 minutes and assert BT stayed in a sensible range.
        # ------------------------------------------------------------------
        _advance(sim, 180)  # 3 more minutes

        bt_mid_roast = sim.bean_temp_true
        et_mid_roast = sim.env_temp_true
        assert et_mid_roast > bt_mid_roast, "ET must exceed BT during roasting"
        assert bt_mid_roast > 200.0, (
            f"BT mid-roast should exceed 200°F, got {bt_mid_roast:.1f}°F"
        )
        assert bt_mid_roast < 600.0, (
            f"BT mid-roast must be below 600°F, got {bt_mid_roast:.1f}°F"
        )

        # ------------------------------------------------------------------
        # Phase 4: Drive to first crack using higher heater.
        # 100% heater guarantees BT reaches first crack within the timeout.
        # ------------------------------------------------------------------
        sim.set_heater(100)
        sim.set_fan(20)
        for _ in range(600):  # up to 10 minutes
            sim.update(1.0)
            if sim.bean_temp_true >= 390.0:
                break

        bt_at_fc = sim.bean_temp_true
        et_at_fc = sim.env_temp_true
        assert bt_at_fc >= 385.0, (
            f"BT should reach first crack zone (>=385°F), got {bt_at_fc:.1f}°F"
        )
        assert et_at_fc > bt_at_fc, "ET must exceed BT at first crack"
        assert et_at_fc < 600.0, f"ET must stay below 600°F, got {et_at_fc:.1f}°F"

        # ------------------------------------------------------------------
        # Phase 5: Cool down - heater off, fan full.
        # ------------------------------------------------------------------
        sim.set_heater(0)
        sim.set_fan(100)
        bt_at_drop = sim.bean_temp_true
        _advance(sim, 300)  # 5 minutes cooling

        bt_cooled = sim.bean_temp_true
        assert bt_cooled < bt_at_drop, (
            f"BT should decrease during cool-down, "
            f"was {bt_at_drop:.1f}°F, now {bt_cooled:.1f}°F"
        )
        assert bt_cooled < 350.0, (
            f"After 5 minutes of cooling BT should be below 350°F, "
            f"got {bt_cooled:.1f}°F"
        )

        # ------------------------------------------------------------------
        # Sanity: all temps still within physical range at end of roast.
        # ------------------------------------------------------------------
        assert 0.0 < sim.bean_temp_true < 600.0
        assert 0.0 < sim.env_temp_true < 600.0

    def test_roast_produces_realistic_bt_range(self):
        """A typical roast (100% heater, moderate fan/drum) should reach
        first-crack territory (385-440°F) within 15 minutes."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(100)
        sim.set_drum(60)
        sim.set_fan(20)
        _advance(sim, 900)  # 15 minutes
        assert 385.0 <= sim.bean_temp_true <= 480.0, (
            f"BT after 15 min should be in 385-480°F range, "
            f"got {sim.bean_temp_true:.1f}°F"
        )

    def test_et_always_hotter_than_bt_throughout_roast(self):
        """ET must remain above BT for the entire duration of a roast."""
        sim = RoasterSimulator(ambient_temp_f=70.0)
        sim.set_heater(90)
        sim.set_drum(60)
        sim.set_fan(20)
        # Warmup - allow a few seconds for ET to get ahead of BT.
        _advance(sim, 10)
        for step in range(900):  # 15 minutes
            sim.update(1.0)
            assert sim.env_temp_true >= sim.bean_temp_true - 0.1, (
                f"ET ({sim.env_temp_true:.1f}°F) must not fall below "
                f"BT ({sim.bean_temp_true:.1f}°F) at step {step}"
            )
