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
    heat_enabled : bool        – Heating enabled (device toggle)
    cooling_enabled : bool     – Cooling enabled (device toggle)

Optional debug keys
-------------------
    connected     : bool        – Device connection status
    device_label  : str         – Short device identifier (e.g. ttyUSB0, SIM)
    debug_visible : bool        – Whether to show debug overlay
    debug_lines   : list[str]   – Debug overlay text lines
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
)
from roastmaster.profiles.schema import ProfileSample

# ---------------------------------------------------------------------------
# Layout constants (all in pixels, 640x480 canvas)
# ---------------------------------------------------------------------------

_MARGIN = 4
_CRT_TOP = 16          # CRT overscan safe margin (top)
_CRT_BOTTOM = 16       # CRT overscan safe margin (bottom)
_READOUT_H = 70        # height of the top readout row
_CONTROL_H = 60        # control indicator height above bottom margin
_GRAPH_TOP = _CRT_TOP + _READOUT_H + _MARGIN   # 90
_CONTROL_Y = SCREEN_HEIGHT - _CRT_BOTTOM - _CONTROL_H  # 404
_GRAPH_BOTTOM = _CONTROL_Y - _MARGIN            # 400
_GRAPH_H = _GRAPH_BOTTOM - _GRAPH_TOP           # 310

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
        readout_y = _CRT_TOP
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

        # -- Control indicator (above bottom overscan) --
        control_y = _CONTROL_Y
        # Split the bottom band: control takes left 2/3, a small info panel takes right 1/3
        control_w = (SCREEN_WIDTH - _MARGIN * 3) * 2 // 3
        self._control = ControlIndicator(
            rect=(_MARGIN, control_y, control_w, _CONTROL_H),
        )

        # Small phase / info label panel on the right of controls
        info_x = _MARGIN * 2 + control_w
        info_w = SCREEN_WIDTH - info_x - _MARGIN
        self._info_rect = pygame.Rect(info_x, control_y, info_w, _CONTROL_H)

        # -- Profile browser overlay (hidden by default) --
        browser_w = 400
        browser_h = 300
        browser_x = (SCREEN_WIDTH - browser_w) // 2
        browser_y = (SCREEN_HEIGHT - browser_h) // 2
        self._browser = ProfileBrowser(
            rect=(browser_x, browser_y, browser_w, browser_h),
        )
        self._browser_visible = False

        # Unit toggle — default to Celsius display
        self._use_celsius: bool = True
        self._graph.use_celsius = self._use_celsius

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def use_celsius(self) -> bool:
        return self._use_celsius

    def toggle_units(self) -> str:
        """Flip between Celsius and Fahrenheit display. Returns 'C' or 'F'."""
        self._use_celsius = not self._use_celsius
        self._graph.use_celsius = self._use_celsius
        return "C" if self._use_celsius else "F"

    def reset_graph(self) -> None:
        """Clear live graph traces for a new roast."""
        self._graph.clear_traces()
        self._graph.clear_charge_time()
        self._graph.clear_events()

    def set_charge_time(self, t: float) -> None:
        """Set the charge time offset on the graph."""
        self._graph.set_charge_time(t)

    def clear_charge_time(self) -> None:
        """Remove the charge time offset from the graph."""
        self._graph.clear_charge_time()

    def set_events(self, events: list[tuple[float, float, str]]) -> None:
        """Set event markers on the graph."""
        self._graph.set_events(events)

    def clear_events(self) -> None:
        """Remove all event markers from the graph."""
        self._graph.clear_events()

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

        # Readouts
        self._bt_readout.update(bt, use_celsius=self._use_celsius)
        self._bt_readout.draw(surface)

        self._et_readout.update(et, use_celsius=self._use_celsius)
        self._et_readout.draw(surface)

        self._ror_readout.update(ror, use_celsius=self._use_celsius)
        self._ror_readout.draw(surface)

        # Debug overlay replaces the graph when active
        debug_visible = bool(data.get("debug_visible", False))
        debug_lines = data.get("debug_lines")
        if (
            debug_visible
            and not self._browser_visible
            and isinstance(debug_lines, list)
            and debug_lines
        ):
            self._draw_full_status_screen(surface, [str(x) for x in debug_lines])
        else:
            # Graph
            self._graph.draw(surface, elapsed)

            # Flash message overlay on top of the graph
            if message:
                self._draw_message_overlay(surface, message)

        # Controls
        self._control.update(burner, drum, air)
        self._control.draw(surface)

        # Info panel
        heat_enabled = data.get("heat_enabled")
        cooling_enabled = data.get("cooling_enabled")
        self._draw_info_panel(
            surface,
            phase,
            elapsed,
            heat_enabled=(bool(heat_enabled) if heat_enabled is not None else None),
            cooling_enabled=(bool(cooling_enabled) if cooling_enabled is not None else None),
        )

        # Profile browser overlay (on top of everything)
        if self._browser_visible:
            self._browser.draw(surface)

    # ------------------------------------------------------------------
    # Private rendering helpers
    # ------------------------------------------------------------------

    def _draw_info_panel(
        self,
        surface: pygame.Surface,
        phase: str,
        elapsed: float,
        *,
        heat_enabled: bool | None = None,
        cooling_enabled: bool | None = None,
    ) -> None:
        """Draw the info panel to the right of the control bars.

        Uses scale=2 for phase and timer so they are legible on a CRT.
        """
        r = self._info_rect
        pygame.draw.rect(surface, theme.BG, r)
        pygame.draw.rect(surface, theme.GREEN_DIM, r, 1)

        pad = 4
        max_w = r.width - pad * 2

        # Line 1: Phase name, scale=2
        phase_text = self._truncate_to_width(phase, max_w, scale=2)
        pw = text_width(phase_text, scale=2)
        px = r.x + (r.width - pw) // 2
        y = r.y + pad
        render_text(surface, phase_text, px, y, theme.TEXT, scale=2)
        y += text_height(2) + 2

        # Line 2: Timer MM:SS, scale=2
        timer_text = f"{int(elapsed) // 60:02d}:{int(elapsed) % 60:02d}"
        tw = text_width(timer_text, scale=2)
        tx = r.x + (r.width - tw) // 2
        render_text(surface, timer_text, tx, y, theme.TEXT, scale=2)
        y += text_height(2) + 2

        # Line 3: H:ON C:OFF, scale=1
        if heat_enabled is True:
            heat = "ON"
        elif heat_enabled is False:
            heat = "OFF"
        else:
            heat = "?"
        if cooling_enabled is True:
            cool = "ON"
        elif cooling_enabled is False:
            cool = "OFF"
        else:
            cool = "?"
        switches_line = f"H:{heat} C:{cool}"
        sw = text_width(switches_line, scale=1)
        sx = r.x + (r.width - sw) // 2
        render_text(surface, switches_line, sx, y, theme.TEXT_DIM, scale=1)

    @staticmethod
    def _truncate_to_width(text: str, max_width_px: int, *, scale: int = 1) -> str:
        """Truncate text to fit within a pixel width using the current bitmap font."""
        if text_width(text, scale=scale) <= max_width_px:
            return text

        suffix = "..."
        if text_width(suffix, scale=scale) > max_width_px:
            return ""

        trimmed = text
        while trimmed and text_width(trimmed + suffix, scale=scale) > max_width_px:
            trimmed = trimmed[:-1]
        return (trimmed + suffix) if trimmed else suffix

    def _draw_full_status_screen(self, surface: pygame.Surface, lines: list[str]) -> None:
        """Draw a full-screen status display in the graph area."""
        pad = 8
        scale = 2
        rect = pygame.Rect(_MARGIN, _GRAPH_TOP, SCREEN_WIDTH - _MARGIN * 2, _GRAPH_H)
        pygame.draw.rect(surface, theme.BG, rect)
        pygame.draw.rect(surface, theme.GREEN_DIM, rect, 1)

        max_content_w = rect.width - pad * 2

        # Title
        title = "SYSTEM STATUS"
        tw = text_width(title, scale=scale)
        tx = rect.x + (rect.width - tw) // 2
        ty = rect.y + pad
        render_text(surface, title, tx, ty, theme.TEXT, scale=scale)
        ty += text_height(scale) + 4

        # Divider line
        pygame.draw.line(
            surface,
            theme.GREEN_DIM,
            (rect.x + pad, ty),
            (rect.right - pad, ty),
        )
        ty += 6

        # Debug lines in scale=2
        line_h = text_height(scale) + 4
        for line in lines:
            if ty + line_h > rect.bottom - pad:
                break
            safe = self._truncate_to_width(line, max_content_w, scale=scale)
            render_text(surface, safe, rect.x + pad, ty, theme.TEXT_DIM, scale=scale)
            ty += line_h

    def _draw_message_overlay(self, surface: pygame.Surface, message: str) -> None:
        """Draw a brief flash message overlay on the graph area."""
        scale = 2
        pad = 6
        mw = text_width(message, scale=scale)
        mh = text_height(scale)

        # Center horizontally in graph area, near top (below legend area)
        graph_rect = pygame.Rect(_MARGIN, _GRAPH_TOP, SCREEN_WIDTH - _MARGIN * 2, _GRAPH_H)
        box_w = mw + pad * 2
        box_h = mh + pad * 2
        bx = graph_rect.x + (graph_rect.width - box_w) // 2
        by = graph_rect.y + 20

        # Semi-transparent dark background
        bg_surf = pygame.Surface((box_w, box_h))
        bg_surf.set_alpha(180)
        bg_surf.fill(theme.BG)
        surface.blit(bg_surf, (bx, by))

        # Text
        tx = bx + pad
        ty = by + pad
        render_text(surface, message, tx, ty, theme.TEXT, scale=scale)
