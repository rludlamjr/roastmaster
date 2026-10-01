"""Tests for the coffee library and plan-derived target curves."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

from roastmaster.app import RoastSession
from roastmaster.display.units import f_to_c
from roastmaster.profiles.coffees import (
    Coffee,
    CoffeeLibrary,
    RoastPlan,
    ror_knots,
    target_curve,
)
from roastmaster.web.live import LiveState
from roastmaster.web.server import RoastWebServer
from tests.roast_fixtures import make_roast

REPO_COFFEES = Path(__file__).resolve().parents[2] / "coffees"


class TestCurve:
    def test_curve_hits_milestones(self):
        plan = RoastPlan()
        curve = target_curve(plan, 150.0)
        by_t = {int(t): bt for t, bt, _ in curve}
        assert by_t[0] == pytest.approx(plan.charge_bt_c)
        assert by_t[int(plan.tp_s)] == pytest.approx(plan.tp_bt_c)
        assert by_t[int(plan.dry_end_s)] == pytest.approx(150.0, abs=0.05)
        assert by_t[int(plan.fc_s)] == pytest.approx(plan.fc_bt_c, abs=0.05)
        assert by_t[int(plan.drop_s)] == pytest.approx(plan.drop_bt_c, abs=0.05)

    def test_ror_declines_smoothly_after_peak(self):
        knots = ror_knots(RoastPlan(), 150.0)
        values = [r for _, r in knots[1:]]
        assert values == sorted(values, reverse=True)
        assert knots[-1][1] == pytest.approx(0.5 * knots[-2][1])

    def test_bad_plan_rejected(self):
        with pytest.raises(ValueError):
            ror_knots(RoastPlan(fc_s=200.0, dry_end_s=240.0), 150.0)


class TestShippedCoffees:
    """The plans in coffees/ must be valid and sensible."""

    @pytest.mark.parametrize("path", sorted(REPO_COFFEES.glob("*.json")), ids=lambda p: p.stem)
    def test_plan_is_sane(self, path):
        coffee = Coffee.from_dict(json.loads(path.read_text()))
        assert coffee.id == path.stem
        knots = ror_knots(coffee.plan, coffee.analysis_targets().dry_end_c)
        values = [r for _, r in knots[1:]]
        assert values == sorted(values, reverse=True), "RoR must fall steadily after the peak"
        assert 15 <= values[0] <= 30  # peak RoR, C/min
        assert 5 <= knots[3][1] <= 12  # RoR at FC
        pt = coffee.plan_targets()
        lo, hi = coffee.analysis_targets().dtr_pct
        assert lo <= pt.dtr_pct <= hi
        assert coffee.steps and coffee.rationale


class TestLibrary:
    def test_add_draft_and_get(self, tmp_path):
        lib = CoffeeLibrary(tmp_path)
        a = lib.add_draft("Kenya Nyeri AA", process="Washed")
        b = lib.add_draft("Kenya Nyeri AA")
        assert a.id == "kenya-nyeri-aa" and b.id == "kenya-nyeri-aa-2"
        assert lib.get(a.id).status == "draft"
        assert lib.get("../etc") is None
        assert [c.id for c in lib.all()] == [a.id, b.id]

    def test_invalid_file_skipped(self, tmp_path):
        (tmp_path / "bad.json").write_text("{}")
        assert CoffeeLibrary(tmp_path).all() == []

    def test_target_overrides(self):
        c = Coffee(id="x", name="X", targets={"dtr_pct": [15, 18], "nonsense": 1})
        assert c.analysis_targets().dtr_pct == (15.0, 18.0)


class TestRoastAgainstPlan:
    def _coffee(self) -> Coffee:
        return Coffee(id="t", name="Test", plan=RoastPlan(
            charge_bt_c=190, tp_s=65, tp_bt_c=95, peak_s=110, dry_end_s=257, fc_s=410,
            fc_bt_c=183, drop_s=510, drop_bt_c=195))

    def test_snapshot_drives_analysis(self):
        p = make_roast()
        p.plan = self._coffee().snapshot()
        a = p.analyze()
        assert a.plan is not None
        assert a.fc_vs_plan_s == pytest.approx(0)
        assert a.drop_vs_plan_s == pytest.approx(0)

    def test_late_fc_flagged(self):
        p = make_roast(fc_s=460, drop_s=560)
        p.plan = self._coffee().snapshot()
        a = p.analyze()
        assert a.fc_vs_plan_s == pytest.approx(50)
        assert any(f.short.startswith("FC 0:50 LATE") for f in a.findings)

    def test_live_bt_vs_plan(self):
        p = make_roast(drop_s=None, until_s=300)
        p.plan = self._coffee().snapshot()
        a = p.analyze()
        assert a.bt_vs_plan_f is not None
        assert abs(f_to_c(a.bt_vs_plan_f + 32) - 0) < 10

    def test_session_stores_plan(self):
        s = RoastSession()
        s.select_coffee(self._coffee())
        assert s.meta["coffee"] == "Test"
        prof = s.build_profile()
        assert prof.coffee_id == "t" and prof.plan["plan"]["fc_s"] == 410
        s.reset()
        assert s.coffee is not None  # carries over to the next roast
        s.select_coffee(None)
        assert s.build_profile().plan == {}


def test_web_coffee_pages(tmp_path):
    from roastmaster.profiles.manager import ProfileManager

    lib = CoffeeLibrary(tmp_path / "coffees")
    lib.save(Coffee(id="t", name="Test", steps=["go"], rationale="why"))
    live = LiveState()
    srv = RoastWebServer(ProfileManager(tmp_path / "p"), live, host="127.0.0.1", port=0,
                         coffees=lib)
    srv.start()
    base = f"http://127.0.0.1:{srv.port}"
    try:
        with urllib.request.urlopen(base + "/coffees", timeout=5) as r:
            assert "Test" in r.read().decode()
        with urllib.request.urlopen(base + "/coffee/t", timeout=5) as r:
            assert "How to fly it" in r.read().decode()
        data = urllib.parse.urlencode({"name": "Kenya AA", "process": "washed"}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/coffees", data=data), timeout=5)
        assert lib.get("kenya-aa").status == "draft"
        data = urllib.parse.urlencode({"coffee_id": "t", "coffee": "", "notes": ""}).encode()
        urllib.request.urlopen(urllib.request.Request(base + "/live", data=data), timeout=5)
        assert live.drain_meta()["coffee_id"] == "t"
    finally:
        srv.stop()


def test_web_reassigns_roast_to_another_plan(tmp_path):
    from roastmaster.profiles.manager import ProfileManager

    lib = CoffeeLibrary(tmp_path / "coffees")
    right = Coffee(id="brazil", name="Brazil Oberon", plan=RoastPlan(fc_s=440, drop_s=570))
    lib.save(Coffee(id="limu", name="Limu G2"))
    lib.save(right)
    pm = ProfileManager(tmp_path / "p")
    roast = make_roast()
    roast.coffee, roast.coffee_id = "Limu G2", "limu"
    roast.plan = lib.get("limu").snapshot()
    pm.save_roast(roast)
    srv = RoastWebServer(pm, LiveState(), host="127.0.0.1", port=0, coffees=lib)
    srv.start()
    try:
        data = urllib.parse.urlencode({"coffee_id": "brazil", "coffee": "Limu G2",
                                       "weight_g": "170", "tasting_notes": "nutty"}).encode()
        url = f"http://127.0.0.1:{srv.port}/roast/{roast.roast_id}"
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=5)
    finally:
        srv.stop()
    fixed = pm.load(roast.roast_id)
    assert fixed.coffee_id == "brazil" and fixed.coffee == "Brazil Oberon"
    assert fixed.plan["plan"]["fc_s"] == 440
    assert fixed.tasting_notes == "nutty"
