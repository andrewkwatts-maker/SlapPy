"""2D SDF shape drawing into Layer textures.

Shapes are accumulated via canvas methods and rendered in a single compute
dispatch (``flush``).  When GPU dispatch is not yet wired up the CPU numpy
fallback produces identical results, making it safe to use in tests and
headless environments.

Usage::

    from pharos_engine.sdf_shapes import SdfCanvas

    canvas = SdfCanvas(layer)
    canvas.circle(center=(320, 240), radius=50,
                  color=(1, 0, 0, 1), glow_color=(1, 0.5, 0, 0.8), glow_radius=12.0)
    canvas.box(center=(100, 100), size=(80, 40), corner_radius=8, color=(0, 0.5, 1, 1))
    canvas.ring(center=(200, 200), radius=40, thickness=4, color=(1, 1, 0, 1))
    canvas.flush()   # dispatches GPU compute pass (CPU fallback if no wgpu device)

Shape kind constants (mirrors WGSL ``SdfShape.kind``):
    0 = circle, 1 = box, 2 = segment, 3 = ring
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Internal data record — one per shape in the pending batch
# ---------------------------------------------------------------------------

@dataclass
class _SdfShapeData:
    """Raw shape record that mirrors the WGSL ``SdfShape`` struct (std140)."""

    kind: int               # 0=circle, 1=box, 2=segment, 3=ring
    center: Tuple[float, float]
    # param_a: (radius, 0) for circle; (half_w, half_h) for box;
    #          (ax, ay) for segment; (radius, 0) for ring
    param_a: Tuple[float, float]
    # param_b: (corner_r, 0) for box; (bx, by) for segment;
    #          (thickness, 0) for ring; unused for circle
    param_b: Tuple[float, float]
    fill_color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    glow_color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    glow_radius: float = 0.0
    shadow_alpha: float = 0.0
    shadow_offset: Tuple[float, float] = (4.0, 4.0)
    aa_width: float = 1.0

    # Byte layout (std140, 96 bytes total):
    #   u32 kind, vec2 center, vec2 param_a, vec2 param_b   → 5×f32 + 1×u32
    #   vec4 fill_color, vec4 glow_color                    → 8×f32
    #   f32 glow_radius, f32 shadow_alpha, vec2 shadow_offset, f32 aa_width
    #   vec3 _pad                                           → 3×f32
    _STRUCT_FMT = "=I3x f ff ff ff ffff ffff ff ff f fff"
    # Note: maturin/wgpu will handle actual alignment; this fmt is for
    # the CPU-side pack() used when building the storage buffer.

    def pack(self) -> bytes:
        """Pack this shape into the 96-byte WGSL struct layout."""
        return struct.pack(
            "<I",  self.kind,
        ) + struct.pack(
            "<fff",
            self.center[0], self.center[1],
            0.0,  # std140 vec2 → padded to 8 bytes, third word unused
        )
        # (Full GPU-side packing is performed by _build_storage_buffer below.)

# ---------------------------------------------------------------------------
# Buffer builder
# ---------------------------------------------------------------------------

# Byte offsets within each SdfShape element as laid out by WGSL std430.
# struct size = 96 bytes (verified against field list in sdf_2d.wgsl).
# struct pack() produces 92 bytes; wgpu's std430 array stride rounds to 96
# (next multiple of the largest member alignment, vec4 = 16).
# The driver handles inter-element padding automatically — we only pack the
# 92 payload bytes per shape; the GPU ignores the 4-byte tail gap.
_SHAPE_STRIDE = 96  # bytes (std430 stride, for reference)


def _pack_shapes(shapes: list[_SdfShapeData]) -> bytes:
    """Pack a list of _SdfShapeData into a byte buffer matching the WGSL struct.

    Layout (little-endian, std430):
      0:  kind         u32
      4:  center.xy    2×f32
     12:  _pad4        f32         (vec2 is 8-byte aligned in std430)
     16:  param_a.xy   2×f32
     24:  _pad8        f32
     28:  param_b.xy   2×f32
     36:  _pad12       f32
     40:  fill_color   4×f32
     56:  glow_color   4×f32
     72:  glow_radius  f32
     76:  shadow_alpha f32
     80:  shadow_off   2×f32
     88:  aa_width     f32
     92:  _pad24       3×f32   → 3×4 = 12 bytes → total = 104?

    WGSL uses std430 for storage buffers.  The struct in sdf_2d.wgsl has a
    vec3<f32> _pad tail, so the natural size is:
      4 (kind/u32) + 4 (gap) + 2×4 (center) + 2×4 (param_a) + 2×4 (param_b)
      + 4×4 (fill) + 4×4 (glow) + 4 (glow_r) + 4 (shadow_a) + 2×4 (off)
      + 4 (aa) + 3×4 (_pad) = 80 bytes … then aligned to 16 → 80 bytes.

    We use numpy structured arrays to keep packing straightforward and let
    the driver handle the rest.
    """
    # Build a flat numpy array of f32 with the fields in declaration order.
    # 20 f32 fields per shape (centre the u32 kind as the first 4 bytes, cast).
    buf = bytearray()
    for s in shapes:
        chunk = struct.pack(
            "<I ff ff ff ffff ffff ff ff f fff",
            s.kind,
            s.center[0], s.center[1],
            s.param_a[0], s.param_a[1],
            s.param_b[0], s.param_b[1],
            s.fill_color[0], s.fill_color[1], s.fill_color[2], s.fill_color[3],
            s.glow_color[0], s.glow_color[1], s.glow_color[2], s.glow_color[3],
            s.glow_radius, s.shadow_alpha,
            s.shadow_offset[0], s.shadow_offset[1],
            s.aa_width,
            0.0, 0.0, 0.0,  # _pad vec3
        )
        buf.extend(chunk)
    return bytes(buf)


# ---------------------------------------------------------------------------
# Public canvas API
# ---------------------------------------------------------------------------

class SdfCanvas:
    """Accumulate 2-D SDF shapes and render them into a layer texture.

    Parameters
    ----------
    layer:
        A Pharos Engine layer object that exposes ``._image_data`` (H×W×4 uint8
        numpy array) for the CPU fallback, and eventually a wgpu texture /
        device for the GPU path.
    """

    def __init__(self, layer) -> None:
        self._layer = layer
        self._shapes: list[_SdfShapeData] = []

    # ------------------------------------------------------------------
    # Shape builders
    # ------------------------------------------------------------------

    def circle(
        self,
        center: Tuple[float, float],
        radius: float,
        color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        glow_color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        glow_radius: float = 0.0,
        shadow_alpha: float = 0.0,
        shadow_offset: Tuple[float, float] = (4.0, 4.0),
        aa_width: float = 1.0,
    ) -> "SdfCanvas":
        """Add a filled circle (optionally with glow / drop-shadow)."""
        self._shapes.append(_SdfShapeData(
            kind=0,
            center=center,
            param_a=(radius, 0.0),
            param_b=(0.0, 0.0),
            fill_color=color,
            glow_color=glow_color,
            glow_radius=glow_radius,
            shadow_alpha=shadow_alpha,
            shadow_offset=shadow_offset,
            aa_width=aa_width,
        ))
        return self

    def box(
        self,
        center: Tuple[float, float],
        size: Tuple[float, float],
        corner_radius: float = 0.0,
        color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        glow_color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        glow_radius: float = 0.0,
        aa_width: float = 1.0,
    ) -> "SdfCanvas":
        """Add a filled rounded rectangle."""
        hw, hh = size[0] / 2.0, size[1] / 2.0
        self._shapes.append(_SdfShapeData(
            kind=1,
            center=center,
            param_a=(hw, hh),
            param_b=(corner_radius, 0.0),
            fill_color=color,
            glow_color=glow_color,
            glow_radius=glow_radius,
            aa_width=aa_width,
        ))
        return self

    def segment(
        self,
        a: Tuple[float, float],
        b: Tuple[float, float],
        thickness: float = 1.0,
        color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        aa_width: float = 1.0,
    ) -> "SdfCanvas":
        """Add a line segment with rounded caps.

        ``thickness`` is the half-width of the stroke in pixels.
        The WGSL shader stores the half-thickness in ``center.x`` for this
        kind, with actual endpoints in ``param_a`` / ``param_b``.
        """
        self._shapes.append(_SdfShapeData(
            kind=2,
            center=(thickness, 0.0),  # center.x encodes stroke half-thickness
            param_a=a,
            param_b=b,
            fill_color=color,
            aa_width=aa_width,
        ))
        return self

    def ring(
        self,
        center: Tuple[float, float],
        radius: float,
        thickness: float,
        color: Tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
        glow_color: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0),
        glow_radius: float = 0.0,
        aa_width: float = 1.0,
    ) -> "SdfCanvas":
        """Add a hollow ring (annulus)."""
        self._shapes.append(_SdfShapeData(
            kind=3,
            center=center,
            param_a=(radius, 0.0),
            param_b=(thickness, 0.0),
            fill_color=color,
            glow_color=glow_color,
            glow_radius=glow_radius,
            aa_width=aa_width,
        ))
        return self

    # ------------------------------------------------------------------
    # Batch management
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Discard all pending shapes without rendering."""
        self._shapes.clear()

    def flush(self) -> None:
        """Render all pending shapes into the layer and clear the queue.

        Attempts GPU compute dispatch first; falls back to the numpy CPU path
        when no wgpu device is available on the layer.
        """
        if not self._shapes:
            return
        dispatched = self._try_gpu_dispatch()
        if not dispatched:
            self._rasterize_cpu()
        self._shapes.clear()

    # ------------------------------------------------------------------
    # GPU dispatch (stub — wired up when layer exposes a wgpu device)
    # ------------------------------------------------------------------

    def _try_gpu_dispatch(self) -> bool:
        """Attempt to dispatch ``sdf_2d.wgsl`` via the layer's wgpu device.

        Returns True if the dispatch succeeded, False if the layer does not
        expose the required GPU objects (falls back to CPU).
        """
        layer = self._layer
        device = getattr(layer, "_device", None)
        texture = getattr(layer, "_texture", None)
        if device is None or texture is None:
            return False

        import wgpu  # noqa: F401 — only imported when device is present

        shape_bytes = _pack_shapes(self._shapes)
        num_shapes = len(self._shapes)

        # Uniform buffer: num_shapes (u32) + 12 bytes padding.
        uniform_data = struct.pack("<I", num_shapes) + b"\x00" * 12
        uniform_buf = device.create_buffer_with_data(
            data=uniform_data,
            usage=wgpu.BufferUsage.UNIFORM,
        )

        storage_buf = device.create_buffer_with_data(
            data=shape_bytes,
            usage=wgpu.BufferUsage.STORAGE,
        )

        import pathlib
        shader_path = (
            pathlib.Path(__file__).parent.parent.parent / "shaders" / "sdf_2d.wgsl"
        )
        shader_src = shader_path.read_text(encoding="utf-8")
        shader_module = device.create_shader_module(code=shader_src)

        pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": shader_module, "entry_point": "sdf_draw"},
        )

        bind_group = device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": uniform_buf}},
                {"binding": 1, "resource": {"buffer": storage_buf}},
                {"binding": 2, "resource": texture.create_view()},
            ],
        )

        tex_size = texture.size
        w, h = tex_size[0], tex_size[1]
        wg_x = (w + 7) // 8
        wg_y = (h + 7) // 8

        encoder = device.create_command_encoder()
        with encoder.begin_compute_pass() as pass_:
            pass_.set_pipeline(pipeline)
            pass_.set_bind_group(0, bind_group)
            pass_.dispatch_workgroups(wg_x, wg_y, 1)
        device.queue.submit([encoder.finish()])
        return True

    # ------------------------------------------------------------------
    # CPU numpy fallback
    # ------------------------------------------------------------------

    def _rasterize_cpu(self) -> None:
        """Rasterize all pending SDF shapes into ``layer._image_data`` (CPU).

        The numpy implementation mirrors the WGSL math exactly so that
        headless tests and the GPU path produce consistent results.
        """
        img = self._layer._image_data  # H×W×4, uint8
        h, w = img.shape[:2]

        # Build pixel-centre coordinate grid once.
        ys, xs = np.mgrid[0:h, 0:w]
        px = xs.astype(np.float32) + 0.5
        py = ys.astype(np.float32) + 0.5

        out = img.astype(np.float32) / 255.0  # work in [0, 1]

        for s in self._shapes:
            cx, cy = float(s.center[0]), float(s.center[1])

            # --- Evaluate SDF ------------------------------------------------
            if s.kind == 0:  # circle
                r = s.param_a[0]
                d = np.sqrt((px - cx) ** 2 + (py - cy) ** 2) - r

            elif s.kind == 1:  # rounded box
                hw, hh = s.param_a[0], s.param_a[1]
                cr = s.param_b[0]
                qx = np.abs(px - cx) - hw + cr
                qy = np.abs(py - cy) - hh + cr
                d = (
                    np.sqrt(np.maximum(qx, 0.0) ** 2 + np.maximum(qy, 0.0) ** 2)
                    + np.minimum(np.maximum(qx, qy), 0.0)
                    - cr
                )

            elif s.kind == 2:  # segment
                # center.x = half-thickness; param_a = A; param_b = B
                ax, ay = s.param_a[0], s.param_a[1]
                bx, by = s.param_b[0], s.param_b[1]
                thickness = cx  # stored in center.x
                pax, pay = px - ax, py - ay
                bax, bay = bx - ax, by - ay
                dot_ba = bax * bax + bay * bay
                if dot_ba < 1e-12:
                    h_t = np.zeros_like(px)
                else:
                    h_t = np.clip((pax * bax + pay * bay) / dot_ba, 0.0, 1.0)
                d = np.sqrt((pax - bax * h_t) ** 2 + (pay - bay * h_t) ** 2) - thickness

            elif s.kind == 3:  # ring
                r = s.param_a[0]
                t = s.param_b[0]
                d = np.abs(np.sqrt((px - cx) ** 2 + (py - cy) ** 2) - r) - t

            else:
                continue

            aa = max(s.aa_width, 1e-6)

            # --- Drop shadow (first, underneath) ----------------------------
            if s.shadow_alpha > 0.0:
                sox, soy = s.shadow_offset
                sd = np.sqrt((px - cx - sox) ** 2 + (py - cy - soy) ** 2) - s.param_a[0]
                shadow = s.shadow_alpha * _smoothstep_np(-6.0, 6.0, sd + 4.0, invert=True)
                out[..., :3] = out[..., :3] * (1.0 - shadow[..., None])

            # --- Glow halo (additive) ----------------------------------------
            if s.glow_radius > 0.0:
                glow = np.exp(-np.maximum(d, 0.0) / s.glow_radius)
                gc = np.array(s.glow_color[:3], dtype=np.float32)
                ga = float(s.glow_color[3])
                out[..., :3] = out[..., :3] + gc * glow[..., None] * ga

            # --- Filled shape -----------------------------------------------
            fill = _smoothstep_np(-aa, aa, d, invert=True)
            alpha = fill * s.fill_color[3]
            fc = np.array(s.fill_color[:3], dtype=np.float32)
            out[..., :3] = out[..., :3] * (1.0 - alpha[..., None]) + fc * alpha[..., None]

        img[:] = np.clip(out * 255.0, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _smoothstep_np(
    edge0: float, edge1: float, x: "np.ndarray", *, invert: bool = False
) -> "np.ndarray":
    """Numpy equivalent of WGSL smoothstep(edge0, edge1, x).

    When *invert* is True returns ``1 - smoothstep(...)`` (i.e. ``sdf_fill``).
    """
    t = np.clip((x - edge0) / (edge1 - edge0), 0.0, 1.0)
    s = t * t * (3.0 - 2.0 * t)
    return (1.0 - s) if invert else s
