"""Roast profile data schema.

A profile captures the complete record of a single roast: metadata, the
time-series of readings, events, and the control settings used.  Profiles
are serialised to/from plain dicts so they can be stored as JSON files.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ProfileSample:
    """One data point in the roast time-series."""

    elapsed: float  # seconds since charge
    bt: float  # bean temperature (F)
    et: float  # environment temperature (F)
    ror: float | None = None  # rate of rise (F/min)
    burner: float = 0.0  # heater %
    drum: float = 0.0  # drum speed %
    air: float = 0.0  # fan/air %
    sv: float | None = None  # roaster setpoint (F), when reported
    hp: float | None = None  # heater power reported by the roaster (%)

    def to_dict(self) -> dict:
        d = {
            "elapsed": round(self.elapsed, 1),
            "bt": round(self.bt, 1),
            "et": round(self.et, 1),
            "ror": round(self.ror, 1) if self.ror is not None else None,
            "burner": round(self.burner, 1),
            "drum": round(self.drum, 1),
            "air": round(self.air, 1),
        }
        if self.sv is not None:
            d["sv"] = round(self.sv, 1)
        if self.hp is not None:
            d["hp"] = round(self.hp, 1)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ProfileSample:
        return cls(
            elapsed=d["elapsed"],
            bt=d["bt"],
            et=d["et"],
            ror=d.get("ror"),
            burner=d.get("burner", 0.0),
            drum=d.get("drum", 0.0),
            air=d.get("air", 0.0),
            sv=d.get("sv"),
            hp=d.get("hp"),
        )


@dataclass
class ProfileEvent:
    """A key roast event (charge, first crack, drop, etc.)."""

    event_type: str  # e.g. "CHARGE", "FIRST_CRACK", "DROP"
    elapsed: float  # seconds since charge
    temperature: float  # BT at event time

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "elapsed": round(self.elapsed, 1),
            "temperature": round(self.temperature, 1),
        }

    @classmethod
    def from_dict(cls, d: dict) -> ProfileEvent:
        return cls(
            event_type=d["event_type"],
            elapsed=d["elapsed"],
            temperature=d["temperature"],
        )


@dataclass
class RoastProfile:
    """Complete record of a single roast.

    Contains metadata, the full time-series of sensor data and control
    inputs, and any events that were marked during the roast.
    """

    # Metadata
    name: str = ""
    coffee: str = ""  # coffee name/origin
    weight_g: float = 0.0  # green (input) batch weight in grams
    notes: str = ""  # roast notes (what you did / intended)
    roast_date: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M"))
    roast_id: str = ""  # timestamp id, also the file stem (e.g. 2026-09-28_1432)
    roasted_weight_g: float | None = None  # weight after roasting
    rating: int | None = None  # 1-10 cup score
    tasting_notes: str = ""
    coffee_id: str = ""  # coffee library id, when roasted against a plan
    plan: dict = field(default_factory=dict)  # snapshot of that coffee's plan

    # Time series and events
    samples: list[ProfileSample] = field(default_factory=list)
    events: list[ProfileEvent] = field(default_factory=list)

    # Analysis summary (Celsius) computed at save time — convenient for logs.
    analysis: dict = field(default_factory=dict)

    # Fields a person edits after the roast (web page); preserved across re-saves.
    USER_FIELDS = ("coffee", "weight_g", "notes", "roasted_weight_g", "rating", "tasting_notes")

    def to_dict(self) -> dict:
        return {
            "roast_id": self.roast_id,
            "name": self.name,
            "coffee": self.coffee,
            "weight_g": self.weight_g,
            "roasted_weight_g": self.roasted_weight_g,
            "rating": self.rating,
            "notes": self.notes,
            "tasting_notes": self.tasting_notes,
            "roast_date": self.roast_date,
            "coffee_id": self.coffee_id,
            "plan": self.plan,
            "analysis": self.analysis,
            "events": [e.to_dict() for e in self.events],
            "samples": [s.to_dict() for s in self.samples],
        }

    @classmethod
    def from_dict(cls, d: dict) -> RoastProfile:
        return cls(
            name=d.get("name", ""),
            coffee=d.get("coffee", ""),
            weight_g=d.get("weight_g", 0.0),
            notes=d.get("notes", ""),
            roast_date=d.get("roast_date", ""),
            roast_id=d.get("roast_id", ""),
            roasted_weight_g=d.get("roasted_weight_g"),
            rating=d.get("rating"),
            tasting_notes=d.get("tasting_notes", ""),
            coffee_id=d.get("coffee_id", ""),
            plan=d.get("plan") or {},
            samples=[ProfileSample.from_dict(s) for s in d.get("samples", [])],
            events=[ProfileEvent.from_dict(e) for e in d.get("events", [])],
            analysis=d.get("analysis") or {},
        )

    def plan_coffee(self):  # -> Coffee | None
        """The coffee plan this roast was made against (as it was that day)."""
        if not self.plan:
            return None
        from roastmaster.profiles.coffees import Coffee

        try:
            coffee = Coffee.from_snapshot(self.plan)
            coffee.curve()  # validate
        except (ValueError, KeyError, TypeError):
            return None
        return coffee

    def analyze(self, *, targets=None):  # -> RoastAnalysis
        """Run the phase analysis over this profile's data (against its plan, if any)."""
        from roastmaster.engine.analysis import DEFAULT_TARGETS, analyze_roast

        coffee = self.plan_coffee()
        return analyze_roast(
            self.samples,
            self.events,
            targets=targets or (coffee.analysis_targets() if coffee else DEFAULT_TARGETS),
            green_weight_g=self.weight_g or None,
            roasted_weight_g=self.roasted_weight_g,
            plan=coffee.plan_targets() if coffee else None,
        )
