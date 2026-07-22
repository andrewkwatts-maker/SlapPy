"""collision_pixel — GPU-accelerated per-pixel collision detection.

Compares the alpha channels of two Layer2D textures within their overlapping
axis-aligned bounding boxes and returns a contact normal derived from the
alpha gradient of layer A.

Usage
-----
    from pharos_engine.collision_pixel import PixelCollisionPass, PixelContactResult

    pass_ = PixelCollisionPass()

    result: PixelContactResult = pass_.test(
        gpu,
        layer_a_tex,  rect_a,   # (x, y, w, h) world pixels
        layer_b_tex,  rect_b,
        alpha_threshold=128,
    )

    if result.hit:
        nx, ny = result.normal          # contact normal pointing from B into A
        print(f"collision: {result.contact_pixels} pixels, normal=({nx:.3f}, {ny:.3f})")

Graceful degradation
--------------------
* If wgpu is unavailable at import time the module still loads; ``test()``
  returns a no-hit ``PixelContactResult``.
* If the shader file is missing the same fallback applies — no exception is
  raised.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

# ---------------------------------------------------------------------------
# Optional wgpu import — degrade gracefully if not installed.
# ---------------------------------------------------------------------------

try:
    import wgpu as _wgpu
    _WGPU_OK = True
except Exception:  # noqa: BLE001
    _wgpu = None  # type: ignore[assignment]
    _WGPU_OK = False

# Path to the bundled WGSL shader, resolved relative to *this* file.
_SHADER_PATH: Path = (
    Path(__file__).parent / "compute" / "defaults" / "pixel_collision.wgsl"
)

if TYPE_CHECKING:
    from pharos_engine.gpu.context import GPUContext


# ---------------------------------------------------------------------------
# Public result type
# ---------------------------------------------------------------------------

@dataclass
class PixelContactResult:
    """Result of a per-pixel collision query.

    Attributes
    ----------
    hit:
        ``True`` when at least one solid pixel overlaps in both textures.
    contact_pixels:
        Number of solid pixels that overlap.
    normal:
        Contact normal ``(nx, ny)`` pointing from layer B into layer A,
        derived from the alpha gradient of layer A averaged over all
        collision pixels.  ``(0.0, 0.0)`` when there is no contact or the
        gradient magnitude is negligibly small.
    """
    hit: bool
    contact_pixels: int
    normal: tuple[float, float]

    # Backwards-compat: Ochema Circuit's Sprint 5 collision suite reads
    # ``result.depth`` as a synonym for ``contact_pixels`` (see
    # tests/test_sprint5_collision.py:64, 101 and 8 additional call sites
    # across systems/collision_system.py). F1's pass returned an alias
    # attribute; the modern struct dropped it. Restoring as a read-only
    # property preserves both spellings without duplicating storage.
    # See docs/game_compat_2026_07_07.md § 11.4 (PixelContactResult drift).
    # DO NOT REMOVE without a v1.0 deprecation cycle.
    @property
    def depth(self) -> int:
        return self.contact_pixels


_NO_CONTACT = PixelContactResult(hit=False, contact_pixels=0, normal=(0.0, 0.0))


# ---------------------------------------------------------------------------
# Internal layout constants
# ---------------------------------------------------------------------------

# CollisionParams uniform layout (all u32, tightly packed):
#   a_x, a_y, a_w, a_h   — 4 × u32
#   b_x, b_y, b_w, b_h   — 4 × u32
#   alpha_threshold       — 1 × u32
#   _pad                  — 3 × u32  (vec3u padding)
# Total: 12 × 4 = 48 bytes
_PARAMS_FORMAT = "12I"   # 12 unsigned ints
_PARAMS_SIZE   = struct.calcsize(_PARAMS_FORMAT)   # 48 bytes

# CollisionResult storage layout (packed atomics read as plain integers):
#   hit             — u32 / i32 → 4 bytes
#   contact_pixels  — u32       → 4 bytes
#   normal_x_acc    — i32       → 4 bytes
#   normal_y_acc    — i32       → 4 bytes
# Total: 16 bytes
_RESULT_FORMAT = "2I2i"  # hit (u32), contact_pixels (u32), nx_acc (i32), ny_acc (i32)
_RESULT_SIZE   = struct.calcsize(_RESULT_FORMAT)   # 16 bytes


# ---------------------------------------------------------------------------
# PixelCollisionPass
# ---------------------------------------------------------------------------

class PixelCollisionPass:
    """Manages the per-pixel collision compute pipeline.

    The pipeline (shader module + bind-group layout) is compiled once on first
    use and reused for subsequent calls, so construction is cheap.

    Parameters
    ----------
    None — call :meth:`test` directly.
    """

    def __init__(self) -> None:
        self._pipeline: object | None = None   # wgpu.GPUComputePipeline
        self._source: str | None = None
        self._ready: bool = False

        if not _WGPU_OK:
            return
        if not _SHADER_PATH.exists():
            return

        try:
            self._source = _SHADER_PATH.read_text(encoding="utf-8")
            self._ready = True
        except OSError:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # Backwards-compat: Ochema Circuit calls ``PixelCollisionPass.test(a, b)``
    # unbound (class-level) with only two entity arguments. The legacy form
    # inspects ``entity.layers[0]._image_data`` alpha overlap at the current
    # position — no GPU context needed. The modern GPU form remains the
    # primary implementation via ``self._test_gpu(...)``. See
    # ``_test_entities_cpu`` below for the fallback.
    # DO NOT REMOVE without a v1.0 deprecation cycle.

    @staticmethod
    def _test_entities_cpu(entity_a, entity_b, alpha_threshold: int = 128) -> PixelContactResult:
        """Backwards-compat: 2-entity alpha-overlap contact test.

        Returns ``PixelContactResult`` with the same shape as the GPU form.
        Position is read from ``entity.position`` (top-left of the sprite);
        alpha channel is read from ``entity.layers[0]._image_data``.
        """
        try:
            import numpy as _np
        except ImportError:  # pragma: no cover — numpy is a core dep
            return _NO_CONTACT
        try:
            layer_a = entity_a.layers[0]
            layer_b = entity_b.layers[0]
            img_a = layer_a._image_data
            img_b = layer_b._image_data
        except (AttributeError, IndexError, TypeError):
            return _NO_CONTACT
        if img_a is None or img_b is None:
            return _NO_CONTACT
        if img_a.ndim != 3 or img_a.shape[2] < 4:
            return _NO_CONTACT
        if img_b.ndim != 3 or img_b.shape[2] < 4:
            return _NO_CONTACT

        ah, aw = img_a.shape[:2]
        bh, bw = img_b.shape[:2]
        try:
            ax = int(round(float(entity_a.position[0])))
            ay = int(round(float(entity_a.position[1])))
            bx = int(round(float(entity_b.position[0])))
            by = int(round(float(entity_b.position[1])))
        except (AttributeError, IndexError, TypeError, ValueError):
            return _NO_CONTACT

        # Overlap rect in world coords.
        ox0 = max(ax, bx)
        oy0 = max(ay, by)
        ox1 = min(ax + aw, bx + bw)
        oy1 = min(ay + ah, by + bh)
        if ox1 <= ox0 or oy1 <= oy0:
            return _NO_CONTACT

        # Slice each sprite's alpha channel to the overlap rect.
        alpha_a = img_a[oy0 - ay:oy1 - ay, ox0 - ax:ox1 - ax, 3]
        alpha_b = img_b[oy0 - by:oy1 - by, ox0 - bx:ox1 - bx, 3]

        thr = int(alpha_threshold) & 0xFF
        solid_a = alpha_a > thr
        solid_b = alpha_b > thr
        contact_mask = solid_a & solid_b
        contact_px = int(contact_mask.sum())
        if contact_px == 0:
            return _NO_CONTACT

        # Contact normal: vector from B's centroid to A's centroid, normalised.
        acx = ax + aw * 0.5
        acy = ay + ah * 0.5
        bcx = bx + bw * 0.5
        bcy = by + bh * 0.5
        nx = acx - bcx
        ny = acy - bcy
        mag = math.sqrt(nx * nx + ny * ny)
        if mag > 1e-9:
            normal = (nx / mag, ny / mag)
        else:
            normal = (1.0, 0.0)

        return PixelContactResult(hit=True, contact_pixels=contact_px, normal=normal)

    class _TestDispatcher:
        """Backwards-compat descriptor that routes ``.test(...)`` calls.

        * ``PixelCollisionPass.test(entity_a, entity_b)`` — 2-arg legacy form,
          delegates to :meth:`_test_entities_cpu` (CPU alpha overlap).
        * ``pass_.test(gpu, layer_a_tex, layer_a_rect, layer_b_tex, layer_b_rect, ...)``
          — modern GPU form, delegates to bound :meth:`_test_gpu`.
        DO NOT REMOVE without a v1.0 deprecation cycle.
        """

        def __get__(self, instance, owner):
            if instance is None:
                # Class-level access — legacy 2-arg CPU form.
                def _cpu_dispatch(entity_a, entity_b, alpha_threshold=128):
                    return owner._test_entities_cpu(entity_a, entity_b, alpha_threshold)
                _cpu_dispatch.__name__ = "test"
                return _cpu_dispatch
            # Instance-level access — modern GPU form.
            return instance._test_gpu

    test = _TestDispatcher()

    def _test_gpu(
        self,
        gpu: "GPUContext",
        layer_a_tex: object,
        layer_a_rect: tuple[int, int, int, int],
        layer_b_tex: object,
        layer_b_rect: tuple[int, int, int, int],
        alpha_threshold: int = 128,
    ) -> PixelContactResult:
        """Run the per-pixel collision check and return a :class:`PixelContactResult`.

        Parameters
        ----------
        gpu:
            Active :class:`~pharos_engine.gpu.context.GPUContext`.
        layer_a_tex:
            ``wgpu.GPUTexture`` for layer A (RGBA8 format expected).
        layer_a_rect:
            ``(x, y, w, h)`` bounding box of layer A in world pixels.
        layer_b_tex:
            ``wgpu.GPUTexture`` for layer B.
        layer_b_rect:
            ``(x, y, w, h)`` bounding box of layer B in world pixels.
        alpha_threshold:
            Pixel alpha value (0–255) above which a pixel is considered solid.
            Default: 128.

        Returns
        -------
        PixelContactResult
            Always returns a valid result; falls back to ``hit=False`` on any
            error or when wgpu / the shader is unavailable.
        """
        if not self._ready:
            return _NO_CONTACT

        try:
            return self._run(gpu, layer_a_tex, layer_a_rect,
                             layer_b_tex, layer_b_rect, alpha_threshold)
        except Exception:  # noqa: BLE001
            return _NO_CONTACT

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_pipeline(self, device: object) -> bool:
        """Compile the compute pipeline if not already done."""
        if self._pipeline is not None:
            return True
        try:
            module = device.create_shader_module(code=self._source)
            self._pipeline = device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
            return True
        except Exception:  # noqa: BLE001
            return False

    def _run(
        self,
        gpu: "GPUContext",
        layer_a_tex: object,
        layer_a_rect: tuple[int, int, int, int],
        layer_b_tex: object,
        layer_b_rect: tuple[int, int, int, int],
        alpha_threshold: int,
    ) -> PixelContactResult:
        device = gpu.device

        if not self._ensure_pipeline(device):
            return _NO_CONTACT

        ax, ay, aw, ah = layer_a_rect
        bx, by, bw, bh = layer_b_rect

        # ------------------------------------------------------------------
        # Compute overlap dimensions so we can size the dispatch.
        # ------------------------------------------------------------------
        overlap_x0 = max(ax, bx)
        overlap_y0 = max(ay, by)
        overlap_x1 = min(ax + aw, bx + bw)
        overlap_y1 = min(ay + ah, by + bh)

        if overlap_x1 <= overlap_x0 or overlap_y1 <= overlap_y0:
            # No geometric overlap at all — skip GPU work entirely.
            return _NO_CONTACT

        overlap_w = overlap_x1 - overlap_x0
        overlap_h = overlap_y1 - overlap_y0

        # ------------------------------------------------------------------
        # Build the params uniform buffer.
        # Layout: a_x, a_y, a_w, a_h, b_x, b_y, b_w, b_h, alpha_threshold,
        #         _pad0, _pad1, _pad2   (vec3u padding → 3 × u32)
        # ------------------------------------------------------------------
        params_data = struct.pack(
            _PARAMS_FORMAT,
            ax, ay, aw, ah,
            bx, by, bw, bh,
            int(alpha_threshold) & 0xFFFF_FFFF,
            0, 0, 0,   # _pad (vec3u)
        )
        params_buf = device.create_buffer_with_data(
            data=params_data,
            usage=_wgpu.BufferUsage.UNIFORM,
        )

        # ------------------------------------------------------------------
        # Build the result storage buffer (zeroed).
        # ------------------------------------------------------------------
        result_init = struct.pack(_RESULT_FORMAT, 0, 0, 0, 0)
        result_buf = device.create_buffer_with_data(
            data=result_init,
            usage=(
                _wgpu.BufferUsage.STORAGE
                | _wgpu.BufferUsage.COPY_SRC
                | _wgpu.BufferUsage.COPY_DST
            ),
        )

        # ------------------------------------------------------------------
        # Texture views (default view — full mip 0, all layers).
        # ------------------------------------------------------------------
        view_a = layer_a_tex.create_view()
        view_b = layer_b_tex.create_view()

        # ------------------------------------------------------------------
        # Bind group.
        # ------------------------------------------------------------------
        pipeline = self._pipeline
        bgl = pipeline.get_bind_group_layout(0)
        bind_group = device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": params_buf,
                                             "offset": 0,
                                             "size": _PARAMS_SIZE}},
                {"binding": 1, "resource": view_a},
                {"binding": 2, "resource": view_b},
                {"binding": 3, "resource": {"buffer": result_buf,
                                             "offset": 0,
                                             "size": _RESULT_SIZE}},
            ],
        )

        # ------------------------------------------------------------------
        # Dispatch.  Workgroup size is 8×8; caller computes grid dimensions.
        # ------------------------------------------------------------------
        wg_x = max(1, (overlap_w + 7) // 8)
        wg_y = max(1, (overlap_h + 7) // 8)

        encoder = device.create_command_encoder(label="pixel_collision")
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, bind_group)
        cp.dispatch_workgroups(wg_x, wg_y, 1)
        cp.end()
        device.queue.submit([encoder.finish()])

        # ------------------------------------------------------------------
        # Readback via a staging buffer (synchronous MAP_READ).
        # ------------------------------------------------------------------
        staging = device.create_buffer(
            size=_RESULT_SIZE,
            usage=_wgpu.BufferUsage.COPY_DST | _wgpu.BufferUsage.MAP_READ,
        )
        enc2 = device.create_command_encoder(label="pixel_collision_readback")
        enc2.copy_buffer_to_buffer(result_buf, 0, staging, 0, _RESULT_SIZE)
        device.queue.submit([enc2.finish()])

        staging.map_sync(_wgpu.MapMode.READ)
        raw = staging.read_mapped(0, _RESULT_SIZE)
        staging.unmap()
        staging.destroy()

        hit_u, contact_px, nx_acc, ny_acc = struct.unpack(_RESULT_FORMAT, bytes(raw))

        # ------------------------------------------------------------------
        # Derive contact normal from accumulated fixed-point gradient.
        # Python normalises: raw_acc / (10000 × contact_pixels) → mean gradient
        # then normalise to unit length.
        # ------------------------------------------------------------------
        normal: tuple[float, float] = (0.0, 0.0)
        if contact_px > 0:
            nx = nx_acc / (10000.0 * contact_px)
            ny = ny_acc / (10000.0 * contact_px)
            mag = math.sqrt(nx * nx + ny * ny)
            if mag > 1e-9:
                normal = (nx / mag, ny / mag)

        return PixelContactResult(
            hit=bool(hit_u),
            contact_pixels=int(contact_px),
            normal=normal,
        )
