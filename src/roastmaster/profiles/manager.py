"""Profile manager: save, load, and list roast profiles.

Profiles are stored as JSON files in a configurable directory.  File names
are derived from the profile name (sanitised for the filesystem) with a
``.json`` extension.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from roastmaster.profiles.schema import RoastProfile

# Default storage directory (relative to project root / working dir).
_DEFAULT_DIR = Path("profiles")


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
        self._dir.mkdir(parents=True, exist_ok=True)

        stem = filename or _sanitise_filename(profile.name)
        path = self._dir / f"{stem}.json"
        path.write_text(json.dumps(profile.to_dict(), indent=2) + "\n")
        return path

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
