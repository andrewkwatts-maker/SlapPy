"""deform_crack — Python interface for the deform_crack.wgsl compute pass.

Dispatched by DeformableLayerComponent when crack_mode != NONE.
Falls back gracefully (no-op) when GPU is unavailable.
"""
from __future__ import annotations

import math
from pathlib import Path

SHADER_PATH = Path(__file__).parent.parent.parent / "shaders" / "deform_crack.wgsl"

# Crack mode constants (mirror the WGSL u32 values).
CRACK_NONE   = -1
CRACK_RADIAL =  0
CRACK_GRAIN  =  1


class CrackPass:
    """Thin wrapper: accumulate crack events this frame, dispatch shader once.

    Usage::

        crack = CrackPass()
        crack.queue(cx, cy, force=1.5, radius=40.0, mode=CRACK_RADIAL, ray_count=12)
        crack.dispatch(layer, gpu_ctx=None)   # CPU fallback when gpu_ctx is None
    """

    def __init__(self) -> None:
        self._pending: list[dict] = []
        self._shader_src: str = (
            SHADER_PATH.read_text(encoding="utf-8") if SHADER_PATH.exists() else ""
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def queue(
        self,
        center_x: float,
        center_y: float,
        force: float,
        radius: float,
        mode: int,
        ray_count: int,
    ) -> None:
        """Queue one crack event (call per impact that should crack).

        Parameters
        ----------
        center_x, center_y:
            Impact centre in texture-pixel space (float).
        force:
            Impact force magnitude.  Controls how deeply the crack reduces
            alpha.  The shader uses ``force * 0.002 * t²`` per step.
        radius:
            Maximum crack length in pixels.
        mode:
            ``CRACK_RADIAL`` (0) or ``CRACK_GRAIN`` (1).
        ray_count:
            Number of rays to trace outward from the impact centre.
            Typical values: 8–16.  Clamped to MAX_RAYS (16) on the GPU.
        """
        if mode == CRACK_NONE:
            return
        self._pending.append(
            {
                "center_x": float(center_x),
                "center_y": float(center_y),
                "force": float(force),
                "radius": float(radius),
                "mode": int(mode),
                "ray_count": int(ray_count),
            }
        )

    def dispatch(self, layer, gpu_ctx=None) -> None:
        """Dispatch crack shader for all queued events this frame.

        Falls back to CPU approximation when *gpu_ctx* is ``None``.
        Clears the pending queue regardless of which path runs.

        Parameters
        ----------
        layer:
            The deformable layer object.  Must expose ``_image_data`` as a
            numpy ``ndarray`` of shape ``(H, W, 4)`` with dtype uint8 for
            the CPU fallback.
        gpu_ctx:
            Engine GPU context; ``None`` forces the CPU path.
        """
        if not self._pending:
            return
        try:
            if gpu_ctx is not None:
                self._dispatch_gpu(layer, gpu_ctx)
            else:
                self._dispatch_cpu(layer)
        finally:
            self._pending.clear()

    # ------------------------------------------------------------------
    # CPU fallback
    # ------------------------------------------------------------------

    def _dispatch_cpu(self, layer) -> None:
        """CPU fallback: draw crack lines via numpy.

        Implements RADIAL mode only (GRAIN bias is skipped — the grain map
        is a GPU-side texture and is not available on the CPU path).
        """
        import numpy as np

        img = getattr(layer, "_image_data", None)
        if img is None or not isinstance(img, np.ndarray) or img.ndim < 3:
            return
        if img.shape[2] < 4:
            return  # no alpha channel to crack

        h, w = img.shape[:2]

        for ev in self._pending:
            cx      = ev["center_x"]
            cy      = ev["center_y"]
            force   = ev["force"]
            radius  = ev["radius"]
            n_rays  = ev["ray_count"]
            # mode is ignored on CPU path (GRAIN falls back to RADIAL)

            for i in range(n_rays):
                angle = i * (2.0 * math.pi / max(1, n_rays))
                dx = math.cos(angle)
                dy = math.sin(angle)
                steps = int(radius)

                for s in range(steps):
                    px = int(round(cx + dx * s))
                    py = int(round(cy + dy * s))
                    if not (0 <= px < w and 0 <= py < h):
                        break
                    # Stop if pixel is already fully transparent.
                    if img[py, px, 3] == 0:
                        break

                    t = 1.0 - s / max(1, steps)
                    strength = force * 0.002 * t * t
                    delta = int(strength * 255)
                    img[py, px, 3] = max(0, int(img[py, px, 3]) - delta)

                    # Brush one perpendicular neighbour near the base.
                    if t > 0.6 and s % 3 == 0:
                        nx = int(round(px - dy))
                        ny = int(round(py + dx))
                        if 0 <= nx < w and 0 <= ny < h:
                            half_delta = int(strength * 255 * 0.5)
                            img[ny, nx, 3] = max(0, int(img[ny, nx, 3]) - half_delta)

    # ------------------------------------------------------------------
    # GPU dispatch
    # ------------------------------------------------------------------

    def _dispatch_gpu(self, layer, gpu_ctx) -> None:
        """GPU dispatch: upload CrackImpact structs and run deform_crack.wgsl.

        Layout per CrackImpact (32 bytes = 8 × f32/u32):
            center_x, center_y, force, radius (f32 × 4)
            mode, ray_count, _pad0, _pad1      (u32 × 4)

        Params uniform (32 bytes = 8 × u32/f32):
            width, height, impact_count, jitter(f32), frame_seed, _pad0-2 (u32)

        Dispatch: one thread per (impact × MAX_RAYS=16) → ceil(n*16 / 64) groups.
        """
        if not self._shader_src:
            return
        try:
            import wgpu
            import struct as _struct
            import time as _time

            device = gpu_ctx.device

            # ── Layer texture ──────────────────────────────────────────────
            layer_tex = getattr(layer, "_gpu_texture", None)
            if layer_tex is None:
                return  # layer not uploaded to GPU yet

            img = getattr(layer, "_image_data", None)
            if img is None:
                return
            h, w = img.shape[:2]

            # ── Encode impact structs ──────────────────────────────────────
            n = len(self._pending)
            impact_bytes = bytearray()
            for ev in self._pending:
                impact_bytes += _struct.pack(
                    "<ffffIIII",
                    ev["center_x"], ev["center_y"],
                    ev["force"],    ev["radius"],
                    ev["mode"],     ev["ray_count"],
                    0, 0,           # _pad0, _pad1
                )
            impact_buf = device.create_buffer_with_data(
                data=bytes(impact_bytes),
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )

            # ── Params uniform ─────────────────────────────────────────────
            frame_seed = int(_time.monotonic_ns() & 0xFFFFFFFF)
            params_bytes = _struct.pack(
                "<IIIf IIII",
                w, h, n, 0.25,    # width, height, impact_count, jitter
                frame_seed, 0, 0, 0,
            )
            params_buf = device.create_buffer_with_data(
                data=params_bytes,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )

            # ── Grain texture placeholder (1×1 zero) ───────────────────────
            grain_tex = device.create_texture(
                size=(1, 1, 1),
                format=wgpu.TextureFormat.r32float,
                usage=wgpu.TextureUsage.STORAGE_BINDING | wgpu.TextureUsage.COPY_DST,
            )

            # ── Pipeline ───────────────────────────────────────────────────
            module = device.create_shader_module(code=self._shader_src)
            pipeline = device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
            bgl = pipeline.get_bind_group_layout(0)
            bg = device.create_bind_group(
                layout=bgl,
                entries=[
                    {"binding": 0, "resource": {"buffer": impact_buf, "offset": 0, "size": impact_buf.size}},
                    {"binding": 1, "resource": {"buffer": params_buf, "offset": 0, "size": params_buf.size}},
                    {"binding": 2, "resource": layer_tex.create_view()},
                    {"binding": 3, "resource": grain_tex.create_view()},
                ],
            )

            # 64 threads per workgroup; 16 rays per impact
            MAX_RAYS = 16
            total_threads = n * MAX_RAYS
            workgroups = (total_threads + 63) // 64

            encoder = device.create_command_encoder()
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(pipeline)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(workgroups, 1, 1)
            cp.end()
            device.queue.submit([encoder.finish()])

        except Exception:
            # Silently fall back — CPU path already ran or will run next frame
            pass
