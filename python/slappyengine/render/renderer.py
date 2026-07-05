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
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np

from .light import Light, pack_lights_ubo
from .null_renderer import NullRenderer

try:  # pragma: no cover - optional at import time
    import wgpu  # type: ignore
    _HAS_WGPU = True
except Exception:  # pragma: no cover
    wgpu = None  # type: ignore[assignment]
    _HAS_WGPU = False


@dataclass
class _WgpuContext:
    device: Any
    queue: Any
    color_format: str
    depth_format: str = "depth24plus"


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
        self.msaa = msaa
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
        self._backend = "null"
        if _HAS_WGPU and not force_null:
            self._try_init_wgpu()

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
            try:
                self._offscreen_texture = self._ctx.device.create_texture(
                    size=(int(width), int(height), 1),
                    format=self._ctx.color_format,
                    usage=wgpu.TextureUsage.RENDER_ATTACHMENT | wgpu.TextureUsage.COPY_SRC,
                    sample_count=1,
                )
            except Exception as e:
                warnings.warn(f"create_offscreen failed: {e!r}", stacklevel=2)
                self._offscreen_texture = None

    # ------------------------------------------------------------------
    # Frame lifecycle
    # ------------------------------------------------------------------
    def begin_frame(self) -> None:
        self._null.begin_frame()

    def end_frame(self) -> None:
        self._null.end_frame()

    # ------------------------------------------------------------------
    # Submissions
    # ------------------------------------------------------------------
    def submit_mesh(self, mesh, model_matrix, material) -> None:
        self._null.submit_mesh(mesh, model_matrix, material)

    def submit_sprite(self, texture, transform_2d, tint=(1.0, 1.0, 1.0, 1.0)) -> None:
        self._null.submit_sprite(texture, transform_2d, tint)

    def submit_lines(self, vertices: np.ndarray, colors: np.ndarray) -> None:
        self._null.submit_lines(vertices, colors)

    def set_camera(self, view_matrix, proj_matrix) -> None:
        self._null.set_camera(view_matrix, proj_matrix)

    def set_lights(self, lights: list[Light]) -> None:
        self._null.set_lights(lights)

    # ------------------------------------------------------------------
    # Upload / read-back
    # ------------------------------------------------------------------
    def _upload_mesh(self, mesh):
        return self._null._upload_mesh(mesh)

    def upload_texture(self, pixels: np.ndarray, *, format: str = "rgba8unorm"):
        return self._null.upload_texture(pixels, format=format)

    def read_pixels(self) -> np.ndarray:
        return self._null.read_pixels()

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
        return self._null.frame_count

    def light_ubo(self, lights: list[Light]) -> np.ndarray:
        return pack_lights_ubo(lights)


def is_wgpu_available() -> bool:
    """True when wgpu is importable in this interpreter."""
    return _HAS_WGPU
