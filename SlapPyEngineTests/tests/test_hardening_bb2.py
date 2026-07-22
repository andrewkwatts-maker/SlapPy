"""Silent-acceptance hardening tests (BB2) — prefabs / autosave / actions.

Sweeps every public method flagged by the BB2 charter:

* :mod:`pharos_engine.prefabs.library` — :class:`PrefabLibrary.register`,
  :meth:`load_from_dir`, :meth:`bake_defaults`, :meth:`load_baked`,
  :meth:`spawn`.
* :mod:`pharos_engine.prefabs.prefab` — :meth:`Prefab.spawn`.
* :mod:`pharos_engine.autosave` — :class:`AutosaveManager._write_snapshot`,
  :func:`default_snapshot_dir`.
* :mod:`pharos_engine.actions.*` (Y/Z/AA batches only — NOT the BB1
  additions ``theme_import_actions`` / ``layout_io_actions`` /
  ``history_actions``): every public action helper now raises
  :class:`TypeError` on non-mapping ``ctx``.

Each test covers three shapes per method:

* invalid input → raises,
* missing target → logs a warning (or returns a status the caller can
  inspect),
* happy path → returns a truthy / non-error status.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(
    0, str(Path(__file__).resolve().parent.parent.parent / "python")
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_valid_prefab_yaml(name: str = "ball") -> str:
    """Return a minimal valid ``.prefab.yaml`` payload."""
    return (
        f"name: {name}\n"
        "category: props\n"
        "body_spec:\n"
        "  kind: circle\n"
        "  radius: 1.0\n"
    )


class _FakeWorld:
    """Bare-bones stand-in for :class:`pharos_engine.dynamics.World`."""

    def __init__(self) -> None:
        self.nodes: list[tuple[tuple[float, float], float]] = []
        self.joints: list[Any] = []
        self.bodies: list[Any] = []

    def add_node(self, pos, mass):
        self.nodes.append((tuple(pos), float(mass)))
        return len(self.nodes) - 1

    def add_joint(self, joint):
        self.joints.append(joint)

    def register_body(self, body):
        self.bodies.append(body)


# ---------------------------------------------------------------------------
# PrefabLibrary.register — input validation + status return
# ---------------------------------------------------------------------------


def test_prefab_library_register_rejects_non_prefab():
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    with pytest.raises(TypeError, match="prefab must be a Prefab"):
        lib.register("not-a-prefab")  # type: ignore[arg-type]


def test_prefab_library_register_rejects_prefab_with_empty_name():
    from pharos_engine.prefabs import Prefab, PrefabLibrary

    prefab = Prefab(name="valid", category="props", body_spec={"kind": "point"})
    # Mutate name post-construction to bypass __post_init__.
    object.__setattr__(prefab, "name", "")
    lib = PrefabLibrary()
    with pytest.raises(ValueError, match="prefab.name must be a non-empty"):
        lib.register(prefab)


def test_prefab_library_register_logs_when_replacing(caplog):
    from pharos_engine.prefabs import Prefab, PrefabLibrary

    lib = PrefabLibrary()
    p1 = Prefab(name="dup", category="props", body_spec={"kind": "point"})
    lib.register(p1)
    p2 = Prefab(name="dup", category="props", body_spec={"kind": "circle"})
    with caplog.at_level(logging.DEBUG, logger="pharos_engine.prefabs.library"):
        lib.register(p2)
    assert any("replacing existing" in r.message for r in caplog.records)


def test_prefab_library_register_happy_path_returns_prefab():
    from pharos_engine.prefabs import Prefab, PrefabLibrary

    lib = PrefabLibrary()
    p = Prefab(name="ok", category="props", body_spec={"kind": "point"})
    ret = lib.register(p)
    assert ret is p
    assert "ok" in lib


# ---------------------------------------------------------------------------
# PrefabLibrary.load_from_dir — validation + missing-target warning
# ---------------------------------------------------------------------------


def test_prefab_library_load_from_dir_rejects_non_path():
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    with pytest.raises(TypeError):
        lib.load_from_dir(123)  # type: ignore[arg-type]


def test_prefab_library_load_from_dir_rejects_empty_string():
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    with pytest.raises(ValueError):
        lib.load_from_dir("")


def test_prefab_library_load_from_dir_raises_on_missing_dir(tmp_path):
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    with pytest.raises(FileNotFoundError):
        lib.load_from_dir(tmp_path / "does-not-exist")


def test_prefab_library_load_from_dir_warns_on_empty_dir(tmp_path, caplog):
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    with caplog.at_level(logging.WARNING, logger="pharos_engine.prefabs.library"):
        result = lib.load_from_dir(tmp_path)
    assert result == []
    assert any("no .prefab.yaml files" in r.message for r in caplog.records)


def test_prefab_library_load_from_dir_happy_path(tmp_path):
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    (tmp_path / "ball.prefab.yaml").write_text(
        _make_valid_prefab_yaml("ball"), encoding="utf-8"
    )
    (tmp_path / "crate.prefab.yaml").write_text(
        _make_valid_prefab_yaml("crate"), encoding="utf-8"
    )
    loaded = lib.load_from_dir(tmp_path)
    assert set(loaded) == {"ball", "crate"}


# ---------------------------------------------------------------------------
# PrefabLibrary.bake_defaults — missing baked dir warning
# ---------------------------------------------------------------------------


def test_prefab_library_bake_defaults_warns_on_missing_baked_dir(
    tmp_path, caplog,
):
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    with caplog.at_level(logging.WARNING, logger="pharos_engine.prefabs.library"):
        result = lib.bake_defaults(
            user_dir=tmp_path / "user",
            baked_dir=tmp_path / "nope",
        )
    assert result == []
    assert any("baked dir" in r.message for r in caplog.records)


def test_prefab_library_bake_defaults_happy_path(tmp_path):
    from pharos_engine.prefabs import PrefabLibrary

    baked = tmp_path / "baked"
    baked.mkdir()
    (baked / "ball.prefab.yaml").write_text(
        _make_valid_prefab_yaml("ball"), encoding="utf-8"
    )
    user = tmp_path / "user"
    lib = PrefabLibrary()
    written = lib.bake_defaults(user_dir=user, baked_dir=baked)
    assert len(written) == 1
    assert (user / "ball.prefab.yaml").is_file()


# ---------------------------------------------------------------------------
# PrefabLibrary.load_baked — missing baked dir warning
# ---------------------------------------------------------------------------


def test_prefab_library_load_baked_warns_when_missing(monkeypatch, caplog, tmp_path):
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    monkeypatch.setattr(lib, "BAKED_DIR", tmp_path / "no-such-dir")
    with caplog.at_level(logging.WARNING, logger="pharos_engine.prefabs.library"):
        result = lib.load_baked()
    assert result == []
    assert any("baked dir" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# PrefabLibrary.spawn — validation + missing-target
# ---------------------------------------------------------------------------


def test_prefab_library_spawn_rejects_empty_name():
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    with pytest.raises(KeyError, match="non-empty str"):
        lib.spawn("", _FakeWorld(), (0.0, 0.0))


def test_prefab_library_spawn_rejects_none_world():
    from pharos_engine.prefabs import Prefab, PrefabLibrary

    lib = PrefabLibrary()
    lib.register(Prefab(name="ok", category="props", body_spec={"kind": "point"}))
    with pytest.raises(TypeError, match="world must not be None"):
        lib.spawn("ok", None, (0.0, 0.0))  # type: ignore[arg-type]


def test_prefab_library_spawn_raises_for_unknown_name():
    from pharos_engine.prefabs import PrefabLibrary

    lib = PrefabLibrary()
    with pytest.raises(KeyError, match="no prefab registered"):
        lib.spawn("ghost", _FakeWorld(), (0.0, 0.0))


# ---------------------------------------------------------------------------
# Prefab.spawn — world-is-None guard + missing child warning
# ---------------------------------------------------------------------------


def test_prefab_spawn_rejects_none_world():
    from pharos_engine.prefabs import Prefab

    p = Prefab(name="ok", category="props", body_spec={"kind": "point"})
    with pytest.raises(TypeError, match="world must not be None"):
        p.spawn(None, (0.0, 0.0))  # type: ignore[arg-type]


def test_prefab_spawn_logs_missing_child(caplog):
    from pharos_engine.prefabs import Prefab, PrefabLibrary

    parent = Prefab(
        name="parent",
        category="structural",
        body_spec={"kind": "composite"},
        child_prefabs=["ghost-child"],
    )
    lib = PrefabLibrary()
    lib.register(parent)
    world = _FakeWorld()
    with caplog.at_level(logging.WARNING, logger="pharos_engine.prefabs.prefab"):
        parent.spawn(world, (0.0, 0.0), library=lib)
    assert any("ghost-child" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# AutosaveManager._write_snapshot — None-payload guard
# ---------------------------------------------------------------------------


def test_autosave_write_snapshot_rejects_none_payload(tmp_path):
    from pharos_engine.autosave import AutosaveManager, AutosaveState

    state = AutosaveState(
        interval_seconds=60.0,
        snapshot_dir=tmp_path,
        max_snapshots=5,
    )
    project = SimpleNamespace(name="proj")
    manager = AutosaveManager(state, project, lambda: None)
    with pytest.raises(ValueError, match="returned None"):
        manager.force_save()


def test_autosave_write_snapshot_wraps_callback_failure(tmp_path):
    from pharos_engine.autosave import AutosaveManager, AutosaveState

    def _boom():
        raise KeyError("boom")

    state = AutosaveState(
        interval_seconds=60.0,
        snapshot_dir=tmp_path,
        max_snapshots=5,
    )
    project = SimpleNamespace(name="proj")
    manager = AutosaveManager(state, project, _boom)
    with pytest.raises(RuntimeError, match="save_callback"):
        manager.force_save()


def test_autosave_write_snapshot_happy_path(tmp_path):
    from pharos_engine.autosave import AutosaveManager, AutosaveState

    state = AutosaveState(
        interval_seconds=60.0,
        snapshot_dir=tmp_path,
        max_snapshots=5,
    )
    project = SimpleNamespace(name="proj")
    manager = AutosaveManager(state, project, lambda: {"note": "hi"})
    path = manager.force_save()
    assert path.is_file()
    assert path.suffix == ".yaml"


def test_default_snapshot_dir_rejects_non_str():
    from pharos_engine.autosave import default_snapshot_dir

    with pytest.raises(TypeError, match="project_name must be a str"):
        default_snapshot_dir(123)  # type: ignore[arg-type]


def test_default_snapshot_dir_happy_path():
    from pharos_engine.autosave import default_snapshot_dir

    p = default_snapshot_dir("myproj")
    assert "myproj" in str(p)


# ---------------------------------------------------------------------------
# actions.save_project / new_project / open_recent — ctx validation
# ---------------------------------------------------------------------------


def test_save_project_rejects_non_dict_ctx():
    from pharos_engine.actions import save_project

    with pytest.raises(TypeError, match="ctx must be a mapping"):
        save_project([])  # type: ignore[arg-type]


def test_save_project_rejects_none_ctx():
    from pharos_engine.actions import save_project

    with pytest.raises(TypeError, match="ctx must not be None"):
        save_project(None)  # type: ignore[arg-type]


def test_save_project_no_project_status():
    from pharos_engine.actions import save_project

    assert save_project({})["status"] == "no_project"


def test_new_project_rejects_int_name():
    from pharos_engine.actions import new_project

    with pytest.raises(TypeError, match="ctx\\['name'\\] must be a str"):
        new_project({"path": "/tmp", "name": 42})


def test_new_project_missing_path():
    from pharos_engine.actions import new_project

    assert new_project({})["status"] == "missing_path"


def test_new_project_missing_name(tmp_path):
    from pharos_engine.actions import new_project

    assert new_project({"path": str(tmp_path)})["status"] == "missing_name"


def test_open_recent_rejects_non_dict():
    from pharos_engine.actions import open_recent

    with pytest.raises(TypeError, match="ctx must be a mapping"):
        open_recent("string")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# actions.reset_layout — ctx + preset validation
# ---------------------------------------------------------------------------


def test_reset_layout_rejects_non_dict():
    from pharos_engine.actions import reset_layout

    with pytest.raises(TypeError, match="ctx must be a mapping"):
        reset_layout(42)  # type: ignore[arg-type]


def test_reset_layout_rejects_int_preset():
    from pharos_engine.actions import reset_layout

    with pytest.raises(TypeError, match="ctx\\['preset'\\] must be a str"):
        reset_layout({"preset": 99})


def test_reset_layout_no_shell():
    from pharos_engine.actions import reset_layout

    assert reset_layout({})["status"] == "no_shell"


# ---------------------------------------------------------------------------
# actions.duplicate_selection / copy / paste / select_all / deselect_all
# ---------------------------------------------------------------------------


def test_duplicate_selection_rejects_none():
    from pharos_engine.actions import duplicate_selection

    with pytest.raises(TypeError):
        duplicate_selection(None)  # type: ignore[arg-type]


def test_duplicate_selection_no_selection_status():
    from pharos_engine.actions import duplicate_selection

    assert duplicate_selection({})["status"] == "no_selection"


def test_select_all_rejects_list():
    from pharos_engine.actions import select_all

    with pytest.raises(TypeError):
        select_all([])  # type: ignore[arg-type]


def test_select_all_no_scene():
    from pharos_engine.actions import select_all

    assert select_all({})["status"] == "no_scene"


def test_deselect_all_rejects_non_dict():
    from pharos_engine.actions import deselect_all

    with pytest.raises(TypeError):
        deselect_all("nope")  # type: ignore[arg-type]


def test_deselect_all_happy_path():
    from pharos_engine.actions import deselect_all

    assert deselect_all({})["status"] == "deselected"


def test_copy_selection_rejects_int():
    from pharos_engine.actions import copy_selection

    with pytest.raises(TypeError):
        copy_selection(5)  # type: ignore[arg-type]


def test_paste_selection_rejects_none():
    from pharos_engine.actions import paste_selection

    with pytest.raises(TypeError):
        paste_selection(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# actions.cycle_theme / toggle_snap_to_grid / zoom_* / etc.
# ---------------------------------------------------------------------------


def test_cycle_theme_rejects_non_dict():
    from pharos_engine.actions import cycle_theme

    with pytest.raises(TypeError):
        cycle_theme("string-ctx")  # type: ignore[arg-type]


def test_toggle_snap_to_grid_rejects_none():
    from pharos_engine.actions import toggle_snap_to_grid

    with pytest.raises(TypeError):
        toggle_snap_to_grid(None)  # type: ignore[arg-type]


def test_toggle_snap_to_grid_headless_toggle():
    from pharos_engine.actions import toggle_snap_to_grid
    from pharos_engine.actions.tool_settings_actions import (
        _reset_snap_grid_for_tests,
    )

    _reset_snap_grid_for_tests()
    result = toggle_snap_to_grid({})
    assert result["status"] == "toggled"
    assert result["enabled"] is True


def test_zoom_in_rejects_non_dict():
    from pharos_engine.actions import zoom_in

    with pytest.raises(TypeError):
        zoom_in([1, 2])  # type: ignore[arg-type]


def test_zoom_out_rejects_none():
    from pharos_engine.actions import zoom_out

    with pytest.raises(TypeError):
        zoom_out(None)  # type: ignore[arg-type]


def test_zoom_reset_rejects_int():
    from pharos_engine.actions import zoom_reset

    with pytest.raises(TypeError):
        zoom_reset(0)  # type: ignore[arg-type]


def test_zoom_in_no_camera():
    from pharos_engine.actions import zoom_in

    assert zoom_in({})["status"] == "no_camera"


def test_zoom_in_happy_path():
    from pharos_engine.actions import zoom_in

    camera = SimpleNamespace(_cam_distance=5.0)
    result = zoom_in({"camera": camera})
    assert result["status"] == "zoomed"
    assert camera._cam_distance < 5.0


def test_export_current_theme_rejects_non_dict():
    from pharos_engine.actions import export_current_theme

    with pytest.raises(TypeError):
        export_current_theme("nope")  # type: ignore[arg-type]


def test_cut_selection_rejects_non_dict():
    from pharos_engine.actions import cut_selection

    with pytest.raises(TypeError):
        cut_selection(None)  # type: ignore[arg-type]


def test_delete_selection_rejects_non_dict():
    from pharos_engine.actions import delete_selection

    with pytest.raises(TypeError):
        delete_selection(42)  # type: ignore[arg-type]


def test_delete_selection_no_selection():
    from pharos_engine.actions import delete_selection

    assert delete_selection({})["status"] == "no_selection"


def test_center_on_selection_rejects_non_dict():
    from pharos_engine.actions import center_on_selection

    with pytest.raises(TypeError):
        center_on_selection([])  # type: ignore[arg-type]


def test_center_on_selection_no_camera():
    from pharos_engine.actions import center_on_selection

    assert center_on_selection({})["status"] == "no_camera"


def test_frame_all_rejects_non_dict():
    from pharos_engine.actions import frame_all

    with pytest.raises(TypeError):
        frame_all(None)  # type: ignore[arg-type]


def test_frame_all_no_camera():
    from pharos_engine.actions import frame_all

    assert frame_all({})["status"] == "no_camera"


def test_activate_pan_tool_rejects_non_dict():
    from pharos_engine.actions import activate_pan_tool

    with pytest.raises(TypeError):
        activate_pan_tool("string")  # type: ignore[arg-type]


def test_activate_pan_tool_headless_fallback():
    from pharos_engine.actions import activate_pan_tool, PAN_TOOL_ID

    result = activate_pan_tool({})
    assert result["status"] == "activated"
    assert result["tool"] == PAN_TOOL_ID
    assert result["path"] == "fallback"


# ---------------------------------------------------------------------------
# _ctx.ensure_ctx — cover the helper itself for completeness
# ---------------------------------------------------------------------------


def test_ensure_ctx_rejects_none():
    from pharos_engine.actions._ctx import ensure_ctx

    with pytest.raises(TypeError, match="ctx must not be None"):
        ensure_ctx("test_fn", None)


def test_ensure_ctx_rejects_list():
    from pharos_engine.actions._ctx import ensure_ctx

    with pytest.raises(TypeError, match="ctx must be a mapping"):
        ensure_ctx("test_fn", [])


def test_ensure_ctx_accepts_dict_subclass():
    from collections import ChainMap

    from pharos_engine.actions._ctx import ensure_ctx

    cm = ChainMap({"a": 1})
    assert ensure_ctx("test_fn", cm) is cm
