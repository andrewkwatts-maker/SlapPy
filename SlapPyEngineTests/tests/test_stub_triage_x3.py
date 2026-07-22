"""X3 STUB-triage tests — top-5 STUB actions wired from
``docs/engine_feature_map_2026_07_04.md``.

Covers the five action ids added in the 2026-07-04 sprint tick:

* ``editor.save_project`` — writes the active project's manifest.
* ``editor.new_project`` — scaffolds a fresh project directory.
* ``editor.open_recent`` — opens (by index or path) an entry from the
  :class:`~pharos_engine.projects.ProjectRegistry` recents list.
* ``view.reset_layout`` — restores the DEFAULT preset via
  :func:`~pharos_engine.ui.editor.layout_presets.apply_preset`.
* ``edit.duplicate_selection`` — clones the current selection through
  :class:`~pharos_engine.ui.editor.entity_clipboard.EntityClipboard`.

Every test dispatches through
:class:`~pharos_engine.tool_router.ToolRouter` so the wire-up (action_id
→ Python fallback) is exercised end-to-end. Filesystem side effects use
:func:`pathlib.Path` + ``tmp_path``; no DPG context is required so the
suite is headless.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pharos_engine.tool_router import REGISTRY, ToolRouter, register_default_actions


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    """A router seeded with the canonical action registry."""
    r = ToolRouter()
    register_default_actions(r)
    return r


@pytest.fixture()
def isolated_registry(tmp_path: Path) -> Any:
    """Return a :class:`ProjectRegistry` pointed at a temp store."""
    from pharos_engine.projects.registry import ProjectRegistry
    store = tmp_path / "projects.yaml"
    return ProjectRegistry(store_path=store)


@pytest.fixture()
def sample_project(tmp_path: Path) -> Any:
    """Create + return a real Project scaffolded under ``tmp_path``."""
    from pharos_engine.projects import Project
    root = tmp_path / "sample_project"
    return Project.new(root=root, name="Sample", scaffold=True)


@dataclass
class _MockEntity:
    """Tiny dataclass entity used by the duplicate-selection tests."""

    name: str = "widget"
    x: float = 1.0
    y: float = 2.0
    tags: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 1. All five actions are registered (5 tests)
# ---------------------------------------------------------------------------


def test_save_project_registered(router: ToolRouter) -> None:
    assert router.has_action("editor.save_project")


def test_new_project_registered(router: ToolRouter) -> None:
    assert router.has_action("editor.new_project")


def test_open_recent_registered(router: ToolRouter) -> None:
    assert router.has_action("editor.open_recent")


def test_view_reset_layout_registered(router: ToolRouter) -> None:
    assert router.has_action("view.reset_layout")


def test_duplicate_selection_registered(router: ToolRouter) -> None:
    assert router.has_action("edit.duplicate_selection")


# ---------------------------------------------------------------------------
# 2. Save Project — writes project.slap_proj (3 tests)
# ---------------------------------------------------------------------------


def test_save_project_dispatch_writes_manifest(
    router: ToolRouter,
    sample_project: Any,
    tmp_path: Path,
) -> None:
    manifest = sample_project.slap_proj_path
    # Poke a description edit then dispatch save — the manifest must
    # include the fresh string on disk after the dispatch returns.
    sample_project.metadata.description = "x3-triage-save"
    result = router.dispatch("editor.save_project", {"project": sample_project})
    assert result is not None
    assert result["status"] == "saved"
    assert manifest.is_file()
    text = manifest.read_text(encoding="utf-8")
    assert "x3-triage-save" in text


def test_save_project_no_project_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("editor.save_project", {})
    assert result == {"status": "no_project"}


def test_save_project_reads_project_from_shell(
    router: ToolRouter,
    sample_project: Any,
) -> None:
    shell = SimpleNamespace(_project=sample_project, _engine=None)
    result = router.dispatch("editor.save_project", {"shell": shell})
    assert result is not None
    assert result["status"] == "saved"
    assert sample_project.slap_proj_path.is_file()


# ---------------------------------------------------------------------------
# 3. New Project — scaffolds directory + manifest (4 tests)
# ---------------------------------------------------------------------------


def test_new_project_dispatch_scaffolds_directory(
    router: ToolRouter,
    tmp_path: Path,
    isolated_registry: Any,
) -> None:
    target = tmp_path / "brand_new"
    result = router.dispatch(
        "editor.new_project",
        {
            "path": str(target),
            "name": "Brand New",
            "description": "fresh project",
            "registry": isolated_registry,
        },
    )
    assert result is not None
    assert result["status"] == "created"
    assert Path(result["path"]).is_dir()
    # scaffold_project lays down scenes/, assets/, scripts/ + the manifest.
    assert (target / "project.slap_proj").is_file()
    assert (target / "scenes").is_dir()


def test_new_project_missing_path_returns_error(router: ToolRouter) -> None:
    result = router.dispatch("editor.new_project", {"name": "X"})
    assert result == {"status": "missing_path"}


def test_new_project_missing_name_returns_error(
    router: ToolRouter,
    tmp_path: Path,
) -> None:
    result = router.dispatch(
        "editor.new_project",
        {"path": str(tmp_path / "will_not_be_made")},
    )
    assert result == {"status": "missing_name"}


def test_new_project_registers_in_registry(
    router: ToolRouter,
    tmp_path: Path,
    isolated_registry: Any,
) -> None:
    target = tmp_path / "in_registry"
    router.dispatch(
        "editor.new_project",
        {
            "path": str(target),
            "name": "Registered",
            "registry": isolated_registry,
        },
    )
    entries = isolated_registry.list_recent(limit=10)
    assert any(Path(e.path).name == target.name for e in entries)


# ---------------------------------------------------------------------------
# 4. Open Recent — pulls from the registry (4 tests)
# ---------------------------------------------------------------------------


def test_open_recent_empty_registry_returns_empty(
    router: ToolRouter,
    isolated_registry: Any,
) -> None:
    result = router.dispatch(
        "editor.open_recent", {"registry": isolated_registry},
    )
    assert result == {"status": "empty"}


def test_open_recent_by_index_opens_first_entry(
    router: ToolRouter,
    tmp_path: Path,
    isolated_registry: Any,
) -> None:
    from pharos_engine.projects import Project

    proj = Project.new(root=tmp_path / "recent_one", name="Recent One")
    isolated_registry.register(proj)

    result = router.dispatch(
        "editor.open_recent",
        {"registry": isolated_registry, "index": 0},
    )
    assert result is not None
    assert result["status"] == "opened"
    assert Path(result["path"]).name == "recent_one"


def test_open_recent_by_path_opens_direct(
    router: ToolRouter,
    tmp_path: Path,
    isolated_registry: Any,
) -> None:
    from pharos_engine.projects import Project

    proj = Project.new(root=tmp_path / "direct_open", name="Direct")
    isolated_registry.register(proj)

    result = router.dispatch(
        "editor.open_recent",
        {"registry": isolated_registry, "path": str(proj.path)},
    )
    assert result is not None
    assert result["status"] == "opened"
    assert Path(result["path"]).name == "direct_open"


def test_open_recent_out_of_range_index_returns_not_found(
    router: ToolRouter,
    tmp_path: Path,
    isolated_registry: Any,
) -> None:
    from pharos_engine.projects import Project

    proj = Project.new(root=tmp_path / "only_one", name="Only One")
    isolated_registry.register(proj)
    result = router.dispatch(
        "editor.open_recent",
        {"registry": isolated_registry, "index": 42},
    )
    assert result["status"] == "not_found"
    assert result["index"] == 42


# ---------------------------------------------------------------------------
# 5. View Reset Layout — restores DEFAULT preset (3 tests)
# ---------------------------------------------------------------------------


def test_reset_layout_no_shell_returns_status(router: ToolRouter) -> None:
    result = router.dispatch("view.reset_layout", {})
    assert result == {"status": "no_shell", "preset": "default"}


def test_reset_layout_shell_hook_dispatch(router: ToolRouter) -> None:
    """Shell exposes apply_layout_preset — router should route through it."""
    calls: list[str] = []

    class FakeShell:
        def apply_layout_preset(self, name: str) -> None:
            calls.append(name)

    result = router.dispatch("view.reset_layout", {"shell": FakeShell()})
    assert result["status"] == "reset"
    assert result["preset"] == "default"
    assert calls == ["default"]


def test_reset_layout_headless_fallback_populates_state(
    router: ToolRouter,
) -> None:
    """When shell lacks apply_layout_preset, apply_preset() is invoked directly.

    The layout_presets fallback populates ``shell._panel_layout_state``
    with every panel id in the DEFAULT preset.
    """
    from pharos_engine.ui.editor.layout_presets import PANEL_IDS

    shell = SimpleNamespace(_running=False)
    result = router.dispatch("view.reset_layout", {"shell": shell})
    assert result["status"] == "reset"
    assert result["path"] == "apply_preset"
    state = getattr(shell, "_panel_layout_state", None)
    assert isinstance(state, dict)
    # Every canonical panel id must appear in the reset-state dict.
    for pid in PANEL_IDS:
        assert pid in state, f"panel {pid!r} missing after reset"


# ---------------------------------------------------------------------------
# 6. Duplicate Selection — EntityClipboard flow (5 tests)
# ---------------------------------------------------------------------------


def test_duplicate_selection_no_selection_returns_status(
    router: ToolRouter,
) -> None:
    from pharos_engine.ui.editor.entity_clipboard import (
        reset_active_clipboard,
    )
    reset_active_clipboard()
    result = router.dispatch("edit.duplicate_selection", {})
    assert result == {"status": "no_selection"}


def test_duplicate_selection_from_explicit_ctx(router: ToolRouter) -> None:
    from pharos_engine.ui.editor.entity_clipboard import (
        reset_active_clipboard,
    )
    reset_active_clipboard()
    ent = _MockEntity(name="widget_a")
    result = router.dispatch(
        "edit.duplicate_selection",
        {"selection": [ent]},
    )
    assert result["status"] == "duplicated"
    assert result["count"] == 1
    assert len(result["clones"]) == 1
    clone = result["clones"][0]
    assert clone["name"] == "widget_a (copy)"
    assert clone["x"] == 1.0


def test_duplicate_selection_bumps_clipboard_generation(
    router: ToolRouter,
) -> None:
    from pharos_engine.ui.editor.entity_clipboard import (
        get_active_clipboard,
        reset_active_clipboard,
    )
    reset_active_clipboard()
    clipboard = get_active_clipboard()
    gen_before = clipboard.generation
    ent = _MockEntity(name="widget_b")
    router.dispatch("edit.duplicate_selection", {"selection": ent})
    assert clipboard.generation == gen_before + 1
    assert clipboard.last_action == "paste"


def test_duplicate_selection_reads_from_shell_selected_entity(
    router: ToolRouter,
) -> None:
    from pharos_engine.ui.editor.entity_clipboard import (
        reset_active_clipboard,
    )
    reset_active_clipboard()
    ent = _MockEntity(name="from_shell")
    shell = SimpleNamespace(
        _selected_entity=ent,
        _selected_entities=None,
        _engine=None,
    )
    result = router.dispatch("edit.duplicate_selection", {"shell": shell})
    assert result["status"] == "duplicated"
    assert result["clones"][0]["name"] == "from_shell (copy)"


def test_duplicate_selection_prefers_shell_hook(router: ToolRouter) -> None:
    """When shell exposes ``_duplicate_selected`` the router routes through it."""

    called: list[bool] = []

    class ShellWithHook:
        def _duplicate_selected(self) -> str:
            called.append(True)
            return "shell-return-value"

    result = router.dispatch(
        "edit.duplicate_selection", {"shell": ShellWithHook()},
    )
    assert called == [True]
    assert result["status"] == "duplicated"
    assert result["path"] == "shell"
    assert result["result"] == "shell-return-value"


# ---------------------------------------------------------------------------
# 7. Integration: all five actions appear on the module-level REGISTRY
# ---------------------------------------------------------------------------


def test_module_registry_has_x3_actions() -> None:
    """The default REGISTRY (populated at import time) must expose the new ids."""
    ids = {a.action_id for a in REGISTRY.list_actions()}
    for aid in (
        "editor.save_project",
        "editor.new_project",
        "editor.open_recent",
        "view.reset_layout",
        "edit.duplicate_selection",
    ):
        assert aid in ids, f"{aid} missing from module-level REGISTRY"
