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
_WORKGROUP_SIZE = 64

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


def _probe_gpu() -> bool:
    """One-shot adapter+device probe; idempotent."""
    global _GPU_PROBED, _GPU_AVAILABLE, _WGPU, _DEVICE, _QUEUE, _PIPELINE, _SHADER_SRC
    global _COLLIDE_PIPELINE, _COLLIDE_SHADER_SRC
    global _THERMAL_PIPELINE, _THERMAL_SHADER_SRC
    global _COLUMN_TOP_PIPELINE, _COLUMN_TOP_SHADER_SRC
    global _SLIDE_PIPELINE, _SLIDE_SHADER_SRC
    global _KINETIC_RELAX_PIPELINE, _KINETIC_RELAX_SHADER_SRC
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
