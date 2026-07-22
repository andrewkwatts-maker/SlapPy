"""Tests for the ``examples/hello_scene_reg.py`` FF3 walkthrough demo.

These tests pin the demo's contract:

1.  ``run_demo`` completes without exception and returns a trace.
2.  scene1 has exactly 5 entities, all with a ``prefab_ref``.
3.  ``SceneFile`` round-trip preserves the entity list.
4.  The registry discovers all 3 extra scenes + scene1 (4 total).
5.  ``scene.apply(world, library)`` spawns bodies into a fresh
    :class:`~pharos_engine.dynamics.World`.
6.  ``Scene.snapshot(world)`` produces one entity per world body.
7.  Loading a corrupt scene raises :class:`SceneValidationError`.
8.  Trace log emits >= 20 events and is written to disk.
9.  Registry names come back sorted.
10. Demo ``main()`` CLI returns 0.
11. Individual builder helpers produce the expected entity counts.
12. Scene ``entity_count`` matches ``len(entities)``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_scene_reg.py"
)


def _load_demo():
    """Import the demo module under a stable name so tests can share it."""
    spec = importlib.util.spec_from_file_location(
        "hello_scene_reg_demo", _DEMO_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_scene_reg_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture()
def ran(demo, tmp_path):
    """Run the demo once per test in an isolated tmp_path."""
    return demo.run_demo(temp_root=tmp_path)


# ---------------------------------------------------------------------------
# 1. run_demo completes end-to-end
# ---------------------------------------------------------------------------


def test_run_demo_returns_trace(demo, tmp_path):
    trace = demo.run_demo(temp_root=tmp_path)
    assert trace is not None
    assert isinstance(trace.events, list)
    assert len(trace.events) > 0


# ---------------------------------------------------------------------------
# 2. scene1 has 5 entities, each with a prefab_ref
# ---------------------------------------------------------------------------


def test_scene1_has_five_prefab_ref_entities(demo):
    scene1 = demo.build_scene1()
    assert scene1.entity_count() == 5
    assert len(scene1.entities) == 5
    prefab_refs = [e.prefab_ref for e in scene1.entities]
    assert prefab_refs.count("crate") == 2
    assert prefab_refs.count("ball") == 2
    assert prefab_refs.count("chain") == 1
    assert all(e.inline_spec is None for e in scene1.entities)


# ---------------------------------------------------------------------------
# 3. SceneFile round-trip preserves entities
# ---------------------------------------------------------------------------


def test_scene_file_round_trip_preserves_entities(demo, tmp_path):
    scene1 = demo.build_scene1()
    path = demo.SceneFile.save(scene1, tmp_path / "scene1")
    assert path.exists()
    loaded = demo.SceneFile.load(path)
    assert loaded.name == scene1.name
    assert loaded.entity_count() == scene1.entity_count()
    assert loaded.to_dict() == scene1.to_dict()
    # Verify entity list identity survives round-trip.
    orig_names = [e.name for e in scene1.entities]
    loaded_names = [e.name for e in loaded.entities]
    assert orig_names == loaded_names


# ---------------------------------------------------------------------------
# 4. Registry discovers all 4 scenes
# ---------------------------------------------------------------------------


def test_registry_discovers_four_scenes(ran):
    discovered = [e for e in ran.events if e["kind"] == "registry_discovered"]
    assert len(discovered) == 1
    payload = discovered[0]
    assert payload["count"] == 4
    assert set(payload["names"]) == {
        "scene1", "scene_small", "scene_medium", "scene_large",
    }


# ---------------------------------------------------------------------------
# 5. apply spawns bodies into a fresh World
# ---------------------------------------------------------------------------


def test_scene_apply_spawns_into_world(demo, tmp_path):
    from pharos_engine.dynamics import World
    from pharos_engine.prefabs import PrefabLibrary

    lib_dir = tmp_path / "prefabs"
    library = PrefabLibrary()
    library.bake_defaults(user_dir=lib_dir)
    library.load_from_dir(lib_dir)

    scene = demo.build_scene1()
    world = World(gravity=(0.0, -9.81))
    spawned = scene.apply(world, library)
    assert len(spawned) == 5  # one entry per SceneEntity
    # Every entity created at least one body.
    for name, bodies in spawned.items():
        assert len(bodies) >= 1, f"entity {name!r} produced no bodies"
    assert len(world.bodies) >= 5


# ---------------------------------------------------------------------------
# 6. snapshot(world) reconstructs entity count
# ---------------------------------------------------------------------------


def test_snapshot_matches_world_body_count(demo, tmp_path):
    from pharos_engine.dynamics import World
    from pharos_engine.prefabs import PrefabLibrary

    lib_dir = tmp_path / "prefabs"
    library = PrefabLibrary()
    library.bake_defaults(user_dir=lib_dir)
    library.load_from_dir(lib_dir)

    scene = demo.build_scene1()
    world = World(gravity=(0.0, -9.81))
    scene.apply(world, library)

    snap = demo.Scene.snapshot(world, name="snap")
    assert snap.entity_count() == len(world.bodies)
    assert snap.name == "snap"
    # Every snapshot entity carries an inline_spec (not a prefab_ref).
    assert all(e.inline_spec is not None for e in snap.entities)
    assert all(e.prefab_ref is None for e in snap.entities)


# ---------------------------------------------------------------------------
# 7. Corrupt YAML raises SceneValidationError
# ---------------------------------------------------------------------------


def test_corrupt_scene_raises_validation_error(demo, tmp_path):
    bad = tmp_path / "bad.scene.yaml"
    bad.write_text(demo.CORRUPT_SCENE_YAML, encoding="utf-8")
    with pytest.raises(demo.SceneValidationError) as exc_info:
        demo.SceneFile.load(bad)
    err = exc_info.value
    # Message must mention the missing-field context.
    assert (
        "prefab_ref" in str(err)
        or "inline_spec" in str(err)
        or "required" in str(err).lower()
    )


def test_missing_required_scene_field_raises(demo):
    # Scene without 'entities' key.
    with pytest.raises(demo.SceneValidationError) as exc_info:
        demo.Scene.from_dict({"name": "no_entities", "version": 1})
    assert "entities" in str(exc_info.value)


# ---------------------------------------------------------------------------
# 8. Trace log has >= 20 events + is written to disk
# ---------------------------------------------------------------------------


def test_trace_has_at_least_20_events(ran):
    # The demo self-records the "demo_end" event and (typically) a
    # "trace_written" tail — so len(trace.events) is guaranteed >= 20.
    assert len(ran.events) >= 20, (
        f"trace must emit >= 20 events; got {len(ran.events)}"
    )


def test_trace_yaml_written_to_disk(ran):
    trace_path = (
        Path(_DEMO_PATH).with_name("hello_scene_reg_trace.yaml")
    )
    assert trace_path.exists()
    assert trace_path.stat().st_size > 0
    # And the written trace records the flush marker.
    kinds = {e["kind"] for e in ran.events}
    assert "trace_written" in kinds or "trace_write_failed" in kinds


# ---------------------------------------------------------------------------
# 9. Registry names come back sorted
# ---------------------------------------------------------------------------


def test_registry_names_are_sorted(demo, tmp_path):
    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    # Write scenes out-of-alphabet-order.
    for name in ("z_last", "a_first", "m_middle"):
        s = demo.Scene(name=name)
        s.add_entity(f"{name}_only", prefab_ref="ball", position=(0.0, 0.0))
        demo.SceneFile.save(s, scenes_dir / name)
    reg = demo.SceneRegistry(scenes_dir)
    discovered = reg.discover()
    assert discovered == sorted(discovered)
    assert set(discovered) == {"z_last", "a_first", "m_middle"}


# ---------------------------------------------------------------------------
# 10. CLI main() returns 0
# ---------------------------------------------------------------------------


def test_cli_main_returns_zero(demo, tmp_path):
    rc = demo.main(["--temp-root", str(tmp_path)])
    assert rc == 0


# ---------------------------------------------------------------------------
# 11. Builder helpers produce expected entity counts
# ---------------------------------------------------------------------------


def test_builder_helpers_match_expected_counts(demo):
    assert demo.build_scene_small().entity_count() == 1
    assert demo.build_scene_medium().entity_count() == 3
    assert demo.build_scene_large().entity_count() == 7


# ---------------------------------------------------------------------------
# 12. Scene.entity_count matches len(entities)
# ---------------------------------------------------------------------------


def test_scene_entity_count_matches_len(demo):
    scene = demo.build_scene1()
    assert scene.entity_count() == len(scene.entities)
    scene.add_entity("bonus", prefab_ref="ball", position=(9.0, 3.0))
    assert scene.entity_count() == len(scene.entities)
    assert scene.entity_count() == 6
    assert scene.find("bonus") is not None
    assert scene.find("does_not_exist") is None
