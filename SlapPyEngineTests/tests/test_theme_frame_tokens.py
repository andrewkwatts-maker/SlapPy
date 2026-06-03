"""Tests for the :class:`FrameStyle` / :class:`PanelFrameSet` theme tokens.

Covers the data layer (defaults, fallbacks, per-theme expected values)
and the DPG bridge (payload structure, theme-switch rebuild). Every
assertion runs headless against the bridge's ``_DPGStub`` so DPG does
not have to be installed for the suite to pass.
"""
from __future__ import annotations

import pytest

try:
    from slappyengine.ui.theme import (
        Color,
        FrameStyle,
        PanelFrameSet,
        ThemeSpec,
        SemanticTokens,
        Gradient,
        apply_theme,
        apply_theme_to_dpg,
        register_theme,
    )
    from slappyengine.ui.theme import _reset_registry_for_tests
    from slappyengine.ui.theme.dpg_bridge import (
        get_last_dpg_payload,
        _reset_last_dpg_payload_for_tests,
    )
    from slappyengine.ui.theme.themes import (
        BULLET_JOURNAL,
        COTTAGECORE_GARDEN,
        COZY_DIARY,
        KAWAII_PLANNER,
        SCRAPBOOK_SUMMER,
        TEENGIRL_NOTEBOOK,
        register_all_themes,
    )
except Exception as e:  # pragma: no cover - skip if subpackage missing
    pytest.skip(
        f"slappyengine.ui.theme frame tokens not importable: {e}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_registry():
    _reset_registry_for_tests()
    _reset_last_dpg_payload_for_tests()
    yield
    _reset_registry_for_tests()
    _reset_last_dpg_payload_for_tests()


# Per-theme expected (border_size, rounding) — driven by the design doc.
EXPECTED_FRAME = {
    "teengirl_notebook": (1.0, 10.0),
    "cozy_diary": (2.0, 6.0),
    "bullet_journal": (1.0, 2.0),
    "scrapbook_summer": (2.0, 14.0),
    "cottagecore_garden": (2.0, 8.0),
    "kawaii_planner": (3.0, 16.0),
}
ALL_THEMES = (
    TEENGIRL_NOTEBOOK,
    COZY_DIARY,
    BULLET_JOURNAL,
    SCRAPBOOK_SUMMER,
    COTTAGECORE_GARDEN,
    KAWAII_PLANNER,
)


# ===========================================================================
# 1. FrameStyle defaults + validation
# ===========================================================================


def test_framestyle_defaults_match_spec():
    f = FrameStyle()
    assert f.border_size == 1.0
    assert f.border_color is None
    assert f.rounding == 8.0
    assert f.padding_x == 8
    assert f.padding_y == 6
    assert f.shadow_size == 4.0
    assert f.shadow_color is None
    assert f.child_rounding == 6.0
    assert f.child_border_size == 0.5
    assert f.grip_size == 12.0
    assert f.grip_rounding == 4.0
    assert f.title_bar_height == 24


def test_framestyle_accepts_custom_values():
    f = FrameStyle(
        border_size=3.0,
        border_color=Color(10, 20, 30, 1.0),
        rounding=16.0,
        padding_x=14,
        padding_y=12,
        shadow_size=8.0,
        shadow_color=Color(40, 50, 60, 0.5),
        child_rounding=10.0,
        child_border_size=1.0,
        grip_size=18.0,
        grip_rounding=6.0,
        title_bar_height=30,
    )
    assert f.border_size == 3.0
    assert f.border_color == Color(10, 20, 30, 1.0)
    assert f.shadow_color == Color(40, 50, 60, 0.5)


def test_framestyle_rejects_negative_border():
    with pytest.raises(ValueError):
        FrameStyle(border_size=-1.0)


def test_framestyle_rejects_negative_padding():
    with pytest.raises(ValueError):
        FrameStyle(padding_x=-2)


def test_framestyle_rejects_non_color_border():
    with pytest.raises(TypeError):
        FrameStyle(border_color="not a color")  # type: ignore[arg-type]


def test_framestyle_rejects_non_color_shadow():
    with pytest.raises(TypeError):
        FrameStyle(shadow_color=(0, 0, 0, 1))  # type: ignore[arg-type]


# ===========================================================================
# 2. PanelFrameSet defaults + fallback
# ===========================================================================


def test_panelframeset_default_factory():
    fs = PanelFrameSet()
    assert isinstance(fs.default, FrameStyle)
    assert fs.toolbar is None
    assert fs.sidebar is None
    assert fs.viewport is None
    assert fs.modal is None
    assert fs.code_pane is None
    assert fs.status_bar is None


def test_panelframeset_for_panel_returns_default_when_unset():
    default_frame = FrameStyle(border_size=2.0)
    fs = PanelFrameSet(default=default_frame)
    assert fs.for_panel("toolbar") is default_frame
    assert fs.for_panel("sidebar") is default_frame
    assert fs.for_panel("modal") is default_frame


def test_panelframeset_for_panel_returns_specific_when_set():
    default_frame = FrameStyle(border_size=1.0)
    toolbar_frame = FrameStyle(border_size=5.0)
    fs = PanelFrameSet(default=default_frame, toolbar=toolbar_frame)
    assert fs.for_panel("toolbar") is toolbar_frame
    assert fs.for_panel("sidebar") is default_frame


def test_panelframeset_for_panel_unknown_kind_falls_back_to_default():
    default_frame = FrameStyle(border_size=1.5)
    fs = PanelFrameSet(default=default_frame)
    # Unknown kind name -> default (not an error).
    assert fs.for_panel("nonexistent_panel_kind") is default_frame


def test_panelframeset_for_panel_rejects_empty_kind():
    fs = PanelFrameSet()
    with pytest.raises(ValueError):
        fs.for_panel("")


def test_panelframeset_rejects_non_framestyle_default():
    with pytest.raises(TypeError):
        PanelFrameSet(default="not a frame")  # type: ignore[arg-type]


def test_panelframeset_rejects_non_framestyle_slot():
    with pytest.raises(TypeError):
        PanelFrameSet(toolbar="bogus")  # type: ignore[arg-type]


# ===========================================================================
# 3. ThemeSpec carries a PanelFrameSet
# ===========================================================================


def test_themespec_default_frames_field():
    semantic = TEENGIRL_NOTEBOOK.semantic
    spec = ThemeSpec(name="probe", semantic=semantic)
    assert isinstance(spec.frames, PanelFrameSet)
    assert isinstance(spec.frames.default, FrameStyle)


def test_themespec_rejects_non_panelframeset_frames():
    semantic = TEENGIRL_NOTEBOOK.semantic
    with pytest.raises(TypeError):
        ThemeSpec(name="probe", semantic=semantic, frames="bogus")  # type: ignore[arg-type]


# ===========================================================================
# 4. Per-theme frame style assertions
# ===========================================================================


@pytest.mark.parametrize("theme", ALL_THEMES)
def test_each_theme_has_panelframeset(theme):
    assert isinstance(theme.frames, PanelFrameSet)
    assert isinstance(theme.frames.default, FrameStyle)


@pytest.mark.parametrize("theme", ALL_THEMES)
def test_each_theme_matches_documented_border_and_rounding(theme):
    expected_border, expected_rounding = EXPECTED_FRAME[theme.name]
    default = theme.frames.default
    assert default.border_size == expected_border, (
        f"{theme.name}: border_size {default.border_size} "
        f"!= expected {expected_border}"
    )
    assert default.rounding == expected_rounding, (
        f"{theme.name}: rounding {default.rounding} "
        f"!= expected {expected_rounding}"
    )


def test_teengirl_notebook_has_lilac_border_and_sidebar_override():
    fs = TEENGIRL_NOTEBOOK.frames
    assert fs.default.border_color == Color(231, 221, 241, 1.0)
    # Sidebar bumps rounding to 12 px.
    assert fs.sidebar is not None
    assert fs.sidebar.rounding == 12.0


def test_cozy_diary_has_caramel_border_and_thick_2px_size():
    fs = COZY_DIARY.frames
    assert fs.default.border_size == 2.0
    assert fs.default.border_color == Color(176, 122, 92, 1.0)  # caramel
    # Padding doc spec 12x10.
    assert fs.default.padding_x == 12
    assert fs.default.padding_y == 10


def test_bullet_journal_has_minimal_shadow():
    fs = BULLET_JOURNAL.frames
    # Minimal shadow per spec (≤ 1 px).
    assert fs.default.shadow_size <= 1.0
    # Crisp soft-black border.
    assert fs.default.border_color == Color(42, 42, 42, 1.0)
    assert fs.default.padding_x == 8
    assert fs.default.padding_y == 6


def test_kawaii_planner_has_oversized_grip_and_thick_border():
    fs = KAWAII_PLANNER.frames
    # Spec: 3 px border, 16 px rounded, 16 px grip.
    assert fs.default.border_size == 3.0
    assert fs.default.rounding == 16.0
    assert fs.default.grip_size == 16.0


def test_scrapbook_summer_has_bubbly_14px_rounding():
    fs = SCRAPBOOK_SUMMER.frames
    assert fs.default.rounding == 14.0
    assert fs.default.border_size == 2.0


def test_cottagecore_garden_has_sage_border_and_generous_padding():
    fs = COTTAGECORE_GARDEN.frames
    assert fs.default.border_color == Color(141, 167, 124, 1.0)  # sage
    assert fs.default.padding_x == 14
    assert fs.default.padding_y == 10


# ===========================================================================
# 5. DPG bridge — apply_theme_to_dpg returns a valid theme handle
# ===========================================================================


def test_apply_theme_to_dpg_returns_integer_tag():
    tag = apply_theme_to_dpg(TEENGIRL_NOTEBOOK, bind=False)
    assert isinstance(tag, int)
    assert tag > 0


def test_apply_theme_to_dpg_records_payload():
    apply_theme_to_dpg(COZY_DIARY, bind=False)
    payload = get_last_dpg_payload()
    assert payload is not None
    assert payload["theme_name"] == "cozy_diary"
    assert "color_tags" in payload
    assert "style_tags" in payload
    assert "panel_payloads" in payload


def test_apply_theme_to_dpg_emits_one_style_tag_per_style_var():
    apply_theme_to_dpg(BULLET_JOURNAL, bind=False)
    payload = get_last_dpg_payload()
    assert payload is not None
    # 9 style-var pairs in _build_style_pairs.
    assert len(payload["style_tags"]) == len(payload["style_pairs"])
    assert len(payload["style_pairs"]) >= 7


def test_apply_theme_to_dpg_records_panel_kinds():
    apply_theme_to_dpg(KAWAII_PLANNER, bind=False)
    payload = get_last_dpg_payload()
    assert payload is not None
    panels = payload["panel_payloads"]
    for kind in ("toolbar", "sidebar", "viewport", "modal",
                 "code_pane", "status_bar"):
        assert kind in panels
        p = panels[kind]
        assert "border_size" in p
        assert "rounding" in p
        assert "padding_x" in p
        assert "shadow_color" in p


def test_apply_theme_to_dpg_falls_back_to_default_shadow_when_none():
    # Build a theme with shadow_color=None in default frame.
    semantic = TEENGIRL_NOTEBOOK.semantic
    spec = ThemeSpec(
        name="probe_shadow_fallback",
        semantic=semantic,
        frames=PanelFrameSet(
            default=FrameStyle(shadow_color=None, border_color=None)
        ),
    )
    apply_theme_to_dpg(spec, bind=False)
    payload = get_last_dpg_payload()
    assert payload is not None
    toolbar = payload["panel_payloads"]["toolbar"]
    # Shadow falls back to text_primary at 30 % alpha.
    ink = semantic.text_primary
    assert toolbar["shadow_color"][:3] == (ink.r, ink.g, ink.b)
    # Border falls back to semantic.border.
    border = semantic.border
    assert toolbar["border_color"][:3] == (border.r, border.g, border.b)


def test_apply_theme_to_dpg_rejects_non_themespec():
    with pytest.raises(TypeError):
        apply_theme_to_dpg("not a theme")  # type: ignore[arg-type]


def test_apply_theme_to_dpg_passes_kawaii_grip_size_to_payload():
    apply_theme_to_dpg(KAWAII_PLANNER, bind=False)
    payload = get_last_dpg_payload()
    assert payload is not None
    # 16 px grip survives the bridge.
    toolbar = payload["panel_payloads"]["toolbar"]
    assert toolbar["grip_size"] == 16.0


# ===========================================================================
# 6. Theme switch triggers DPG theme rebuild
# ===========================================================================


def test_apply_theme_invokes_dpg_bridge():
    register_all_themes()
    apply_theme("teengirl_notebook")
    payload = get_last_dpg_payload()
    assert payload is not None
    assert payload["theme_name"] == "teengirl_notebook"


def test_theme_switch_rebuilds_dpg_payload():
    register_all_themes()
    apply_theme("teengirl_notebook")
    first = get_last_dpg_payload()
    assert first is not None
    first_tag = first["theme_tag"]

    apply_theme("kawaii_planner")
    second = get_last_dpg_payload()
    assert second is not None
    assert second["theme_name"] == "kawaii_planner"
    # New tag minted on every apply.
    assert second["theme_tag"] != first_tag


def test_theme_switch_picks_up_new_border_color():
    register_all_themes()
    apply_theme("bullet_journal")
    bj = get_last_dpg_payload()
    assert bj is not None
    bj_border = bj["colors"][bj["color_tags"].__iter__().__next__()]  # noqa
    # Re-fetch by key to be deterministic — pull WindowBg colour.
    from slappyengine.ui.theme.dpg_bridge import _DPG
    bj_wnd_bg = bj["colors"][_DPG.mvThemeCol_WindowBg]
    apply_theme("kawaii_planner")
    kp = get_last_dpg_payload()
    assert kp is not None
    kp_wnd_bg = kp["colors"][_DPG.mvThemeCol_WindowBg]
    assert bj_wnd_bg != kp_wnd_bg
