"""Profile manager: save, load, and list roast profiles.

Profiles are stored as JSON files in a configurable directory.  File names
are derived from the profile name (sanitised for the filesystem) with a
``.json`` extension.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from roastmaster.profiles.schema import RoastProfile

logger = logging.getLogger(__name__)

# Default storage directory (relative to project root / working dir).
_DEFAULT_DIR = Path("profiles")


def new_roast_id() -> str:
    """Timestamp id for a new roast, used as its file stem."""
    return time.strftime("%Y-%m-%d_%H%M%S")


def _sanitise_filename(name: str) -> str:
    """Turn a human-readable profile name into a safe filename stem."""
    # Replace non-alphanumeric chars with underscores, collapse runs.
    stem = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return stem or "untitled"


class ProfileManager:
    """Manages saving, loading, and listing roast profiles on disk.

    Parameters
    ----------
    directory:
        Path to the directory where profile JSON files are stored.
        Created automatically on first save if it does not exist.
    """

    def __init__(self, directory: Path | str | None = None) -> None:
        self._dir = Path(directory) if directory else _DEFAULT_DIR
        # Saves come from the roast loop and the web server thread.
        self._lock = threading.RLock()

    @property
    def directory(self) -> Path:
        return self._dir

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, profile: RoastProfile, filename: str | None = None) -> Path:
        """Save a profile to disk as JSON.

        Parameters
        ----------
        profile:
            The roast profile to save.
        filename:
            Optional filename (without extension).  If not provided, a name
            is derived from ``profile.name``.

        Returns
        -------
        Path
            The path to the saved file.
        """
        stem = filename or _sanitise_filename(profile.name)
        path = self._dir / f"{stem}.json"
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(profile.to_dict(), indent=2) + "\n")
            os.replace(tmp, path)
        return path

    def save_roast(self, profile: RoastProfile) -> Path:
        """Save a roast under its ``roast_id``, keeping edits made elsewhere.

        If the file already exists, user-edited fields (coffee, weights,
        rating, notes) that are empty on *profile* are taken from the file,
        so the roast loop re-saving never wipes notes entered on the web page.
        The analysis summary is recomputed.
        """
        if not profile.roast_id:
            profile.roast_id = new_roast_id()
        with self._lock:
            try:
                existing = self.load(profile.roast_id)
            except (FileNotFoundError, ValueError, KeyError):
                existing = None
            if existing is not None:
                for name in RoastProfile.USER_FIELDS:
                    if getattr(profile, name) in (None, "", 0, 0.0):
                        setattr(profile, name, getattr(existing, name))
            profile.analysis = profile.analyze().to_dict()
            return self.save(profile, filename=profile.roast_id)

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    def load(self, filename: str) -> RoastProfile:
        """Load a profile from a JSON file.

        Parameters
        ----------
        filename:
            Filename (with or without ``.json`` extension) relative to the
            profile directory.

        Raises
        ------
        FileNotFoundError
            If the file does not exist.
        """
        if not filename.endswith(".json"):
            filename = f"{filename}.json"
        path = self._dir / filename
        data = json.loads(path.read_text())
        return RoastProfile.from_dict(data)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------

    def list_profiles(self) -> list[str]:
        """Return a sorted list of available profile filenames (without extension).

        Returns an empty list if the directory does not exist.
        """
        if not self._dir.is_dir():
            return []
        return sorted(p.stem for p in self._dir.glob("*.json"))

    def list_recent(self) -> list[str]:
        """Profile names, newest file first."""
        if not self._dir.is_dir():
            return []
        paths = sorted(
            self._dir.glob("*.json"), key=lambda p: (p.stat().st_mtime, p.stem), reverse=True
        )
        return [p.stem for p in paths]

    def load_all(self) -> list[RoastProfile]:
        """Load every readable profile, newest first. Unreadable files are skipped."""
        out: list[RoastProfile] = []
        for name in self.list_recent():
            try:
                profile = self.load(name)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.warning("Skipping unreadable profile %s: %s", name, exc)
                continue
            if not profile.roast_id:
                profile.roast_id = name
            out.append(profile)
        out.sort(key=lambda p: p.roast_date or "", reverse=True)
        return out

    def recent_coffees(self, limit: int = 20) -> list[str]:
        """Distinct coffee names from saved roasts, most recent first."""
        seen: list[str] = []
        for profile in self.load_all():
            name = profile.coffee.strip()
            if name and name.lower() not in (s.lower() for s in seen):
                seen.append(name)
            if len(seen) >= limit:
                break
        return seen
