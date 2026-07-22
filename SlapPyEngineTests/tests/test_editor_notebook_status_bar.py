"""Tests for the notebook ambient status bar + window-title decorator.

Headless contract:

* All state mutation paths run without ``dearpygui`` installed.
* Transient messages fade out after ``transient_ttl_s`` of ticks.
* Theme indicator routes through the configured click callback.
* Semantic-token colours are pulled from the active :class:`ThemeSpec`
  when one is registered, with sane fallbacks otherwise.
* :func:`format_window_title` round-trips through :func:`parse_window_title`
  for both saved + unsaved scenes.
"""
from __future__ import annotations

import pytest

try:
    from pharos_engine.ui.editor.notebook_status_bar import (
        NotebookStatusBar,
        _TransientMessage,
        _FALLBACK_INK,
    )
    from pharos_engine.ui.editor.notebook_window_title import (
        format_window_title,
        parse_window_title,
        saved_glyph,
        unsaved_glyph,
    )
    from pharos_engine.ui.theme import (
        Color,
        Gradient,
        SemanticTokens,
        ThemeSpec,
        _reset_registry_for_tests,
        apply_theme,
        register_theme,
    )
except Exception as exc:  # pragma: no cover - skip when deps missing
    pytest.skip(
        f"notebook_status_bar dependencies unavailable: {exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Hand-rolled ThemeSpec so colour assertions don't depend on the full
# starter-theme registration (which carries unrelated import-time guards).
# ---------------------------------------------------------------------------


def _make_themespec(
    name: str,
    *,
    accent: tuple[int, int, int] = (255, 224, 102),
    success: tuple[int, int, int] = (91, 193, 138),
    error: tuple[int, int, int] = (232, 90, 108),
    warning: tuple[int, int, int] = (242, 187, 85),
    text_primary: tuple[int, int, int] = (31, 47, 102),
) -> ThemeSpec:
    accent_c = Color(*accent, 1.0)
    return ThemeSpec(
        name=name,
        semantic=SemanticTokens(
            primary=accent_c,
            primary_gradient=Gradient(
                start=accent_c, end=Color(0, 0, 0, 1.0), angle_deg=135.0,
            ),
            secondary=accent_c,
            accent=accent_c,
            background=Color(250, 246, 235, 1.0),
            surface=Color(250, 246, 235, 1.0),
            surface_hover=Color(231, 221, 241, 1.0),
            border=Color(184, 176, 160, 1.0),
            text_primary=Color(*text_primary, 1.0),
            text_secondary=Color(59, 59, 69, 1.0),
            text_disabled=Color(177, 172, 184, 1.0),
            success=Color(*success, 1.0),
            warning=Color(*warning, 1.0),
            error=Color(*error, 1.0),
            info=Color(127, 200, 232, 1.0),
            focus_ring=accent_c,
            glass_bg=Color(250, 246, 235, 0.85),
            glass_blur_px=12.0,
        ),
        palette={
            "washi_tape": Color(255, 111, 181, 1.0),
        },
        fonts={},
    )


@pytest.fixture(autouse=True)
def _isolated_registry():
    _reset_registry_for_tests()
    yield
    _reset_registry_for_tests()


@pytest.fixture
def with_teengirl():
    spec = _make_themespec("teengirl_notebook")
    register_theme(spec)
    apply_theme("teengirl_notebook")
    yield spec


# ---------------------------------------------------------------------------
# 1. Defaults + state setters
# ---------------------------------------------------------------------------


def test_defaults_are_sensible():
    bar = NotebookStatusBar()
    assert bar.active_tool == "select"
    assert bar.selection_count == 0
    assert bar.world_cursor == (0.0, 0.0)
    assert bar.fps == 0.0
    assert bar.saved is True
    assert bar.theme_name == "teengirl_notebook"
    assert bar.transient is None


def test_set_active_tool_updates_label():
    bar = NotebookStatusBar()
    bar.set_active_tool("rotate")
    assert bar.active_tool == "rotate"
    assert "rotate" in bar.compose_label()


def test_set_world_cursor_rounds_to_one_decimal():
    bar = NotebookStatusBar()
    bar.set_world_cursor(12.387, 8.04)
    assert bar.world_cursor == (12.387, 8.04)
    # compose_label rounds to 1 decimal so the bar doesn't shimmer.
    label = bar.compose_label()
    assert "(12.4, 8.0)" in label


def test_set_fps_renders_zero_decimal():
    bar = NotebookStatusBar()
    bar.set_fps(60.4)
    assert "60 fps" in bar.compose_label()


def test_set_save_state_flips_marker():
    bar = NotebookStatusBar()
    bar.set_save_state(False)
    assert bar.saved is False
    assert "unsaved" in bar.compose_label()
    bar.set_save_state(True)
    assert "saved" in bar.compose_label()
    assert "unsaved" not in bar.compose_label()


def test_set_selection_count_renders():
    bar = NotebookStatusBar()
    bar.set_selection_count(3)
    assert "3 selected" in bar.compose_label()


def test_set_active_theme_name_updates_sticker_hint():
    bar = NotebookStatusBar()
    bar.set_active_theme_name("cozy_diary")
    assert bar.theme_name == "cozy_diary"
    assert bar.theme_sticker_hint == "leaf"


# ---------------------------------------------------------------------------
# 2. Transient messages + fade
# ---------------------------------------------------------------------------


def test_set_message_overrides_label():
    bar = NotebookStatusBar()
    bar.set_message("Saved!", kind="success")
    assert bar.compose_label() == "Saved!"
    assert bar.transient is not None
    assert bar.transient.kind == "success"


def test_transient_fades_after_three_seconds(with_teengirl):
    bar = NotebookStatusBar(transient_ttl_s=3.0)
    bar.set_message("Saved!", kind="success")
    # Tick 2.9s — still visible.
    bar.tick(2.9)
    assert bar.transient is not None
    assert bar.compose_label() == "Saved!"
    # Tick past the TTL boundary — drops off.
    bar.tick(0.2)
    assert bar.transient is None
    assert bar.compose_label() != "Saved!"


def test_error_message_resolves_semantic_error_color(with_teengirl):
    bar = NotebookStatusBar()
    bar.set_message("Oops", kind="error")
    r, g, b, a = bar.message_color
    # TeenGirl semantic.error is (232, 90, 108).
    assert (r, g, b) == (232, 90, 108)


def test_success_message_resolves_semantic_success_color(with_teengirl):
    bar = NotebookStatusBar()
    bar.set_message("Saved!", kind="success")
    r, g, b, a = bar.message_color
    assert (r, g, b) == (91, 193, 138)


def test_set_message_rejects_unknown_kind():
    bar = NotebookStatusBar()
    with pytest.raises(ValueError):
        bar.set_message("hi", kind="cataclysm")


def test_tick_with_no_transient_is_noop():
    bar = NotebookStatusBar()
    bar.tick(1.0)
    assert bar.transient is None


def test_transient_alpha_fades_linearly_at_end():
    msg = _TransientMessage(text="x", kind="info", ttl_s=4.0)
    assert msg.alpha == 1.0
    msg.elapsed = 3.0  # 75% mark — still full alpha
    assert msg.alpha == 1.0
    msg.elapsed = 3.5  # 50% through the fade window
    assert 0.4 < msg.alpha < 0.6
    msg.elapsed = 4.0
    assert msg.alpha == 0.0


# ---------------------------------------------------------------------------
# 3. Theme indicator click
# ---------------------------------------------------------------------------


def test_theme_indicator_click_invokes_callback():
    fired: list[bool] = []
    bar = NotebookStatusBar(on_theme_indicator_click=lambda: fired.append(True))
    assert bar.on_theme_indicator_click() is True
    assert fired == [True]


def test_theme_indicator_click_without_callback_returns_false():
    bar = NotebookStatusBar()
    assert bar.on_theme_indicator_click() is False


def test_theme_indicator_click_swallows_callback_errors():
    def boom() -> None:
        raise RuntimeError("kaboom")
    bar = NotebookStatusBar(on_theme_indicator_click=boom)
    assert bar.on_theme_indicator_click() is False


# ---------------------------------------------------------------------------
# 4. Theme resolution fallbacks
# ---------------------------------------------------------------------------


def test_resident_color_falls_back_to_ink_without_theme():
    bar = NotebookStatusBar()
    # No theme registered; the fallback ink-navy should surface.
    assert bar.message_color == _FALLBACK_INK


def test_divider_color_pulls_washi_tape_from_theme(with_teengirl):
    bar = NotebookStatusBar()
    r, g, b, a = bar.divider_color
    assert (r, g, b) == (255, 111, 181)


# ---------------------------------------------------------------------------
# 5. Headless build is a no-op
# ---------------------------------------------------------------------------


def test_build_with_stub_dpg_does_not_raise(monkeypatch):
    """Verify the DPG codepath is invoked when a stub is monkeypatched in."""
    import sys
    import types

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

    bar = NotebookStatusBar()
    bar.build("parent_tag")
    # _built is flipped + set_* calls still work after build.
    bar.set_fps(60.0)
    assert "60 fps" in bar.compose_label()


def test_refresh_label_when_not_built_is_noop():
    bar = NotebookStatusBar()
    # set_* calls invoke _refresh_label internally; before build() runs
    # they should be silent (no DPG access).
    bar.set_fps(120.0)
    bar.set_save_state(False)
    assert "120 fps" in bar.compose_label()


# ---------------------------------------------------------------------------
# 6. Window-title formatter
# ---------------------------------------------------------------------------


def test_format_window_title_saved_uses_heart_glyph():
    title = format_window_title("my_scene", saved=True, theme_name="teengirl_notebook")
    assert title.startswith("SlapPy Notebook")
    assert "my_scene heart" in title
    assert "teengirl_notebook" in title


def test_format_window_title_unsaved_uses_flower_glyph():
    title = format_window_title("draft", saved=False, theme_name="cozy_diary")
    assert "draft flower" in title


def test_format_window_title_unicode_glyphs_when_requested():
    title = format_window_title("hi", saved=True, theme_name="t", use_unicode=True)
    assert saved_glyph(True) in title
    assert "hi " + saved_glyph(True) in title


def test_format_window_title_rejects_empty_scene():
    with pytest.raises(ValueError):
        format_window_title("", saved=True, theme_name="t")


def test_format_window_title_rejects_non_bool_saved():
    with pytest.raises(TypeError):
        format_window_title("s", saved="yes", theme_name="t")  # type: ignore[arg-type]


def test_format_window_title_round_trip_saved():
    title = format_window_title("my_scene", saved=True, theme_name="teengirl_notebook")
    parsed = parse_window_title(title)
    assert parsed["scene_name"] == "my_scene"
    assert parsed["saved"] is True
    assert parsed["theme_name"] == "teengirl_notebook"


def test_format_window_title_round_trip_unsaved_unicode():
    title = format_window_title(
        "draft", saved=False, theme_name="cozy_diary", use_unicode=True,
    )
    parsed = parse_window_title(title)
    assert parsed["scene_name"] == "draft"
    assert parsed["saved"] is False
    assert parsed["theme_name"] == "cozy_diary"
    assert parsed["use_unicode"] is True


def test_saved_glyph_differs_from_unsaved_glyph():
    assert saved_glyph(False) != unsaved_glyph(False)
    assert saved_glyph(True) != unsaved_glyph(True)
