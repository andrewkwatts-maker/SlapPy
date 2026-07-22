"""Tests for :mod:`pharos_engine.ui.editor.panel_extras`.

Covers the :class:`ExtendedCornerSpec` validation surface, the
attach / detach / render lifecycle on :class:`ExtendedPanelDecorator`,
and the theme-driven default corner list. No live Dear PyGui context is
required — a recording drawlist captures every op so the tests can
assert on counts, colours, and geometry.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pharos_engine.ui.editor.panel_extras import (
    ExtendedCornerSpec,
    ExtendedPanelDecorator,
    default_extended_corners_for_theme,
)


# ---------------------------------------------------------------------------
# Recording drawlist
# ---------------------------------------------------------------------------


class _RecordingDrawList:
    """Capture every draw_image / draw_polygon call."""

    def __init__(self) -> None:
        self.ops: list[dict[str, Any]] = []

    def draw_image(self, **kwargs: Any) -> None:
        self.ops.append({"op": "image", **kwargs})

    def draw_polygon(self, **kwargs: Any) -> None:
        self.ops.append({"op": "polygon", **kwargs})

    def images(self) -> list[dict[str, Any]]:
        return [op for op in self.ops if op["op"] == "image"]


# ---------------------------------------------------------------------------
# Panel window stub — mimics MovablePanelWindow's surface
# ---------------------------------------------------------------------------


@dataclass
class _FakePanelWindow:
    tag: str = "fake_panel"
    pos: tuple[int, int] = (100, 80)
    size: tuple[int, int] = (400, 300)
    docked_to: str | None = "floating"
    extended_corners: list = field(default_factory=list)

    def get_window_tag(self) -> str:
        return self.tag

    def get_position(self) -> tuple[int, int]:
        return self.pos

    def get_size(self) -> tuple[int, int]:
        return self.size


# ---------------------------------------------------------------------------
# Minimal theme + decor stubs
# ---------------------------------------------------------------------------


class _FakeDecor:
    def __init__(self, corner_style: str = "tape_blue") -> None:
        self.corner_style = corner_style
        self.per_kind: dict[str, tuple[str, str]] = {}

    def for_panel(self, kind: str) -> tuple[str, str]:
        return self.per_kind.get(kind, ("wavy", self.corner_style))


class _FakeTheme:
    def __init__(self, corner_style: str = "tape_blue") -> None:
        self.decor = _FakeDecor(corner_style=corner_style)


# ---------------------------------------------------------------------------
# ExtendedCornerSpec validation
# ---------------------------------------------------------------------------


class TestExtendedCornerSpec:
    def test_defaults(self):
        spec = ExtendedCornerSpec(corner="TL", tape_style="tape_pink")
        assert spec.corner == "TL"
        assert spec.tape_style == "tape_pink"
        assert spec.tape_size_px == (48, 16)
        assert spec.offset_px == (-8, -6)
        assert spec.rotation_deg == 0.0
        assert spec.z_order == 10

    def test_corner_case_insensitive(self):
        spec = ExtendedCornerSpec(corner="tr", tape_style="tape_pink")
        assert spec.corner == "TR"

    def test_corner_rejects_unknown(self):
        with pytest.raises(ValueError):
            ExtendedCornerSpec(corner="MIDDLE", tape_style="tape_pink")

    def test_corner_rejects_empty(self):
        with pytest.raises(Exception):
            ExtendedCornerSpec(corner="", tape_style="tape_pink")

    def test_tape_style_rejects_empty(self):
        with pytest.raises(Exception):
            ExtendedCornerSpec(corner="TL", tape_style="")

    def test_tape_size_rejects_zero(self):
        with pytest.raises(Exception):
            ExtendedCornerSpec(
                corner="TL", tape_style="tape_pink", tape_size_px=(0, 16),
            )

    def test_tape_size_rejects_bad_shape(self):
        with pytest.raises(TypeError):
            ExtendedCornerSpec(
                corner="TL", tape_style="tape_pink", tape_size_px=(48,),  # type: ignore[arg-type]
            )

    def test_offset_rejects_non_int(self):
        with pytest.raises(TypeError):
            ExtendedCornerSpec(
                corner="TL", tape_style="tape_pink", offset_px=(-8.5, -6),  # type: ignore[arg-type]
            )

    def test_rotation_accepts_float(self):
        spec = ExtendedCornerSpec(
            corner="TL", tape_style="tape_pink", rotation_deg=-12.5,
        )
        assert spec.rotation_deg == pytest.approx(-12.5)

    def test_rotation_rejects_bool(self):
        with pytest.raises(TypeError):
            ExtendedCornerSpec(
                corner="TL", tape_style="tape_pink", rotation_deg=True,  # type: ignore[arg-type]
            )

    def test_z_order_stored(self):
        spec = ExtendedCornerSpec(
            corner="BR", tape_style="tape_pink", z_order=42,
        )
        assert spec.z_order == 42


# ---------------------------------------------------------------------------
# Attach / detach lifecycle
# ---------------------------------------------------------------------------


class TestAttachDetach:
    def test_attach_populates_specs(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow()
        specs = [
            ExtendedCornerSpec(corner="TL", tape_style="tape_pink"),
            ExtendedCornerSpec(corner="TR", tape_style="tape_pink"),
        ]
        dec.attach(panel, specs)
        assert len(dec.get_specs(panel)) == 2
        assert panel.extended_corners == specs

    def test_attach_overwrites(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow()
        dec.attach(panel, [ExtendedCornerSpec(corner="TL", tape_style="tape_pink")])
        dec.attach(
            panel,
            [
                ExtendedCornerSpec(corner="BL", tape_style="tape_blue"),
                ExtendedCornerSpec(corner="BR", tape_style="tape_mint"),
            ],
        )
        specs = dec.get_specs(panel)
        assert [s.corner for s in specs] == ["BL", "BR"]

    def test_detach_removes_specs(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow()
        dec.attach(panel, [ExtendedCornerSpec(corner="TL", tape_style="tape_pink")])
        dec.detach(panel)
        assert dec.get_specs(panel) == []
        assert panel.extended_corners == []

    def test_detach_unattached_is_noop(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow()
        dec.detach(panel)  # must not raise

    def test_attach_rejects_none(self):
        dec = ExtendedPanelDecorator()
        with pytest.raises(TypeError):
            dec.attach(None, [])  # type: ignore[arg-type]

    def test_attach_rejects_bad_specs_element(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow()
        with pytest.raises(TypeError):
            dec.attach(panel, ["not-a-spec"])  # type: ignore[list-item]

    def test_attached_panels_lists_registered(self):
        dec = ExtendedPanelDecorator()
        p1 = _FakePanelWindow(tag="p1")
        p2 = _FakePanelWindow(tag="p2")
        dec.attach(p1, [ExtendedCornerSpec(corner="TL", tape_style="tape_pink")])
        dec.attach(p2, [ExtendedCornerSpec(corner="TR", tape_style="tape_pink")])
        panels = dec.attached_panels()
        assert p1 in panels and p2 in panels


# ---------------------------------------------------------------------------
# is_floating predicate
# ---------------------------------------------------------------------------


class TestIsFloating:
    def test_floating_string(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to="floating")
        assert dec.is_floating(panel) is True

    def test_none_is_floating(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to=None)
        assert dec.is_floating(panel) is True

    def test_docked_left_is_not_floating(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to="left")
        assert dec.is_floating(panel) is False

    def test_docked_top_is_not_floating(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to="top")
        assert dec.is_floating(panel) is False


# ---------------------------------------------------------------------------
# render_all — the fun stuff
# ---------------------------------------------------------------------------


class TestRenderAll:
    def test_render_all_skips_docked_panels(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to="left")
        dec.attach(
            panel,
            [
                ExtendedCornerSpec(corner="TL", tape_style="tape_pink"),
                ExtendedCornerSpec(corner="TR", tape_style="tape_pink"),
            ],
        )
        dl = _RecordingDrawList()
        diag = dec.render_all(dl)
        assert diag["visited_panels"] == 0
        assert diag["skipped_docked"] == 1
        assert dl.ops == []

    def test_render_all_draws_four_strips_for_floating(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to="floating")
        specs = [
            ExtendedCornerSpec(corner=c, tape_style="tape_pink")
            for c in ("TL", "TR", "BL", "BR")
        ]
        dec.attach(panel, specs)
        dl = _RecordingDrawList()
        diag = dec.render_all(dl)
        assert diag["visited_panels"] == 1
        assert diag["draw_calls"] == 4
        assert len(dl.images()) == 4

    def test_render_all_empty_specs_skipped(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to="floating")
        dec.attach(panel, [])
        dl = _RecordingDrawList()
        diag = dec.render_all(dl)
        assert diag["visited_panels"] == 0
        assert diag["draw_calls"] == 0

    def test_render_all_visits_multiple_panels(self):
        dec = ExtendedPanelDecorator()
        p1 = _FakePanelWindow(tag="p1", docked_to="floating")
        p2 = _FakePanelWindow(tag="p2", docked_to=None)
        dec.attach(p1, [ExtendedCornerSpec(corner="TL", tape_style="tape_pink")])
        dec.attach(p2, [ExtendedCornerSpec(corner="TR", tape_style="tape_pink")])
        dl = _RecordingDrawList()
        diag = dec.render_all(dl)
        assert diag["visited_panels"] == 2
        assert diag["draw_calls"] == 2

    def test_render_all_offset_propagates_outward(self):
        # TL corner at (100, 80). Default offset is (-8, -6) — the polygon
        # bbox should extend at least 6 px above and 8 px to the LEFT of
        # the panel's TL, proving the tape spills past the window.
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(pos=(100, 80), size=(400, 300), docked_to="floating")
        dec.attach(
            panel,
            [
                ExtendedCornerSpec(
                    corner="TL",
                    tape_style="tape_pink",
                    tape_size_px=(48, 16),
                    offset_px=(-8, -6),
                    rotation_deg=0.0,
                ),
            ],
        )
        dl = _RecordingDrawList()
        dec.render_all(dl)
        images = dl.images()
        assert len(images) == 1
        polygon = images[0]["polygon"]
        min_x = min(p[0] for p in polygon)
        min_y = min(p[1] for p in polygon)
        # Anchor sits at (92, 74); tape is 48 wide × 16 tall centred on that.
        # So min x should be 92 - 24 = 68 and min y should be 74 - 8 = 66.
        assert min_x == pytest.approx(68.0)
        assert min_y == pytest.approx(66.0)

    def test_render_all_rotation_propagates(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(pos=(100, 80), size=(400, 300), docked_to="floating")
        dec.attach(
            panel,
            [
                ExtendedCornerSpec(
                    corner="TL",
                    tape_style="tape_pink",
                    rotation_deg=45.0,
                    offset_px=(0, 0),
                ),
            ],
        )
        dl = _RecordingDrawList()
        dec.render_all(dl)
        images = dl.images()
        assert len(images) == 1
        assert images[0]["rotation_deg"] == pytest.approx(45.0)
        # Sanity: with a 45-degree rotation, the polygon's bbox on the y
        # axis grows compared to the unrotated 16 px short edge.
        polygon = images[0]["polygon"]
        h = max(p[1] for p in polygon) - min(p[1] for p in polygon)
        assert h > 16.0

    def test_render_all_z_order_determines_draw_sequence(self):
        # Higher z_order draws last (on top). We attach two specs in
        # z=1 then z=100 order but reversed at attach time — the render
        # order should still respect the z_order key.
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to="floating")
        top = ExtendedCornerSpec(
            corner="TR", tape_style="tape_mint", z_order=100,
        )
        bot = ExtendedCornerSpec(
            corner="TL", tape_style="tape_pink", z_order=1,
        )
        dec.attach(panel, [top, bot])
        dl = _RecordingDrawList()
        dec.render_all(dl)
        # First image drawn should be the low-z one (tape_pink @ TL);
        # second should be tape_mint @ TR.
        assert dl.images()[0]["texture_tag"] == "tape_pink"
        assert dl.images()[1]["texture_tag"] == "tape_mint"

    def test_render_all_returns_diagnostics_dict(self):
        dec = ExtendedPanelDecorator()
        panel = _FakePanelWindow(docked_to="floating")
        dec.attach(panel, [ExtendedCornerSpec(corner="TL", tape_style="tape_pink")])
        dl = _RecordingDrawList()
        diag = dec.render_all(dl)
        assert set(diag.keys()) == {"draw_calls", "visited_panels", "skipped_docked"}


# ---------------------------------------------------------------------------
# Theme-driven default corners
# ---------------------------------------------------------------------------


class TestThemeDefaults:
    def test_default_returns_tl_and_tr(self):
        theme = _FakeTheme(corner_style="tape_yellow")
        specs = default_extended_corners_for_theme(theme)
        assert [s.corner for s in specs] == ["TL", "TR"]
        assert all(s.tape_style == "tape_yellow" for s in specs)

    def test_default_none_theme_uses_pink(self):
        specs = default_extended_corners_for_theme(None)
        assert all(s.tape_style == "tape_pink" for s in specs)

    def test_theme_switch_updates_style(self):
        # A theme swap should give the caller a fresh spec list with the
        # new tape style — that's how the theme switcher re-attaches.
        theme_a = _FakeTheme(corner_style="tape_pink")
        theme_b = _FakeTheme(corner_style="tape_mint")
        specs_a = default_extended_corners_for_theme(theme_a)
        specs_b = default_extended_corners_for_theme(theme_b)
        assert specs_a[0].tape_style == "tape_pink"
        assert specs_b[0].tape_style == "tape_mint"

    def test_default_size_and_offset_match_brief(self):
        # The brief specifies ~48×16 px tape with an 8 px outward spill.
        specs = default_extended_corners_for_theme(_FakeTheme())
        for s in specs:
            assert s.tape_size_px == (48, 16)
            # x offset pulls the tape leftward for TL and rightward-anchor
            # is baked in for TR — but both are negative on x, confirming
            # "spill outward" semantics per corner.
            assert s.offset_px[0] < 0
            assert s.offset_px[1] < 0

    def test_default_uses_per_kind_override(self):
        theme = _FakeTheme(corner_style="tape_pink")
        theme.decor.per_kind = {"toolbar": ("wavy", "tape_lavender")}
        specs = default_extended_corners_for_theme(theme, kind="toolbar")
        assert all(s.tape_style == "tape_lavender" for s in specs)


# ---------------------------------------------------------------------------
# Integration: MovablePanelWindow.extended_corners slot
# ---------------------------------------------------------------------------


class TestMovablePanelIntegration:
    def test_movable_panel_has_extended_corners_slot(self):
        from pharos_engine.ui.editor.movable_panel import MovablePanelWindow

        class _Stub:
            def build(self, parent_tag: Any) -> None:
                pass

        mp = MovablePanelWindow(panel=_Stub())
        assert hasattr(mp, "extended_corners")
        assert mp.extended_corners == []

    def test_attach_populates_movable_panel_slot(self):
        from pharos_engine.ui.editor.movable_panel import MovablePanelWindow

        class _Stub:
            def build(self, parent_tag: Any) -> None:
                pass

        mp = MovablePanelWindow(panel=_Stub())
        dec = ExtendedPanelDecorator()
        specs = [ExtendedCornerSpec(corner="TL", tape_style="tape_pink")]
        dec.attach(mp, specs)
        assert mp.extended_corners == specs

    def test_docked_movable_panel_skipped(self):
        from pharos_engine.ui.editor.movable_panel import MovablePanelWindow

        class _Stub:
            def build(self, parent_tag: Any) -> None:
                pass

        mp = MovablePanelWindow(panel=_Stub())
        mp.docked_to = "left"
        dec = ExtendedPanelDecorator()
        dec.attach(mp, [ExtendedCornerSpec(corner="TL", tape_style="tape_pink")])
        dl = _RecordingDrawList()
        diag = dec.render_all(dl)
        assert diag["skipped_docked"] == 1
        assert dl.ops == []
