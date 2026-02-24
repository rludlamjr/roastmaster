"""Session-wide pytest configuration and fixtures.

Initialises pygame in headless/dummy mode so that tests which rely on the
pygame event system (e.g. KeyboardInput.poll_events) can run without a
physical display.  SDL_VIDEODRIVER=dummy is set *before* pygame.init() so
no window is created.
"""

import os

import pygame
import pytest


@pytest.fixture(scope="session", autouse=True)
def pygame_headless():
    """Initialise pygame with a dummy video driver for the entire test session."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    pygame.init()
    yield
    pygame.quit()
