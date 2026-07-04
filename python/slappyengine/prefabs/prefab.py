"""Prefab dataclass — reusable entity template loadable from YAML.

A prefab is a serialisable recipe for spawning a small entity in a
:class:`slappyengine.dynamics.World`. Each prefab bundles a *body spec*
(the shape of one or more :class:`~slappyengine.dynamics.body.Body`
handles), a list of :class:`~slappyengine.dynamics.joint.JointSpec`
dicts, an optional list of child prefab names for composition, and
free-form metadata for editor / gameplay tagging.

Prefabs deliberately store their spec as plain ``dict`` payloads so the
YAML round-trip is lossless without touching the dynamics-side dataclass
constructors. :meth:`Prefab.spawn` materialises the prefab into a real
world, returning the :class:`Body` handles it created.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from slappyengine._validation import validate_non_empty_str

if TYPE_CHECKING:  # pragma: no cover
    from slappyengine.dynamics import Body, World

# The five categories the trading-card deck buckets prefabs into. Kept
# as a module-level tuple so tests and the editor can enumerate them
# without importing :class:`Prefab`.
CATEGORIES: tuple[str, ...] = (
    "props",
    "characters",
    "vehicles",
    "particles",
    "structural",
)

# The body-spec kinds recognised by :meth:`Prefab.spawn`. Each kind maps
# onto a small builder inside :func:`_spawn_body_spec` below.
_BODY_KINDS: tuple[str, ...] = (
    "point",
    "circle",
    "box",
    "rope",
    "ragdoll",
    "chain",
    "composite",
)


@dataclass
class Prefab:
    """One reusable entity template.

    Parameters
    ----------
    name:
        Unique identifier the library keys on. Non-empty string.
    category:
        One of :data:`CATEGORIES`.
    body_spec:
        Dict shape describing the primary body. Must contain a ``"kind"``
        key drawn from :data:`_BODY_KINDS`; other keys are kind-specific
        (see :func:`_spawn_body_spec`).
    joint_specs:
        List of :class:`~slappyengine.dynamics.joint.JointSpec` dicts.
        Each dict is passed through :func:`_joint_from_dict` at spawn
        time, so authoring code and YAML never touches the runtime
        dataclass directly.
    child_prefabs:
        Names of other prefabs composed into this one. When a prefab
        library is available at spawn time, each child is instantiated
        alongside the parent (see :meth:`spawn`).
    metadata:
        Arbitrary user tags — the library never inspects this dict.

    Raises
    ------
    TypeError
        If any field is the wrong type.
    ValueError
        If ``name`` is empty, ``category`` is not in :data:`CATEGORIES`,
        or ``body_spec`` is missing / has an unknown ``"kind"``.
    """

    name: str
    category: str
    body_spec: dict[str, Any] = field(default_factory=dict)
    joint_specs: list[dict[str, Any]] = field(default_factory=list)
    child_prefabs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.name = validate_non_empty_str("name", "Prefab", self.name)
        if not isinstance(self.category, str):
            raise TypeError(
                f"Prefab.category must be a str; got "
                f"{type(self.category).__name__}"
            )
        if self.category not in CATEGORIES:
            raise ValueError(
                f"Prefab.category must be one of {list(CATEGORIES)}; "
                f"got {self.category!r}"
            )
        if not isinstance(self.body_spec, dict):
            raise TypeError(
                f"Prefab.body_spec must be a dict; got "
                f"{type(self.body_spec).__name__}"
            )
        if "kind" not in self.body_spec:
            raise ValueError(
                f"Prefab.body_spec must contain a 'kind' key "
                f"(one of {list(_BODY_KINDS)})"
            )
        kind = self.body_spec["kind"]
        if kind not in _BODY_KINDS:
            raise ValueError(
                f"Prefab.body_spec['kind'] must be one of "
                f"{list(_BODY_KINDS)}; got {kind!r}"
            )
        if not isinstance(self.joint_specs, list):
            raise TypeError(
                f"Prefab.joint_specs must be a list; got "
                f"{type(self.joint_specs).__name__}"
            )
        for i, js in enumerate(self.joint_specs):
            if not isinstance(js, dict):
                raise TypeError(
                    f"Prefab.joint_specs[{i}] must be a dict; got "
                    f"{type(js).__name__}"
                )
        if not isinstance(self.child_prefabs, list):
            raise TypeError(
                f"Prefab.child_prefabs must be a list; got "
                f"{type(self.child_prefabs).__name__}"
            )
        for i, c in enumerate(self.child_prefabs):
            if not isinstance(c, str) or not c:
                raise ValueError(
                    f"Prefab.child_prefabs[{i}] must be a non-empty str; "
                    f"got {c!r}"
                )
        if not isinstance(self.metadata, dict):
            raise TypeError(
                f"Prefab.metadata must be a dict; got "
                f"{type(self.metadata).__name__}"
            )

    # ------------------------------------------------------------------
    # Entity-count introspection
    # ------------------------------------------------------------------

    @property
    def entity_count(self) -> int:
        """Gameplay entity count for this prefab.

        Convention — matches the way the editor spawn-card widget and
        gameplay HUD reason about "how many things did I just spawn":

        * ``point`` / ``circle`` / ``box`` → ``1`` (one rigid entity).
        * ``rope``    → ``body_spec['segments']`` (fallback ``5``).
        * ``chain``   → ``body_spec['links']`` (fallback ``5``).
        * ``ragdoll`` → ``7`` (matches the shipping humanoid skeleton).
        * ``composite`` → recursive sum of every ``child_prefabs`` entry;
          child lookup requires a library, so the property falls back to
          ``len(body_spec.get('nodes', [1]))`` when no library is
          attached. Callers that need accurate composite totals should
          use :meth:`compute_entity_count` with an explicit library.
        * Anything else → ``len(body_spec.get('nodes', [1]))``.
        """
        return self.compute_entity_count(None)

    def compute_entity_count(self, library: "Any | None" = None) -> int:
        """Compute :attr:`entity_count` with an optional *library* ref.

        Passing a :class:`PrefabLibrary` allows composite prefabs to
        resolve their :attr:`child_prefabs` recursively — without one
        the composite branch falls back to the length of
        ``body_spec['nodes']`` (or ``1`` when no nodes list is present).
        """
        kind = self.body_spec.get("kind")
        if kind in ("point", "circle", "box"):
            return 1
        if kind == "rope":
            return int(self.body_spec.get("segments", 5))
        if kind == "chain":
            return int(self.body_spec.get("links", 5))
        if kind == "ragdoll":
            return 7
        if kind == "composite":
            if self.child_prefabs and library is not None and hasattr(library, "get"):
                total = 0
                resolved_any = False
                for cname in self.child_prefabs:
                    child = library.get(cname)
                    if child is None:
                        continue
                    resolved_any = True
                    total += child.compute_entity_count(library)
                if resolved_any:
                    return total
            nodes = self.body_spec.get("nodes")
            if isinstance(nodes, list) and nodes:
                return len(nodes)
            return 1
        nodes = self.body_spec.get("nodes", [1])
        try:
            return len(nodes)
        except TypeError:
            return 1

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict view suitable for JSON / YAML."""
        return {
            "name": self.name,
            "category": self.category,
            "body_spec": dict(self.body_spec),
            "joint_specs": [dict(j) for j in self.joint_specs],
            "child_prefabs": list(self.child_prefabs),
            "metadata": dict(self.metadata),
        }

    def to_yaml(self) -> str:
        """Serialise as human-readable YAML (round-trips through
        :meth:`from_yaml`)."""
        import yaml  # local — keeps package import cheap when unused

        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Prefab":
        """Construct a :class:`Prefab` from a plain dict."""
        if not isinstance(data, dict):
            raise TypeError(
                f"Prefab.from_dict: data must be a dict; got "
                f"{type(data).__name__}"
            )
        missing = {"name", "category", "body_spec"} - set(data.keys())
        if missing:
            raise ValueError(
                f"Prefab.from_dict: missing required keys "
                f"{sorted(missing)!r}"
            )
        return cls(
            name=str(data["name"]),
            category=str(data["category"]),
            body_spec=dict(data.get("body_spec") or {}),
            joint_specs=[dict(j) for j in (data.get("joint_specs") or [])],
            child_prefabs=[str(c) for c in (data.get("child_prefabs") or [])],
            metadata=dict(data.get("metadata") or {}),
        )

    @classmethod
    def from_yaml(cls, text: str) -> "Prefab":
        """Parse a YAML string produced by :meth:`to_yaml`."""
        if not isinstance(text, str):
            raise TypeError(
                f"Prefab.from_yaml: text must be a str; got "
                f"{type(text).__name__}"
            )
        import yaml

        payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise ValueError(
                f"Prefab.from_yaml: YAML must decode to a dict; got "
                f"{type(payload).__name__}"
            )
        return cls.from_dict(payload)

    # ------------------------------------------------------------------
    # Spawn
    # ------------------------------------------------------------------

    def spawn(
        self,
        world: "World",
        position: tuple[float, float],
        rotation: float = 0.0,
        *,
        library: "Any | None" = None,
    ) -> list["Body"]:
        """Instantiate the prefab into *world*, returning the spawned bodies.

        The primary :attr:`body_spec` is spawned first, positioned at
        *position* (rotated by *rotation* radians when the body kind
        supports it). Any :attr:`joint_specs` are then wired between the
        newly-created nodes. Finally, if a :class:`PrefabLibrary` is
        passed as *library*, each entry of :attr:`child_prefabs` is
        looked up and spawned at the same *position*.

        Returns
        -------
        list[Body]
            Every :class:`~slappyengine.dynamics.body.Body` handle the
            prefab appended to *world*, in creation order.

        Raises
        ------
        TypeError
            If *world* / *position* / *rotation* are the wrong type.
        ValueError
            If *position* is not a 2-sequence of finite floats or
            *rotation* is non-finite.
        """
        px, py = _validate_position(position)
        rot = _validate_rotation(rotation)

        bodies: list["Body"] = []
        primary = _spawn_body_spec(
            world, self.body_spec, (px, py), rot, label=self.name,
        )
        bodies.extend(primary)

        # Wire prefab-level joint specs. Node indices in these dicts are
        # interpreted as *offsets* into the primary body's node slice so
        # the same YAML can spawn the prefab at any world position.
        primary_offset = primary[0].node_offset if primary else 0
        for js in self.joint_specs:
            _wire_joint_dict(world, js, primary_offset)

        # Compose children (best-effort — a missing library or unknown
        # child name is a soft skip rather than a hard failure so half-
        # authored YAML still spawns the primary body).
        if library is not None and self.child_prefabs:
            for cname in self.child_prefabs:
                child = library.get(cname)
                if child is None:
                    continue
                bodies.extend(
                    child.spawn(world, (px, py), rot, library=library)
                )
        return bodies


# ---------------------------------------------------------------------------
# Body-spec dispatch — one entry per kind in :data:`_BODY_KINDS`.
# ---------------------------------------------------------------------------


def _spawn_body_spec(
    world: "World",
    spec: dict[str, Any],
    position: tuple[float, float],
    rotation: float,
    *,
    label: str,
) -> list["Body"]:
    """Materialise *spec* into *world*, returning the created bodies.

    Kinds recognised:

    * ``point``     — one node at *position*.
    * ``circle``    — one node at *position*, ``radius`` / ``bounce``
      recorded on ``Body.parameters``.
    * ``box``       — four corner nodes joined by four edge distance
      joints + two diagonal bracing joints.
    * ``rope``      — passes through
      :func:`slappyengine.dynamics.build_rope` using ``node_count`` /
      ``total_length`` from the spec.
    * ``ragdoll``   — passes through
      :func:`slappyengine.dynamics.build_ragdoll` using the ``bones``
      list from the spec.
    * ``chain``     — a straight chain of ``link_count`` nodes joined
      by ``link_count - 1`` distance constraints.
    * ``composite`` — creates a bare :class:`Body` marker only; the
      prefab's ``child_prefabs`` do the actual work.
    """
    from slappyengine.dynamics import (
        Body,
        JointSpec,
        RagdollSpec,
        RopeSpec,
        build_ragdoll,
        build_rope,
    )
    from slappyengine.dynamics.ragdoll import BoneSpec

    kind = spec["kind"]
    px, py = position

    if kind == "point":
        mass = float(spec.get("mass", 1.0))
        idx = world.add_node((px, py), mass)
        body = Body(
            kind="point",
            parameters={k: v for k, v in spec.items() if k != "kind"},
            node_offset=idx,
            node_count=1,
            label=label,
        )
        world.register_body(body)
        return [body]

    if kind == "circle":
        mass = float(spec.get("mass", 1.0))
        idx = world.add_node((px, py), mass)
        body = Body(
            kind="circle",
            parameters={
                "radius": float(spec.get("radius", 1.0)),
                "bounce": float(spec.get("bounce", 0.5)),
                "mass": mass,
            },
            node_offset=idx,
            node_count=1,
            label=label,
        )
        world.register_body(body)
        return [body]

    if kind == "box":
        half_w = float(spec.get("width", 1.0)) * 0.5
        half_h = float(spec.get("height", 1.0)) * 0.5
        mass = float(spec.get("mass", 1.0)) * 0.25  # per corner
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
        edge = float(spec.get("edge_stiffness", 1.0e6))
        diag = float(spec.get("diag_stiffness", 5.0e5))
        # 4 perimeter edges.
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
        # 2 diagonal braces.
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
                "width": float(spec.get("width", 1.0)),
                "height": float(spec.get("height", 1.0)),
                "mass": float(spec.get("mass", 1.0)),
            },
            node_offset=offset,
            node_count=4,
            label=label,
        )
        world.register_body(body)
        return [body]

    if kind == "rope":
        node_count = int(spec.get("node_count", 5))
        total_length = float(spec.get("total_length", 4.0))
        mass_per_node = float(spec.get("mass_per_node", 0.1))
        stiffness = float(spec.get("stiffness", 1.0e6))
        damping = float(spec.get("damping", 0.05))
        rope_spec = RopeSpec(
            node_count=node_count,
            total_length=total_length,
            mass_per_node=mass_per_node,
            stiffness=stiffness,
            damping=damping,
            anchor_a_pinned=bool(spec.get("anchor_a_pinned", True)),
            anchor_b_pinned=bool(spec.get("anchor_b_pinned", False)),
        )
        # Endpoints follow rotation so an angled rope spawns cleanly.
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        anchor_a = (px, py)
        end_off = (total_length, 0.0)
        anchor_b = (
            px + cos_r * end_off[0] - sin_r * end_off[1],
            py + sin_r * end_off[0] + cos_r * end_off[1],
        )
        body = build_rope(rope_spec, world, anchor_a, anchor_b)
        body.label = label
        return [body]

    if kind == "ragdoll":
        raw_bones = spec.get("bones") or []
        bones: list[BoneSpec] = []
        for b in raw_bones:
            bones.append(
                BoneSpec(
                    parent_idx=int(b.get("parent_idx", -1)),
                    length=float(b.get("length", 1.0)),
                    mass=float(b.get("mass", 1.0)),
                    angle_limit=tuple(
                        b.get("angle_limit", (-math.pi, math.pi))
                    ),
                    direction=tuple(b.get("direction", (0.0, -1.0))),
                    label=str(b.get("label", "")),
                )
            )
        if not bones:
            bones = [
                BoneSpec(parent_idx=-1, length=1.0, mass=1.0),
            ]
        ragdoll_spec = RagdollSpec(
            bones=bones,
            stiffness=float(spec.get("stiffness", 5.0e6)),
            damping=float(spec.get("damping", 0.05)),
        )
        body = build_ragdoll(
            ragdoll_spec, world, (px, py),
            pin_root=bool(spec.get("pin_root", False)),
        )
        body.label = label
        return [body]

    if kind == "chain":
        link_count = int(spec.get("link_count", 5))
        link_length = float(spec.get("link_length", 1.0))
        mass = float(spec.get("mass_per_link", 0.5))
        stiffness = float(spec.get("stiffness", 1.0e7))
        damping = float(spec.get("damping", 0.02))
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        offset = None
        for i in range(link_count):
            dx = link_length * i
            dy = 0.0
            wx = px + cos_r * dx - sin_r * dy
            wy = py + sin_r * dx + cos_r * dy
            m = 0.0 if (i == 0 and bool(spec.get("pin_first", True))) else mass
            idx = world.add_node((wx, wy), m)
            if offset is None:
                offset = idx
        assert offset is not None
        for i in range(link_count - 1):
            world.add_joint(
                JointSpec(
                    kind="distance",
                    node_a=offset + i,
                    node_b=offset + i + 1,
                    rest_length=link_length,
                    stiffness=stiffness,
                    damping=damping,
                )
            )
        body = Body(
            kind="chain",
            parameters={
                "link_count": link_count,
                "link_length": link_length,
            },
            node_offset=offset,
            node_count=link_count,
            label=label,
        )
        world.register_body(body)
        return [body]

    if kind == "composite":
        # Composite: authoring code may supply a ``nodes`` list of
        # ``(offset_x, offset_y, mass)`` tuples so a single prefab can
        # place multiple nodes at once (windmill hub + 4 arm tips, for
        # example). When absent, a single placeholder marker is spawned
        # and the prefab's ``child_prefabs`` do the rest.
        cos_r = math.cos(rotation)
        sin_r = math.sin(rotation)
        raw_nodes = spec.get("nodes")
        if raw_nodes:
            offset = None
            for n in raw_nodes:
                nx = float(n[0])
                ny = float(n[1])
                nmass = float(n[2]) if len(n) > 2 else 1.0
                wx = px + cos_r * nx - sin_r * ny
                wy = py + sin_r * nx + cos_r * ny
                idx = world.add_node((wx, wy), nmass)
                if offset is None:
                    offset = idx
            assert offset is not None
            body = Body(
                kind="composite",
                parameters={
                    k: v for k, v in spec.items()
                    if k not in ("kind", "nodes")
                },
                node_offset=offset,
                node_count=len(raw_nodes),
                label=label,
            )
            world.register_body(body)
            return [body]
        idx = world.add_node((px, py), float(spec.get("mass", 0.0)))
        body = Body(
            kind="composite",
            parameters={k: v for k, v in spec.items() if k != "kind"},
            node_offset=idx,
            node_count=1,
            label=label,
        )
        world.register_body(body)
        return [body]

    raise ValueError(f"_spawn_body_spec: unknown kind {kind!r}")


def _wire_joint_dict(
    world: "World",
    spec: dict[str, Any],
    primary_offset: int,
) -> None:
    """Instantiate a joint from *spec* and add it to *world*.

    ``node_a`` / ``node_b`` are treated as offsets into the primary
    body's node slice — the concrete world indices are recovered by
    adding *primary_offset*.
    """
    from slappyengine.dynamics import JointSpec

    kind = str(spec.get("kind", "distance"))
    joint = JointSpec(
        kind=kind,
        node_a=int(spec["node_a"]) + primary_offset,
        node_b=int(spec["node_b"]) + primary_offset,
        rest_length=float(spec.get("rest_length", 0.0)),
        stiffness=float(spec.get("stiffness", 1.0e6)),
        damping=float(spec.get("damping", 0.02)),
        params=dict(spec.get("params") or {}),
    )
    world.add_joint(joint)


def _validate_position(position: Any) -> tuple[float, float]:
    if not hasattr(position, "__len__") or len(position) != 2:
        raise TypeError(
            f"Prefab.spawn: position must be a 2-sequence; "
            f"got {position!r}"
        )
    try:
        x = float(position[0])
        y = float(position[1])
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Prefab.spawn: position entries must be floats; "
            f"got {position!r}"
        ) from exc
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError(
            f"Prefab.spawn: position entries must be finite; "
            f"got {position!r}"
        )
    return x, y


def _validate_rotation(rotation: Any) -> float:
    try:
        r = float(rotation)
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Prefab.spawn: rotation must be float-coercible; "
            f"got {rotation!r}"
        ) from exc
    if not math.isfinite(r):
        raise ValueError(
            f"Prefab.spawn: rotation must be finite; got {rotation!r}"
        )
    return r


__all__ = ["CATEGORIES", "Prefab"]
