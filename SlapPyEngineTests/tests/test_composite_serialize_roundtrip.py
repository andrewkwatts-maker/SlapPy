"""Composite-scene serialize round-trip test (Sprint 4).

This module exercises the dynamics-world serializer
(:func:`slappyengine.dynamics.serialize.save_world` /
:func:`load_world`) against the multi-subsystem ``hello_composite`` scene
and documents exactly which subsystem state is — and is NOT — captured by
the on-disk format.

What this test asserts
----------------------
1. After driving the composite scene through ``step_scene`` for
   ``DEFAULT_FRAMES`` frames, the dynamics ``World`` (the rope's PBD
   particles + sequential distance joints) can be JSON-serialised to disk
   and reloaded byte-for-byte identical via
   :func:`world_to_dict` / :func:`world_from_dict`.
2. The save file is non-trivial: it contains the rope's positions,
   prev_positions, velocities, inv_masses, the catenary joint chain, and
   the gravity / solver-iterations / frame-counter scalars.
3. The byte size of the round-trip payload is reported and pinned to a
   sane lower bound so a future serializer regression that silently drops
   fields (e.g. forgets to encode ``prev_positions``) is caught.
4. Loading the saved world and taking one ``step(dt)`` produces a
   position field within 1e-9 of the original — i.e. the round-trip
   preserves enough state for deterministic continuation.
5. Telemetry subscribers attached during ``step_scene`` observe the
   expected event counts (``physics.step`` = frames; ``combat.hit`` and
   ``zone.enter`` >= 1).

What is NOT serialised by this test
-----------------------------------
Phase C-like surface gaps documented in
``docs/sprint_4_serialization_gaps.md``:

* :class:`HeatField` temperature grid — no serializer; the heat state is
  reset to ambient on reload.
* :class:`ZoneManager` occupancy + per-zone enter/exit counters — no
  serializer; live entity membership is lost across save/load.
* :mod:`slappyengine.iso.combat` ``Defender`` / ``Attacker`` / ongoing
  ``WaveSchedule.elapsed`` — no serializer; an in-flight wave restarts.
* :mod:`slappyengine.telemetry` history ring buffer — has clear-able
  in-process history but no JSON round-trip; subscribers are reattached
  by the demo on each run.

The test explicitly asserts non-serializable status for those subsystems
via ``hasattr`` probes so a future generalisation that adds JSON support
will trip this test and force the gap-doc to be updated.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

import slappyengine.telemetry as telemetry
from slappyengine.dynamics import World
from slappyengine.dynamics.serialize import (
    SCHEMA_VERSION,
    load_world,
    save_world,
    world_from_dict,
    world_to_dict,
)


# ── Repo paths + demo loader ──────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_composite.py"

# Minimum byte size of the JSON save when the rope world is fully encoded.
# 16 rope nodes × 4 float64 arrays of (16, 2) plus the 15-joint chain plus
# the body / scalar metadata easily clears 5 KB even with base64 packing.
_MIN_SAVE_BYTES = 4_000


def _load_demo():
    """Load hello_composite.py as a fresh module (mirrors test_demo_*)."""
    spec = importlib.util.spec_from_file_location(
        "hello_composite_demo_serialize", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_composite_demo_serialize"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ── Telemetry capture helper ──────────────────────────────────────────────


class _EventCounter:
    """Subscribe to physics.step / combat.hit / zone.enter and tally."""

    def __init__(self) -> None:
        self.physics_step: int = 0
        self.combat_hit: int = 0
        self.zone_enter: int = 0
        self._handles: list[int] = []

    def attach(self) -> None:
        self._handles.append(
            telemetry.subscribe("physics.step", self._on_physics)
        )
        self._handles.append(
            telemetry.subscribe("combat.hit", self._on_combat)
        )
        self._handles.append(
            telemetry.subscribe("zone.enter", self._on_zone)
        )

    def detach(self) -> None:
        while self._handles:
            telemetry.unsubscribe(self._handles.pop())

    def _on_physics(self, _ev: telemetry.TelemetryEvent) -> None:
        self.physics_step += 1

    def _on_combat(self, _ev: telemetry.TelemetryEvent) -> None:
        self.combat_hit += 1

    def _on_zone(self, _ev: telemetry.TelemetryEvent) -> None:
        self.zone_enter += 1


# ── Tests ─────────────────────────────────────────────────────────────────


def test_composite_world_serialize_roundtrip(demo, tmp_path):
    """The dynamics World round-trips through save_world/load_world.

    Builds the full composite scene (defenders, wave schedule, rope,
    zones, thermal field), runs ``step_scene`` for the demo's default
    frame count, then exercises the JSON serializer on the *dynamics*
    half of the scene. Asserts:

    * The save file lands above ``_MIN_SAVE_BYTES`` (no silent field drop).
    * Reloading the world preserves every node array bit-for-bit.
    * One step on the reload reproduces the original's next-frame
      positions to 1e-9.
    """
    counter = _EventCounter()
    counter.attach()
    try:
        scene = demo.build_scene()
        demo.step_scene(scene, frames=demo.DEFAULT_FRAMES, dt=demo.DEFAULT_DT)
    finally:
        counter.detach()

    assert scene.world is not None
    world: World = scene.world

    # ── 1. JSON encode + decode in-memory ────────────────────────────────
    payload = world_to_dict(world)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["frame"] == world.frame
    assert len(payload["joints"]) == len(world.joints)
    assert len(payload["bodies"]) == len(world.bodies)

    reloaded_mem = world_from_dict(payload)
    np.testing.assert_array_equal(reloaded_mem.positions, world.positions)
    np.testing.assert_array_equal(
        reloaded_mem.prev_positions, world.prev_positions
    )
    np.testing.assert_array_equal(reloaded_mem.velocities, world.velocities)
    np.testing.assert_array_equal(reloaded_mem.inv_masses, world.inv_masses)

    # ── 2. Disk round trip + byte-size guard ─────────────────────────────
    save_path = tmp_path / "composite_world.json"
    save_world(world, save_path)
    save_bytes = save_path.stat().st_size
    assert save_bytes >= _MIN_SAVE_BYTES, (
        f"composite world save is suspiciously small "
        f"({save_bytes} < {_MIN_SAVE_BYTES} bytes); a silent field drop?"
    )

    # The JSON should at least parse as a top-level dict with all the
    # core attributes — guards against e.g. a serializer that wrote a
    # bare list instead of a structured dict.
    with save_path.open("r", encoding="utf-8") as fp:
        parsed = json.load(fp)
    for required_key in (
        "schema_version",
        "positions",
        "prev_positions",
        "velocities",
        "inv_masses",
        "bodies",
        "joints",
        "gravity",
        "solver_iterations",
        "warn_overdamping",
        "frame",
    ):
        assert required_key in parsed, (
            f"saved world missing top-level key {required_key!r}"
        )

    reloaded_disk = load_world(save_path)
    np.testing.assert_array_equal(reloaded_disk.positions, world.positions)
    np.testing.assert_array_equal(
        reloaded_disk.prev_positions, world.prev_positions
    )
    np.testing.assert_array_equal(reloaded_disk.velocities, world.velocities)
    np.testing.assert_array_equal(reloaded_disk.inv_masses, world.inv_masses)
    assert reloaded_disk.solver_iterations == world.solver_iterations
    assert reloaded_disk.frame == world.frame
    assert reloaded_disk.warn_overdamping == world.warn_overdamping

    # Joints round-trip: kind / endpoints / rest_length preserved.
    assert len(reloaded_disk.joints) == len(world.joints)
    for j_in, j_out in zip(world.joints, reloaded_disk.joints):
        assert j_in.kind == j_out.kind
        assert j_in.node_a == j_out.node_a
        assert j_in.node_b == j_out.node_b
        assert j_in.rest_length == pytest.approx(j_out.rest_length, rel=1e-12)
        assert j_in.stiffness == pytest.approx(j_out.stiffness, rel=1e-12)

    # ── 3. Determinism contract: one step on the reload tracks the
    #     original's next-frame state to 1e-9.
    original_step = World(gravity=tuple(world.gravity))
    original_step.positions = world.positions.copy()
    original_step.prev_positions = world.prev_positions.copy()
    original_step.velocities = world.velocities.copy()
    original_step.inv_masses = world.inv_masses.copy()
    original_step.solver_iterations = world.solver_iterations
    original_step.warn_overdamping = world.warn_overdamping
    original_step.frame = world.frame
    original_step.bodies = list(world.bodies)
    original_step.joints = list(world.joints)
    original_step.step(demo.DEFAULT_DT)

    reloaded_disk.step(demo.DEFAULT_DT)

    np.testing.assert_allclose(
        reloaded_disk.positions,
        original_step.positions,
        rtol=0.0,
        atol=1e-9,
    )

    # ── 4. Telemetry counters: physics.step fires once per frame,
    #     zone.enter / combat.hit fire at least once over 180 frames.
    assert counter.physics_step == demo.DEFAULT_FRAMES, (
        f"physics.step subscriber observed {counter.physics_step} events; "
        f"expected exactly {demo.DEFAULT_FRAMES}"
    )
    assert counter.zone_enter >= 1, (
        f"zone.enter never fired; expected at least one foundry crossing "
        f"during {demo.DEFAULT_FRAMES} frames"
    )
    assert counter.combat_hit >= 1, (
        f"combat.hit never fired; expected at least one resolve_attack "
        f"to deal damage during {demo.DEFAULT_FRAMES} frames"
    )


def test_composite_documents_serialization_gaps(demo):
    """Pin the Phase-C-like serialization gaps: thermal / zones / iso /
    telemetry are NOT covered by ``dynamics.serialize``.

    These probes assert the *absence* of save/load APIs on the
    composite scene's non-dynamics subsystems. When a future PR adds
    JSON round-trips for any of them, the corresponding probe trips and
    the author is forced to update ``docs/sprint_4_serialization_gaps.md``.
    """
    scene = demo.build_scene()
    demo.step_scene(scene, frames=10, dt=demo.DEFAULT_DT)

    # ── HeatField: no to_dict / from_dict ────────────────────────────────
    assert scene.heat_field is not None
    assert not hasattr(scene.heat_field, "to_dict"), (
        "HeatField gained a to_dict — update docs/sprint_4_serialization_gaps.md"
    )
    assert not hasattr(scene.heat_field, "from_dict"), (
        "HeatField gained a from_dict — update docs/sprint_4_serialization_gaps.md"
    )

    # ── ZoneManager: no to_dict / from_dict ──────────────────────────────
    assert not hasattr(scene.zone_manager, "to_dict"), (
        "ZoneManager gained a to_dict — update docs/sprint_4_serialization_gaps.md"
    )
    assert not hasattr(scene.zone_manager, "from_dict"), (
        "ZoneManager gained a from_dict — update docs/sprint_4_serialization_gaps.md"
    )

    # ── WaveSchedule: no to_dict / from_dict ─────────────────────────────
    assert not hasattr(scene.schedule, "to_dict"), (
        "WaveSchedule gained a to_dict — update docs/sprint_4_serialization_gaps.md"
    )
    assert not hasattr(scene.schedule, "from_dict"), (
        "WaveSchedule gained a from_dict — update docs/sprint_4_serialization_gaps.md"
    )

    # ── telemetry: history is in-process only ───────────────────────────
    # Module-level history exists but there is no JSON round-trip.
    assert not hasattr(telemetry, "save_history"), (
        "telemetry gained save_history — update docs/sprint_4_serialization_gaps.md"
    )
    assert not hasattr(telemetry, "load_history"), (
        "telemetry gained load_history — update docs/sprint_4_serialization_gaps.md"
    )
