"""Tests for live burner/air guidance."""

from __future__ import annotations

import pytest

from roastmaster.engine.guidance import (
    GuidanceTracker,
    _interp,
    coach_text,
    compute_guidance,
    parse_controls,
    plan_ror_by_bt,
)
from roastmaster.profiles.coffees import CoffeeLibrary, RoastPlan, target_curve

CONTROLS = [
    {"at": "charge", "burner": 70, "air": 30, "drum": 90},
    {"bt_c": 150, "burner": 60, "air": 40},
    {"bt_c": 165, "burner": 52, "air": 50},
    {"bt_c": 178, "burner": 45},
    {"at": "fc", "burner": 40, "air": 55},
    {"at": "fc", "after_s": 30, "burner": 35},
]
STEPS = parse_controls(CONTROLS)
PLAN = RoastPlan(tp_s=36, tp_bt_c=110, peak_s=44, dry_end_s=215, fc_s=435, fc_bt_c=188,
                 drop_s=535, drop_bt_c=198.5)
PLAN_ROR = plan_ror_by_bt(target_curve(PLAN, 150), PLAN.tp_s)


def guide(**kw):
    args = dict(charged=True, dropped=False, t=300.0, bt_c=160.0, ror_c=None, tp_passed=True,
                fc_t=None, fc_bt_plan_c=188.0, plan_ror=PLAN_ROR)
    args.update(kw)
    return compute_guidance(STEPS, **args)


class TestSchedule:
    def test_before_charge_shows_charge_settings(self):
        g = guide(charged=False)
        assert (g.burner, g.air, g.drum) == (70, 30, 90)

    def test_after_drop_no_guidance(self):
        assert guide(dropped=True) is None

    def test_no_bt_steps_before_turning_point(self):
        # During the charge dip BT is above 150 C; that must not count as dry end
        g = guide(t=10, bt_c=160, tp_passed=False)
        assert g.burner == 70

    def test_bt_step_and_carry_forward(self):
        g = guide(bt_c=158, ror_c=None)  # no RoR: schedule only, no correction
        assert (g.burner, g.air, g.drum) == (60, 40, 90)

    def test_lead_brings_step_forward(self):
        # 160 C rising 10 C/min projects to 167.5 C in 45 s: the 165 C step is due now
        assert guide(bt_c=160, ror_c=10).scheduled_burner == 52
        assert guide(bt_c=160, ror_c=2).scheduled_burner == 60

    def test_behind_plan_step_comes_later_in_time(self):
        # Same clock time, cooler beans: the step isn't due yet
        assert guide(t=330, bt_c=150, ror_c=8).scheduled_burner == 60

    def test_next_change_and_eta(self):
        g = guide(bt_c=155, ror_c=10)  # projects to 162.5; 165 C step 15 s away
        assert g.next_change == {"burner": 52, "air": 50}
        assert g.next_in_s == pytest.approx(15, abs=0.5)

    def test_fc_step_anticipated_from_planned_fc_temperature(self):
        assert guide(bt_c=181, ror_c=10).scheduled_burner == 40  # projects to 188.5

    def test_after_fc_steps_wait_for_fcs_press(self):
        g = guide(t=480, bt_c=195, ror_c=8)  # well past planned FC, FC not marked
        assert g.scheduled_burner == 40
        assert guide(t=480, bt_c=195, ror_c=8, fc_t=440).scheduled_burner == 35
        assert guide(t=460, bt_c=193, ror_c=8, fc_t=440).scheduled_burner == 40


class TestRoRCorrection:
    def test_running_hot_lowers_burner(self):
        g = guide(bt_c=172, ror_c=13)  # plan RoR at 172 C is ~10
        assert g.correction < -5
        assert g.burner < g.scheduled_burner

    def test_running_cold_early_adds_heat(self):
        g = guide(bt_c=155, ror_c=8)
        assert g.correction > 0

    def test_never_adds_heat_near_first_crack(self):
        g = guide(bt_c=175, ror_c=5)  # within 25 C of planned FC
        assert g.correction == 0
        assert g.burner == g.scheduled_burner

    def test_no_correction_before_dry_end(self):
        assert guide(t=120, bt_c=130, ror_c=30).correction == 0

    def test_after_fc_cut_is_capped(self):
        g = guide(t=470, bt_c=193, ror_c=20, fc_t=440)
        assert g.correction == pytest.approx(-10)
        assert g.burner == 25

    def test_tracker_smooths_noisy_ror(self):
        tracker = GuidanceTracker(STEPS, PLAN_ROR, 188.0)
        targets = []
        for i, ror in enumerate([13, 8, 13, 8, 13, 8, 13, 8]):
            g = tracker.update(charged=True, dropped=False, t=360 + 2 * i, bt_c=172 + 0.3 * i,
                               ror_c=ror, tp_passed=True, fc_t=None)
            targets.append(g.burner)
        assert max(targets) - min(targets) <= 3


class TestCoach:
    def test_now_when_burner_off_target(self):
        g = guide(bt_c=158, ror_c=None)
        assert coach_text(g, burner=70, air=40) == "BURN TO 60% NOW"

    def test_countdown_when_step_is_close(self):
        ror = _interp(PLAN_ROR, 155)  # on plan: no correction
        bt = 160 - ror * 45 / 60      # projects to 160 C, 5 C short of the 165 C step
        g = guide(bt_c=bt, ror_c=ror)
        eta = round(5 / (ror / 60))
        assert g.burner == 60
        assert coach_text(g, burner=60, air=40) == f"BURN 52% IN 0:{eta:02d}"

    def test_quiet_when_on_target(self):
        g = guide(bt_c=152, ror_c=3)
        assert coach_text(g, burner=g.burner, air=40) == ""


def test_shipped_plans_have_valid_controls():
    for coffee in CoffeeLibrary("coffees").all():
        steps = parse_controls(coffee.controls)
        assert steps and steps[0].trigger == "charge", coffee.id
        bts = [s.bt_c for s in steps if s.trigger == "bt"]
        assert bts == sorted(bts) and bts[0] == 150, coffee.id
        burners = [s.burner for s in steps if s.burner is not None]
        assert burners == sorted(burners, reverse=True), f"{coffee.id}: burner only steps down"


def test_session_guidance_follows_selected_plan():
    from roastmaster.app import RoastSession

    session = RoastSession()
    coffee = CoffeeLibrary("coffees").get("honduras-18-rabbit-yellow-honey")
    session.select_coffee(coffee)
    assert session.guidance is not None
    assert (session.guidance.burner, session.guidance.air, session.guidance.drum) == (70, 30, 90)
    session.select_coffee(None)
    assert session.guidance is None
