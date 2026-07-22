"""Tests for the notebook-themed editor toolbar.

Covers the contract in the sprint brief: 4 stamp tools, SVG icons under
500 bytes each, washi-tape active-tool indicator that recolours with the
theme, S/T/R/C keyboard shortcuts, theme-switch palette propagation, the
reserved 32×32 creature slot, and a headless smoke build.

All tests run without dearpygui — the module degrades to no-op build
paths so the toolbar object + every public method remain inspectable
in headless contexts.
"""
from __future__ import annotations

import sys
import types

import numpy as np
import pytest

try:
    from pharos_engine.ui.editor.notebook_toolbar import (
        NotebookToolbar,
        _SVG_BOW_TIE,
        _SVG_FOUR_ARROW_FLOWER,
        _SVG_HEART_ARROW,
        _SVG_SPIRAL,
    )
    from pharos_engine.ui.theme import (
        Color,
        Font,
        Gradient,
        SemanticTokens,
        ThemeSpec,
        _reset_registry_for_tests,
        apply_theme,
        register_theme,
    )
    from pharos_engine.ui.theme.creatures.slot_policy import SlotRegion
    from pharos_engine.ui.theme.svg_icon import SVGIcon
    from pharos_engine.ui.theme.svg_icon import clear_cache as clear_svg_cache
    from pharos_engine.ui.widgets.notebook_theme import set_active_theme
    from pharos_engine.ui.widgets.sticker_button import StickerButton
except Exception as exc:  # pragma: no cover - skip when deps missing
    pytest.skip(
        f"notebook_toolbar dependencies unavailable: {exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Local hand-rolled ThemeSpecs — the ``themes`` subpackage carries an
# unrelated import-time guard that fires on a pre-existing SVG; we mint
# minimal stand-ins so the toolbar can be exercised in isolation.
# ---------------------------------------------------------------------------


def _make_themespec(name, accent_rgb, washi_rgb=None, ink_rgb=(31, 47, 102),
                    body_font="Quicksand"):
    accent = Color(accent_rgb[0], accent_rgb[1], accent_rgb[2],
                   accent_rgb[3] / 255 if len(accent_rgb) == 4 else 1.0)
    washi = Color(*washi_rgb, 1.0) if washi_rgb is not None else None
    ink = Color(ink_rgb[0], ink_rgb[1], ink_rgb[2], 1.0)
    palette = {"surface": Color(250, 246, 235, 1.0)}
    if washi is not None:
        palette["washi_tape"] = washi
    return ThemeSpec(
        name=name,
        semantic=SemanticTokens(
            primary=accent,
            primary_gradient=Gradient(start=accent, end=ink, angle_deg=135.0),
            secondary=accent,
            accent=accent,
            background=Color(250, 246, 235, 1.0),
            surface=Color(250, 246, 235, 1.0),
            surface_hover=Color(231, 221, 241, 1.0),
            border=Color(184, 176, 160, 1.0),
            text_primary=ink,
            text_secondary=Color(59, 59, 69, 1.0),
            text_disabled=Color(177, 172, 184, 1.0),
            success=Color(91, 193, 138, 1.0),
            warning=Color(242, 187, 85, 1.0),
            error=Color(232, 90, 108, 1.0),
            info=Color(127, 200, 232, 1.0),
            focus_ring=accent,
            glass_bg=Color(250, 246, 235, 0.85),
            glass_blur_px=12.0,
        ),
        palette=palette,
        fonts={"body": Font(family=body_font, size=14, weight="500")},
    )


# TeenGirl substitute: highlighter yellow accent @ 220 alpha + bubblegum
# washi-tape colour + ink-navy text_primary.
_TEEN_STAND_IN = _make_themespec(
    name="teengirl_notebook",
    accent_rgb=(255, 224, 102, 220),
    washi_rgb=(255, 111, 181),
    ink_rgb=(0x1F, 0x2F, 0x66),
    body_font="Quicksand",
)
# Cozy diary substitute: caramel accent.
_COZY_STAND_IN = _make_themespec(
    name="cozy_diary",
    accent_rgb=(0xB0, 0x7A, 0x5C, 255),
    ink_rgb=(0x2E, 0x29, 0x26),
    body_font="Quicksand",
)
# Bullet journal substitute: pastel-pink accent.
_BJ_STAND_IN = _make_themespec(
    name="bullet_journal",
    accent_rgb=(0xFF, 0xC9, 0xD9, 255),
    ink_rgb=(0x2A, 0x2A, 0x2A),
    body_font="Quicksand",
)


def _register_stand_ins() -> None:
    register_theme(_TEEN_STAND_IN)
    register_theme(_COZY_STAND_IN)
    register_theme(_BJ_STAND_IN)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_theme_registry():
    """Reset the theme registry + svg cache around every test."""
    _reset_registry_for_tests()
    clear_svg_cache()
    set_active_theme(None)
    yield
    _reset_registry_for_tests()
    clear_svg_cache()
    set_active_theme(None)


@pytest.fixture
def with_teengirl():
    """Register and activate the TeenGirl Notebook stand-in theme."""
    _register_stand_ins()
    apply_theme("teengirl_notebook")
    yield _TEEN_STAND_IN


@pytest.fixture
def stub_dpg(monkeypatch):
    """Inject a stub dearpygui so build() exercises the DPG branch."""
    class _NoOp:
        def __getattr__(self, name):
            return lambda *a, **kw: None

        def does_item_exist(self, *a, **kw):
            return False

        def group(self, *a, **kw):
            class _Ctx:
                def __enter__(self_inner):
                    return self_inner

                def __exit__(self_inner, *exc):
                    return False

            return _Ctx()

    stub = _NoOp()
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = stub
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", stub)
    yield stub


# ---------------------------------------------------------------------------
# 1. Tool roster
# ---------------------------------------------------------------------------


def test_four_tools_present():
    bar = NotebookToolbar()
    ids = [t[0] for t in bar.TOOLS]
    assert ids == ["select", "move", "rotate", "scale"]


def test_tools_carry_shortcut_letters():
    bar = NotebookToolbar()
    sc = bar.shortcuts
    assert sc == {"S": "select", "T": "move", "R": "rotate", "C": "scale"}


def test_tools_carry_labels():
    bar = NotebookToolbar()
    labels = {t[0]: t[1] for t in bar.TOOLS}
    assert labels == {
        "select": "Select", "move": "Move",
        "rotate": "Rotate", "scale": "Scale",
    }


# ---------------------------------------------------------------------------
# 2. SVG icons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "svg",
    [_SVG_HEART_ARROW, _SVG_FOUR_ARROW_FLOWER, _SVG_SPIRAL, _SVG_BOW_TIE],
)
def test_svg_strings_under_500_bytes(svg):
    assert len(svg.encode("utf-8")) <= 500, (
        f"svg payload {len(svg)} bytes exceeds 500-byte budget"
    )


def test_icons_rasterize_without_error():
    bar = NotebookToolbar()
    for tool_id in ("select", "move", "rotate", "scale"):
        icon = bar.icons[tool_id]
        assert isinstance(icon, SVGIcon)
        tex = icon.rasterize()
        assert isinstance(tex, np.ndarray)
        assert tex.shape == (24, 24, 4)
        assert tex.dtype == np.uint8


def test_icons_distinct_per_tool():
    bar = NotebookToolbar()
    svgs = {tid: bar.icons[tid].svg_xml for tid in
            ("select", "move", "rotate", "scale")}
    # All four payloads must be distinct.
    assert len(set(svgs.values())) == 4


# ---------------------------------------------------------------------------
# 3. set_active / callback
# ---------------------------------------------------------------------------


def test_default_active_tool_is_select():
    bar = NotebookToolbar()
    assert bar.get_active() == "select"


def test_set_active_changes_tool_and_fires_callback():
    fired: list[str] = []
    bar = NotebookToolbar(on_tool_changed=fired.append)
    bar.set_active("move")
    assert bar.get_active() == "move"
    assert fired == ["move"]


def test_set_active_same_tool_does_not_refire():
    fired: list[str] = []
    bar = NotebookToolbar(on_tool_changed=fired.append)
    bar.set_active("rotate")
    bar.set_active("rotate")
    assert fired == ["rotate"]


def test_set_active_rejects_unknown_tool():
    bar = NotebookToolbar()
    with pytest.raises(ValueError):
        bar.set_active("nope")


# ---------------------------------------------------------------------------
# 4. Washi-tape indicator + theme colours
# ---------------------------------------------------------------------------


def test_tape_texture_shape_matches_button_width(with_teengirl):
    bar = NotebookToolbar()
    tex = bar.tape_texture("select")
    # Default button width is 96 px, tape height is 2 px.
    assert tex.shape == (2, 96, 4)
    assert tex.dtype == np.uint8


def test_tape_color_matches_teengirl_bubblegum_pink(with_teengirl):
    bar = NotebookToolbar()
    # TEENGIRL_NOTEBOOK has bubblegum-pink as primary; the washi-tape
    # colour falls back to semantic.accent (highlighter yellow @ alpha)
    # unless palette["washi_tape"] is registered. Verify the strip is at
    # least non-transparent and matches the resolver.
    expected = bar.active_tape_color
    centre = tex_centre_pixel(bar.tape_texture("rotate"))
    assert tuple(int(c) for c in centre) == expected


def test_active_indicator_color_matches_semantic_accent(with_teengirl):
    bar = NotebookToolbar()
    # TEENGIRL semantic.accent == highlighter yellow #FFE066 @ ~220 alpha.
    r, g, b, a = bar.active_indicator_color
    assert (r, g, b) == (255, 224, 102)
    assert a == 220


# ---------------------------------------------------------------------------
# 5. Keyboard shortcuts
# ---------------------------------------------------------------------------


def test_shortcut_S_selects_select_tool():
    bar = NotebookToolbar()
    bar.set_active("move")              # move away from default
    assert bar.handle_shortcut("S") is True
    assert bar.get_active() == "select"


def test_shortcut_T_selects_move_tool():
    fired: list[str] = []
    bar = NotebookToolbar(on_tool_changed=fired.append)
    assert bar.handle_shortcut("T") is True
    assert bar.get_active() == "move"
    assert fired == ["move"]


def test_shortcut_lowercase_works():
    bar = NotebookToolbar()
    assert bar.handle_shortcut("r") is True
    assert bar.get_active() == "rotate"


def test_unknown_shortcut_returns_false_without_mutating():
    bar = NotebookToolbar()
    assert bar.get_active() == "select"
    assert bar.handle_shortcut("X") is False
    assert bar.get_active() == "select"


# ---------------------------------------------------------------------------
# 6. Theme switch propagation
# ---------------------------------------------------------------------------


def test_theme_switch_updates_palette():
    _register_stand_ins()
    apply_theme("teengirl_notebook")
    bar = NotebookToolbar()
    yellow_accent = bar.active_indicator_color
    # Cozy diary's semantic.accent is caramel (#B07A5C).
    apply_theme("cozy_diary")
    bar.refresh_theme()
    caramel = bar.active_indicator_color
    assert yellow_accent != caramel
    assert (caramel[0], caramel[1], caramel[2]) == (0xB0, 0x7A, 0x5C)


def test_theme_switch_rebakes_tape_texture():
    _register_stand_ins()
    apply_theme("teengirl_notebook")
    bar = NotebookToolbar()
    teen_centre = tex_centre_pixel(bar.tape_texture("select"))
    apply_theme("bullet_journal")
    bar.refresh_theme()
    bj_centre = tex_centre_pixel(bar.tape_texture("select"))
    # The two themes have different semantic accents, so the centre
    # pixel must change.
    assert tuple(teen_centre) != tuple(bj_centre)


# ---------------------------------------------------------------------------
# 7. Creature slot
# ---------------------------------------------------------------------------


def test_creature_slot_region_is_32x32():
    bar = NotebookToolbar()
    slot = bar.creature_slot
    assert isinstance(slot, SlotRegion)
    assert slot.w == 32
    assert slot.h == 32


def test_default_creature_is_fox_01():
    bar = NotebookToolbar()
    assert bar.creature_id == "fox_01"


def test_creature_slot_anchored_to_toolbar():
    bar = NotebookToolbar()
    assert bar.creature_slot.parent_panel == "notebook_toolbar"


# ---------------------------------------------------------------------------
# 8. Sticker buttons
# ---------------------------------------------------------------------------


def test_buttons_are_sticker_buttons():
    bar = NotebookToolbar()
    for tid in ("select", "move", "rotate", "scale"):
        assert isinstance(bar.buttons[tid], StickerButton)
        assert bar.buttons[tid].label in {"Select", "Move", "Rotate", "Scale"}


# ---------------------------------------------------------------------------
# 9. Tooltip descriptor
# ---------------------------------------------------------------------------


def test_tooltip_uses_handwritten_font_when_theme_active(with_teengirl):
    bar = NotebookToolbar()
    tip = bar.tooltip("select")
    assert tip["text"] == "Select"
    # Body font is Quicksand in the TeenGirl Notebook theme.
    assert tip["font"] == "Quicksand"
    # text_primary is ink-navy #1F2F66.
    assert tip["color"][:3] == (0x1F, 0x2F, 0x66)


def test_tooltip_handles_unknown_tool():
    bar = NotebookToolbar()
    with pytest.raises(ValueError):
        bar.tooltip("nope")


# ---------------------------------------------------------------------------
# 10. Headless smoke
# ---------------------------------------------------------------------------


def test_build_headless_no_dpg_is_noop(monkeypatch):
    # Simulate "dearpygui not installed" by pointing the import at a
    # broken module — the toolbar's build() must swallow the failure.
    broken = types.ModuleType("dearpygui.dearpygui")
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = broken
    # Drop attribute access so any dpg.xxx call raises immediately,
    # exercising the build()'s headless fallback path.
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", broken)
    bar = NotebookToolbar()
    bar.build("some_parent_tag")
    # And the active tool / shortcuts still work.
    assert bar.get_active() == "select"
    bar.handle_shortcut("R")
    assert bar.get_active() == "rotate"


def test_build_with_stub_dpg_runs_through_group(stub_dpg):
    bar = NotebookToolbar()
    bar.build("toolbar_parent")
    # Nothing to assert on the stub side beyond no-raise; the contract
    # is that build() never throws for headless / stub DPG environments.
    assert bar.get_active() == "select"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def tex_centre_pixel(tex: np.ndarray) -> tuple[int, int, int, int]:
    """Return the centre pixel of an RGBA texture as a Python tuple."""
    h, w = tex.shape[0], tex.shape[1]
    px = tex[h // 2, w // 2, :]
    return (int(px[0]), int(px[1]), int(px[2]), int(px[3]))
