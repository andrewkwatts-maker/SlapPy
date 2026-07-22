"""Tests for :mod:`pharos_engine.ui.editor.notebook_snap_overlay`.

The overlay is draw-list agnostic — every test drives it with a recording
:class:`_MockDrawList` instead of Dear PyGui so the contract runs
headless. A single ``dpg.create_context`` fixture is provided for
compatibility with the parallel V-batch tests that share the same
harness; individual tests do not depend on a live DPG context.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pharos_engine.ui.editor.notebook_snap_overlay import (
    NotebookSnapOverlay,
    SnapGhost,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def dpg_context():
    """Provide a shared DPG context if the library is available.

    The overlay itself does not require DPG — but the sprint brief pins
    the fixture so future integration tests can share the same session.
    Falls back to a no-op object when Dear PyGui is not installed on the
    test box (headless CI without an editor extra).
    """
    try:
        import dearpygui.dearpygui as dpg
    except Exception:
        yield None
        return
    try:
        dpg.create_context()
    except Exception:
        yield None
        return
    try:
        yield dpg
    finally:
        try:
            dpg.destroy_context()
        except Exception:
            pass


@dataclass
class _MockDrawList:
    """Recording drawlist mock — captures every ``add_line`` invocation."""

    lines: list[tuple[
        tuple[float, float], tuple[float, float],
        tuple[int, int, int, int], float,
    ]] = field(default_factory=list)

    def add_line(
        self,
        p0: tuple[float, float],
        p1: tuple[float, float],
        *,
        color: tuple[int, int, int, int],
        thickness: float,
    ) -> None:
        self.lines.append((tuple(p0), tuple(p1), tuple(color), float(thickness)))


@dataclass
class _FakeManager:
    """Fake snap / dock manager without a callback slot."""

    on_snap_preview: Any = None
    on_dock_preview: Any = None


# ---------------------------------------------------------------------------
# SnapGhost construction
# ---------------------------------------------------------------------------


class TestSnapGhost:
    def test_construct_valid_edge(self) -> None:
        g = SnapGhost(rect=(10, 20, 100, 50), snap_kind="edge")
        assert g.rect == (10, 20, 100, 50)
        assert g.snap_kind == "edge"
        assert g.theme_color[3] > 0

    def test_construct_all_dock_kinds(self) -> None:
        for kind in (
            "dock_left", "dock_right",
            "dock_top", "dock_bottom", "dock_center",
        ):
            g = SnapGhost(rect=(0, 0, 100, 100), snap_kind=kind)
            assert g.snap_kind == kind

    def test_construct_grid_kind(self) -> None:
        g = SnapGhost(rect=(0, 0, 10, 10), snap_kind="grid")
        assert g.snap_kind == "grid"

    def test_reject_bad_rect_type(self) -> None:
        with pytest.raises(TypeError):
            SnapGhost(rect="not-a-tuple", snap_kind="edge")  # type: ignore[arg-type]

    def test_reject_wrong_arity_rect(self) -> None:
        with pytest.raises(TypeError):
            SnapGhost(rect=(10, 20, 30), snap_kind="edge")  # type: ignore[arg-type]

    def test_reject_unknown_snap_kind(self) -> None:
        with pytest.raises(ValueError):
            SnapGhost(rect=(0, 0, 1, 1), snap_kind="floating")

    def test_reject_bad_color(self) -> None:
        with pytest.raises(TypeError):
            SnapGhost(rect=(0, 0, 1, 1), snap_kind="edge",
                      theme_color="red")  # type: ignore[arg-type]

    def test_theme_color_defaults_alpha_when_rgb_only(self) -> None:
        g = SnapGhost(
            rect=(0, 0, 1, 1),
            snap_kind="edge",
            theme_color=(255, 128, 32),  # type: ignore[arg-type]
        )
        assert len(g.theme_color) == 4
        assert g.theme_color[3] == 220


# ---------------------------------------------------------------------------
# Overlay state
# ---------------------------------------------------------------------------


class TestOverlayState:
    def test_construct(self, dpg_context) -> None:
        overlay = NotebookSnapOverlay()
        assert overlay.ghosts == []

    def test_set_ghosts_replaces(self, dpg_context) -> None:
        overlay = NotebookSnapOverlay()
        overlay.set_ghosts([
            SnapGhost(rect=(0, 0, 10, 10), snap_kind="edge"),
        ])
        assert len(overlay.ghosts) == 1
        overlay.set_ghosts([
            SnapGhost(rect=(100, 100, 20, 20), snap_kind="grid"),
            SnapGhost(rect=(200, 200, 30, 30), snap_kind="edge"),
        ])
        assert len(overlay.ghosts) == 2

    def test_clear_hides_all(self, dpg_context) -> None:
        overlay = NotebookSnapOverlay()
        overlay.set_ghosts([
            SnapGhost(rect=(0, 0, 10, 10), snap_kind="edge"),
        ])
        overlay.clear()
        assert overlay.ghosts == []

    def test_set_ghosts_rejects_non_snap_ghost(self, dpg_context) -> None:
        overlay = NotebookSnapOverlay()
        with pytest.raises(TypeError):
            overlay.set_ghosts(["not-a-ghost"])  # type: ignore[list-item]

    def test_set_ghosts_accepts_generator(self, dpg_context) -> None:
        overlay = NotebookSnapOverlay()
        overlay.set_ghosts(
            SnapGhost(rect=(i, i, 5, 5), snap_kind="edge") for i in range(3)
        )
        assert len(overlay.ghosts) == 3


# ---------------------------------------------------------------------------
# Manager attachment
# ---------------------------------------------------------------------------


class TestSnapManagerAttach:
    def test_attach_calls_callback_when_slot_missing(self, dpg_context) -> None:
        mgr = _FakeManager()
        overlay = NotebookSnapOverlay()
        overlay.attach_to_snap_manager(mgr)

        # Slot must now exist and be a list-of-callbacks.
        assert isinstance(mgr.on_snap_preview, list)
        assert len(mgr.on_snap_preview) == 1

        # Simulate a snap preview fan-out.
        ghosts = [SnapGhost(rect=(1, 2, 3, 4), snap_kind="edge")]
        for cb in mgr.on_snap_preview:
            cb(ghosts)
        assert len(overlay.ghosts) == 1

    def test_attach_appends_to_existing_list_slot(self, dpg_context) -> None:
        mgr = _FakeManager(on_snap_preview=[])
        overlay = NotebookSnapOverlay()
        overlay.attach_to_snap_manager(mgr)
        assert len(mgr.on_snap_preview) == 1

    def test_attach_wraps_bare_callable_slot(self, dpg_context) -> None:
        called: list[Any] = []

        def prev_cb(ghosts):
            called.append(ghosts)

        mgr = _FakeManager(on_snap_preview=prev_cb)
        overlay = NotebookSnapOverlay()
        overlay.attach_to_snap_manager(mgr)
        # Manager now has a fan-out list containing the previous
        # subscriber PLUS the overlay's callback.
        assert isinstance(mgr.on_snap_preview, list)
        assert len(mgr.on_snap_preview) == 2

    def test_attach_dock_installs_slot(self, dpg_context) -> None:
        mgr = _FakeManager()
        overlay = NotebookSnapOverlay()
        overlay.attach_to_dock_manager(mgr)
        assert isinstance(mgr.on_dock_preview, list)
        ghosts = [SnapGhost(rect=(0, 0, 10, 10), snap_kind="dock_left")]
        for cb in mgr.on_dock_preview:
            cb(ghosts)
        assert overlay.ghosts[0].snap_kind == "dock_left"

    def test_detach_clears_subscriptions(self, dpg_context) -> None:
        mgr = _FakeManager()
        overlay = NotebookSnapOverlay()
        overlay.attach_to_snap_manager(mgr)
        overlay.detach()
        assert mgr.on_snap_preview == [] or mgr.on_snap_preview is None

    def test_none_ghosts_clears(self, dpg_context) -> None:
        mgr = _FakeManager()
        overlay = NotebookSnapOverlay()
        overlay.set_ghosts([SnapGhost(rect=(0, 0, 1, 1), snap_kind="edge")])
        overlay.attach_to_snap_manager(mgr)
        for cb in mgr.on_snap_preview:
            cb(None)
        assert overlay.ghosts == []


# ---------------------------------------------------------------------------
# Dashed rect helper
# ---------------------------------------------------------------------------


class TestDashedRect:
    def test_forty_by_forty_yields_at_least_four_segments_per_side(
        self, dpg_context,
    ) -> None:
        mock = _MockDrawList()
        # Use the class-bound helper — the brief calls out the exact API.
        n = NotebookSnapOverlay._draw_dashed_rect(
            mock, 0.0, 0.0, 40.0, 40.0, (255, 0, 0, 255),
        )
        assert n >= 16, f"expected >= 16 total dashes, got {n}"

    def test_dashes_are_lines(self, dpg_context) -> None:
        mock = _MockDrawList()
        NotebookSnapOverlay._draw_dashed_rect(
            mock, 0.0, 0.0, 40.0, 40.0, (255, 0, 0, 255),
        )
        assert len(mock.lines) >= 16
        # Every segment is a 2-point line.
        for p0, p1, color, thickness in mock.lines:
            assert len(p0) == 2 and len(p1) == 2
            assert color == (255, 0, 0, 255)

    def test_zero_jitter_produces_axis_aligned_segments(
        self, dpg_context,
    ) -> None:
        mock = _MockDrawList()
        NotebookSnapOverlay._draw_dashed_rect(
            mock, 0.0, 0.0, 40.0, 40.0, (255, 0, 0, 255),
            jitter=0.0,
        )
        # With zero jitter, every top-edge segment should sit exactly on y=0.
        top_ys = [p[1] for line in mock.lines for p in (line[0], line[1])
                  if abs(p[1]) < 0.5]
        assert len(top_ys) >= 8


# ---------------------------------------------------------------------------
# Dock arrow helper
# ---------------------------------------------------------------------------


class TestDockArrow:
    def test_left_arrow_points_left(self, dpg_context) -> None:
        mock = _MockDrawList()
        pts = NotebookSnapOverlay._draw_dock_arrow(
            mock, 100.0, 100.0, "left", (0, 0, 0, 255),
        )
        # Tail is on the right of tip for a left-pointing arrow.
        tail, _shaft_end, _hl, tip, _hr = pts
        assert tail[0] > tip[0], f"tail {tail} should be right of tip {tip}"

    def test_right_arrow_points_right(self, dpg_context) -> None:
        mock = _MockDrawList()
        pts = NotebookSnapOverlay._draw_dock_arrow(
            mock, 100.0, 100.0, "right", (0, 0, 0, 255),
        )
        tail, _shaft_end, _hl, tip, _hr = pts
        assert tail[0] < tip[0]

    def test_up_arrow_points_up(self, dpg_context) -> None:
        mock = _MockDrawList()
        pts = NotebookSnapOverlay._draw_dock_arrow(
            mock, 100.0, 100.0, "up", (0, 0, 0, 255),
        )
        tail, _shaft_end, _hl, tip, _hr = pts
        # y increases downward on the drawlist, so "up" → tip has smaller y.
        assert tip[1] < tail[1]

    def test_down_arrow_points_down(self, dpg_context) -> None:
        mock = _MockDrawList()
        pts = NotebookSnapOverlay._draw_dock_arrow(
            mock, 100.0, 100.0, "down", (0, 0, 0, 255),
        )
        tail, _shaft_end, _hl, tip, _hr = pts
        assert tip[1] > tail[1]

    def test_arrow_returns_five_vertices(self, dpg_context) -> None:
        mock = _MockDrawList()
        pts = NotebookSnapOverlay._draw_dock_arrow(
            mock, 100.0, 100.0, "right", (0, 0, 0, 255),
        )
        assert len(pts) == 5

    def test_center_arrow_uses_cross(self, dpg_context) -> None:
        mock = _MockDrawList()
        pts = NotebookSnapOverlay._draw_dock_arrow(
            mock, 100.0, 100.0, "center", (0, 0, 0, 255),
        )
        # Centre arrow emits 2 lines (vertical + horizontal cross).
        assert len(mock.lines) == 2
        assert pts[0] == (100.0, 100.0)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


class TestRender:
    def test_render_empty_is_zero(self, dpg_context) -> None:
        overlay = NotebookSnapOverlay(drawlist=_MockDrawList())
        assert overlay.render() == 0

    def test_render_one_edge_ghost_paints_dashes(self, dpg_context) -> None:
        mock = _MockDrawList()
        overlay = NotebookSnapOverlay(drawlist=mock)
        overlay.set_ghosts([
            SnapGhost(rect=(0, 0, 40, 40), snap_kind="edge"),
        ])
        n = overlay.render()
        assert n >= 16
        assert len(mock.lines) >= 16

    def test_render_dock_ghost_emits_arrow_lines(self, dpg_context) -> None:
        mock = _MockDrawList()
        overlay = NotebookSnapOverlay(drawlist=mock)
        overlay.set_ghosts([
            SnapGhost(rect=(0, 0, 100, 100), snap_kind="dock_left"),
        ])
        overlay.render()
        # Dashed border + 3 arrow lines (shaft + 2 wings).
        assert len(mock.lines) >= 19

    def test_render_uses_ghost_theme_color(self, dpg_context) -> None:
        mock = _MockDrawList()
        overlay = NotebookSnapOverlay(drawlist=mock)
        overlay.set_ghosts([
            SnapGhost(
                rect=(0, 0, 40, 40),
                snap_kind="edge",
                theme_color=(200, 50, 150, 255),
            ),
        ])
        overlay.render()
        colors = {line[2] for line in mock.lines}
        assert (200, 50, 150, 255) in colors

    def test_render_all_dock_kinds(self, dpg_context) -> None:
        mock = _MockDrawList()
        overlay = NotebookSnapOverlay(drawlist=mock)
        overlay.set_ghosts([
            SnapGhost(rect=(0, 0, 100, 100), snap_kind=k)
            for k in (
                "dock_left", "dock_right",
                "dock_top", "dock_bottom", "dock_center",
            )
        ])
        n = overlay.render()
        assert n > 0

    def test_render_without_drawlist_is_zero(self, dpg_context) -> None:
        overlay = NotebookSnapOverlay(drawlist=None)
        overlay.set_ghosts([
            SnapGhost(rect=(0, 0, 40, 40), snap_kind="edge"),
        ])
        assert overlay.render() == 0

    def test_render_target_override(self, dpg_context) -> None:
        overlay = NotebookSnapOverlay(drawlist=None)
        overlay.set_ghosts([
            SnapGhost(rect=(0, 0, 40, 40), snap_kind="edge"),
        ])
        mock = _MockDrawList()
        n = overlay.render(drawlist=mock)
        assert n > 0
        assert len(mock.lines) > 0


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------


class TestPublicExports:
    def test_lazy_import_from_editor_pkg(self, dpg_context) -> None:
        from pharos_engine.ui import editor

        assert editor.NotebookSnapOverlay is NotebookSnapOverlay
        assert editor.SnapGhost is SnapGhost

    def test_default_theme_color_falls_back(self, dpg_context) -> None:
        rgba = NotebookSnapOverlay.default_theme_color()
        assert len(rgba) == 4
        for c in rgba[:3]:
            assert 0 <= c <= 255
