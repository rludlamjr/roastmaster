"""Tests for roast phase analysis."""

from __future__ import annotations

import pytest

from roastmaster.display.units import c_to_f, f_to_c
from roastmaster.engine.analysis import Targets, analyze_roast, fmt_time
from roastmaster.profiles.schema import ProfileEvent
from tests.roast_fixtures import PREHEAT_S, make_roast


def _levels(a):
    return {f.short: f.level for f in a.findings}


class TestFmtTime:
    def test_formats(self):
        assert fmt_time(0) == "0:00"
        assert fmt_time(65.4) == "1:05"
        assert fmt_time(None) == "--"


class TestFinishedRoast:
    def test_phases_and_events(self):
        a = make_roast().analyze()
        assert a.charged and not a.live
        assert a.end_s == pytest.approx(510)
        assert [p.name for p in a.phases] == ["DRYING", "MAILLARD", "DEVELOPMENT"]
        assert sum(p.pct for p in a.phases) == pytest.approx(100.0)
        assert a.turning_point.time_s == pytest.approx(65, abs=2)
        assert a.dry_end_auto
        assert f_to_c(a.dry_end.bt_f) == pytest.approx(150, abs=1)
        assert a.first_crack.time_s == pytest.approx(410)

    def test_development_metrics(self):
        a = make_roast().analyze()
        assert a.dev_time_s == pytest.approx(100)
        assert a.dtr_pct == pytest.approx(100 / 510 * 100)
        assert a.dev_delta_f > 0
        assert a.status["dtr"] == "ok"

    def test_smooth_roast_has_no_crash_or_flick(self):
        a = make_roast().analyze()
        assert not a.crash
        assert a.flick_times_s == []

    def test_samples_after_drop_ignored(self):
        # Cooling tail must not affect RoR at drop
        a = make_roast().analyze()
        assert a.ror_end_f > 0

    def test_drying_avg_ror_excludes_charge_dip(self):
        a = make_roast().analyze()
        assert a.phase("DRYING").avg_ror_f > 0


class TestCrashAndFlick:
    def test_crash_detected(self):
        a = make_roast(crash=True).analyze()
        assert a.crash
        assert _levels(a)["ROR CRASH AFTER FC"] == "bad"

    def test_flick_detected_after_crash(self):
        a = make_roast(crash=True).analyze()
        assert a.flick_times_s
        assert a.flick_times_s[0] > a.first_crack.time_s
        assert any(f.short.startswith("ROR FLICK") for f in a.findings)

    def test_bad_findings_listed_first(self):
        a = make_roast(crash=True).analyze()
        order = {"bad": 0, "warn": 1, "info": 2, "good": 3}
        ranks = [order[f.level] for f in a.findings]
        assert ranks == sorted(ranks)


class TestTargets:
    def test_short_development_flagged(self):
        a = make_roast(drop_s=450).analyze()  # 40 s after FC
        assert a.status["dtr"] == "low"
        assert _levels(a)["DTR LOW: UNDERDEVELOPED"] == "bad"

    def test_all_good_reported(self):
        tg = Targets(drying_pct=(30.0, 60.0))
        p = make_roast()
        a = analyze_roast(p.samples, p.events, targets=tg)
        assert [f.level for f in a.findings] == ["good"]

    def test_weight_loss(self):
        p = make_roast()
        a = analyze_roast(p.samples, p.events, green_weight_g=170, roasted_weight_g=148)
        assert a.weight_loss_pct == pytest.approx(22 / 170 * 100)
        assert a.status["weight_loss"] == "ok"


class TestLiveRoast:
    def test_live_drop_now_projection(self):
        p = make_roast(drop_s=None, until_s=455)
        a = p.analyze()
        assert a.live
        assert a.current_phase == "DEVELOPMENT"
        assert a.dtr_pct == pytest.approx(45 / 455 * 100, abs=0.5)

    def test_live_does_not_flag_still_growing_numbers(self):
        a = make_roast(drop_s=None, until_s=440).analyze()
        assert a.status.get("dtr") != "low"
        assert a.status.get("total_time") != "low"
        assert "DTR LOW: UNDERDEVELOPED" not in _levels(a)
        assert "FAST ROAST" not in _levels(a)

    def test_live_in_drying(self):
        a = make_roast(drop_s=None, until_s=120, fc_s=410).analyze()
        # FC event is beyond "now" so only drying exists
        assert a.current_phase == "DRYING"
        assert a.first_crack is None


class TestEdgeCases:
    def test_no_charge(self):
        p = make_roast()
        events = [e for e in p.events if e.event_type != "CHARGE"]
        a = analyze_roast(p.samples, events)
        assert not a.charged
        assert a.phases == []

    def test_no_samples(self):
        a = analyze_roast([], [ProfileEvent("CHARGE", 0.0, 380.0)])
        assert not a.charged

    def test_manual_dry_end_wins(self):
        p = make_roast()
        p.events.append(ProfileEvent("DRY_END", PREHEAT_S + 200.0, c_to_f(140)))
        a = p.analyze()
        assert not a.dry_end_auto
        assert a.dry_end.time_s == pytest.approx(200)

    def test_no_first_crack(self):
        p = make_roast()
        p.events = [e for e in p.events if e.event_type != "FIRST_CRACK"]
        a = p.analyze()
        assert a.dtr_pct is None
        assert "NO FC MARKED" in _levels(a)

    def test_to_dict_is_celsius(self):
        d = make_roast().analyze().to_dict()
        assert d["first_crack"]["bt_c"] == pytest.approx(183, abs=2)
        assert d["phases"][2]["name"] == "DEVELOPMENT"
        assert isinstance(d["findings"], list)


class TestBogusTurningPoint:
    """Regression: a TP event at charge time made dry end show as 0:01."""

    def test_tp_event_at_charge_is_ignored(self):
        p = make_roast()
        charge = p.events[0]
        p.events.append(ProfileEvent("TURNING_POINT", charge.elapsed, charge.temperature))
        a = p.analyze()
        assert a.turning_point.time_s == pytest.approx(65, abs=2)
        assert a.dry_end.time_s > 200
        assert f_to_c(a.dry_end.bt_f) == pytest.approx(150, abs=1)

    def test_dry_end_needs_an_upward_crossing(self):
        # Charge BT is above the dry-end threshold; that must not count as dry end
        a = make_roast(charge_bt_c=200).analyze()
        assert a.dry_end.time_s > a.turning_point.time_s + 60
