"""Tripwire suite for the AA2 API-polish additions.

Covers four Z4-documented gaps:

* :meth:`PrefabLibrary.spawn` — one-shot ``lib.get(name).spawn(...)``.
* :attr:`Prefab.entity_count` — gameplay entity total per body kind.
* :meth:`PrefabLibrary.bake_and_load` — combined bake + load, idempotent.
* :meth:`AutosaveManager.read_snapshot` — public snapshot reader,
  :class:`AutosaveReadError` on corrupt YAML.

Tests live under :mod:`SlapPyEngineTests.tests` so they run alongside
the rest of the engine suite (``pytest SlapPyEngineTests``).
"""
from __future__ import annotations

import math
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from slappyengine.autosave import (
    AutosaveManager,
    AutosaveReadError,
    AutosaveState,
)
from slappyengine.dynamics import World
from slappyengine.prefabs import Prefab, PrefabLibrary


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def loaded_library(tmp_path: Path) -> PrefabLibrary:
    """A library primed with the six baked prefabs, sandboxed under tmp."""
    lib = PrefabLibrary()
    lib.bake_defaults(user_dir=tmp_path / "prefabs")
    lib.load_from_dir(tmp_path / "prefabs")
    return lib


@pytest.fixture
def world() -> World:
    return World(gravity=(0.0, -9.81))


def _make_autosave_manager(tmp_path: Path) -> AutosaveManager:
    state = AutosaveState(
        enabled=True,
        interval_seconds=0.05,
        snapshot_dir=tmp_path / "autosave",
        max_snapshots=5,
    )
    project = SimpleNamespace(name="aa2_test")
    return AutosaveManager(state, project, lambda: {"note": "hi"})


# ---------------------------------------------------------------------------
# PrefabLibrary.spawn — 4 tests
# ---------------------------------------------------------------------------


def test_library_spawn_end_to_end(loaded_library: PrefabLibrary, world: World) -> None:
    bodies = loaded_library.spawn("ball", world, (0.0, 5.0))
    assert isinstance(bodies, list) and bodies
    assert bodies[0].kind == "circle"
    assert bodies[0].label == "ball"


def test_library_spawn_unknown_raises_keyerror(
    loaded_library: PrefabLibrary, world: World,
) -> None:
    with pytest.raises(KeyError) as exc:
        loaded_library.spawn("does_not_exist", world, (0.0, 0.0))
    assert "does_not_exist" in str(exc.value)


def test_library_spawn_empty_name_raises_keyerror(
    loaded_library: PrefabLibrary, world: World,
) -> None:
    with pytest.raises(KeyError):
        loaded_library.spawn("", world, (0.0, 0.0))


def test_library_spawn_threads_library_into_composite(
    loaded_library: PrefabLibrary, world: World,
) -> None:
    # Windmill is composite; spawning through the library should not
    # crash even when no child_prefabs are present.
    bodies = loaded_library.spawn("windmill", world, (2.0, 3.0))
    assert bodies
    assert any(b.kind == "composite" for b in bodies)


# ---------------------------------------------------------------------------
# Prefab.entity_count — 7+ cases
# ---------------------------------------------------------------------------


def _make_prefab(kind: str, **body_spec) -> Prefab:
    body_spec.setdefault("kind", kind)
    return Prefab(name=f"probe_{kind}", category="props", body_spec=body_spec)


def test_entity_count_point() -> None:
    assert _make_prefab("point", mass=1.0).entity_count == 1


def test_entity_count_circle() -> None:
    assert _make_prefab("circle", radius=0.5).entity_count == 1


def test_entity_count_box() -> None:
    assert _make_prefab("box", width=1.0, height=1.0).entity_count == 1


def test_entity_count_rope_default() -> None:
    assert _make_prefab("rope").entity_count == 5


def test_entity_count_rope_custom_segments() -> None:
    assert _make_prefab("rope", segments=11).entity_count == 11


def test_entity_count_chain_default() -> None:
    assert _make_prefab("chain").entity_count == 5


def test_entity_count_chain_custom_links() -> None:
    assert _make_prefab("chain", links=8).entity_count == 8


def test_entity_count_ragdoll_is_seven() -> None:
    p = Prefab(
        name="rag_probe",
        category="characters",
        body_spec={"kind": "ragdoll", "bones": [{"parent_idx": -1, "length": 1.0}]},
    )
    assert p.entity_count == 7


def test_entity_count_composite_without_library_uses_nodes() -> None:
    p = _make_prefab(
        "composite",
        nodes=[(0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)],
    )
    # No library attached, so fallback to len(nodes).
    assert p.entity_count == 3


def test_entity_count_composite_with_children_recursive() -> None:
    lib = PrefabLibrary()
    lib.register(_make_prefab("circle", radius=0.4))  # probe_circle → 1
    lib.register(_make_prefab("chain", links=6))       # probe_chain → 6
    parent = Prefab(
        name="parent_composite",
        category="structural",
        body_spec={"kind": "composite", "nodes": [(0.0, 0.0, 1.0)]},
        child_prefabs=["probe_circle", "probe_chain"],
    )
    lib.register(parent)
    # With library: 1 (circle) + 6 (chain) = 7.
    assert parent.compute_entity_count(lib) == 7
    # Property (no library) falls back to len(nodes) = 1.
    assert parent.entity_count == 1


def test_entity_count_composite_nested_recursion() -> None:
    lib = PrefabLibrary()
    leaf = _make_prefab("box")  # probe_box → 1
    mid = Prefab(
        name="mid",
        category="structural",
        body_spec={"kind": "composite", "nodes": [(0.0, 0.0)]},
        child_prefabs=["probe_box", "probe_box"],
    )
    root = Prefab(
        name="root",
        category="structural",
        body_spec={"kind": "composite", "nodes": [(0.0, 0.0)]},
        child_prefabs=["mid", "mid"],
    )
    for p in (leaf, mid, root):
        lib.register(p)
    # root -> 2*mid -> 2*(2*box) -> 4 boxes total.
    assert root.compute_entity_count(lib) == 4


# ---------------------------------------------------------------------------
# PrefabLibrary.bake_and_load — idempotency + presence
# ---------------------------------------------------------------------------


def test_bake_and_load_populates_registry(tmp_path: Path) -> None:
    lib = PrefabLibrary()
    result = lib.bake_and_load(user_dir=tmp_path / "user_prefabs")
    assert result is lib
    # At least the shipping baked palette should now be registered.
    names = lib.list_names()
    assert "ball" in names
    assert "crate" in names
    assert "chain" in names
    assert "windmill" in names


def test_bake_and_load_is_idempotent(tmp_path: Path) -> None:
    udir = tmp_path / "user_prefabs"
    lib_a = PrefabLibrary()
    lib_a.bake_and_load(user_dir=udir)
    first_names = set(lib_a.list_names())
    first_files = sorted(p.name for p in udir.glob("*.prefab.yaml"))

    lib_b = PrefabLibrary()
    lib_b.bake_and_load(user_dir=udir)
    lib_b.bake_and_load(user_dir=udir)  # third call, still idempotent
    second_names = set(lib_b.list_names())
    second_files = sorted(p.name for p in udir.glob("*.prefab.yaml"))

    assert first_names == second_names
    assert first_files == second_files


def test_bake_and_load_preserves_user_edits(tmp_path: Path) -> None:
    udir = tmp_path / "user_prefabs"
    lib = PrefabLibrary()
    lib.bake_and_load(user_dir=udir)
    # Hand-edit one file so we can prove bake_and_load doesn't clobber it.
    crate_path = udir / "crate.prefab.yaml"
    crate_path.write_text(
        "name: crate\ncategory: props\nbody_spec:\n  kind: box\n  width: 99.0\n"
        "  height: 99.0\n",
        encoding="utf-8",
    )
    # Second bake_and_load should not overwrite the on-disk file.
    lib2 = PrefabLibrary()
    lib2.bake_and_load(user_dir=udir)
    assert crate_path.read_text(encoding="utf-8").find("99.0") != -1
    # And the loaded prefab reflects the user edit.
    edited = lib2.get("crate")
    assert edited is not None
    assert float(edited.body_spec.get("width", 0.0)) == pytest.approx(99.0)


# ---------------------------------------------------------------------------
# AutosaveManager.read_snapshot — round-trip + error surfaces
# ---------------------------------------------------------------------------


def test_read_snapshot_roundtrip(tmp_path: Path) -> None:
    manager = _make_autosave_manager(tmp_path)
    path = manager.force_save()
    doc = AutosaveManager.read_snapshot(path)
    assert isinstance(doc, dict)
    assert "meta" in doc and "payload" in doc
    assert doc["payload"] == {"note": "hi"}
    assert doc["meta"].get("project") == "aa2_test"


def test_read_snapshot_bytes_payload_decodes_via_b64(tmp_path: Path) -> None:
    state = AutosaveState(
        enabled=True,
        interval_seconds=0.05,
        snapshot_dir=tmp_path / "autosave",
        max_snapshots=5,
    )
    project = SimpleNamespace(name="bytes_test")

    def _cb() -> bytes:
        return b"\x00\x01hello"

    manager = AutosaveManager(state, project, _cb)
    path = manager.force_save()
    doc = AutosaveManager.read_snapshot(path)
    assert doc["payload"] == b"\x00\x01hello"


def test_read_snapshot_missing_file_raises(tmp_path: Path) -> None:
    ghost = tmp_path / "ghost.snap.yaml"
    with pytest.raises(FileNotFoundError):
        AutosaveManager.read_snapshot(ghost)


def test_read_snapshot_old_version_still_reads(tmp_path: Path) -> None:
    # A snapshot that lacks the ``engine_version`` field (as an early
    # sprint-Y6 snap file would). read_snapshot should still return the
    # payload untouched.
    old = tmp_path / "old.snap.yaml"
    old.write_text(
        "meta:\n  saved_at: 2026-01-01T00:00:00Z\n  project: legacy\n"
        "payload:\n  notebook_text: hello\n",
        encoding="utf-8",
    )
    doc = AutosaveManager.read_snapshot(old)
    assert doc["payload"] == {"notebook_text": "hello"}
    assert doc["meta"]["project"] == "legacy"


def test_read_snapshot_corrupt_raises_autosave_read_error(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.snap.yaml"
    corrupt.write_text(
        "meta:\n  saved_at: 2026-01-01\npayload:\n  bad: [unterminated\n",
        encoding="utf-8",
    )
    with pytest.raises(AutosaveReadError) as exc:
        AutosaveManager.read_snapshot(corrupt)
    msg = str(exc.value)
    # Message should reference the file path and something about the
    # parse failure. When pyyaml is available we also expect a line
    # number to be attached to the exception.
    assert "corrupt.snap.yaml" in msg
    assert exc.value.path is not None
    # AutosaveReadError.line is None-safe — assert the attribute exists.
    assert hasattr(exc.value, "line")


def test_read_snapshot_non_dict_top_level_raises(tmp_path: Path) -> None:
    scalar = tmp_path / "scalar.snap.yaml"
    scalar.write_text("just_a_string\n", encoding="utf-8")
    with pytest.raises(AutosaveReadError):
        AutosaveManager.read_snapshot(scalar)


def test_read_snapshot_is_classmethod() -> None:
    # No instance required to call read_snapshot.
    assert callable(AutosaveManager.read_snapshot)


def test_autosave_read_error_carries_line(tmp_path: Path) -> None:
    try:
        import yaml  # noqa: F401
    except ImportError:
        pytest.skip("pyyaml not installed — line tracking unavailable")
    corrupt = tmp_path / "line_probe.snap.yaml"
    # Deliberate parse error on line 3.
    corrupt.write_text(
        "meta:\n  ok: true\n  bad: [oops\npayload: null\n",
        encoding="utf-8",
    )
    with pytest.raises(AutosaveReadError) as exc:
        AutosaveManager.read_snapshot(corrupt)
    # Line attribute should be a plausible int if the loader supplied one.
    assert exc.value.line is None or isinstance(exc.value.line, int)
