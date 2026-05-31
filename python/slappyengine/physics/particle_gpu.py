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


_SHADER_PATH = Path(__file__).resolve().parent.parent.parent.parent / "shaders" / "particle_integrate.wgsl"
_WORKGROUP_SIZE = 64

# ── Lazy device / pipeline cache ───────────────────────────────────────
_GPU_PROBED = False
_GPU_AVAILABLE = False
_WGPU = None  # type: ignore[var-annotated]
_DEVICE = None  # type: ignore[var-annotated]
_QUEUE = None  # type: ignore[var-annotated]
_PIPELINE = None  # type: ignore[var-annotated]
_SHADER_SRC: str | None = None


def _probe_gpu() -> bool:
    """One-shot adapter+device probe; idempotent."""
    global _GPU_PROBED, _GPU_AVAILABLE, _WGPU, _DEVICE, _QUEUE, _PIPELINE, _SHADER_SRC
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

    _WGPU = wgpu
    _DEVICE = device
    _QUEUE = device.queue
    _PIPELINE = pipeline
    _SHADER_SRC = src
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
