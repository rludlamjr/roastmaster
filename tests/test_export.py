"""Tests for roast saving, reports, email and the web page."""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from roastmaster.app import RoastSession, crt_text, cycle_coffee, picker_entries, save_session
from roastmaster.engine.events import EventType
from roastmaster.export.mailer import EmailConfig, build_message
from roastmaster.export.report import (
    SUMMARY_COLUMNS,
    html_report,
    samples_csv,
    summary_csv,
    svg_chart,
    text_summary,
)
from roastmaster.profiles.manager import ProfileManager
from roastmaster.profiles.schema import ProfileSample, RoastProfile
from roastmaster.web.live import LiveSnapshot, LiveState
from roastmaster.web.server import RoastWebServer
from tests.roast_fixtures import make_roast

# ---------------------------------------------------------------------------
# Schema / manager
# ---------------------------------------------------------------------------


class TestSchema:
    def test_round_trip_new_fields(self):
        p = make_roast()
        p.roasted_weight_g = 147.5
        p.rating = 7
        p.tasting_notes = "sweet"
        p.samples[0].sv = 392.0
        back = RoastProfile.from_dict(json.loads(json.dumps(p.to_dict())))
        assert back.roast_id == p.roast_id
        assert back.roasted_weight_g == 147.5
        assert back.rating == 7
        assert back.tasting_notes == "sweet"
        assert back.samples[0].sv == 392.0
        assert back.samples[1].hp is None

    def test_old_files_still_load(self):
        old = {"name": "", "coffee": "", "weight_g": 0.0, "notes": "",
               "roast_date": "2026-03-03 11:22",
               "samples": [{"elapsed": 0.0, "bt": 70.0, "et": 70.0, "ror": None,
                            "burner": 0.0, "drum": 50.0, "air": 50.0}],
               "events": []}
        p = RoastProfile.from_dict(old)
        assert p.roast_id == "" and p.rating is None and p.analysis == {}


class TestManager:
    def test_save_roast_uses_id_and_stores_analysis(self, tmp_path):
        pm = ProfileManager(tmp_path)
        path = pm.save_roast(make_roast())
        assert path.name == "2026-09-28_143200.json"
        data = json.loads(path.read_text())
        assert data["analysis"]["dtr_pct"] == pytest.approx(19.6, abs=0.1)

    def test_save_roast_keeps_web_edits(self, tmp_path):
        pm = ProfileManager(tmp_path)
        p = make_roast()
        pm.save_roast(p)
        edited = pm.load(p.roast_id)
        edited.tasting_notes = "bright, juicy"
        edited.rating = 8
        pm.save(edited, filename=p.roast_id)
        # The roast loop re-saves without those fields
        again = make_roast()
        pm.save_roast(again)
        final = pm.load(p.roast_id)
        assert final.tasting_notes == "bright, juicy"
        assert final.rating == 8

    def test_recent_listing_and_coffees(self, tmp_path):
        pm = ProfileManager(tmp_path)
        for i, coffee in enumerate(["RDP", "Kenya", "rdp"]):
            p = make_roast()
            p.roast_id = f"2026-09-2{i}_100000"
            p.roast_date = f"2026-09-2{i} 10:00"
            p.coffee = coffee
            pm.save_roast(p)
        (tmp_path / "broken.json").write_text("{not json")
        roasts = pm.load_all()
        assert [r.roast_id for r in roasts][0] == "2026-09-22_100000"
        assert pm.recent_coffees() == ["rdp", "Kenya"]


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class TestReports:
    def test_summary_csv(self):
        text = summary_csv([make_roast(), make_roast(crash=True)])
        rows = list(csv.DictReader(io.StringIO(text)))
        assert list(rows[0].keys()) == SUMMARY_COLUMNS
        assert rows[0]["fc_time"] == "6:50"
        assert rows[1]["crash"] == "yes"

    def test_samples_csv_relative_to_charge(self):
        rows = list(csv.reader(io.StringIO(samples_csv(make_roast()))))
        times = [int(r[0]) for r in rows[1:]]
        assert 0 in times and min(times) < 0  # preheat samples are negative
        assert any(r[-1] == "FIRST_CRACK" for r in rows[1:])

    def test_text_and_html(self):
        p = make_roast(crash=True)
        p.tasting_notes = "flat <b>"
        assert "RoR crash    YES" in text_summary(p)
        page = html_report(p)
        assert "&lt;b&gt;" in page and "<svg" in page

    def test_svg_chart_handles_live_roast(self):
        assert svg_chart(make_roast(drop_s=None, until_s=300)).startswith("<svg")


class TestEmail:
    def test_config_missing(self, tmp_path):
        assert EmailConfig.load(tmp_path / "nope.toml") is None

    def test_config_and_message(self, tmp_path):
        f = tmp_path / "email.toml"
        f.write_text('smtp_host = "smtp.example.com"\nusername = "a@example.com"\n'
                     'password = "x"\nto = "b@example.com"\n')
        cfg = EmailConfig.load(f)
        assert cfg is not None and cfg.smtp_port == 465 and cfg.auto_send
        msg = build_message(make_roast(), cfg)
        assert "Reserva del Patron" in msg["Subject"]
        assert "DTR" in msg["Subject"]
        names = [part.get_filename() for part in msg.iter_attachments()]
        assert names == ["2026-09-28_143200.html", "2026-09-28_143200_samples.csv",
                         "2026-09-28_143200.json"]


# ---------------------------------------------------------------------------
# App helpers
# ---------------------------------------------------------------------------


class TestSessionHelpers:
    def test_crt_text(self):
        assert crt_text("Reserva del Pátron") == "RESERVA DEL PATRON"

    def test_cycle_coffee(self):
        choices = ["", "RDP", "Kenya"]
        assert cycle_coffee(choices, "", 1) == "RDP"
        assert cycle_coffee(choices, "rdp", 1) == "Kenya"
        assert cycle_coffee(choices, "", -1) == "Kenya"

    def test_picker_entries_end_with_blank(self, tmp_path):
        from roastmaster.profiles.coffees import CoffeeLibrary

        lib = CoffeeLibrary(tmp_path)
        lib.add_draft("Kenya AA")
        coffees, labels = picker_entries(lib)
        assert labels == ["KENYA AA (DRAFT)", "NEW / BLANK"]
        assert coffees[-1] is None

    def test_session_save_and_reset(self, tmp_path):
        s = RoastSession()
        assert s.meta["weight_g"] == 170.0
        s.meta["coffee"] = "RDP"
        for i in range(5):
            s.samples.append(ProfileSample(elapsed=float(i), bt=300.0 + i, et=350.0))
        s.events.mark_event(EventType.CHARGE, 1.0, 301.0)
        assert s.charged and s.unsaved
        path, profile = save_session(s, ProfileManager(tmp_path))
        assert path.stem == s.roast_id and profile.coffee == "RDP"
        assert not s.unsaved
        s.reset()
        assert s.roast_id == "" and s.meta["coffee"] == "RDP"


# ---------------------------------------------------------------------------
# Web
# ---------------------------------------------------------------------------


@pytest.fixture()
def web(tmp_path):
    pm = ProfileManager(tmp_path)
    pm.save_roast(make_roast())
    live = LiveState()
    p = make_roast(drop_s=None, until_s=455)
    live.publish(LiveSnapshot(fsm_phase="ROASTING", samples=p.samples, events=p.events,
                              analysis=p.analyze(), meta={"coffee": "RDP"}))
    srv = RoastWebServer(pm, live, host="127.0.0.1", port=0)
    srv.start()
    yield srv, pm, live, f"http://127.0.0.1:{srv.port}"
    srv.stop()


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, ""


def _post(url: str, fields: dict) -> int:
    data = urllib.parse.urlencode(fields).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=5) as r:
        return r.status


class TestWeb:
    def test_pages(self, web):
        _, _, _, base = web
        status, body = _get(base + "/")
        assert status == 200 and "2026-09-28 14:32" in body and "RDP" in body
        assert _get(base + "/live/fragment")[0] == 200
        assert "<svg" in _get(base + "/live/chart.svg")[1]
        assert _get(base + "/roast/2026-09-28_143200")[0] == 200
        assert _get(base + "/roast/2026-09-28_143200.csv")[0] == 200
        assert "roast_id" in _get(base + "/roasts.csv")[1]

    def test_bad_ids_404(self, web):
        _, _, _, base = web
        assert _get(base + "/roast/nope")[0] == 404
        assert _get(base + "/roast/..%2F..%2Fetc%2Fpasswd")[0] == 404

    def test_edit_roast(self, web):
        _, pm, _, base = web
        _post(base + "/roast/2026-09-28_143200", {
            "coffee": "RDP", "weight_g": "170", "roasted_weight_g": "148",
            "rating": "11", "notes": "", "tasting_notes": "syrupy"})
        p = pm.load("2026-09-28_143200")
        assert p.rating == 10 and p.tasting_notes == "syrupy"
        assert p.analysis["weight_loss_pct"] == pytest.approx(12.9, abs=0.1)

    def test_live_meta_queued_for_roast_loop(self, web):
        _, _, live, base = web
        _post(base + "/live", {"coffee": "Kenya AA", "weight_g": "165", "notes": "hotter"})
        assert live.drain_meta() == {"coffee": "Kenya AA", "weight_g": 165.0, "notes": "hotter"}
        assert live.drain_meta() == {}

    def test_email_not_configured(self, web):
        _, _, _, base = web
        data = urllib.parse.urlencode({}).encode()
        req = urllib.request.Request(base + "/roast/2026-09-28_143200/email", data=data)
        with urllib.request.urlopen(req, timeout=5) as r:
            assert "not configured" in r.read().decode()
