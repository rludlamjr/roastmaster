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

    def to_dict(self) -> dict:
        return {
            "elapsed": round(self.elapsed, 1),
            "bt": round(self.bt, 1),
            "et": round(self.et, 1),
            "ror": round(self.ror, 1) if self.ror is not None else None,
            "burner": round(self.burner, 1),
            "drum": round(self.drum, 1),
            "air": round(self.air, 1),
        }

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
    weight_g: float = 0.0  # batch weight in grams
    notes: str = ""
    roast_date: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M"))

    # Time series and events
    samples: list[ProfileSample] = field(default_factory=list)
    events: list[ProfileEvent] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "coffee": self.coffee,
            "weight_g": self.weight_g,
            "notes": self.notes,
            "roast_date": self.roast_date,
            "samples": [s.to_dict() for s in self.samples],
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, d: dict) -> RoastProfile:
        return cls(
            name=d.get("name", ""),
            coffee=d.get("coffee", ""),
            weight_g=d.get("weight_g", 0.0),
            notes=d.get("notes", ""),
            roast_date=d.get("roast_date", ""),
            samples=[ProfileSample.from_dict(s) for s in d.get("samples", [])],
            events=[ProfileEvent.from_dict(e) for e in d.get("events", [])],
        )
