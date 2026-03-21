"""Tests for the RoastStateMachine."""

import pytest

from roastmaster.engine.roast import RoastPhase, RoastStateMachine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_full_roast() -> RoastStateMachine:
    """Walk a state machine through the complete valid sequence."""
    sm = RoastStateMachine()
    sm.start_preheat(10.0)
    sm.charge(60.0)
    sm.begin_roasting(120.0)
    sm.start_cooling(600.0)
    sm.finish(720.0)
    return sm


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


def test_initial_phase_is_idle():
    sm = RoastStateMachine()
    assert sm.phase == RoastPhase.IDLE


def test_initial_times_are_zero():
    sm = RoastStateMachine()
    assert sm.elapsed == 0.0
    assert sm.phase_start_time == 0.0
    assert sm.roast_start_time == 0.0


# ---------------------------------------------------------------------------
# Valid transitions
# ---------------------------------------------------------------------------


def test_idle_to_preheat():
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    assert sm.phase == RoastPhase.PREHEAT


def test_preheat_to_charge():
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    sm.charge(30.0)
    assert sm.phase == RoastPhase.CHARGE


def test_charge_to_roasting():
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    sm.charge(30.0)
    sm.begin_roasting(90.0)
    assert sm.phase == RoastPhase.ROASTING


def test_roasting_to_cooling():
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    sm.charge(30.0)
    sm.begin_roasting(90.0)
    sm.start_cooling(500.0)
    assert sm.phase == RoastPhase.COOLING


def test_cooling_to_done():
    sm = make_full_roast()
    assert sm.phase == RoastPhase.DONE


# ---------------------------------------------------------------------------
# Non-standard transitions log a warning but still proceed
# ---------------------------------------------------------------------------


def test_idle_to_charge_warns(caplog):
    sm = RoastStateMachine()
    sm.charge(10.0)
    assert sm.phase == RoastPhase.CHARGE
    assert "Non-standard transition" in caplog.text


def test_idle_to_cooling_warns(caplog):
    sm = RoastStateMachine()
    sm.start_cooling(10.0)
    assert sm.phase == RoastPhase.COOLING
    assert "Non-standard transition" in caplog.text


def test_idle_to_done_warns(caplog):
    sm = RoastStateMachine()
    sm.finish(10.0)
    assert sm.phase == RoastPhase.DONE
    assert "Non-standard transition" in caplog.text


def test_idle_to_roasting_warns(caplog):
    sm = RoastStateMachine()
    sm.begin_roasting(10.0)
    assert sm.phase == RoastPhase.ROASTING
    assert "Non-standard transition" in caplog.text


def test_preheat_to_roasting_warns(caplog):
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    sm.begin_roasting(10.0)
    assert sm.phase == RoastPhase.ROASTING
    assert "Non-standard transition" in caplog.text


def test_charge_to_cooling_warns(caplog):
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    sm.charge(30.0)
    sm.start_cooling(50.0)
    assert sm.phase == RoastPhase.COOLING
    assert "Non-standard transition" in caplog.text


def test_roasting_to_done_warns(caplog):
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    sm.charge(30.0)
    sm.begin_roasting(90.0)
    sm.finish(500.0)
    assert sm.phase == RoastPhase.DONE
    assert "Non-standard transition" in caplog.text


def test_done_to_preheat_warns(caplog):
    sm = make_full_roast()
    sm.start_preheat(800.0)
    assert sm.phase == RoastPhase.PREHEAT
    assert "Non-standard transition" in caplog.text


def test_preheat_twice_warns(caplog):
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    sm.start_preheat(10.0)
    assert sm.phase == RoastPhase.PREHEAT
    assert "Non-standard transition" in caplog.text


# ---------------------------------------------------------------------------
# roast_elapsed tracks time since CHARGE
# ---------------------------------------------------------------------------


def test_roast_elapsed_zero_before_charge():
    sm = RoastStateMachine()
    sm.start_preheat(10.0)
    # elapsed and roast_start_time are both 0 until charge
    assert sm.roast_elapsed == sm.elapsed - sm.roast_start_time


def test_roast_elapsed_after_charge():
    sm = RoastStateMachine()
    sm.start_preheat(10.0)
    sm.charge(60.0)
    # roast_elapsed should be 0 immediately after charge
    assert sm.roast_elapsed == 0.0


def test_roast_elapsed_advances_with_elapsed():
    sm = RoastStateMachine()
    sm.start_preheat(10.0)
    sm.charge(60.0)
    sm.begin_roasting(120.0)
    assert sm.roast_elapsed == pytest.approx(60.0)


def test_roast_elapsed_at_cooling():
    sm = RoastStateMachine()
    sm.start_preheat(10.0)
    sm.charge(60.0)
    sm.begin_roasting(120.0)
    sm.start_cooling(600.0)
    assert sm.roast_elapsed == pytest.approx(540.0)


def test_roast_elapsed_at_done():
    sm = make_full_roast()
    # charge at 60, finish at 720 => 660s of roast time
    assert sm.roast_elapsed == pytest.approx(660.0)


# ---------------------------------------------------------------------------
# phase_elapsed tracks time in current phase
# ---------------------------------------------------------------------------


def test_phase_elapsed_zero_at_transition():
    sm = RoastStateMachine()
    sm.start_preheat(10.0)
    assert sm.phase_elapsed == pytest.approx(0.0)


def test_phase_elapsed_after_transition():
    sm = RoastStateMachine()
    sm.start_preheat(10.0)
    sm.charge(60.0)
    # phase_start_time updated to 60; elapsed is 60 => 0
    assert sm.phase_elapsed == pytest.approx(0.0)
    sm.begin_roasting(120.0)
    # phase_start_time = 120; elapsed = 120 => 0 again
    assert sm.phase_elapsed == pytest.approx(0.0)


def test_phase_elapsed_across_roasting():
    sm = RoastStateMachine()
    sm.start_preheat(10.0)
    sm.charge(60.0)
    sm.begin_roasting(120.0)
    sm.start_cooling(600.0)
    # cooling phase started at 600 and elapsed is 600, then finish at 720
    sm.finish(720.0)
    # done phase started at 720; elapsed = 720 => phase_elapsed = 0
    assert sm.phase_elapsed == pytest.approx(0.0)


def test_phase_elapsed_roasting_duration():
    sm = RoastStateMachine()
    sm.start_preheat(0.0)
    sm.charge(30.0)
    sm.begin_roasting(90.0)
    sm.start_cooling(480.0)
    # COOLING phase: phase_start_time = 480, elapsed = 480 => 0
    assert sm.phase_elapsed == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


def test_reset_returns_to_idle():
    sm = make_full_roast()
    sm.reset()
    assert sm.phase == RoastPhase.IDLE


def test_reset_clears_times():
    sm = make_full_roast()
    sm.reset()
    assert sm.elapsed == 0.0
    assert sm.phase_start_time == 0.0
    assert sm.roast_start_time == 0.0


def test_can_start_preheat_after_reset():
    sm = make_full_roast()
    sm.reset()
    sm.start_preheat(5.0)
    assert sm.phase == RoastPhase.PREHEAT


def test_elapsed_updated_on_each_transition():
    sm = RoastStateMachine()
    sm.start_preheat(5.0)
    assert sm.elapsed == pytest.approx(5.0)
    sm.charge(30.0)
    assert sm.elapsed == pytest.approx(30.0)
    sm.begin_roasting(90.0)
    assert sm.elapsed == pytest.approx(90.0)
