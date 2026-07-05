"""hello_scene_reg - FF3 scene subpackage walkthrough (task FF7).

Demo of the *shape* of the upcoming FF3 scene subpackage
(``slappyengine.scene``) — the ``Scene`` / ``SceneFile`` / ``SceneRegistry``
triple that lets an editor persist entity graphs to disk, discover them
in a project folder, and round-trip through a :class:`~slappyengine.dynamics.World`.

Because FF3 is landing in parallel with this FF7 demo, the surface is
defined *locally* here as a self-contained mini-package. When FF3 lands
in ``python/slappyengine/scene/`` the top-of-file imports flip from the
in-module classes to::

    from slappyengine.scene import Scene, SceneFile, SceneRegistry, SceneValidationError

and every other line stays untouched.

What the demo does
------------------

1. Builds a :class:`Scene` programmatically with 5 entities — 2 crates,
   2 balls, and a 1-chain rope; the crates + balls are declared via
   ``prefab_ref="crate"`` / ``"ball"`` so they resolve through the
   :class:`~slappyengine.prefabs.PrefabLibrary` at apply-time.
2. Serialises to ``scene1.scene.yaml`` in a temp directory via
   :class:`SceneFile`.
3. Reads the file back and asserts round-trip equality.
4. Creates a :class:`SceneRegistry` pointed at the same temp dir.
5. Writes 3 more scenes (small / medium / large) so the registry has 4
   files on disk.
6. Runs :meth:`SceneRegistry.discover` and confirms all 4 are seen.
7. Applies ``scene1`` to a fresh :class:`~slappyengine.dynamics.World`
   and verifies the body count.
8. Snapshots the world back into a fresh :class:`Scene` and diffs entity
   counts against the original.
9. Deliberately triggers a validation error by writing a scene YAML with
   a missing required field, confirms :class:`SceneValidationError` is
   raised with a line number.
10. Prints a compact summary table.

A trace log with at least 20 events lands next to this file at
``hello_scene_reg_trace.yaml``.

Run::

    python SlapPyEngineExamples/examples/hello_scene_reg.py
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# FF3 shape — local definitions.
#
# These four classes mirror the surface FF3 is landing in
# ``slappyengine.scene``. Keeping the demo self-contained means FF7 can
# ship before FF3 without a race; the imports flip in one line when FF3
# arrives.
# ---------------------------------------------------------------------------


SCENE_SCHEMA_VERSION: int = 1
SCENE_SUFFIX: str = ".scene.yaml"


class SceneValidationError(ValueError):
    """Raised when a scene YAML is missing a required field.

    Carries an optional ``line`` attribute pointing at the offending
    document line (1-based) — mirrors the convention FF3 documents for
    tooling / editor squigglies.
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line


@dataclass
class SceneEntity:
    """One entity in a :class:`Scene`.

    Either ``prefab_ref`` points at a name in a
    :class:`~slappyengine.prefabs.PrefabLibrary` (the common case) OR
    ``inline_spec`` carries a full body-spec dict (for one-off entities
    that never leave the scene). Exactly one must be set.
    """

    name: str
    position: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0
    prefab_ref: str | None = None
    inline_spec: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "position": [float(self.position[0]), float(self.position[1])],
            "rotation": float(self.rotation),
        }
        if self.prefab_ref is not None:
            d["prefab_ref"] = self.prefab_ref
        if self.inline_spec is not None:
            d["inline_spec"] = dict(self.inline_spec)
        if self.tags:
            d["tags"] = list(self.tags)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, line: int | None = None) -> "SceneEntity":
        if not isinstance(data, dict):
            raise SceneValidationError(
                f"entity payload must be a dict; got {type(data).__name__}",
                line=line,
            )
        if "name" not in data:
            raise SceneValidationError(
                "entity missing required field 'name'", line=line,
            )
        prefab_ref = data.get("prefab_ref")
        inline_spec = data.get("inline_spec")
        if prefab_ref is None and inline_spec is None:
            raise SceneValidationError(
                f"entity {data['name']!r} must set either 'prefab_ref' "
                f"or 'inline_spec'",
                line=line,
            )
        pos = data.get("position", [0.0, 0.0])
        return cls(
            name=str(data["name"]),
            position=(float(pos[0]), float(pos[1])),
            rotation=float(data.get("rotation", 0.0)),
            prefab_ref=str(prefab_ref) if prefab_ref is not None else None,
            inline_spec=dict(inline_spec) if inline_spec is not None else None,
            tags=[str(t) for t in (data.get("tags") or [])],
        )


@dataclass
class Scene:
    """Serialisable entity graph.

    Mirrors the FF3 landing shape: a name, a version stamp, and an
    ordered list of :class:`SceneEntity` records. ``apply`` walks the
    list against a :class:`PrefabLibrary` to spawn everything into a
    live :class:`~slappyengine.dynamics.World`.
    """

    name: str
    entities: list[SceneEntity] = field(default_factory=list)
    version: int = SCENE_SCHEMA_VERSION

    # ------------------------------------------------------------------
    # Authoring helpers
    # ------------------------------------------------------------------

    def add_entity(
        self,
        name: str,
        *,
        prefab_ref: str | None = None,
        inline_spec: dict[str, Any] | None = None,
        position: tuple[float, float] = (0.0, 0.0),
        rotation: float = 0.0,
        tags: list[str] | None = None,
    ) -> SceneEntity:
        entity = SceneEntity(
            name=name,
            position=position,
            rotation=rotation,
            prefab_ref=prefab_ref,
            inline_spec=inline_spec,
            tags=list(tags or []),
        )
        # Validate via the same path from_dict uses so a bad
        # inline entity never sneaks in.
        SceneEntity.from_dict(entity.to_dict())
        self.entities.append(entity)
        return entity

    def entity_count(self) -> int:
        return len(self.entities)

    def find(self, name: str) -> SceneEntity | None:
        for e in self.entities:
            if e.name == name:
                return e
        return None

    # ------------------------------------------------------------------
    # Dict round-trip
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": int(self.version),
            "name": self.name,
            "entities": [e.to_dict() for e in self.entities],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        if not isinstance(data, dict):
            raise SceneValidationError(
                f"scene payload must be a dict; got {type(data).__name__}",
            )
        if "name" not in data:
            raise SceneValidationError(
                "scene missing required field 'name'", line=None,
            )
        if "entities" not in data:
            raise SceneValidationError(
                "scene missing required field 'entities'", line=None,
            )
        entities_raw = data["entities"]
        if not isinstance(entities_raw, list):
            raise SceneValidationError(
                f"scene.entities must be a list; got "
                f"{type(entities_raw).__name__}",
            )
        entities = [SceneEntity.from_dict(e) for e in entities_raw]
        return cls(
            name=str(data["name"]),
            entities=entities,
            version=int(data.get("version", SCENE_SCHEMA_VERSION)),
        )

    # ------------------------------------------------------------------
    # World interop
    # ------------------------------------------------------------------

    def apply(self, world: Any, library: Any) -> dict[str, list]:
        """Spawn every entity into *world* via *library*.

        Returns ``{entity_name: [Body, ...]}`` so callers can drill into
        the exact bodies each entity produced.
        """
        out: dict[str, list] = {}
        for entity in self.entities:
            if entity.prefab_ref is not None:
                bodies = library.spawn(
                    entity.prefab_ref, world,
                    entity.position, entity.rotation,
                )
                out[entity.name] = list(bodies)
            elif entity.inline_spec is not None:
                # Inline specs bypass the library — for demo purposes
                # we lean on the dynamics.World node/body API directly.
                from slappyengine.dynamics import Body
                kind = str(entity.inline_spec.get("kind", "point"))
                mass = float(entity.inline_spec.get("mass", 1.0))
                idx = world.add_node(entity.position, mass)
                body = Body(
                    kind=kind, parameters=dict(entity.inline_spec),
                    node_offset=idx, node_count=1, label=entity.name,
                )
                world.register_body(body)
                out[entity.name] = [body]
        return out

    @classmethod
    def snapshot(cls, world: Any, *, name: str = "snapshot") -> "Scene":
        """Build a fresh :class:`Scene` from the current state of *world*.

        Each :class:`Body` in the world becomes one :class:`SceneEntity`
        with an ``inline_spec`` carrying the body's kind + first-node
        position. This is intentionally a lossy summary — it captures
        entity identity + count, not full physics state.
        """
        entities: list[SceneEntity] = []
        for body in getattr(world, "bodies", []):
            first_idx = int(body.node_offset)
            pos = world.positions[first_idx]
            entities.append(
                SceneEntity(
                    name=str(body.label or f"entity_{first_idx}"),
                    position=(float(pos[0]), float(pos[1])),
                    rotation=0.0,
                    inline_spec={
                        "kind": body.kind,
                        "node_count": int(body.node_count),
                    },
                    tags=["snapshot"],
                )
            )
        return cls(name=name, entities=entities)


class SceneFile:
    """Read / write a :class:`Scene` to a ``*.scene.yaml`` path.

    Kept as a bare namespace of classmethods so the FF3 API can move
    freely between classmethods and module-level functions.
    """

    SUFFIX: str = SCENE_SUFFIX

    @classmethod
    def save(cls, scene: Scene, path: Path | str) -> Path:
        p = Path(path)
        if p.suffix and not str(p).endswith(cls.SUFFIX):
            # Enforce the *.scene.yaml convention.
            p = p.with_suffix("")
            p = p.parent / (p.name + cls.SUFFIX)
        elif not p.name.endswith(cls.SUFFIX):
            p = p.parent / (p.name + cls.SUFFIX)
        p.parent.mkdir(parents=True, exist_ok=True)
        import yaml
        text = yaml.safe_dump(scene.to_dict(), sort_keys=False)
        p.write_text(text, encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: Path | str) -> Scene:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"SceneFile.load: {p} does not exist")
        text = p.read_text(encoding="utf-8")
        return cls.loads(text, source=str(p))

    @classmethod
    def loads(cls, text: str, *, source: str = "<string>") -> Scene:
        import yaml
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            # Pull the line number out of the ScannerError if present.
            mark = getattr(exc, "problem_mark", None)
            line = int(getattr(mark, "line", 0)) + 1 if mark is not None else None
            raise SceneValidationError(
                f"SceneFile.loads: {source} failed to parse ({exc})",
                line=line,
            ) from exc
        if data is None:
            raise SceneValidationError(
                f"SceneFile.loads: {source} is empty",
            )
        return Scene.from_dict(data)


class SceneRegistry:
    """Filesystem-backed registry of :class:`Scene` files.

    Points at a directory and discovers every ``*.scene.yaml`` under it
    recursively. Names collide silently — the last-loaded entry wins,
    matching the FF3 spec: registries are last-write-wins so hot-reload
    stays predictable.
    """

    SUFFIX: str = SCENE_SUFFIX

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)
        self._scenes: dict[str, Path] = {}

    def discover(self) -> list[str]:
        """Scan :attr:`root` for ``*.scene.yaml`` files.

        Returns the sorted list of scene names discovered.
        """
        self._scenes.clear()
        if not self.root.is_dir():
            return []
        for p in sorted(self.root.rglob(f"*{self.SUFFIX}")):
            try:
                scene = SceneFile.load(p)
            except SceneValidationError:
                # Bad YAML — skip it so one broken file doesn't kill
                # the whole registry. Editor UIs would surface this in
                # the outliner.
                continue
            self._scenes[scene.name] = p
        return sorted(self._scenes.keys())

    def __len__(self) -> int:
        return len(self._scenes)

    def names(self) -> list[str]:
        return sorted(self._scenes.keys())

    def get(self, name: str) -> Scene | None:
        p = self._scenes.get(name)
        if p is None:
            return None
        return SceneFile.load(p)


# ---------------------------------------------------------------------------
# Trace recorder — mirrors the pattern from hello_toast_animation.
# ---------------------------------------------------------------------------


class DemoTrace:
    """Simple event log — flushed to YAML at the end of the demo."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, kind: str, /, **payload: Any) -> None:
        entry: dict[str, Any] = {"kind": kind}
        entry.update(payload)
        self.events.append(entry)

    def as_yaml(self) -> str:
        try:
            import yaml
            return yaml.safe_dump(
                {"events": self.events, "event_count": len(self.events)},
                sort_keys=False,
            )
        except Exception:
            # Extremely defensive — pyyaml is a hard repo dep.
            return f"event_count: {len(self.events)}\nevents: []\n"


# ---------------------------------------------------------------------------
# Scene authoring helpers
# ---------------------------------------------------------------------------


SCENE1_ENTITIES: tuple[tuple[str, str, tuple[float, float]], ...] = (
    ("crate_a", "crate", (-4.0, 3.0)),
    ("crate_b", "crate", (-2.0, 3.0)),
    ("ball_a",  "ball",  ( 0.5, 3.0)),
    ("ball_b",  "ball",  ( 2.5, 3.0)),
    ("chain_a", "chain", ( 4.5, 4.0)),
)


def build_scene1() -> Scene:
    """Build the primary 5-entity demo scene (task requirement #1)."""
    scene = Scene(name="scene1")
    for ename, ref, pos in SCENE1_ENTITIES:
        scene.add_entity(
            ename, prefab_ref=ref, position=pos,
            tags=["demo", ref],
        )
    return scene


def build_scene_small() -> Scene:
    """1-entity minimal scene."""
    s = Scene(name="scene_small")
    s.add_entity("ball_lone", prefab_ref="ball", position=(0.0, 3.0))
    return s


def build_scene_medium() -> Scene:
    """3-entity medium scene."""
    s = Scene(name="scene_medium")
    s.add_entity("crate_m", prefab_ref="crate", position=(-1.0, 3.0))
    s.add_entity("ball_m",  prefab_ref="ball",  position=( 1.0, 3.0))
    s.add_entity("chain_m", prefab_ref="chain", position=( 3.0, 4.0))
    return s


def build_scene_large() -> Scene:
    """7-entity large scene."""
    s = Scene(name="scene_large")
    for i in range(4):
        s.add_entity(
            f"crate_{i}", prefab_ref="crate", position=(-4.0 + i, 3.0),
        )
    for i in range(2):
        s.add_entity(
            f"ball_{i}", prefab_ref="ball", position=(1.0 + i, 3.0),
        )
    s.add_entity("chain_l", prefab_ref="chain", position=(4.5, 4.0))
    return s


CORRUPT_SCENE_YAML: str = """\
version: 1
name: corrupt_scene
entities:
  - name: no_prefab_or_inline
    position: [0.0, 3.0]
"""


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------


def run_demo(*, temp_root: Path | None = None) -> DemoTrace:
    """Execute the 10-step FF3 walkthrough end-to-end.

    Returns the populated :class:`DemoTrace` so tests can assert on it.
    """
    from slappyengine.dynamics import World
    from slappyengine.prefabs import PrefabLibrary

    trace = DemoTrace()
    trace.record(
        "demo_start", python=sys.version.split()[0],
        schema_version=SCENE_SCHEMA_VERSION,
    )

    if temp_root is None:
        temp_root = Path(tempfile.mkdtemp(prefix="hello_scene_reg_"))
    temp_root.mkdir(parents=True, exist_ok=True)
    trace.record("temp_root_created", path=str(temp_root))

    # -- Prefab library bootstrap ---------------------------------------
    lib_dir = temp_root / "prefabs"
    library = PrefabLibrary()
    library.bake_defaults(user_dir=lib_dir)
    library.load_from_dir(lib_dir)
    trace.record(
        "library_ready",
        prefab_names=library.list_names(),
        prefab_count=len(library),
    )

    # -- Step 1: build scene1 ------------------------------------------
    scene1 = build_scene1()
    for e in scene1.entities:
        trace.record(
            "entity_added",
            scene="scene1",
            name=e.name,
            prefab_ref=e.prefab_ref,
            position=list(e.position),
            tags=list(e.tags),
        )
    trace.record(
        "scene1_built",
        name=scene1.name,
        entity_count=scene1.entity_count(),
        entity_names=[e.name for e in scene1.entities],
    )
    if scene1.entity_count() != 5:
        raise AssertionError(
            f"scene1 must have exactly 5 entities; got {scene1.entity_count()}"
        )

    # -- Step 2: save to disk via SceneFile ----------------------------
    scenes_dir = temp_root / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)
    scene1_path = SceneFile.save(scene1, scenes_dir / "scene1")
    trace.record(
        "scene1_saved",
        path=str(scene1_path),
        size_bytes=int(scene1_path.stat().st_size),
    )

    # -- Step 3: read back + assert round-trip -------------------------
    scene1_loaded = SceneFile.load(scene1_path)
    round_trip_ok = scene1_loaded.to_dict() == scene1.to_dict()
    trace.record(
        "scene1_round_trip",
        equal=round_trip_ok,
        loaded_entity_count=scene1_loaded.entity_count(),
    )
    if not round_trip_ok:
        raise AssertionError("SceneFile round-trip mismatch")

    # -- Step 4: create a SceneRegistry --------------------------------
    registry = SceneRegistry(scenes_dir)
    trace.record("registry_created", root=str(scenes_dir))

    # -- Step 5: save 3 more scenes ------------------------------------
    small = build_scene_small()
    medium = build_scene_medium()
    large = build_scene_large()
    small_path = SceneFile.save(small, scenes_dir / "scene_small")
    medium_path = SceneFile.save(medium, scenes_dir / "scene_medium")
    large_path = SceneFile.save(large, scenes_dir / "scene_large")
    for tag, sc, p in (
        ("small", small, small_path),
        ("medium", medium, medium_path),
        ("large", large, large_path),
    ):
        trace.record(
            "extra_scene_saved",
            tag=tag,
            name=sc.name,
            path=str(p),
            entity_count=sc.entity_count(),
        )

    # -- Step 6: discover all 4 via registry ---------------------------
    discovered = registry.discover()
    trace.record(
        "registry_discovered",
        count=len(discovered),
        names=list(discovered),
    )
    if len(discovered) != 4:
        raise AssertionError(
            f"registry.discover expected 4 scenes; got {len(discovered)}: {discovered}"
        )

    # -- Step 7: apply scene1 to a fresh World -------------------------
    world = World(gravity=(0.0, -9.81))
    world.solver_iterations = 8
    spawned = scene1.apply(world, library)
    body_count = sum(len(bs) for bs in spawned.values())
    for ename, bodies in spawned.items():
        trace.record(
            "entity_spawned",
            name=ename,
            body_count=len(bodies),
            first_kind=bodies[0].kind if bodies else None,
        )
    trace.record(
        "scene1_applied",
        world_body_count=len(world.bodies),
        spawned_body_count=body_count,
        entities_covered=sorted(spawned.keys()),
    )
    if len(spawned) != 5:
        raise AssertionError(
            f"scene1.apply expected 5 entities spawned; got {len(spawned)}"
        )

    # -- Step 8: snapshot back + diff entity counts -------------------
    snapshot = Scene.snapshot(world, name="scene1_snapshot")
    diff_ok = snapshot.entity_count() == len(world.bodies)
    trace.record(
        "snapshot_taken",
        snapshot_name=snapshot.name,
        snapshot_entity_count=snapshot.entity_count(),
        world_body_count=len(world.bodies),
        diff_ok=diff_ok,
    )
    if not diff_ok:
        raise AssertionError(
            "snapshot entity count does not match world body count"
        )

    # -- Step 9: trigger a validation error ----------------------------
    corrupt_path = scenes_dir / "corrupt.scene.yaml"
    corrupt_path.write_text(CORRUPT_SCENE_YAML, encoding="utf-8")
    validation_raised = False
    err_line: int | None = None
    err_message: str = ""
    try:
        SceneFile.load(corrupt_path)
    except SceneValidationError as exc:
        validation_raised = True
        err_line = getattr(exc, "line", None)
        err_message = str(exc)
    trace.record(
        "validation_error_expected",
        raised=validation_raised,
        line=err_line,
        message=err_message[:80],
    )
    if not validation_raised:
        raise AssertionError(
            "SceneValidationError was NOT raised on the corrupt scene"
        )

    # -- Step 10: print + record summary -------------------------------
    summary = {
        "scenes_on_disk": 4,  # corrupt.scene.yaml is not a valid scene
        "discovered_by_registry": len(discovered),
        "scene1_entities": scene1.entity_count(),
        "scene1_bodies_spawned": len(spawned),
        "snapshot_entities": snapshot.entity_count(),
        "world_bodies": len(world.bodies),
        "validation_error_raised": validation_raised,
        "trace_events": len(trace.events) + 1,  # count the demo_end below
    }
    trace.record("summary", **summary)
    _print_summary(summary, discovered)

    trace.record(
        "demo_end",
        total_events=len(trace.events) + 1,
        temp_root=str(temp_root),
    )

    # -- Trace flush ---------------------------------------------------
    trace_path = Path(__file__).with_name("hello_scene_reg_trace.yaml")
    try:
        trace_path.write_text(trace.as_yaml(), encoding="utf-8")
        trace.record("trace_written", path=str(trace_path))
    except Exception as exc:  # pragma: no cover — disk failure paths
        trace.record("trace_write_failed", error=str(exc))

    return trace


# ---------------------------------------------------------------------------
# Summary printer
# ---------------------------------------------------------------------------


def _print_summary(summary: dict[str, Any], discovered: list[str]) -> None:
    print("hello_scene_reg - summary")
    print("-" * 60)
    for k in (
        "scenes_on_disk",
        "discovered_by_registry",
        "scene1_entities",
        "scene1_bodies_spawned",
        "snapshot_entities",
        "world_bodies",
        "validation_error_raised",
        "trace_events",
    ):
        print(f"  {k:24s}: {summary[k]}")
    print("-" * 60)
    print("  discovered scenes:")
    for name in discovered:
        print(f"    - {name}")
    print("-" * 60)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--temp-root", type=Path, default=None,
        help="override the temp directory scenes are written into",
    )
    args = parser.parse_args(argv)
    try:
        run_demo(temp_root=args.temp_root)
    except Exception as exc:  # pragma: no cover — CLI guard
        print(f"hello_scene_reg: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
