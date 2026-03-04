"""Sound effects for RoastMaster — plays one-shot WAV/MP3 files via pygame.mixer.

Short sound effects use pygame.mixer.Sound (multiple can overlap).
Background music and long MP3s (startup, shutdown) use pygame.mixer.music
(single stream, supports looping).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pygame

from roastmaster.hal.base import InputEvent

logger = logging.getLogger(__name__)

_SFX_DIR = Path(__file__).resolve().parent.parent.parent / "assets" / "sfx"

# Map input events to sound filenames (played via mixer.Sound)
_EVENT_SOUNDS: dict[InputEvent, str] = {
    # Dedicated sounds
    InputEvent.HEAT_TOGGLE: "heating.wav",
    InputEvent.COOL_TOGGLE: "cooling.wav",
    InputEvent.DROP: "drop.mp3",
    InputEvent.ROAST_RESET: "reset.wav",
    InputEvent.CHARGE: "charge.wav",
    InputEvent.FIRST_CRACK: "crack.wav",
    InputEvent.SECOND_CRACK: "crack.wav",
    # Menu / navigation sounds
    InputEvent.NAV_UP: "menu_change.wav",
    InputEvent.NAV_DOWN: "menu_change.wav",
    InputEvent.UNIT_TOGGLE: "menu_change.wav",
    InputEvent.HELP_TOGGLE: "menu_change.wav",
    InputEvent.MUSIC_TOGGLE: "menu_change.wav",
    InputEvent.PROFILE_SAVE: "menuselect.wav",
    InputEvent.PROFILE_LOAD: "menuselect.wav",
    InputEvent.CONFIRM: "menuselect.wav",
}

_BG_MUSIC_FILE = "bg_music1.mp3"
_STARTUP_FILE = "startup.mp3"
_SHUTDOWN_FILE = "shutdown.mp3"


class SFX:
    """Loads and plays one-shot sound effects and background music."""

    def __init__(self) -> None:
        self._sounds: dict[str, pygame.mixer.Sound] = {}
        self._available = False
        self._music_on = False

        try:
            if not pygame.mixer.get_init():
                pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=8192)
                pygame.mixer.init()
            self._available = True
        except pygame.error:
            logger.warning("pygame.mixer not available — sound effects disabled")
            return

        # Pre-load all unique sound effect files
        for filename in set(_EVENT_SOUNDS.values()):
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

    # --- Music channel (startup, shutdown, background music) ---------------

    def play_startup(self) -> None:
        """Play the startup MP3 via the music channel.

        Playback continues after the title screen is dismissed.
        """
        if not self._available:
            return
        path = _SFX_DIR / _STARTUP_FILE
        if not path.exists():
            logger.warning("Startup sound not found: %s", path)
            return
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
        except pygame.error:
            logger.warning("Failed to play startup sound")

    def start_shutdown(self) -> bool:
        """Stop any music and start the shutdown MP3 (non-blocking).

        Returns True if the shutdown sound is now playing.
        """
        if not self._available:
            return False
        # Stop background music / startup sound first
        self._music_on = False
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass

        path = _SFX_DIR / _SHUTDOWN_FILE
        if not path.exists():
            logger.warning("Shutdown sound not found: %s", path)
            return False
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play()
            return True
        except pygame.error:
            logger.warning("Failed to play shutdown sound")
            return False

    @staticmethod
    def shutdown_playing() -> bool:
        """Return True if the shutdown sound is still playing."""
        try:
            return pygame.mixer.music.get_busy()
        except pygame.error:
            return False

    def toggle_bg_music(self) -> bool:
        """Toggle background music on/off. Returns new state."""
        if not self._available:
            return False
        if self._music_on:
            self._music_on = False
            try:
                pygame.mixer.music.stop()
            except pygame.error:
                pass
            return False
        else:
            return self._start_bg_music()

    def _start_bg_music(self) -> bool:
        """Start looping background music. Returns True on success."""
        path = _SFX_DIR / _BG_MUSIC_FILE
        if not path.exists():
            logger.warning("Background music not found: %s", path)
            return False
        try:
            pygame.mixer.music.load(str(path))
            pygame.mixer.music.play(loops=-1)
            self._music_on = True
            return True
        except pygame.error:
            logger.warning("Failed to start background music")
            return False

    @property
    def music_on(self) -> bool:
        """Whether background music is currently playing."""
        return self._music_on
