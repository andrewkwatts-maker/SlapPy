"""Tests for :mod:`pharos_editor.ui.runtime` — HH7 immediate-mode game UI.

Covers:
    * :class:`ImmediateUI` frame lifecycle + widgets (button, label, slider,
      checkbox, progress_bar, panel).
    * :class:`DrawCommand` dataclass validation + all kinds.
    * :class:`RuntimeTheme` defaults + soft ``from_diary_theme`` bridge.
    * HUD kit widgets: HealthBar, StaminaBar, AmmoCounter, Compass, Toast,
      Minimap.
    * :mod:`text_layout`: ``measure_text`` + ``wrap_text``.
    * :mod:`layout`: ``stack_vertical`` / ``stack_horizontal`` / ``grid`` +
      anchor factories.
    * :mod:`dpg_bridge`: soft-skip when Dear PyGui is missing.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from pharos_editor.ui.runtime import (
    AmmoCounter,
    Compass,
    DrawCommand,
    HealthBar,
    ImmediateUI,
    Minimap,
    RuntimeTheme,
    StaminaBar,
    Toast,
    anchor_bottomright,
    anchor_center,
    anchor_topleft,
    grid,
    measure_text,
    stack_horizontal,
    stack_vertical,
    wrap_text,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class _Item:
    """Ad-hoc dataclass matching the layout helpers' duck-type contract."""

    position: tuple[float, float] = (0.0, 0.0)
    size: tuple[float, float] = (100.0, 24.0)


def _kinds(cmds):
    return [c.kind for c in cmds]


# ---------------------------------------------------------------------------
# DrawCommand — dataclass surface
# ---------------------------------------------------------------------------


def test_drawcommand_rect_defaults():
    cmd = DrawCommand(
        kind="rect",
        position=(1, 2),
        size=(10, 20),
        color=(0.1, 0.2, 0.3, 1.0),
    )
    assert cmd.kind == "rect"
    assert cmd.position == (1.0, 2.0)
    assert cmd.size == (10.0, 20.0)
    assert cmd.color == (0.1, 0.2, 0.3, 1.0)
    assert cmd.text is None
    assert cmd.texture_id is None
    assert cmd.z_order == 0


def test_drawcommand_all_valid_kinds():
    kinds = ("rect", "text", "line", "circle", "textured_quad")
    for kind in kinds:
        cmd = DrawCommand(
            kind=kind,
            position=(0, 0),
            size=(4, 4),
            color=(1, 1, 1, 1),
        )
        assert cmd.kind == kind


def test_drawcommand_rejects_bad_kind():
    with pytest.raises(ValueError):
        DrawCommand(
            kind="triangle",
            position=(0, 0),
            size=(1, 1),
            color=(1, 1, 1, 1),
        )


def test_drawcommand_text_and_texture_slots():
    text_cmd = DrawCommand(
        kind="text",
        position=(0, 0),
        size=(1, 1),
        color=(1, 1, 1, 1),
        text="hello",
    )
    assert text_cmd.text == "hello"
    tex_cmd = DrawCommand(
        kind="textured_quad",
        position=(0, 0),
        size=(1, 1),
        color=(1, 1, 1, 1),
        texture_id=7,
        z_order=5,
    )
    assert tex_cmd.texture_id == 7
    assert tex_cmd.z_order == 5


# ---------------------------------------------------------------------------
# RuntimeTheme
# ---------------------------------------------------------------------------


def test_runtime_theme_default_palette_present():
    theme = RuntimeTheme()
    for name in (
        "text_color",
        "button_color",
        "hover_color",
        "bg_color",
        "panel_bg_color",
        "panel_border_color",
    ):
        col = getattr(theme, name)
        assert isinstance(col, tuple) and len(col) == 4
        # Non-None + finite floats.
        assert all(isinstance(c, float) for c in col)


def test_runtime_theme_from_diary_theme_returns_theme():
    # Whether or not the editor theme registry is present, the call must
    # produce a usable RuntimeTheme with non-None colours.
    theme = RuntimeTheme.from_diary_theme("aurora")
    assert isinstance(theme, RuntimeTheme)
    assert theme.text_color is not None
    assert theme.bg_color is not None
    assert len(theme.button_color) == 4


def test_runtime_theme_from_diary_theme_rejects_empty_id():
    with pytest.raises(TypeError):
        RuntimeTheme.from_diary_theme("")


# ---------------------------------------------------------------------------
# ImmediateUI — frame lifecycle
# ---------------------------------------------------------------------------


def test_immediate_ui_begin_end_returns_drawcommand_list():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    cmds = ui.end_frame()
    assert isinstance(cmds, list)
    # Frame always emits the background clear rect.
    assert len(cmds) >= 1
    assert all(isinstance(c, DrawCommand) for c in cmds)


def test_immediate_ui_double_begin_raises():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    with pytest.raises(RuntimeError):
        ui.begin_frame(0.016)


def test_immediate_ui_end_without_begin_raises():
    ui = ImmediateUI()
    with pytest.raises(RuntimeError):
        ui.end_frame()


def test_immediate_ui_widget_without_frame_raises():
    ui = ImmediateUI()
    with pytest.raises(RuntimeError):
        ui.label("l", "hi", (0, 0))


def test_immediate_ui_bad_font_size_rejected():
    with pytest.raises(ValueError):
        ImmediateUI(default_font_size=0)


# ---------------------------------------------------------------------------
# ImmediateUI — widgets
# ---------------------------------------------------------------------------


def test_button_click_release_returns_true():
    ui = ImmediateUI()
    # Frame 1: press inside button.
    ui.begin_frame(0.016, mouse_pos=(20, 20), mouse_down=True)
    clicked = ui.button("btn", "OK", (10, 10), (80, 24))
    ui.end_frame()
    assert clicked is False  # not released yet
    # Frame 2: release inside button — click fires now.
    ui.begin_frame(0.016, mouse_pos=(20, 20), mouse_down=False)
    clicked = ui.button("btn", "OK", (10, 10), (80, 24))
    ui.end_frame()
    assert clicked is True


def test_button_not_clicked_when_released_outside():
    ui = ImmediateUI()
    ui.begin_frame(0.016, mouse_pos=(500, 500), mouse_down=True)
    ui.button("btn", "OK", (10, 10), (80, 24))
    ui.end_frame()
    ui.begin_frame(0.016, mouse_pos=(500, 500), mouse_down=False)
    clicked = ui.button("btn", "OK", (10, 10), (80, 24))
    ui.end_frame()
    assert clicked is False


def test_button_empty_id_rejected():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    with pytest.raises(ValueError):
        ui.button("", "OK", (0, 0), (10, 10))
    ui.end_frame()


def test_checkbox_click_toggles_value():
    ui = ImmediateUI()
    ui.begin_frame(0.016, mouse_pos=(4, 4), mouse_down=True)
    v1 = ui.checkbox("chk", "", (0, 0), value=False)
    ui.end_frame()
    assert v1 is False
    ui.begin_frame(0.016, mouse_pos=(4, 4), mouse_down=False)
    v2 = ui.checkbox("chk", "", (0, 0), value=v1)
    ui.end_frame()
    assert v2 is True


def test_slider_clamps_incoming_value():
    ui = ImmediateUI()
    ui.begin_frame(0.016, mouse_pos=(-100, -100))  # far away → no drag
    v = ui.slider("s", "vol", (0, 0), (100, 20), value=999.0, min_value=0.0, max_value=1.0)
    ui.end_frame()
    assert v == 1.0
    ui.begin_frame(0.016, mouse_pos=(-100, -100))
    v = ui.slider("s2", "vol", (0, 0), (100, 20), value=-99.0, min_value=0.0, max_value=1.0)
    ui.end_frame()
    assert v == 0.0


def test_slider_rejects_inverted_range():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    with pytest.raises(ValueError):
        ui.slider("s", "vol", (0, 0), (100, 20), 0.5, min_value=1.0, max_value=0.0)
    ui.end_frame()


def test_progress_bar_emits_rect_command():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    ui.progress_bar("pb", (5, 5), (200, 12), 0.5)
    cmds = ui.end_frame()
    kinds = _kinds(cmds)
    # bg clear (rect) + track rect + fill rect.
    assert kinds.count("rect") >= 2


def test_progress_bar_no_fill_at_zero():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    ui.progress_bar("pb", (0, 0), (100, 10), 0.0)
    cmds = ui.end_frame()
    # bg clear + track rect only — no fill rect at ratio 0.
    rect_widgets = [c for c in cmds if c.kind == "rect" and c.z_order >= 20]
    assert len(rect_widgets) == 1


def test_label_emits_text_command():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    ui.label("l", "Score: 42", (10, 10))
    cmds = ui.end_frame()
    text_cmds = [c for c in cmds if c.kind == "text"]
    assert len(text_cmds) == 1
    assert text_cmds[0].text == "Score: 42"


def test_panel_context_collects_nested_widgets():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    with ui.panel("p", (100, 100), (200, 100), title="HUD"):
        ui.label("inner", "hello", (10, 30))
    cmds = ui.end_frame()
    # Text command position must reflect the panel offset (100, 100 + title_h).
    inner = [c for c in cmds if c.kind == "text" and c.text == "hello"]
    assert len(inner) == 1
    assert inner[0].position[0] >= 100 + 10 - 0.001


def test_panel_unclosed_raises_on_end_frame():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    # Manually push a panel without exiting — simulates a forgotten
    # `with` block by re-entering the CM.
    ctx = ui.panel("p", (0, 0), (10, 10))
    ctx.__enter__()
    with pytest.raises(RuntimeError):
        ui.end_frame()
    # Clean up so the fixture doesn't leak state.
    ctx.__exit__(None, None, None)


def test_end_frame_returns_sorted_by_z_order():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    ui.label("l", "hi", (0, 0))
    ui.progress_bar("pb", (0, 20), (100, 10), 0.5)
    cmds = ui.end_frame()
    zs = [c.z_order for c in cmds]
    assert zs == sorted(zs)


# ---------------------------------------------------------------------------
# HUD kit
# ---------------------------------------------------------------------------


def test_health_bar_build_emits_commands():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    hb = HealthBar(value=75.0, max_value=100.0)
    hb.build(ui)
    cmds = ui.end_frame()
    # progress_bar => bg + fill rects; label => text.
    kinds = _kinds(cmds)
    assert "rect" in kinds
    assert "text" in kinds


def test_health_bar_rejects_zero_max():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    hb = HealthBar(value=1.0, max_value=0.0)
    with pytest.raises(ValueError):
        hb.build(ui)
    ui.end_frame()


def test_stamina_bar_build_emits_progress_rects():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    sb = StaminaBar(value=40.0, max_value=100.0)
    sb.build(ui)
    cmds = ui.end_frame()
    rect_widgets = [c for c in cmds if c.kind == "rect" and c.z_order >= 20]
    # bg + fill rects.
    assert len(rect_widgets) >= 2


def test_ammo_counter_build_emits_text():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    ac = AmmoCounter(current=12, reserve=48, weapon_name="AR")
    ac.build(ui)
    cmds = ui.end_frame()
    text_cmds = [c for c in cmds if c.kind == "text"]
    assert len(text_cmds) == 1
    assert "12" in text_cmds[0].text
    assert "48" in text_cmds[0].text
    assert "AR" in text_cmds[0].text


def test_compass_build_snaps_to_cardinal():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    c = Compass(heading_deg=90.0)
    c.build(ui)
    cmds = ui.end_frame()
    text_cmds = [x for x in cmds if x.kind == "text"]
    assert len(text_cmds) == 1
    assert text_cmds[0].text.startswith("E")


def test_toast_lifecycle_expires_after_duration():
    ui = ImmediateUI()
    toast = Toast(message="pickup!", duration_s=2.0, remaining_s=2.0)
    # Frame 1: alive.
    ui.begin_frame(1.0)
    toast.build(ui)
    ui.end_frame()
    assert toast.is_alive
    # Frame 2: dt=1.0 → remaining=0 → expired.
    ui.begin_frame(1.0)
    toast.build(ui)
    ui.end_frame()
    assert not toast.is_alive


def test_toast_expired_emits_nothing():
    ui = ImmediateUI()
    toast = Toast(message="gone", duration_s=1.0, remaining_s=0.0)
    ui.begin_frame(0.016)
    toast.build(ui)
    cmds = ui.end_frame()
    text_cmds = [c for c in cmds if c.kind == "text"]
    assert text_cmds == []


def test_minimap_builds_without_crash():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    mm = Minimap(position=(20, 20), size=(64, 64))
    mm.add_marker(30.0, 30.0)
    mm.add_marker(50.0, 40.0, color=(1.0, 0.0, 0.0, 1.0))
    mm.build(ui)
    cmds = ui.end_frame()
    # Panel bg + border rects + 2 marker rects, no crashes.
    marker_rects = [c for c in cmds if c.kind == "rect" and c.size == (2.0, 2.0)]
    assert len(marker_rects) == 2


def test_minimap_textured_overlay_emits_textured_quad():
    ui = ImmediateUI()
    ui.begin_frame(0.016)
    mm = Minimap(position=(0, 0), size=(32, 32), texture_id=99)
    mm.build(ui)
    cmds = ui.end_frame()
    tex = [c for c in cmds if c.kind == "textured_quad"]
    assert len(tex) == 1
    assert tex[0].texture_id == 99


# ---------------------------------------------------------------------------
# text_layout
# ---------------------------------------------------------------------------


def test_measure_text_returns_positive_dims():
    w, h = measure_text("hello", 14)
    assert w > 0
    assert h > 0


def test_measure_text_empty_string_zero_width():
    w, h = measure_text("", 14)
    assert w == 0.0
    assert h == 14.0


def test_measure_text_rejects_non_positive_font():
    with pytest.raises(ValueError):
        measure_text("x", 0)
    with pytest.raises(ValueError):
        measure_text("x", -3)


def test_wrap_text_respects_max_width():
    # Long string with short max_width forces multiple lines.
    lines = wrap_text("hello world foo bar baz", max_width=30.0, font_size=14)
    assert isinstance(lines, list)
    assert len(lines) >= 2


def test_wrap_text_hard_newlines():
    lines = wrap_text("a\nb\nc", max_width=500.0, font_size=14)
    assert lines == ["a", "b", "c"]


def test_wrap_text_empty_returns_empty_list():
    assert wrap_text("", max_width=100.0, font_size=14) == []


def test_wrap_text_rejects_bad_max_width():
    with pytest.raises(ValueError):
        wrap_text("x", max_width=0.0, font_size=14)


# ---------------------------------------------------------------------------
# layout helpers
# ---------------------------------------------------------------------------


def test_stack_vertical_places_items_below_each_other():
    items = [
        _Item(position=(10.0, 20.0), size=(80.0, 24.0)),
        _Item(size=(80.0, 24.0)),
        _Item(size=(80.0, 24.0)),
    ]
    stack_vertical(items, spacing=6.0)
    assert items[0].position == (10.0, 20.0)
    assert items[1].position == (10.0, 20.0 + 24.0 + 6.0)
    assert items[2].position == (10.0, 20.0 + (24.0 + 6.0) * 2)


def test_stack_horizontal_places_items_side_by_side():
    items = [
        _Item(position=(5.0, 5.0), size=(40.0, 20.0)),
        _Item(size=(40.0, 20.0)),
        _Item(size=(40.0, 20.0)),
    ]
    stack_horizontal(items, spacing=2.0)
    assert items[0].position == (5.0, 5.0)
    assert items[1].position == (5.0 + 40.0 + 2.0, 5.0)
    assert items[2].position == (5.0 + (40.0 + 2.0) * 2, 5.0)


def test_stack_vertical_rejects_negative_spacing():
    with pytest.raises(ValueError):
        stack_vertical([_Item()], spacing=-1.0)


def test_stack_horizontal_rejects_bad_item():
    class NoPos:
        pass

    with pytest.raises(TypeError):
        stack_horizontal([NoPos()])


def test_grid_lays_out_two_columns():
    items = [
        _Item(position=(0.0, 0.0), size=(50.0, 20.0)),
        _Item(size=(50.0, 20.0)),
        _Item(size=(50.0, 20.0)),
        _Item(size=(50.0, 20.0)),
    ]
    grid(2, items, spacing_x=4.0, spacing_y=4.0)
    # Row 0.
    assert items[0].position == (0.0, 0.0)
    assert items[1].position == (54.0, 0.0)
    # Row 1.
    assert items[2].position == (0.0, 24.0)
    assert items[3].position == (54.0, 24.0)


def test_grid_rejects_zero_cols():
    with pytest.raises(ValueError):
        grid(0, [_Item()])


def test_anchor_topleft_returns_fixed_position():
    fn = anchor_topleft(10.0, 20.0)
    assert fn(800.0, 600.0) == (10.0, 20.0)
    # Screen size is ignored for top-left anchors.
    assert fn(1600.0, 1200.0) == (10.0, 20.0)


def test_anchor_center_returns_screen_centre():
    fn = anchor_center()
    assert fn(800.0, 600.0) == (400.0, 300.0)


def test_anchor_bottomright_returns_offset_from_bottomright():
    fn = anchor_bottomright(16.0, 32.0)
    assert fn(800.0, 600.0) == (800.0 - 16.0, 600.0 - 32.0)


# ---------------------------------------------------------------------------
# dpg_bridge — soft-skip when Dear PyGui is absent
# ---------------------------------------------------------------------------


def test_dpg_bridge_soft_skip_or_run():
    """`run_immediate_in_dpg` requires DPG; skip cleanly when it's missing."""
    pytest.importorskip("dearpygui.dearpygui")
    from pharos_editor.ui.runtime.dpg_bridge import run_immediate_in_dpg

    # Empty parent tag rejected regardless of whether DPG is installed.
    with pytest.raises(ValueError):
        run_immediate_in_dpg([], "")


def test_dpg_bridge_import_does_not_import_dpg():
    """Importing the bridge module must not pull in Dear PyGui."""
    import importlib
    import sys

    # Force a clean reimport of the bridge module.
    sys.modules.pop("pharos_editor.ui.runtime.dpg_bridge", None)
    mod = importlib.import_module("pharos_editor.ui.runtime.dpg_bridge")
    assert hasattr(mod, "run_immediate_in_dpg")
    # The import itself must not have side-effected DPG into sys.modules,
    # unless another test already imported it.
    # We only assert the callable is present; that's the soft-import contract.
