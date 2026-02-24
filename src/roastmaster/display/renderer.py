"""Main screen compositor for the RoastMaster CRT display.

Arranges all widgets into a 640x480 layout and renders them each frame
from a data dictionary.

Expected data dict keys
-----------------------
    bt          : float | None  – Bean temperature (°F)
    et          : float | None  – Environment temperature (°F)
    ror         : float | None  – Rate of rise (°F/min)
    elapsed     : float         – Roast elapsed time in seconds
    phase       : str           – 'IDLE' | 'PREHEAT' | 'ROASTING' | 'COOLING'
    burner      : float         – Burner % (0-100)
    drum        : float         – Drum speed % (0-100)
    air         : float         – Air % (0-100)
    message     : str           – Optional status message
"""

from __future__ import annotations

import pygame

from roastmaster.config import SCREEN_HEIGHT, SCREEN_WIDTH
from roastmaster.display import theme
from roastmaster.display.fonts import render_text, text_height, text_width
from roastmaster.display.widgets import (
    ControlIndicator,
    GraphWidget,
    NumericReadout,
    ProfileBrowser,
    StatusBar,
)
from roastmaster.profiles.schema import ProfileSample

# ---------------------------------------------------------------------------
# Layout constants (all in pixels, 640x480 canvas)
# ---------------------------------------------------------------------------

_MARGIN = 4
_TITLE_H = 18          # top title strip height
_READOUT_H = 70        # height of the top readout row
_STATUS_H = 26         # status bar height at the very bottom
_CONTROL_H = 60        # control indicator height above status bar
_GRAPH_TOP = _MARGIN + _TITLE_H + _MARGIN + _READOUT_H + _MARGIN
_GRAPH_BOTTOM = SCREEN_HEIGHT - _MARGIN - _STATUS_H - _MARGIN - _CONTROL_H - _MARGIN
_GRAPH_H = _GRAPH_BOTTOM - _GRAPH_TOP

# Three equal-width readout panels across the top
_READOUT_W = (SCREEN_WIDTH - _MARGIN * 4) // 3


class Renderer:
    """Composites all widgets onto a pygame Surface every frame.

    Parameters
    ----------
    surface:
        The main pygame display surface (must be 640x480).
    window_seconds:
        How many seconds of temperature history the graph shows at once.
    """

    def __init__(
        self,
        surface: pygame.Surface,
        window_seconds: float = 600.0,
    ) -> None:
        self._surface = surface

        # -- Readout widgets (top row) --
        readout_y = _MARGIN + _TITLE_H + _MARGIN
        self._bt_readout = NumericReadout(
            rect=(_MARGIN, readout_y, _READOUT_W, _READOUT_H),
            label="BT",
            unit="F",
            color=theme.TRACE_BT,
            value_scale=4,
        )
        self._et_readout = NumericReadout(
            rect=(_MARGIN * 2 + _READOUT_W, readout_y, _READOUT_W, _READOUT_H),
            label="ET",
            unit="F",
            color=theme.TRACE_ET,
            value_scale=4,
        )
        self._ror_readout = NumericReadout(
            rect=(_MARGIN * 3 + _READOUT_W * 2, readout_y, _READOUT_W, _READOUT_H),
            label="ROR",
            unit="F/M",
            color=theme.TRACE_ROR,
            value_scale=4,
        )

        # -- Graph (centre) --
        self._graph = GraphWidget(
            rect=(_MARGIN, _GRAPH_TOP, SCREEN_WIDTH - _MARGIN * 2, _GRAPH_H),
            temp_min=50.0,
            temp_max=500.0,
            window_seconds=window_seconds,
        )

        # -- Control indicator (above status bar) --
        control_y = SCREEN_HEIGHT - _MARGIN - _STATUS_H - _MARGIN - _CONTROL_H
        # Split the bottom band: control takes left 2/3, a small info panel takes right 1/3
        control_w = (SCREEN_WIDTH - _MARGIN * 3) * 2 // 3
        self._control = ControlIndicator(
            rect=(_MARGIN, control_y, control_w, _CONTROL_H),
        )

        # Small phase / info label panel on the right of controls
        info_x = _MARGIN * 2 + control_w
        info_w = SCREEN_WIDTH - info_x - _MARGIN
        self._info_rect = pygame.Rect(info_x, control_y, info_w, _CONTROL_H)

        # -- Status bar (bottom) --
        status_y = SCREEN_HEIGHT - _MARGIN - _STATUS_H
        self._status = StatusBar(
            rect=(_MARGIN, status_y, SCREEN_WIDTH - _MARGIN * 2, _STATUS_H),
        )

        # -- Profile browser overlay (hidden by default) --
        browser_w = 400
        browser_h = 300
        browser_x = (SCREEN_WIDTH - browser_w) // 2
        browser_y = (SCREEN_HEIGHT - browser_h) // 2
        self._browser = ProfileBrowser(
            rect=(browser_x, browser_y, browser_w, browser_h),
        )
        self._browser_visible = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_reference_profile(self, samples: list[ProfileSample]) -> None:
        """Load a reference profile into the graph for comparison."""
        self._graph.set_reference(samples)

    def clear_reference_profile(self) -> None:
        """Remove the reference profile overlay from the graph."""
        self._graph.clear_reference()

    @property
    def browser(self) -> ProfileBrowser:
        """Access the profile browser widget."""
        return self._browser

    @property
    def browser_visible(self) -> bool:
        return self._browser_visible

    def show_browser(self, profiles: list[str]) -> None:
        """Open the profile browser overlay with the given profile list."""
        self._browser.set_profiles(profiles)
        self._browser_visible = True

    def hide_browser(self) -> None:
        """Close the profile browser overlay."""
        self._browser_visible = False

    def push_data(self, data: dict) -> None:
        """Feed a new data sample into the graph traces.

        Call this each time a new temperature sample arrives (typically
        once per second).
        """
        elapsed = float(data.get("elapsed", 0.0))
        bt = data.get("bt")
        et = data.get("et")
        ror = data.get("ror")

        if bt is not None:
            self._graph.add_point("BT", elapsed, float(bt))
        if et is not None:
            self._graph.add_point("ET", elapsed, float(et))
        if ror is not None:
            self._graph.add_point("RoR", elapsed, float(ror))

    def render(self, data: dict) -> None:
        """Draw the full display for the current frame.

        Parameters
        ----------
        data:
            Current-state dictionary (see module docstring for keys).
        """
        surface = self._surface
        elapsed = float(data.get("elapsed", 0.0))
        phase = str(data.get("phase", "IDLE"))
        bt = data.get("bt")
        et = data.get("et")
        ror = data.get("ror")
        burner = float(data.get("burner", 0.0))
        drum = float(data.get("drum", 0.0))
        air = float(data.get("air", 0.0))
        message = str(data.get("message", ""))

        # Clear
        surface.fill(theme.BG)

        # Outer border
        pygame.draw.rect(surface, theme.GREEN_DIM, (0, 0, SCREEN_WIDTH, SCREEN_HEIGHT), 1)

        # Title strip
        self._draw_title(surface, elapsed)

        # Readouts
        self._bt_readout.update(bt)
        self._bt_readout.draw(surface)

        self._et_readout.update(et)
        self._et_readout.draw(surface)

        self._ror_readout.update(ror)
        self._ror_readout.draw(surface)

        # Graph
        self._graph.draw(surface, elapsed)

        # Controls
        self._control.update(burner, drum, air)
        self._control.draw(surface)

        # Info panel
        self._draw_info_panel(surface, phase, elapsed)

        # Status bar
        self._status.update(phase, elapsed, message)
        self._status.draw(surface)

        # Profile browser overlay (on top of everything)
        if self._browser_visible:
            self._browser.draw(surface)

    # ------------------------------------------------------------------
    # Private rendering helpers
    # ------------------------------------------------------------------

    def _draw_title(self, surface: pygame.Surface, elapsed: float) -> None:
        """Draw the narrow title band at the top of the screen."""
        title_rect = pygame.Rect(_MARGIN, _MARGIN, SCREEN_WIDTH - _MARGIN * 2, _TITLE_H)
        pygame.draw.rect(surface, theme.BG, title_rect)
        pygame.draw.rect(surface, theme.GREEN_DIM, title_rect, 1)

        title = "ROASTMASTER"
        tw = text_width(title, scale=2)
        tx = title_rect.x + (title_rect.width - tw) // 2
        ty = title_rect.y + (title_rect.height - text_height(2)) // 2
        render_text(surface, title, tx, ty, theme.TEXT, scale=2)

        # Right-align a small clock
        mins = int(elapsed) // 60
        secs = int(elapsed) % 60
        clock_str = f"T+ {mins:02d}:{secs:02d}"
        cw = text_width(clock_str, scale=1)
        render_text(
            surface,
            clock_str,
            title_rect.right - cw - 4,
            title_rect.y + (title_rect.height - text_height(1)) // 2,
            theme.TEXT_DIM,
            scale=1,
        )

    def _draw_info_panel(
        self, surface: pygame.Surface, phase: str, elapsed: float
    ) -> None:
        """Draw the small info panel to the right of the control bars."""
        r = self._info_rect
        pygame.draw.rect(surface, theme.BG, r)
        pygame.draw.rect(surface, theme.GREEN_DIM, r, 1)

        lines = [
            phase,
            f"{int(elapsed) // 60:02d}:{int(elapsed) % 60:02d}",
            "640x480",
        ]
        pad = 4
        y = r.y + pad
        for line in lines:
            lw = text_width(line, scale=1)
            lx = r.x + (r.width - lw) // 2
            render_text(surface, line, lx, y, theme.TEXT_DIM, scale=1)
            y += text_height(1) + 3
