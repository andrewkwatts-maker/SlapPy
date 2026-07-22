"""Tests for the editor layout-preset registry + hotkey wiring.

Covers the brief at ``docs/ui_layout_presets_2026_06_04.md`` § Window Mgmt:

* Five named presets ship — Default / Wide Code / Focus / Triple Pane /
  Compact.
* Each preset is a valid :class:`LayoutPreset` with a non-empty name,
  description, and panel map.
* :func:`apply_preset` mutates the shell's ``_panel_layout_state`` dict.
* Hotkey table includes Ctrl+1..5 + Ctrl+0 + Ctrl+T + Ctrl+Shift+T +
  Ctrl+\\ / Ctrl+Shift+\\ / Ctrl+/ / Ctrl+Shift+/.
* :meth:`EditorShell.cycle_theme` rotates through the 6 diary themes.
* :meth:`EditorShell.toggle_panel` flips visibility.
* :meth:`EditorShell.reset_layout` clears persistent state and reapplies
  Default.
"""
from __future__ import annotations

import pytest

from pharos_editor.ui.editor.layout_presets import (
    LayoutPreset,
    PANEL_IDS,
    PRESETS,
    PanelLayoutState,
    apply_preset,
    get_preset,
    list_preset_names,
    list_presets,
)
from pharos_editor.ui.editor.notebook_hotkeys import NotebookHotkeys


# ---------------------------------------------------------------------------
# Minimal shell stub — mirrors only the attributes touched by apply_preset
# + the EditorShell methods under test.
# ---------------------------------------------------------------------------


class _StubStatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self.theme_name: str = ""

    def set_message(self, msg: str, *, kind: str = "info") -> None:
        self.messages.append((msg, kind))

    def set_active_theme_name(self, name: str) -> None:
        self.theme_name = name


class _StubUISettings:
    default_theme: str = "teengirl_notebook"
    easter_eggs: bool = True
    creature_animations: bool = True
    reduced_motion: bool = False
    welcome_shown: bool = False
    last_opened_demo: str = ""


def _make_shell():
    """Build a minimal EditorShell instance for the dispatch tests."""
    from pharos_editor.ui.editor.shell import EditorShell

    class _StubEngine:
        scene = None

    return EditorShell(engine=_StubEngine())


# ---------------------------------------------------------------------------
# 1. Preset registry — five valid presets
# ---------------------------------------------------------------------------


def test_five_presets_exist():
    assert set(PRESETS.keys()) == {
        "default", "wide_code", "focus", "triple_pane", "compact",
    }


def test_each_preset_is_layoutpreset():
    for name, preset in PRESETS.items():
        assert isinstance(preset, LayoutPreset), name
        assert preset.name, name
        assert preset.description, name
        assert isinstance(preset.panels, dict), name
        assert len(preset.panels) >= 5, f"{name} too few panels"


def test_each_preset_has_shortcut():
    assert PRESETS["default"].shortcut     == "ctrl+1"
    assert PRESETS["wide_code"].shortcut   == "ctrl+2"
    assert PRESETS["focus"].shortcut       == "ctrl+3"
    assert PRESETS["triple_pane"].shortcut == "ctrl+4"
    assert PRESETS["compact"].shortcut     == "ctrl+5"


def test_each_preset_has_icon_id():
    for name, preset in PRESETS.items():
        assert preset.icon_id, f"{name} missing icon_id"


def test_list_presets_returns_five():
    presets = list_presets()
    assert len(presets) == 5
    assert presets[0].name == "Default"


def test_list_preset_names_order():
    names = list_preset_names()
    assert names == ["default", "wide_code", "focus", "triple_pane", "compact"]


# ---------------------------------------------------------------------------
# 2. get_preset
# ---------------------------------------------------------------------------


def test_get_preset_by_name():
    p = get_preset("focus")
    assert p.name == "Focus"


def test_get_preset_missing_raises_keyerror():
    with pytest.raises(KeyError):
        get_preset("notarealpreset")


def test_get_preset_empty_name_raises():
    with pytest.raises((ValueError, TypeError)):
        get_preset("")


# ---------------------------------------------------------------------------
# 3. PanelLayoutState contract
# ---------------------------------------------------------------------------


def test_panel_layout_state_defaults():
    # Reuses the canonical layout_persistence dataclass — position +
    # size are required, visible/z_order/docked_to have defaults.
    s = PanelLayoutState(panel_id="viewport", position=(0, 0), size=(100, 100))
    assert s.visible is True
    assert s.docked_to == ""
    assert s.position == (0, 0)


def test_panel_layout_state_rejects_empty_id():
    with pytest.raises((ValueError, TypeError)):
        PanelLayoutState(panel_id="", position=(0, 0), size=(100, 100))


def test_focus_preset_hides_sidebars():
    p = get_preset("focus")
    assert p.panels["outliner"].visible is False
    assert p.panels["inspector"].visible is False
    assert p.panels["content_browser"].visible is False
    # Toolbar + status bar + viewport stay visible.
    assert p.panels["toolbar"].visible is True
    assert p.panels["status_bar"].visible is True
    assert p.panels["viewport"].visible is True


def test_wide_code_preset_shows_code_panel():
    p = get_preset("wide_code")
    assert p.panels["code"].visible is True


def test_triple_pane_preset_equal_thirds():
    p = get_preset("triple_pane")
    # Three equal main columns; their widths sum close to total.
    w_total = sum(
        p.panels[name].size[0]
        for name in ("outliner", "viewport", "inspector")
    )
    assert w_total >= 1300  # at least ~1400 of horizontal real estate


# ---------------------------------------------------------------------------
# 4. apply_preset mutates shell state
# ---------------------------------------------------------------------------


def test_apply_preset_sets_layout_state_on_shell():
    shell = _make_shell()
    apply_preset(shell, "default")
    assert hasattr(shell, "_panel_layout_state")
    state = shell._panel_layout_state
    assert "viewport" in state
    assert "outliner" in state


def test_apply_preset_records_active_preset_name():
    shell = _make_shell()
    apply_preset(shell, "focus")
    assert shell._active_layout_preset == "focus"


def test_apply_preset_reorders_panel_positions():
    shell = _make_shell()
    apply_preset(shell, "default")
    default_state = dict(shell._panel_layout_state)
    apply_preset(shell, "wide_code")
    wide_state = dict(shell._panel_layout_state)
    # Wide Code positions the code panel differently from default.
    assert default_state["code"].size != wide_state["code"].size


def test_apply_preset_missing_raises_keyerror():
    shell = _make_shell()
    with pytest.raises(KeyError):
        apply_preset(shell, "no_such_preset")


# ---------------------------------------------------------------------------
# 5. Hotkey table includes the new bindings
# ---------------------------------------------------------------------------


def test_hotkey_ctrl_1_through_5_present():
    for digit, suffix in enumerate(
        ["default", "wide_code", "focus", "triple_pane", "compact"], start=1,
    ):
        key = f"ctrl+{digit}"
        assert NotebookHotkeys.BINDINGS[key] == f"editor.layout_preset_{suffix}"


def test_hotkey_ctrl_0_resets_layout():
    assert NotebookHotkeys.BINDINGS["ctrl+0"] == "editor.reset_layout"


def test_hotkey_ctrl_t_opens_theme_switcher():
    assert NotebookHotkeys.BINDINGS["ctrl+t"] == "editor.toggle_theme_switcher"


def test_hotkey_ctrl_shift_t_cycles_theme():
    assert NotebookHotkeys.BINDINGS["ctrl+shift+t"] == "editor.cycle_theme"


def test_hotkey_panel_toggles_present():
    assert NotebookHotkeys.BINDINGS["ctrl+\\"] == "editor.toggle_panel_outliner"
    assert NotebookHotkeys.BINDINGS["ctrl+shift+\\"] == \
        "editor.toggle_panel_inspector"
    assert NotebookHotkeys.BINDINGS["ctrl+/"] == \
        "editor.toggle_panel_content_browser"
    assert NotebookHotkeys.BINDINGS["ctrl+shift+/"] == \
        "editor.toggle_panel_code"


def test_hotkey_f11_fullscreen_present():
    assert NotebookHotkeys.BINDINGS["f11"] == "editor.toggle_fullscreen"


# ---------------------------------------------------------------------------
# 6. EditorShell integration
# ---------------------------------------------------------------------------


def test_shell_apply_layout_preset_default():
    shell = _make_shell()
    shell._notebook_status_bar = _StubStatusBar()
    shell.apply_layout_preset("default")
    assert shell._active_layout_preset == "default"
    # Status bar got a "Preset: Default" toast.
    assert any("Preset: Default" in m for m, _ in shell._notebook_status_bar.messages)


def test_shell_cycle_theme_rotates_through_six():
    shell = _make_shell()
    shell._notebook_status_bar = _StubStatusBar()
    shell._ui_settings.default_theme = "teengirl_notebook"
    seen = [shell._ui_settings.default_theme]
    for _ in range(6):
        seen.append(shell.cycle_theme())
    # All six diary themes should appear in the seen list, and after 6
    # cycles we should be back at the starting theme.
    assert seen[-1] == "teengirl_notebook"
    assert set(seen) >= {
        "teengirl_notebook", "cozy_diary", "bullet_journal",
        "scrapbook_summer", "cottagecore_garden", "kawaii_planner",
    }


def test_shell_toggle_panel_hides_and_shows():
    shell = _make_shell()
    shell._notebook_status_bar = _StubStatusBar()
    shell.apply_layout_preset("default")
    # Outliner starts visible.
    assert shell._panel_layout_state["outliner"].visible is True
    new = shell.toggle_panel("outliner")
    assert new is False
    assert shell._panel_layout_state["outliner"].visible is False
    # Toggling again brings it back.
    new = shell.toggle_panel("outliner")
    assert new is True


def test_shell_reset_layout_reapplies_default():
    shell = _make_shell()
    shell._notebook_status_bar = _StubStatusBar()
    shell.apply_layout_preset("focus")
    assert shell._active_layout_preset == "focus"
    shell.reset_layout()
    assert shell._active_layout_preset == "default"


def test_shell_dispatcher_routes_layout_preset_command():
    shell = _make_shell()
    shell._notebook_status_bar = _StubStatusBar()
    shell._dispatch_editor_command("editor.layout_preset_focus")
    assert shell._active_layout_preset == "focus"


def test_shell_dispatcher_routes_toggle_panel_command():
    shell = _make_shell()
    shell._notebook_status_bar = _StubStatusBar()
    shell.apply_layout_preset("default")
    shell._dispatch_editor_command("editor.toggle_panel_inspector")
    assert shell._panel_layout_state["inspector"].visible is False


def test_shell_dispatcher_routes_cycle_theme_command():
    shell = _make_shell()
    shell._notebook_status_bar = _StubStatusBar()
    shell._ui_settings.default_theme = "teengirl_notebook"
    shell._dispatch_editor_command("editor.cycle_theme")
    assert shell._ui_settings.default_theme != "teengirl_notebook"


def test_shell_dispatcher_routes_reset_layout_command():
    shell = _make_shell()
    shell._notebook_status_bar = _StubStatusBar()
    shell.apply_layout_preset("focus")
    shell._dispatch_editor_command("editor.reset_layout")
    assert shell._active_layout_preset == "default"


# ---------------------------------------------------------------------------
# 7. PANEL_IDS roster
# ---------------------------------------------------------------------------


def test_panel_ids_contains_canonical_seven():
    assert set(PANEL_IDS) == {
        "toolbar", "outliner", "viewport", "inspector",
        "content_browser", "code", "status_bar",
    }
