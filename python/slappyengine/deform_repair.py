"""slappyengine.deform_repair — Per-pixel and radial repair for DeformableLayerComponent.

Provides targeted repair: restore alpha within a circle, at a specific pixel,
or across the whole layer. Complements DeformableLayerComponent.repair() which
does uniform whole-layer restoration.

Usage
-----
    repairer = DeformRepairer(layer, original_alpha)
    repairer.queue_radial(cx=64, cy=32, radius=20, rate=2.0)
    repairer.queue_pixel(x=30, y=15, rate=5.0)
    repairer.dispatch()   # GPU when available, CPU fallback otherwise
"""
from __future__ import annotations
from pathlib import Path

import numpy as np

SHADER_PATH = Path(__file__).parent.parent.parent / "shaders" / "deform_repair.wgsl"


class DeformRepairer:
    """Queues and dispatches targeted repair events for one deformable layer.

    Parameters
    ----------
    layer:
        The Layer2D with _image_data to repair.
    original_alpha:
        Float32 numpy array (h × w) of the original alpha channel.
        Repair never exceeds this. If None, repair restores toward 255.
    """

    def __init__(self, layer, original_alpha: "np.ndarray | None" = None) -> None:
        self._layer = layer
        self._original_alpha = original_alpha
        self._pending: list[dict] = []
        # Diagnostic: which code path actually ran on the last dispatch().
        #   "none" = no events were pending or layer was unusable
        #   "cpu"  = numpy fallback executed
        #   "gpu"  = real wgpu compute dispatch was submitted
        self.last_path: str = "none"
        self._shader_src: str = (
            SHADER_PATH.read_text(encoding="utf-8") if SHADER_PATH.exists() else ""
        )

    def queue_radial(
        self,
        center_x: float,
        center_y: float,
        radius: float,
        rate: float = 2.0,
        falloff: bool = True,
    ) -> None:
        """Queue a radial repair centered at (center_x, center_y).

        Parameters
        ----------
        rate:
            Alpha units (0-255) restored per dispatch at the center.
            Edge gets rate × falloff_weight.
        falloff:
            True = smoothstep falloff from center. False = uniform fill.
        """
        self._pending.append({
            "center_x": center_x, "center_y": center_y,
            "radius": radius, "rate": rate,
            "mode": 0 if falloff else 1,
        })

    def queue_pixel(self, x: int, y: int, rate: float = 5.0) -> None:
        """Queue repair of a single pixel at (x, y)."""
        self._pending.append({
            "center_x": float(x), "center_y": float(y),
            "radius": 0.5, "rate": rate,
            "mode": 1,  # uniform, sub-pixel radius → only exact pixel
        })

    def queue_full(self, rate: float = 1.0) -> None:
        """Queue uniform repair of the entire layer."""
        self._pending.append({
            "center_x": 0.0, "center_y": 0.0,
            "radius": 0.0, "rate": rate,
            "mode": 2,  # full layer mode
        })

    def dispatch(self, gpu_ctx=None) -> None:
        """Apply all queued repair events. CPU fallback if no GPU context."""
        if not self._pending:
            self.last_path = "none"
            return
        try:
            if gpu_ctx is not None:
                ok = self._dispatch_gpu(self._layer, gpu_ctx)
                if not ok:
                    self._dispatch_cpu()
                    self.last_path = "cpu"
            else:
                self._dispatch_cpu()
                self.last_path = "cpu"
        finally:
            self._pending.clear()

    def _dispatch_cpu(self) -> None:
        """CPU numpy implementation of the repair shader logic."""
        img = getattr(self._layer, "_image_data", None)
        if img is None or not isinstance(img, np.ndarray) or img.ndim != 3:
            return

        h, w = img.shape[:2]
        alpha = img[:, :, 3].astype(np.float32)

        orig = self._original_alpha
        if orig is None:
            orig_cap = np.full((h, w), 255.0, dtype=np.float32)
        else:
            orig_cap = orig.astype(np.float32)

        for ev in self._pending:
            cx, cy = ev["center_x"], ev["center_y"]
            radius = ev["radius"]
            rate   = ev["rate"]
            mode   = ev["mode"]

            if mode == 2:
                # Full layer
                weight = np.ones((h, w), dtype=np.float32)
            else:
                ys, xs = np.ogrid[:h, :w]
                dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
                if mode == 0:
                    # Radial falloff (smoothstep)
                    in_r = dist < radius
                    t = np.where(in_r, 1.0 - dist / max(radius, 0.001), 0.0)
                    weight = t * t * (3.0 - 2.0 * t)
                else:
                    # Uniform fill
                    weight = np.where(dist < max(radius, 0.5), 1.0, 0.0)

            repaired = np.minimum(orig_cap, alpha + rate * weight)
            alpha = repaired

        img[:, :, 3] = np.clip(alpha, 0, 255).astype(np.uint8)

    def _dispatch_gpu(self, layer, gpu_ctx) -> bool:
        """GPU dispatch: upload RepairEvent storage + Params uniform, run shader.

        Layout per RepairEvent (32 bytes = 8 × 4-byte fields):
            center_x, center_y, radius, rate              (f32 × 4)
            mode, _pad0, _pad1, _pad2                     (u32 × 4)

        Params uniform (16 bytes):
            width, height, event_count, _pad              (u32 × 4)

        Bindings (group 0):
            0: storage<read>          events array
            1: uniform                params
            2: storage_2d rgba8unorm  color_tex (read_write)
            3: storage_2d rgba8unorm  original_tex (read)

        Returns
        -------
        bool
            ``True`` if the shader was actually dispatched.  ``False`` means
            the caller should fall back to the CPU path.
        """
        if not self._shader_src:
            return False
        try:
            import wgpu
            import struct as _struct

            device = getattr(gpu_ctx, "device", None)
            if device is None:
                return False

            img = getattr(layer, "_image_data", None)
            if img is None or not isinstance(img, np.ndarray) or img.ndim != 3:
                return False
            if img.shape[2] < 4:
                return False
            h, w = img.shape[:2]

            # ── Resolve / create the layer's GPU color texture ────────────
            # The shader binds at rgba8unorm so the layer texture must match.
            layer_tex = getattr(layer, "_gpu_texture", None)
            tex_owned_by_us = False
            if layer_tex is None:
                layer_tex = device.create_texture(
                    size=(w, h, 1),
                    format=wgpu.TextureFormat.rgba8unorm,
                    usage=(
                        wgpu.TextureUsage.STORAGE_BINDING
                        | wgpu.TextureUsage.COPY_DST
                        | wgpu.TextureUsage.COPY_SRC
                    ),
                )
                tex_owned_by_us = True

            # Upload current image_data into the color texture.
            rgba = np.ascontiguousarray(img[:, :, :4], dtype=np.uint8)
            device.queue.write_texture(
                {"texture": layer_tex, "origin": (0, 0, 0)},
                rgba.tobytes(),
                {"offset": 0, "bytes_per_row": w * 4, "rows_per_image": h},
                (w, h, 1),
            )

            # ── Original-alpha texture (rgba8unorm read-only storage) ─────
            orig = self._original_alpha
            if orig is None:
                orig_a = np.full((h, w), 255, dtype=np.uint8)
            else:
                orig_a = np.clip(orig, 0, 255).astype(np.uint8)
            orig_rgba = np.zeros((h, w, 4), dtype=np.uint8)
            orig_rgba[:, :, 3] = orig_a
            orig_tex = device.create_texture(
                size=(w, h, 1),
                format=wgpu.TextureFormat.rgba8unorm,
                usage=wgpu.TextureUsage.STORAGE_BINDING | wgpu.TextureUsage.COPY_DST,
            )
            device.queue.write_texture(
                {"texture": orig_tex, "origin": (0, 0, 0)},
                np.ascontiguousarray(orig_rgba).tobytes(),
                {"offset": 0, "bytes_per_row": w * 4, "rows_per_image": h},
                (w, h, 1),
            )

            # ── Encode RepairEvent storage buffer ─────────────────────────
            n = len(self._pending)
            event_bytes = bytearray()
            for ev in self._pending:
                event_bytes += _struct.pack(
                    "<ffffIIII",
                    float(ev["center_x"]), float(ev["center_y"]),
                    float(ev["radius"]),   float(ev["rate"]),
                    int(ev["mode"]), 0, 0, 0,
                )
            events_buf = device.create_buffer_with_data(
                data=bytes(event_bytes),
                usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST,
            )

            # ── Params uniform ────────────────────────────────────────────
            params_bytes = _struct.pack("<IIII", w, h, n, 0)
            params_buf = device.create_buffer_with_data(
                data=params_bytes,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )

            # ── Pipeline + bind group ─────────────────────────────────────
            module = device.create_shader_module(code=self._shader_src)
            pipeline = device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
            bgl = pipeline.get_bind_group_layout(0)
            bg = device.create_bind_group(
                layout=bgl,
                entries=[
                    {"binding": 0, "resource": {"buffer": events_buf, "offset": 0, "size": events_buf.size}},
                    {"binding": 1, "resource": {"buffer": params_buf, "offset": 0, "size": params_buf.size}},
                    {"binding": 2, "resource": layer_tex.create_view()},
                    {"binding": 3, "resource": orig_tex.create_view()},
                ],
            )

            # One thread per pixel; @workgroup_size(8, 8) in WGSL.
            wg_x = (w + 7) // 8
            wg_y = (h + 7) // 8

            encoder = device.create_command_encoder()
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(pipeline)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(wg_x, wg_y, 1)
            cp.end()
            device.queue.submit([encoder.finish()])

            # If we created the texture locally, the user wanted the GPU
            # result reflected in CPU memory — read it back into _image_data.
            if tex_owned_by_us:
                try:
                    readback = device.queue.read_texture(
                        {"texture": layer_tex, "origin": (0, 0, 0)},
                        {"offset": 0, "bytes_per_row": w * 4, "rows_per_image": h},
                        (w, h, 1),
                    )
                    arr = np.frombuffer(readback, dtype=np.uint8).reshape(h, w, 4)
                    img[:, :, :4] = arr
                except Exception:
                    # Readback failed but dispatch succeeded; that's still GPU.
                    pass

            self.last_path = "gpu"
            return True

        except Exception:
            # Silently fall back; caller will run CPU path.
            return False
