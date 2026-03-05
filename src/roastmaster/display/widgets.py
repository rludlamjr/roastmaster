"""Reusable CRT-style UI widgets for the RoastMaster display.

All widgets operate on a pygame Surface passed to their draw() method.
They do not maintain any pygame display state themselves.
"""

from __future__ import annotations

import math
from collections import deque
from typing import NamedTuple

import pygame

from roastmaster.display import theme
from roastmaster.display.fonts import render_text, text_height, text_width
from roastmaster.display.units import c_to_f, f_to_c, f_to_c_delta
from roastmaster.profiles.schema import ProfileSample

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _draw_label(
    surface: pygame.Surface,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    scale: int = 1,
) -> None:
    render_text(surface, text, x, y, color, scale)


# ---------------------------------------------------------------------------
# TracePoint – a single data point stored by the graph
# ---------------------------------------------------------------------------


class TracePoint(NamedTuple):
    t: float  # elapsed seconds
    value: float


# ---------------------------------------------------------------------------
# GraphWidget
# ---------------------------------------------------------------------------


class GraphWidget:
    """Real-time scrolling line graph for roasting curves.

    Looks like an oscilloscope / scientific instrument display.

    Parameters
    ----------
    rect:
        (x, y, width, height) area on the parent surface.
    temp_min, temp_max:
        Y-axis temperature bounds.
    window_seconds:
        How many seconds of history are visible at once.
    """

    TRACES = ("BT", "ET", "RoR")
    TRACE_COLORS = {
        "BT": theme.TRACE_BT,
        "ET": theme.TRACE_ET,
        "RoR": theme.TRACE_ROR,
    }
    REF_COLORS = {
        "BT": theme.REF_BT,
        "ET": theme.REF_ET,
        "RoR": theme.REF_ROR,
    }
    # RoR lives on its own scale
    ROR_MIN = -10.0
    ROR_MAX = 30.0

    # Short labels for event markers on the graph
    EVENT_LABELS = {
        "CHARGE": "CH",
        "TURNING_POINT": "TP",
        "FIRST_CRACK": "FC",
        "SECOND_CRACK": "SC",
        "DROP": "DR",
    }

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        temp_min: float = 50.0,
        temp_max: float = 500.0,
        window_seconds: float = 600.0,
    ) -> None:
        self.rect = pygame.Rect(rect)
        self.temp_min = temp_min
        self.temp_max = temp_max
        self.window_seconds = window_seconds

        # Each trace is a deque of TracePoints
        self._traces: dict[str, deque[TracePoint]] = {
            name: deque() for name in self.TRACES
        }

        # Reference profile traces (static — drawn behind live traces)
        self._ref_traces: dict[str, list[TracePoint]] = {}

        self._use_celsius: bool = False

        # Charge time offset — when set, X-axis labels treat this as t=0
        self._charge_time: float | None = None

        # Event markers: list of (time, temp, short_label)
        self._event_markers: list[tuple[float, float, str]] = []

        # Inner plot area (inset from the widget rect for labels/axes)
        self._margin_left = 36
        self._margin_right = 36
        self._margin_top = 8
        self._margin_bottom = 20
        self._plot = pygame.Rect(
            self.rect.x + self._margin_left,
            self.rect.y + self._margin_top,
            self.rect.width - self._margin_left - self._margin_right,
            self.rect.height - self._margin_top - self._margin_bottom,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def use_celsius(self) -> bool:
        return self._use_celsius

    @use_celsius.setter
    def use_celsius(self, value: bool) -> None:
        self._use_celsius = value

    def clear_traces(self) -> None:
        """Clear all live trace data."""
        for d in self._traces.values():
            d.clear()

    def add_point(self, trace: str, t: float, value: float) -> None:
        """Append a data point to *trace* ('BT', 'ET', or 'RoR')."""
        if trace not in self._traces:
            return
        self._traces[trace].append(TracePoint(t, value))
        # Prune points that are too old (keep a little extra for scrolling)
        cutoff = t - self.window_seconds * 1.5
        d = self._traces[trace]
        while d and d[0].t < cutoff:
            d.popleft()

    def set_reference(self, samples: list[ProfileSample]) -> None:
        """Load a saved profile as background reference traces.

        The reference BT, ET, and RoR curves are drawn behind the live
        traces in dimmer colours so the operator can compare the current
        roast against a known-good profile.
        """
        bt_pts: list[TracePoint] = []
        et_pts: list[TracePoint] = []
        ror_pts: list[TracePoint] = []
        for s in samples:
            bt_pts.append(TracePoint(s.elapsed, s.bt))
            et_pts.append(TracePoint(s.elapsed, s.et))
            if s.ror is not None:
                ror_pts.append(TracePoint(s.elapsed, s.ror))
        self._ref_traces = {"BT": bt_pts, "ET": et_pts, "RoR": ror_pts}

    def clear_reference(self) -> None:
        """Remove the reference profile overlay."""
        self._ref_traces = {}

    @property
    def has_reference(self) -> bool:
        """True if a reference profile is loaded."""
        return bool(self._ref_traces)

    def set_charge_time(self, t: float) -> None:
        """Set the CHARGE time so X-axis labels treat it as 0:00."""
        self._charge_time = t

    def clear_charge_time(self) -> None:
        """Remove the charge time offset."""
        self._charge_time = None

    def set_events(self, events: list[tuple[float, float, str]]) -> None:
        """Set event markers on the graph.

        Parameters
        ----------
        events:
            List of (time, temp, event_type_name) tuples.
            event_type_name is mapped to a short label via EVENT_LABELS.
        """
        self._event_markers = [
            (t, temp, self.EVENT_LABELS.get(name, name[:2]))
            for t, temp, name in events
        ]

    def clear_events(self) -> None:
        """Remove all event markers."""
        self._event_markers = []

    def draw(self, surface: pygame.Surface, elapsed: float, scroll: float = 100.0) -> None:
        """Render the widget onto *surface*.

        Parameters
        ----------
        elapsed:
            Current roast elapsed time in seconds (used to anchor the X axis).
        scroll:
            Scroll position 0–100 (100 = live, 0 = beginning of roast).
        """
        self._scroll = scroll
        r = self.rect
        p = self._plot

        # Widget background
        pygame.draw.rect(surface, theme.BG, r)
        pygame.draw.rect(surface, theme.GREEN_DIM, r, 1)

        # Plot area background (slightly lighter)
        pygame.draw.rect(surface, (2, 8, 2), p)

        self._draw_grid(surface, elapsed)
        self._draw_axis_labels(surface, elapsed)
        if self._ref_traces:
            self._draw_ref_traces(surface, elapsed)
        self._draw_traces(surface, elapsed)
        self._draw_bt_projection(surface, elapsed)
        self._draw_event_markers(surface, elapsed)
        self._draw_legend(surface)

    # ------------------------------------------------------------------
    # Private drawing helpers
    # ------------------------------------------------------------------

    def _visible_range(self, elapsed: float) -> tuple[float, float]:
        """Return (t_start, t_end) for the visible window.

        The window always spans ``window_seconds``.  Before the roast
        reaches that duration, the right edge stays fixed at
        ``window_seconds`` so the projection line has room to draw.
        After that, the window scrolls with *elapsed*.

        When a charge time is set, the window anchors so that t_start
        is at minimum the charge time — preheat data scrolls off the
        left edge immediately.

        The scroll value (0–100) controls the view position when the
        roast is longer than window_seconds.  100 = live (tracking
        elapsed), 0 = back to the start.
        """
        if self._charge_time is not None:
            live_end = max(self._charge_time + self.window_seconds, elapsed)
        else:
            live_end = max(self.window_seconds, elapsed)

        # Apply scroll: interpolate between earliest possible view and live
        scroll = getattr(self, "_scroll", 100.0)
        earliest_end = self.window_seconds  # view starts at t=0
        if scroll >= 100.0 or live_end <= self.window_seconds:
            t_end = live_end
        else:
            t_end = earliest_end + (live_end - earliest_end) * (scroll / 100.0)

        t_start = t_end - self.window_seconds
        return t_start, t_end

    def _t_to_x(self, t: float, elapsed: float) -> int:
        """Convert an elapsed-seconds time to a plot X coordinate."""
        p = self._plot
        t_start, t_end = self._visible_range(elapsed)
        fraction = (t - t_start) / (t_end - t_start)
        return p.x + int(fraction * p.width)

    def _temp_to_y(self, temp: float) -> int:
        """Convert a temperature value to a plot Y coordinate."""
        p = self._plot
        fraction = (temp - self.temp_min) / (self.temp_max - self.temp_min)
        fraction = max(0.0, min(1.0, fraction))
        return p.bottom - 1 - int(fraction * (p.height - 1))

    def _ror_to_y(self, ror: float) -> int:
        """Convert a RoR value to a plot Y coordinate (secondary axis)."""
        p = self._plot
        fraction = (ror - self.ROR_MIN) / (self.ROR_MAX - self.ROR_MIN)
        fraction = max(0.0, min(1.0, fraction))
        return p.bottom - 1 - int(fraction * (p.height - 1))

    def _draw_grid(self, surface: pygame.Surface, elapsed: float) -> None:
        """Draw dotted grid lines."""
        p = self._plot

        if self._use_celsius:
            # Grid every 25 °C — iterate in C space, convert to F for pixel mapping
            c_step = 25.0
            c_min = f_to_c(self.temp_min)
            c_max = f_to_c(self.temp_max)
            c_val = (c_min // c_step + 1) * c_step
            while c_val <= c_max:
                y = self._temp_to_y(c_to_f(c_val))
                if p.top <= y <= p.bottom:
                    self._draw_dotted_hline(surface, p.x, p.right, y, theme.GRID)
                c_val += c_step
        else:
            # Horizontal temperature grid lines (every 50 °F)
            temp_step = 50.0
            temp = (self.temp_min // temp_step + 1) * temp_step
            while temp <= self.temp_max:
                y = self._temp_to_y(temp)
                if p.top <= y <= p.bottom:
                    self._draw_dotted_hline(surface, p.x, p.right, y, theme.GRID)
                temp += temp_step

        # Vertical time grid lines (every 60 s)
        t_start, t_end = self._visible_range(elapsed)
        # Align to minute boundaries
        first_minute = int(t_start / 60) * 60
        t_mark = first_minute
        while t_mark <= t_end:
            if t_mark >= t_start:
                x = self._t_to_x(t_mark, elapsed)
                if p.x <= x <= p.right:
                    self._draw_dotted_vline(surface, x, p.top, p.bottom, theme.GRID)
            t_mark += 60.0

    def _draw_dotted_hline(
        self,
        surface: pygame.Surface,
        x1: int,
        x2: int,
        y: int,
        color: tuple[int, int, int],
        dash: int = 4,
        gap: int = 4,
    ) -> None:
        x = x1
        on = True
        while x <= x2:
            if on:
                end = min(x + dash, x2 + 1)
                pygame.draw.line(surface, color, (x, y), (end - 1, y))
                x = end
            else:
                x += gap
            on = not on

    def _draw_dotted_vline(
        self,
        surface: pygame.Surface,
        x: int,
        y1: int,
        y2: int,
        color: tuple[int, int, int],
        dash: int = 4,
        gap: int = 4,
    ) -> None:
        y = y1
        on = True
        while y <= y2:
            if on:
                end = min(y + dash, y2 + 1)
                pygame.draw.line(surface, color, (x, y), (x, end - 1))
                y = end
            else:
                y += gap
            on = not on

    def _draw_dashed_line(
        self,
        surface: pygame.Surface,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        color: tuple[int, int, int],
        dash: int = 3,
        gap: int = 3,
    ) -> None:
        """Draw a dashed line between two arbitrary points."""
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length < 1:
            return
        step = dash + gap
        dist = 0.0
        while dist < length:
            seg_end = min(dist + dash, length)
            t0 = dist / length
            t1 = seg_end / length
            sx = int(x1 + dx * t0)
            sy = int(y1 + dy * t0)
            ex = int(x1 + dx * t1)
            ey = int(y1 + dy * t1)
            pygame.draw.line(surface, color, (sx, sy), (ex, ey))
            dist += step

    def _draw_bt_projection(self, surface: pygame.Surface, elapsed: float) -> None:
        """Draw a dashed projection line from the last BT point to the right edge."""
        bt_data = self._traces["BT"]
        ror_data = self._traces["RoR"]
        if not bt_data or not ror_data:
            return

        last_bt = bt_data[-1]
        last_ror = ror_data[-1].value

        # Skip if RoR is near zero (no meaningful projection)
        if abs(last_ror) < 0.1:
            return

        p = self._plot
        # Convert RoR from deg/min to deg/sec
        ror_per_sec = last_ror / 60.0

        # Project to the right edge of the visible window
        _t_start, t_end = self._visible_range(elapsed)
        dt = t_end - last_bt.t
        if dt <= 0:
            return

        projected_temp = last_bt.value + ror_per_sec * dt

        # Clamp projected temp to axis bounds and shorten line accordingly
        if last_ror > 0 and projected_temp > self.temp_max:
            dt = (self.temp_max - last_bt.value) / ror_per_sec
            projected_temp = self.temp_max
            t_end = last_bt.t + dt
        elif last_ror < 0 and projected_temp < self.temp_min:
            dt = (self.temp_min - last_bt.value) / ror_per_sec
            projected_temp = self.temp_min
            t_end = last_bt.t + dt

        x1 = self._t_to_x(last_bt.t, elapsed)
        y1 = self._temp_to_y(last_bt.value)
        x2 = self._t_to_x(t_end, elapsed)
        y2 = self._temp_to_y(projected_temp)

        # Clip to plot area
        x1 = max(p.x, min(p.right, x1))
        x2 = max(p.x, min(p.right, x2))
        y1 = max(p.top, min(p.bottom, y1))
        y2 = max(p.top, min(p.bottom, y2))

        self._draw_dashed_line(surface, x1, y1, x2, y2, theme.PROJECTION_BT)

    def _draw_axis_labels(self, surface: pygame.Surface, elapsed: float) -> None:
        p = self._plot

        if self._use_celsius:
            # Y axis labels every 50 °C
            c_step = 50.0
            c_min = f_to_c(self.temp_min)
            c_max = f_to_c(self.temp_max)
            c_val = (c_min // c_step) * c_step
            while c_val <= c_max:
                y = self._temp_to_y(c_to_f(c_val))
                if p.top <= y <= p.bottom:
                    label = str(int(c_val))
                    lw = text_width(label, scale=1)
                    render_text(
                        surface,
                        label,
                        self.rect.x + self._margin_left - lw - 2,
                        y - text_height(1) // 2,
                        theme.TEXT_DIM,
                        scale=1,
                    )
                c_val += c_step
        else:
            # Y axis temperature labels every 100 °F
            temp_step = 100.0
            temp = (self.temp_min // temp_step) * temp_step
            while temp <= self.temp_max:
                y = self._temp_to_y(temp)
                if p.top <= y <= p.bottom:
                    label = str(int(temp))
                    lw = text_width(label, scale=1)
                    render_text(
                        surface,
                        label,
                        self.rect.x + self._margin_left - lw - 2,
                        y - text_height(1) // 2,
                        theme.TEXT_DIM,
                        scale=1,
                    )
                temp += temp_step

        # X axis time labels (full visible window)
        t_start, t_end = self._visible_range(elapsed)
        offset = self._charge_time or 0.0
        first_minute = int(t_start / 60) * 60
        t_mark = first_minute
        while t_mark <= t_end:
            if t_mark >= t_start:
                display_t = t_mark - offset
                if display_t < 0:
                    t_mark += 60.0
                    continue
                x = self._t_to_x(t_mark, elapsed)
                if p.x <= x <= p.right:
                    mins = int(display_t) // 60
                    secs = int(display_t) % 60
                    label = f"{mins}:{secs:02d}"
                    lw = text_width(label, scale=1)
                    render_text(
                        surface,
                        label,
                        x - lw // 2,
                        p.bottom + 4,
                        theme.TEXT_DIM,
                        scale=1,
                    )
            t_mark += 60.0

        # Right Y-axis temperature labels
        if self._use_celsius:
            c_val = (c_min // c_step) * c_step
            while c_val <= c_max:
                y = self._temp_to_y(c_to_f(c_val))
                if p.top <= y <= p.bottom:
                    label = str(int(c_val))
                    render_text(
                        surface,
                        label,
                        p.right + 4,
                        y - text_height(1) // 2,
                        theme.TEXT_DIM,
                        scale=1,
                    )
                c_val += c_step
        else:
            temp_step = 100.0
            temp = (self.temp_min // temp_step) * temp_step
            while temp <= self.temp_max:
                y = self._temp_to_y(temp)
                if p.top <= y <= p.bottom:
                    label = str(int(temp))
                    render_text(
                        surface,
                        label,
                        p.right + 4,
                        y - text_height(1) // 2,
                        theme.TEXT_DIM,
                        scale=1,
                    )
                temp += temp_step

    def _draw_ref_traces(self, surface: pygame.Surface, elapsed: float) -> None:
        """Draw reference profile traces behind the live data."""
        p = self._plot
        clip_rect = p.inflate(-2, -2)

        for name in ("BT", "ET"):
            points_raw = self._ref_traces.get(name, [])
            if len(points_raw) < 2:
                continue
            color = self.REF_COLORS[name]
            pts: list[tuple[int, int]] = []
            for tp in points_raw:
                x = self._t_to_x(tp.t, elapsed)
                y = self._temp_to_y(tp.value)
                pts.append((x, y))
            for i in range(len(pts) - 1):
                x0, y0 = pts[i]
                x1, y1 = pts[i + 1]
                if x1 >= clip_rect.left and x0 <= clip_rect.right:
                    draw_x0 = max(x0, clip_rect.left)
                    draw_x1 = min(x1, clip_rect.right)
                    pygame.draw.line(surface, color, (draw_x0, y0), (draw_x1, y1))

        # RoR reference
        ror_pts = self._ref_traces.get("RoR", [])
        if len(ror_pts) >= 2:
            color = self.REF_COLORS["RoR"]
            for i in range(len(ror_pts) - 1):
                x0 = self._t_to_x(ror_pts[i].t, elapsed)
                y0 = self._ror_to_y(ror_pts[i].value)
                x1 = self._t_to_x(ror_pts[i + 1].t, elapsed)
                y1 = self._ror_to_y(ror_pts[i + 1].value)
                if x1 >= clip_rect.left and x0 <= clip_rect.right:
                    draw_x0 = max(x0, clip_rect.left)
                    draw_x1 = min(x1, clip_rect.right)
                    pygame.draw.line(surface, color, (draw_x0, y0), (draw_x1, y1))

    def _draw_traces(self, surface: pygame.Surface, elapsed: float) -> None:
        p = self._plot
        clip_rect = p.inflate(-2, -2)

        for name in ("BT", "ET"):
            color = self.TRACE_COLORS[name]
            points_raw = list(self._traces[name])
            if len(points_raw) < 2:
                continue
            # Build screen coords
            pts: list[tuple[int, int]] = []
            for tp in points_raw:
                x = self._t_to_x(tp.t, elapsed)
                y = self._temp_to_y(tp.value)
                pts.append((x, y))
            # Draw segment by segment, clipping to plot area
            for i in range(len(pts) - 1):
                x0, y0 = pts[i]
                x1, y1 = pts[i + 1]
                if (
                    x1 >= clip_rect.left
                    and x0 <= clip_rect.right
                ):
                    draw_x0 = max(x0, clip_rect.left)
                    draw_x1 = min(x1, clip_rect.right)
                    pygame.draw.line(surface, color, (draw_x0, y0), (draw_x1, y1))

        # RoR trace
        ror_color = self.TRACE_COLORS["RoR"]
        ror_points_raw = list(self._traces["RoR"])
        if len(ror_points_raw) >= 2:
            for i in range(len(ror_points_raw) - 1):
                x0 = self._t_to_x(ror_points_raw[i].t, elapsed)
                y0 = self._ror_to_y(ror_points_raw[i].value)
                x1 = self._t_to_x(ror_points_raw[i + 1].t, elapsed)
                y1 = self._ror_to_y(ror_points_raw[i + 1].value)
                if x1 >= clip_rect.left and x0 <= clip_rect.right:
                    draw_x0 = max(x0, clip_rect.left)
                    draw_x1 = min(x1, clip_rect.right)
                    pygame.draw.line(surface, ror_color, (draw_x0, y0), (draw_x1, y1))

    def _draw_event_markers(self, surface: pygame.Surface, elapsed: float) -> None:
        """Draw filled circles and short text labels at event positions on the BT trace."""
        if not self._event_markers:
            return
        p = self._plot
        for t, temp, label in self._event_markers:
            x = self._t_to_x(t, elapsed)
            y = self._temp_to_y(temp)
            # Clip to plot area
            if x < p.x or x > p.right or y < p.top or y > p.bottom:
                continue
            pygame.draw.circle(surface, theme.EVENT_MARKER, (x, y), 4)
            lw = text_width(label, scale=1)
            lh = text_height(1)
            lx = x - lw // 2
            ly = y - lh - 6
            # Keep label inside plot area
            lx = max(p.x, min(p.right - lw, lx))
            ly = max(p.top, ly)
            render_text(surface, label, lx, ly, theme.EVENT_MARKER, scale=1)

    def _draw_legend(self, surface: pygame.Surface) -> None:
        p = self._plot
        x = p.x + 4
        y = p.y + 4
        for name in self.TRACES:
            color = self.TRACE_COLORS[name]
            pygame.draw.line(surface, color, (x, y + 4), (x + 10, y + 4))
            render_text(surface, name, x + 13, y, color, scale=1)
            x += text_width(name, 1) + 20
        if self._ref_traces:
            label = "REF"
            render_text(surface, label, x + 4, y, theme.REF_BT, scale=1)


# ---------------------------------------------------------------------------
# NumericReadout
# ---------------------------------------------------------------------------


class NumericReadout:
    """Large numeric display: LABEL  VALUE UNIT.

    Parameters
    ----------
    rect:
        (x, y, width, height) bounding box.
    label:
        Short label string (e.g. 'BT').
    unit:
        Unit string (e.g. 'F').
    color:
        Phosphor color for this readout.
    value_scale:
        Pixel scale factor for the main number.
    """

    def __init__(
        self,
        rect: tuple[int, int, int, int],
        label: str,
        unit: str,
        color: tuple[int, int, int] = theme.TEXT,
        value_scale: int = 4,
    ) -> None:
        self.rect = pygame.Rect(rect)
        self.label = label
        self.unit = unit
        self.color = color
        self.value_scale = value_scale
        self._value: float | None = None
        self._use_celsius: bool = False
        self._dim_color = (
            max(0, color[0] // 3),
            max(0, color[1] // 3),
            max(0, color[2] // 3),
        )

    def update(self, value: float | None, *, use_celsius: bool = False) -> None:
        """Set the current numeric value (None = dashes)."""
        self._value = value
        self._use_celsius = use_celsius

    def draw(self, surface: pygame.Surface) -> None:
        r = self.rect

        # Background + border
        pygame.draw.rect(surface, theme.BG, r)
        pygame.draw.rect(surface, theme.GREEN_DIM, r, 1)

        # Label in small text – top left
        render_text(surface, self.label, r.x + 4, r.y + 4, self._dim_color, scale=1)

        # Display unit (swap F→C when in celsius mode)
        if self._use_celsius:
            display_unit = self.unit.replace("F", "C")
        else:
            display_unit = self.unit

        # Unit in small text – bottom right
        uw = text_width(display_unit, scale=1)
        render_text(
            surface,
            display_unit,
            r.right - uw - 4,
            r.bottom - text_height(1) - 4,
            self._dim_color,
            scale=1,
        )

        # Convert value for display
        display_value = self._value
        if display_value is not None and self._use_celsius:
            if "/M" in self.unit:
                display_value = f_to_c_delta(display_value)
            else:
                display_value = f_to_c(display_value)

        # Main value – large, centered
        sc = self.value_scale
        if display_value is None:
            val_str = "---"
        else:
            # Display as integer if we're ≥ 10, otherwise 1 decimal
            if abs(display_value) >= 10 or display_value == 0:
                val_str = str(int(round(display_value)))
            else:
                val_str = f"{display_value:.1f}"

        vw = text_width(val_str, scale=sc)
        vh = text_height(sc)
        vx = r.x + (r.width - vw) // 2
        vy = r.y + (r.height - vh) // 2
        render_text(surface, val_str, vx, vy, self.color, scale=sc)


# ---------------------------------------------------------------------------
# StatusBar
# ---------------------------------------------------------------------------

PHASES = ("IDLE", "PREHEAT", "ROASTING", "COOLING")


class StatusBar:
    """Horizontal status bar showing roast phase and elapsed time.

    Parameters
    ----------
    rect:
        (x, y, width, height) area.
    """

    def __init__(self, rect: tuple[int, int, int, int]) -> None:
        self.rect = pygame.Rect(rect)
        self._phase: str = "IDLE"
        self._elapsed: float = 0.0
        self._message: str = ""

    def update(self, phase: str, elapsed: float, message: str = "") -> None:
        self._phase = phase.upper()
        self._elapsed = elapsed
        self._message = message

    def draw(self, surface: pygame.Surface) -> None:
        r = self.rect
        pygame.draw.rect(surface, theme.BG, r)
        pygame.draw.rect(surface, theme.GREEN_DIM, r, 1)

        cy = r.y + (r.height - text_height(2)) // 2

        # Phase indicator with brackets
        phase_str = f"[{self._phase}]"
        render_text(surface, phase_str, r.x + 6, cy, theme.TEXT, scale=2)

        # Elapsed time – right side
        mins = int(self._elapsed) // 60
        secs = int(self._elapsed) % 60
        time_str = f"{mins:02d}:{secs:02d}"
        tw = text_width(time_str, scale=2)
        render_text(surface, time_str, r.right - tw - 6, cy, theme.TEXT, scale=2)

        # Optional centre message (scale=1)
        if self._message:
            mw = text_width(self._message, scale=1)
            mx = r.x + (r.width - mw) // 2
            my = r.y + (r.height - text_height(1)) // 2
            render_text(surface, self._message, mx, my, theme.TEXT_DIM, scale=1)

        # Separator lines top and bottom
        pygame.draw.line(surface, theme.GRID, (r.x, r.y), (r.right, r.y))
        pygame.draw.line(surface, theme.GRID, (r.x, r.bottom - 1), (r.right, r.bottom - 1))


# ---------------------------------------------------------------------------
# ControlIndicator
# ---------------------------------------------------------------------------


class ControlIndicator:
    """Bar-gauge display for burner %, drum %, air %.

    Parameters
    ----------
    rect:
        (x, y, width, height) bounding box.
    """

    CHANNELS = [
        ("BURN", theme.AMBER_BRIGHT),
        ("DRUM", theme.GREEN_MEDIUM),
        ("AIR", theme.GREEN_BRIGHT),
    ]

    def __init__(self, rect: tuple[int, int, int, int]) -> None:
        self.rect = pygame.Rect(rect)
        self._values: dict[str, float] = {"BURN": 0.0, "DRUM": 0.0, "AIR": 0.0}

    def update(self, burner: float, drum: float, air: float) -> None:
        """Set control values in the range 0.0 – 100.0."""
        self._values["BURN"] = max(0.0, min(100.0, burner))
        self._values["DRUM"] = max(0.0, min(100.0, drum))
        self._values["AIR"] = max(0.0, min(100.0, air))

    def draw(self, surface: pygame.Surface) -> None:
        r = self.rect
        pygame.draw.rect(surface, theme.BG, r)
        pygame.draw.rect(surface, theme.GREEN_DIM, r, 1)

        n = len(self.CHANNELS)
        padding = 6
        bar_height = 10
        label_w = text_width("BURN", scale=1) + 4
        value_label_w = text_width("100%", scale=1) + 4
        bar_area_w = r.width - label_w - value_label_w - padding * 3

        slot_h = (r.height - padding) // n

        for i, (name, color) in enumerate(self.CHANNELS):
            val = self._values[name]
            y_center = r.y + padding // 2 + i * slot_h + slot_h // 2

            # Label
            lx = r.x + padding
            ly = y_center - text_height(1) // 2
            render_text(surface, name, lx, ly, theme.TEXT_DIM, scale=1)

            # Bar background
            bx = r.x + label_w + padding * 2
            by = y_center - bar_height // 2
            pygame.draw.rect(surface, theme.GRID_FAINT, (bx, by, bar_area_w, bar_height))
            pygame.draw.rect(surface, theme.GRID, (bx, by, bar_area_w, bar_height), 1)

            # Filled portion
            fill_w = int(bar_area_w * val / 100.0)
            if fill_w > 0:
                pygame.draw.rect(surface, color, (bx, by, fill_w, bar_height))

            # Tick marks every 25%
            for tick_pct in (25, 50, 75):
                tx = bx + int(bar_area_w * tick_pct / 100)
                pygame.draw.line(surface, theme.GRID, (tx, by), (tx, by + bar_height - 1))

            # Numeric value
            pct_str = f"{int(val)}%"
            vx = bx + bar_area_w + padding
            vy = y_center - text_height(1) // 2
            render_text(surface, pct_str, vx, vy, color, scale=1)


# ---------------------------------------------------------------------------
# ProfileBrowser
# ---------------------------------------------------------------------------


class ProfileBrowser:
    """Full-screen overlay listing saved profiles for selection.

    The browser draws a bordered list of profile names, highlighting the
    currently selected entry. It consumes navigation events and returns
    the selected profile name when the user confirms.

    Parameters
    ----------
    rect:
        (x, y, width, height) area to draw the browser.
    """

    _VISIBLE_ROWS = 12  # how many rows visible at once (scrolls if more)
    _ROW_HEIGHT = 14     # pixels per row

    def __init__(self, rect: tuple[int, int, int, int]) -> None:
        self.rect = pygame.Rect(rect)
        self._profiles: list[str] = []
        self._cursor: int = 0
        self._scroll_offset: int = 0

    def set_profiles(self, profiles: list[str]) -> None:
        """Set the list of available profile names."""
        self._profiles = list(profiles)
        self._cursor = 0
        self._scroll_offset = 0

    @property
    def profiles(self) -> list[str]:
        return self._profiles

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def selected_name(self) -> str | None:
        """Return the currently highlighted profile name, or None if empty."""
        if not self._profiles:
            return None
        return self._profiles[self._cursor]

    def move_up(self) -> None:
        """Move the cursor up one entry."""
        if self._cursor > 0:
            self._cursor -= 1
            if self._cursor < self._scroll_offset:
                self._scroll_offset = self._cursor

    def move_down(self) -> None:
        """Move the cursor down one entry."""
        if self._cursor < len(self._profiles) - 1:
            self._cursor += 1
            if self._cursor >= self._scroll_offset + self._VISIBLE_ROWS:
                self._scroll_offset = self._cursor - self._VISIBLE_ROWS + 1

    def draw(self, surface: pygame.Surface) -> None:
        r = self.rect
        # Dark overlay background
        pygame.draw.rect(surface, theme.BG, r)
        pygame.draw.rect(surface, theme.TEXT, r, 2)

        # Title
        title = "LOAD PROFILE"
        tw = text_width(title, scale=2)
        tx = r.x + (r.width - tw) // 2
        ty = r.y + 6
        render_text(surface, title, tx, ty, theme.TEXT, scale=2)

        # Divider
        div_y = ty + text_height(2) + 4
        pygame.draw.line(surface, theme.GREEN_DIM, (r.x + 4, div_y), (r.right - 4, div_y))

        list_y = div_y + 6

        if not self._profiles:
            msg = "NO SAVED PROFILES"
            mw = text_width(msg, scale=1)
            render_text(
                surface, msg,
                r.x + (r.width - mw) // 2,
                list_y + 20,
                theme.TEXT_DIM, scale=1,
            )
        else:
            end = min(self._scroll_offset + self._VISIBLE_ROWS, len(self._profiles))
            for i in range(self._scroll_offset, end):
                row_y = list_y + (i - self._scroll_offset) * self._ROW_HEIGHT
                name = self._profiles[i]

                if i == self._cursor:
                    # Highlight bar
                    bar_rect = (r.x + 4, row_y, r.width - 8, self._ROW_HEIGHT)
                    pygame.draw.rect(surface, theme.GREEN_DIM, bar_rect)
                    prefix = "> "
                    color = theme.TEXT
                else:
                    prefix = "  "
                    color = theme.TEXT_DIM

                label = f"{prefix}{name}"
                render_text(surface, label, r.x + 8, row_y + 2, color, scale=1)

            # Scroll indicators
            if self._scroll_offset > 0:
                render_text(surface, "^", r.right - 16, list_y, theme.TEXT_DIM, scale=1)
            if end < len(self._profiles):
                bottom_y = list_y + self._VISIBLE_ROWS * self._ROW_HEIGHT
                render_text(surface, "v", r.right - 16, bottom_y - 10, theme.TEXT_DIM, scale=1)

        # Footer
        footer = "UP/DN:NAV  ENTER:LOAD  L:CANCEL"
        fw = text_width(footer, scale=1)
        fy = r.bottom - text_height(1) - 6
        render_text(surface, footer, r.x + (r.width - fw) // 2, fy, theme.TEXT_DIM, scale=1)
