"""Thread-safe hand-off between the roast loop and the web server.

The roast loop *publishes* a snapshot about once a second; the web server
only reads snapshots.  Edits made on the web page for the roast in progress
(coffee name, batch weight, notes) are queued here and *drained* by the roast
loop, which owns the session.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from roastmaster.engine.analysis import RoastAnalysis
from roastmaster.profiles.schema import ProfileEvent, ProfileSample


@dataclass
class LiveSnapshot:
    roast_id: str = ""
    coffee_id: str = ""
    fsm_phase: str = "IDLE"
    bt_f: float | None = None
    et_f: float | None = None
    ror_f: float | None = None
    meta: dict = field(default_factory=dict)
    samples: list[ProfileSample] = field(default_factory=list)
    events: list[ProfileEvent] = field(default_factory=list)
    analysis: RoastAnalysis | None = None


class LiveState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = LiveSnapshot()
        self._pending_meta: dict = {}

    def publish(self, snapshot: LiveSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot

    def snapshot(self) -> LiveSnapshot:
        with self._lock:
            return self._snapshot

    def submit_meta(self, **fields: object) -> None:
        with self._lock:
            self._pending_meta.update(fields)
            # Reflect immediately so the page shows the new value on reload
            self._snapshot.meta = {**self._snapshot.meta, **fields}

    def drain_meta(self) -> dict:
        with self._lock:
            out, self._pending_meta = self._pending_meta, {}
            return out
