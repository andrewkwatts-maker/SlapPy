"""YAML-driven scene loader for :class:`PhysicsWorld`.

Lets games describe a physics scene declaratively:

.. code-block:: yaml

    world:
      gravity: [0.0, 196.0]
      bounds: [-200, -100, 200, 250]
    bodies:
      - name: ground
        material: stone
        shape: rect
        width: 240
        height: 16
        position: [0, 180]
        fixed: true
      - name: ball
        material: steel
        shape: circle
        diameter: 24
        position: [0, 0]
        velocity: [0, 0]

The loader is intentionally narrow: it parses YAML into ``SceneSpec`` and
``SceneBodySpec`` dataclasses, then instantiates a :class:`PhysicsWorld`,
overrides ``world.gravity`` and the world bounds, and creates each body
via :meth:`PhysicsWorld.create_body`.  Names declared in the YAML are
stashed in a ``body_by_name`` dict on the world so callers can look them
up after the build.

Custom silhouettes
------------------
``shape: custom_silhouette`` reads a PNG via Pillow and uses its alpha
channel as the silhouette mask.  This allows non-circle / non-rect
bodies (e.g. artist-authored chunks) to be authored from the YAML.

Errors
------
- Unknown ``material`` -> ``ValueError`` naming the offending material.
- Unknown ``shape`` -> ``ValueError`` listing valid shapes.
- ``custom_silhouette`` without ``silhouette_path`` -> ``ValueError``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import yaml

from slappyengine._compat import cell_material_for
from slappyengine.physics.body import (
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.hull import TIER_T0, TIER_T1, TIER_T2
from slappyengine.physics.world import PhysicsWorld, load_physics_config

if TYPE_CHECKING:
    pass


_TIER_LOOKUP = {
    "T0": TIER_T0,
    "T1": TIER_T1,
    "T2": TIER_T2,
}

_VALID_SHAPES = ("circle", "rect", "custom_silhouette")


@dataclass
class SceneBodySpec:
    """Declarative description of one body in a YAML scene."""
    name: str
    material: str
    shape: str  # "circle" | "rect" | "custom_silhouette"
    width: int = 0
    height: int = 0
    diameter: int = 0
    silhouette_path: str | None = None
    position: tuple[float, float] = (0.0, 0.0)
    velocity: tuple[float, float] = (0.0, 0.0)
    angle: float = 0.0
    fixed: bool = False
    tier: str = "T2"


@dataclass
class SceneSpec:
    """Top-level scene description."""
    world: dict = field(default_factory=dict)
    bodies: list[SceneBodySpec] = field(default_factory=list)


# -- parsing -----------------------------------------------------------------

def _coerce_pair(v, default: tuple[float, float]) -> tuple[float, float]:
    if v is None:
        return default
    if not (isinstance(v, (list, tuple)) and len(v) == 2):
        raise ValueError(f"Expected a [x, y] pair, got {v!r}")
    return (float(v[0]), float(v[1]))


def _coerce_bounds(v) -> tuple[float, float, float, float] | None:
    if v is None:
        return None
    if not (isinstance(v, (list, tuple)) and len(v) == 4):
        raise ValueError(f"world.bounds must be [x0, y0, x1, y1], got {v!r}")
    return (float(v[0]), float(v[1]), float(v[2]), float(v[3]))


def _parse_body(raw: dict) -> SceneBodySpec:
    if not isinstance(raw, dict):
        raise ValueError(f"Body entry must be a mapping, got {raw!r}")
    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError(f"Body is missing a string 'name': {raw!r}")
    material = raw.get("material")
    if not isinstance(material, str) or not material:
        raise ValueError(f"Body '{name}' is missing a 'material' string")
    shape = raw.get("shape")
    if shape not in _VALID_SHAPES:
        raise ValueError(
            f"Body '{name}' has invalid shape {shape!r}; "
            f"valid shapes: {_VALID_SHAPES}"
        )

    tier = str(raw.get("tier", "T2"))
    if tier not in _TIER_LOOKUP:
        raise ValueError(
            f"Body '{name}' has invalid tier {tier!r}; "
            f"valid tiers: {sorted(_TIER_LOOKUP.keys())}"
        )

    return SceneBodySpec(
        name=name,
        material=material,
        shape=shape,
        width=int(raw.get("width", 0)),
        height=int(raw.get("height", 0)),
        diameter=int(raw.get("diameter", 0)),
        silhouette_path=raw.get("silhouette_path"),
        position=_coerce_pair(raw.get("position"), (0.0, 0.0)),
        velocity=_coerce_pair(raw.get("velocity"), (0.0, 0.0)),
        angle=float(raw.get("angle", 0.0)),
        fixed=bool(raw.get("fixed", False)),
        tier=tier,
    )


def load_scene_spec(path: str | Path) -> SceneSpec:
    """Parse a YAML scene file into a :class:`SceneSpec`."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Scene YAML not found: {p}")
    with open(p, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"Scene YAML root must be a mapping, got {type(raw).__name__}")

    world_raw = raw.get("world", {}) or {}
    if not isinstance(world_raw, dict):
        raise ValueError(f"'world' must be a mapping, got {type(world_raw).__name__}")

    bodies_raw = raw.get("bodies", []) or []
    if not isinstance(bodies_raw, list):
        raise ValueError(f"'bodies' must be a list, got {type(bodies_raw).__name__}")

    bodies = [_parse_body(b) for b in bodies_raw]
    return SceneSpec(world=dict(world_raw), bodies=bodies)


# -- building ----------------------------------------------------------------

def _load_silhouette_png(path: str | Path) -> np.ndarray:
    """Load a PNG and return its alpha channel as a float32 (h, w) array."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - hard dep in this engine
        raise ImportError(
            "custom_silhouette shapes require Pillow; install slappy-engine "
            "with image support."
        ) from exc
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"silhouette_path not found: {p}")
    img = Image.open(p).convert("RGBA")
    arr = np.asarray(img, dtype=np.float32)
    # Alpha channel, normalised to [0, 1].
    alpha = arr[..., 3] / 255.0
    return alpha.astype(np.float32)


def _silhouette_for(body: SceneBodySpec) -> np.ndarray:
    if body.shape == "circle":
        if body.diameter <= 0:
            raise ValueError(
                f"Body '{body.name}' shape=circle requires diameter > 0"
            )
        return make_circle_silhouette(body.diameter)
    if body.shape == "rect":
        if body.width <= 0 or body.height <= 0:
            raise ValueError(
                f"Body '{body.name}' shape=rect requires width and height > 0"
            )
        return make_rect_silhouette(body.width, body.height)
    if body.shape == "custom_silhouette":
        if not body.silhouette_path:
            raise ValueError(
                f"Body '{body.name}' shape=custom_silhouette requires "
                f"'silhouette_path'"
            )
        return _load_silhouette_png(body.silhouette_path)
    # Shape was validated at parse-time; defensive only.
    raise ValueError(f"Body '{body.name}' has unsupported shape {body.shape!r}")


def build_world_from_scene(scene: SceneSpec) -> PhysicsWorld:
    """Instantiate a :class:`PhysicsWorld` populated from *scene*.

    World-level overrides
    ---------------------
    - ``world.gravity`` overrides ``PhysicsYaml.world.gravity``.
    - ``world.bounds`` becomes the world's ``world_bounds`` rectangle.

    Returns the populated world.  A ``body_by_name`` attribute is attached
    to the world (and bound as a method too) for convenient lookup.
    """
    config = load_physics_config()
    world_raw = scene.world or {}

    if "gravity" in world_raw:
        gx, gy = _coerce_pair(world_raw["gravity"], config.world.gravity)
        config.world = type(config.world)(
            default_dt=config.world.default_dt,
            substeps=config.world.substeps,
            gravity=(gx, gy),
        )

    bounds = _coerce_bounds(world_raw.get("bounds"))

    world = PhysicsWorld(config=config, world_bounds=bounds)

    # Pre-validate materials so we get a clear error before any partial build.
    for body in scene.bodies:
        if cell_material_for(body.material) is None:
            raise ValueError(
                f"Unknown material '{body.material}' on body '{body.name}'. "
                f"Check spelling or register the material before loading."
            )

    name_map: dict[str, object] = {}
    for body in scene.bodies:
        silhouette = _silhouette_for(body)
        pb = world.create_body(
            silhouette=silhouette,
            material=body.material,
            position=body.position,
            velocity=body.velocity,
            fixed=body.fixed,
            tier=_TIER_LOOKUP[body.tier],
        )
        # Apply angle if provided.
        if body.angle != 0.0:
            world.hulls.angle[pb.root_hull_id] = float(body.angle)
            world.hulls.mark_dirty()
        if body.name in name_map:
            raise ValueError(
                f"Duplicate body name '{body.name}' in scene"
            )
        name_map[body.name] = pb

    # Stash and expose lookup helper on the world.
    world.body_by_name_map = name_map  # type: ignore[attr-defined]

    def _body_by_name(name: str):
        try:
            return name_map[name]
        except KeyError:
            raise KeyError(
                f"No body named {name!r} in scene; "
                f"known names: {sorted(name_map.keys())}"
            )

    world.body_by_name = _body_by_name  # type: ignore[attr-defined]
    return world


def load_and_build(path: str | Path) -> PhysicsWorld:
    """Convenience: :func:`load_scene_spec` + :func:`build_world_from_scene`."""
    return build_world_from_scene(load_scene_spec(path))


__all__ = [
    "SceneBodySpec",
    "SceneSpec",
    "build_world_from_scene",
    "load_and_build",
    "load_scene_spec",
]
