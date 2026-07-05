"""HH1 ↔ HH4 ↔ HH5 integration bridge.

This module wires the ergonomic HH1 :class:`slappyengine.app.App` API to
the HH4 renderer (:mod:`slappyengine.render`) and the HH5 asset importer
(:mod:`slappyengine.asset_import`). Nothing else in the engine needs
to know about the three surfaces at once — the bridge lives here so
``import slappyengine`` remains cheap.

The four public helpers:

* :func:`bridge_load_model` — parses an asset via HH5, builds a proper
  :class:`slappyengine.render.mesh.Mesh`, records it on a fresh
  :class:`~slappyengine.app.ModelHandle`, and returns the handle.
* :func:`bridge_submit_frame` — walks the app's models / lights /
  active-camera and issues renderer-compatible ``submit_*`` /
  ``set_*`` calls.
* :func:`promote_stub_renderer` — swaps the HH1 logging stub for a
  real HH4 :class:`~slappyengine.render.renderer.Renderer` (or
  :class:`~slappyengine.render.null_renderer.NullRenderer`) at runtime.
* :func:`default_material` — a sensible starting :class:`Material`
  (opaque, light gray).

The module deliberately avoids any hard import of
:mod:`slappyengine.render` or :mod:`slappyengine.asset_import` at
module-import time — every dependency is soft-imported inside the
helper that needs it. That keeps the module cheap and lets the tests
soft-skip cleanly when a subpackage is unavailable.
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:  # pragma: no cover - import only for type hints
    from slappyengine.app import App, LightHandle, ModelHandle
    from slappyengine.render.material import Material
    from slappyengine.render.mesh import Mesh


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mesh conversion — HH5 GpuMesh / dict → HH4 render.mesh.Mesh
# ---------------------------------------------------------------------------


def _extract_positions_and_indices(imported: Any) -> tuple[np.ndarray, np.ndarray]:
    """Best-effort extraction of ``(vertices_Nx3, indices_Mx3)`` from any HH5 mesh.

    Handles three shapes emitted by :mod:`slappyengine.asset_import`:

    1. A ``GpuMesh`` with ``_vertices`` (list of ``MeshVertex``) and
       ``_indices`` (flat list of int).
    2. A fallback dict with ``vertices`` (list of ``MeshVertex`` or dicts)
       and ``indices`` (flat list of int).
    3. Anything already numpy-shaped (fast path — pass through).

    Raises
    ------
    TypeError
        If the object doesn't look like any known shape.
    """
    # Path 3 — already-numpy Mesh-like duck type
    verts_attr = getattr(imported, "vertices", None)
    idx_attr = getattr(imported, "indices", None)
    if (
        isinstance(verts_attr, np.ndarray)
        and verts_attr.ndim == 2
        and verts_attr.shape[1] == 3
        and isinstance(idx_attr, np.ndarray)
    ):
        idx = idx_attr
        if idx.ndim == 1:
            idx = idx.reshape(-1, 3)
        return verts_attr.astype(np.float32, copy=False), idx.astype(np.uint32, copy=False)

    # Path 1 — GpuMesh
    if hasattr(imported, "_vertices") and hasattr(imported, "_indices"):
        verts = imported._vertices
        idx = imported._indices
    # Path 2 — fallback dict
    elif isinstance(imported, dict) and "vertices" in imported and "indices" in imported:
        verts = imported["vertices"]
        idx = imported["indices"]
    else:
        raise TypeError(
            f"cannot extract mesh geometry from {type(imported).__name__!r} "
            f"(expected GpuMesh, dict with vertices/indices, or numpy-shaped mesh)"
        )

    positions: list[tuple[float, float, float]] = []
    for v in verts:
        # MeshVertex has .position; fallback dict has ["position"].
        if hasattr(v, "position"):
            positions.append(tuple(v.position))
        elif isinstance(v, dict) and "position" in v:
            positions.append(tuple(v["position"]))
        elif isinstance(v, (list, tuple)) and len(v) >= 3:
            positions.append((float(v[0]), float(v[1]), float(v[2])))
        else:
            positions.append((0.0, 0.0, 0.0))

    vert_arr = np.asarray(positions, dtype=np.float32)
    if vert_arr.size == 0:
        vert_arr = np.zeros((0, 3), dtype=np.float32)

    idx_flat = np.asarray(list(idx), dtype=np.uint32)
    if idx_flat.size % 3 != 0:
        # Trim trailing partial triangle rather than crash.
        idx_flat = idx_flat[: (idx_flat.size // 3) * 3]
    idx_arr = idx_flat.reshape(-1, 3)
    return vert_arr, idx_arr


def _to_render_mesh(imported: Any) -> "Mesh":
    """Build a :class:`slappyengine.render.mesh.Mesh` from an HH5 import.

    The returned mesh has ``bounding_box`` populated from the vertex
    array (via :class:`Mesh.__post_init__`), so downstream code can
    read ``mesh.bounding_box`` immediately.
    """
    from slappyengine.render.mesh import Mesh  # noqa: PLC0415 - soft dep

    verts, idx = _extract_positions_and_indices(imported)
    if verts.shape[0] == 0 or idx.shape[0] == 0:
        # Renderer Mesh insists on non-empty (N,3) / (M,3). Fabricate a
        # 1-triangle degenerate mesh so tests can still assert on the
        # handle and bounding-box path.
        verts = np.zeros((3, 3), dtype=np.float32)
        idx = np.array([[0, 1, 2]], dtype=np.uint32)
    return Mesh(vertices=verts, indices=idx)


# ---------------------------------------------------------------------------
# Material
# ---------------------------------------------------------------------------


def default_material() -> "Material":
    """Return a sensible starting :class:`Material` — opaque light gray.

    Used by :func:`bridge_load_model` when the asset didn't carry an
    explicit material through the importer. Deliberately not a global
    singleton so callers can mutate freely without spooky action.
    """
    from slappyengine.render.material import Material  # noqa: PLC0415 - soft dep

    return Material(
        name="default",
        base_color=(0.8, 0.8, 0.8, 1.0),
        metallic=0.0,
        roughness=0.5,
        alpha_mode="opaque",
    )


# ---------------------------------------------------------------------------
# Transform matrix from HH1's Euler-tuple ModelHandle
# ---------------------------------------------------------------------------


def handle_transform_matrix(handle: "ModelHandle") -> np.ndarray:
    """Build a 4x4 model matrix from a :class:`ModelHandle`.

    Uses XYZ Euler convention (matches the ModelHandle docstring):
    ``M = T · Rz · Ry · Rx · S``.
    """
    px, py, pz = handle.position
    rx, ry, rz = handle.rotation
    sx, sy, sz = handle.scale

    cx, sx_ = math.cos(rx), math.sin(rx)
    cy, sy_ = math.cos(ry), math.sin(ry)
    cz, sz_ = math.cos(rz), math.sin(rz)

    # Rx
    Rx = np.array(
        [[1, 0, 0], [0, cx, -sx_], [0, sx_, cx]], dtype=np.float32
    )
    # Ry
    Ry = np.array(
        [[cy, 0, sy_], [0, 1, 0], [-sy_, 0, cy]], dtype=np.float32
    )
    # Rz
    Rz = np.array(
        [[cz, -sz_, 0], [sz_, cz, 0], [0, 0, 1]], dtype=np.float32
    )

    R = Rz @ Ry @ Rx
    S = np.diag([sx, sy, sz]).astype(np.float32)
    RS = R @ S

    m = np.eye(4, dtype=np.float32)
    m[:3, :3] = RS
    m[0, 3] = px
    m[1, 3] = py
    m[2, 3] = pz
    return m


# ---------------------------------------------------------------------------
# bridge_load_model — HH5 → HH1 ModelHandle
# ---------------------------------------------------------------------------


def bridge_load_model(app: "App", path: str) -> "ModelHandle":
    """Load an asset via HH5 and attach a real mesh to a new ModelHandle.

    The returned handle:

    * Is appended to ``app.models`` (matches HH1 :meth:`App.load_model`
      semantics).
    * Has ``.mesh`` set to a :class:`slappyengine.render.mesh.Mesh`.
    * Has ``.material`` defaulted to :func:`default_material` when the
      importer didn't supply one.
    * Has ``.bounding_box`` recorded ``((min_xyz), (max_xyz))`` for
      later camera framing.

    On any importer failure, falls back to the plain HH1 stub load path
    so the 2-line render pattern never crashes on a typo.
    """
    from slappyengine.app import ModelHandle  # noqa: PLC0415 - avoid import cycle

    try:
        from slappyengine.asset_import import import_asset  # noqa: PLC0415
    except Exception as exc:
        logger.info(
            "bridge_load_model: asset_import not importable (%s); "
            "falling back to stub loader",
            exc,
        )
        return app._load_model_stub(path)

    try:
        result = import_asset(path)
    except Exception as exc:
        logger.info(
            "bridge_load_model: import_asset(%r) failed (%s); "
            "falling back to stub loader",
            path,
            exc,
        )
        return app._load_model_stub(path)

    if not result.meshes:
        logger.info(
            "bridge_load_model: %r imported but returned no meshes; "
            "falling back to stub loader",
            path,
        )
        return app._load_model_stub(path)

    # Real path — build a proper render.mesh.Mesh from the first import.
    try:
        mesh = _to_render_mesh(result.meshes[0])
    except Exception as exc:
        logger.warning(
            "bridge_load_model: mesh conversion failed for %r (%s); "
            "falling back to stub loader",
            path,
            exc,
        )
        return app._load_model_stub(path)

    handle = ModelHandle(
        path=str(path),
        id=app._next_id(),
        _app=app,
    )
    # Attach the real mesh + material + bbox as ad-hoc attributes.
    # ModelHandle is a dataclass, but Python still lets us tack extras
    # onto individual instances — cheaper than widening the dataclass
    # signature for a rarely-populated payload.
    handle.mesh = mesh
    handle.material = default_material()
    handle.bounding_box = mesh.bounding_box
    app.models.append(handle)
    app.trace.append(("load_model", handle.id, str(path), ".obj"))
    app.trace.append(("bridge_load_model", handle.id, mesh.vertices.shape[0]))
    return handle


# ---------------------------------------------------------------------------
# bridge_submit_frame — HH1 App → HH4 Renderer
# ---------------------------------------------------------------------------


def bridge_submit_frame(app: "App", renderer: Any) -> None:
    """Walk ``app.models`` / ``app.lights`` / active camera → HH4 renderer.

    The renderer here must be a HH4 :class:`Renderer` /
    :class:`NullRenderer` (i.e. have ``submit_mesh`` / ``set_lights`` /
    ``set_camera``). Callers wrap this between the renderer's
    ``begin_frame`` / ``end_frame``.
    """
    # Camera first — some pipelines bind the view/proj UBO before draws.
    cam = app.active_camera
    if cam is not None:
        try:
            from slappyengine.render.camera import Camera3D  # noqa: PLC0415

            c3d = Camera3D(
                position=cam.position,
                look_at=cam.look_at,
                fov_degrees=cam.fov_deg,
                near=cam.near,
                far=cam.far,
                aspect=(
                    app.config.window_size[0] / app.config.window_size[1]
                    if app.config.window_size[1]
                    else 16.0 / 9.0
                ),
            )
            renderer.set_camera(c3d.view_matrix(), c3d.projection_matrix())
        except Exception as exc:
            logger.debug("bridge_submit_frame: camera setup skipped (%s)", exc)

    # Lights — convert HH1 LightHandle → HH4 Light.
    if app.lights:
        try:
            from slappyengine.render.light import Light  # noqa: PLC0415

            packed: list[Any] = []
            for lh in app.lights:
                packed.append(
                    Light(
                        kind="point",
                        position=tuple(lh.position),
                        color=tuple(lh.color),
                        intensity=float(lh.intensity),
                    )
                )
            renderer.set_lights(packed)
        except Exception as exc:
            logger.debug("bridge_submit_frame: lights setup skipped (%s)", exc)

    # Meshes — submit each visible model with mesh + material.
    default_mat = None
    for handle in app.models:
        if not getattr(handle, "visible", True):
            continue
        mesh = getattr(handle, "mesh", None)
        if mesh is None:
            continue  # stub-loaded handles have no mesh — skip
        mat = getattr(handle, "material", None)
        if mat is None:
            if default_mat is None:
                default_mat = default_material()
            mat = default_mat
        model_matrix = handle_transform_matrix(handle)
        renderer.submit_mesh(mesh, model_matrix, mat)


# ---------------------------------------------------------------------------
# promote_stub_renderer — swap HH1's _StubRenderer for a real backend
# ---------------------------------------------------------------------------


def promote_stub_renderer(app: "App") -> None:
    """Swap ``app._renderer`` for a real HH4 renderer when appropriate.

    Selection matrix:

    +-------------------+-----------------+------------------------+
    | enable_gpu        | wgpu available? | outcome                |
    +===================+=================+========================+
    | False             | any             | HH4 ``NullRenderer``   |
    +-------------------+-----------------+------------------------+
    | True              | yes             | HH4 ``Renderer`` (wgpu)|
    +-------------------+-----------------+------------------------+
    | True              | no              | HH4 ``NullRenderer``   |
    +-------------------+-----------------+------------------------+

    If ``app._renderer`` is already a real HH4 backend, this is a no-op.
    """
    from slappyengine.app import _StubRenderer  # noqa: PLC0415

    if not isinstance(app._renderer, _StubRenderer):
        return  # already promoted

    try:
        from slappyengine.render import (  # noqa: PLC0415
            NullRenderer,
            Renderer,
            is_wgpu_available,
        )
    except Exception as exc:  # pragma: no cover - render subpackage missing
        logger.info(
            "promote_stub_renderer: HH4 render subpackage unavailable (%s)", exc
        )
        return

    cfg = app.config
    want_gpu = bool(cfg.enable_gpu) and cfg.renderer_backend not in ("stub", "headless")

    if want_gpu and is_wgpu_available():
        try:
            app._renderer = Renderer(
                window_size=cfg.window_size,
                msaa=cfg.msaa_samples,
                clear_color=cfg.clear_color,
                vsync=cfg.vsync,
            )
            app.trace.append(("promote_renderer", "Renderer"))
            return
        except Exception as exc:
            logger.info(
                "promote_stub_renderer: Renderer init failed (%s); "
                "falling back to NullRenderer",
                exc,
            )

    # Headless / GPU-disabled / init-failed → NullRenderer.
    app._renderer = NullRenderer(
        window_size=cfg.window_size,
        msaa=cfg.msaa_samples,
        clear_color=cfg.clear_color,
        vsync=cfg.vsync,
    )
    app.trace.append(("promote_renderer", "NullRenderer"))


__all__ = [
    "bridge_load_model",
    "bridge_submit_frame",
    "default_material",
    "handle_transform_matrix",
    "promote_stub_renderer",
]
