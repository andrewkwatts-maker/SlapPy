"""``Scene`` dataclass — YAML-serialisable authoring container (FF3).

A :class:`Scene` is a lightweight authoring document that lists the
entities placed into a :class:`pharos_engine.dynamics.World`. It sits one
level above :class:`pharos_engine.prefabs.Prefab` — a scene composes many
prefabs / body specs at named world positions and remembers arbitrary
per-entity parameter overrides.

The scene format is deliberately kept independent of the runtime
:class:`pharos_engine.scene.Scene` (which owns a live entity graph, event
bus, and GPU state). This class is the *serialised* view: just enough
information to reconstruct a world of bodies via :meth:`apply_to_world`
and to round-trip the result back to disk via :meth:`snapshot_from_world`
and :meth:`to_yaml`.

YAML shape (schema v1)::

    schema_version: 1
    name: intro_pit
    metadata:
      author: sprint-ff3
      description: Two boxes over a rope
    layers:
      - default
      - foreground
    entities:
      - id: entity_0
        kind: box
        position: [0.0, 3.0]
        params:
          width: 1.0
          height: 1.0
          mass: 5.0
      - id: entity_1
        kind: point
        position: [-2.0, 1.0]
        params: {mass: 2.0}
        prefab_ref: pickup_ball    # optional — resolved via PrefabLibrary

Design notes
~~~~~~~~~~~~
* Every entity is stored as a plain dict so YAML round-trip is lossless
  without touching the dynamics-side dataclass constructors. The shape
  mirrors :class:`pharos_engine.prefabs.Prefab` — anything the prefab
  system can spawn is a valid scene entity.
* :meth:`add_entity` mints unique ``id`` strings when omitted so the
  editor can generate scenes without tracking a counter.
* :meth:`snapshot_from_world` reads the position from the *first* node in
  each body's slice — the same convention prefabs use when placing bodies.
* No mutation of the runtime :class:`pharos_engine.scene.Scene` — this
  serialiser only talks to the dynamics :class:`~pharos_engine.dynamics.World`
  and the :class:`pharos_engine.prefabs.PrefabLibrary`.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pharos_engine._validation import validate_non_empty_str

if TYPE_CHECKING:  # pragma: no cover
    from pharos_engine.dynamics import World
    from pharos_engine.prefabs import PrefabLibrary


#: Schema version bumped whenever the on-disk YAML shape breaks
#: compatibility. Loaders should reject other versions loudly.
SCHEMA_VERSION: int = 1

#: Body kinds the scene can spawn directly without a prefab reference.
#: Mirrors :data:`pharos_engine.prefabs.prefab._BODY_KINDS`.
_KNOWN_KINDS: tuple[str, ...] = (
    "point",
    "circle",
    "box",
    "rope",
    "ragdoll",
    "chain",
    "composite",
)


class SceneValidationError(ValueError):
    """Raised when a :class:`Scene` payload is malformed.

    When the error originates from a YAML source the ``line`` attribute
    carries the 1-based source line so editors can surface the caret.
    ``line`` is ``None`` for structural problems that have no textual
    origin (e.g. an in-memory dict with a missing key).
    """

    def __init__(self, message: str, *, line: int | None = None) -> None:
        self.line = line
        prefix = f"[line {line}] " if line is not None else ""
        super().__init__(prefix + message)


# ---------------------------------------------------------------------------
# Scene dataclass
# ---------------------------------------------------------------------------


@dataclass
class Scene:
    """One authoring scene — a list of entities placed at world positions.

    Parameters
    ----------
    name:
        Human-readable scene name; must be a non-empty ``str``.
    entities:
        List of entity dicts. Each dict must contain ``id``, ``kind``,
        ``position``, and ``params`` and may optionally include a
        ``prefab_ref`` key naming an entry in a
        :class:`pharos_engine.prefabs.PrefabLibrary`.
    layers:
        Ordered list of logical draw / gameplay layer names. Purely
        informational — the runtime consumes them when it wires the
        world into a renderer.
    metadata:
        Free-form dict for author / project notes. Never inspected by
        the loader / applier.
    """

    name: str = "Scene"
    entities: list[dict[str, Any]] = field(default_factory=list)
    layers: list[str] = field(default_factory=lambda: ["default"])
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = validate_non_empty_str("name", "Scene", self.name)
        if not isinstance(self.entities, list):
            raise TypeError(
                f"Scene.entities must be a list; got "
                f"{type(self.entities).__name__}"
            )
        for i, ent in enumerate(list(self.entities)):
            self.entities[i] = _validate_entity_dict(
                ent, path=f"Scene.entities[{i}]",
            )
        if not isinstance(self.layers, list):
            raise TypeError(
                f"Scene.layers must be a list; got "
                f"{type(self.layers).__name__}"
            )
        for i, layer in enumerate(self.layers):
            if not isinstance(layer, str) or not layer:
                raise ValueError(
                    f"Scene.layers[{i}] must be a non-empty str; "
                    f"got {layer!r}"
                )
        if not isinstance(self.metadata, dict):
            raise TypeError(
                f"Scene.metadata must be a dict; got "
                f"{type(self.metadata).__name__}"
            )

    # ------------------------------------------------------------------
    # Entity management
    # ------------------------------------------------------------------

    def add_entity(self, entity: dict[str, Any]) -> str:
        """Append *entity*, minting an ``id`` when the caller omits one.

        Returns
        -------
        str
            The final ``id`` of the newly added entity (either the
            caller-supplied value or a freshly-minted ``entity_N``).

        Raises
        ------
        TypeError
            If *entity* is not a dict.
        SceneValidationError
            If required keys are missing, the ``kind`` is unknown, or
            the id collides with an existing entity.
        """
        if not isinstance(entity, dict):
            raise TypeError(
                f"Scene.add_entity: entity must be a dict; "
                f"got {type(entity).__name__}"
            )
        ent = dict(entity)
        if "id" not in ent or ent.get("id") in (None, ""):
            ent["id"] = self._mint_id()
        existing_ids = {e["id"] for e in self.entities}
        if ent["id"] in existing_ids:
            raise SceneValidationError(
                f"Scene.add_entity: id {ent['id']!r} already present"
            )
        validated = _validate_entity_dict(ent, path="Scene.add_entity(entity)")
        self.entities.append(validated)
        return validated["id"]

    def remove_entity(self, entity_id: str) -> bool:
        """Remove the entity with *entity_id*; returns ``True`` if found.

        Never raises for a missing id — returns ``False`` so callers can
        idempotently reconcile authoring diffs.
        """
        if not isinstance(entity_id, str):
            return False
        for i, ent in enumerate(self.entities):
            if ent.get("id") == entity_id:
                del self.entities[i]
                return True
        return False

    def find_by_name(self, name: str) -> list[dict[str, Any]]:
        """Return every entity whose ``metadata['name']`` matches *name*.

        Editor code labels entities via ``entity['metadata']['name']`` so
        prefab-spawned instances can be searched by human-readable name
        without touching the internal id.
        """
        if not isinstance(name, str) or not name:
            return []
        out: list[dict[str, Any]] = []
        for ent in self.entities:
            meta = ent.get("metadata") or {}
            if isinstance(meta, dict) and meta.get("name") == name:
                out.append(ent)
            elif ent.get("id") == name:
                out.append(ent)
        return out

    def list_by_kind(self, kind: str) -> list[dict[str, Any]]:
        """Return every entity whose ``kind`` equals *kind*."""
        if not isinstance(kind, str) or not kind:
            return []
        return [e for e in self.entities if e.get("kind") == kind]

    def get(self, entity_id: str) -> dict[str, Any] | None:
        """Return the entity dict with *entity_id*, or ``None``."""
        if not isinstance(entity_id, str):
            return None
        for ent in self.entities:
            if ent.get("id") == entity_id:
                return ent
        return None

    def __len__(self) -> int:
        return len(self.entities)

    def _mint_id(self) -> str:
        """Mint an ``entity_N`` id that doesn't collide with existing ones."""
        n = len(self.entities)
        existing = {e.get("id") for e in self.entities}
        while f"entity_{n}" in existing:
            n += 1
        return f"entity_{n}"

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict view suitable for JSON / YAML."""
        return {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "metadata": dict(self.metadata),
            "layers": list(self.layers),
            "entities": [dict(e) for e in self.entities],
        }

    def to_yaml(self) -> str:
        """Serialise as human-readable YAML (round-trips through
        :meth:`from_yaml`).

        Uses ``yaml.safe_dump(sort_keys=False)`` so the field order
        matches :meth:`to_dict` — schema_version first, then name,
        metadata, layers, entities. Editors reading the file top-to-
        bottom get the metadata block before the (potentially long)
        entity list.
        """
        import yaml  # local: keeps import cheap when scene YAML unused

        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Scene":
        """Construct a :class:`Scene` from a plain dict.

        Raises
        ------
        SceneValidationError
            If ``data`` is not a dict, has an unsupported
            ``schema_version``, or contains malformed entities.
        """
        if not isinstance(data, dict):
            raise SceneValidationError(
                f"Scene.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        schema = data.get("schema_version", SCHEMA_VERSION)
        if schema != SCHEMA_VERSION:
            raise SceneValidationError(
                f"Scene.from_dict: unsupported schema_version {schema!r} "
                f"(this build expects {SCHEMA_VERSION})"
            )
        name = data.get("name", "Scene")
        if not isinstance(name, str) or not name:
            raise SceneValidationError(
                f"Scene.from_dict: name must be a non-empty str; got {name!r}"
            )
        entities_raw = data.get("entities", [])
        if not isinstance(entities_raw, list):
            raise SceneValidationError(
                f"Scene.from_dict: entities must be a list; "
                f"got {type(entities_raw).__name__}"
            )
        layers_raw = data.get("layers", ["default"])
        if not isinstance(layers_raw, list):
            raise SceneValidationError(
                f"Scene.from_dict: layers must be a list; "
                f"got {type(layers_raw).__name__}"
            )
        metadata_raw = data.get("metadata", {})
        if not isinstance(metadata_raw, dict):
            raise SceneValidationError(
                f"Scene.from_dict: metadata must be a dict; "
                f"got {type(metadata_raw).__name__}"
            )
        # Validate each entity dict via the same path the constructor uses.
        entities: list[dict[str, Any]] = []
        for i, ent in enumerate(entities_raw):
            entities.append(
                _validate_entity_dict(ent, path=f"entities[{i}]")
            )
        return cls(
            name=str(name),
            entities=entities,
            layers=[str(l) for l in layers_raw],
            metadata=dict(metadata_raw),
        )

    @classmethod
    def from_yaml(cls, text: str) -> "Scene":
        """Parse a YAML string produced by :meth:`to_yaml`.

        Raises
        ------
        SceneValidationError
            If ``text`` is not valid YAML or does not decode to the
            expected shape. When the YAML parser reports a line number
            it is preserved on the raised exception.
        """
        if not isinstance(text, str):
            raise SceneValidationError(
                f"Scene.from_yaml: text must be a str; "
                f"got {type(text).__name__}"
            )
        import yaml

        try:
            payload = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            line = None
            mark = getattr(exc, "problem_mark", None) or getattr(
                exc, "context_mark", None,
            )
            if mark is not None:
                line = int(mark.line) + 1  # PyYAML marks are 0-based
            raise SceneValidationError(
                f"Scene.from_yaml: invalid YAML ({exc})", line=line,
            ) from exc
        if payload is None:
            raise SceneValidationError(
                "Scene.from_yaml: YAML decoded to None (empty document)"
            )
        if not isinstance(payload, dict):
            raise SceneValidationError(
                f"Scene.from_yaml: YAML must decode to a dict; "
                f"got {type(payload).__name__}"
            )
        return cls.from_dict(payload)

    # ------------------------------------------------------------------
    # World interop
    # ------------------------------------------------------------------

    def apply_to_world(
        self,
        world: "World",
        *,
        prefab_library: "PrefabLibrary | None" = None,
    ) -> dict[str, list[Any]]:
        """Instantiate every entity in ``self.entities`` into *world*.

        Returns
        -------
        dict[str, list[Body]]
            Mapping from ``entity['id']`` to the list of
            :class:`pharos_engine.dynamics.body.Body` handles it created.
            The dict makes it trivial for callers to correlate the
            authoring id with the runtime handle.

        Behaviour
        ---------
        * ``prefab_ref`` set: looks the name up in *prefab_library* and
          calls :meth:`Prefab.spawn`. If no library is passed or the
          name is missing, the entity is skipped with an empty handle
          list and its ``id`` still appears in the returned dict so the
          caller can tell.
        * ``prefab_ref`` unset: dispatches on ``kind`` via the small
          internal :func:`_spawn_body_from_scene_dict` — a reduced form
          of the prefab body-spec dispatcher that only handles the
          three simple point-mass kinds (``point`` / ``circle`` /
          ``box``). Rope / ragdoll / chain / composite need the prefab
          library and are skipped when none is available.
        """
        if world is None:
            raise TypeError("Scene.apply_to_world: world must not be None")
        out: dict[str, list[Any]] = {}
        for ent in self.entities:
            eid = ent["id"]
            kind = ent["kind"]
            pos = (float(ent["position"][0]), float(ent["position"][1]))
            params = ent.get("params") or {}
            prefab_ref = ent.get("prefab_ref")

            bodies: list[Any] = []
            if prefab_ref:
                if prefab_library is not None:
                    prefab = prefab_library.get(prefab_ref)
                    if prefab is not None:
                        rotation = float(params.get("rotation", 0.0))
                        bodies = list(
                            prefab.spawn(
                                world, pos, rotation,
                                library=prefab_library,
                            )
                        )
                # else: leave bodies empty; caller inspects the empty list.
            else:
                bodies = _spawn_body_from_scene_dict(
                    world, kind, pos, params, label=eid,
                )
            out[eid] = bodies
        return out

    def snapshot_from_world(
        self, world: "World", *, keep_metadata: bool = True,
    ) -> None:
        """Replace ``self.entities`` with a snapshot of ``world.bodies``.

        Each :class:`pharos_engine.dynamics.body.Body` in ``world`` is
        translated into a scene entity dict using the *first* node's
        world position as the entity ``position``. The body's ``label``
        becomes the entity ``id`` (falling back to ``entity_N`` when
        the label is empty) and its ``parameters`` become the entity
        ``params``.

        When ``keep_metadata`` is ``True`` (default) the scene's
        top-level ``metadata`` and ``layers`` are preserved so callers
        can round-trip a live world back to disk without losing the
        author's project-level tags.
        """
        if world is None:
            raise TypeError(
                "Scene.snapshot_from_world: world must not be None"
            )
        # Snapshot: preserve top-level fields, replace entities.
        new_entities: list[dict[str, Any]] = []
        for i, body in enumerate(world.bodies):
            if body.node_count == 0:
                # Bodies with no nodes can't have a position; skip.
                continue
            first_idx = body.node_offset
            if first_idx < 0 or first_idx >= world.positions.shape[0]:
                continue
            px, py = world.positions[first_idx]
            eid = body.label or f"entity_{i}"
            # Guarantee id uniqueness inside the snapshot.
            existing_ids = {e["id"] for e in new_entities}
            if eid in existing_ids:
                suffix = 0
                while f"{eid}_{suffix}" in existing_ids:
                    suffix += 1
                eid = f"{eid}_{suffix}"
            entity = {
                "id": eid,
                "kind": str(body.kind),
                "position": [float(px), float(py)],
                "params": _sanitize_params(body.parameters),
            }
            new_entities.append(entity)
        self.entities = new_entities
        if not keep_metadata:
            self.metadata = {}
            self.layers = ["default"]


# ---------------------------------------------------------------------------
# Entity dict validation
# ---------------------------------------------------------------------------


_REQUIRED_ENTITY_KEYS = ("id", "kind", "position", "params")


def _validate_entity_dict(
    entity: Any, *, path: str,
) -> dict[str, Any]:
    """Validate one entity dict and return a normalised copy.

    Normalisation:
    * ``id`` coerced to ``str``.
    * ``position`` coerced to a fresh 2-element list of floats.
    * ``params`` copied to detach from caller-owned dict.
    * ``prefab_ref`` preserved when present (must be a ``str``).
    * Unknown top-level keys pass through untouched so authoring tools
      can attach editor-only metadata (e.g. UI colour) without the
      loader stripping it.
    """
    if not isinstance(entity, dict):
        raise SceneValidationError(
            f"{path}: entity must be a dict; got {type(entity).__name__}"
        )
    missing = [k for k in _REQUIRED_ENTITY_KEYS if k not in entity]
    if missing:
        raise SceneValidationError(
            f"{path}: missing required keys {missing!r}"
        )
    eid = entity["id"]
    if not isinstance(eid, str) or not eid:
        raise SceneValidationError(
            f"{path}: 'id' must be a non-empty str; got {eid!r}"
        )
    kind = entity["kind"]
    if not isinstance(kind, str) or not kind:
        raise SceneValidationError(
            f"{path}: 'kind' must be a non-empty str; got {kind!r}"
        )
    prefab_ref = entity.get("prefab_ref")
    # A scene entity may skip the known-kind check when it delegates to a
    # prefab (prefab kinds can be user-defined).
    if kind not in _KNOWN_KINDS and not prefab_ref:
        raise SceneValidationError(
            f"{path}: 'kind' {kind!r} is not one of {list(_KNOWN_KINDS)} "
            f"and no 'prefab_ref' was supplied"
        )
    pos = entity["position"]
    if not hasattr(pos, "__len__") or len(pos) != 2:
        raise SceneValidationError(
            f"{path}: 'position' must be a 2-sequence; got {pos!r}"
        )
    try:
        px = float(pos[0])
        py = float(pos[1])
    except (TypeError, ValueError) as exc:
        raise SceneValidationError(
            f"{path}: 'position' entries must be floats; got {pos!r}"
        ) from exc
    if not (math.isfinite(px) and math.isfinite(py)):
        raise SceneValidationError(
            f"{path}: 'position' entries must be finite; got {pos!r}"
        )
    params = entity["params"]
    if not isinstance(params, dict):
        raise SceneValidationError(
            f"{path}: 'params' must be a dict; got {type(params).__name__}"
        )
    if prefab_ref is not None and (
        not isinstance(prefab_ref, str) or not prefab_ref
    ):
        raise SceneValidationError(
            f"{path}: 'prefab_ref' must be a non-empty str; "
            f"got {prefab_ref!r}"
        )
    out: dict[str, Any] = dict(entity)
    out["id"] = str(eid)
    out["kind"] = str(kind)
    out["position"] = [px, py]
    out["params"] = dict(params)
    if prefab_ref is not None:
        out["prefab_ref"] = str(prefab_ref)
    return out


# ---------------------------------------------------------------------------
# Body spawn (reduced dispatcher — used when no prefab library is around)
# ---------------------------------------------------------------------------


def _spawn_body_from_scene_dict(
    world: "World",
    kind: str,
    position: tuple[float, float],
    params: dict[str, Any],
    *,
    label: str,
) -> list[Any]:
    """Dispatch a small set of body kinds directly into *world*.

    Handles ``point``, ``circle``, ``box``, and ``composite`` (single
    node). For richer kinds (``rope``, ``ragdoll``, ``chain``) callers
    should route through :class:`pharos_engine.prefabs.PrefabLibrary`
    via :meth:`Scene.apply_to_world`'s ``prefab_ref`` path.

    Returns
    -------
    list[Body]
        The bodies registered with *world*. Empty when *kind* is
        unrecognised.
    """
    from pharos_engine.dynamics import Body, JointSpec

    px, py = position

    if kind == "point":
        mass = float(params.get("mass", 1.0))
        idx = world.add_node((px, py), mass)
        body = Body(
            kind="point",
            parameters=dict(params),
            node_offset=idx,
            node_count=1,
            label=label,
        )
        world.register_body(body)
        return [body]

    if kind == "circle":
        mass = float(params.get("mass", 1.0))
        idx = world.add_node((px, py), mass)
        body = Body(
            kind="circle",
            parameters={
                "radius": float(params.get("radius", 1.0)),
                "bounce": float(params.get("bounce", 0.5)),
                "mass": mass,
            },
            node_offset=idx,
            node_count=1,
            label=label,
        )
        world.register_body(body)
        return [body]

    if kind == "box":
        half_w = float(params.get("width", 1.0)) * 0.5
        half_h = float(params.get("height", 1.0)) * 0.5
        rotation = float(params.get("rotation", 0.0))
        mass = float(params.get("mass", 1.0)) * 0.25  # per corner
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        corners_local = [
            (-half_w, -half_h),
            (half_w, -half_h),
            (half_w, half_h),
            (-half_w, half_h),
        ]
        corners_world: list[tuple[float, float]] = []
        for cx, cy in corners_local:
            wx = px + cos_r * cx - sin_r * cy
            wy = py + sin_r * cx + cos_r * cy
            corners_world.append((wx, wy))
        offset = None
        for cw in corners_world:
            i = world.add_node(cw, mass)
            if offset is None:
                offset = i
        assert offset is not None
        edge = float(params.get("edge_stiffness", 1.0e6))
        diag = float(params.get("diag_stiffness", 5.0e5))
        for i in range(4):
            a = offset + i
            b = offset + (i + 1) % 4
            rest = float(
                math.hypot(
                    corners_world[i][0] - corners_world[(i + 1) % 4][0],
                    corners_world[i][1] - corners_world[(i + 1) % 4][1],
                )
            )
            world.add_joint(
                JointSpec(
                    kind="distance", node_a=a, node_b=b,
                    rest_length=rest, stiffness=edge, damping=0.02,
                )
            )
        for a_i, b_i in ((0, 2), (1, 3)):
            a = offset + a_i
            b = offset + b_i
            rest = float(
                math.hypot(
                    corners_world[a_i][0] - corners_world[b_i][0],
                    corners_world[a_i][1] - corners_world[b_i][1],
                )
            )
            world.add_joint(
                JointSpec(
                    kind="distance", node_a=a, node_b=b,
                    rest_length=rest, stiffness=diag, damping=0.02,
                )
            )
        body = Body(
            kind="box",
            parameters={
                "width": float(params.get("width", 1.0)),
                "height": float(params.get("height", 1.0)),
                "mass": float(params.get("mass", 1.0)),
            },
            node_offset=offset,
            node_count=4,
            label=label,
        )
        world.register_body(body)
        return [body]

    if kind == "composite":
        idx = world.add_node((px, py), float(params.get("mass", 0.0)))
        body = Body(
            kind="composite",
            parameters=dict(params),
            node_offset=idx,
            node_count=1,
            label=label,
        )
        world.register_body(body)
        return [body]

    # Unknown / advanced kinds — caller can supply a prefab library.
    return []


def _sanitize_params(value: Any) -> dict[str, Any]:
    """Cheaply coerce a body parameters dict for YAML round-trip.

    Preserves ``str`` / ``int`` / ``float`` / ``bool`` / ``None``; casts
    numpy scalars to Python primitives; recurses into nested list / dict.
    Anything more exotic falls back to ``str(...)`` so the scene YAML
    never contains a language-native object reference.
    """
    if isinstance(value, dict):
        return {str(k): _sanitize_leaf(v) for k, v in value.items()}
    return {}


def _sanitize_leaf(value: Any) -> Any:
    import numpy as np

    if isinstance(value, (bool, str)) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, np.ndarray):
        return [_sanitize_leaf(v) for v in value.tolist()]
    if isinstance(value, (list, tuple)):
        return [_sanitize_leaf(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _sanitize_leaf(v) for k, v in value.items()}
    return str(value)


__all__ = [
    "SCHEMA_VERSION",
    "Scene",
    "SceneValidationError",
]
