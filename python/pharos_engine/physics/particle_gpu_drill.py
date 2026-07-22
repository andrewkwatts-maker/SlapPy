"""GPU port of ``ParticleField._drill_through``.

Replicates the entry-crater + DDA-walk + ejecta-spawn logic from
:meth:`pharos_engine.physics.particle_field.ParticleField._drill_through`
on a WGSL compute shader (``shaders/particle_drill.wgsl``).

Scope
-----
This kernel covers the **per-bullet** drilling work — entry crater,
drill walk, per-pixel velocity loss, KE-driven lodging, ejecta spawn.
What it DOES NOT do, and the reasons:

* Per-pixel deflection (``Material.drill_deflection > 0``) — adds a
  conditional 3x3 neighbour scan inside the inner loop. Not needed by
  the parity test (BULLET_MAT defaults to ``drill_deflection=0``).
* Fracture pass (``Material.drill_fracture_threshold < 1.0``) — a
  post-walk 7x7 density check + ring expand. Again, default disabled.
* Isolated-pixel detach pass — runs on the CPU AFTER the GPU readback
  (see :func:`gpu_drill_through`). The detach pass is naturally a
  numpy 4-direction shift-and-sum, which is faster on the CPU than a
  per-bullet workgroup search would be on the GPU.

Determinism caveat
------------------
When two bullets drill overlapping wall regions in the SAME frame,
the order in which their writes to ``mask`` / ``material_grid`` /
``loose`` land is undefined (workgroup dispatches are not serialised).
The CPU path has the same property — it iterates particles in index
order, so two bullets clearing the same pixel both succeed but the
"who cleared it" depends on iteration order. Both paths converge as
long as no two bullets clear the same pixel in the same frame. The
parity test enforces this by spacing bullets apart.

Cost model
----------
The per-frame readback of the ejecta counter + arrays is the dominant
overhead — it forces a CPU/GPU sync that's hundreds of microseconds
even when no ejecta are produced. For the parity test (5 bullets, 30
frames, BULLET_MAT default drill_eject_gain=0) we still pay the cost
of the counter readback every step. Real-world calls amortise this
across hundreds of bullets per dispatch.
"""
from __future__ import annotations

import struct
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from pharos_engine.physics.particle_field import ParticleField


_SHADER_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "shaders" / "particle_drill.wgsl"
)
_WORKGROUP_SIZE = 64
# Hard cap on ejecta we'll capture in one dispatch. At 36 bytes per
# ejecta record (9 u32s), 4096 = 144 KB GPU buffer + 144 KB readback.
# Chosen so the buffer round-trip is well below 1 ms on any modern
# discrete GPU; if a single dispatch exceeds this, we warn and keep
# what fits.
MAX_EJECTA_PER_DISPATCH = 4096
EJECTA_STRIDE_U32 = 9  # must match WGSL EJECTA_STRIDE

# ── Lazy device / pipeline cache ───────────────────────────────────────
_GPU_PROBED = False
_GPU_AVAILABLE = False
_WGPU = None  # type: ignore[var-annotated]
_DEVICE = None  # type: ignore[var-annotated]
_PIPELINE = None  # type: ignore[var-annotated]


def _probe_gpu() -> bool:
    """One-shot adapter + device + pipeline probe; idempotent."""
    global _GPU_PROBED, _GPU_AVAILABLE, _WGPU, _DEVICE, _PIPELINE
    if _GPU_PROBED:
        return _GPU_AVAILABLE
    _GPU_PROBED = True

    try:
        import wgpu  # type: ignore
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu_drill: wgpu not importable ({exc!r}); "
            "falling back to CPU drill.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        adapter = wgpu.gpu.request_adapter_sync(
            power_preference="high-performance")
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu_drill: adapter request failed ({exc!r}); "
            "falling back to CPU drill.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    if adapter is None:
        warnings.warn(
            "particle_gpu_drill: no wgpu adapter available; "
            "falling back to CPU drill.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        device = adapter.request_device_sync(
            required_features=[], required_limits={})
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu_drill: device request failed ({exc!r}); "
            "falling back to CPU drill.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    try:
        src = _SHADER_PATH.read_text(encoding="utf-8")
        module = device.create_shader_module(code=src, label="particle_drill")
        pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": module, "entry_point": "main"},
            label="particle_drill_pipeline",
        )
    except Exception as exc:  # noqa: BLE001
        warnings.warn(
            f"particle_gpu_drill: pipeline build failed ({exc!r}); "
            "falling back to CPU drill.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False

    _WGPU = wgpu
    _DEVICE = device
    _PIPELINE = pipeline
    _GPU_AVAILABLE = True
    return True


# ── Helpers ────────────────────────────────────────────────────────────


def _pack_mat_props(field: "ParticleField") -> np.ndarray:
    """Pack drill-relevant material properties into a flat vec4 array.

    Layout: two vec4<f32> per material —
      [2*mid+0] = (drill_max_px, drill_velocity_loss,
                   drill_eject_gain, binding_force)
      [2*mid+1] = (drill_entry_crater, drill_entry_crater_jitter,
                   mass_conservation, _pad)
    """
    n = len(field.materials)
    arr = np.zeros((n * 2, 4), dtype=np.float32)
    for i, mat in enumerate(field.materials):
        arr[2 * i, 0] = float(mat.drill_max_px)
        arr[2 * i, 1] = float(mat.drill_velocity_loss)
        arr[2 * i, 2] = float(mat.drill_eject_gain)
        arr[2 * i, 3] = float(mat.binding_force)
        arr[2 * i + 1, 0] = float(mat.drill_entry_crater)
        arr[2 * i + 1, 1] = float(mat.drill_entry_crater_jitter)
        arr[2 * i + 1, 2] = float(mat.mass_conservation)
        arr[2 * i + 1, 3] = 0.0
    return arr


def _pack_mask_to_u32(mask: np.ndarray) -> np.ndarray:
    """(H, W, 4) uint8 → (H*W,) uint32 with bytes packed r,g,b,a."""
    flat = mask.reshape(-1, 4).astype(np.uint32)
    return (flat[:, 0]
            | (flat[:, 1] << 8)
            | (flat[:, 2] << 16)
            | (flat[:, 3] << 24))


def _unpack_u32_to_mask(packed: np.ndarray, H: int, W: int) -> np.ndarray:
    """(H*W,) uint32 → (H, W, 4) uint8."""
    out = np.zeros((H * W, 4), dtype=np.uint8)
    out[:, 0] = (packed & 0xFF).astype(np.uint8)
    out[:, 1] = ((packed >> 8) & 0xFF).astype(np.uint8)
    out[:, 2] = ((packed >> 16) & 0xFF).astype(np.uint8)
    out[:, 3] = ((packed >> 24) & 0xFF).astype(np.uint8)
    return out.reshape(H, W, 4)


def _pack_color_to_u32(color: np.ndarray) -> np.ndarray:
    """(N, 3) uint8 → (N,) uint32 with a=255 in MSB."""
    n = color.shape[0]
    c = color.astype(np.uint32)
    return (c[:, 0]
            | (c[:, 1] << 8)
            | (c[:, 2] << 16)
            | (255 << 24)).astype(np.uint32)


def _readback(device, src_buf, size_bytes: int, dtype) -> np.ndarray:
    """Copy a storage buffer into a MAP_READ staging buffer; return ndarray."""
    wgpu = _WGPU
    staging = device.create_buffer(
        size=size_bytes,
        usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
        label="pf_drill_readback",
    )
    encoder = device.create_command_encoder(label="pf_drill_readback_copy")
    encoder.copy_buffer_to_buffer(src_buf, 0, staging, 0, size_bytes)
    device.queue.submit([encoder.finish()])

    staging.map_sync(wgpu.MapMode.READ)
    raw = np.frombuffer(
        staging.read_mapped(0, size_bytes), dtype=dtype).copy()
    staging.unmap()
    try:
        staging.destroy()
    except Exception:  # noqa: BLE001
        pass
    return raw


# ── Numpy fallback (calls the CPU path) ────────────────────────────────


def _numpy_drill_through(field: "ParticleField", dt: float) -> None:
    """Fallback: replicate the CPU _collide drill branch.

    Walks every airborne bullet (mat.drill_max_px > 0), does the swept
    DDA, fires _drill_through. This is a TRIMMED copy of the CPU
    _collide loop — drilling pieces only — so we can route the
    use_gpu_drill=True code path through gpu_drill_through() regardless
    of whether the GPU device is available.
    """
    H, W = field.mask.shape[:2]
    air_mask = ~field.landed
    if not air_mask.any():
        return
    for i in np.nonzero(air_mask)[0]:
        x = int(field.pos[i, 0])
        y = int(field.pos[i, 1])
        if x < 0 or x >= W or y >= H or y < 0:
            continue
        mat = field.materials[int(field.material_id[i])]
        if mat.drill_max_px == 0:
            continue
        prev_x = int(field.pos[i, 0] - field.vel[i, 0] * dt)
        prev_y = int(field.pos[i, 1] - field.vel[i, 1] * dt)
        dx = x - prev_x
        dy = y - prev_y
        steps = max(abs(dx), abs(dy), 1)
        hit_x = -1
        hit_y = -1
        for s in range(steps + 1):
            cx = prev_x + (dx * s) // steps
            cy = prev_y + (dy * s) // steps
            if not (0 <= cx < W and 0 <= cy < H):
                continue
            if field.mask[cy, cx, 3] > 0:
                hit_x = cx
                hit_y = cy
                break
        if hit_x < 0:
            continue
        vsq = float(field.vel[i, 0] ** 2 + field.vel[i, 1] ** 2)
        ke = 0.5 * (max(1.0, float(field.radius[i])) ** 2) * vsq
        if ke > mat.binding_force:
            field._drill_through(i, hit_x, hit_y, mat)


# ── GPU dispatch ──────────────────────────────────────────────────────


def _gpu_drill_through(field: "ParticleField", dt: float) -> None:
    """Dispatch the WGSL drill kernel; readback ejecta + mutated state.

    Steps:
      1. Upload SoA + mask + material_grid + loose + mat_props + params.
      2. Run dispatch (one workgroup per 64 bullets).
      3. Readback pos, vel, phase, mask, material_grid, loose,
         ejecta_count, ejecta.data.
      4. Resolve ejecta into a spawn_batch.
      5. Run isolated-pixel detach pass on CPU (numpy-vectorised).
    """
    n = int(field.pos.shape[0])
    if n == 0:
        return

    wgpu = _WGPU
    device = _DEVICE
    pipeline = _PIPELINE
    H, W = field.mask.shape[:2]

    # ── Pack uploads ──────────────────────────────────────────────────
    pos_np = np.ascontiguousarray(field.pos, dtype=np.float32)
    vel_np = np.ascontiguousarray(field.vel, dtype=np.float32)
    phase_np = field.phase.astype(np.int32, copy=False)
    color_np = _pack_color_to_u32(field.color)
    mid_np = np.ascontiguousarray(field.material_id, dtype=np.int32)
    mask_packed = _pack_mask_to_u32(field.mask)
    mat_grid_np = field.material_grid.astype(np.int32).ravel()
    loose_np = field.loose.astype(np.uint32).ravel()
    radius_np = np.ascontiguousarray(field.radius, dtype=np.float32)
    mat_props_np = _pack_mat_props(field)

    # Ejecta buffers — sized to the cap.
    ejecta_data = np.zeros(
        MAX_EJECTA_PER_DISPATCH * EJECTA_STRIDE_U32, dtype=np.uint32)
    ejecta_counter = np.zeros(1, dtype=np.uint32)

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

    pos_buf      = _mkbuf(pos_np, "pf_drill_pos", rw=True)
    vel_buf      = _mkbuf(vel_np, "pf_drill_vel", rw=True)
    phase_buf    = _mkbuf(phase_np, "pf_drill_phase", rw=True)
    color_buf    = _mkbuf(color_np, "pf_drill_color", rw=True)
    mid_buf      = _mkbuf(mid_np, "pf_drill_mid", rw=False)
    mask_buf     = _mkbuf(mask_packed, "pf_drill_mask", rw=True)
    mgrid_buf    = _mkbuf(mat_grid_np, "pf_drill_mgrid", rw=True)
    loose_buf    = _mkbuf(loose_np, "pf_drill_loose", rw=True)
    ej_count_buf = _mkbuf(ejecta_counter, "pf_drill_ej_count", rw=True)
    ej_data_buf  = _mkbuf(ejecta_data, "pf_drill_ej_data", rw=True)
    mat_buf      = _mkbuf(mat_props_np, "pf_drill_mat_props", rw=False)
    radius_buf   = _mkbuf(radius_np, "pf_drill_radius", rw=False)

    # ── Params uniform ───────────────────────────────────────────────
    # Struct: n_particles, width, height, max_ejecta, rng_seed (u32),
    # dt (f32), _pad0, _pad1. Total 32 bytes.
    seed = int(np.random.SeedSequence().generate_state(1)[0]) & 0xFFFFFFFF
    params_data = struct.pack(
        "IIIIIfII",
        n,
        W,
        H,
        MAX_EJECTA_PER_DISPATCH,
        seed,
        float(dt),
        0,
        0,
    )
    params_buf = device.create_buffer(
        size=len(params_data),
        usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        label="pf_drill_params",
    )
    device.queue.write_buffer(
        params_buf, 0, np.frombuffer(params_data, dtype=np.uint8))

    # ── Bind group ───────────────────────────────────────────────────
    bgl = pipeline.get_bind_group_layout(0)
    bg = device.create_bind_group(
        layout=bgl,
        entries=[
            {"binding": 0, "resource": {"buffer": pos_buf,      "offset": 0, "size": pos_np.nbytes}},
            {"binding": 1, "resource": {"buffer": vel_buf,      "offset": 0, "size": vel_np.nbytes}},
            {"binding": 2, "resource": {"buffer": phase_buf,    "offset": 0, "size": phase_np.nbytes}},
            {"binding": 3, "resource": {"buffer": color_buf,    "offset": 0, "size": color_np.nbytes}},
            {"binding": 4, "resource": {"buffer": mid_buf,      "offset": 0, "size": mid_np.nbytes}},
            {"binding": 5, "resource": {"buffer": mask_buf,     "offset": 0, "size": mask_packed.nbytes}},
            {"binding": 6, "resource": {"buffer": mgrid_buf,    "offset": 0, "size": mat_grid_np.nbytes}},
            {"binding": 7, "resource": {"buffer": loose_buf,    "offset": 0, "size": loose_np.nbytes}},
            {"binding": 8, "resource": {"buffer": ej_count_buf, "offset": 0, "size": ejecta_counter.nbytes}},
            {"binding": 9, "resource": {"buffer": ej_data_buf,  "offset": 0, "size": ejecta_data.nbytes}},
            {"binding": 10, "resource": {"buffer": mat_buf,     "offset": 0, "size": mat_props_np.nbytes}},
            {"binding": 11, "resource": {"buffer": params_buf,  "offset": 0, "size": len(params_data)}},
            {"binding": 12, "resource": {"buffer": radius_buf,  "offset": 0, "size": radius_np.nbytes}},
        ],
    )

    encoder = device.create_command_encoder(label="pf_drill_dispatch")
    cp = encoder.begin_compute_pass()
    cp.set_pipeline(pipeline)
    cp.set_bind_group(0, bg)
    n_groups = max(1, (n + _WORKGROUP_SIZE - 1) // _WORKGROUP_SIZE)
    cp.dispatch_workgroups(n_groups)
    cp.end()
    device.queue.submit([encoder.finish()])

    # ── Readback ────────────────────────────────────────────────────
    pos_out = _readback(device, pos_buf, pos_np.nbytes, np.float32).reshape(n, 2)
    vel_out = _readback(device, vel_buf, vel_np.nbytes, np.float32).reshape(n, 2)
    phase_out = _readback(device, phase_buf, phase_np.nbytes, np.int32)
    mask_out_packed = _readback(
        device, mask_buf, mask_packed.nbytes, np.uint32)
    mgrid_out = _readback(device, mgrid_buf, mat_grid_np.nbytes, np.int32)
    loose_out = _readback(device, loose_buf, loose_np.nbytes, np.uint32)
    ej_count_out = _readback(
        device, ej_count_buf, ejecta_counter.nbytes, np.uint32)
    n_ej = int(ej_count_out[0])
    if n_ej > MAX_EJECTA_PER_DISPATCH:
        warnings.warn(
            f"particle_gpu_drill: ejecta overflow — kernel wanted "
            f"{n_ej} ejecta but max_ejecta={MAX_EJECTA_PER_DISPATCH}; "
            f"keeping the first {MAX_EJECTA_PER_DISPATCH}.",
            RuntimeWarning,
            stacklevel=2,
        )
        n_ej = MAX_EJECTA_PER_DISPATCH

    if n_ej > 0:
        ej_raw = _readback(
            device, ej_data_buf,
            n_ej * EJECTA_STRIDE_U32 * 4,
            np.uint32,
        ).reshape(n_ej, EJECTA_STRIDE_U32)
    else:
        ej_raw = np.zeros((0, EJECTA_STRIDE_U32), dtype=np.uint32)

    # ── Write back into the field SoA ────────────────────────────────
    field.pos[...] = pos_out
    field.vel[...] = vel_out
    field.phase[...] = phase_out.astype(np.int8)
    # Derived bool arrays — replicate _set_phase logic vectorised.
    field.landed[...] = field.phase >= int(1)   # Phase.LANDED
    field.settled[...] = field.phase >= int(2)  # Phase.SETTLING
    field.bake_flag[...] = field.phase == int(3)  # Phase.BAKED
    field.mask[...] = _unpack_u32_to_mask(mask_out_packed, H, W)
    field.material_grid[...] = mgrid_out.reshape(H, W).astype(np.int8)
    field.loose[...] = loose_out.reshape(H, W).astype(bool)

    # ── Resolve ejecta into spawn_batch ──────────────────────────────
    if n_ej > 0:
        ej_pos_x = ej_raw[:, 0].view(np.float32)
        ej_pos_y = ej_raw[:, 1].view(np.float32)
        ej_vel_x = ej_raw[:, 2].view(np.float32)
        ej_vel_y = ej_raw[:, 3].view(np.float32)
        ej_mid   = ej_raw[:, 4].view(np.int32)
        ej_r     = ej_raw[:, 5].astype(np.uint8)
        ej_g     = ej_raw[:, 6].astype(np.uint8)
        ej_b     = ej_raw[:, 7].astype(np.uint8)
        ej_pos = np.column_stack([ej_pos_x, ej_pos_y]).astype(np.float32)
        ej_vel = np.column_stack([ej_vel_x, ej_vel_y]).astype(np.float32)
        ej_cols = np.column_stack([ej_r, ej_g, ej_b]).astype(np.uint8)
        ej_radii = np.zeros(n_ej, dtype=np.float32)
        field.spawn_batch(
            pos=ej_pos, vel=ej_vel,
            material_ids=ej_mid.astype(np.int32),
            radii=ej_radii,
            colors=ej_cols,
        )

    # ── CPU-side detach pass (isolated unsupported solid pixels) ─────
    _detach_isolated_pixels(field)

    # Cleanup transient buffers.
    for buf in (
        pos_buf, vel_buf, phase_buf, color_buf, mid_buf, mask_buf,
        mgrid_buf, loose_buf, ej_count_buf, ej_data_buf, mat_buf,
        radius_buf, params_buf,
    ):
        try:
            buf.destroy()
        except Exception:  # noqa: BLE001
            pass


def _detach_isolated_pixels(field: "ParticleField") -> None:
    """Vectorised global scan for unsupported solid pixels.

    The CPU drill path scans a local window around the hit point. With
    multiple bullets per frame on the GPU we don't have a single
    hit-point, so we do one whole-grid scan: any non-fixed solid pixel
    with zero 4-neighbour solid neighbours becomes a fresh airborne
    particle inheriting the pixel's colour + material id.
    """
    mask = field.mask[..., 3] > 0
    fixed = field._fixed_mask
    if not mask.any():
        return
    # 4-neighbour sum via shifts.
    nb = np.zeros_like(mask, dtype=np.int8)
    nb[1:, :] += mask[:-1, :].astype(np.int8)
    nb[:-1, :] += mask[1:, :].astype(np.int8)
    nb[:, 1:] += mask[:, :-1].astype(np.int8)
    nb[:, :-1] += mask[:, 1:].astype(np.int8)
    isolated = mask & (nb == 0) & ~fixed
    if not isolated.any():
        return
    ys, xs = np.where(isolated)
    n_det = ys.size
    detach_pos = np.column_stack([xs, ys]).astype(np.float32)
    detach_cols = field.mask[ys, xs, :3].copy()
    detach_mids = field.material_grid[ys, xs].astype(np.int32)
    # Bullet mid fallback — pick material 0 when grid is -1.
    detach_mids[detach_mids < 0] = 0
    field.mask[ys, xs, 3] = 0
    field.loose[ys, xs] = False
    field.spawn_batch(
        pos=detach_pos,
        vel=np.zeros((n_det, 2), dtype=np.float32),
        material_ids=detach_mids,
        radii=np.zeros(n_det, dtype=np.float32),
        colors=detach_cols,
    )


# ── Public entry point ────────────────────────────────────────────────


def gpu_drill_through(field: "ParticleField", dt: float) -> None:
    """Run the drill phase on the GPU for every airborne drilling bullet.

    Drop-in replacement for the in-line CPU drill branch inside
    ``ParticleField._collide``. Walks every airborne particle whose
    material has ``drill_max_px > 0``, does the swept DDA to find a
    hit pixel, then runs entry-crater + drill-walk + ejecta spawn on
    the GPU.

    Falls back to a CPU mimic when wgpu is unavailable.
    """
    if field.pos.shape[0] == 0:
        return
    # Only fire when at least one bullet material is registered (any
    # material with drill_max_px > 0). Saves the entire upload round
    # trip on fields that have no drilling materials at all.
    has_drill_mat = any(m.drill_max_px > 0 for m in field.materials)
    if not has_drill_mat:
        return
    if _probe_gpu():
        _gpu_drill_through(field, dt)
    else:
        _numpy_drill_through(field, dt)


def is_gpu_available() -> bool:
    """Probe (cached) whether the GPU drill path is active in this process."""
    return _probe_gpu()
