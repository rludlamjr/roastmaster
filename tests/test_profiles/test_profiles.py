"""Tests for the profile schema and manager."""

from __future__ import annotations

import json

import pytest

from roastmaster.profiles.manager import ProfileManager, _sanitise_filename
from roastmaster.profiles.schema import ProfileEvent, ProfileSample, RoastProfile

# ---------------------------------------------------------------------------
# ProfileSample
# ---------------------------------------------------------------------------


class TestProfileSample:
    def test_basic_fields(self):
        s = ProfileSample(elapsed=10.0, bt=300.0, et=350.0, ror=15.5, burner=80.0)
        assert s.elapsed == 10.0
        assert s.bt == 300.0
        assert s.ror == 15.5

    def test_defaults(self):
        s = ProfileSample(elapsed=0.0, bt=70.0, et=70.0)
        assert s.ror is None
        assert s.burner == 0.0
        assert s.drum == 0.0
        assert s.air == 0.0

    def test_to_dict(self):
        s = ProfileSample(elapsed=10.0, bt=300.0, et=350.0, ror=15.5, burner=80.0)
        d = s.to_dict()
        assert d["elapsed"] == 10.0
        assert d["bt"] == 300.0
        assert d["ror"] == 15.5
        assert d["burner"] == 80.0

    def test_to_dict_none_ror(self):
        s = ProfileSample(elapsed=0.0, bt=70.0, et=70.0)
        assert s.to_dict()["ror"] is None

    def test_from_dict(self):
        d = {"elapsed": 5.0, "bt": 200.0, "et": 250.0, "ror": 10.0}
        s = ProfileSample.from_dict(d)
        assert s.elapsed == 5.0
        assert s.bt == 200.0
        assert s.ror == 10.0
        assert s.burner == 0.0  # default

    def test_roundtrip(self):
        original = ProfileSample(elapsed=42.0, bt=388.3, et=420.1, ror=12.7, burner=75.0)
        restored = ProfileSample.from_dict(original.to_dict())
        assert restored.elapsed == pytest.approx(original.elapsed, abs=0.1)
        assert restored.bt == pytest.approx(original.bt, abs=0.1)
        assert restored.ror == pytest.approx(original.ror, abs=0.1)


# ---------------------------------------------------------------------------
# ProfileEvent
# ---------------------------------------------------------------------------


class TestProfileEvent:
    def test_basic(self):
        e = ProfileEvent(event_type="FIRST_CRACK", elapsed=420.0, temperature=400.0)
        assert e.event_type == "FIRST_CRACK"

    def test_to_dict(self):
        e = ProfileEvent(event_type="DROP", elapsed=600.0, temperature=430.0)
        d = e.to_dict()
        assert d["event_type"] == "DROP"
        assert d["elapsed"] == 600.0

    def test_roundtrip(self):
        original = ProfileEvent(event_type="CHARGE", elapsed=0.0, temperature=380.0)
        restored = ProfileEvent.from_dict(original.to_dict())
        assert restored.event_type == original.event_type
        assert restored.temperature == original.temperature


# ---------------------------------------------------------------------------
# RoastProfile
# ---------------------------------------------------------------------------


class TestRoastProfile:
    def test_empty_profile(self):
        p = RoastProfile()
        assert p.name == ""
        assert p.samples == []
        assert p.events == []

    def test_with_data(self):
        p = RoastProfile(
            name="Test Roast",
            coffee="Ethiopia Yirgacheffe",
            weight_g=250.0,
            samples=[ProfileSample(elapsed=0.0, bt=380.0, et=420.0)],
            events=[ProfileEvent(event_type="CHARGE", elapsed=0.0, temperature=380.0)],
        )
        assert p.name == "Test Roast"
        assert len(p.samples) == 1
        assert len(p.events) == 1

    def test_to_dict(self):
        p = RoastProfile(name="My Roast", coffee="Brazil", weight_g=200.0)
        d = p.to_dict()
        assert d["name"] == "My Roast"
        assert d["coffee"] == "Brazil"
        assert d["weight_g"] == 200.0
        assert d["samples"] == []
        assert d["events"] == []

    def test_roundtrip(self):
        original = RoastProfile(
            name="Roundtrip Test",
            coffee="Colombia Supremo",
            weight_g=300.0,
            notes="Medium roast",
            samples=[
                ProfileSample(elapsed=0.0, bt=380.0, et=420.0, ror=None),
                ProfileSample(elapsed=60.0, bt=300.0, et=400.0, ror=10.0, burner=80.0),
            ],
            events=[
                ProfileEvent(event_type="CHARGE", elapsed=0.0, temperature=380.0),
                ProfileEvent(event_type="FIRST_CRACK", elapsed=420.0, temperature=400.0),
            ],
        )
        d = original.to_dict()
        restored = RoastProfile.from_dict(d)
        assert restored.name == original.name
        assert restored.coffee == original.coffee
        assert len(restored.samples) == 2
        assert len(restored.events) == 2
        assert restored.samples[1].ror == pytest.approx(10.0)
        assert restored.events[1].event_type == "FIRST_CRACK"

    def test_from_dict_missing_optional_fields(self):
        d = {"name": "Minimal"}
        p = RoastProfile.from_dict(d)
        assert p.name == "Minimal"
        assert p.coffee == ""
        assert p.samples == []


# ---------------------------------------------------------------------------
# Filename sanitisation
# ---------------------------------------------------------------------------


class TestSanitiseFilename:
    def test_simple_name(self):
        assert _sanitise_filename("My Roast") == "my_roast"

    def test_special_characters(self):
        assert _sanitise_filename("Ethiopia 2024/01/15!") == "ethiopia_2024_01_15"

    def test_empty_string(self):
        assert _sanitise_filename("") == "untitled"

    def test_only_special_chars(self):
        assert _sanitise_filename("!!!") == "untitled"


# ---------------------------------------------------------------------------
# ProfileManager
# ---------------------------------------------------------------------------


class TestProfileManager:
    def test_save_and_load(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path)
        profile = RoastProfile(
            name="Test Save",
            coffee="Kenya AA",
            samples=[ProfileSample(elapsed=0.0, bt=380.0, et=420.0)],
        )
        path = mgr.save(profile)
        assert path.exists()

        loaded = mgr.load(path.stem)
        assert loaded.name == "Test Save"
        assert loaded.coffee == "Kenya AA"
        assert len(loaded.samples) == 1

    def test_save_creates_directory(self, tmp_path):
        target = tmp_path / "sub" / "profiles"
        mgr = ProfileManager(directory=target)
        profile = RoastProfile(name="Nested")
        mgr.save(profile)
        assert target.is_dir()

    def test_save_with_explicit_filename(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path)
        profile = RoastProfile(name="My Roast")
        path = mgr.save(profile, filename="custom_name")
        assert path.name == "custom_name.json"

    def test_save_overwrites_existing(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path)
        p1 = RoastProfile(name="Version 1", notes="old")
        p2 = RoastProfile(name="Version 2", notes="new")
        mgr.save(p1, filename="same")
        mgr.save(p2, filename="same")
        loaded = mgr.load("same")
        assert loaded.name == "Version 2"
        assert loaded.notes == "new"

    def test_load_with_extension(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path)
        profile = RoastProfile(name="Ext Test")
        mgr.save(profile, filename="myfile")
        loaded = mgr.load("myfile.json")
        assert loaded.name == "Ext Test"

    def test_load_nonexistent_raises(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path)
        with pytest.raises(FileNotFoundError):
            mgr.load("does_not_exist")

    def test_list_profiles_empty(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path)
        assert mgr.list_profiles() == []

    def test_list_profiles_nonexistent_dir(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path / "nope")
        assert mgr.list_profiles() == []

    def test_list_profiles(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path)
        mgr.save(RoastProfile(name="Alpha"), filename="alpha")
        mgr.save(RoastProfile(name="Bravo"), filename="bravo")
        mgr.save(RoastProfile(name="Charlie"), filename="charlie")
        profiles = mgr.list_profiles()
        assert profiles == ["alpha", "bravo", "charlie"]

    def test_saved_file_is_valid_json(self, tmp_path):
        mgr = ProfileManager(directory=tmp_path)
        profile = RoastProfile(
            name="JSON Check",
            samples=[ProfileSample(elapsed=i * 5.0, bt=200.0 + i, et=250.0 + i) for i in range(5)],
        )
        path = mgr.save(profile)
        data = json.loads(path.read_text())
        assert data["name"] == "JSON Check"
        assert len(data["samples"]) == 5
