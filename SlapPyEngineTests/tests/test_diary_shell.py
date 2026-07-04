"""Tests for the diary-book main-window shell.

Verifies :class:`DiaryShell`'s contract:

* Constructs against a minimal editor-shell stand-in with no DPG.
* Default 6 pages register (Scene, Code, Material, Animation, FX,
  Settings) with sane tab colours + panel lists.
* :meth:`switch_page` shows every target panel wrapper and hides
  every non-target wrapper referenced by any other page.
* Active page id + tracking counters advance on each switch.
* Ctrl+Tab / Ctrl+Shift+Tab route through :class:`NotebookHotkeys`
  and cycle pages with wrap-around.
* Custom pages can be added + removed; a removed active page falls
  back to the first remaining page.
* Tab colours: active tabs render at full saturation, inactive tabs
  desaturate 30 % toward a neutral cream.
* Applied layout preset matches the target page's descriptor.

Runs entirely headless — no ``dearpygui`` dependency; every panel
wrapper is a Python stand-in that just records show / hide calls.
"""
from __future__ import annotations

from typing import Any

import pytest

from slappyengine.ui.editor.diary_shell import (
    CMD_NEXT_PAGE,
    CMD_PREV_PAGE,
    DEFAULT_PAGES,
    DiaryPage,
    DiaryShell,
    PANEL_ID_ALIAS,
    _resolve_panel_key,
)
from slappyengine.ui.editor.notebook_hotkeys import NotebookHotkeys


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeWrapper:
    """Minimal :class:`MovablePanelWindow` stand-in — records show/hide."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._visible = True
        self.show_calls = 0
        self.hide_calls = 0

    def show(self) -> None:
        self._visible = True
        self.show_calls += 1

    def hide(self) -> None:
        self._visible = False
        self.hide_calls += 1

    def is_visible(self) -> bool:
        return self._visible


class _FakeStatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def set_message(self, msg: str, kind: str = "info") -> None:
        self.messages.append((msg, kind))


class _FakeShell:
    """The subset of :class:`EditorShell` DiaryShell reads."""

    def __init__(self, panel_ids: list[str] | None = None) -> None:
        # Union of every default-page panel + a couple of legacy IDs
        # ensures the show/hide plumbing has real wrappers to poke.
        if panel_ids is None:
            union = set()
            for page in DEFAULT_PAGES:
                for pid in page.panels:
                    union.add(_resolve_panel_key(pid))
            panel_ids = sorted(union)
        self._panel_windows: dict[str, _FakeWrapper] = {
            pid: _FakeWrapper(pid) for pid in panel_ids
        }
        self._notebook_status_bar = _FakeStatusBar()
        self._running = False  # keeps apply_preset off the DPG path
        # Preset routing side-effects land here.
        self._panel_layout_state: dict = {}
        self._active_layout_preset: str | None = None


# ---------------------------------------------------------------------------
# Construction + defaults
# ---------------------------------------------------------------------------


def test_diary_shell_constructs():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    assert diary.editor_shell is shell
    assert diary.switch_count == 0
    assert diary.get_active_page() is None


def test_diary_shell_rejects_none_editor_shell():
    with pytest.raises(TypeError):
        DiaryShell(None)  # type: ignore[arg-type]


def test_default_pages_count_is_six():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    assert len(diary.list_pages()) == 6


def test_default_page_ids_match_spec():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    ids = [p.id for p in diary.list_pages()]
    assert ids == ["scene", "code", "material", "animation", "fx", "settings"]


def test_default_page_colors_are_in_range():
    for page in DEFAULT_PAGES:
        assert isinstance(page.color, tuple) and len(page.color) == 3
        for channel in page.color:
            assert 0 <= channel <= 255


def test_default_pages_reference_only_string_panel_ids():
    for page in DEFAULT_PAGES:
        assert page.panels
        for pid in page.panels:
            assert isinstance(pid, str) and pid


def test_scene_page_carries_expected_panels():
    scene = next(p for p in DEFAULT_PAGES if p.id == "scene")
    assert "notebook_toolbar" in scene.panels
    assert "notebook_outliner" in scene.panels
    assert "notebook_inspector" in scene.panels
    assert scene.default_layout_preset == "default"


def test_fx_page_uses_focus_preset():
    fx = next(p for p in DEFAULT_PAGES if p.id == "fx")
    assert fx.default_layout_preset == "focus"


# ---------------------------------------------------------------------------
# switch_page — show/hide routing
# ---------------------------------------------------------------------------


def test_switch_page_activates_target():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    page = diary.switch_page("code")
    assert page.id == "code"
    assert diary.get_active_page_id() == "code"
    assert diary.get_active_page().id == "code"


def test_switch_page_shows_target_panels():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("code")
    for pid in ("toolbar", "content_browser", "code_panel", "status_bar"):
        wrapper = shell._panel_windows.get(pid)
        if wrapper is None:
            continue
        assert wrapper.is_visible(), f"{pid} should be visible on Code page"


def test_switch_page_hides_other_pages_panels():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    # Move to Settings — Settings only shows theme_switcher + status_bar,
    # so outliner + inspector + material_editor etc. must all hide.
    diary.switch_page("settings")
    hidden_expected = ("outliner", "inspector", "material_editor",
                        "code_panel", "animation_panel",
                        "post_process_panel", "telemetry_panel")
    for pid in hidden_expected:
        wrapper = shell._panel_windows.get(pid)
        if wrapper is None:
            continue
        assert not wrapper.is_visible(), f"{pid} should be hidden on Settings"


def test_switch_page_bumps_counter():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("scene")
    diary.switch_page("code")
    diary.switch_page("scene")
    assert diary.switch_count == 3


def test_switch_page_unknown_id_raises():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    with pytest.raises(KeyError):
        diary.switch_page("nonexistent_page")


def test_switch_page_applies_layout_preset():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("code")
    # Code page uses wide_code preset.
    assert diary.last_preset_applied == "wide_code"
    assert shell._active_layout_preset == "wide_code"


def test_switch_page_pushes_status_message():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("material")
    msgs = shell._notebook_status_bar.messages
    assert any("Material" in m for m, _ in msgs)


# ---------------------------------------------------------------------------
# Cycling
# ---------------------------------------------------------------------------


def test_next_page_advances_from_none_to_first():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    page = diary.next_page()
    assert page.id == "scene"


def test_next_page_advances_to_neighbor():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("scene")
    page = diary.next_page()
    assert page.id == "code"


def test_next_page_wraps_around():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("settings")   # last default page
    page = diary.next_page()
    assert page.id == "scene"


def test_prev_page_wraps_around():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("scene")
    page = diary.prev_page()
    assert page.id == "settings"


def test_cycle_page_rejects_zero_direction():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    with pytest.raises(ValueError):
        diary.cycle_page(0)


# ---------------------------------------------------------------------------
# Custom page management
# ---------------------------------------------------------------------------


def test_add_custom_page():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    custom = DiaryPage(
        id="scripting",
        label="Scripts",
        color=(255, 200, 100),
        panels=["notebook_toolbar", "notebook_code_panel", "notebook_status_bar"],
        default_layout_preset="wide_code",
    )
    diary.add_page(custom)
    assert diary.has_page("scripting")
    assert len(diary.list_pages()) == 7


def test_add_duplicate_page_raises():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    dup = DiaryPage(
        id="scene", label="X", color=(0, 0, 0), panels=["notebook_toolbar"],
    )
    with pytest.raises(ValueError):
        diary.add_page(dup)


def test_create_custom_page_helper():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    page = diary.create_custom_page(
        page_id="notes", label="Notes", color=(120, 220, 200),
    )
    assert diary.has_page("notes")
    assert diary.page_created_count == 1
    assert page.default_layout_preset == "default"


def test_remove_page():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.remove_page("fx")
    assert not diary.has_page("fx")
    assert len(diary.list_pages()) == 5


def test_remove_active_page_falls_back():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("code")
    diary.remove_page("code")
    active = diary.get_active_page()
    assert active is not None
    # Should have fallen back to the first remaining page (scene).
    assert active.id == "scene"


def test_remove_unknown_page_raises():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    with pytest.raises(KeyError):
        diary.remove_page("does_not_exist")


# ---------------------------------------------------------------------------
# Hotkey wiring
# ---------------------------------------------------------------------------


def test_install_hotkeys_registers_ctrl_tab():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    dispatched: list[str] = []
    hk = NotebookHotkeys(command_dispatcher=dispatched.append)
    diary.install_hotkeys(hk)
    assert hk.BINDINGS.get("ctrl+tab") == CMD_NEXT_PAGE
    assert hk.BINDINGS.get("ctrl+shift+tab") == CMD_PREV_PAGE


def test_hotkey_ctrl_tab_dispatches_diary_command():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    dispatched: list[str] = []
    hk = NotebookHotkeys(command_dispatcher=dispatched.append)
    diary.install_hotkeys(hk)
    ok = hk.handle_key_event("tab", ["ctrl"])
    assert ok is True
    assert CMD_NEXT_PAGE in dispatched


def test_dispatch_command_next_cycles():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("scene")
    diary.dispatch_command(CMD_NEXT_PAGE)
    assert diary.get_active_page_id() == "code"


def test_dispatch_command_prev_cycles():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.switch_page("code")
    diary.dispatch_command(CMD_PREV_PAGE)
    assert diary.get_active_page_id() == "scene"


def test_dispatch_command_direct_switch():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    assert diary.dispatch_command("editor.diary_switch_material") is True
    assert diary.get_active_page_id() == "material"


def test_dispatch_command_returns_false_for_unknown():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    assert diary.dispatch_command("editor.unrelated_command") is False


# ---------------------------------------------------------------------------
# Tab geometry + colour
# ---------------------------------------------------------------------------


def test_tab_bounds_stacks_vertically():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    b0 = diary.tab_bounds(0)
    b1 = diary.tab_bounds(1)
    # Same X anchor, Y grows by TAB_HEIGHT + TAB_GAP.
    assert b0[0] == b1[0]
    assert b1[1] - b0[1] == diary.TAB_HEIGHT + diary.TAB_GAP


def test_tab_bounds_size_matches_spec():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    _, _, w, h = diary.tab_bounds(0)
    assert (w, h) == (60, 40)   # matches the brief


def test_tab_bounds_negative_index_raises():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    with pytest.raises(ValueError):
        diary.tab_bounds(-1)


def test_active_tab_color_full_saturation():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    scene = diary.get_page("scene")
    assert diary.tab_color(scene, active=True) == scene.color


def test_inactive_tab_color_desaturated():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    scene = diary.get_page("scene")
    tinted = diary.tab_color(scene, active=False)
    # Inactive drifts toward neutral (230, 224, 210) so every channel
    # shifts *toward* that value — never past.
    for orig, blended, neutral in zip(scene.color, tinted, (230, 224, 210)):
        # Blended sits between orig and neutral (inclusive endpoints).
        lo, hi = sorted((orig, neutral))
        assert lo <= blended <= hi


# ---------------------------------------------------------------------------
# Build + panel-alias resolution
# ---------------------------------------------------------------------------


def test_build_marks_shell_built_and_activates_first_page():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    diary.build()
    assert diary.is_built is True
    assert diary.get_active_page_id() == "scene"
    # Every default-page tab has a minted tag.
    for page in diary.list_pages():
        assert diary.get_tab_tag(page.id) == f"diary_tab_{page.id}"


def test_all_panel_ids_covers_every_page_reference():
    shell = _FakeShell()
    diary = DiaryShell(shell)
    ids = diary.all_panel_ids()
    for page in DEFAULT_PAGES:
        for pid in page.panels:
            assert pid in ids


def test_panel_id_alias_maps_notebook_prefix():
    assert _resolve_panel_key("notebook_toolbar") == "toolbar"
    assert _resolve_panel_key("notebook_content_browser") == "content_browser"
    assert _resolve_panel_key("theme_switcher_panel") == "theme_switcher"


def test_panel_id_alias_falls_through_for_unknown():
    assert _resolve_panel_key("plugin_custom_panel") == "plugin_custom_panel"


def test_panel_id_alias_dict_is_populated():
    assert "notebook_toolbar" in PANEL_ID_ALIAS
    assert "notebook_status_bar" in PANEL_ID_ALIAS


# ---------------------------------------------------------------------------
# Editor integration — DiaryShell attached to EditorShell
# ---------------------------------------------------------------------------


def test_editor_shell_owns_diary_shell():
    # Import lazily so the module cost is only paid when the [editor]
    # extra is exercised.
    from slappyengine.ui.editor.shell import EditorShell

    class _Engine:
        scene = None
    shell = EditorShell(_Engine())
    diary = shell.get_diary_shell()
    assert diary is not None
    assert isinstance(diary, DiaryShell)
    # And DiaryShell already installed Ctrl+Tab bindings on the hotkey
    # table by the time __init__ returns.
    assert shell._notebook_hotkeys.BINDINGS.get("ctrl+tab") == CMD_NEXT_PAGE


def test_editor_shell_dispatches_diary_commands():
    from slappyengine.ui.editor.shell import EditorShell

    class _Engine:
        scene = None
    shell = EditorShell(_Engine())
    diary = shell.get_diary_shell()
    # Prime the diary shell so ``.next_page`` has an anchor.
    diary.switch_page("scene")
    # Route the hotkey command through the shell dispatcher — that's
    # the real production path (NotebookHotkeys → dispatcher →
    # DiaryShell.dispatch_command).
    shell._dispatch_editor_command(CMD_NEXT_PAGE)
    assert diary.get_active_page_id() == "code"
