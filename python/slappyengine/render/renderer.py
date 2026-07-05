"""Forward-rasterization renderer.

wgpu-first, with a graceful fallback to :class:`NullRenderer` when wgpu is
absent or the adapter request fails (typical of headless CI). Both back-ends
share the same public API, so callers — including HH1's ``App`` — never
have to branch on whether the GPU came up.

The wgpu path deliberately keeps things simple (per the user's ask):

* Forward pass with a single depth attachment and optional MSAA resolve.
* Blinn-Phong 3D and unlit 3D shader stock, 2D sprite quad, 3D debug lines.
* No shadow maps, no bloom, no refraction, no post FX beyond a clear +
  final colour attachment. Those live in ``slappyengine.post_process``.

JJ1 landed the real forward pipeline: ``_wgpu_begin_frame`` /
``_wgpu_end_frame`` acquire an offscreen render target, ``_wgpu_submit_*``
build vertex/index/uniform buffers via :mod:`pipeline`, and
``read_pixels`` performs the round-trip readback.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .light import Light, pack_lights_ubo
from .null_renderer import NullRenderer
from .passes import DepthPrepass, MSAAResolvePass, PassChain
from .pipeline import (
    BufferUploader,
    PipelineCache,
    UniformBufferPool,
    VERTEX_FORMAT_POS2_UV2,
    VERTEX_FORMAT_POS3_COL4,
    VERTEX_FORMAT_POS3_NRM3_UV2,
    VERTEX_FORMAT_POS3_UV2,
    create_forward_pipeline,
    create_line_pipeline,
    create_sprite_pipeline,
)

try:  # pragma: no cover - optional at import time
    import wgpu  # type: ignore
    _HAS_WGPU = True
except Exception:  # pragma: no cover
    wgpu = None  # type: ignore[assignment]
    _HAS_WGPU = False


# ----------------------------------------------------------------------
# Context + frame state
# ----------------------------------------------------------------------
@dataclass
class _WgpuContext:
    device: Any
    queue: Any
    color_format: str
    depth_format: str = "depth24plus"


@dataclass
class _FrameState:
    color_view: Any = None
    resolve_view: Any = None
    depth_view: Any = None
    encoder: Any = None
    pass_encoder: Any = None
    camera_buffer: Any = None
    lights_buffer: Any = None
    camera_bg_phong: Any = None
    camera_bg_unlit: Any = None


# Fixed unit-quad geometry used by the sprite path.
_SPRITE_VERTS = np.array(
    [
        # x, y, u, v
        [-0.5, -0.5, 0.0, 0.0],
        [0.5, -0.5, 1.0, 0.0],
        [0.5, 0.5, 1.0, 1.0],
        [-0.5, 0.5, 0.0, 1.0],
    ],
    dtype=np.float32,
).reshape(-1)
_SPRITE_INDICES = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32)


class Renderer:
    """Public forward renderer.

    Parameters
    ----------
    window_size : (w, h) pixel size for the offscreen render target / window.
    msaa        : sample count for the colour attachment. Set to 1 to disable.
    clear_color : (r, g, b, a) in linear space.
    vsync       : Present with vsync when bound to a real surface.
    force_null  : Force the CPU/null path even when wgpu is importable.
                  Handy for reproducible unit tests.
    """

    def __init__(
        self,
        *,
        window_size: tuple[int, int] = (1280, 720),
        msaa: int = 4,
        clear_color: tuple[float, float, float, float] = (0.05, 0.06, 0.08, 1.0),
        vsync: bool = True,
        force_null: bool = False,
    ) -> None:
        self.window_size = window_size
        self.msaa = int(msaa)
        self.clear_color = clear_color
        self.vsync = vsync
        self._null = NullRenderer(
            window_size=window_size,
            msaa=msaa,
            clear_color=clear_color,
            vsync=vsync,
        )
        self._ctx: _WgpuContext | None = None
        self._surface = None
        self._offscreen_texture = None
        self._offscreen_view = None
        self._msaa_texture = None
        self._msaa_view = None
        self._depth_texture = None
        self._depth_view = None
        self._readback_buffer = None
        self._pipeline_cache = PipelineCache()
        self._buffer_uploader = BufferUploader()
        self._ubo_pool = UniformBufferPool()
        self._current_camera: tuple[np.ndarray, np.ndarray] | None = None
        self._current_lights: list[Light] = []
        self._frame = _FrameState()
        self._frame_count = 0
        self._frame_open = False
        self._sprite_vb = None
        self._sprite_ib = None
        self._sprite_sampler = None
        self._backend = "null"
        # KK2: reusable pass chain (depth prepass + MSAA resolve).
        # Depth prepass is off by default so existing lifecycle is
        # unchanged for backward compat; ``enable_depth_prepass()`` flips
        # it on. MSAA resolve is registered eagerly so callers can query
        # the chain, but stays a no-op when ``msaa == 1``.
        self._pass_chain: PassChain = PassChain(renderer=self)
        self._pass_chain.add(MSAAResolvePass())
        self._depth_prepass_enabled: bool = False
        # Main-pass depth compare op — flipped by EarlyZPass when active.
        self.depth_compare: str = "less"
        if _HAS_WGPU and not force_null:
            self._try_init_wgpu()
        # Ensure the offscreen render target matches the initial window size
        # so ``read_pixels`` works even without an explicit ``create_offscreen``.
        if self._ctx is not None:
            try:
                self._ensure_offscreen(*self.window_size)
            except Exception as e:  # pragma: no cover
                warnings.warn(f"initial offscreen create failed: {e!r}", stacklevel=2)

    # ------------------------------------------------------------------
    # wgpu bring-up
    # ------------------------------------------------------------------
    def _try_init_wgpu(self) -> None:
        try:
            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
            if adapter is None:
                raise RuntimeError("no wgpu adapter")
            device = adapter.request_device_sync()
            self._ctx = _WgpuContext(
                device=device,
                queue=device.queue,
                color_format="rgba8unorm",
            )
            self._buffer_uploader.set_device(device)
            self._ubo_pool.set_device(device)
            self._backend = "wgpu"
        except Exception as e:  # pragma: no cover - GPU-dependent
            warnings.warn(
                f"Renderer: wgpu init failed ({e!r}); falling back to NullRenderer",
                stacklevel=2,
            )
            self._ctx = None
            self._backend = "null"

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def is_null(self) -> bool:
        return self._backend == "null"

    @property
    def pipeline_cache(self) -> PipelineCache:
        return self._pipeline_cache

    @property
    def buffer_uploader(self) -> BufferUploader:
        return self._buffer_uploader

    @property
    def uniform_pool(self) -> UniformBufferPool:
        return self._ubo_pool

    # ------------------------------------------------------------------
    # KK2 — reusable pass chain
    # ------------------------------------------------------------------
    @property
    def pass_chain(self) -> PassChain:
        """The reusable :class:`PassChain` for this renderer.

        Populated at construction with a :class:`MSAAResolvePass`;
        :meth:`enable_depth_prepass` inserts a :class:`DepthPrepass`
        ahead of it. Callers may append their own passes.
        """
        return self._pass_chain

    def enable_depth_prepass(self, enabled: bool = True) -> None:
        """Toggle the KK2 depth prepass in the renderer's :attr:`pass_chain`.

        The prepass runs before MSAA resolve and skips transparent
        meshes. Backward-compat safe — existing frame lifecycle only
        picks up the prepass when this flag flips on.
        """
        if bool(enabled) == self._depth_prepass_enabled:
            return
        if enabled:
            # Insert DepthPrepass ahead of the existing MSAA resolve.
            prepass = DepthPrepass()
            prepass.setup(self)
            # Re-order: [DepthPrepass, ..existing..].
            existing = list(self._pass_chain)
            self._pass_chain = PassChain(renderer=self)
            self._pass_chain._passes.append(prepass)
            for p in existing:
                self._pass_chain._passes.append(p)
            self._depth_prepass_enabled = True
        else:
            self._pass_chain.remove("depth_prepass")
            self._depth_prepass_enabled = False

    # ------------------------------------------------------------------
    # Surface / offscreen
    # ------------------------------------------------------------------
    def create_surface(self, window_handle: Any) -> None:
        if self.is_null:
            self._null.create_surface(window_handle)
            return
        # Real wgpu surface creation is windowing-toolkit specific; we defer to
        # the caller providing a compatible ``present_context``. Guard failures
        # to keep the renderer usable for offscreen work.
        try:  # pragma: no cover - environment specific
            self._surface = wgpu.gpu.request_adapter_sync().get_surface(window_handle)
        except Exception as e:  # pragma: no cover
            warnings.warn(f"create_surface failed: {e!r}", stacklevel=2)

    def create_offscreen(self, width: int, height: int) -> None:
        self.window_size = (int(width), int(height))
        self._null.create_offscreen(width, height)
        if self._ctx is not None:  # pragma: no cover - GPU-dependent
            self._ensure_offscreen(int(width), int(height))

    def _ensure_offscreen(self, width: int, height: int) -> None:
        if self._ctx is None:
            return
        w = max(1, int(width))
        h = max(1, int(height))
        cur = getattr(self, "_offscreen_size", None)
        if cur == (w, h) and self._offscreen_texture is not None:
            return
        self._offscreen_size = (w, h)
        self._offscreen_texture = self._ctx.device.create_texture(
            label="offscreen_color",
            size=(w, h, 1),
            format=self._ctx.color_format,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC,
            sample_count=1,
        )
        self._offscreen_view = self._offscreen_texture.create_view()
        self._depth_texture = self._ctx.device.create_texture(
            label="offscreen_depth",
            size=(w, h, 1),
            format=self._ctx.depth_format,
            usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
            sample_count=self.msaa,
        )
        self._depth_view = self._depth_texture.create_view()
        if self.msaa > 1:
            self._msaa_texture = self._ctx.device.create_texture(
                label="offscreen_msaa",
                size=(w, h, 1),
                format=self._ctx.color_format,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT,
                sample_count=self.msaa,
            )
            self._msaa_view = self._msaa_texture.create_view()
        else:
            self._msaa_texture = None
            self._msaa_view = None
        # 256-byte row alignment required by wgpu's texture-to-buffer copy.
        bytes_per_pixel = 4
        row_stride = ((w * bytes_per_pixel + 255) // 256) * 256
        self._readback_row_stride = row_stride
        self._readback_buffer = self._ctx.device.create_buffer(
            label="readback",
            size=row_stride * h,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
        )

    # ------------------------------------------------------------------
    # Frame lifecycle
    # ------------------------------------------------------------------
    def begin_frame(self) -> None:
        if not _HAS_WGPU or self._ctx is None:
            self._null.begin_frame()
            self._frame_open = True
            return
        self._wgpu_begin_frame()
        self._frame_open = True

    def end_frame(self) -> None:
        if not _HAS_WGPU or self._ctx is None:
            self._null.end_frame()
            self._frame_open = False
            return
        self._wgpu_end_frame()
        self._frame_open = False

    # ------------------------------------------------------------------
    # Submissions
    # ------------------------------------------------------------------
    def submit_mesh(self, mesh, model_matrix, material) -> None:
        # Always mirror to NullRenderer so introspection helpers (draw_log,
        # calls_of) work regardless of backend.
        if not self._null._frame_open:  # keep the null-side lifecycle honest
            # NullRenderer expects begin/end; but on the wgpu path we don't
            # want to mirror lifecycle. Just append the call directly.
            from .null_renderer import DrawCall
            self._null.draw_log.append(
                DrawCall(
                    "mesh",
                    {
                        "vertex_count": int(mesh.vertices.shape[0]),
                        "triangle_count": int(mesh.indices.shape[0]),
                        "model_matrix": np.asarray(model_matrix, dtype=np.float32).copy(),
                        "material_name": material.name,
                        "base_color": material.base_color,
                        "alpha_mode": material.alpha_mode,
                    },
                )
            )
        else:
            self._null.submit_mesh(mesh, model_matrix, material)
        if not _HAS_WGPU or self._ctx is None:
            return
        self._wgpu_submit_mesh(mesh, model_matrix, material)

    def submit_sprite(self, texture, transform_2d, tint=(1.0, 1.0, 1.0, 1.0)) -> None:
        if not self._null._frame_open:
            from .null_renderer import DrawCall
            self._null.draw_log.append(
                DrawCall(
                    "sprite",
                    {
                        "texture_id": getattr(texture, "id", None),
                        "transform_2d": np.asarray(transform_2d, dtype=np.float32).copy(),
                        "tint": tuple(float(x) for x in tint),
                    },
                )
            )
        else:
            self._null.submit_sprite(texture, transform_2d, tint)
        if not _HAS_WGPU or self._ctx is None:
            return
        self._wgpu_submit_sprite(texture, transform_2d, tint)

    def submit_lines(self, vertices: np.ndarray, colors: np.ndarray) -> None:
        if not self._null._frame_open:
            from .null_renderer import DrawCall
            self._null.draw_log.append(
                DrawCall(
                    "line",
                    {
                        "count": int(np.asarray(vertices).shape[0]) // 2,
                        "vertices": np.asarray(vertices, dtype=np.float32).copy(),
                        "colors": np.asarray(colors, dtype=np.float32).copy(),
                    },
                )
            )
        else:
            self._null.submit_lines(vertices, colors)
        if not _HAS_WGPU or self._ctx is None:
            return
        self._wgpu_submit_lines(vertices, colors)

    def set_camera(self, view_matrix, proj_matrix) -> None:
        self._null.set_camera(view_matrix, proj_matrix)
        v = np.asarray(view_matrix, dtype=np.float32)
        p = np.asarray(proj_matrix, dtype=np.float32)
        self._current_camera = (v, p)
        if not _HAS_WGPU or self._ctx is None:
            return
        self._wgpu_set_camera(v, p)

    def set_lights(self, lights: list[Light]) -> None:
        self._null.set_lights(lights)
        self._current_lights = list(lights)
        if not _HAS_WGPU or self._ctx is None:
            return
        self._wgpu_set_lights(self._current_lights)

    # ------------------------------------------------------------------
    # Upload / read-back
    # ------------------------------------------------------------------
    def _upload_mesh(self, mesh):
        # Even on the wgpu path we hand out a NullRenderer-issued handle
        # for compatibility with HH4's existing tests; the real buffers
        # live on the BufferUploader cache keyed by mesh contents.
        return self._null._upload_mesh(mesh)

    def upload_texture(self, pixels: np.ndarray, *, format: str = "rgba8unorm"):
        handle = self._null.upload_texture(pixels, format=format)
        if _HAS_WGPU and self._ctx is not None:
            try:
                self._create_wgpu_texture(handle, pixels, format=format)
            except Exception as e:  # pragma: no cover
                warnings.warn(f"upload_texture wgpu path failed: {e!r}", stacklevel=2)
        return handle

    def _create_wgpu_texture(self, handle, pixels: np.ndarray, *, format: str) -> None:
        px = np.ascontiguousarray(pixels, dtype=np.uint8)
        if px.ndim != 3 or px.shape[2] != 4:
            raise ValueError("texture pixels must be (H, W, 4) uint8")
        h, w, _ = px.shape
        tex = self._ctx.device.create_texture(
            label="tex",
            size=(w, h, 1),
            format=format,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
            sample_count=1,
        )
        self._ctx.queue.write_texture(
            {"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
            px.tobytes(),
            {"offset": 0, "bytes_per_row": w * 4, "rows_per_image": h},
            (w, h, 1),
        )
        handle.gpu_texture = tex

    def read_pixels(self) -> np.ndarray:
        if not _HAS_WGPU or self._ctx is None or self._offscreen_texture is None:
            return self._null.read_pixels()
        return self._wgpu_read_pixels()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def draw_log(self):
        return self._null.draw_log

    def calls_of(self, kind: str):
        return self._null.calls_of(kind)

    @property
    def frame_count(self) -> int:
        if self._ctx is None:
            return self._null.frame_count
        return self._frame_count

    def light_ubo(self, lights: list[Light]) -> np.ndarray:
        return pack_lights_ubo(lights)

    # ==================================================================
    # wgpu path — the real forward pipeline
    # ==================================================================
    def _wgpu_begin_frame(self) -> None:  # pragma: no cover - GPU-dependent
        self._ensure_offscreen(*self.window_size)
        self._ubo_pool.reset()
        self._frame.encoder = self._ctx.device.create_command_encoder(label="frame")
        color_view = self._msaa_view if self.msaa > 1 else self._offscreen_view
        resolve_view = self._offscreen_view if self.msaa > 1 else None
        r, g, b, a = self.clear_color
        color_attachment: dict = {
            "view": color_view,
            "load_op": "clear",
            "store_op": "store",
            "clear_value": (float(r), float(g), float(b), float(a)),
        }
        if resolve_view is not None:
            color_attachment["resolve_target"] = resolve_view
        self._frame.pass_encoder = self._frame.encoder.begin_render_pass(
            label="forward",
            color_attachments=[color_attachment],
            depth_stencil_attachment={
                "view": self._depth_view,
                "depth_load_op": "clear",
                "depth_store_op": "store",
                "depth_clear_value": 1.0,
            },
        )
        # Re-upload the current camera / lights bind groups for this frame.
        if self._current_camera is not None:
            self._wgpu_set_camera(*self._current_camera)
        self._wgpu_set_lights(self._current_lights)

    def _wgpu_end_frame(self) -> None:  # pragma: no cover - GPU-dependent
        if self._frame.pass_encoder is not None:
            self._frame.pass_encoder.end()
        if self._frame.encoder is not None:
            cmd = self._frame.encoder.finish()
            self._ctx.queue.submit([cmd])
        self._frame.encoder = None
        self._frame.pass_encoder = None
        self._frame_count += 1

    def _wgpu_set_camera(self, view: np.ndarray, proj: np.ndarray) -> None:  # pragma: no cover
        v = np.asarray(view, dtype=np.float32)
        p = np.asarray(proj, dtype=np.float32)
        vp = (p @ v).astype(np.float32)
        # Extract camera position for the phong shader (view^-1 * origin).
        try:
            cam_pos = np.linalg.inv(v)[:3, 3]
        except np.linalg.LinAlgError:
            cam_pos = np.zeros(3, dtype=np.float32)
        # Phong Camera struct: view_proj (mat4) + cam_pos (vec4) = 80 B.
        buf_phong = np.zeros(20, dtype=np.float32)
        buf_phong[0:16] = vp.T.reshape(-1)  # wgsl mat4 is column-major
        buf_phong[16:19] = cam_pos
        buf_phong[19] = 1.0
        # Unlit Camera struct: view_proj (mat4) = 64 B.
        buf_unlit = np.zeros(16, dtype=np.float32)
        buf_unlit[:] = vp.T.reshape(-1)

        cam_phong = self._ubo_pool.acquire(size=80)
        cam_unlit = self._ubo_pool.acquire(size=64)
        self._ubo_pool.write(cam_phong, buf_phong)
        self._ubo_pool.write(cam_unlit, buf_unlit)
        self._frame.camera_buffer = cam_phong
        self._frame.camera_unlit_buffer = cam_unlit
        self._frame.camera_bg_phong = None
        self._frame.camera_bg_unlit = None

    def _wgpu_set_lights(self, lights: list[Light]) -> None:  # pragma: no cover
        ubo = pack_lights_ubo(lights).astype(np.float32)
        # Layout matches the WGSL `Lights` struct exactly (4 slots × 64 B + vec4).
        buf = self._ubo_pool.acquire(size=ubo.nbytes)
        self._ubo_pool.write(buf, ubo)
        self._frame.lights_buffer = buf
        self._frame.camera_bg_phong = None  # invalidate cached bg

    def _wgpu_submit_mesh(self, mesh, model_matrix, material) -> None:  # pragma: no cover
        if self._frame.pass_encoder is None:
            return
        phong = not _is_unlit_material(material) and len(self._current_lights) > 0
        shader_id = "phong_3d" if phong else "unlit_3d"
        vf = VERTEX_FORMAT_POS3_NRM3_UV2 if phong else VERTEX_FORMAT_POS3_UV2
        pipeline = create_forward_pipeline(
            self._ctx.device,
            shader_id=shader_id,
            msaa_samples=self.msaa,
            color_format=self._ctx.color_format,
            depth_format=self._ctx.depth_format,
            cache=self._pipeline_cache,
            blend_mode="alpha" if material.alpha_mode == "blend" else "opaque",
        )
        # Interleave vertex data.
        v = np.asarray(mesh.vertices, dtype=np.float32)
        if phong:
            n = mesh.normals if mesh.normals is not None else mesh.compute_normals()
            uv = mesh.uvs if mesh.uvs is not None else np.zeros((v.shape[0], 2), dtype=np.float32)
            interleaved = np.concatenate([v, n.astype(np.float32), uv.astype(np.float32)], axis=1)
        else:
            uv = mesh.uvs if mesh.uvs is not None else np.zeros((v.shape[0], 2), dtype=np.float32)
            interleaved = np.concatenate([v, uv.astype(np.float32)], axis=1)
        interleaved = np.ascontiguousarray(interleaved, dtype=np.float32)
        vb, _ = self._buffer_uploader.upload(interleaved, usage="vertex")
        indices = np.ascontiguousarray(mesh.indices, dtype=np.uint32).reshape(-1)
        ib, _ = self._buffer_uploader.upload(indices, usage="index")

        # Model UBO — mat4 (16 f) + color vec4 (4 f) = 80 B.
        model_data = np.zeros(20, dtype=np.float32)
        m = np.asarray(model_matrix, dtype=np.float32).reshape(4, 4)
        model_data[0:16] = m.T.reshape(-1)  # column-major
        model_data[16:20] = np.asarray(material.base_color, dtype=np.float32)
        model_buf = self._ubo_pool.acquire(size=80)
        self._ubo_pool.write(model_buf, model_data)

        # Bind groups.
        bgls = pipeline.get_bind_group_layout(0), pipeline.get_bind_group_layout(1)
        entries_g0 = [{"binding": 0, "resource": {"buffer": self._frame.camera_buffer, "offset": 0, "size": 80}}] if phong else [
            {"binding": 0, "resource": {"buffer": self._frame.camera_unlit_buffer, "offset": 0, "size": 64}}
        ]
        if phong and self._frame.lights_buffer is not None:
            lights_size = int(np.dtype(np.float32).itemsize) * (4 * 16 + 4)
            entries_g0.append(
                {"binding": 1, "resource": {"buffer": self._frame.lights_buffer, "offset": 0, "size": lights_size}}
            )
        bg0 = self._ctx.device.create_bind_group(label="cam", layout=bgls[0], entries=entries_g0)
        bg1 = self._ctx.device.create_bind_group(
            label="model",
            layout=bgls[1],
            entries=[{"binding": 0, "resource": {"buffer": model_buf, "offset": 0, "size": 80}}],
        )
        pe = self._frame.pass_encoder
        pe.set_pipeline(pipeline)
        pe.set_bind_group(0, bg0)
        pe.set_bind_group(1, bg1)
        pe.set_vertex_buffer(0, vb)
        pe.set_index_buffer(ib, "uint32")
        pe.draw_indexed(indices.size, 1, 0, 0, 0)

    def _wgpu_submit_sprite(self, texture, transform_2d, tint) -> None:  # pragma: no cover
        if self._frame.pass_encoder is None:
            return
        if getattr(texture, "gpu_texture", None) is None:
            # No texture on the GPU — skip silently but the null-log call is already recorded.
            return
        pipeline = create_sprite_pipeline(
            self._ctx.device,
            msaa_samples=self.msaa,
            color_format=self._ctx.color_format,
            depth_format=self._ctx.depth_format,
            cache=self._pipeline_cache,
        )
        if self._sprite_vb is None:
            self._sprite_vb, _ = self._buffer_uploader.upload(_SPRITE_VERTS, usage="vertex")
            self._sprite_ib, _ = self._buffer_uploader.upload(_SPRITE_INDICES, usage="index")
        if self._sprite_sampler is None:
            self._sprite_sampler = self._ctx.device.create_sampler(
                label="sprite_sampler",
                mag_filter="linear",
                min_filter="linear",
                mipmap_filter="nearest",
            )
        # Build a 4x4 sprite transform from the 3x3 transform_2d.
        t = np.eye(4, dtype=np.float32)
        t2 = np.asarray(transform_2d, dtype=np.float32)
        if t2.shape == (3, 3):
            t[0, 0] = t2[0, 0]; t[0, 1] = t2[0, 1]; t[0, 3] = t2[0, 2]
            t[1, 0] = t2[1, 0]; t[1, 1] = t2[1, 1]; t[1, 3] = t2[1, 2]
        elif t2.shape == (4, 4):
            t = t2.copy()
        sprite_ubo = np.zeros(20, dtype=np.float32)
        sprite_ubo[0:16] = t.T.reshape(-1)
        sprite_ubo[16:20] = np.asarray(tint, dtype=np.float32)
        sprite_buf = self._ubo_pool.acquire(size=80)
        self._ubo_pool.write(sprite_buf, sprite_ubo)

        bgl0 = pipeline.get_bind_group_layout(0)
        bgl1 = pipeline.get_bind_group_layout(1)
        bg0 = self._ctx.device.create_bind_group(
            label="cam2d",
            layout=bgl0,
            entries=[
                {"binding": 0, "resource": {"buffer": self._frame.camera_unlit_buffer, "offset": 0, "size": 64}}
            ],
        )
        bg1 = self._ctx.device.create_bind_group(
            label="sprite_bg",
            layout=bgl1,
            entries=[
                {"binding": 0, "resource": {"buffer": sprite_buf, "offset": 0, "size": 80}},
                {"binding": 1, "resource": texture.gpu_texture.create_view()},
                {"binding": 2, "resource": self._sprite_sampler},
            ],
        )
        pe = self._frame.pass_encoder
        pe.set_pipeline(pipeline)
        pe.set_bind_group(0, bg0)
        pe.set_bind_group(1, bg1)
        pe.set_vertex_buffer(0, self._sprite_vb)
        pe.set_index_buffer(self._sprite_ib, "uint32")
        pe.draw_indexed(6, 1, 0, 0, 0)

    def _wgpu_submit_lines(self, vertices: np.ndarray, colors: np.ndarray) -> None:  # pragma: no cover
        if self._frame.pass_encoder is None:
            return
        pipeline = create_line_pipeline(
            self._ctx.device,
            msaa_samples=self.msaa,
            color_format=self._ctx.color_format,
            depth_format=self._ctx.depth_format,
            cache=self._pipeline_cache,
        )
        v = np.ascontiguousarray(vertices, dtype=np.float32).reshape(-1, 3)
        c = np.ascontiguousarray(colors, dtype=np.float32).reshape(-1, 4)
        if v.shape[0] != c.shape[0]:
            # Broadcast a single colour across all vertices if provided as one.
            if c.shape[0] == 1:
                c = np.repeat(c, v.shape[0], axis=0)
            else:
                return
        interleaved = np.concatenate([v, c], axis=1).astype(np.float32, copy=False)
        vb, _ = self._buffer_uploader.upload(interleaved, usage="vertex")
        bgl0 = pipeline.get_bind_group_layout(0)
        bg0 = self._ctx.device.create_bind_group(
            label="line_cam",
            layout=bgl0,
            entries=[
                {"binding": 0, "resource": {"buffer": self._frame.camera_unlit_buffer, "offset": 0, "size": 64}}
            ],
        )
        pe = self._frame.pass_encoder
        pe.set_pipeline(pipeline)
        pe.set_bind_group(0, bg0)
        pe.set_vertex_buffer(0, vb)
        pe.draw(v.shape[0], 1, 0, 0)

    def _wgpu_read_pixels(self) -> np.ndarray:  # pragma: no cover - GPU-dependent
        w, h = self.window_size
        w = max(1, int(w))
        h = max(1, int(h))
        row_stride = self._readback_row_stride
        enc = self._ctx.device.create_command_encoder(label="readback")
        enc.copy_texture_to_buffer(
            {"texture": self._offscreen_texture, "mip_level": 0, "origin": (0, 0, 0)},
            {"buffer": self._readback_buffer, "offset": 0, "bytes_per_row": row_stride, "rows_per_image": h},
            (w, h, 1),
        )
        self._ctx.queue.submit([enc.finish()])
        # Map + copy out.
        self._readback_buffer.map_sync(wgpu.MapMode.READ)
        try:
            mem = self._readback_buffer.read_mapped()
            raw = bytes(mem)
        finally:
            self._readback_buffer.unmap()
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(h, row_stride // 4, 4)
        return np.ascontiguousarray(arr[:, :w, :])


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _is_unlit_material(material) -> bool:
    """Return True when the material should render with the unlit shader.

    Currently: emissive != (0,0,0) or explicit alpha_mode == 'blend' → still
    phong; but if the caller sets material.name == 'unlit' we honour that.
    """
    if getattr(material, "name", "") == "unlit":
        return True
    return False


def is_wgpu_available() -> bool:
    """True when wgpu is importable in this interpreter."""
    return _HAS_WGPU
