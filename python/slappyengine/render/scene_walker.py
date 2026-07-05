"""SceneWalker — traverse an FF3 :class:`~slappyengine.scenes.scene.Scene`
and emit per-entity draw calls through the HH4 :class:`Renderer`.

Closes HH3 rendering gap #2 (JJ5, Nova3D parity Sprint 5).

Design
------
* ``SceneWalker`` sits above HH4 and never mutates the scene / renderer /
  camera / mesh / material modules — it purely *reads* an FF3 scene, turns
  each entity into an :class:`EntityDrawInfo`, then submits it through the
  renderer's already-existing ``submit_mesh`` surface.
* Frustum culling is a straight 6-plane test extracted from
  ``view_projection`` — no dependencies on wgpu / any GPU path.
* Asset loads route through :mod:`slappyengine.asset_import` when a
  ``params["mesh_path"]`` is present; results are memoised in
  :class:`AssetCache` so the walker never re-hits disk mid-frame.
* Prefab resolution soft-imports :class:`slappyengine.prefabs.PrefabLibrary`
  — the walker keeps working in stripped-down builds where prefabs are not
  available.

The walker is deliberately Python-only. Hot loops still land in the HH4
renderer / Rust kernels — this file is glue.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np

from .camera import Camera2D, Camera3D
from .material import Material
from .mesh import Mesh, cube

if TYPE_CHECKING:  # pragma: no cover
    from slappyengine.scenes.scene import Scene
    from .light import Light

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-entity draw info
# ---------------------------------------------------------------------------


@dataclass
class EntityDrawInfo:
    """Resolved draw information for a single scene entity.

    Attributes
    ----------
    entity_id
        FF3 entity id — echoed for correlation with the source scene.
    mesh
        The mesh handle to submit, or ``None`` when the entity has no
        renderable geometry (e.g. a point-mass with no visual override).
    material
        Material to bind for this draw. Falls back to a
        ``Material()`` default when the scene did not name one.
    transform_matrix
        4x4 model matrix in T @ R @ S order — ready for
        :meth:`Renderer.submit_mesh`.
    visible
        ``False`` when the entity is culled or marked invisible; the
        walker respects this and skips its ``submit_mesh`` call.
    bounding_box
        World-space AABB used by the frustum culler.
    """

    entity_id: str
    mesh: Mesh | None
    material: Material
    transform_matrix: np.ndarray
    visible: bool = True
    bounding_box: tuple[tuple[float, float, float], tuple[float, float, float]] = (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    )


# ---------------------------------------------------------------------------
# Frustum
# ---------------------------------------------------------------------------


@dataclass
class Frustum:
    """Six-plane view frustum extracted from a view+proj matrix.

    Each plane is stored as ``(nx, ny, nz, d)`` so
    ``dot(n, p) + d`` is the signed distance from ``p`` to the plane
    (positive → inside the frustum).
    """

    planes: np.ndarray  # (6, 4) float32

    # ------------------------------------------------------------------
    @classmethod
    def from_camera(cls, camera: Any) -> "Frustum":
        """Extract 6 planes from *camera*'s view_projection matrix.

        Accepts :class:`Camera3D`, :class:`Camera2D`, or any object that
        exposes a ``view_projection() -> 4x4 ndarray`` method. A plain
        4x4 ndarray also works (bypasses the camera abstraction for
        unit tests).
        """
        if isinstance(camera, np.ndarray):
            vp = np.asarray(camera, dtype=np.float64)
        elif hasattr(camera, "view_projection"):
            vp = np.asarray(camera.view_projection(), dtype=np.float64)
        else:
            raise TypeError(
                "Frustum.from_camera: camera must expose view_projection() "
                f"or be a 4x4 ndarray; got {type(camera).__name__}"
            )
        if vp.shape != (4, 4):
            raise ValueError(
                f"Frustum.from_camera: view_projection must be 4x4; got {vp.shape}"
            )
        # Standard Gribb-Hartmann plane extraction (row-form) from a
        # column-vector matrix M @ v. Planes point *inward*.
        m = vp
        planes = np.zeros((6, 4), dtype=np.float64)
        # Left / right
        planes[0] = m[3] + m[0]
        planes[1] = m[3] - m[0]
        # Bottom / top
        planes[2] = m[3] + m[1]
        planes[3] = m[3] - m[1]
        # Near / far (WebGPU-style clip: z ∈ [0, 1]).
        planes[4] = m[3] + m[2]
        planes[5] = m[3] - m[2]
        # Normalise so the ``d`` term is a real world-space distance.
        for i in range(6):
            n = float(np.linalg.norm(planes[i, :3]))
            if n > 1e-12:
                planes[i] /= n
        return cls(planes=planes.astype(np.float32))

    # ------------------------------------------------------------------
    def intersects_aabb(
        self,
        aabb: tuple[tuple[float, float, float], tuple[float, float, float]],
    ) -> bool:
        """True iff the axis-aligned bounding box lies at least partly
        inside every plane of the frustum.

        Uses the standard "p-vertex" test: for each plane, project the
        AABB's most-positive-along-the-normal corner and cull if it
        still lies behind the plane.
        """
        (mn_x, mn_y, mn_z), (mx_x, mx_y, mx_z) = aabb
        for plane in self.planes:
            nx, ny, nz, d = float(plane[0]), float(plane[1]), float(plane[2]), float(plane[3])
            # Positive-vertex: max coord where normal is positive, min otherwise.
            px = mx_x if nx >= 0.0 else mn_x
            py = mx_y if ny >= 0.0 else mn_y
            pz = mx_z if nz >= 0.0 else mn_z
            if nx * px + ny * py + nz * pz + d < 0.0:
                return False
        return True


# ---------------------------------------------------------------------------
# Asset cache
# ---------------------------------------------------------------------------


@dataclass
class _CacheEntry:
    mesh: Mesh | None
    inserted_at: float
    ttl_seconds: float


class AssetCache:
    """Small path → :class:`Mesh` LRU with time-to-live entries.

    The cache is intentionally trivial — SceneWalker holds a per-instance
    cache and passes it to every ``resolve_entity`` call, so repeated
    entities that reference the same ``mesh_path`` never re-import.

    ``default_ttl_seconds`` is deliberately generous (10 min) so a full
    game session can re-use uploaded meshes; callers may override on
    construction or bypass the cache with :meth:`invalidate`.
    """

    def __init__(self, *, default_ttl_seconds: float = 600.0) -> None:
        if not isinstance(default_ttl_seconds, (int, float)):
            raise TypeError(
                f"AssetCache: default_ttl_seconds must be numeric; "
                f"got {type(default_ttl_seconds).__name__}"
            )
        if default_ttl_seconds <= 0:
            raise ValueError(
                f"AssetCache: default_ttl_seconds must be > 0; "
                f"got {default_ttl_seconds}"
            )
        self._default_ttl = float(default_ttl_seconds)
        self._entries: dict[str, _CacheEntry] = {}
        self._hits = 0
        self._misses = 0

    # ------------------------------------------------------------------
    def get(self, path: str, *, now: float | None = None) -> Mesh | None:
        """Return the cached mesh for *path*, or ``None`` on miss / expiry."""
        if not isinstance(path, str) or not path:
            self._misses += 1
            return None
        entry = self._entries.get(path)
        if entry is None:
            self._misses += 1
            return None
        current = time.monotonic() if now is None else now
        if current - entry.inserted_at > entry.ttl_seconds:
            del self._entries[path]
            self._misses += 1
            return None
        self._hits += 1
        return entry.mesh

    # ------------------------------------------------------------------
    def put(
        self,
        path: str,
        mesh: Mesh | None,
        *,
        ttl_seconds: float | None = None,
        now: float | None = None,
    ) -> None:
        """Store *mesh* under *path* with a per-entry TTL."""
        if not isinstance(path, str) or not path:
            return
        ttl = self._default_ttl if ttl_seconds is None else float(ttl_seconds)
        if ttl <= 0:
            return
        current = time.monotonic() if now is None else now
        self._entries[path] = _CacheEntry(
            mesh=mesh, inserted_at=current, ttl_seconds=ttl,
        )

    # ------------------------------------------------------------------
    def invalidate(self, path: str | None = None) -> None:
        """Drop one entry (``path`` given) or every entry (``path`` None)."""
        if path is None:
            self._entries.clear()
            return
        self._entries.pop(path, None)

    # ------------------------------------------------------------------
    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    def __len__(self) -> int:
        return len(self._entries)


# ---------------------------------------------------------------------------
# Render stats
# ---------------------------------------------------------------------------


@dataclass
class RenderStats:
    """Per-walk metrics — populated by :meth:`SceneWalker.walk`."""

    entities_walked: int = 0
    entities_culled: int = 0
    draw_calls: int = 0
    wall_ms: float = 0.0


# ---------------------------------------------------------------------------
# Helpers — transform / bounding box composition
# ---------------------------------------------------------------------------


def _euler_to_quat(euler: tuple[float, float, float]) -> tuple[float, float, float, float]:
    """XYZ intrinsic Euler → quaternion (x, y, z, w)."""
    ex, ey, ez = (float(v) for v in euler)
    cx, sx = math.cos(ex * 0.5), math.sin(ex * 0.5)
    cy, sy = math.cos(ey * 0.5), math.sin(ey * 0.5)
    cz, sz = math.cos(ez * 0.5), math.sin(ez * 0.5)
    qx = sx * cy * cz + cx * sy * sz
    qy = cx * sy * cz - sx * cy * sz
    qz = cx * cy * sz + sx * sy * cz
    qw = cx * cy * cz - sx * sy * sz
    return (qx, qy, qz, qw)


def _quat_to_matrix(q: tuple[float, float, float, float]) -> np.ndarray:
    """(x, y, z, w) quaternion → 3x3 rotation matrix."""
    qx, qy, qz, qw = (float(v) for v in q)
    n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
    qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
    xx, yy, zz = qx * qx, qy * qy, qz * qz
    xy, xz, yz = qx * qy, qx * qz, qy * qz
    wx, wy, wz = qw * qx, qw * qy, qw * qz
    return np.array(
        [
            [1 - 2 * (yy + zz), 2 * (xy - wz), 2 * (xz + wy)],
            [2 * (xy + wz), 1 - 2 * (xx + zz), 2 * (yz - wx)],
            [2 * (xz - wy), 2 * (yz + wx), 1 - 2 * (xx + yy)],
        ],
        dtype=np.float32,
    )


def _compose_trs(
    position: tuple[float, float, float],
    rotation: tuple[float, float, float, float],
    scale: tuple[float, float, float],
) -> np.ndarray:
    """Compose T · R · S into a 4x4 float32 matrix."""
    r = _quat_to_matrix(rotation)
    sx, sy, sz = (float(v) for v in scale)
    m = np.eye(4, dtype=np.float32)
    m[0, :3] = r[0] * np.array([sx, sy, sz], dtype=np.float32)
    m[1, :3] = r[1] * np.array([sx, sy, sz], dtype=np.float32)
    m[2, :3] = r[2] * np.array([sx, sy, sz], dtype=np.float32)
    m[0, 3] = float(position[0])
    m[1, 3] = float(position[1])
    m[2, 3] = float(position[2])
    return m


def _normalise_position(
    position: Any,
) -> tuple[float, float, float]:
    """Coerce a scene ``position`` (2- or 3-sequence) into a 3-tuple."""
    if position is None:
        return (0.0, 0.0, 0.0)
    if hasattr(position, "__len__"):
        if len(position) == 2:
            return (float(position[0]), float(position[1]), 0.0)
        if len(position) == 3:
            return (float(position[0]), float(position[1]), float(position[2]))
    raise ValueError(
        f"SceneWalker: entity position must be a 2- or 3-sequence; got {position!r}"
    )


def _normalise_rotation(
    rotation: Any,
) -> tuple[float, float, float, float]:
    """Coerce a scene ``rotation`` param to a quaternion (x, y, z, w).

    Supported inputs:
      * ``None`` → identity.
      * scalar (2D radians) → z-axis rotation quaternion.
      * 3-sequence (Euler radians) → XYZ intrinsic quaternion.
      * 4-sequence → quaternion, taken as-is (x, y, z, w).
    """
    if rotation is None:
        return (0.0, 0.0, 0.0, 1.0)
    if isinstance(rotation, (int, float)):
        theta = float(rotation) * 0.5
        return (0.0, 0.0, math.sin(theta), math.cos(theta))
    if hasattr(rotation, "__len__"):
        if len(rotation) == 3:
            return _euler_to_quat((rotation[0], rotation[1], rotation[2]))
        if len(rotation) == 4:
            return (
                float(rotation[0]), float(rotation[1]),
                float(rotation[2]), float(rotation[3]),
            )
    raise ValueError(
        f"SceneWalker: entity rotation must be scalar / 3-seq / 4-seq; "
        f"got {rotation!r}"
    )


def _normalise_scale(scale: Any) -> tuple[float, float, float]:
    """Coerce a scene ``scale`` param to a 3-tuple.

    Supports scalar (uniform scale) or 3-sequence (per-axis).
    """
    if scale is None:
        return (1.0, 1.0, 1.0)
    if isinstance(scale, (int, float)):
        s = float(scale)
        return (s, s, s)
    if hasattr(scale, "__len__"):
        if len(scale) == 3:
            return (float(scale[0]), float(scale[1]), float(scale[2]))
        if len(scale) == 2:
            return (float(scale[0]), float(scale[1]), 1.0)
    raise ValueError(
        f"SceneWalker: entity scale must be scalar / 3-seq; got {scale!r}"
    )


def _mesh_aabb(mesh: Mesh | None) -> tuple[
    tuple[float, float, float], tuple[float, float, float]
]:
    if mesh is None or mesh.vertices.size == 0:
        return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    return (
        tuple(float(x) for x in mesh.vertices.min(axis=0)),
        tuple(float(x) for x in mesh.vertices.max(axis=0)),
    )


def _transform_aabb(
    local: tuple[tuple[float, float, float], tuple[float, float, float]],
    matrix: np.ndarray,
) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
    """Return the AABB of *local* after applying the 4x4 *matrix*."""
    (mn_x, mn_y, mn_z), (mx_x, mx_y, mx_z) = local
    # If the local box is degenerate (empty mesh) shortcut to the origin.
    if mn_x == mx_x and mn_y == mx_y and mn_z == mx_z and mn_x == 0.0:
        px, py, pz = float(matrix[0, 3]), float(matrix[1, 3]), float(matrix[2, 3])
        return ((px, py, pz), (px, py, pz))
    corners = np.array(
        [
            [mn_x, mn_y, mn_z, 1.0],
            [mx_x, mn_y, mn_z, 1.0],
            [mn_x, mx_y, mn_z, 1.0],
            [mx_x, mx_y, mn_z, 1.0],
            [mn_x, mn_y, mx_z, 1.0],
            [mx_x, mn_y, mx_z, 1.0],
            [mn_x, mx_y, mx_z, 1.0],
            [mx_x, mx_y, mx_z, 1.0],
        ],
        dtype=np.float32,
    )
    world = corners @ np.asarray(matrix, dtype=np.float32).T
    world_xyz = world[:, :3]
    mn = world_xyz.min(axis=0)
    mx = world_xyz.max(axis=0)
    return (
        (float(mn[0]), float(mn[1]), float(mn[2])),
        (float(mx[0]), float(mx[1]), float(mx[2])),
    )


# ---------------------------------------------------------------------------
# Material registry (very small)
# ---------------------------------------------------------------------------


_DEFAULT_MATERIAL = Material()


class _MaterialRegistry:
    """Optional material lookup used by the walker."""

    def __init__(self) -> None:
        self._entries: dict[str, Material] = {}

    def register(self, material_id: str, material: Material) -> None:
        if not isinstance(material_id, str) or not material_id:
            raise ValueError("_MaterialRegistry.register: id must be non-empty str")
        if not isinstance(material, Material):
            raise TypeError(
                "_MaterialRegistry.register: material must be a Material"
            )
        self._entries[material_id] = material

    def get(self, material_id: str | None) -> Material:
        if material_id is None or material_id == "":
            return _DEFAULT_MATERIAL
        return self._entries.get(material_id, _DEFAULT_MATERIAL)


# ---------------------------------------------------------------------------
# SceneWalker
# ---------------------------------------------------------------------------


class SceneWalker:
    """Walk an FF3 :class:`Scene` and emit HH4 draw calls.

    Parameters
    ----------
    scene
        The read-only :class:`~slappyengine.scenes.scene.Scene` to walk.
        The walker never mutates the scene.
    prefab_library
        Optional :class:`slappyengine.prefabs.PrefabLibrary`. When
        provided, entities with a ``prefab_ref`` are resolved through it
        so authored prefabs pick up their default meshes / materials.
    asset_cache
        Optional :class:`AssetCache`. When ``None`` the walker creates a
        private cache — pass in a shared instance to reuse imports
        across walks.
    material_registry
        Optional mapping from ``params["material_id"]`` → :class:`Material`.
        When ``None`` every entity picks up the default material unless
        it inlines a full ``material`` dict.
    default_mesh
        Fallback :class:`Mesh` for entities that neither reference a
        prefab nor supply a ``mesh_path``. Defaults to a unit cube so a
        blank scene still shows up in the viewer.
    """

    def __init__(
        self,
        scene: "Scene",
        *,
        prefab_library: Any | None = None,
        asset_cache: AssetCache | None = None,
        material_registry: _MaterialRegistry | None = None,
        default_mesh: Mesh | None = None,
    ) -> None:
        if scene is None:
            raise TypeError("SceneWalker: scene must not be None")
        if not hasattr(scene, "entities"):
            raise TypeError(
                f"SceneWalker: scene must expose an ``entities`` list; "
                f"got {type(scene).__name__}"
            )
        self.scene = scene
        self.prefab_library = prefab_library
        self.asset_cache = asset_cache if asset_cache is not None else AssetCache()
        self.material_registry = (
            material_registry if material_registry is not None else _MaterialRegistry()
        )
        self._default_mesh = default_mesh if default_mesh is not None else cube(1.0)

    # ------------------------------------------------------------------
    def register_material(self, material_id: str, material: Material) -> None:
        """Register a :class:`Material` under *material_id* for lookup."""
        self.material_registry.register(material_id, material)

    # ------------------------------------------------------------------
    # Entity resolution
    # ------------------------------------------------------------------

    def resolve_entity(self, entity: dict[str, Any]) -> EntityDrawInfo | None:
        """Turn one entity dict into an :class:`EntityDrawInfo`.

        Returns ``None`` when the entity cannot be resolved (missing
        prefab, malformed dict) — callers may use this to decide
        whether to warn or fall back.
        """
        if not isinstance(entity, dict):
            _LOG.warning(
                "SceneWalker.resolve_entity: entity is not a dict "
                "(got %s); skipping", type(entity).__name__,
            )
            return None
        entity_id = str(entity.get("id") or "")
        if not entity_id:
            _LOG.warning(
                "SceneWalker.resolve_entity: entity missing 'id'; skipping",
            )
            return None
        params = entity.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        try:
            position = _normalise_position(entity.get("position"))
            rotation = _normalise_rotation(params.get("rotation"))
            scale = _normalise_scale(params.get("scale"))
        except (TypeError, ValueError) as exc:
            _LOG.warning(
                "SceneWalker.resolve_entity: %s could not compose transform "
                "(%s); skipping", entity_id, exc,
            )
            return None

        matrix = _compose_trs(position, rotation, scale)

        # ---- Mesh resolution ------------------------------------------------
        mesh: Mesh | None = None
        prefab_ref = entity.get("prefab_ref")
        kind = entity.get("kind")

        if prefab_ref:
            mesh = self._resolve_prefab_mesh(prefab_ref, entity_id)
            if mesh is None:
                # Prefab not found — the caller wants us to skip.
                return None
        elif kind == "mesh_ref" and params.get("mesh_path"):
            mesh = self._resolve_mesh_from_path(str(params["mesh_path"]))
        elif isinstance(params.get("mesh"), Mesh):
            mesh = params["mesh"]
        else:
            mesh = self._default_mesh

        # ---- Material -------------------------------------------------------
        material_id = params.get("material_id")
        if isinstance(params.get("material"), Material):
            material = params["material"]
        else:
            material = self.material_registry.get(
                material_id if isinstance(material_id, str) else None,
            )

        # ---- Visibility -----------------------------------------------------
        visible = bool(params.get("visible", True))

        # ---- Bounding box ---------------------------------------------------
        local_aabb = _mesh_aabb(mesh)
        world_aabb = _transform_aabb(local_aabb, matrix)

        return EntityDrawInfo(
            entity_id=entity_id,
            mesh=mesh,
            material=material,
            transform_matrix=matrix,
            visible=visible,
            bounding_box=world_aabb,
        )

    # ------------------------------------------------------------------
    def _resolve_prefab_mesh(
        self, prefab_ref: str, entity_id: str,
    ) -> Mesh | None:
        """Extract a mesh from a prefab lookup.

        Prefabs currently describe dynamics bodies, not meshes, so we
        fall back to the default mesh when the prefab exists but does
        not carry a ``mesh`` attribute. Missing prefab → warn + skip.
        """
        if self.prefab_library is None:
            _LOG.warning(
                "SceneWalker: entity %s references prefab %r but no "
                "prefab_library supplied; skipping",
                entity_id, prefab_ref,
            )
            return None
        try:
            prefab = self.prefab_library.get(prefab_ref)
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning(
                "SceneWalker: prefab_library.get(%r) failed (%s); skipping "
                "entity %s", prefab_ref, exc, entity_id,
            )
            return None
        if prefab is None:
            _LOG.warning(
                "SceneWalker: entity %s references unknown prefab %r; "
                "skipping", entity_id, prefab_ref,
            )
            return None
        candidate = getattr(prefab, "mesh", None)
        if isinstance(candidate, Mesh):
            return candidate
        # Prefab doesn't carry a mesh — fall back to the default.
        return self._default_mesh

    # ------------------------------------------------------------------
    def _resolve_mesh_from_path(self, mesh_path: str) -> Mesh | None:
        """Load a mesh via asset_import + cache, or return ``None``."""
        cached = self.asset_cache.get(mesh_path)
        if cached is not None:
            return cached
        try:
            from slappyengine.asset_import import import_asset
        except Exception as exc:  # pragma: no cover - defensive
            _LOG.warning(
                "SceneWalker: asset_import unavailable (%s); using default mesh",
                exc,
            )
            self.asset_cache.put(mesh_path, self._default_mesh)
            return self._default_mesh
        try:
            result = import_asset(mesh_path)
        except Exception as exc:
            _LOG.warning(
                "SceneWalker: import_asset(%r) failed (%s); using default mesh",
                mesh_path, exc,
            )
            self.asset_cache.put(mesh_path, self._default_mesh)
            return self._default_mesh
        raw = result.primary_mesh
        mesh = _coerce_import_to_mesh(raw)
        if mesh is None:
            mesh = self._default_mesh
        self.asset_cache.put(mesh_path, mesh)
        return mesh

    # ------------------------------------------------------------------
    # Walking
    # ------------------------------------------------------------------

    def walk(
        self,
        renderer: Any,
        camera: Any,
        *,
        stats: RenderStats | None = None,
    ) -> RenderStats:
        """Traverse the scene once, submitting each entity to *renderer*.

        The walker respects frustum culling when *camera* exposes
        ``view_projection`` — invisible entities never reach
        ``renderer.submit_mesh``. Passing ``camera=None`` disables
        culling.

        Returns a :class:`RenderStats` snapshot (also populated in-place
        into ``stats`` when the caller passes one — useful for
        aggregating multi-scene walks).
        """
        if renderer is None:
            raise TypeError("SceneWalker.walk: renderer must not be None")
        if not hasattr(renderer, "submit_mesh"):
            raise TypeError(
                "SceneWalker.walk: renderer must expose submit_mesh; "
                f"got {type(renderer).__name__}"
            )
        out = stats if stats is not None else RenderStats()
        t0 = time.perf_counter()
        frustum: Frustum | None = None
        if camera is not None:
            try:
                frustum = Frustum.from_camera(camera)
            except (TypeError, ValueError) as exc:
                _LOG.info(
                    "SceneWalker.walk: could not build frustum (%s); "
                    "culling disabled", exc,
                )
                frustum = None
            # Push camera state so the renderer can drive its own uniforms.
            if hasattr(renderer, "set_camera") and hasattr(camera, "view_matrix"):
                try:
                    renderer.set_camera(
                        camera.view_matrix(), camera.projection_matrix(),
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    _LOG.info(
                        "SceneWalker.walk: renderer.set_camera failed (%s)",
                        exc,
                    )

        for entity in list(self.scene.entities):
            out.entities_walked += 1
            info = self.resolve_entity(entity)
            if info is None:
                continue
            if not info.visible or info.mesh is None:
                out.entities_culled += 1
                continue
            if frustum is not None and not frustum.intersects_aabb(info.bounding_box):
                out.entities_culled += 1
                continue
            renderer.submit_mesh(info.mesh, info.transform_matrix, info.material)
            out.draw_calls += 1

        out.wall_ms = (time.perf_counter() - t0) * 1000.0
        return out

    # ------------------------------------------------------------------
    def walk_with_lights(
        self,
        renderer: Any,
        camera: Any,
        lights: Iterable["Light"] | None,
        *,
        stats: RenderStats | None = None,
    ) -> RenderStats:
        """Push *lights* to the renderer, then walk the scene.

        Mirrors :meth:`walk` but front-loads a ``renderer.set_lights``
        call so materials can pick up the lighting environment before
        any mesh draw fires. When *lights* is ``None`` or empty the
        renderer's existing light state is left untouched.
        """
        if renderer is None:
            raise TypeError(
                "SceneWalker.walk_with_lights: renderer must not be None"
            )
        if lights is not None:
            light_list = list(lights)
            if light_list and hasattr(renderer, "set_lights"):
                try:
                    renderer.set_lights(light_list)
                except Exception as exc:  # pragma: no cover - defensive
                    _LOG.info(
                        "SceneWalker.walk_with_lights: set_lights failed (%s)",
                        exc,
                    )
        return self.walk(renderer, camera, stats=stats)


# ---------------------------------------------------------------------------
# Import → Mesh coercion
# ---------------------------------------------------------------------------


def _coerce_import_to_mesh(raw: Any) -> Mesh | None:
    """Best-effort conversion of an asset importer's mesh into a
    :class:`Mesh` — HH4's canonical dataclass.

    Handles the three shapes the importers currently produce:
      * :class:`Mesh` directly (identity).
      * :class:`GpuMesh` — pull ``vertices`` / ``indices`` attributes.
      * ``dict`` with ``vertices`` / ``indices`` keys.
    """
    if raw is None:
        return None
    if isinstance(raw, Mesh):
        return raw
    if isinstance(raw, dict):
        v = raw.get("vertices")
        i = raw.get("indices")
        if v is None or i is None:
            return None
        return _mesh_from_arrays(v, i)
    # Duck-type: object with vertices + indices attributes.
    v = getattr(raw, "vertices", None)
    i = getattr(raw, "indices", None)
    if v is None or i is None:
        return None
    return _mesh_from_arrays(v, i)


def _mesh_from_arrays(vertices: Any, indices: Any) -> Mesh | None:
    """Build a :class:`Mesh` from raw arrays, coercing shape when needed."""
    try:
        v_arr = np.ascontiguousarray(vertices, dtype=np.float32)
        i_arr = np.asarray(indices)
    except (TypeError, ValueError):
        return None
    if v_arr.ndim == 1:
        if v_arr.size % 3 != 0:
            return None
        v_arr = v_arr.reshape(-1, 3)
    if v_arr.ndim != 2 or v_arr.shape[1] != 3:
        return None
    if i_arr.ndim == 1:
        if i_arr.size % 3 != 0:
            return None
        i_arr = i_arr.reshape(-1, 3)
    if i_arr.ndim != 2 or i_arr.shape[1] != 3:
        return None
    i_arr = np.ascontiguousarray(i_arr, dtype=np.uint32)
    try:
        return Mesh(vertices=v_arr, indices=i_arr)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Convenience — top-level renderer driver
# ---------------------------------------------------------------------------


def render_scene(
    scene: "Scene",
    renderer: Any,
    camera: Any,
    *,
    lights: Iterable["Light"] | None = None,
    prefab_library: Any | None = None,
    asset_cache: AssetCache | None = None,
    stats: RenderStats | None = None,
) -> RenderStats:
    """One-shot Scene → renderer pipeline.

    Wraps :class:`SceneWalker`, opens / closes the renderer's frame, and
    returns a fresh :class:`RenderStats` snapshot. Handy for callers
    that just need "render this one scene to this one renderer" without
    holding onto walker state.
    """
    if scene is None:
        raise TypeError("render_scene: scene must not be None")
    if renderer is None:
        raise TypeError("render_scene: renderer must not be None")
    walker = SceneWalker(
        scene, prefab_library=prefab_library, asset_cache=asset_cache,
    )
    frame_opened = False
    if hasattr(renderer, "begin_frame") and hasattr(renderer, "end_frame"):
        try:
            renderer.begin_frame()
            frame_opened = True
        except RuntimeError:
            # Already inside a frame — caller drives the lifecycle.
            frame_opened = False
    try:
        out = walker.walk_with_lights(renderer, camera, lights, stats=stats)
    finally:
        if frame_opened:
            try:
                renderer.end_frame()
            except Exception as exc:  # pragma: no cover - defensive
                _LOG.info("render_scene: end_frame failed (%s)", exc)
    return out


# ---------------------------------------------------------------------------
# App bridge
# ---------------------------------------------------------------------------


def bridge_render_scene(
    app: Any,
    scene: "Scene",
    renderer: Any,
    *,
    camera: Any | None = None,
    lights: Iterable["Light"] | None = None,
) -> RenderStats:
    """Bridge helper for ``App.render_frame_from_scene(scene)``.

    Uses the app's own camera / lights when the caller doesn't override
    them, letting HH1 wire ``render_frame_from_scene`` in one line
    without importing this module in a hot path.

    Parameters
    ----------
    app
        The HH1 :class:`App` — inspected for ``camera`` / ``lights`` /
        ``prefab_library`` / ``asset_cache`` attributes.
    scene
        FF3 scene to walk.
    renderer
        HH4 renderer instance (already promoted).
    camera
        Explicit camera override; defaults to ``app.camera``.
    lights
        Explicit lights override; defaults to ``app.lights``.
    """
    if scene is None:
        raise TypeError("bridge_render_scene: scene must not be None")
    if renderer is None:
        raise TypeError("bridge_render_scene: renderer must not be None")
    cam = camera if camera is not None else getattr(app, "camera", None)
    lgt = lights if lights is not None else getattr(app, "lights", None)
    prefab_library = getattr(app, "prefab_library", None)
    asset_cache = getattr(app, "asset_cache", None)
    return render_scene(
        scene,
        renderer,
        cam,
        lights=lgt,
        prefab_library=prefab_library,
        asset_cache=asset_cache,
    )


__all__ = [
    "AssetCache",
    "EntityDrawInfo",
    "Frustum",
    "RenderStats",
    "SceneWalker",
    "bridge_render_scene",
    "render_scene",
]
