"""Sound effects for RoastMaster — plays one-shot WAV files via pygame.mixer."""

from __future__ import annotations

import logging
from pathlib import Path

import pygame

from roastmaster.hal.base import InputEvent

logger = logging.getLogger(__name__)

_SFX_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "sfx"

# Map input events to WAV filenames
_EVENT_SOUNDS: dict[InputEvent, str] = {
    # Dedicated sounds
    InputEvent.HEAT_TOGGLE: "heating.wav",
    InputEvent.COOL_TOGGLE: "cooling.wav",
    InputEvent.DROP: "drop.wav",
    InputEvent.ROAST_RESET: "reset.wav",
    # QUIT/shutdown is played via play_and_wait() during cleanup, not here
    # Menu / navigation sounds
    InputEvent.NAV_UP: "menu_change.wav",
    InputEvent.NAV_DOWN: "menu_change.wav",
    InputEvent.UNIT_TOGGLE: "menu_change.wav",
    InputEvent.HELP_TOGGLE: "menu_change.wav",
    InputEvent.CHARGE: "charge.wav",
    InputEvent.FIRST_CRACK: "crack.wav",
    InputEvent.SECOND_CRACK: "crack.wav",
    InputEvent.PROFILE_SAVE: "menuselect.wav",
    InputEvent.PROFILE_LOAD: "menuselect.wav",
    InputEvent.CONFIRM: "menuselect.wav",
}


class SFX:
    """Loads and plays one-shot sound effects."""

    def __init__(self) -> None:
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._available = False

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            self._available = True
        except pygame.error:
            logger.warning("pygame.mixer not available — sound effects disabled")
            return

        # Pre-load all unique WAV files
        for filename in set(_EVENT_SOUNDS.values()) | {"title_startup.wav"}:
            path = _SFX_DIR / filename
            if path.exists():
                try:
                    self._sounds[filename] = pygame.mixer.Sound(str(path))
                except pygame.error:
                    logger.warning("Failed to load %s", path)
            else:
                logger.warning("Sound file not found: %s", path)

        logger.info("SFX loaded: %d sounds", len(self._sounds))

    def play_event(self, event: InputEvent) -> None:
        """Play the sound associated with an input event (if any)."""
        if not self._available:
            return
        filename = _EVENT_SOUNDS.get(event)
        if filename:
            sound = self._sounds.get(filename)
            if sound:
                sound.play()

    def play_and_wait(self, filename: str) -> None:
        """Play a sound and block until it finishes."""
        if not self._available:
            return
        sound = self._sounds.get(filename)
        if sound:
            sound.play()
            while pygame.mixer.get_busy():
                pygame.time.wait(50)

    def play_startup(self) -> None:
        """Play the title screen startup sound."""
        if not self._available:
            return
        sound = self._sounds.get("title_startup.wav")
        if sound:
            sound.play()
