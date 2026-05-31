"""GPU port of ``ParticleField._integrate``.

Proof-of-concept for moving the cheapest ParticleField kernel onto a
compute shader (see ``shaders/particle_integrate.wgsl``).

Public API
----------
``gpu_integrate(field, dt)``
    Mirror of ``ParticleField._integrate(field, ~field.landed, dt)`` but
    executed on the GPU when ``wgpu`` is available. Falls back to a
    pure-numpy implementation that produces bit-identical output so the
    rest of the engine can target the same call site regardless of
    backend.

Notes
-----
- Device creation is lazy and one-shot per process — first call probes
  for a wgpu adapter; on failure the wrapper switches permanently into
  the numpy fallback path (and emits a warning once).
- Bind-group layout uses storage buffers for pos / vel / material_id /
  phase / material props, plus a small uniform for ``(gravity, dt,
  n_particles)``. Workgroup size is 64; see the shader comment for the
  rationale.
- Only AIRBORNE particles (``phase == 0``) are advanced; identical to
  the CPU mask ``air_mask = ~self.landed``.
"""
from __future__ import annotations

import struct
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from slappyengine.physics.particle_field import ParticleField


_SHADER_DIR = Path(__file__).resolve().parent.parent.parent.parent / "shaders"
_SHADER_PATH = _SHADER_DIR / "particle_integrate.wgsl"
_COLLIDE_SHADER_PATH = _SHADER_DIR / "particle_collide.wgsl"
_THERMAL_SHADER_PATH = _SHADER_DIR / "particle_thermal.wgsl"
_COLUMN_TOP_SHADER_PATH = _SHADER_DIR / "particle_column_top.wgsl"
_SLIDE_SHADER_PATH = _SHADER_DIR / "particle_slide.wgsl"
_KINETIC_RELAX_SHADER_PATH = _SHADER_DIR / "particle_kinetic_relax.wgsl"
_BAKE_SHADER_PATH = _SHADER_DIR / "particle_bake.wgsl"
_SLUMP_SHADER_PATH = _SHADER_DIR / "particle_slump.wgsl"
_WORKGROUP_SIZE = 64
# 2D workgroup for the slump kernel — must mirror @workgroup_size(8, 8)
# in shaders/particle_slump.wgsl.
_SLUMP_WG_X = 8
_SLUMP_WG_Y = 8

# ── Lazy device / pipeline cache ───────────────────────────────────────
_GPU_PROBED = False
_GPU_AVAILABLE = False
_WGPU = None  # type: ignore[var-annotated]
_DEVICE = None  # type: ignore[var-annotated]
_QUEUE = None  # type: ignore[var-annotated]
_PIPELINE = None  # type: ignore[var-annotated]
_SHADER_SRC: str | None = None
_COLLIDE_PIPELINE = None  # type: ignore[var-annotated]
_COLLIDE_SHADER_SRC: str | None = None
_THERMAL_PIPELINE = None  # type: ignore[var-annotated]
_THERMAL_SHADER_SRC: str | None = None
_COLUMN_TOP_PIPELINE = None  # type: ignore[var-annotated]
_COLUMN_TOP_SHADER_SRC: str | None = None
_SLIDE_PIPELINE = None  # type: ignore[var-annotated]
_SLIDE_SHADER_SRC: str | None = None
_KINETIC_RELAX_PIPELINE = None  # type: ignore[var-annotated]
_KINETIC_RELAX_SHADER_SRC: str | None = None
_BAKE_PIPELINE = None  # type: ignore[var-annotated]
_BAKE_SHADER_SRC: str | None = None
_SLUMP_PIPELINE = None  # type: ignore[var-annotated]
_SLUMP_SHADER_SRC: str | None = None
# Cached shape-mask atlas (built once per (process, materials list).
# Key = id of the materials list so a rebuild on swap reuses the slot.
_BAKE_ATLAS_CACHE: dict[int, "_BakeAtlas"] = {}


def _probe_gpu() -> bool:
    """One-shot adapter+device probe; idempotent."""
    global _GPU_PROBED, _GPU_AVAILABLE, _WGPU, _DEVICE, _QUEUE, _PIPELINE, _SHADER_SRC
    global _COLLIDE_PIPELINE, _COLLIDE_SHADER_SRC
    global _THERMAL_PIPELINE, _THERMAL_SHADER_SRC
    global _COLUMN_TOP_PIPELINE, _COLUMN_TOP_SHADER_SRC
    global _SLIDE_PIPELINE, _SLIDE_SHADER_SRC
    global _KINETIC_RELAX_PIPELINE, _KINETIC_RELAX_SHADER_SRC
    global _BAKE_PIPELINE, _BAKE_SHADER_SRC
    global _SLUMP_PIPELINE, _SLUMP_SHADER_SRC
    if _GPU_PROBED:
        return _GPU_AVAILABLE
    _GPU_PROBED = True

    try:
        import wgpu  # type: ignore
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: wgpu not importable ({exc!r}); using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: adapter request failed ({exc!r}); using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    if adapter is None:
        warnings.warn(
            "particle_gpu: no wgpu adapter available; using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        device = adapter.request_device_sync(required_features=[], required_limits={})
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: device request failed ({exc!r}); using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        src = _SHADER_PATH.read_text(encoding="utf-8")
        module = device.create_shader_module(code=src, label="particle_integrate")
        pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": module, "entry_point": "main"},
            label="particle_integrate_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: pipeline build failed ({exc!r}); using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        collide_src = _COLLIDE_SHADER_PATH.read_text(encoding="utf-8")
        collide_module = device.create_shader_module(
            code=collide_src, label="particle_collide")
        collide_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": collide_module, "entry_point": "main"},
            label="particle_collide_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: collide pipeline build failed ({exc!r}); "
            "using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        thermal_src = _THERMAL_SHADER_PATH.read_text(encoding="utf-8")
        thermal_module = device.create_shader_module(
            code=thermal_src, label="particle_thermal")
        thermal_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": thermal_module, "entry_point": "main"},
            label="particle_thermal_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: thermal pipeline build failed ({exc!r}); "
            "using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        col_top_src = _COLUMN_TOP_SHADER_PATH.read_text(encoding="utf-8")
        col_top_module = device.create_shader_module(
            code=col_top_src, label="particle_column_top")
        col_top_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": col_top_module, "entry_point": "main"},
            label="particle_column_top_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: column_top pipeline build failed ({exc!r}); "
            "using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        slide_src = _SLIDE_SHADER_PATH.read_text(encoding="utf-8")
        slide_module = device.create_shader_module(
            code=slide_src, label="particle_slide")
        slide_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": slide_module, "entry_point": "main"},
            label="particle_slide_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: slide pipeline build failed ({exc!r}); "
            "using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        krelax_src = _KINETIC_RELAX_SHADER_PATH.read_text(encoding="utf-8")
        krelax_module = device.create_shader_module(
            code=krelax_src, label="particle_kinetic_relax")
        krelax_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": krelax_module, "entry_point": "main"},
            label="particle_kinetic_relax_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: kinetic_relax pipeline build failed ({exc!r}); "
            "using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        bake_src = _BAKE_SHADER_PATH.read_text(encoding="utf-8")
        bake_module = device.create_shader_module(
            code=bake_src, label="particle_bake")
        bake_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": bake_module, "entry_point": "main"},
            label="particle_bake_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: bake pipeline build failed ({exc!r}); "
            "using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        slump_src = _SLUMP_SHADER_PATH.read_text(encoding="utf-8")
        slump_module = device.create_shader_module(
            code=slump_src, label="particle_slump")
        slump_pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": slump_module, "entry_point": "main"},
            label="particle_slump_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: slump pipeline build failed ({exc!r}); "
            "using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    _WGPU = wgpu
    _DEVICE = device
    _QUEUE = device.queue
    _PIPELINE = pipeline
    _SHADER_SRC = src
    _COLLIDE_PIPELINE = collide_pipeline
    _COLLIDE_SHADER_SRC = collide_src
    _THERMAL_PIPELINE = thermal_pipeline
    _THERMAL_SHADER_SRC = thermal_src
    _COLUMN_TOP_PIPELINE = col_top_pipeline
    _COLUMN_TOP_SHADER_SRC = col_top_src
    _SLIDE_PIPELINE = slide_pipeline
    _SLIDE_SHADER_SRC = slide_src
    _KINETIC_RELAX_PIPELINE = krelax_pipeline
    _KINETIC_RELAX_SHADER_SRC = krelax_src
    _BAKE_PIPELINE = bake_pipeline
    _BAKE_SHADER_SRC = bake_src
    _SLUMP_PIPELINE = slump_pipeline
    _SLUMP_SHADER_SRC = slump_src
    _GPU_AVAILABLE = True
    return True


# ── Numpy fallback (bit-identical to ParticleField._integrate) ────────


def _numpy_integrate(field: "ParticleField", dt: float) -> None:
    """Pure-numpy port — used when wgpu is unavailable."""
    if field.pos.shape[0] == 0:
        return
    air_mask = ~field.landed
    if not air_mask.any():
        return
    for mi, mat in enumerate(field.materials):
        m = air_mask & (field.material_id == mi)
        if not m.any():
            continue
        field.vel[m] *= mat.air_drag_per_sec ** dt
        field.vel[m, 1] += field.gravity * mat.gravity_scale * dt
    field.pos[air_mask] += field.vel[air_mask] * dt


# ── GPU dispatch ──────────────────────────────────────────────────────


def _pack_mat_props(field: "ParticleField") -> np.ndarray:
    """Per-material (gravity_scale, air_drag_per_sec) → vec2<f32> array."""
    n = len(field.materials)
    arr = np.empty((n, 2), dtype=np.float32)
    for i, mat in enumerate(field.materials):
        arr[i, 0] = float(mat.gravity_scale)
        arr[i, 1] = float(mat.air_drag_per_sec)
    return arr


def _gpu_integrate(field: "ParticleField", dt: float) -> None:
    """Dispatch the WGSL compute kernel, read back pos/vel, write to field."""
    n = int(field.pos.shape[0])
    if n == 0:
        return

    wgpu = _WGPU
    device = _DEVICE
    pipeline = _PIPELINE

    # ── Upload (storage buffers) ─────────────────────────────────────
    pos_np = np.ascontiguousarray(field.pos, dtype=np.float32)
    vel_np = np.ascontiguousarray(field.vel, dtype=np.float32)
    mid_np = np.ascontiguousarray(field.material_id, dtype=np.int32)
    # phase array is int8 on the CPU; widen to i32 for storage buffer
    # alignment (WGSL atomics / scalar load require 32-bit elements).
    phase_np = field.phase.astype(np.int32, copy=False)
    mat_props_np = _pack_mat_props(field)

    pos_bytes = pos_np.nbytes
    vel_bytes = vel_np.nbytes
    mid_bytes = mid_np.nbytes
    phase_bytes = phase_np.nbytes
    mat_bytes = mat_props_np.nbytes

    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST

    pos_buf = device.create_buffer(size=pos_bytes, usage=USAGE_RW, label="pf_pos")
    vel_buf = device.create_buffer(size=vel_bytes, usage=USAGE_RW, label="pf_vel")
    mid_buf = device.create_buffer(size=mid_bytes, usage=USAGE_R, label="pf_mid")
    phase_buf = device.create_buffer(size=phase_bytes, usage=USAGE_R, label="pf_phase")
    mat_buf = device.create_buffer(size=mat_bytes, usage=USAGE_R, label="pf_mat_props")

    device.queue.write_buffer(pos_buf, 0, pos_np)
    device.queue.write_buffer(vel_buf, 0, vel_np)
    device.queue.write_buffer(mid_buf, 0, mid_np)
    device.queue.write_buffer(phase_buf, 0, phase_np)
    device.queue.write_buffer(mat_buf, 0, mat_props_np)

    # ── Params uniform: (gravity: f32, dt: f32, n: u32, _pad0: u32) ──
    params_data = struct.pack("ffII", float(field.gravity), float(dt), n, 0)
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="pf_params",
    )
    device.queue.write_buffer(params_buf, 0, np.frombuffer(params_data, dtype=np.uint8))

    # ── Bind group ──
    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0, "resource": {"buffer": pos_buf,    "offset": 0, "size": pos_bytes}},
            {"binding": 1, "resource": {"buffer": vel_buf,    "offset": 0, "size": vel_bytes}},
            {"binding": 2, "resource": {"buffer": mid_buf,    "offset": 0, "size": mid_bytes}},
            {"binding": 3, "resource": {"buffer": phase_buf,  "offset": 0, "size": phase_bytes}},
            {"binding": 4, "resource": {"buffer": mat_buf,    "offset": 0, "size": mat_bytes}},
            {"binding": 5, "resource": {"buffer": params_buf, "offset": 0, "size": len(params_data)}},
        ],
    )

    # ── Dispatch ──
    encoder = device.create_command_encoder(label="pf_integrate")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_groups = max(1, (n + _WORKGROUP_SIZE - 1) // _WORKGROUP_SIZE)
    cp.dispatch_workgroups(n_groups)
    cp.end()
    device.queue.submit([encoder.finish()])

    # ── Readback pos + vel ──
    pos_out = _readback(device, pos_buf, pos_bytes, dtype=np.float32).reshape(n, 2)
    vel_out = _readback(device, vel_buf, vel_bytes, dtype=np.float32).reshape(n, 2)

    # Write back into the field's SoA. ParticleField._integrate mutates
    # in place — preserve that contract by copying into the existing
    # arrays rather than rebinding the attribute (other systems may hold
    # views).
    field.pos[...] = pos_out
    field.vel[...] = vel_out

    # Best-effort cleanup of transient buffers.
    for buf in (pos_buf, vel_buf, mid_buf, phase_buf, mat_buf, params_buf):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass


def _readback(device, src_buf, size_bytes: int, dtype) -> np.ndarray:
    """Copy a storage buffer into a MAP_READ staging buffer; return ndarray."""
    wgpu = _WGPU
    staging = device.create_buffer(
        size=size_bytes,
        usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
        label="pf_readback",
    )
    encoder = device.create_command_encoder(label="pf_readback_copy")
    encoder.copy_buffer_to_buffer(src_buf, 0, staging, 0, size_bytes)
    device.queue.submit([encoder.finish()])

    staging.map_sync(wgpu.MapMode.READ)
    raw = np.frombuffer(staging.read_mapped(0, size_bytes), dtype=dtype).copy()
    staging.unmap()
    try:
        staging.destroy()
    except Exception:  # noqa: BLE001
        pass
    return raw


# ── Public entry point ────────────────────────────────────────────────


def gpu_integrate(field: "ParticleField", dt: float) -> None:
    """Advance airborne particles' pos/vel for one step.

    Drop-in replacement for ``ParticleField._integrate(~field.landed, dt)``.
    Uses a WGSL compute shader if wgpu is available; otherwise falls back
    to a pure-numpy mimic with identical observable behaviour.
    """
    if field.pos.shape[0] == 0:
        return
    if _probe_gpu():
        _gpu_integrate(field, dt)
    else:
        _numpy_integrate(field, dt)


def is_gpu_available() -> bool:
    """Probe (cached) whether the GPU path is active in this process."""
    return _probe_gpu()


# ──────────────────────────────────────────────────────────────────────
# Kinetic-relax GPU port
# ──────────────────────────────────────────────────────────────────────
#
# Mirrors ``ParticleField._kinetic_relax`` (the *vectorised* numpy form).
#
# Per particle:
#   * Filter by material.is_fluid == False, bake_flag == False,
#     phase < SETTLING.
#   * Strength = max(material.kinetic_fluidity * (1 - age/rig), 0.4).
# Per pair (i, j) within the SAME spatial-hash cell with |pi - pj| in
# (0, rest_distance):
#   * f      = (rest - d) * 0.4 * 0.5 * (g_i + g_j)
#   * push_i += normal * f      (push_j accumulates -normal*f when j's
#                                thread runs — symmetric, no atomics)
# Final: pos[i] += push[i].
#
# Spatial hash is rebuilt CPU-side via ``physics.particle_spatial.SpatialHash``
# (cheap at ~0.4 ms / 10 k particles per Sprint 1 benchmarks). Only the
# resulting ``cell_start`` / ``cell_count`` / ``sorted_ids`` arrays are
# uploaded — same drop-in layout as ``shaders/particle_spatial_hash.wgsl``.

_KINETIC_REST_DISTANCE = 2.5   # ParticleField._kinetic_relax constant
_KINETIC_BASELINE     = 0.4    # ParticleField._kinetic_relax constant
_KINETIC_BIN_SIZE     = _KINETIC_REST_DISTANCE * 1.5  # cell_size for the hash


def _pack_kinetic_mat_props(field: "ParticleField") -> np.ndarray:
    """Per-material (kinetic_fluidity, is_fluid) → vec2<f32>."""
    n = len(field.materials)
    arr = np.empty((n, 2), dtype=np.float32)
    for i, mat in enumerate(field.materials):
        arr[i, 0] = float(mat.kinetic_fluidity)
        arr[i, 1] = 1.0 if mat.is_fluid else 0.0
    return arr


def _build_kinetic_hash(positions: np.ndarray):
    """Build the spatial-hash buffers required by particle_kinetic_relax.wgsl.

    Returns ``(cell_start, cell_count, sorted_ids, cell_id, grid_w, grid_h)``
    where ``cell_id[i]`` is the cell key of particle ``i`` (or -1 if it
    fell outside the padded grid).

    Mirrors the EXACT binning convention from
    ``ParticleField._kinetic_relax``::

        bx = (pos[:, 0] / bin_size).astype(np.int32)
        by = (pos[:, 1] / bin_size).astype(np.int32)

    i.e. integer truncation in world coordinates, NOT bounding-box
    shifted floor. We can't use ``SpatialHash`` directly because it
    phase-aligns the grid to the field's origin which, combined with
    a per-frame bbox shift, can group particles that the CPU path
    bins into separate cells (and vice versa).
    """
    if positions.size == 0:
        return (
            np.zeros(0, dtype=np.int32),
            np.zeros(0, dtype=np.int32),
            np.zeros(0, dtype=np.int32),
            np.zeros(0, dtype=np.int32),
            0,
            0,
        )

    bin_size = float(_KINETIC_BIN_SIZE)
    bx = (positions[:, 0] / bin_size).astype(np.int32)
    by = (positions[:, 1] / bin_size).astype(np.int32)

    # Build a flat grid covering the actual bx/by range plus 1-cell
    # padding so neighbour walks (if we add them later) stay in-bounds.
    bx_min = int(bx.min())
    by_min = int(by.min())
    bx_max = int(bx.max())
    by_max = int(by.max())
    grid_w = (bx_max - bx_min) + 1
    grid_h = (by_max - by_min) + 1

    # Re-base cell coords to 0..grid_w-1 / 0..grid_h-1.
    cx = bx - bx_min
    cy = by - by_min
    cell_id = (cy * grid_w + cx).astype(np.int32)
    n_cells = grid_w * grid_h

    # Counting-sort: cell_count via bincount, cell_start via cumsum,
    # sorted_ids via stable argsort. Same layout as SpatialHash but
    # without the bbox-shift indirection.
    n = positions.shape[0]
    cell_count = np.bincount(cell_id, minlength=n_cells).astype(np.int32)
    cell_start = np.zeros(n_cells, dtype=np.int32)
    if n_cells > 1:
        np.cumsum(cell_count[:-1], out=cell_start[1:])
    order = np.argsort(cell_id, kind="stable")
    sorted_ids = order.astype(np.int32)

    return (cell_start, cell_count, sorted_ids, cell_id, grid_w, grid_h)


def _numpy_kinetic_relax(field: "ParticleField", dt: float) -> None:
    """Pure-numpy fallback — defer to the field's vectorised method."""
    field._kinetic_relax(dt)


def _gpu_kinetic_relax(field: "ParticleField", dt: float) -> None:
    """Dispatch the WGSL kinetic-relax kernel and apply ``push`` to pos."""
    n = int(field.pos.shape[0])
    if n < 2:
        return

    wgpu = _WGPU
    device = _DEVICE
    pipeline = _KINETIC_RELAX_PIPELINE

    # ── CPU-side spatial hash rebuild ────────────────────────────────
    pos_np = np.ascontiguousarray(field.pos, dtype=np.float32)
    cell_start, cell_count, sorted_ids, cell_id, grid_w, grid_h = (
        _build_kinetic_hash(pos_np)
    )

    if grid_w == 0 or grid_h == 0:
        return

    mid_np = np.ascontiguousarray(field.material_id, dtype=np.int32)
    phase_np = field.phase.astype(np.int32, copy=False)
    bake_np = field.bake_flag.astype(np.uint32, copy=False)
    rig_np = field.rigidify_at.astype(np.int32, copy=False)
    age_np = field.kinetic_age.astype(np.int32, copy=False)
    mat_props_np = _pack_kinetic_mat_props(field)
    push_zero = np.zeros((n, 2), dtype=np.float32)

    # Sizes
    pos_bytes        = pos_np.nbytes
    cell_start_bytes = cell_start.nbytes
    cell_count_bytes = cell_count.nbytes
    sorted_ids_bytes = sorted_ids.nbytes
    cell_id_bytes    = cell_id.nbytes
    mid_bytes        = mid_np.nbytes
    phase_bytes      = phase_np.nbytes
    bake_bytes       = bake_np.nbytes
    rig_bytes        = rig_np.nbytes
    age_bytes        = age_np.nbytes
    push_bytes       = push_zero.nbytes
    mat_bytes        = mat_props_np.nbytes

    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST

    # Empty bindings would be UB; use a 4-byte stub so the bind group
    # validates. The shader's bounds checks make the stub harmless.
    def _safe_size(nbytes: int) -> int:
        return max(4, nbytes)

    pos_buf        = device.create_buffer(size=_safe_size(pos_bytes),        usage=USAGE_R,  label="kr_pos")
    cell_start_buf = device.create_buffer(size=_safe_size(cell_start_bytes), usage=USAGE_R,  label="kr_cell_start")
    cell_count_buf = device.create_buffer(size=_safe_size(cell_count_bytes), usage=USAGE_R,  label="kr_cell_count")
    sorted_ids_buf = device.create_buffer(size=_safe_size(sorted_ids_bytes), usage=USAGE_R,  label="kr_sorted_ids")
    cell_id_buf    = device.create_buffer(size=_safe_size(cell_id_bytes),    usage=USAGE_R,  label="kr_cell_id")
    mid_buf        = device.create_buffer(size=_safe_size(mid_bytes),        usage=USAGE_R,  label="kr_mid")
    phase_buf      = device.create_buffer(size=_safe_size(phase_bytes),      usage=USAGE_R,  label="kr_phase")
    bake_buf       = device.create_buffer(size=_safe_size(bake_bytes),       usage=USAGE_R,  label="kr_bake")
    rig_buf        = device.create_buffer(size=_safe_size(rig_bytes),        usage=USAGE_R,  label="kr_rig")
    age_buf        = device.create_buffer(size=_safe_size(age_bytes),        usage=USAGE_R,  label="kr_age")
    push_buf       = device.create_buffer(size=_safe_size(push_bytes),       usage=USAGE_RW, label="kr_push")
    mat_buf        = device.create_buffer(size=_safe_size(mat_bytes),        usage=USAGE_R,  label="kr_mat_props")

    if pos_bytes:        device.queue.write_buffer(pos_buf,        0, pos_np)
    if cell_start_bytes: device.queue.write_buffer(cell_start_buf, 0, cell_start)
    if cell_count_bytes: device.queue.write_buffer(cell_count_buf, 0, cell_count)
    if sorted_ids_bytes: device.queue.write_buffer(sorted_ids_buf, 0, sorted_ids)
    if cell_id_bytes:    device.queue.write_buffer(cell_id_buf,    0, cell_id)
    if mid_bytes:        device.queue.write_buffer(mid_buf,        0, mid_np)
    if phase_bytes:      device.queue.write_buffer(phase_buf,      0, phase_np)
    if bake_bytes:       device.queue.write_buffer(bake_buf,       0, bake_np)
    if rig_bytes:        device.queue.write_buffer(rig_buf,        0, rig_np)
    if age_bytes:        device.queue.write_buffer(age_buf,        0, age_np)
    if push_bytes:       device.queue.write_buffer(push_buf,       0, push_zero)
    if mat_bytes:        device.queue.write_buffer(mat_buf,        0, mat_props_np)

    # ── Params uniform ──
    # Layout matches struct Params in particle_kinetic_relax.wgsl:
    #   f32 rest_distance, f32 baseline_strength, f32 cell_size,
    #   u32 n_particles, i32 grid_w, i32 grid_h, u32 _pad0, u32 _pad1
    params_data = struct.pack(
        "fffIiiII",
        float(_KINETIC_REST_DISTANCE),
        float(_KINETIC_BASELINE),
        float(_KINETIC_BIN_SIZE),
        n,
        int(grid_w),
        int(grid_h),
        0,
        0,
    )
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="kr_params",
    )
    device.queue.write_buffer(params_buf, 0, np.frombuffer(params_data, dtype=np.uint8))

    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0,  "resource": {"buffer": pos_buf,        "offset": 0, "size": _safe_size(pos_bytes)}},
            {"binding": 1,  "resource": {"buffer": cell_start_buf, "offset": 0, "size": _safe_size(cell_start_bytes)}},
            {"binding": 2,  "resource": {"buffer": cell_count_buf, "offset": 0, "size": _safe_size(cell_count_bytes)}},
            {"binding": 3,  "resource": {"buffer": sorted_ids_buf, "offset": 0, "size": _safe_size(sorted_ids_bytes)}},
            {"binding": 4,  "resource": {"buffer": cell_id_buf,    "offset": 0, "size": _safe_size(cell_id_bytes)}},
            {"binding": 5,  "resource": {"buffer": mid_buf,        "offset": 0, "size": _safe_size(mid_bytes)}},
            {"binding": 6,  "resource": {"buffer": phase_buf,      "offset": 0, "size": _safe_size(phase_bytes)}},
            {"binding": 7,  "resource": {"buffer": bake_buf,       "offset": 0, "size": _safe_size(bake_bytes)}},
            {"binding": 8,  "resource": {"buffer": rig_buf,        "offset": 0, "size": _safe_size(rig_bytes)}},
            {"binding": 9,  "resource": {"buffer": age_buf,        "offset": 0, "size": _safe_size(age_bytes)}},
            {"binding": 10, "resource": {"buffer": push_buf,       "offset": 0, "size": _safe_size(push_bytes)}},
            {"binding": 11, "resource": {"buffer": mat_buf,        "offset": 0, "size": _safe_size(mat_bytes)}},
            {"binding": 12, "resource": {"buffer": params_buf,     "offset": 0, "size": len(params_data)}},
        ],
    )

    encoder = device.create_command_encoder(label="kr_dispatch")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_groups = max(1, (n + _WORKGROUP_SIZE - 1) // _WORKGROUP_SIZE)
    cp.dispatch_workgroups(n_groups)
    cp.end()
    device.queue.submit([encoder.finish()])

    # Readback the push buffer and apply it CPU-side. Applying on the
    # GPU would save a roundtrip but would also require ``pos`` to be
    # read_write on the GPU (forcing a vel/material-id readback too).
    # Until the whole step lives on GPU, the readback is the simpler
    # contract.
    push_out = _readback(device, push_buf, push_bytes, dtype=np.float32).reshape(n, 2)
    field.pos += push_out

    for buf in (pos_buf, cell_start_buf, cell_count_buf, sorted_ids_buf,
                cell_id_buf, mid_buf, phase_buf, bake_buf, rig_buf,
                age_buf, push_buf, mat_buf, params_buf):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass


def gpu_kinetic_relax(field: "ParticleField", dt: float) -> None:
    """Drop-in replacement for ``ParticleField._kinetic_relax(dt)``.

    Uses a WGSL compute shader when wgpu is available; otherwise falls
    back to the existing vectorised CPU path.
    """
    if field.pos.shape[0] < 2:
        return
    if _probe_gpu():
        _gpu_kinetic_relax(field, dt)
    else:
        _numpy_kinetic_relax(field, dt)


# ──────────────────────────────────────────────────────────────────────
# Collide GPU port
# ──────────────────────────────────────────────────────────────────────


def _numpy_collide(field: "ParticleField", dt: float) -> None:
    """No GPU available — call the CPU ``_collide`` over current air_mask.

    Matches the contract of ``ParticleField.step``: ``air_mask`` is
    captured BEFORE integration as ``~self.landed``. ``gpu_collide``
    runs after integration; integration doesn't flip phase so the
    equivalent post-integrate mask is ``phase == Phase.AIRBORNE``.
    """
    if field.pos.shape[0] == 0:
        return
    from slappyengine.physics.particle_field import Phase
    air_mask = field.phase == np.int8(Phase.AIRBORNE)
    if not air_mask.any():
        return
    field._collide(air_mask, dt)


def _pack_collide_mat_props(field: "ParticleField") -> np.ndarray:
    """Per-material (is_fluid, impact_stickiness, drill_max_px, _pad) -> vec4<f32>."""
    n = len(field.materials)
    arr = np.zeros((n, 4), dtype=np.float32)
    for i, mat in enumerate(field.materials):
        arr[i, 0] = 1.0 if mat.is_fluid else 0.0
        arr[i, 1] = float(mat.impact_stickiness)
        arr[i, 2] = float(mat.drill_max_px)
        arr[i, 3] = 0.0
    return arr


def _any_active_drill(field: "ParticleField") -> bool:
    """True iff any airborne particle is a drill material.

    The GPU collide kernel does not implement the drill carve path;
    such particles must take the CPU path for correctness. The drill
    kernel will land in a follow-up sprint.
    """
    from slappyengine.physics.particle_field import Phase
    air = field.phase == np.int8(Phase.AIRBORNE)
    if not air.any():
        return False
    for mi, mat in enumerate(field.materials):
        if mat.drill_max_px > 0:
            if (air & (field.material_id == mi)).any():
                return True
    return False


def _gpu_collide(field: "ParticleField", dt: float) -> None:
    """Dispatch the collide WGSL kernel; read back pos/vel/phase/impact_vel/rigidify_at."""
    n = int(field.pos.shape[0])
    if n == 0:
        return

    wgpu = _WGPU
    device = _DEVICE
    pipeline = _COLLIDE_PIPELINE

    pos_np = np.ascontiguousarray(field.pos, dtype=np.float32)
    vel_np = np.ascontiguousarray(field.vel, dtype=np.float32)
    phase_np = field.phase.astype(np.int32, copy=False)
    impact_vel_np = np.ascontiguousarray(field.impact_vel, dtype=np.float32)
    rigidify_np = field.rigidify_at.astype(np.int32, copy=False)
    kinetic_age_np = field.kinetic_age.astype(np.int32, copy=False)
    mid_np = np.ascontiguousarray(field.material_id, dtype=np.int32)
    # Mask alpha as flat u32 (H*W); alpha>0 = solid. u32 sidesteps the
    # texture-binding ceremony in wgpu-py while matching the CPU probe
    # ``self.mask[cy, cx, 3] > 0``.
    mask_alpha_np = np.ascontiguousarray(
        field.mask[..., 3].astype(np.uint32, copy=False).ravel())
    mat_props_np = _pack_collide_mat_props(field)

    pos_bytes = pos_np.nbytes
    vel_bytes = vel_np.nbytes
    phase_bytes = phase_np.nbytes
    impact_bytes = impact_vel_np.nbytes
    rigidify_bytes = rigidify_np.nbytes
    kinetic_bytes = kinetic_age_np.nbytes
    mid_bytes = mid_np.nbytes
    mask_bytes = mask_alpha_np.nbytes
    mat_bytes = mat_props_np.nbytes

    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST

    pos_buf = device.create_buffer(size=pos_bytes, usage=USAGE_RW, label="pfc_pos")
    vel_buf = device.create_buffer(size=vel_bytes, usage=USAGE_RW, label="pfc_vel")
    phase_buf = device.create_buffer(size=phase_bytes, usage=USAGE_RW, label="pfc_phase")
    impact_buf = device.create_buffer(size=impact_bytes, usage=USAGE_RW, label="pfc_impact")
    rigidify_buf = device.create_buffer(size=rigidify_bytes, usage=USAGE_RW, label="pfc_rigidify")
    kinetic_buf = device.create_buffer(size=kinetic_bytes, usage=USAGE_R, label="pfc_kinetic")
    mid_buf = device.create_buffer(size=mid_bytes, usage=USAGE_R, label="pfc_mid")
    mask_buf = device.create_buffer(size=mask_bytes, usage=USAGE_R, label="pfc_mask")
    mat_buf = device.create_buffer(size=mat_bytes, usage=USAGE_R, label="pfc_mat_props")

    device.queue.write_buffer(pos_buf, 0, pos_np)
    device.queue.write_buffer(vel_buf, 0, vel_np)
    device.queue.write_buffer(phase_buf, 0, phase_np)
    device.queue.write_buffer(impact_buf, 0, impact_vel_np)
    device.queue.write_buffer(rigidify_buf, 0, rigidify_np)
    device.queue.write_buffer(kinetic_buf, 0, kinetic_age_np)
    device.queue.write_buffer(mid_buf, 0, mid_np)
    device.queue.write_buffer(mask_buf, 0, mask_alpha_np)
    device.queue.write_buffer(mat_buf, 0, mat_props_np)

    # Params uniform: (dt: f32, n: u32, width: u32, height: u32).
    params_data = struct.pack(
        "fIII", float(dt), n, int(field.width), int(field.height))
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="pfc_params",
    )
    device.queue.write_buffer(
        params_buf, 0, np.frombuffer(params_data, dtype=np.uint8))

    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0, "resource": {"buffer": pos_buf,      "offset": 0, "size": pos_bytes}},
            {"binding": 1, "resource": {"buffer": vel_buf,      "offset": 0, "size": vel_bytes}},
            {"binding": 2, "resource": {"buffer": phase_buf,    "offset": 0, "size": phase_bytes}},
            {"binding": 3, "resource": {"buffer": impact_buf,   "offset": 0, "size": impact_bytes}},
            {"binding": 4, "resource": {"buffer": rigidify_buf, "offset": 0, "size": rigidify_bytes}},
            {"binding": 5, "resource": {"buffer": kinetic_buf,  "offset": 0, "size": kinetic_bytes}},
            {"binding": 6, "resource": {"buffer": mid_buf,      "offset": 0, "size": mid_bytes}},
            {"binding": 7, "resource": {"buffer": mask_buf,     "offset": 0, "size": mask_bytes}},
            {"binding": 8, "resource": {"buffer": mat_buf,      "offset": 0, "size": mat_bytes}},
            {"binding": 9, "resource": {"buffer": params_buf,   "offset": 0, "size": len(params_data)}},
        ],
    )

    encoder = device.create_command_encoder(label="pfc_collide")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_groups = max(1, (n + _WORKGROUP_SIZE - 1) // _WORKGROUP_SIZE)
    cp.dispatch_workgroups(n_groups)
    cp.end()
    device.queue.submit([encoder.finish()])

    pos_out = _readback(device, pos_buf, pos_bytes, dtype=np.float32).reshape(n, 2)
    vel_out = _readback(device, vel_buf, vel_bytes, dtype=np.float32).reshape(n, 2)
    phase_out = _readback(device, phase_buf, phase_bytes, dtype=np.int32)
    impact_out = _readback(device, impact_buf, impact_bytes, dtype=np.float32).reshape(n, 2)
    rigidify_out = _readback(device, rigidify_buf, rigidify_bytes, dtype=np.int32)

    # Write back into the SoA in place to preserve any external views.
    # ``phase`` is i8 on the CPU; downcast from the i32 the shader uses.
    field.pos[...] = pos_out
    field.vel[...] = vel_out
    field.impact_vel[...] = impact_out
    field.rigidify_at[...] = rigidify_out
    new_phase = phase_out.astype(np.int8, copy=False)

    # Mirror ``_set_phase`` for any particle whose phase changed:
    # ``phase_age`` resets to 0 and derived ``landed`` / ``settled`` /
    # ``bake_flag`` arrays stay consistent.
    changed = new_phase != field.phase
    if changed.any():
        field.phase[changed] = new_phase[changed]
        field.phase_age[changed] = 0
        # Phase ordering: LANDED=1, SETTLING=2, BAKED=3.
        field.landed[changed] = new_phase[changed] >= 1
        field.settled[changed] = new_phase[changed] >= 2
        field.bake_flag[changed] = new_phase[changed] == 3

    for buf in (
        pos_buf, vel_buf, phase_buf, impact_buf, rigidify_buf,
        kinetic_buf, mid_buf, mask_buf, mat_buf, params_buf,
    ):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass


def gpu_collide(field: "ParticleField", dt: float) -> None:
    """Run per-pixel collision for AIRBORNE particles.

    Drop-in replacement for ``ParticleField._collide(air_mask, dt)``
    where ``air_mask`` is ``self.phase == Phase.AIRBORNE``. Uses the
    WGSL compute kernel when wgpu is available; otherwise falls back
    to the CPU implementation.

    Note: the drill carve path (``mat.drill_max_px > 0``) is not
    implemented in this kernel. If any airborne particle is a drill
    material the whole call routes through the CPU for the frame —
    a dedicated drill compute kernel will land in a follow-up sprint.
    """
    if field.pos.shape[0] == 0:
        return
    if not _probe_gpu():
        _numpy_collide(field, dt)
        return
    if _any_active_drill(field):
        _numpy_collide(field, dt)
        return
    _gpu_collide(field, dt)


# ── Thermal step (GPU port of ParticleField._thermal_step) ────────────


def _pack_thermal_props(field: "ParticleField") -> np.ndarray:
    """Build the per-material thermal-props storage buffer.

    Each row mirrors the ``ThermalProps`` struct in
    ``particle_thermal.wgsl``: 48 B (vec4f scalars, vec4i ints,
    has_melt u32, has_freeze u32, pad u32 x2). With ~64 max
    registered materials the whole table is ~3 KB.

    ``melt_to_id`` / ``freeze_to_id`` default to ``-1`` when the
    profile has no target material; ``has_melt`` / ``has_freeze``
    are 0 when the profile has no threshold — this carries the CPU
    ``melt_at is None`` branch onto the GPU without a magic float.
    """
    n = len(field.materials)
    dtype = np.dtype([
        ("scalars",    np.float32, 4),
        ("ints",       np.int32,   4),
        ("has_melt",   np.uint32),
        ("has_freeze", np.uint32),
        ("_pad0",      np.uint32),
        ("_pad1",      np.uint32),
    ])
    assert dtype.itemsize == 48, (
        f"thermal_props row size {dtype.itemsize} != 48 B "
        "(WGSL struct layout drift)"
    )
    arr = np.zeros(n, dtype=dtype)
    name_to_id = field._name_to_id  # noqa: SLF001
    for i, mat in enumerate(field.materials):
        prof = mat.thermal
        melt_to_id = -1
        freeze_to_id = -1
        if prof.melt_to_material is not None:
            mt = name_to_id.get(prof.melt_to_material)
            if mt is not None:
                melt_to_id = int(mt)
        if prof.freeze_to_material is not None:
            ft = name_to_id.get(prof.freeze_to_material)
            if ft is not None:
                freeze_to_id = int(ft)
        r, g, b = (int(c) & 0xFF for c in mat.color)
        packed = (255 << 24) | (b << 16) | (g << 8) | r
        if packed >= (1 << 31):
            packed -= (1 << 32)
        arr[i]["scalars"] = (
            float(prof.ambient_temperature),
            float(prof.decay_per_sec),
            float(prof.melt_at)   if prof.melt_at   is not None else 0.0,
            float(prof.freeze_at) if prof.freeze_at is not None else 0.0,
        )
        arr[i]["ints"] = (melt_to_id, freeze_to_id, packed, 0)
        arr[i]["has_melt"]   = 1 if prof.melt_at   is not None else 0
        arr[i]["has_freeze"] = 1 if prof.freeze_at is not None else 0
    return arr


def _numpy_thermal_step(field: "ParticleField", dt: float) -> None:
    """Pure-numpy mimic of ``_thermal_step`` — fallback when wgpu is
    unavailable. Mirrors the CPU code so the parity test still passes.
    """
    from slappyengine.physics.thermal import (
        detect_phase_changes, step_temperatures,
    )
    if field.pos.shape[0] == 0:
        return
    profiles = [m.thermal for m in field.materials]
    if not any(
        p.decay_per_sec > 0.0 or p.melt_at is not None or p.freeze_at is not None
        for p in profiles
    ):
        return
    step_temperatures(field.temperature, field.material_id, profiles, dt)
    new_ids = detect_phase_changes(
        field.temperature, field.material_id, profiles, field._name_to_id,
    )
    changed = new_ids != field.material_id
    if changed.any():
        field.material_id[changed] = new_ids[changed]
        for i in np.nonzero(changed)[0]:
            new_mat = field.materials[int(new_ids[i])]
            field.color[i] = new_mat.color


def _gpu_thermal_step(field: "ParticleField", dt: float) -> None:
    """Dispatch the WGSL thermal kernel; read back temperature,
    material_id, color into the field's SoA.
    """
    n = int(field.pos.shape[0])
    if n == 0:
        return

    wgpu = _WGPU
    device = _DEVICE
    pipeline = _THERMAL_PIPELINE

    temp_np = np.ascontiguousarray(field.temperature, dtype=np.float32)
    mid_np  = np.ascontiguousarray(field.material_id, dtype=np.int32)
    color_rgb = np.ascontiguousarray(field.color, dtype=np.uint8)
    color_u32 = (
        (np.uint32(255) << 24)
        | (color_rgb[:, 2].astype(np.uint32) << 16)
        | (color_rgb[:, 1].astype(np.uint32) << 8)
        | color_rgb[:, 0].astype(np.uint32)
    )
    color_u32 = np.ascontiguousarray(color_u32, dtype=np.uint32)
    props_np = _pack_thermal_props(field)

    temp_bytes  = temp_np.nbytes
    mid_bytes   = mid_np.nbytes
    color_bytes = color_u32.nbytes
    props_bytes = props_np.nbytes

    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST

    temp_buf  = device.create_buffer(size=temp_bytes,  usage=USAGE_RW, label="pf_temp")
    mid_buf   = device.create_buffer(size=mid_bytes,   usage=USAGE_RW, label="pf_mid_t")
    color_buf = device.create_buffer(size=color_bytes, usage=USAGE_RW, label="pf_color")
    props_buf = device.create_buffer(size=props_bytes, usage=USAGE_R,  label="pf_thermal_props")

    device.queue.write_buffer(temp_buf,  0, temp_np)
    device.queue.write_buffer(mid_buf,   0, mid_np)
    device.queue.write_buffer(color_buf, 0, color_u32)
    device.queue.write_buffer(props_buf, 0, props_np.tobytes())

    params_data = struct.pack("fIII", float(dt), n, 0, 0)
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="pf_thermal_params",
    )
    device.queue.write_buffer(
        params_buf, 0, np.frombuffer(params_data, dtype=np.uint8),
    )

    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0, "resource": {"buffer": temp_buf,   "offset": 0, "size": temp_bytes}},
            {"binding": 1, "resource": {"buffer": mid_buf,    "offset": 0, "size": mid_bytes}},
            {"binding": 2, "resource": {"buffer": color_buf,  "offset": 0, "size": color_bytes}},
            {"binding": 3, "resource": {"buffer": props_buf,  "offset": 0, "size": props_bytes}},
            {"binding": 4, "resource": {"buffer": params_buf, "offset": 0, "size": len(params_data)}},
        ],
    )

    encoder = device.create_command_encoder(label="pf_thermal")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_groups = max(1, (n + _WORKGROUP_SIZE - 1) // _WORKGROUP_SIZE)
    cp.dispatch_workgroups(n_groups)
    cp.end()
    device.queue.submit([encoder.finish()])

    temp_out  = _readback(device, temp_buf,  temp_bytes,  dtype=np.float32)
    mid_out   = _readback(device, mid_buf,   mid_bytes,   dtype=np.int32)
    color_out = _readback(device, color_buf, color_bytes, dtype=np.uint32)

    field.temperature[...] = temp_out
    field.material_id[...] = mid_out
    field.color[:, 0] = (color_out & 0xFF).astype(np.uint8)
    field.color[:, 1] = ((color_out >> 8) & 0xFF).astype(np.uint8)
    field.color[:, 2] = ((color_out >> 16) & 0xFF).astype(np.uint8)

    for buf in (temp_buf, mid_buf, color_buf, props_buf, params_buf):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass


def gpu_thermal_step(field: "ParticleField", dt: float) -> None:
    """Advance per-particle temperature + phase changes by ``dt``.

    Drop-in replacement for ``ParticleField._thermal_step(dt)``.
    Uses a WGSL compute shader if wgpu is available; otherwise
    falls back to a numpy mimic of the CPU path.
    """
    if field.pos.shape[0] == 0:
        return
    profiles = [m.thermal for m in field.materials]
    if not any(
        p.decay_per_sec > 0.0 or p.melt_at is not None or p.freeze_at is not None
        for p in profiles
    ):
        return
    if _probe_gpu():
        _gpu_thermal_step(field, dt)
    else:
        _numpy_thermal_step(field, dt)


# ──────────────────────────────────────────────────────────────────────
# Slide GPU port (column_top + per-particle slide)
# ──────────────────────────────────────────────────────────────────────


def _pack_slide_mat_props(field: "ParticleField") -> np.ndarray:
    """Per-material (friction, settle_threshold, settle_jitter, tumble_kick)
    → vec4<f32> array. Mirrors ``mat_props`` binding 5 of particle_slide.wgsl.
    """
    n = len(field.materials)
    arr = np.empty((n, 4), dtype=np.float32)
    for i, mat in enumerate(field.materials):
        arr[i, 0] = float(mat.friction_per_sec)
        arr[i, 1] = float(mat.settle_speed_threshold)
        arr[i, 2] = float(mat.settle_jitter)
        arr[i, 3] = float(mat.tumble_kick)
    return arr


# PCG32 advance — keep in lock-step with the WGSL pcg32() helper. Returns
# (uniform_in_0_1, new_state). Used only by the numpy fallback.

def _pcg32_step(state) -> "tuple[float, np.uint32]":
    s = np.uint32(state)
    new_state = np.uint32(s * np.uint32(747796405) + np.uint32(2891336453))
    shift = np.uint32((s >> np.uint32(28)) + np.uint32(4))
    word = np.uint32(((s >> shift) ^ s) * np.uint32(277803737))
    word = np.uint32((word >> np.uint32(22)) ^ word)
    u01 = float(word >> np.uint32(8)) * (1.0 / 16777216.0)
    return u01, new_state


def _compute_column_top_cpu(field: "ParticleField") -> np.ndarray:
    """Vectorised mirror of ParticleField._column_top across all columns.
    Returns (W,) i32 — the y of the topmost solid pixel per column, or
    H if the column is empty. O(H*W) numpy reduction.
    """
    H, W = field.mask.shape[:2]
    solid = field.mask[..., 3] > 0          # (H, W) bool
    any_solid = solid.any(axis=0)           # (W,)
    # argmax returns 0 for all-False columns; fix those to H below.
    first_solid = solid.argmax(axis=0).astype(np.int32)
    first_solid[~any_solid] = np.int32(H)
    return first_solid


def gpu_column_top(field: "ParticleField") -> np.ndarray:
    """Compute the per-column topmost-solid-y buffer.

    Returns an ``(W,) int32`` numpy array; values equal to
    ``field.height`` indicate empty columns. Used as the precomputed
    lookup for :func:`gpu_slide`. CPU fallback is an O(H*W) numpy
    reduction; the GPU path runs ``particle_column_top.wgsl`` with
    one thread per column.
    """
    if _probe_gpu():
        return _gpu_column_top(field)
    return _compute_column_top_cpu(field)


def _gpu_column_top(field: "ParticleField") -> np.ndarray:
    wgpu = _WGPU
    device = _DEVICE
    pipeline = _COLUMN_TOP_PIPELINE
    H, W = field.mask.shape[:2]

    # Pack mask alpha into a flat u32 buffer (one cell per pixel; 0 or 1).
    alpha = (field.mask[..., 3] > 0).astype(np.uint32).reshape(-1)
    alpha = np.ascontiguousarray(alpha, dtype=np.uint32)
    col_top_init = np.full(W, H, dtype=np.int32)

    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST
    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    alpha_buf = device.create_buffer(
        size=alpha.nbytes, usage=USAGE_R, label="pf_alpha")
    col_top_buf = device.create_buffer(
        size=col_top_init.nbytes, usage=USAGE_RW, label="pf_col_top")
    device.queue.write_buffer(alpha_buf, 0, alpha)
    device.queue.write_buffer(col_top_buf, 0, col_top_init)

    params_data = struct.pack("IIII", W, H, 0, 0)
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="pf_col_top_params",
    )
    device.queue.write_buffer(
        params_buf, 0, np.frombuffer(params_data, dtype=np.uint8))

    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0, "resource": {"buffer": alpha_buf,   "offset": 0, "size": alpha.nbytes}},
            {"binding": 1, "resource": {"buffer": col_top_buf, "offset": 0, "size": col_top_init.nbytes}},
            {"binding": 2, "resource": {"buffer": params_buf,  "offset": 0, "size": len(params_data)}},
        ],
    )
    encoder = device.create_command_encoder(label="pf_col_top")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_groups = max(1, (W + _WORKGROUP_SIZE - 1) // _WORKGROUP_SIZE)
    cp.dispatch_workgroups(n_groups)
    cp.end()
    device.queue.submit([encoder.finish()])

    out = _readback(device, col_top_buf, col_top_init.nbytes, dtype=np.int32)
    for buf in (alpha_buf, col_top_buf, params_buf):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass
    return out


def _phase_enum_slide(value: int):
    # Local helper — avoid a top-level import cycle.
    from slappyengine.physics.particle_field import Phase
    return Phase(value)


def _numpy_slide(field: "ParticleField", dt: float) -> None:
    """Pure-numpy port of ParticleField._slide that mirrors the GPU
    PCG32-per-particle RNG strategy. Used when wgpu is unavailable so
    the call sites can target ``gpu_slide`` regardless of backend.

    The CPU reference (``ParticleField._slide``) uses ``self._rng`` for
    jitter. This fallback uses the per-particle PCG state instead so
    the GPU-off branch matches the GPU branch (not the legacy CPU).
    """
    n = field.pos.shape[0]
    if n == 0:
        return
    slide_mask = field.landed & ~field.settled
    if not slide_mask.any():
        return
    H, W = field.mask.shape[:2]
    col_top = _compute_column_top_cpu(field)
    rng_state = field.rng_state

    # Per-material friction + vy=0 + pos.x advance (vectorised).
    for mi, mat in enumerate(field.materials):
        m = slide_mask & (field.material_id == mi)
        if not m.any():
            continue
        field.vel[m, 0] *= np.float32(mat.friction_per_sec) ** np.float32(dt)
        field.vel[m, 1] = np.float32(0.0)
    field.pos[slide_mask, 0] += field.vel[slide_mask, 0] * np.float32(dt)

    # Per-particle loop — mirror of WGSL slide main().
    for i in np.nonzero(slide_mask)[0]:
        mat = field.materials[int(field.material_id[i])]
        settle_thresh = float(mat.settle_speed_threshold)
        settle_jit = float(mat.settle_jitter)
        tumble = float(mat.tumble_kick)

        vx = float(field.vel[i, 0])
        vy = 0.0
        px = float(field.pos[i, 0])
        py = float(field.pos[i, 1])

        state = np.uint32(rng_state[i])

        xi = int(px)
        if 0 <= xi < W:
            top = int(col_top[xi])
            y_cur = int(py)
            if y_cur >= top:
                y_cur = max(0, top - 1)

            my_top = y_cur
            best_left = 0
            best_right = 0
            for d in range(1, 6):
                cxl = xi - d
                if 0 <= cxl < W:
                    dl = int(col_top[cxl]) - my_top
                    if dl > best_left:
                        best_left = dl
                cxr = xi + d
                if 0 <= cxr < W:
                    dr = int(col_top[cxr]) - my_top
                    if dr > best_right:
                        best_right = dr
            fast_thresh = max(20.0, settle_thresh * 2.0)
            is_fast = abs(vx) > fast_thresh
            step = 2 if is_fast else 4
            if best_left >= step or best_right >= step:
                if best_left > best_right:
                    direction = -1
                elif best_right > best_left:
                    direction = 1
                else:
                    u, state = _pcg32_step(state)
                    direction = -1 if u < 0.5 else 1
                new_x = max(0, min(W - 1, xi + direction))
                new_y = max(0, int(col_top[new_x]) - 1)
                px = float(new_x)
                py = float(new_y)
            else:
                py = float(y_cur)

        new_phase = int(field.phase[i])  # stays LANDED unless we change it
        if tumble > 0.0 and abs(vx) > 5.0:
            u, state = _pcg32_step(state)
            scale = 0.3 + 0.7 * u
            kick = tumble * abs(vx) * scale
            vy = -kick
            new_phase = 0  # AIRBORNE

        threshold = settle_thresh
        if settle_jit > 0.0:
            u, state = _pcg32_step(state)
            j = -settle_jit + 2.0 * settle_jit * u
            threshold = settle_thresh * (1.0 + j)
        if abs(vx) < threshold:
            new_phase = 2  # SETTLING
            vx = 0.0

        field.pos[i, 0] = np.float32(px)
        field.pos[i, 1] = np.float32(py)
        field.vel[i, 0] = np.float32(vx)
        field.vel[i, 1] = np.float32(vy)
        if new_phase != int(field.phase[i]):
            field._set_phase(int(i), _phase_enum_slide(new_phase))
        rng_state[i] = state


def _gpu_slide(field: "ParticleField", dt: float, col_top: np.ndarray) -> None:
    wgpu = _WGPU
    device = _DEVICE
    pipeline = _SLIDE_PIPELINE

    n = int(field.pos.shape[0])
    if n == 0:
        return
    H, W = field.mask.shape[:2]

    pos_np = np.ascontiguousarray(field.pos, dtype=np.float32)
    vel_np = np.ascontiguousarray(field.vel, dtype=np.float32)
    phase_np = field.phase.astype(np.int32, copy=True)
    mid_np = np.ascontiguousarray(field.material_id, dtype=np.int32)
    col_top_np = np.ascontiguousarray(col_top, dtype=np.int32)
    mat_props_np = _pack_slide_mat_props(field)
    rng_np = np.ascontiguousarray(field.rng_state, dtype=np.uint32)

    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST

    pos_buf = device.create_buffer(size=pos_np.nbytes, usage=USAGE_RW, label="pf_slide_pos")
    vel_buf = device.create_buffer(size=vel_np.nbytes, usage=USAGE_RW, label="pf_slide_vel")
    phase_buf = device.create_buffer(size=phase_np.nbytes, usage=USAGE_RW, label="pf_slide_phase")
    mid_buf = device.create_buffer(size=mid_np.nbytes, usage=USAGE_R, label="pf_slide_mid")
    col_top_buf = device.create_buffer(size=col_top_np.nbytes, usage=USAGE_R, label="pf_slide_coltop")
    mat_buf = device.create_buffer(size=mat_props_np.nbytes, usage=USAGE_R, label="pf_slide_mat")
    rng_buf = device.create_buffer(size=rng_np.nbytes, usage=USAGE_RW, label="pf_slide_rng")

    device.queue.write_buffer(pos_buf, 0, pos_np)
    device.queue.write_buffer(vel_buf, 0, vel_np)
    device.queue.write_buffer(phase_buf, 0, phase_np)
    device.queue.write_buffer(mid_buf, 0, mid_np)
    device.queue.write_buffer(col_top_buf, 0, col_top_np)
    device.queue.write_buffer(mat_buf, 0, mat_props_np)
    device.queue.write_buffer(rng_buf, 0, rng_np)

    params_data = struct.pack("fIII", float(dt), n, W, H)
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="pf_slide_params",
    )
    device.queue.write_buffer(
        params_buf, 0, np.frombuffer(params_data, dtype=np.uint8))

    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0, "resource": {"buffer": pos_buf,    "offset": 0, "size": pos_np.nbytes}},
            {"binding": 1, "resource": {"buffer": vel_buf,    "offset": 0, "size": vel_np.nbytes}},
            {"binding": 2, "resource": {"buffer": phase_buf,  "offset": 0, "size": phase_np.nbytes}},
            {"binding": 3, "resource": {"buffer": mid_buf,    "offset": 0, "size": mid_np.nbytes}},
            {"binding": 4, "resource": {"buffer": col_top_buf,"offset": 0, "size": col_top_np.nbytes}},
            {"binding": 5, "resource": {"buffer": mat_buf,    "offset": 0, "size": mat_props_np.nbytes}},
            {"binding": 6, "resource": {"buffer": rng_buf,    "offset": 0, "size": rng_np.nbytes}},
            {"binding": 7, "resource": {"buffer": params_buf, "offset": 0, "size": len(params_data)}},
        ],
    )

    encoder = device.create_command_encoder(label="pf_slide")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_groups = max(1, (n + _WORKGROUP_SIZE - 1) // _WORKGROUP_SIZE)
    cp.dispatch_workgroups(n_groups)
    cp.end()
    device.queue.submit([encoder.finish()])

    pos_out = _readback(device, pos_buf, pos_np.nbytes, dtype=np.float32).reshape(n, 2)
    vel_out = _readback(device, vel_buf, vel_np.nbytes, dtype=np.float32).reshape(n, 2)
    phase_out = _readback(device, phase_buf, phase_np.nbytes, dtype=np.int32)
    rng_out = _readback(device, rng_buf, rng_np.nbytes, dtype=np.uint32)

    field.pos[...] = pos_out
    field.vel[...] = vel_out
    field.rng_state[...] = rng_out

    # Phase changes need to drive the derived bool arrays. Walk only
    # the indices whose phase actually changed.
    old_phase = field.phase.astype(np.int32, copy=False)
    changed = np.nonzero(phase_out != old_phase)[0]
    if changed.size:
        for idx in changed:
            field._set_phase(int(idx), _phase_enum_slide(int(phase_out[idx])))

    for buf in (pos_buf, vel_buf, phase_buf, mid_buf,
                col_top_buf, mat_buf, rng_buf, params_buf):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass


def gpu_slide(field: "ParticleField", dt: float) -> None:
    """Advance LANDED particles' slide step on the GPU.

    Drop-in replacement for ``ParticleField._slide(slide_mask, dt)``.
    Internally calls :func:`gpu_column_top` first so the slide kernel
    can read pre-baked column-top values instead of re-scanning the
    mask per particle. Falls back to a pure-numpy mimic that uses the
    same per-particle PCG32 state when the GPU is unavailable.

    Note on RNG: the per-particle ``rng_state`` is advanced by this
    call. CPU ``_slide`` uses the shared ``field._rng`` instead, so
    bit-identical CPU/GPU parity is not expected — tests should allow
    a small tolerance (≈1 px on pos, ≈2 px/s on vel) driven by the
    different jitter draws.
    """
    if field.pos.shape[0] == 0:
        return
    if _probe_gpu():
        col_top = _gpu_column_top(field)
        _gpu_slide(field, dt, col_top)
    else:
        _numpy_slide(field, dt)


# ──────────────────────────────────────────────────────────────────────
# Isolated-pixel detach GPU port
# ──────────────────────────────────────────────────────────────────────
#
# GPU port of the vectorised "isolated-pixel detach" pass inside
# ``ParticleField._drill_through`` (see particle_field.py). The CPU
# reference scans only a small window around the drill impact site —
# the GPU port generalises it to the WHOLE mask, suitable for use as a
# periodic cleanup sweep that catches dangling pixels produced by
# slumps, multiple bullets, bake conflicts, etc.
#
# Per pixel (8x8 workgroups):
#   1. Skip if alpha == 0 or fixed_mask is set.
#   2. Count 4-neighbour solid pixels (border treated as 0).
#   3. Skip pixels on the 1-pixel canvas border (matches the CPU
#      window inset which excludes them).
#   4. If neighbour count is 0: atomically reserve a slot, write
#      (pos, packed colour, material id).
#
# CPU side then clears the mask + spawns particles via
# ``field.spawn_batch``. The split exists because spawn_batch is a
# Python operation that grows the SoA — there is no benefit to also
# pushing the mask write to the GPU when a readback is required
# anyway.
#
# Memory cost
# -----------
# MAX_DETACH_PER_DISPATCH controls the worst-case dispatch buffer
# size. At MAX_DETACH=65536:
#   * detach_pos   : 65536 * 2 * 4 B = 512 KB
#   * detach_color : 65536     * 4 B = 256 KB
#   * detach_mid   : 65536     * 4 B = 256 KB
#   Sum ≈ 1.0 MB GPU + 1.0 MB readback staging. Counter is 4 bytes.
# Real workloads almost never produce more than a few thousand
# isolated pixels per cleanup sweep — the cap is sized so a 4K mask
# with severe fragmentation still has room.

_DETACH_SHADER_PATH = _SHADER_DIR / "particle_detach.wgsl"
_DETACH_WORKGROUP_X = 8
_DETACH_WORKGROUP_Y = 8
MAX_DETACH_PER_DISPATCH = 65536

_DETACH_GPU_PROBED = False
_DETACH_GPU_AVAILABLE = False
_DETACH_PIPELINE = None  # type: ignore[var-annotated]


def _probe_detach_gpu() -> bool:
    """One-shot adapter + device + pipeline probe for the detach pass.

    Reuses the main ``_probe_gpu()`` device / queue so we don't open a
    second wgpu device per process. The pipeline is built lazily on
    the first call.
    """
    global _DETACH_GPU_PROBED, _DETACH_GPU_AVAILABLE, _DETACH_PIPELINE
    if _DETACH_GPU_PROBED:
        return _DETACH_GPU_AVAILABLE
    _DETACH_GPU_PROBED = True

    if not _probe_gpu():
        return False
    device = _DEVICE
    try:
        src = _DETACH_SHADER_PATH.read_text(encoding="utf-8")
        module = device.create_shader_module(code=src, label="particle_detach")
        pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": module, "entry_point": "main"},
            label="particle_detach_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu: detach pipeline build failed ({exc!r}); "
            "using numpy fallback.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    _DETACH_PIPELINE = pipeline
    _DETACH_GPU_AVAILABLE = True
    return True


def _pack_mask_to_u32_detach(mask: np.ndarray) -> np.ndarray:
    """(H, W, 4) uint8 → (H*W,) uint32 — same layout as the drill kernel."""
    flat = mask.reshape(-1, 4).astype(np.uint32)
    return (flat[:, 0]
            | (flat[:, 1] << 8)
            | (flat[:, 2] << 16)
            | (flat[:, 3] << 24))


def _numpy_detach_isolated_pixels(
    field: "ParticleField",
) -> list[tuple[int, int]]:
    """Pure-numpy mirror of the GPU pass.

    Returns the sorted list of (y, x) coords of the detached pixels,
    same as the GPU path returns (after sorting). Used by the GPU path
    as a fallback when wgpu is unavailable, and by the parity test.

    Mutates ``field.mask`` / ``field.loose`` and calls
    ``field.spawn_batch`` — bit-identical to the bottom of
    ``_drill_through``'s detach branch but applied to the whole grid
    (with the 1-pixel canvas inset).
    """
    H, W = field.mask.shape[:2]
    if H < 3 or W < 3:
        return []
    # Inset by 1 pixel so the 4-neighbour shift never touches OOB —
    # matches the CPU window in _drill_through.
    win = field.mask[..., 3] > 0
    inner = win[1:-1, 1:-1]
    nb = (win[:-2, 1:-1].astype(np.int8)
          + win[2:,   1:-1].astype(np.int8)
          + win[1:-1, :-2 ].astype(np.int8)
          + win[1:-1, 2:  ].astype(np.int8))
    fixed = field._fixed_mask[1:-1, 1:-1]
    isolated = inner & (nb == 0) & ~fixed
    if not isolated.any():
        return []
    ys_inner, xs_inner = np.where(isolated)
    ys = ys_inner + 1
    xs = xs_inner + 1
    n_det = ys.size
    detach_pos = np.column_stack([xs, ys]).astype(np.float32)
    detach_cols = field.mask[ys, xs, :3].copy()
    detach_mids = field.material_grid[ys, xs].astype(np.int32)
    fallback_mid = 0
    detach_mids[detach_mids < 0] = fallback_mid
    field.mask[ys, xs, 3] = 0
    field.loose[ys, xs] = False
    field.spawn_batch(
        pos=detach_pos,
        vel=np.zeros((n_det, 2), dtype=np.float32),
        material_ids=detach_mids,
        radii=np.zeros(n_det, dtype=np.float32),
        colors=detach_cols,
    )
    coords = sorted(zip(ys.tolist(), xs.tolist()))
    return coords


def _gpu_detach_isolated_pixels(
    field: "ParticleField",
) -> list[tuple[int, int]]:
    """Dispatch the WGSL detach kernel and apply mask clear + spawn_batch."""
    H, W = field.mask.shape[:2]
    if H < 3 or W < 3:
        return []

    wgpu = _WGPU
    device = _DEVICE
    pipeline = _DETACH_PIPELINE

    mask_packed = _pack_mask_to_u32_detach(field.mask)
    mat_grid_np = field.material_grid.astype(np.int32).ravel()
    fixed_np = field._fixed_mask.astype(np.uint32).ravel()

    detach_pos_zero = np.zeros((MAX_DETACH_PER_DISPATCH, 2), dtype=np.float32)
    detach_color_zero = np.zeros(MAX_DETACH_PER_DISPATCH, dtype=np.uint32)
    detach_mid_zero = np.zeros(MAX_DETACH_PER_DISPATCH, dtype=np.int32)
    counter_zero = np.zeros(1, dtype=np.uint32)

    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST

    def _mkbuf(data: np.ndarray, label: str, rw: bool = False):
        usage = USAGE_RW if rw else USAGE_R
        buf = device.create_buffer(size=data.nbytes, usage=usage, label=label)
        device.queue.write_buffer(buf, 0, np.ascontiguousarray(data))
        return buf

    mask_buf    = _mkbuf(mask_packed,       "pf_detach_mask",    rw=False)
    mgrid_buf   = _mkbuf(mat_grid_np,       "pf_detach_mgrid",   rw=False)
    fixed_buf   = _mkbuf(fixed_np,          "pf_detach_fixed",   rw=False)
    counter_buf = _mkbuf(counter_zero,      "pf_detach_counter", rw=True)
    pos_buf     = _mkbuf(detach_pos_zero,   "pf_detach_pos",     rw=True)
    color_buf   = _mkbuf(detach_color_zero, "pf_detach_color",   rw=True)
    mid_buf     = _mkbuf(detach_mid_zero,   "pf_detach_mid",     rw=True)

    # ── Params uniform: width, height, max_detach (u32), fallback_mid (i32) ──
    fallback_mid = 0
    params_data = struct.pack(
        "IIIi", W, H, MAX_DETACH_PER_DISPATCH, fallback_mid)
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="pf_detach_params",
    )
    device.queue.write_buffer(
        params_buf, 0, np.frombuffer(params_data, dtype=np.uint8))

    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0, "resource": {"buffer": mask_buf,    "offset": 0, "size": mask_packed.nbytes}},
            {"binding": 1, "resource": {"buffer": mgrid_buf,   "offset": 0, "size": mat_grid_np.nbytes}},
            {"binding": 2, "resource": {"buffer": fixed_buf,   "offset": 0, "size": fixed_np.nbytes}},
            {"binding": 3, "resource": {"buffer": counter_buf, "offset": 0, "size": counter_zero.nbytes}},
            {"binding": 4, "resource": {"buffer": pos_buf,     "offset": 0, "size": detach_pos_zero.nbytes}},
            {"binding": 5, "resource": {"buffer": color_buf,   "offset": 0, "size": detach_color_zero.nbytes}},
            {"binding": 6, "resource": {"buffer": mid_buf,     "offset": 0, "size": detach_mid_zero.nbytes}},
            {"binding": 7, "resource": {"buffer": params_buf,  "offset": 0, "size": len(params_data)}},
        ],
    )

    encoder = device.create_command_encoder(label="pf_detach_dispatch")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_gx = max(1, (W + _DETACH_WORKGROUP_X - 1) // _DETACH_WORKGROUP_X)
    n_gy = max(1, (H + _DETACH_WORKGROUP_Y - 1) // _DETACH_WORKGROUP_Y)
    cp.dispatch_workgroups(n_gx, n_gy)
    cp.end()
    device.queue.submit([encoder.finish()])

    counter_out = _readback(
        device, counter_buf, counter_zero.nbytes, np.uint32)
    n_det = int(counter_out[0])
    if n_det > MAX_DETACH_PER_DISPATCH:
        warnings.warn(
            f"particle_gpu: detach overflow — kernel wanted {n_det} "
            f"detached pixels but max_detach={MAX_DETACH_PER_DISPATCH}; "
            f"keeping the first {MAX_DETACH_PER_DISPATCH}.",
            RuntimeWarning,
            stacklevel=2,
        )
        n_det = MAX_DETACH_PER_DISPATCH

    coords: list[tuple[int, int]] = []
    if n_det > 0:
        pos_out = _readback(
            device, pos_buf,
            n_det * 2 * 4,
            np.float32,
        ).reshape(n_det, 2)
        color_out = _readback(
            device, color_buf, n_det * 4, np.uint32)
        mid_out = _readback(
            device, mid_buf, n_det * 4, np.int32)
        xs = pos_out[:, 0].astype(np.int32)
        ys = pos_out[:, 1].astype(np.int32)
        # Decode packed rgba8 back to (N, 3) uint8.
        r = (color_out & 0xFF).astype(np.uint8)
        g = ((color_out >> 8) & 0xFF).astype(np.uint8)
        b = ((color_out >> 16) & 0xFF).astype(np.uint8)
        detach_cols = np.column_stack([r, g, b])
        detach_pos = np.column_stack([xs, ys]).astype(np.float32)
        # Clear the mask + loose on CPU — cheap vectorised numpy op.
        field.mask[ys, xs, 3] = 0
        field.loose[ys, xs] = False
        field.spawn_batch(
            pos=detach_pos,
            vel=np.zeros((n_det, 2), dtype=np.float32),
            material_ids=mid_out.astype(np.int32),
            radii=np.zeros(n_det, dtype=np.float32),
            colors=detach_cols,
        )
        coords = sorted(zip(ys.tolist(), xs.tolist()))

    for buf in (mask_buf, mgrid_buf, fixed_buf, counter_buf,
                pos_buf, color_buf, mid_buf, params_buf):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass

    return coords


def gpu_detach_isolated_pixels(
    field: "ParticleField",
    scan_region: tuple[int, int, int, int] | None = None,
) -> list[tuple[int, int]]:
    """Scan the mask for isolated solid pixels and detach them.

    Drop-in for the local detach pass at the bottom of
    ``ParticleField._drill_through``, scaled to the whole mask. Uses
    a WGSL compute shader when wgpu is available; falls back to a
    pure-numpy mimic with bit-identical behaviour.

    Parameters
    ----------
    field
        The :class:`ParticleField` to scan + mutate.
    scan_region
        Optional ``(x_lo, y_lo, x_hi, y_hi)`` bounding box. Currently
        accepted for API symmetry but not used to gate the dispatch
        — the kernel runs on the whole mask. Reserved for a future
        sub-region optimisation.

    Returns
    -------
    list[tuple[int, int]]
        Sorted ``(y, x)`` coords of the detached pixels (useful for
        the parity test; the field has already been mutated).
    """
    if field.mask.shape[0] < 3 or field.mask.shape[1] < 3:
        return []
    _ = scan_region  # placeholder for future sub-region optimisation
    if _probe_detach_gpu():
        return _gpu_detach_isolated_pixels(field)
    return _numpy_detach_isolated_pixels(field)


def is_gpu_detach_available() -> bool:
    """Probe (cached) whether the GPU detach path is active."""
    return _probe_detach_gpu()


# ──────────────────────────────────────────────────────────────────────
# Slump-loose GPU port
# ──────────────────────────────────────────────────────────────────────
#
# Mirrors ``ParticleField._slump_loose`` — a per-pixel cellular automaton
# on the ``loose`` mask. Two passes: pass 0 = vertical fall, pass 1 =
# sideways slump. Pull semantics on a ping-pong (mask_in, mask_out) +
# (loose_in, loose_out) + (rng_in, rng_out) so no atomics are needed.
#
# Ping-pong implementation: 2 passes, no atomics. Each thread owns
# exactly one output pixel and reads from the previous-pass storage
# buffers. This sidesteps the race condition that arises when two
# source pixels both want to flow into the same destination — the
# destination thread resolves the conflict locally by re-evaluating
# both neighbours' decisions and tie-breaking against its own
# rng_in slot.
#
# Memory cost of the per-pixel rng_state buffer
# ----------------------------------------------
# Per pixel: 4 bytes (u32 PCG32 state). The buffer is persistent across
# frames so the same pixel re-uses its seed (cached on the field as
# ``_slump_rng_state``):
#
#   256 x 256   →   256 KB
#   512 x 512   →     1 MB
#  1024 x 1024  →     4 MB
#  1920 x 1080  →   ~8 MB
#
# At 1080p we pay ~8 MB of VRAM for the persistent rng_state. The cost
# is bounded by the field's pixel count and amortises over every frame
# (one allocation, mutated in place). For very large fields the buffer
# can be swapped to a smaller-state LCG if 8 MB becomes a concern.


def _compute_slump_probs_cpu(field: "ParticleField") -> "tuple[float, float]":
    """Mirror the CPU heuristic: pick the LEAST cohesive material
    currently represented in the settled set and derive fall + side
    probabilities from it. Returns ``(fall_prob, side_prob)``; both
    zero if there's nothing to slump.
    """
    if not field.loose.any():
        return (0.0, 0.0)
    if not field.settled.any():
        return (0.0, 0.0)
    cohs = np.array(
        [field.materials[int(field.material_id[i])].cohesion
         for i in np.nonzero(field.settled)[0]],
        dtype=np.float32,
    )
    min_coh = float(cohs.min())
    if min_coh >= 1.0:
        return (0.0, 0.0)
    fall_prob = (1.0 - min_coh) * 0.08
    side_prob = fall_prob * 0.4
    if fall_prob <= 0.0:
        return (0.0, 0.0)
    return (fall_prob, side_prob)


def _ensure_slump_rng(field: "ParticleField") -> np.ndarray:
    """Lazy-allocate a ``(H*W,) u32`` array of per-pixel PCG32 seeds.

    Stored on the field as ``_slump_rng_state`` so the same buffer is
    reused frame-to-frame (advancing one PCG step per pass per pixel).
    Seeded from ``field._rng`` so test runs that pin the field RNG
    also pin the slump RNG.
    """
    cached = getattr(field, "_slump_rng_state", None)
    expected_size = field.height * field.width
    if cached is None or cached.size != expected_size:
        # ``integers(low=1, ...)`` avoids 0 (degenerate PCG state).
        seeds = field._rng.integers(  # noqa: SLF001
            1, 2**32, size=expected_size, dtype=np.uint32,
        ).astype(np.uint32)
        field._slump_rng_state = seeds  # type: ignore[attr-defined]
        cached = seeds
    return cached


def _numpy_slump_loose(field: "ParticleField", dt: float) -> None:
    """Pure-numpy fallback — defer to the CPU implementation so tests
    that opt into the GPU path still get the same observable behaviour
    when wgpu is unavailable.
    """
    field._slump_loose(dt)  # noqa: SLF001


def _gpu_slump_loose(field: "ParticleField", dt: float) -> None:
    """Dispatch the slump WGSL kernel twice (fall pass + slump pass)
    with a ping-ponged (mask, loose, rng) triple. Reads back the final
    mask + loose into the field's arrays.
    """
    fall_prob, side_prob = _compute_slump_probs_cpu(field)
    if fall_prob <= 0.0:
        return

    wgpu = _WGPU
    device = _DEVICE
    pipeline = _SLUMP_PIPELINE

    H, W = field.mask.shape[:2]

    # Pack the RGBA8 mask into one u32 per pixel (little-endian: r,g,b,a).
    mask_u32 = (
        field.mask[..., 0].astype(np.uint32)
        | (field.mask[..., 1].astype(np.uint32) << 8)
        | (field.mask[..., 2].astype(np.uint32) << 16)
        | (field.mask[..., 3].astype(np.uint32) << 24)
    ).reshape(-1)
    mask_u32 = np.ascontiguousarray(mask_u32, dtype=np.uint32)

    loose_u32 = np.ascontiguousarray(
        field.loose.astype(np.uint32).reshape(-1), dtype=np.uint32)
    fixed_u32 = np.ascontiguousarray(
        field._fixed_mask.astype(np.uint32).reshape(-1),  # noqa: SLF001
        dtype=np.uint32)

    rng_state = _ensure_slump_rng(field)
    rng_u32 = np.ascontiguousarray(rng_state, dtype=np.uint32)

    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST

    mask_a = device.create_buffer(
        size=mask_u32.nbytes, usage=USAGE_RW, label="slump_mask_a")
    mask_b = device.create_buffer(
        size=mask_u32.nbytes, usage=USAGE_RW, label="slump_mask_b")
    loose_a = device.create_buffer(
        size=loose_u32.nbytes, usage=USAGE_RW, label="slump_loose_a")
    loose_b = device.create_buffer(
        size=loose_u32.nbytes, usage=USAGE_RW, label="slump_loose_b")
    rng_a = device.create_buffer(
        size=rng_u32.nbytes, usage=USAGE_RW, label="slump_rng_a")
    rng_b = device.create_buffer(
        size=rng_u32.nbytes, usage=USAGE_RW, label="slump_rng_b")
    fixed_buf = device.create_buffer(
        size=fixed_u32.nbytes, usage=USAGE_R, label="slump_fixed")

    device.queue.write_buffer(mask_a, 0, mask_u32)
    device.queue.write_buffer(loose_a, 0, loose_u32)
    device.queue.write_buffer(rng_a, 0, rng_u32)
    device.queue.write_buffer(fixed_buf, 0, fixed_u32)

    # The CPU loop is ``range(H-2, 0, -1)`` so y == 0 is never touched.
    # Mirror that with protect_y_above = 1 (rows 0..0 are protected).
    protect_y_above = 1

    def _dispatch(pass_kind, src_mask, dst_mask, src_loose, dst_loose,
                  src_rng, dst_rng):
        params_data = struct.pack(
            "fffIIIII",
            float(fall_prob),
            float(side_prob),
            float(1.0),            # slump_step — reserved for v2
            int(W),
            int(H),
            int(protect_y_above),
            int(pass_kind),
            0,
        )
        params_buf = device.create_buffer(
            size=len(params_data),
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            label="slump_params",
        )
        device.queue.write_buffer(
            params_buf, 0, np.frombuffer(params_data, dtype=np.uint8))

        bgl = pipeline.get_bind_group_layout(0)
        bg = device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": src_mask,   "offset": 0, "size": mask_u32.nbytes}},
                {"binding": 1, "resource": {"buffer": dst_mask,   "offset": 0, "size": mask_u32.nbytes}},
                {"binding": 2, "resource": {"buffer": src_loose,  "offset": 0, "size": loose_u32.nbytes}},
                {"binding": 3, "resource": {"buffer": dst_loose,  "offset": 0, "size": loose_u32.nbytes}},
                {"binding": 4, "resource": {"buffer": fixed_buf,  "offset": 0, "size": fixed_u32.nbytes}},
                {"binding": 5, "resource": {"buffer": src_rng,    "offset": 0, "size": rng_u32.nbytes}},
                {"binding": 6, "resource": {"buffer": dst_rng,    "offset": 0, "size": rng_u32.nbytes}},
                {"binding": 7, "resource": {"buffer": params_buf, "offset": 0, "size": len(params_data)}},
            ],
        )
        encoder = device.create_command_encoder(label="slump_pass")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, bg)
        nx = max(1, (W + _SLUMP_WG_X - 1) // _SLUMP_WG_X)
        ny = max(1, (H + _SLUMP_WG_Y - 1) // _SLUMP_WG_Y)
        cp.dispatch_workgroups(nx, ny, 1)
        cp.end()
        device.queue.submit([encoder.finish()])
        try:
            params_buf.destroy()
        except Exception:  # noqa: BLE001
            pass

    # Pass 0 = vertical fall (A -> B). Pass 1 = sideways slump (B -> A).
    _dispatch(0, mask_a, mask_b, loose_a, loose_b, rng_a, rng_b)
    _dispatch(1, mask_b, mask_a, loose_b, loose_a, rng_b, rng_a)

    # Readback the final state (back in the A buffers after pass 1).
    mask_out = _readback(device, mask_a, mask_u32.nbytes, dtype=np.uint32)
    loose_out = _readback(device, loose_a, loose_u32.nbytes, dtype=np.uint32)
    rng_out = _readback(device, rng_a, rng_u32.nbytes, dtype=np.uint32)

    # Unpack mask back into HxWx4 uint8.
    field.mask[..., 0] = (mask_out & 0xFF).astype(np.uint8).reshape(H, W)
    field.mask[..., 1] = ((mask_out >> 8) & 0xFF).astype(np.uint8).reshape(H, W)
    field.mask[..., 2] = ((mask_out >> 16) & 0xFF).astype(np.uint8).reshape(H, W)
    field.mask[..., 3] = ((mask_out >> 24) & 0xFF).astype(np.uint8).reshape(H, W)
    field.loose[...] = loose_out.astype(bool).reshape(H, W)
    # Persist the advanced RNG into the cached field-level slot.
    field._slump_rng_state[...] = rng_out  # type: ignore[attr-defined]

    for buf in (mask_a, mask_b, loose_a, loose_b, rng_a, rng_b, fixed_buf):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass


def gpu_slump_loose(field: "ParticleField", dt: float) -> None:
    """Drop-in replacement for ``ParticleField._slump_loose(dt)``.

    Runs a per-pixel cellular automaton on the loose mask via the WGSL
    compute kernel when wgpu is available; otherwise falls back to the
    CPU implementation.

    Memory cost
    -----------
    A persistent ``H*W * 4 B`` PCG32 buffer is allocated on first call
    (stored as ``field._slump_rng_state``). For a 256x256 field that
    is 256 KB; 1920x1080 fields pay ~8 MB. Seed data is taken from
    ``field._rng`` so reproducible test runs stay reproducible.

    RNG divergence
    --------------
    Each pixel advances its OWN PCG32 state once per pass; the CPU
    path uses the shared ``field._rng`` with vectorised row-at-a-time
    draws. The two RNG strategies are NOT bit-equivalent, so per-pixel
    parity is not expected — tests should assert distribution-level
    invariants (mass conservation, settled pixel count, ~90% loose
    mask overlap) rather than exact equality.
    """
    if _probe_gpu():
        _gpu_slump_loose(field, dt)
    else:
        _numpy_slump_loose(field, dt)


# ──────────────────────────────────────────────────────────────────────
# Bake settled particles GPU port
# ──────────────────────────────────────────────────────────────────────
#
# Mirrors the polygon path of
# ``slappyengine.physics.baked_terrain.bake_settled_particles``. Per
# particle whose phase == SETTLING (and bake_flag is still False), look
# up its precomputed polygon mask in a CPU-built atlas and stamp the
# mask into the field's RGBA mask + material_grid + loose buffers.
#
# Atlas
# -----
# Built once per (process, materials-list-id). Each registered
# material's ``fragment_family.shapes`` is rasterised at every
# ``(scale, rotation)`` pair we expect to see; the resulting binary
# masks are concatenated into a flat u32 buffer with a parallel
# ``(offset, width, height)`` table.
#
# Scale bins: ``BAKE_SCALES = [1..MAX_SCALE]`` — clamped from the
# per-particle ``bake_radius + 1`` exactly as the CPU path computes
# ``br`` inside ParticleField.step.
#
# Rotation bins: ``N_ROTATIONS = 8`` (every π/4). Per-particle
# ``shape_rotation`` is quantised to the nearest bin; the slight
# rounding is what drives the ~5% pixel-difference tolerance in the
# parity test — CPU uses the exact float rotation, GPU uses the
# nearest quantised rasterisation.
#
# Splat (non-uniform scale) is NOT supported here. Particles whose
# material has ``splat_squash > 0 || splat_stretch > 0`` are routed
# through the CPU path by the caller. Sprint 4 will add splat.

_BAKE_MAX_SCALE   = 8
_BAKE_N_SCALES    = _BAKE_MAX_SCALE
_BAKE_N_ROTATIONS = 8


class _BakeAtlas:
    """Precomputed shape-mask atlas + lookup metadata.

    Attributes
    ----------
    atlas : np.ndarray (uint32 flat)
        Concatenated mask bits, one u32 per pixel (0 / 1).
    meta  : np.ndarray (uint32, N_entries × 4)
        (offset, width, height, _pad) per (shape_global, scale, rot).
    shape_global_of : list[list[int]]
        ``shape_global_of[material_id][shape_idx]`` → global shape
        index.
    n_entries : int
    n_shapes  : int
    """

    __slots__ = ("atlas", "meta", "shape_global_of", "n_entries", "n_shapes")

    def __init__(self, atlas, meta, shape_global_of, n_entries, n_shapes):
        self.atlas = atlas
        self.meta = meta
        self.shape_global_of = shape_global_of
        self.n_entries = n_entries
        self.n_shapes = n_shapes


def _build_bake_atlas(field: "ParticleField") -> _BakeAtlas:
    """Build (or fetch from cache) the shape-mask atlas for ``field``.

    Cached by ``id(field.materials)``. New materials registered after
    the first bake call will not invalidate the cache automatically —
    callers can drop ``_BAKE_ATLAS_CACHE.clear()`` if they need to.
    """
    cache_key = id(field.materials)
    cached = _BAKE_ATLAS_CACHE.get(cache_key)
    if cached is not None:
        return cached

    # Enumerate unique shapes by identity. Each material's family may
    # share shapes with others (e.g. SHAPE_CIRCLE in both SAND_FAMILY
    # and WATER_FAMILY); de-dup so the atlas isn't bloated.
    global_shapes: list = []
    shape_to_global: dict[int, int] = {}
    shape_global_of: list[list[int]] = []
    for mat in field.materials:
        family = mat.fragment_family
        if family is None:
            shape_global_of.append([])
            continue
        per_mat: list[int] = []
        for shape in family.shapes:
            key = id(shape)
            gi = shape_to_global.get(key)
            if gi is None:
                gi = len(global_shapes)
                shape_to_global[key] = gi
                global_shapes.append(shape)
            per_mat.append(gi)
        shape_global_of.append(per_mat)

    n_shapes = len(global_shapes)
    n_entries = n_shapes * _BAKE_N_SCALES * _BAKE_N_ROTATIONS

    # Rasterise every (shape, scale, rot) and pack into a flat u32 buf.
    import math as _math
    masks: list[np.ndarray] = []
    meta = np.zeros((max(1, n_entries), 4), dtype=np.uint32)
    cursor = 0
    for gi, shape in enumerate(global_shapes):
        for s in range(_BAKE_N_SCALES):
            scale = float(s + 1)
            for r in range(_BAKE_N_ROTATIONS):
                rot = (2.0 * _math.pi) * (r / float(_BAKE_N_ROTATIONS))
                m = shape.bake_mask(scale=scale, rotation=rot)
                bits = m.astype(np.uint32, copy=False).ravel()
                idx = gi * (_BAKE_N_SCALES * _BAKE_N_ROTATIONS) \
                    + s * _BAKE_N_ROTATIONS + r
                meta[idx, 0] = cursor
                meta[idx, 1] = m.shape[1]  # width
                meta[idx, 2] = m.shape[0]  # height
                meta[idx, 3] = 0
                masks.append(bits)
                cursor += bits.size

    if masks:
        atlas = np.concatenate(masks).astype(np.uint32)
    else:
        atlas = np.zeros(1, dtype=np.uint32)

    obj = _BakeAtlas(
        atlas=atlas,
        meta=meta,
        shape_global_of=shape_global_of,
        n_entries=n_entries,
        n_shapes=n_shapes,
    )
    _BAKE_ATLAS_CACHE[cache_key] = obj
    return obj


def _has_splat_particles(field: "ParticleField") -> bool:
    """True iff any settling particle is on a material with splat.

    Splat (non-uniform scale) is unsupported in the GPU bake kernel —
    callers route the whole frame through the CPU path when present.
    """
    from slappyengine.physics.particle_field import Phase
    to_bake = (
        (field.phase == np.int8(Phase.SETTLING))
        & ~field.bake_flag
    )
    if not to_bake.any():
        return False
    for mi, mat in enumerate(field.materials):
        if mat.splat_squash > 0.0 or mat.splat_stretch > 0.0:
            if (to_bake & (field.material_id == mi)).any():
                return True
    return False


def _build_particle_atlas_idx(
    field: "ParticleField", atlas: _BakeAtlas,
) -> np.ndarray:
    """Per-particle global atlas entry index, or -1 for skip-on-GPU.

    Mirrors the CPU resolve at the bake call site:
      * mat.fragment_family is None   → -1
      * br  = max(1, bake_radius + 1) clamped to MAX_SCALE
      * rot = nearest (2π / N_ROTATIONS) bin
    """
    import math as _math
    n = field.pos.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int32)

    n_per_shape = _BAKE_N_SCALES * _BAKE_N_ROTATIONS
    n_rot = _BAKE_N_ROTATIONS
    two_pi = 2.0 * _math.pi

    out = np.full(n, -1, dtype=np.int32)
    mids = field.material_id
    for mi, mat in enumerate(field.materials):
        family = mat.fragment_family
        if family is None:
            continue
        per_mat_shape_globals = atlas.shape_global_of[mi]
        if not per_mat_shape_globals:
            continue
        mask = mids == mi
        if not mask.any():
            continue
        local_idx = field.shape_idx[mask].astype(np.int64, copy=False)
        # The CPU does `% len(family.shapes)` — replicate.
        local_idx = local_idx % len(family.shapes)
        per_arr = np.asarray(per_mat_shape_globals, dtype=np.int32)
        gi = per_arr[local_idx]
        br = field.bake_radius[mask].astype(np.int32, copy=False) + 1
        br = np.clip(br, 1, _BAKE_MAX_SCALE)
        scale_bin = (br - 1).astype(np.int64)
        rot = field.shape_rotation[mask].astype(np.float64, copy=False)
        rot_norm = np.mod(rot, two_pi)
        rot_bin = np.floor(rot_norm / (two_pi / n_rot) + 0.5).astype(np.int64)
        rot_bin = np.mod(rot_bin, n_rot)
        entry = (
            gi.astype(np.int64) * n_per_shape
            + scale_bin * n_rot
            + rot_bin
        ).astype(np.int32)
        out[mask] = entry
    return out


def _numpy_bake_settled(field: "ParticleField") -> None:
    """Numpy fallback — delegate to the CPU code path used by
    ``ParticleField.step``. Keeps a single source of truth.
    """
    from slappyengine.physics.splat import SplatConfig, compute_splat

    to_bake_mask = field.settled & field.landed & ~field.bake_flag
    if not to_bake_mask.any():
        return
    shape_masks: list[np.ndarray | None] = []
    for i in range(field.pos.shape[0]):
        if not to_bake_mask[i]:
            shape_masks.append(None)
            continue
        mat = field.materials[int(field.material_id[i])]
        family = mat.fragment_family
        if family is None:
            shape_masks.append(None)
            continue
        si = int(field.shape_idx[i]) % len(family.shapes)
        shape = family.shapes[si]
        br = max(1, int(field.bake_radius[i]) + 1)
        if mat.splat_squash > 0.0 or mat.splat_stretch > 0.0:
            cfg = SplatConfig(
                squash_strength=mat.splat_squash,
                stretch_strength=mat.splat_stretch,
                fluidity_gate=mat.splat_fluidity_gate,
            )
            rig = max(1, int(field.rigidify_at[i]))
            age = int(field.kinetic_age[i])
            current_fluidity = max(0.0, 1.0 - age / rig)
            sx, sy, rot = compute_splat(
                impact_vel=(float(field.impact_vel[i, 0]),
                            float(field.impact_vel[i, 1])),
                current_fluidity=current_fluidity,
                base_scale=float(br),
                base_rotation=float(field.shape_rotation[i]),
                cfg=cfg,
            )
            shape_masks.append(
                shape.bake_mask_xy(scale_x=sx, scale_y=sy, rotation=rot)
            )
        else:
            shape_masks.append(
                shape.bake_mask(scale=float(br),
                                rotation=float(field.shape_rotation[i]))
            )

    from slappyengine.physics.baked_terrain import bake_settled_particles
    bake_settled_particles(
        pos=field.pos, radius=field.radius, colour=field.color,
        landed=field.landed, settled=field.settled,
        bake_flag=field.bake_flag, terrain_rgba=field.mask,
        per_particle_bake_radius=field.bake_radius,
        jagged=True,
        shape_masks=shape_masks if shape_masks else None,
        material_id=field.material_id,
        material_grid=field.material_grid,
    )


def _gpu_bake_settled(field: "ParticleField") -> None:
    """Dispatch the WGSL bake kernel and read back mask + material_grid
    + loose + bake_flag.
    """
    n = int(field.pos.shape[0])
    if n == 0:
        return

    wgpu = _WGPU
    device = _DEVICE
    pipeline = _BAKE_PIPELINE

    atlas = _build_bake_atlas(field)
    atlas_idx_np = _build_particle_atlas_idx(field, atlas)
    if not (atlas_idx_np >= 0).any():
        return

    H, W = field.mask.shape[:2]

    pos_np = np.ascontiguousarray(field.pos, dtype=np.float32)
    phase_np = field.phase.astype(np.int32, copy=False)
    bake_flag_np = field.bake_flag.astype(np.uint32, copy=False)
    color_rgb = np.ascontiguousarray(field.color, dtype=np.uint8)
    color_u32 = (
        (np.uint32(255) << 24)
        | (color_rgb[:, 2].astype(np.uint32) << 16)
        | (color_rgb[:, 1].astype(np.uint32) << 8)
        | color_rgb[:, 0].astype(np.uint32)
    )
    color_u32 = np.ascontiguousarray(color_u32, dtype=np.uint32)
    mid_np = np.ascontiguousarray(field.material_id, dtype=np.int32)

    mask_2d = field.mask  # (H, W, 4) uint8
    mask_u32 = (
        (mask_2d[..., 3].astype(np.uint32) << 24)
        | (mask_2d[..., 2].astype(np.uint32) << 16)
        | (mask_2d[..., 1].astype(np.uint32) << 8)
        | mask_2d[..., 0].astype(np.uint32)
    ).ravel()
    mask_u32 = np.ascontiguousarray(mask_u32, dtype=np.uint32)

    matgrid_i32 = field.material_grid.astype(np.int32, copy=False).ravel()
    matgrid_i32 = np.ascontiguousarray(matgrid_i32, dtype=np.int32)
    loose_u32 = field.loose.astype(np.uint32, copy=False).ravel()
    loose_u32 = np.ascontiguousarray(loose_u32, dtype=np.uint32)

    atlas_idx_np = np.ascontiguousarray(atlas_idx_np, dtype=np.int32)
    atlas_buf_np = np.ascontiguousarray(atlas.atlas, dtype=np.uint32)
    atlas_meta_np = np.ascontiguousarray(atlas.meta, dtype=np.uint32)

    USAGE_RW = (
        wgpu.BufferUsage.STORAGE
        | wgpu.BufferUsage.COPY_SRC
        | wgpu.BufferUsage.COPY_DST
    )
    USAGE_R = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST

    def _safe_size(nbytes: int) -> int:
        return max(4, nbytes)

    pos_buf       = device.create_buffer(size=_safe_size(pos_np.nbytes),       usage=USAGE_R,  label="pb_pos")
    phase_buf     = device.create_buffer(size=_safe_size(phase_np.nbytes),     usage=USAGE_R,  label="pb_phase")
    bake_flag_buf = device.create_buffer(size=_safe_size(bake_flag_np.nbytes), usage=USAGE_RW, label="pb_bake_flag")
    color_buf     = device.create_buffer(size=_safe_size(color_u32.nbytes),    usage=USAGE_R,  label="pb_color")
    mid_buf       = device.create_buffer(size=_safe_size(mid_np.nbytes),       usage=USAGE_R,  label="pb_mid")
    atlas_idx_buf = device.create_buffer(size=_safe_size(atlas_idx_np.nbytes), usage=USAGE_R,  label="pb_atlas_idx")
    atlas_buf     = device.create_buffer(size=_safe_size(atlas_buf_np.nbytes), usage=USAGE_R,  label="pb_atlas")
    atlas_meta_buf= device.create_buffer(size=_safe_size(atlas_meta_np.nbytes),usage=USAGE_R,  label="pb_atlas_meta")
    mask_buf      = device.create_buffer(size=_safe_size(mask_u32.nbytes),     usage=USAGE_RW, label="pb_mask")
    matgrid_buf   = device.create_buffer(size=_safe_size(matgrid_i32.nbytes),  usage=USAGE_RW, label="pb_matgrid")
    loose_buf     = device.create_buffer(size=_safe_size(loose_u32.nbytes),    usage=USAGE_RW, label="pb_loose")

    device.queue.write_buffer(pos_buf,        0, pos_np)
    device.queue.write_buffer(phase_buf,      0, phase_np)
    device.queue.write_buffer(bake_flag_buf,  0, bake_flag_np)
    device.queue.write_buffer(color_buf,      0, color_u32)
    device.queue.write_buffer(mid_buf,        0, mid_np)
    device.queue.write_buffer(atlas_idx_buf,  0, atlas_idx_np)
    device.queue.write_buffer(atlas_buf,      0, atlas_buf_np)
    device.queue.write_buffer(atlas_meta_buf, 0, atlas_meta_np)
    device.queue.write_buffer(mask_buf,       0, mask_u32)
    device.queue.write_buffer(matgrid_buf,    0, matgrid_i32)
    device.queue.write_buffer(loose_buf,      0, loose_u32)

    params_data = struct.pack(
        "IIII",
        n, int(W), int(H), int(atlas.n_entries),
    )
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="pb_params",
    )
    device.queue.write_buffer(
        params_buf, 0, np.frombuffer(params_data, dtype=np.uint8),
    )

    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0,  "resource": {"buffer": pos_buf,        "offset": 0, "size": _safe_size(pos_np.nbytes)}},
            {"binding": 1,  "resource": {"buffer": phase_buf,      "offset": 0, "size": _safe_size(phase_np.nbytes)}},
            {"binding": 2,  "resource": {"buffer": bake_flag_buf,  "offset": 0, "size": _safe_size(bake_flag_np.nbytes)}},
            {"binding": 3,  "resource": {"buffer": color_buf,      "offset": 0, "size": _safe_size(color_u32.nbytes)}},
            {"binding": 4,  "resource": {"buffer": mid_buf,        "offset": 0, "size": _safe_size(mid_np.nbytes)}},
            {"binding": 5,  "resource": {"buffer": atlas_idx_buf,  "offset": 0, "size": _safe_size(atlas_idx_np.nbytes)}},
            {"binding": 6,  "resource": {"buffer": atlas_buf,      "offset": 0, "size": _safe_size(atlas_buf_np.nbytes)}},
            {"binding": 7,  "resource": {"buffer": atlas_meta_buf, "offset": 0, "size": _safe_size(atlas_meta_np.nbytes)}},
            {"binding": 8,  "resource": {"buffer": mask_buf,       "offset": 0, "size": _safe_size(mask_u32.nbytes)}},
            {"binding": 9,  "resource": {"buffer": matgrid_buf,    "offset": 0, "size": _safe_size(matgrid_i32.nbytes)}},
            {"binding": 10, "resource": {"buffer": loose_buf,      "offset": 0, "size": _safe_size(loose_u32.nbytes)}},
            {"binding": 11, "resource": {"buffer": params_buf,     "offset": 0, "size": len(params_data)}},
        ],
    )

    encoder = device.create_command_encoder(label="pb_bake")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_groups = max(1, (n + _WORKGROUP_SIZE - 1) // _WORKGROUP_SIZE)
    cp.dispatch_workgroups(n_groups)
    cp.end()
    device.queue.submit([encoder.finish()])

    mask_out  = _readback(device, mask_buf,      mask_u32.nbytes,    dtype=np.uint32)
    matg_out  = _readback(device, matgrid_buf,   matgrid_i32.nbytes, dtype=np.int32)
    loose_out = _readback(device, loose_buf,     loose_u32.nbytes,   dtype=np.uint32)
    bake_out  = _readback(device, bake_flag_buf, bake_flag_np.nbytes,dtype=np.uint32)

    mask_2d_out = mask_out.reshape(H, W)
    field.mask[..., 0] = (mask_2d_out & 0xFF).astype(np.uint8)
    field.mask[..., 1] = ((mask_2d_out >> 8) & 0xFF).astype(np.uint8)
    field.mask[..., 2] = ((mask_2d_out >> 16) & 0xFF).astype(np.uint8)
    field.mask[..., 3] = ((mask_2d_out >> 24) & 0xFF).astype(np.uint8)
    field.material_grid[...] = matg_out.reshape(H, W).astype(np.int8, copy=False)
    field.loose[...] = loose_out.reshape(H, W).astype(bool, copy=False)
    field.bake_flag[...] = field.bake_flag | bake_out.astype(bool, copy=False)

    for buf in (
        pos_buf, phase_buf, bake_flag_buf, color_buf, mid_buf,
        atlas_idx_buf, atlas_buf, atlas_meta_buf,
        mask_buf, matgrid_buf, loose_buf, params_buf,
    ):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass


def gpu_bake_settled(field: "ParticleField") -> bool:
    """Run the polygon-stamp bake pass on the GPU.

    Returns
    -------
    bool
        ``True`` if the GPU path handled the frame (caller should skip
        the CPU bake call). ``False`` if the GPU path bailed (no wgpu,
        or splat particles present) and the caller should run the CPU
        path. ``True`` is also returned when there is nothing to bake.
    """
    if field.pos.shape[0] == 0:
        return True
    if not _probe_gpu():
        return False
    if _has_splat_particles(field):
        return False
    _gpu_bake_settled(field)
    return True


def bake_atlas_memory_bytes(field: "ParticleField") -> int:
    """Total bytes held by the cached bake atlas for ``field``.

    Sum of the mask buffer + the entry meta table. Useful for the
    `Atlas memory cost` line in the Sprint 3 wrap-up.
    """
    atlas = _build_bake_atlas(field)
    return int(atlas.atlas.nbytes + atlas.meta.nbytes)


# ── Smoke test ────────────────────────────────────────────────────────


if __name__ == "__main__":
    # Spawn 100 particles, integrate 20 steps via both CPU (_integrate)
    # and GPU (gpu_integrate); assert pos/vel match within tolerance.
    from slappyengine.physics.particle_field import ParticleField

    rng = np.random.default_rng(0xBEEF)
    N = 100
    STEPS = 20
    DT = 1.0 / 60.0

    def _new_field() -> ParticleField:
        f = ParticleField(width=512, height=512)
        # Local RNG ensures CPU + GPU fields see the same spawn sequence
        # — re-seeded inside _new_field so the second call starts from
        # the same state as the first.
        local_rng = np.random.default_rng(0xBEEF)
        for _ in range(N):
            mid = int(local_rng.integers(0, len(f.materials)))
            x = float(local_rng.uniform(0, f.width))
            # Spawn above the floor and well below the ceiling so most
            # particles stay airborne for the duration of the test.
            y = float(local_rng.uniform(0, f.height // 4))
            vx = float(local_rng.uniform(-50, 50))
            vy = float(local_rng.uniform(-200, 0))
            f.spawn(x=x, y=y, vx=vx, vy=vy, material=mid)
        return f

    # CPU reference
    cpu = _new_field()
    for _ in range(STEPS):
        air = ~cpu.landed
        if air.any():
            cpu._integrate(air, DT)

    # GPU (or numpy fallback) under test
    gpu = _new_field()
    for _ in range(STEPS):
        gpu_integrate(gpu, DT)

    pos_diff = float(np.max(np.abs(cpu.pos - gpu.pos)))
    vel_diff = float(np.max(np.abs(cpu.vel - gpu.vel)))
    tol = 1e-3  # GPU is f32 throughout; CPU also f32 — small drift OK.
    backend = "GPU" if is_gpu_available() else "numpy-fallback"
    print(f"backend         : {backend}")
    print(f"max |dpos|      : {pos_diff:.3e}")
    print(f"max |dvel|      : {vel_diff:.3e}")
    print(f"tolerance       : {tol:.3e}")
    if pos_diff < tol and vel_diff < tol:
        print("PASS — CPU vs GPU integration within tolerance.")
    else:
        print("FAIL — divergence exceeds tolerance.")
        raise SystemExit(1)
