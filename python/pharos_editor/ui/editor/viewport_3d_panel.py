"""``Viewport3DPanel`` — a real 3D wgpu viewport hosted inside the editor.

This panel lands the first end-to-end wgpu render surface inside the
Dear PyGui notebook editor. It owns a self-contained scene (one rotating
cube + one point light + an orbit camera), renders each frame into an
offscreen RGBA texture, downloads the result to CPU, and blits the pixels
into a DPG ``dynamic_texture`` displayed via ``dpg.add_image``.

Design goals (CCC1 sprint):

* Zero external asset dependencies — the cube mesh is generated in
  Python, the shader is a single small WGSL file, and no glTF/PNG loader
  is required to see something on screen.
* Graceful fallback — if wgpu can't request an adapter (headless CI,
  missing Vulkan/DX12/Metal driver) the panel still builds and shows a
  numpy-drawn "wgpu adapter unavailable" placeholder so the tab isn't
  blank.
* Headless-safe — every ``dearpygui`` call is guarded so the same panel
  code runs under pytest without a DPG context. The renderer half runs
  regardless of DPG state so tests can assert on ``last_frame``.
* Live-updating — :meth:`tick` advances the cube rotation and re-uploads
  the frame. The editor shell calls this from its per-frame subsystem
  tick.

The panel is deliberately independent of :mod:`pharos_engine.render.renderer`
so the shell doesn't have to pay the full renderer bring-up cost when the
user only wants to peek at the 3D tab. If a later sprint wants to unify
the two, ``_get_or_create_device`` is the single seam to swap in.
"""

from __future__ import annotations

import math
import os
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# wgpu soft-import — every wgpu reference below goes through the module-level
# alias so tests can monkeypatch ``_wgpu`` to ``None`` and exercise the
# placeholder path deterministically.
# ---------------------------------------------------------------------------
try:  # pragma: no cover — optional dep
    import wgpu as _wgpu  # type: ignore[import-not-found]
    import wgpu.utils as _wgpu_utils  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    _wgpu = None  # type: ignore[assignment]
    _wgpu_utils = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Cube mesh — 24 verts (4 per face for flat normals) + 36 indices.
# Ordered so front-faces are counter-clockwise when viewed from outside.
# ---------------------------------------------------------------------------

def _make_cube_mesh() -> tuple[np.ndarray, np.ndarray]:
    """Return ``(vertices, indices)`` for a unit cube centred at the origin.

    ``vertices`` is ``(24, 6) float32`` — position (xyz) followed by
    normal (xyz), one vertex per face-corner so each face gets a crisp
    flat normal instead of the smoothed 8-vertex box normals.

    ``indices`` is ``(36,) uint32`` — two triangles per face.
    """
    s = 0.5
    faces = [
        # (four positions ccw as seen from outside, normal)
        ([(-s, -s,  s), ( s, -s,  s), ( s,  s,  s), (-s,  s,  s)], (0.0, 0.0,  1.0)),  # +Z
        ([( s, -s, -s), (-s, -s, -s), (-s,  s, -s), ( s,  s, -s)], (0.0, 0.0, -1.0)),  # -Z
        ([( s, -s,  s), ( s, -s, -s), ( s,  s, -s), ( s,  s,  s)], ( 1.0, 0.0, 0.0)),  # +X
        ([(-s, -s, -s), (-s, -s,  s), (-s,  s,  s), (-s,  s, -s)], (-1.0, 0.0, 0.0)),  # -X
        ([(-s,  s,  s), ( s,  s,  s), ( s,  s, -s), (-s,  s, -s)], (0.0,  1.0, 0.0)),  # +Y
        ([(-s, -s, -s), ( s, -s, -s), ( s, -s,  s), (-s, -s,  s)], (0.0, -1.0, 0.0)),  # -Y
    ]

    verts: list[float] = []
    inds: list[int] = []
    for i, (quad, nrm) in enumerate(faces):
        base = i * 4
        for p in quad:
            verts.extend([p[0], p[1], p[2], nrm[0], nrm[1], nrm[2]])
        inds.extend([base + 0, base + 1, base + 2, base + 0, base + 2, base + 3])

    vbo = np.asarray(verts, dtype=np.float32).reshape(24, 6)
    ibo = np.asarray(inds, dtype=np.uint32)
    return vbo, ibo


# ---------------------------------------------------------------------------
# Matrix helpers — column-major mat4 stored as 16 floats. wgpu's WGSL
# ``mat4x4`` reads uniform data column-major so this matches the shader.
# ---------------------------------------------------------------------------

def _identity4() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def _rot_y(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    m = np.eye(4, dtype=np.float32)
    m[0, 0] =  c; m[0, 2] = s
    m[2, 0] = -s; m[2, 2] = c
    return m


def _rot_x(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    m = np.eye(4, dtype=np.float32)
    m[1, 1] =  c; m[1, 2] = -s
    m[2, 1] =  s; m[2, 2] =  c
    return m


def _perspective(fov_y_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    """Right-handed perspective projection matching wgpu NDC (Z in [0,1]).

    Convention: view space uses -Z forward (right-handed). Post-projection
    Z lands in [0, 1] with the near plane at Z=0 (as wgpu / DirectX 12 /
    Metal expect). Column-major.
    """
    f = 1.0 / math.tan(math.radians(fov_y_deg) * 0.5)
    m = np.zeros((4, 4), dtype=np.float32)
    # Row-major-looking storage; we flip to column-major on upload.
    m[0, 0] = f / aspect
    m[1, 1] = f
    # For a right-handed view with -Z forward → wgpu clip Z in [0, 1]:
    #   z_clip = -z_view * far/(near-far) - near*far/(near-far)
    #   w_clip = -z_view
    m[2, 2] = far / (near - far)
    m[2, 3] = (near * far) / (near - far)
    m[3, 2] = -1.0
    return m


def _look_at(eye: np.ndarray, target: np.ndarray, up: np.ndarray) -> np.ndarray:
    f = target - eye
    f /= np.linalg.norm(f) + 1e-12
    r = np.cross(f, up)
    r /= np.linalg.norm(r) + 1e-12
    u = np.cross(r, f)
    m = np.eye(4, dtype=np.float32)
    m[0, 0:3] = r
    m[1, 0:3] = u
    m[2, 0:3] = -f
    m[0, 3] = -np.dot(r, eye)
    m[1, 3] = -np.dot(u, eye)
    m[2, 3] =  np.dot(f, eye)
    return m


def _column_major(m: np.ndarray) -> np.ndarray:
    """Return a 16-float column-major view of *m* for uniform upload."""
    return m.T.astype(np.float32, copy=True).reshape(-1)


# ---------------------------------------------------------------------------
# Placeholder image — drawn onto a numpy array so the tab renders something
# even when wgpu init failed. No PIL dependency; uses a simple pattern +
# stamped-in text glyphs from a tiny built-in 5x7 font would be overkill for
# a first cut, so we draw geometry hints and rely on a tooltip for the copy.
# ---------------------------------------------------------------------------

def _draw_placeholder(width: int, height: int, message: str) -> np.ndarray:
    """Return a ``(H, W, 4)`` uint8 RGBA placeholder image.

    Draws a subtle diagonal-stripe pattern in the paper cream / graphite
    palette used by the notebook editor, with a centred marker so the
    user can tell the tab is alive but wgpu didn't come up. *message* is
    stored on the panel so a hover-tooltip can surface the copy.
    """
    img = np.full((height, width, 4), (30, 32, 38, 255), dtype=np.uint8)
    # Diagonal stripes — every 24 px, 2-px thick, warmer graphite.
    yy, xx = np.mgrid[0:height, 0:width]
    stripes = ((xx + yy) // 12) % 2 == 0
    img[stripes] = (44, 46, 52, 255)
    # Centred cross + rectangle to hint "viewport unavailable".
    cy, cx = height // 2, width // 2
    if cy > 10 and cx > 10:
        img[cy - 1:cy + 1, cx - 40:cx + 40] = (220, 180, 100, 255)
        img[cy - 40:cy + 40, cx - 1:cx + 1] = (220, 180, 100, 255)
        # Frame
        img[cy - 42, cx - 60:cx + 60] = (220, 180, 100, 255)
        img[cy + 41, cx - 60:cx + 60] = (220, 180, 100, 255)
        img[cy - 42:cy + 42, cx - 60] = (220, 180, 100, 255)
        img[cy - 42:cy + 42, cx + 59] = (220, 180, 100, 255)
    # Suppress unused arg lint — the message is stashed by the caller.
    _ = message
    return img


# ---------------------------------------------------------------------------
# Viewport3DPanel
# ---------------------------------------------------------------------------

class Viewport3DPanel:
    """Live wgpu 3D viewport rendered into a DPG dynamic_texture.

    The panel is a single-tab payload (the caller wraps it in a
    ``MovablePanelWindow`` or a tab bar). It renders into an offscreen
    ``rgba8unorm`` texture, reads the pixels back to CPU each frame, and
    calls :func:`dpg.set_value` on the registered ``dynamic_texture`` so
    the on-screen image updates without any re-registration.

    Attributes
    ----------
    width, height:
        Render target size in pixels. Kept small (256x256 by default) so
        the CPU readback stays cheap.
    last_frame:
        The most recent ``(H, W, 4) uint8`` render — the same buffer the
        DPG texture wraps. Tests read this to verify at least one frame
        landed. Never ``None`` after :meth:`build` returns.
    backend:
        String describing the wgpu backend (``"Vulkan"``, ``"DX12"``,
        ``"Metal"``, ``"Software"``) — or ``"placeholder"`` when wgpu
        failed to initialise. Populated by :meth:`_init_gpu`.

    Notes
    -----
    * The device is soft-imported at module load; if wgpu is missing the
      panel falls straight through to the placeholder path.
    * The demo scene is one rotating cube with a shared point light. The
      cube rotates in :meth:`tick` and re-renders on the next frame.
    * Auto-resize is opt-in via :meth:`resize_to_parent` — the shell
      calls it on viewport resize so the panel fills its centre tab.
    """

    # A conservative default that keeps CPU readback under 1 ms while
    # still showing crisp shading. The shell can bump this via ``resize``.
    _DEFAULT_W = 512
    _DEFAULT_H = 384

    # WGSL source is bundled next to :mod:`pharos_engine.render.shaders`.
    _SHADER_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "..", "render", "shaders", "viewport_basic.wgsl",
    )

    def __init__(
        self,
        width: int | None = None,
        height: int | None = None,
        texture_tag: str = "viewport_3d_dynamic_texture",
        image_tag: str = "viewport_3d_image",
    ) -> None:
        self.width = int(width) if width else self._DEFAULT_W
        self.height = int(height) if height else self._DEFAULT_H
        self._texture_tag = texture_tag
        self._image_tag = image_tag
        self._parent_tag: str | int | None = None

        # Scene state — a single cube rotating in Y, a fixed point light
        # off-axis so the shading gradient is obvious even before any
        # tick() has advanced ``_angle``.
        self._angle = 0.0
        self._cam_eye = np.array([2.5, 2.0, 3.5], dtype=np.float32)
        self._cam_target = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        self._cam_up = np.array([0.0, 1.0, 0.0], dtype=np.float32)
        self._light_pos = np.array([3.0, 4.0, 2.5, 1.5], dtype=np.float32)  # w = intensity
        self._light_color = np.array([1.0, 0.94, 0.85, 0.18], dtype=np.float32)  # w = ambient
        self._base_color = np.array([0.85, 0.55, 0.30, 0.6], dtype=np.float32)   # w = spec

        # GPU + render-target state. All optional — the placeholder path
        # leaves these ``None`` and short-circuits :meth:`render`.
        self._device: Any = None
        self._queue: Any = None
        self._pipeline: Any = None
        self._bind_group: Any = None
        self._uniform_buffer: Any = None
        self._vertex_buffer: Any = None
        self._index_buffer: Any = None
        self._color_texture: Any = None
        self._color_view: Any = None
        self._depth_texture: Any = None
        self._depth_view: Any = None

        # CPU-side render output. Initialised so ``last_frame`` is never
        # ``None`` even if a caller queries it before :meth:`build`.
        self.last_frame: np.ndarray = np.zeros(
            (self.height, self.width, 4), dtype=np.uint8,
        )
        self.backend: str = "placeholder"
        self.placeholder_message: str = "wgpu adapter unavailable - see docs"

        # Cube mesh + index count.
        self._vertices, self._indices = _make_cube_mesh()
        self._index_count = int(self._indices.size)

    # ------------------------------------------------------------------
    # Panel protocol
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Register the dynamic texture and image widget under *parent_tag*.

        Safe to call in headless environments — Dear PyGui imports are
        guarded and the panel still renders one frame so ``last_frame``
        holds a real image the moment ``build`` returns.
        """
        self._parent_tag = parent_tag

        # 1. Bring up the GPU (soft — success is optional).
        self._init_gpu()

        # 2. Render the first frame so ``last_frame`` is populated.
        try:
            self.render()
        except Exception:
            # If the first render throws (driver hiccup, out-of-memory,
            # a subtle WGSL typo introduced by a future edit) we still
            # want the panel to build — fall through to the placeholder
            # so the UI stays alive.
            self.backend = "placeholder"
            self.last_frame = _draw_placeholder(
                self.width, self.height, self.placeholder_message,
            )

        # 3. Wire the DPG texture + image widget. Every call is guarded
        # so headless tests pass without a live DPG context.
        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            return

        try:
            flat = self._as_dpg_float(self.last_frame)
            # Use a top-level texture_registry so re-parenting the panel
            # (dock/undock) doesn't invalidate the tag.
            try:
                if dpg.does_item_exist(self._texture_tag):
                    dpg.delete_item(self._texture_tag)
            except Exception:
                pass
            try:
                with dpg.texture_registry(show=False):
                    dpg.add_dynamic_texture(
                        self.width,
                        self.height,
                        flat,
                        tag=self._texture_tag,
                    )
            except Exception:
                try:
                    dpg.add_dynamic_texture(
                        self.width,
                        self.height,
                        flat,
                        tag=self._texture_tag,
                    )
                except Exception:
                    return
            try:
                if dpg.does_item_exist(self._image_tag):
                    dpg.delete_item(self._image_tag)
            except Exception:
                pass
            dpg.add_image(
                self._texture_tag,
                parent=parent_tag,
                width=self.width,
                height=self.height,
                tag=self._image_tag,
            )
        except Exception:
            # A DPG failure must never propagate — the panel is decorative.
            return

    def tick(self, dt: float = 1.0 / 60.0) -> None:
        """Advance the demo scene by *dt* seconds and re-upload the frame.

        Called from the shell's per-frame subsystem tick. The cube
        rotates at ~30 degrees/sec so the motion is legible without
        making the user seasick. When wgpu isn't up this is a no-op —
        the placeholder image is static.
        """
        self._angle += dt * math.radians(30.0)
        try:
            self.render()
        except Exception:
            return
        self._push_to_dpg()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def resize(self, width: int, height: int) -> None:
        """Resize the offscreen render target + DPG image widget.

        Keeps the aspect + auto-fits the centre tab. If wgpu is up the
        colour / depth textures + readback buffer are rebuilt; otherwise
        only the placeholder ndarray is resized.
        """
        w = max(16, int(width))
        h = max(16, int(height))
        if w == self.width and h == self.height:
            return
        self.width = w
        self.height = h
        if self._device is not None:
            try:
                self._create_targets()
            except Exception:
                # If target rebuild fails (device lost, huge alloc), drop
                # back to the placeholder path so the panel stays alive.
                self._device = None
                self.backend = "placeholder"
        if self._device is None:
            self.last_frame = _draw_placeholder(
                self.width, self.height, self.placeholder_message,
            )
        # DPG texture must be recreated — dynamic_texture size is fixed.
        try:
            import dearpygui.dearpygui as dpg
            if self._parent_tag is not None:
                self.build(self._parent_tag)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # GPU bring-up
    # ------------------------------------------------------------------

    def _init_gpu(self) -> None:
        """Request a device, compile the shader, build the pipeline + targets.

        Every step is wrapped so a failure at any point drops the panel
        into the placeholder mode with a message describing the fault.
        The final :attr:`backend` string is set from the adapter info.
        """
        if _wgpu is None or _wgpu_utils is None:
            self.placeholder_message = "wgpu module not installed"
            self.last_frame = _draw_placeholder(
                self.width, self.height, self.placeholder_message,
            )
            return

        try:
            device = _wgpu_utils.get_default_device()
        except Exception as e:  # pragma: no cover — GPU-dependent
            self.placeholder_message = f"wgpu adapter unavailable: {e!r}"
            self.last_frame = _draw_placeholder(
                self.width, self.height, self.placeholder_message,
            )
            return

        try:
            info = dict(device.adapter.info)
            self.backend = str(info.get("backend_type", "Unknown"))
        except Exception:
            self.backend = "Unknown"

        self._device = device
        self._queue = device.queue

        try:
            self._create_pipeline()
            self._create_targets()
            self._upload_mesh()
        except Exception as e:  # pragma: no cover — GPU-dependent
            self._device = None
            self._queue = None
            self.backend = "placeholder"
            self.placeholder_message = f"wgpu pipeline error: {e!r}"
            self.last_frame = _draw_placeholder(
                self.width, self.height, self.placeholder_message,
            )

    def _load_shader_source(self) -> str:
        with open(self._SHADER_PATH, "r", encoding="utf-8") as fh:
            return fh.read()

    def _create_pipeline(self) -> None:
        """Compile ``viewport_basic.wgsl`` and build the render pipeline."""
        assert self._device is not None
        wgsl = self._load_shader_source()

        module = self._device.create_shader_module(code=wgsl)

        # Uniform buffer — 3 mat4 + 4 vec4 = 192 + 64 = 256 bytes.
        # WGSL rounds struct sizes up to a multiple of the largest member
        # alignment (mat4x4 = 16), so 256 is exactly what the shader wants.
        ubo_size = 64 * 3 + 16 * 4
        self._uniform_buffer = self._device.create_buffer(
            size=ubo_size,
            usage=_wgpu.BufferUsage.UNIFORM | _wgpu.BufferUsage.COPY_DST,
        )

        bgl = self._device.create_bind_group_layout(entries=[
            {
                "binding": 0,
                "visibility": _wgpu.ShaderStage.VERTEX | _wgpu.ShaderStage.FRAGMENT,
                "buffer": {"type": _wgpu.BufferBindingType.uniform},
            },
        ])

        self._bind_group = self._device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": self._uniform_buffer, "offset": 0, "size": ubo_size}},
            ],
        )

        layout = self._device.create_pipeline_layout(bind_group_layouts=[bgl])

        self._pipeline = self._device.create_render_pipeline(
            layout=layout,
            vertex={
                "module": module,
                "entry_point": "vs_main",
                "buffers": [
                    {
                        "array_stride": 6 * 4,  # 6 floats * 4 bytes
                        "step_mode": _wgpu.VertexStepMode.vertex,
                        "attributes": [
                            {"format": _wgpu.VertexFormat.float32x3, "offset": 0,  "shader_location": 0},
                            {"format": _wgpu.VertexFormat.float32x3, "offset": 12, "shader_location": 1},
                        ],
                    },
                ],
            },
            primitive={
                "topology": _wgpu.PrimitiveTopology.triangle_list,
                "front_face": _wgpu.FrontFace.ccw,
                # No culling — the offscreen render target uses the same
                # right-handed math the shader expects, so back faces are
                # occluded by the depth buffer without needing GPU-side
                # culling. Skipping this dodges a subtle NDC-Y-flip trap
                # where a forgotten viewport-Y flip inverts winding.
                "cull_mode": _wgpu.CullMode.none,
            },
            depth_stencil={
                "format": _wgpu.TextureFormat.depth24plus,
                "depth_write_enabled": True,
                "depth_compare": _wgpu.CompareFunction.less,
            },
            multisample={"count": 1, "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            fragment={
                "module": module,
                "entry_point": "fs_main",
                "targets": [
                    {"format": _wgpu.TextureFormat.rgba8unorm},
                ],
            },
        )

    def _create_targets(self) -> None:
        """Allocate colour + depth textures + the CPU readback buffer.

        Called on init and again on :meth:`resize`.
        """
        assert self._device is not None
        # Colour target — rgba8unorm to match the DPG-friendly readback.
        self._color_texture = self._device.create_texture(
            size=(self.width, self.height, 1),
            format=_wgpu.TextureFormat.rgba8unorm,
            usage=_wgpu.TextureUsage.RENDER_ATTACHMENT | _wgpu.TextureUsage.COPY_SRC,
        )
        self._color_view = self._color_texture.create_view()

        self._depth_texture = self._device.create_texture(
            size=(self.width, self.height, 1),
            format=_wgpu.TextureFormat.depth24plus,
            usage=_wgpu.TextureUsage.RENDER_ATTACHMENT,
        )
        self._depth_view = self._depth_texture.create_view()

    def _upload_mesh(self) -> None:
        """Upload the cube VBO + IBO to the GPU."""
        assert self._device is not None and self._queue is not None
        vbytes = self._vertices.tobytes()
        ibytes = self._indices.tobytes()
        self._vertex_buffer = self._device.create_buffer(
            size=len(vbytes),
            usage=_wgpu.BufferUsage.VERTEX | _wgpu.BufferUsage.COPY_DST,
        )
        self._queue.write_buffer(self._vertex_buffer, 0, vbytes)
        self._index_buffer = self._device.create_buffer(
            size=len(ibytes),
            usage=_wgpu.BufferUsage.INDEX | _wgpu.BufferUsage.COPY_DST,
        )
        self._queue.write_buffer(self._index_buffer, 0, ibytes)

    # ------------------------------------------------------------------
    # Frame rendering
    # ------------------------------------------------------------------

    def render(self) -> np.ndarray:
        """Render a single frame, download it to CPU, cache into ``last_frame``.

        Returns the same array as :attr:`last_frame` — a ``(H, W, 4)``
        ``uint8`` RGBA image. When wgpu isn't up the return is the
        placeholder image so callers still get a valid ndarray.
        """
        if self._device is None:
            # Refresh the placeholder in case someone resized us.
            self.last_frame = _draw_placeholder(
                self.width, self.height, self.placeholder_message,
            )
            return self.last_frame

        # ---- Update uniforms -----------------------------------------
        model = _rot_y(self._angle) @ _rot_x(self._angle * 0.6)
        view = _look_at(self._cam_eye, self._cam_target, self._cam_up)
        aspect = float(self.width) / float(max(1, self.height))
        proj = _perspective(55.0, aspect, 0.1, 100.0)

        ubo = np.concatenate([
            _column_major(model),
            _column_major(view),
            _column_major(proj),
            self._light_pos,
            self._light_color,
            np.array([*self._cam_eye, 1.0], dtype=np.float32),
            self._base_color,
        ]).astype(np.float32)
        self._queue.write_buffer(self._uniform_buffer, 0, ubo.tobytes())

        # ---- Encode + submit ----------------------------------------
        encoder = self._device.create_command_encoder()
        rpass = encoder.begin_render_pass(
            color_attachments=[
                {
                    "view": self._color_view,
                    "clear_value": (0.09, 0.10, 0.13, 1.0),
                    "load_op": _wgpu.LoadOp.clear,
                    "store_op": _wgpu.StoreOp.store,
                },
            ],
            depth_stencil_attachment={
                "view": self._depth_view,
                "depth_clear_value": 1.0,
                "depth_load_op": _wgpu.LoadOp.clear,
                "depth_store_op": _wgpu.StoreOp.store,
            },
        )
        rpass.set_pipeline(self._pipeline)
        rpass.set_bind_group(0, self._bind_group)
        rpass.set_vertex_buffer(0, self._vertex_buffer)
        rpass.set_index_buffer(self._index_buffer, _wgpu.IndexFormat.uint32)
        rpass.draw_indexed(self._index_count)
        rpass.end()

        self._queue.submit([encoder.finish()])

        # ---- Read pixels back to CPU --------------------------------
        # ``queue.read_texture`` handles the row-padding + buffer plumbing
        # internally and returns a memoryview we can wrap in a numpy view
        # zero-copy. It blocks until the submitted commands complete, so
        # we don't need an explicit fence.
        bytes_per_row = self.width * 4
        data = self._queue.read_texture(
            {"texture": self._color_texture, "mip_level": 0, "origin": (0, 0, 0)},
            {"offset": 0, "bytes_per_row": bytes_per_row, "rows_per_image": self.height},
            (self.width, self.height, 1),
        )
        img = np.frombuffer(bytes(data), dtype=np.uint8).reshape(
            self.height, self.width, 4,
        ).copy()
        self.last_frame = img
        return img

    # ------------------------------------------------------------------
    # DPG plumbing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _as_dpg_float(rgba: np.ndarray) -> list[float]:
        """Convert a uint8 RGBA ndarray into the flat float32 list DPG wants."""
        return (rgba.astype(np.float32) / 255.0).flatten().tolist()

    def _push_to_dpg(self) -> None:
        """Upload :attr:`last_frame` into the registered dynamic texture."""
        try:
            import dearpygui.dearpygui as dpg
        except Exception:
            return
        try:
            if not dpg.does_item_exist(self._texture_tag):
                return
            dpg.set_value(self._texture_tag, self._as_dpg_float(self.last_frame))
        except Exception:
            return
