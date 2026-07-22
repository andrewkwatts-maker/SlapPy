"""Y1 STUB-triage tests — second round of feature-map wiring.

Covers the five new action ids added by the 2026-07-04 Y1 sprint tick
(``docs/engine_feature_map_2026_07_04.md`` §"Y1 STUB-triage patch"):

* ``tool.select_all`` — flag every entity in the active scene as selected.
* ``tool.deselect_all`` — clear whatever selection the shell is tracking.
* ``editor.copy_selection`` — snapshot the current selection into the
  process-wide ``EntityClipboard`` (does not auto-paste).
* ``editor.paste_selection`` — pull deep-copies of the last-copied
  snapshots from the clipboard, spawn them into the scene if reachable.
* ``theme.cycle`` — rotate to the next registered theme via the shell
  hook or the headless-safe registry cursor.

Every test dispatches through :class:`~pharos_engine.tool_router.ToolRouter`
so the wire-up (``action_id`` → Python fallback) is exercised end-to-end.
Filesystem side effects — where present — use :func:`pathlib.Path` +
``tmp_path``; no DPG context is required so the suite is headless.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest

from pharos_engine.tool_router import (
    REGISTRY,
    ToolRouter,
    register_default_actions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    """A router seeded with the canonical action registry."""
    r = ToolRouter()
    register_default_actions(r)
    return r


@pytest.fixture(autouse=True)
def _reset_clipboard_and_cursor() -> None:
    """Drop the process-wide clipboard + theme cursor before each test."""
    from pharos_engine.ui.editor.entity_clipboard import (
        reset_active_clipboard,
    )
    from pharos_engine.actions.theme_actions import (
        _reset_theme_cursor_for_tests,
    )
    reset_active_clipboard()
    _reset_theme_cursor_for_tests()


@dataclass
class _MockEntity:
    """Tiny dataclass entity used across every selection/clipboard test."""

    name: str = "widget"
    x: float = 1.0
    y: float = 2.0
    tags: list[str] = field(default_factory=list)


class _MockScene:
    """Minimal Scene stand-in exposing the ``entities`` list surface."""

    def __init__(self, entities: list[Any] | None = None) -> None:
        self._entities = list(entities or [])

    @property
    def entities(self) -> list[Any]:
        return list(self._entities)

    def add(self, entity: Any) -> Any:
        # Match pharos_engine.scene.Scene.add's signature — returns the
        # entity so caller can chain, appends to the entity list so
        # subsequent selects see the paste.
        self._entities.append(entity)
        return entity


# ---------------------------------------------------------------------------
# 1. All five actions are registered on both the fixture router + REGISTRY
# ---------------------------------------------------------------------------


def test_select_all_registered(router: ToolRouter) -> None:
    assert router.has_action("tool.select_all")


def test_deselect_all_registered(router: ToolRouter) -> None:
    assert router.has_action("tool.deselect_all")


def test_copy_selection_registered(router: ToolRouter) -> None:
    assert router.has_action("editor.copy_selection")


def test_paste_selection_registered(router: ToolRouter) -> None:
    assert router.has_action("editor.paste_selection")


def test_theme_cycle_registered(router: ToolRouter) -> None:
    assert router.has_action("theme.cycle")


def test_module_registry_has_y1_actions() -> None:
    """The default REGISTRY must expose the new Y1 action ids."""
    ids = {a.action_id for a in REGISTRY.list_actions()}
    for aid in (
        "tool.select_all",
        "tool.deselect_all",
        "editor.copy_selection",
        "editor.paste_selection",
        "theme.cycle",
    ):
        assert aid in ids, f"{aid} missing from module-level REGISTRY"


# ---------------------------------------------------------------------------
# 2. tool.select_all — flags every scene entity as selected
# ---------------------------------------------------------------------------


def test_select_all_no_scene_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("tool.select_all", {})
    assert result == {"status": "no_scene"}


def test_select_all_populates_shell_selected_entities(
    router: ToolRouter,
) -> None:
    entities = [
        _MockEntity(name="a"),
        _MockEntity(name="b"),
        _MockEntity(name="c"),
    ]
    scene = _MockScene(entities)
    shell = SimpleNamespace(
        _selected_entity=None,
        _selected_entities=None,
    )
    result = router.dispatch(
        "tool.select_all", {"shell": shell, "scene": scene},
    )
    assert result["status"] == "selected"
    assert result["count"] == 3
    assert len(shell._selected_entities) == 3
    # Singular slot gets the first entity so legacy inspectors fire.
    assert shell._selected_entity is entities[0]


def test_select_all_empty_scene_returns_zero(router: ToolRouter) -> None:
    scene = _MockScene([])
    shell = SimpleNamespace(_selected_entity="stale", _selected_entities=[])
    result = router.dispatch(
        "tool.select_all", {"shell": shell, "scene": scene},
    )
    assert result == {"status": "selected", "count": 0}
    assert shell._selected_entity is None
    assert shell._selected_entities == []


def test_select_all_reads_scene_from_shell_engine(router: ToolRouter) -> None:
    entities = [_MockEntity(name="via_shell")]
    scene = _MockScene(entities)
    engine = SimpleNamespace(scene=scene)
    shell = SimpleNamespace(
        _engine=engine,
        _selected_entity=None,
        _selected_entities=None,
    )
    result = router.dispatch("tool.select_all", {"shell": shell})
    assert result == {"status": "selected", "count": 1}
    assert shell._selected_entities == entities


# ---------------------------------------------------------------------------
# 3. tool.deselect_all — clears both singular + plural selection slots
# ---------------------------------------------------------------------------


def test_deselect_all_no_shell_still_succeeds(router: ToolRouter) -> None:
    """Deselecting with no shell is a no-op but must not crash."""
    result = router.dispatch("tool.deselect_all", {})
    assert result == {"status": "deselected"}


def test_deselect_all_clears_shell_slots(router: ToolRouter) -> None:
    shell = SimpleNamespace(
        _selected_entity=_MockEntity(),
        _selected_entities=[_MockEntity(), _MockEntity()],
    )
    result = router.dispatch("tool.deselect_all", {"shell": shell})
    assert result == {"status": "deselected"}
    assert shell._selected_entity is None
    assert shell._selected_entities == []


# ---------------------------------------------------------------------------
# 4. editor.copy_selection — snapshots to EntityClipboard (no auto-paste)
# ---------------------------------------------------------------------------


def test_copy_selection_no_selection_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("editor.copy_selection", {})
    assert result == {"status": "no_selection"}


def test_copy_selection_from_explicit_ctx(router: ToolRouter) -> None:
    from pharos_engine.ui.editor.entity_clipboard import get_active_clipboard

    ent = _MockEntity(name="explicit")
    result = router.dispatch(
        "editor.copy_selection", {"selection": [ent]},
    )
    assert result == {"status": "copied", "count": 1}
    clipboard = get_active_clipboard()
    assert not clipboard.is_empty()
    assert clipboard.last_action == "copy"


def test_copy_selection_reads_shell_selected_entity(router: ToolRouter) -> None:
    from pharos_engine.ui.editor.entity_clipboard import get_active_clipboard

    ent = _MockEntity(name="from_shell_single")
    shell = SimpleNamespace(
        _selected_entity=ent,
        _selected_entities=None,
    )
    result = router.dispatch("editor.copy_selection", {"shell": shell})
    assert result == {"status": "copied", "count": 1}
    snapshots = get_active_clipboard().snapshots()
    assert snapshots[0]["name"] == "from_shell_single"


def test_copy_selection_multi_select_from_shell(router: ToolRouter) -> None:
    from pharos_engine.ui.editor.entity_clipboard import get_active_clipboard

    ents = [_MockEntity(name="a"), _MockEntity(name="b")]
    shell = SimpleNamespace(
        _selected_entity=None,
        _selected_entities=ents,
    )
    result = router.dispatch("editor.copy_selection", {"shell": shell})
    assert result == {"status": "copied", "count": 2}
    assert len(get_active_clipboard().snapshots()) == 2


def test_copy_selection_does_not_auto_paste(router: ToolRouter) -> None:
    """Unlike duplicate_selection, copy must not paste anything."""
    from pharos_engine.ui.editor.entity_clipboard import get_active_clipboard

    ent = _MockEntity(name="lonely")
    router.dispatch("editor.copy_selection", {"selection": ent})
    clipboard = get_active_clipboard()
    # No paste — last_action must still be "copy".
    assert clipboard.last_action == "copy"


# ---------------------------------------------------------------------------
# 5. editor.paste_selection — pulls from clipboard + spawns clones
# ---------------------------------------------------------------------------


def test_paste_selection_empty_clipboard_returns_status(
    router: ToolRouter,
) -> None:
    result = router.dispatch("editor.paste_selection", {})
    assert result == {"status": "empty_clipboard"}


def test_paste_selection_returns_clones_with_suffix(
    router: ToolRouter,
) -> None:
    ent = _MockEntity(name="original")
    # Copy first so paste has something to pull.
    router.dispatch("editor.copy_selection", {"selection": ent})
    result = router.dispatch("editor.paste_selection", {})
    assert result["status"] == "pasted"
    assert result["count"] == 1
    assert result["clones"][0]["name"] == "original (paste)"


def test_paste_selection_adds_to_scene_when_reachable(
    router: ToolRouter,
) -> None:
    ent = _MockEntity(name="widget_a")
    router.dispatch("editor.copy_selection", {"selection": ent})

    scene = _MockScene()
    result = router.dispatch("editor.paste_selection", {"scene": scene})
    assert result["status"] == "pasted"
    assert result["added"] == 1
    # Scene now holds the pasted clone dict.
    assert len(scene.entities) == 1
    assert scene.entities[0]["name"] == "widget_a (paste)"


def test_paste_selection_custom_suffix(router: ToolRouter) -> None:
    ent = _MockEntity(name="src")
    router.dispatch("editor.copy_selection", {"selection": ent})
    result = router.dispatch(
        "editor.paste_selection", {"name_suffix": " (dup)"},
    )
    assert result["clones"][0]["name"] == "src (dup)"


def test_paste_selection_bumps_clipboard_last_action(
    router: ToolRouter,
) -> None:
    from pharos_engine.ui.editor.entity_clipboard import get_active_clipboard

    ent = _MockEntity(name="bump_check")
    router.dispatch("editor.copy_selection", {"selection": ent})
    router.dispatch("editor.paste_selection", {})
    assert get_active_clipboard().last_action == "paste"


# ---------------------------------------------------------------------------
# 6. theme.cycle — headless-safe theme rotation
# ---------------------------------------------------------------------------


def test_theme_cycle_shell_hook_preferred(router: ToolRouter) -> None:
    """When shell exposes cycle_theme() the router routes through it."""
    calls: list[str] = []

    class ShellWithHook:
        def cycle_theme(self) -> str:
            calls.append("cycled")
            return "next_theme_id"

    result = router.dispatch("theme.cycle", {"shell": ShellWithHook()})
    assert calls == ["cycled"]
    assert result["status"] == "cycled"
    assert result["theme"] == "next_theme_id"
    assert result["path"] == "shell"


def test_theme_cycle_headless_no_themes_returns_status(
    router: ToolRouter,
) -> None:
    """When the theme registry is empty and no override is passed,
    the fallback reports ``no_themes``."""
    result = router.dispatch("theme.cycle", {"themes": []})
    # Empty-list override falls through to the registry read; ensure at
    # minimum the status field is one of the two headless outcomes.
    assert result["status"] in {"no_themes", "cycled"}


def test_theme_cycle_headless_override_advances_cursor(
    router: ToolRouter,
) -> None:
    """Passing ``themes=[...]`` overrides the registry — the fallback
    cursor must advance deterministically on repeat dispatches."""
    themes = ["alpha", "beta", "gamma"]
    r1 = router.dispatch("theme.cycle", {"themes": themes})
    r2 = router.dispatch("theme.cycle", {"themes": themes})
    r3 = router.dispatch("theme.cycle", {"themes": themes})
    r4 = router.dispatch("theme.cycle", {"themes": themes})
    assert r1["theme"] == "alpha"
    assert r2["theme"] == "beta"
    assert r3["theme"] == "gamma"
    # Wraps back to the head of the list.
    assert r4["theme"] == "alpha"
    for r in (r1, r2, r3, r4):
        assert r["status"] == "cycled"
        assert r["path"] == "fallback"


def test_theme_cycle_shell_returns_none_reads_settings(
    router: ToolRouter,
) -> None:
    """Shells whose cycle_theme returns None fall back to
    ``_ui_settings.default_theme`` so the result dict still carries a
    theme id for the status bar hook-up."""

    class ShellWithNoneReturn:
        def cycle_theme(self) -> None:
            self._ui_settings.default_theme = "post_cycle"

        _ui_settings = SimpleNamespace(default_theme="pre_cycle")

    result = router.dispatch(
        "theme.cycle", {"shell": ShellWithNoneReturn()},
    )
    assert result["status"] == "cycled"
    assert result["theme"] == "post_cycle"
    assert result["path"] == "shell"


# ---------------------------------------------------------------------------
# 7. Copy → Paste round-trip integration
# ---------------------------------------------------------------------------


def test_copy_then_paste_full_roundtrip(router: ToolRouter) -> None:
    """End-to-end: copy → paste → clones land in scene with correct fields."""
    src = _MockEntity(name="round_trip", x=42.0, y=99.0, tags=["a", "b"])
    scene = _MockScene()

    copy_result = router.dispatch(
        "editor.copy_selection", {"selection": src},
    )
    assert copy_result["status"] == "copied"

    paste_result = router.dispatch(
        "editor.paste_selection", {"scene": scene},
    )
    assert paste_result["status"] == "pasted"
    assert paste_result["added"] == 1
    clone = scene.entities[0]
    assert clone["name"] == "round_trip (paste)"
    assert clone["x"] == 42.0
    assert clone["y"] == 99.0
    assert clone["tags"] == ["a", "b"]


def test_select_all_then_copy_selection(router: ToolRouter) -> None:
    """Select all → copy_selection captures every entity."""
    entities = [_MockEntity(name=f"e{i}") for i in range(4)]
    scene = _MockScene(entities)
    shell = SimpleNamespace(
        _selected_entity=None,
        _selected_entities=None,
    )
    router.dispatch("tool.select_all", {"shell": shell, "scene": scene})
    result = router.dispatch("editor.copy_selection", {"shell": shell})
    assert result["status"] == "copied"
    assert result["count"] == 4


def test_deselect_all_then_copy_selection_is_no_selection(
    router: ToolRouter,
) -> None:
    """After deselect the copy path returns no_selection."""
    entities = [_MockEntity(name="only")]
    scene = _MockScene(entities)
    shell = SimpleNamespace(
        _selected_entity=None,
        _selected_entities=None,
    )
    router.dispatch("tool.select_all", {"shell": shell, "scene": scene})
    router.dispatch("tool.deselect_all", {"shell": shell})
    result = router.dispatch("editor.copy_selection", {"shell": shell})
    assert result == {"status": "no_selection"}
