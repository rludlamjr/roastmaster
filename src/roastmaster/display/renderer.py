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

Phase analysis keys
-------------------
    view          : str         – 'graph' | 'phases' | 'plan' | 'system'
    analysis      : RoastAnalysis | None – live/final phase analysis
    coffee        : str         – coffee name for the current roast
    coffee_plan   : Coffee | None – selected coffee (for the plan page)
"""

from __future__ import annotations

import pygame

from roastmaster.config import SCREEN_HEIGHT, SCREEN_WIDTH
from roastmaster.display import theme
from roastmaster.display.fonts import render_text, text_height, text_width
from roastmaster.display.units import f_to_c, f_to_c_delta
from roastmaster.display.widgets import (
    ControlIndicator,
    GraphWidget,
    NumericReadout,
    ProfileBrowser,
)
from roastmaster.engine.analysis import PlanTargets, RoastAnalysis, fmt_time
from roastmaster.profiles.coffees import rest_text
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

# Phase screen colours
_PHASE_COLORS = {
    "DRYING": theme.GREEN_DIM,
    "MAILLARD": theme.AMBER_DIM,
    "DEVELOPMENT": theme.AMBER_MEDIUM,
}
_FINDING_STYLE = {
    "bad": ("!", theme.AMBER_BRIGHT),
    "warn": ("?", theme.AMBER_MEDIUM),
    "info": ("-", theme.TEXT_DIM),
    "good": ("+", theme.TEXT),
}

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

        # -- Coffee picker overlay (same widget, different wording) --
        # Double-size text so it reads easily on the CRT from the roaster
        picker_w = SCREEN_WIDTH - 40
        picker_h = 340
        self._picker = ProfileBrowser(
            rect=((SCREEN_WIDTH - picker_w) // 2, (SCREEN_HEIGHT - picker_h) // 2,
                  picker_w, picker_h),
            title="WHICH COFFEE?",
            footer="KNOB:MOVE  PUSH:SELECT",
            empty_text="NO COFFEES",
            text_scale=2,
        )
        self._picker_visible = False

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

    @property
    def picker(self) -> ProfileBrowser:
        return self._picker

    @property
    def picker_visible(self) -> bool:
        return self._picker_visible

    def show_picker(self, labels: list[str], cursor: int = 0) -> None:
        self._picker.set_profiles(labels, cursor)
        self._picker_visible = True

    def hide_picker(self) -> None:
        self._picker_visible = False

    def set_target_plan(self, plan: PlanTargets | None) -> None:
        """Show (or clear) a coffee plan as a target curve on the graph."""
        if plan is None:
            self._graph.clear_target()
            return
        marks = []
        for label, t in (("DE", plan.dry_end_s), ("FC", plan.fc_s), ("DROP", plan.drop_s)):
            at = plan.at(t)
            if at is not None:
                marks.append((t, at[0], label))
        # RoR before the turning point is just the charge dip — don't draw it
        curve = [(t, bt, ror if t >= plan.tp_s else None) for t, bt, ror in plan.curve]
        self._graph.set_target(curve, marks, label=f"PLAN {_crt(plan.label)}".strip())

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
        scroll = float(data.get("scroll", 100.0))

        # Clear
        surface.fill(theme.BG)

        # Readouts
        self._bt_readout.update(bt, use_celsius=self._use_celsius)
        self._bt_readout.draw(surface)

        self._et_readout.update(et, use_celsius=self._use_celsius)
        self._et_readout.draw(surface)

        self._ror_readout.update(ror, use_celsius=self._use_celsius)
        self._ror_readout.draw(surface)

        # Debug overlay / phase screen replace the graph when active
        debug_visible = bool(data.get("debug_visible", False))
        debug_lines = data.get("debug_lines")
        analysis = data.get("analysis")
        if not isinstance(analysis, RoastAnalysis):
            analysis = None
        if (
            debug_visible
            and not self._browser_visible
            and isinstance(debug_lines, list)
            and debug_lines
        ):
            self._draw_full_status_screen(surface, [str(x) for x in debug_lines])
        elif data.get("view") == "phases" and not self._browser_visible:
            self._draw_phase_screen(surface, analysis, str(data.get("coffee", "")))
            if message:
                self._draw_message_overlay(surface, message)
        elif data.get("view") == "plan" and not self._browser_visible:
            self._draw_plan_page(surface, data.get("coffee_plan"))
            if message:
                self._draw_message_overlay(surface, message)
        else:
            # Graph
            self._graph.draw(surface, elapsed, scroll=scroll)

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
            self._phase_label(phase, analysis),
            float(data.get("timer", elapsed)),
            heat_enabled=(bool(heat_enabled) if heat_enabled is not None else None),
            cooling_enabled=(bool(cooling_enabled) if cooling_enabled is not None else None),
            extra=self._dev_delta_label(phase, analysis),
        )

        # Profile browser / coffee picker overlays (on top of everything)
        if self._browser_visible:
            self._browser.draw(surface)
        if self._picker_visible:
            self._picker.draw(surface)

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
        extra: str = "",
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
        if extra:
            switches_line += f"  {extra}"
        sw = text_width(switches_line, scale=1)
        sx = r.x + (r.width - sw) // 2
        render_text(surface, switches_line, sx, y, theme.TEXT_DIM, scale=1)

    # ------------------------------------------------------------------
    # Phase analysis display
    # ------------------------------------------------------------------

    @staticmethod
    def _phase_label(fsm_phase: str, a: RoastAnalysis | None) -> str:
        """Roast phase (DRYING / MAILLARD / DEV + live DTR) while roasting."""
        if a is None or not a.charged or not a.live or fsm_phase not in ("CHARGE", "ROASTING"):
            return fsm_phase
        if a.current_phase == "DEVELOPMENT" and a.dtr_pct is not None:
            return f"DEV {a.dtr_pct:.1f}%"
        return a.current_phase or fsm_phase

    def _dev_delta_label(self, fsm_phase: str, a: RoastAnalysis | None) -> str:
        if a is None or a.dev_delta_f is None or not a.live:
            return ""
        return f"DT {self._fmt_delta(a.dev_delta_f)}"

    def _fmt_temp(self, temp_f: float | None) -> str:
        if temp_f is None:
            return "--"
        if self._use_celsius:
            return f"{f_to_c(temp_f):.0f}C"
        return f"{temp_f:.0f}F"

    def _fmt_delta(self, delta_f: float | None, *, unit: bool = True) -> str:
        if delta_f is None:
            return "--"
        if self._use_celsius:
            return f"{f_to_c_delta(delta_f):.1f}" + ("C" if unit else "")
        return f"{delta_f:.1f}" + ("F" if unit else "")

    def _draw_phase_screen(
        self, surface: pygame.Surface, a: RoastAnalysis | None, coffee: str
    ) -> None:
        """Phase breakdown, development metrics and diagnostics (graph area)."""
        rect = pygame.Rect(_MARGIN, _GRAPH_TOP, SCREEN_WIDTH - _MARGIN * 2, _GRAPH_H)
        pygame.draw.rect(surface, theme.BG, rect)
        pygame.draw.rect(surface, theme.GREEN_DIM, rect, 1)
        pad = 8
        x0 = rect.x + pad
        w = rect.width - pad * 2
        y = rect.y + pad

        # Title row: PHASES  <coffee>          LIVE/FINAL
        render_text(surface, "PHASES", x0, y, theme.TEXT, scale=2)
        state = "" if a is None or not a.charged else ("LIVE" if a.live else "FINAL")
        sw = text_width(state, scale=2)
        render_text(surface, state, rect.right - pad - sw, y, theme.AMBER_BRIGHT, scale=2)
        name_x = x0 + text_width("PHASES ", scale=2)
        name_w = rect.right - pad - sw - 8 - name_x
        name = self._truncate_to_width(coffee or "NO COFFEE SET", name_w, scale=2)
        render_text(surface, name, name_x, y, theme.TEXT if coffee else theme.GREEN_DIM, scale=2)
        y += text_height(2) + 8

        footer = "PUSH:NEXT PAGE"
        fy = rect.bottom - pad - text_height(1)
        fw = text_width(footer, scale=1)
        render_text(surface, footer, rect.x + (rect.width - fw) // 2, fy, theme.GREEN_DIM, scale=1)

        if a is None or not a.charged or a.end_s <= 0:
            msg = "WAITING FOR CHARGE"
            mw = text_width(msg, scale=2)
            render_text(surface, msg, rect.x + (rect.width - mw) // 2, rect.centery - 8,
                        theme.TEXT_DIM, scale=2)
            return

        # Phase bar, proportional to time
        bar_h = 22
        bx = x0
        for i, ph in enumerate(a.phases):
            seg_w = int(round(w * ph.duration_s / a.end_s))
            if i == len(a.phases) - 1:
                seg_w = x0 + w - bx
            seg = pygame.Rect(bx, y, max(seg_w, 1), bar_h)
            pygame.draw.rect(surface, _PHASE_COLORS.get(ph.name, theme.GREEN_DIM), seg)
            pygame.draw.rect(surface, theme.TEXT_DIM, seg, 1)
            label = ph.name[:3]
            if seg_w > text_width(label, scale=1) + 4:
                render_text(surface, label, seg.x + (seg_w - text_width(label, 1)) // 2,
                            y + (bar_h - text_height(1)) // 2, theme.TEXT, scale=1)
            info = f"{fmt_time(ph.duration_s)} {ph.pct or 0:.0f}%"
            if seg_w > text_width(info, scale=1) + 2:
                render_text(surface, info, seg.x + (seg_w - text_width(info, 1)) // 2,
                            y + bar_h + 3, theme.TEXT_DIM, scale=1)
            bx += seg_w
        y += bar_h + 3 + text_height(1) + 4
        if a.plan is not None:
            pl = a.plan
            plan_line = (
                f"PLAN  DRY {fmt_time(pl.dry_end_s)}  FC {fmt_time(pl.fc_s)} "
                f"{self._fmt_temp(pl.fc_bt_f)}  DROP {fmt_time(pl.drop_s)} "
                f"{self._fmt_temp(pl.drop_bt_f)}  DTR {pl.dtr_pct:.0f}%"
            )
            render_text(surface, self._truncate_to_width(plan_line, w, scale=1), x0, y,
                        theme.TARGET_BT, scale=1)
        y += text_height(1) + 6

        # Key numbers, two columns
        end_label = "NOW" if a.live else "DROP"
        tp, de, fc = a.turning_point, a.dry_end, a.first_crack

        def ev(p) -> str:
            return f"{fmt_time(p.time_s)} {self._fmt_temp(p.bt_f)}" if p else "--"

        cells: list[tuple[str, str, str | None]] = [
            ("TOTAL", fmt_time(a.end_s), "total_time"),
            ("DTR", f"{a.dtr_pct:.1f}%" if a.dtr_pct is not None else "--", "dtr"),
            ("CHG", self._fmt_temp(a.charge_bt_f), None),
            ("DEV", fmt_time(a.dev_time_s) if a.dev_time_s is not None else "--", "dev_time"),
            ("TP", ev(tp), None),
            ("DEV DT", self._fmt_delta(a.dev_delta_f), "dev_delta"),
            ("DRY", ev(de), "drying_pct"),
            ("ROR FC", self._fmt_delta(a.ror_fc_f, unit=False), "ror_fc"),
            ("FC", ev(fc), None),
            (f"ROR {end_label}", self._fmt_delta(a.ror_end_f, unit=False), "ror_drop"),
        ]
        col_w = w // 2
        row_h = text_height(2) + 4
        for i, (label, value, key) in enumerate(cells):
            cx = x0 + (i % 2) * col_w
            cy = y + (i // 2) * row_h
            status = a.status.get(key) if key else None
            color = theme.AMBER_BRIGHT if status in ("low", "high") else theme.TEXT
            render_text(surface, label, cx, cy, theme.TEXT_DIM, scale=2)
            vw = text_width(value, scale=2)
            render_text(surface, value, cx + col_w - 12 - vw, cy, color, scale=2)
        y += (len(cells) + 1) // 2 * row_h + 2

        vs = self._vs_plan_text(a)
        if vs:
            render_text(surface, self._truncate_to_width(vs, w, scale=2), x0, y,
                        theme.TARGET_BT, scale=2)
            y += row_h

        pygame.draw.line(surface, theme.GREEN_DIM, (x0, y), (x0 + w, y))
        y += 6

        # Diagnostics, most severe first
        findings = list(a.findings)
        line_h = text_height(2) + 4
        for f in findings:
            if y + line_h > fy - 2:
                break
            mark, color = _FINDING_STYLE.get(f.level, ("-", theme.TEXT_DIM))
            text = self._truncate_to_width(f"{mark} {f.short}", w, scale=2)
            render_text(surface, text, x0, y, color, scale=2)
            y += line_h

    def _vs_plan_text(self, a: RoastAnalysis) -> str:
        """Short 'how am I doing against the plan' line."""
        if a.plan is None:
            return ""

        def secs(d: float | None) -> str:
            if d is None:
                return "--"
            return ("+" if d >= 0 else "-") + fmt_time(abs(d))

        if a.live:
            if a.bt_vs_plan_f is None:
                return ""
            bt = f_to_c_delta(a.bt_vs_plan_f) if self._use_celsius else a.bt_vs_plan_f
            text = f"VS PLAN  BT {bt:+.1f}"
            if a.ror_vs_plan_f is not None:
                ror = f_to_c_delta(a.ror_vs_plan_f) if self._use_celsius else a.ror_vs_plan_f
                text += f"  ROR {ror:+.1f}"
            return text
        return f"VS PLAN  FC {secs(a.fc_vs_plan_s)}  DROP {secs(a.drop_vs_plan_s)}"

    def _draw_plan_page(self, surface: pygame.Surface, coffee: object) -> None:
        """The selected coffee's plan: milestones and how to fly the roast."""
        rect = pygame.Rect(_MARGIN, _GRAPH_TOP, SCREEN_WIDTH - _MARGIN * 2, _GRAPH_H)
        pygame.draw.rect(surface, theme.BG, rect)
        pygame.draw.rect(surface, theme.GREEN_DIM, rect, 1)
        pad = 8
        x0, w, y = rect.x + pad, rect.width - pad * 2, rect.y + pad
        footer = "PUSH:NEXT PAGE"
        fy = rect.bottom - pad - text_height(1)
        render_text(surface, footer, rect.x + (rect.width - text_width(footer, 1)) // 2, fy,
                    theme.GREEN_DIM, scale=1)
        plan = getattr(coffee, "plan", None)
        if coffee is None or plan is None:
            msg = "NO COFFEE PLAN SELECTED"
            render_text(surface, msg, rect.x + (rect.width - text_width(msg, 2)) // 2,
                        rect.centery - 8, theme.TEXT_DIM, scale=2)
            return
        label = _crt(str(getattr(coffee, "label", "")))
        render_text(surface, self._truncate_to_width(f"PLAN  {label}", w, scale=2), x0, y,
                    theme.TARGET_BT, scale=2)
        y += text_height(2) + 8

        def t(c: float) -> str:
            return f"{c:.0f}C" if self._use_celsius else f"{c * 9 / 5 + 32:.0f}F"

        dtr = (plan.drop_s - plan.fc_s) / plan.drop_s * 100 if plan.drop_s else 0
        dev_dt = plan.drop_bt_c - plan.fc_bt_c
        cells = [
            ("PREHEAT", t(plan.preheat_sv_c)), ("CHARGE", t(plan.charge_bt_c)),
            ("TP", f"{fmt_time(plan.tp_s)} {t(plan.tp_bt_c)}"),
            ("DRY END", fmt_time(plan.dry_end_s)),
            ("FC", f"{fmt_time(plan.fc_s)} {t(plan.fc_bt_c)}"),
            ("DROP", f"{fmt_time(plan.drop_s)} {t(plan.drop_bt_c)}"),
            ("DTR", f"{dtr:.1f}%"),
            ("DEV DT", f"{dev_dt:.1f}C" if self._use_celsius else f"{dev_dt * 1.8:.1f}F"),
        ]
        col_w = w // 2
        row_h = text_height(2) + 4
        for i, (lab, val) in enumerate(cells):
            cx, cy = x0 + (i % 2) * col_w, y + (i // 2) * row_h
            render_text(surface, lab, cx, cy, theme.TEXT_DIM, scale=2)
            render_text(surface, val, cx + col_w - 12 - text_width(val, 2), cy, theme.TEXT,
                        scale=2)
        y += (len(cells) + 1) // 2 * row_h + 2
        rest = rest_text(getattr(coffee, "rest", {}) or {})
        if rest:
            render_text(surface, _crt(f"REST BEFORE ESPRESSO: {rest}"), x0, y,
                        theme.TARGET_BT, scale=1)
            y += text_height(1) + 6
        pygame.draw.line(surface, theme.GREEN_DIM, (x0, y), (x0 + w, y))
        y += 6
        line_h = text_height(1) + 4
        for step in getattr(coffee, "steps", []):
            for line in _wrap(_crt(step), w // text_width("X", 1)):
                if y + line_h > fy - 2:
                    return
                render_text(surface, line, x0, y, theme.TEXT_DIM, scale=1)
                y += line_h

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


def _crt(text: str) -> str:
    """Text the bitmap font can draw: ASCII upper case, no tildes."""
    import unicodedata

    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return ascii_text.replace("~", "").upper()


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    cur = ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = "  " + word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        lines.append(cur)
    return lines
