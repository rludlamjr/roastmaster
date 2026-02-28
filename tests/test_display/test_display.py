"""Tests for the display subsystem.

These tests run headlessly via the session-scoped `pygame_headless` fixture
defined in conftest.py, which sets SDL_VIDEODRIVER=dummy before pygame.init().
No display hardware is required.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Theme tests
# ---------------------------------------------------------------------------


class TestTheme:
    def test_green_bright_defined(self):
        from roastmaster.display import theme

        assert theme.GREEN_BRIGHT == (51, 255, 51)

    def test_green_medium_defined(self):
        from roastmaster.display import theme

        assert theme.GREEN_MEDIUM == (30, 180, 30)

    def test_green_dim_defined(self):
        from roastmaster.display import theme

        assert theme.GREEN_DIM == (15, 90, 15)

    def test_amber_bright_defined(self):
        from roastmaster.display import theme

        assert theme.AMBER_BRIGHT == (255, 176, 0)

    def test_bg_is_dark(self):
        from roastmaster.display import theme

        r, g, b = theme.BG
        assert r < 20 and g < 20 and b < 20

    def test_trace_colors_defined(self):
        from roastmaster.display import theme

        assert hasattr(theme, "TRACE_BT")
        assert hasattr(theme, "TRACE_ET")
        assert hasattr(theme, "TRACE_ROR")

    def test_grid_colors_defined(self):
        from roastmaster.display import theme

        assert hasattr(theme, "GRID")
        assert hasattr(theme, "GRID_FAINT")

    def test_reference_trace_colors_defined(self):
        from roastmaster.display import theme

        assert hasattr(theme, "REF_BT")
        assert hasattr(theme, "REF_ET")
        assert hasattr(theme, "REF_ROR")

    def test_projection_bt_color_defined(self):
        from roastmaster.display import theme

        assert theme.PROJECTION_BT == theme.AMBER_MEDIUM


# ---------------------------------------------------------------------------
# Font tests
# ---------------------------------------------------------------------------


class TestFonts:
    def test_text_width_empty(self):
        from roastmaster.display.fonts import text_width

        assert text_width("") == 0

    def test_text_width_single_char(self):
        from roastmaster.display.fonts import text_width

        # 8 pixels wide + 1 pixel gap per character
        assert text_width("A") == 9

    def test_text_width_scales(self):
        from roastmaster.display.fonts import text_width

        assert text_width("AB", scale=2) == text_width("AB", scale=1) * 2

    def test_text_height(self):
        from roastmaster.display.fonts import text_height

        assert text_height(1) == 8
        assert text_height(2) == 16
        assert text_height(3) == 24

    def test_render_text_returns_x(self, pygame_headless):
        """render_text must return an integer x-position."""
        import pygame

        from roastmaster.display.fonts import render_text

        surf = pygame.Surface((200, 50))
        result = render_text(surf, "HELLO", 0, 0, (0, 255, 0), scale=1)
        assert isinstance(result, int)
        assert result > 0

    def test_render_text_scaled(self, pygame_headless):
        """Scale=2 should advance cursor twice as far as scale=1."""
        import pygame

        from roastmaster.display.fonts import render_text

        surf = pygame.Surface((400, 100))
        x1 = render_text(surf, "AB", 0, 0, (0, 255, 0), scale=1)
        x2 = render_text(surf, "AB", 0, 20, (0, 255, 0), scale=2)
        assert x2 == x1 * 2

    def test_render_lowercase_works(self, pygame_headless):
        """Lowercase characters should render without errors."""
        import pygame

        from roastmaster.display.fonts import render_text

        surf = pygame.Surface((200, 50))
        # Should not raise
        render_text(surf, "hello", 0, 0, (0, 255, 0), scale=1)


# ---------------------------------------------------------------------------
# Widget tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pygame_surface(pygame_headless):
    """Return a 640x480 offscreen surface for widget testing.

    Depends on the session-scoped pygame_headless fixture from conftest.py
    so pygame is already initialised when this runs.
    """
    import pygame

    return pygame.Surface((640, 480))


class TestGraphWidget:
    def test_instantiation(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        assert gw is not None

    def test_add_point(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.add_point("BT", 10.0, 250.0)
        gw.add_point("ET", 10.0, 300.0)
        gw.add_point("RoR", 10.0, 5.0)
        assert len(gw._traces["BT"]) == 1
        assert len(gw._traces["ET"]) == 1
        assert len(gw._traces["RoR"]) == 1

    def test_add_invalid_trace_ignored(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        # Should not raise
        gw.add_point("INVALID", 10.0, 250.0)

    def test_draw_empty(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        # Should not raise with no data
        gw.draw(pygame_surface, elapsed=0.0)

    def test_draw_with_data(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 300, 5):
            gw.add_point("BT", float(t), 200.0 + t * 0.5)
            gw.add_point("ET", float(t), 250.0 + t * 0.3)
            gw.add_point("RoR", float(t), 8.0)
        gw.draw(pygame_surface, elapsed=300.0)

    def test_old_points_pruned(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200), window_seconds=60.0)
        # Add a lot of old data
        for t in range(0, 1000, 5):
            gw.add_point("BT", float(t), 300.0)
        # Points should be pruned to roughly 1.5 * window_seconds back from last
        assert len(gw._traces["BT"]) < 100

    def test_clear_traces(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 60, 5):
            gw.add_point("BT", float(t), 200.0 + t)
            gw.add_point("ET", float(t), 250.0 + t)
            gw.add_point("RoR", float(t), 8.0)
        assert len(gw._traces["BT"]) > 0
        gw.clear_traces()
        assert len(gw._traces["BT"]) == 0
        assert len(gw._traces["ET"]) == 0
        assert len(gw._traces["RoR"]) == 0

    def test_clear_traces_preserves_reference(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget
        from roastmaster.profiles.schema import ProfileSample

        gw = GraphWidget(rect=(0, 0, 400, 200))
        samples = [
            ProfileSample(elapsed=float(t), bt=200.0 + t, et=250.0 + t, ror=8.0)
            for t in range(10)
        ]
        gw.set_reference(samples)
        gw.add_point("BT", 0.0, 200.0)
        gw.clear_traces()
        assert len(gw._traces["BT"]) == 0
        assert gw.has_reference


class TestNumericReadout:
    def test_instantiation(self, pygame_surface):
        from roastmaster.display.widgets import NumericReadout

        nr = NumericReadout(rect=(0, 0, 100, 60), label="BT", unit="F")
        assert nr is not None

    def test_draw_with_none_value(self, pygame_surface):
        from roastmaster.display.widgets import NumericReadout

        nr = NumericReadout(rect=(0, 0, 100, 60), label="BT", unit="F")
        nr.update(None)
        nr.draw(pygame_surface)  # Should not raise

    def test_draw_with_value(self, pygame_surface):
        from roastmaster.display.widgets import NumericReadout

        nr = NumericReadout(rect=(0, 0, 100, 60), label="BT", unit="F")
        nr.update(385.0)
        nr.draw(pygame_surface)

    def test_custom_color(self, pygame_surface):
        from roastmaster.display import theme
        from roastmaster.display.widgets import NumericReadout

        nr = NumericReadout(
            rect=(0, 0, 100, 60),
            label="ROR",
            unit="F/M",
            color=theme.AMBER_BRIGHT,
        )
        nr.update(8.5)
        nr.draw(pygame_surface)

    def test_small_value_shows_decimal(self, pygame_surface):
        """Values < 10 should render with one decimal place."""
        from roastmaster.display.widgets import NumericReadout

        nr = NumericReadout(rect=(0, 0, 200, 80), label="ROR", unit="F/M", value_scale=2)
        nr.update(5.3)
        # Just ensure draw does not raise
        nr.draw(pygame_surface)


class TestStatusBar:
    def test_instantiation(self, pygame_surface):
        from roastmaster.display.widgets import StatusBar

        sb = StatusBar(rect=(0, 0, 640, 30))
        assert sb is not None

    def test_draw_idle(self, pygame_surface):
        from roastmaster.display.widgets import StatusBar

        sb = StatusBar(rect=(0, 0, 640, 30))
        sb.update("IDLE", 0.0)
        sb.draw(pygame_surface)

    def test_draw_roasting(self, pygame_surface):
        from roastmaster.display.widgets import StatusBar

        sb = StatusBar(rect=(0, 0, 640, 30))
        sb.update("ROASTING", 245.0, "FC APPROACHING")
        sb.draw(pygame_surface)

    def test_elapsed_formats_correctly(self):
        from roastmaster.display.widgets import StatusBar

        sb = StatusBar(rect=(0, 0, 640, 30))
        sb.update("ROASTING", 125.0)
        # 125 seconds = 2 minutes 5 seconds
        assert sb._elapsed == 125.0
        assert sb._phase == "ROASTING"


class TestControlIndicator:
    def test_instantiation(self, pygame_surface):
        from roastmaster.display.widgets import ControlIndicator

        ci = ControlIndicator(rect=(0, 0, 300, 60))
        assert ci is not None

    def test_draw_zero(self, pygame_surface):
        from roastmaster.display.widgets import ControlIndicator

        ci = ControlIndicator(rect=(0, 0, 300, 60))
        ci.update(0.0, 0.0, 0.0)
        ci.draw(pygame_surface)

    def test_draw_full(self, pygame_surface):
        from roastmaster.display.widgets import ControlIndicator

        ci = ControlIndicator(rect=(0, 0, 300, 60))
        ci.update(100.0, 100.0, 100.0)
        ci.draw(pygame_surface)

    def test_values_clamped(self):
        from roastmaster.display.widgets import ControlIndicator

        ci = ControlIndicator(rect=(0, 0, 300, 60))
        ci.update(200.0, -50.0, 75.0)
        assert ci._values["BURN"] == 100.0
        assert ci._values["DRUM"] == 0.0
        assert ci._values["AIR"] == 75.0


# ---------------------------------------------------------------------------
# Renderer tests
# ---------------------------------------------------------------------------


class TestGraphReferenceTrace:
    """Tests for Plan 7.3: reference profile trace overlay."""

    def _make_samples(self, n: int = 60) -> list:
        from roastmaster.profiles.schema import ProfileSample

        return [
            ProfileSample(
                elapsed=float(t),
                bt=200.0 + t * 0.8,
                et=250.0 + t * 0.5,
                ror=8.0 if t > 5 else None,
            )
            for t in range(n)
        ]

    def test_set_reference_populates_traces(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        samples = self._make_samples(30)
        gw.set_reference(samples)
        assert gw.has_reference
        assert len(gw._ref_traces["BT"]) == 30
        assert len(gw._ref_traces["ET"]) == 30
        # RoR: first 6 samples have None ror, so only 24 points
        assert len(gw._ref_traces["RoR"]) == 24

    def test_clear_reference(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_reference(self._make_samples(10))
        assert gw.has_reference
        gw.clear_reference()
        assert not gw.has_reference
        assert gw._ref_traces == {}

    def test_has_reference_false_by_default(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        assert not gw.has_reference

    def test_draw_with_reference_does_not_raise(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_reference(self._make_samples(60))
        # Also add some live data
        for t in range(0, 30):
            gw.add_point("BT", float(t), 210.0 + t)
            gw.add_point("ET", float(t), 260.0 + t)
        gw.draw(pygame_surface, elapsed=30.0)

    def test_draw_reference_only_no_live_data(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_reference(self._make_samples(60))
        gw.draw(pygame_surface, elapsed=0.0)

    def test_set_reference_replaces_previous(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_reference(self._make_samples(20))
        assert len(gw._ref_traces["BT"]) == 20
        gw.set_reference(self._make_samples(40))
        assert len(gw._ref_traces["BT"]) == 40

    def test_ref_trace_values_correct(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget
        from roastmaster.profiles.schema import ProfileSample

        samples = [
            ProfileSample(elapsed=0.0, bt=200.0, et=250.0, ror=5.0),
            ProfileSample(elapsed=10.0, bt=210.0, et=260.0, ror=6.0),
        ]
        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_reference(samples)
        assert gw._ref_traces["BT"][0].t == 0.0
        assert gw._ref_traces["BT"][0].value == 200.0
        assert gw._ref_traces["BT"][1].value == 210.0
        assert gw._ref_traces["RoR"][1].value == 6.0


class TestBTProjection:
    """Tests for BT projection line drawing."""

    def test_draw_with_bt_and_ror_data(self, pygame_surface):
        """Projection line draws when both BT and RoR data are present."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 120, 5):
            gw.add_point("BT", float(t), 200.0 + t * 0.5)
            gw.add_point("RoR", float(t), 10.0)
        gw.draw(pygame_surface, elapsed=120.0)

    def test_no_crash_without_ror(self, pygame_surface):
        """No crash when RoR trace is empty."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 60, 5):
            gw.add_point("BT", float(t), 200.0 + t)
        gw.draw(pygame_surface, elapsed=60.0)

    def test_no_crash_without_bt(self, pygame_surface):
        """No crash when BT trace is empty."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 60, 5):
            gw.add_point("RoR", float(t), 10.0)
        gw.draw(pygame_surface, elapsed=60.0)

    def test_zero_ror_skips_projection(self, pygame_surface):
        """Near-zero RoR should skip drawing projection."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 60, 5):
            gw.add_point("BT", float(t), 300.0)
            gw.add_point("RoR", float(t), 0.0)
        gw.draw(pygame_surface, elapsed=60.0)

    def test_negative_ror(self, pygame_surface):
        """Negative RoR should project downward without error."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 60, 5):
            gw.add_point("BT", float(t), 400.0 - t * 0.5)
            gw.add_point("RoR", float(t), -5.0)
        gw.draw(pygame_surface, elapsed=60.0)

    def test_clamp_at_temp_max(self, pygame_surface):
        """Projection line should clamp at temp_max, not extend beyond."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200), temp_max=500.0)
        gw.add_point("BT", 0.0, 490.0)
        gw.add_point("BT", 5.0, 495.0)
        gw.add_point("RoR", 0.0, 60.0)
        gw.add_point("RoR", 5.0, 60.0)
        gw.draw(pygame_surface, elapsed=5.0)


class TestVisibleWindow:
    """Tests for the fixed-width visible window and right-axis labels."""

    def test_right_margin_value(self, pygame_surface):
        """Right margin should be 36 to accommodate temperature labels."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        assert gw._margin_right == 36

    def test_visible_range_early(self, pygame_surface):
        """Before window_seconds, right edge stays at window_seconds."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200), window_seconds=600.0)
        t_start, t_end = gw._visible_range(120.0)
        assert t_start == 0.0
        assert t_end == 600.0

    def test_visible_range_scrolls(self, pygame_surface):
        """After window_seconds, the window scrolls with elapsed."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200), window_seconds=600.0)
        t_start, t_end = gw._visible_range(720.0)
        assert t_start == 120.0
        assert t_end == 720.0

    def test_draw_with_right_labels(self, pygame_surface):
        """Drawing with data should render right-axis temp labels without error."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 60, 5):
            gw.add_point("BT", float(t), 200.0 + t)
            gw.add_point("RoR", float(t), 10.0)
        gw.draw(pygame_surface, elapsed=60.0)


class TestRendererReferenceProfile:
    """Tests for reference profile wiring through Renderer."""

    def test_set_reference_profile(self, pygame_surface):
        from roastmaster.display.renderer import Renderer
        from roastmaster.profiles.schema import ProfileSample

        r = Renderer(surface=pygame_surface)
        samples = [
            ProfileSample(elapsed=float(t), bt=200.0 + t, et=250.0 + t, ror=8.0)
            for t in range(30)
        ]
        r.set_reference_profile(samples)
        assert r._graph.has_reference

    def test_clear_reference_profile(self, pygame_surface):
        from roastmaster.display.renderer import Renderer
        from roastmaster.profiles.schema import ProfileSample

        r = Renderer(surface=pygame_surface)
        samples = [
            ProfileSample(elapsed=float(t), bt=200.0 + t, et=250.0 + t)
            for t in range(10)
        ]
        r.set_reference_profile(samples)
        assert r._graph.has_reference
        r.clear_reference_profile()
        assert not r._graph.has_reference

    def test_render_with_reference_profile(self, pygame_surface):
        from roastmaster.display.renderer import Renderer
        from roastmaster.profiles.schema import ProfileSample

        r = Renderer(surface=pygame_surface)
        samples = [
            ProfileSample(elapsed=float(t), bt=200.0 + t, et=250.0 + t, ror=8.0)
            for t in range(60)
        ]
        r.set_reference_profile(samples)
        r.render({
            "elapsed": 30.0,
            "bt": 230.0,
            "et": 280.0,
            "ror": 8.0,
            "phase": "ROASTING",
            "burner": 70.0,
            "drum": 60.0,
            "air": 30.0,
        })


class TestProfileBrowser:
    """Tests for the profile browser widget (Plan 7.4)."""

    def test_instantiation(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        assert pb is not None

    def test_set_profiles(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.set_profiles(["roast_a", "roast_b", "roast_c"])
        assert pb.profiles == ["roast_a", "roast_b", "roast_c"]
        assert pb.cursor == 0

    def test_selected_name_empty(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        assert pb.selected_name is None

    def test_selected_name(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.set_profiles(["alpha", "beta"])
        assert pb.selected_name == "alpha"

    def test_move_down(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.set_profiles(["a", "b", "c"])
        pb.move_down()
        assert pb.cursor == 1
        assert pb.selected_name == "b"

    def test_move_up(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.set_profiles(["a", "b", "c"])
        pb.move_down()
        pb.move_down()
        pb.move_up()
        assert pb.cursor == 1

    def test_move_up_at_top_stays(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.set_profiles(["a", "b"])
        pb.move_up()
        assert pb.cursor == 0

    def test_move_down_at_bottom_stays(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.set_profiles(["a", "b"])
        pb.move_down()
        pb.move_down()  # already at bottom
        assert pb.cursor == 1

    def test_draw_empty_list(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.draw(pygame_surface)  # Should not raise

    def test_draw_with_profiles(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.set_profiles(["ethiopia_natural", "colombia_washed", "kenya_aa"])
        pb.move_down()
        pb.draw(pygame_surface)

    def test_set_profiles_resets_cursor(self, pygame_surface):
        from roastmaster.display.widgets import ProfileBrowser

        pb = ProfileBrowser(rect=(0, 0, 400, 300))
        pb.set_profiles(["a", "b", "c"])
        pb.move_down()
        pb.move_down()
        pb.set_profiles(["x", "y"])
        assert pb.cursor == 0


class TestRendererBrowser:
    """Tests for browser overlay in Renderer."""

    def test_browser_hidden_by_default(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        assert not r.browser_visible

    def test_show_browser(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.show_browser(["roast_a", "roast_b"])
        assert r.browser_visible
        assert r.browser.profiles == ["roast_a", "roast_b"]

    def test_hide_browser(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.show_browser(["roast_a"])
        r.hide_browser()
        assert not r.browser_visible

    def test_render_with_browser_visible(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.show_browser(["alpha", "beta", "gamma"])
        r.render({"elapsed": 60.0, "phase": "IDLE"})


class TestRenderer:
    def test_instantiation(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        assert r is not None

    def test_render_empty_data(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.render({})  # Should not raise

    def test_render_full_data(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        data = {
            "bt": 350.0,
            "et": 400.0,
            "ror": 12.5,
            "elapsed": 180.0,
            "phase": "ROASTING",
            "burner": 70.0,
            "drum": 60.0,
            "air": 30.0,
            "message": "DRYING",
        }
        r.render(data)

    def test_push_data_then_render(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        for t in range(0, 120, 10):
            r.push_data(
                {
                    "elapsed": float(t),
                    "bt": 200.0 + t,
                    "et": 250.0 + t,
                    "ror": 5.0,
                }
            )
        r.render(
            {
                "elapsed": 120.0,
                "bt": 320.0,
                "et": 370.0,
                "ror": 5.0,
                "phase": "ROASTING",
                "burner": 65.0,
                "drum": 60.0,
                "air": 25.0,
            }
        )

    def test_custom_window_seconds(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface, window_seconds=300.0)
        assert r._graph.window_seconds == 300.0

    def test_render_none_values(self, pygame_surface):
        """Rendering with bt/et/ror as None should not raise."""
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.render(
            {
                "bt": None,
                "et": None,
                "ror": None,
                "elapsed": 0.0,
                "phase": "IDLE",
                "burner": 0.0,
                "drum": 0.0,
                "air": 0.0,
            }
        )

    def test_reset_graph(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        for t in range(0, 30, 5):
            r.push_data({"elapsed": float(t), "bt": 200.0 + t, "et": 250.0 + t, "ror": 5.0})
        assert len(r._graph._traces["BT"]) > 0
        r.reset_graph()
        assert len(r._graph._traces["BT"]) == 0
        # Render after reset should not raise
        r.render({"elapsed": 0.0, "phase": "IDLE"})


class TestUnitToggle:
    """Tests for Fahrenheit / Celsius display toggle."""

    def test_renderer_defaults_to_celsius(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        assert r.use_celsius is True

    def test_toggle_units_returns_label(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        # Default is celsius, toggling should switch to F
        assert r.toggle_units() == "F"
        assert r.toggle_units() == "C"

    def test_graph_use_celsius_synced(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        assert r._graph.use_celsius is True
        r.toggle_units()
        assert r._graph.use_celsius is False
        r.toggle_units()
        assert r._graph.use_celsius is True

    def test_render_in_celsius_mode(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        # Default is celsius
        r.render({
            "elapsed": 60.0,
            "bt": 350.0,
            "et": 400.0,
            "ror": 12.0,
            "phase": "ROASTING",
            "burner": 50.0,
            "drum": 50.0,
            "air": 50.0,
        })

    def test_render_in_fahrenheit_mode(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.toggle_units()  # switch to F
        r.render({
            "elapsed": 60.0,
            "bt": 350.0,
            "et": 400.0,
            "ror": 12.0,
            "phase": "ROASTING",
            "burner": 50.0,
            "drum": 50.0,
            "air": 50.0,
        })

    def test_numeric_readout_celsius(self, pygame_surface):
        from roastmaster.display.widgets import NumericReadout

        nr = NumericReadout(rect=(0, 0, 100, 60), label="BT", unit="F")
        nr.update(212.0, use_celsius=True)
        nr.draw(pygame_surface)  # Should not raise


# ---------------------------------------------------------------------------
# Charge time offset tests
# ---------------------------------------------------------------------------


class TestChargeTimeOffset:
    def test_charge_time_none_by_default(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        assert gw._charge_time is None

    def test_set_charge_time(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_charge_time(120.0)
        assert gw._charge_time == 120.0

    def test_clear_charge_time(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_charge_time(120.0)
        gw.clear_charge_time()
        assert gw._charge_time is None

    def test_visible_range_before_charge(self, pygame_surface):
        """Without charge time, visible range behaves as before."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200), window_seconds=600.0)
        t_start, t_end = gw._visible_range(120.0)
        assert t_start == 0.0
        assert t_end == 600.0

    def test_visible_range_after_charge(self, pygame_surface):
        """With charge time set, t_start anchors at charge_time."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200), window_seconds=600.0)
        gw.set_charge_time(120.0)
        t_start, t_end = gw._visible_range(200.0)
        # t_end = max(120 + 600, 200) = 720
        assert t_end == 720.0
        assert t_start == 120.0

    def test_visible_range_scrolls_after_charge(self, pygame_surface):
        """After elapsed exceeds charge_time + window, window scrolls."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200), window_seconds=600.0)
        gw.set_charge_time(60.0)
        t_start, t_end = gw._visible_range(900.0)
        # t_end = max(60 + 600, 900) = 900
        assert t_end == 900.0
        assert t_start == 300.0

    def test_draw_with_charge_time(self, pygame_surface):
        """Drawing with charge time set should not crash."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_charge_time(60.0)
        for t in range(0, 120, 5):
            gw.add_point("BT", float(t), 200.0 + t)
        gw.draw(pygame_surface, elapsed=120.0)


# ---------------------------------------------------------------------------
# Event marker tests
# ---------------------------------------------------------------------------


class TestEventMarkers:
    def test_no_markers_by_default(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        assert gw._event_markers == []

    def test_set_events(self, pygame_surface):
        """set_events maps event type names to short labels."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_events([
            (60.0, 200.0, "CHARGE"),
            (180.0, 350.0, "FIRST_CRACK"),
        ])
        assert len(gw._event_markers) == 2
        assert gw._event_markers[0] == (60.0, 200.0, "CH")
        assert gw._event_markers[1] == (180.0, 350.0, "FC")

    def test_clear_events(self, pygame_surface):
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_events([(60.0, 200.0, "CHARGE")])
        gw.clear_events()
        assert gw._event_markers == []

    def test_draw_with_event_markers(self, pygame_surface):
        """Drawing with event markers should not crash."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        for t in range(0, 300, 5):
            gw.add_point("BT", float(t), 200.0 + t * 0.5)
        gw.set_events([
            (60.0, 230.0, "CHARGE"),
            (180.0, 290.0, "FIRST_CRACK"),
        ])
        gw.draw(pygame_surface, elapsed=300.0)

    def test_draw_markers_outside_range(self, pygame_surface):
        """Markers outside visible range should not crash."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200), window_seconds=60.0)
        gw.set_events([(1000.0, 400.0, "DROP")])
        gw.draw(pygame_surface, elapsed=30.0)

    def test_event_label_mapping(self, pygame_surface):
        """All standard event types map to correct short labels."""
        from roastmaster.display.widgets import GraphWidget

        gw = GraphWidget(rect=(0, 0, 400, 200))
        gw.set_events([
            (10.0, 200.0, "CHARGE"),
            (30.0, 190.0, "TURNING_POINT"),
            (180.0, 350.0, "FIRST_CRACK"),
            (240.0, 400.0, "SECOND_CRACK"),
            (300.0, 410.0, "DROP"),
        ])
        labels = [m[2] for m in gw._event_markers]
        assert labels == ["CH", "TP", "FC", "SC", "DR"]


# ---------------------------------------------------------------------------
# Renderer charge time tests
# ---------------------------------------------------------------------------


class TestRendererChargeTime:
    def test_set_charge_time(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.set_charge_time(90.0)
        assert r._graph._charge_time == 90.0

    def test_clear_charge_time(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.set_charge_time(90.0)
        r.clear_charge_time()
        assert r._graph._charge_time is None

    def test_reset_graph_clears_charge_time(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.set_charge_time(90.0)
        r.reset_graph()
        assert r._graph._charge_time is None


# ---------------------------------------------------------------------------
# Renderer event marker tests
# ---------------------------------------------------------------------------


class TestRendererEventMarkers:
    def test_set_events(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.set_events([(60.0, 200.0, "CHARGE")])
        assert len(r._graph._event_markers) == 1
        assert r._graph._event_markers[0][2] == "CH"

    def test_clear_events(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.set_events([(60.0, 200.0, "CHARGE")])
        r.clear_events()
        assert r._graph._event_markers == []

    def test_reset_graph_clears_events(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.set_events([(60.0, 200.0, "CHARGE")])
        r.reset_graph()
        assert r._graph._event_markers == []


# ---------------------------------------------------------------------------
# Full-screen status / debug overlay tests
# ---------------------------------------------------------------------------


class TestFullStatusScreen:
    """Tests for the CRT-reworked full-screen debug overlay."""

    def test_render_with_debug_overlay(self, pygame_surface):
        """Debug overlay should render without error."""
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.render({
            "elapsed": 60.0,
            "phase": "ROASTING",
            "burner": 50.0,
            "drum": 50.0,
            "air": 50.0,
            "debug_visible": True,
            "debug_lines": [
                "DEV: SIM",
                "CONN: ONLINE",
                "MODE: MANUAL",
                "HEAT: OFF",
                "COOL: OFF",
                "ERRS: 0",
                "BT: 200.0F",
                "ET: 250.0F",
            ],
        })

    def test_debug_replaces_graph(self, pygame_surface):
        """When debug is visible, graph is not drawn (no crash)."""
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        for t in range(0, 60, 5):
            r.push_data({"elapsed": float(t), "bt": 200.0 + t, "et": 250.0, "ror": 5.0})
        r.render({
            "elapsed": 60.0,
            "phase": "IDLE",
            "debug_visible": True,
            "debug_lines": ["LINE 1", "LINE 2"],
        })

    def test_debug_hidden_shows_graph(self, pygame_surface):
        """When debug is not visible, graph renders normally."""
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.render({
            "elapsed": 10.0,
            "phase": "IDLE",
            "debug_visible": False,
            "debug_lines": ["SHOULD NOT SHOW"],
        })

    def test_debug_many_lines_truncated(self, pygame_surface):
        """More lines than fit should not crash (lines are clipped)."""
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.render({
            "elapsed": 0.0,
            "phase": "IDLE",
            "debug_visible": True,
            "debug_lines": [f"LINE {i}" for i in range(30)],
        })


class TestMessageOverlay:
    """Tests for the flash message overlay on the graph area."""

    def test_render_with_message(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.render({
            "elapsed": 60.0,
            "phase": "ROASTING",
            "burner": 50.0,
            "drum": 50.0,
            "air": 50.0,
            "message": "CHARGE MARKED",
        })

    def test_render_empty_message_no_overlay(self, pygame_surface):
        from roastmaster.display.renderer import Renderer

        r = Renderer(surface=pygame_surface)
        r.render({
            "elapsed": 60.0,
            "phase": "IDLE",
            "message": "",
        })
