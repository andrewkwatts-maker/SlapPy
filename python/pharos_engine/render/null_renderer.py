"""NullRenderer — GPU-free renderer that records draw calls.

Used by:
* headless CI (no wgpu / no display),
* HH1's ``App(enable_gpu=False)``,
* unit tests exercising the renderer API without hitting a GPU.

Draw calls are captured verbatim into :attr:`NullRenderer.draw_log`, and
``read_pixels`` returns a filled RGBA buffer painted with the clear
colour so callers can still compare against fixture bytes.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .light import Light, pack_lights_ubo


@dataclass
class DrawCall:
    kind: str  # "mesh" | "sprite" | "line" | "camera" | "lights" | "clear"
    payload: dict = field(default_factory=dict)


class NullRenderer:
    """No-op renderer that records every submission for inspection."""

    def __init__(
        self,
        *,
        window_size: tuple[int, int] = (1280, 720),
        msaa: int = 4,
        clear_color: tuple[float, float, float, float] = (0.05, 0.06, 0.08, 1.0),
        vsync: bool = True,
    ) -> None:
        self.window_size = window_size
        self.msaa = msaa
        self.clear_color = clear_color
        self.vsync = vsync
        self.draw_log: list[DrawCall] = []
        self._frame_open = False
        self._frame_count = 0
        self._mesh_ids = itertools.count(1)
        self._tex_ids = itertools.count(1)
        self._current_camera: tuple[np.ndarray, np.ndarray] | None = None
        self._current_lights: list[Light] = []
        self._offscreen_size: tuple[int, int] | None = None

    # ------------------------------------------------------------------
    # Surface / offscreen
    # ------------------------------------------------------------------
    def create_surface(self, window_handle: Any) -> None:  # noqa: D401
        """No-op — the null renderer never binds to a real surface."""
        self.draw_log.append(DrawCall("surface", {"handle": repr(window_handle)}))

    def create_offscreen(self, width: int, height: int) -> None:
        self._offscreen_size = (int(width), int(height))
        self.window_size = self._offscreen_size
        self.draw_log.append(DrawCall("offscreen", {"size": self._offscreen_size}))

    # ------------------------------------------------------------------
    # Frame lifecycle
    # ------------------------------------------------------------------
    def begin_frame(self) -> None:
        if self._frame_open:
            raise RuntimeError("begin_frame called twice without end_frame")
        self._frame_open = True
        self.draw_log.append(DrawCall("clear", {"color": self.clear_color}))

    def end_frame(self) -> None:
        if not self._frame_open:
            raise RuntimeError("end_frame called without begin_frame")
        self._frame_open = False
        self._frame_count += 1
        self.draw_log.append(DrawCall("present", {"frame": self._frame_count}))

    # ------------------------------------------------------------------
    # Submission
    # ------------------------------------------------------------------
    def submit_mesh(self, mesh, model_matrix, material) -> None:
        if not self._frame_open:
            raise RuntimeError("submit_mesh outside begin/end_frame")
        self.draw_log.append(
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

    def submit_sprite(self, texture, transform_2d, tint=(1.0, 1.0, 1.0, 1.0)) -> None:
        if not self._frame_open:
            raise RuntimeError("submit_sprite outside begin/end_frame")
        self.draw_log.append(
            DrawCall(
                "sprite",
                {
                    "texture_id": getattr(texture, "id", None),
                    "transform_2d": np.asarray(transform_2d, dtype=np.float32).copy(),
                    "tint": tuple(float(x) for x in tint),
                },
            )
        )

    def submit_lines(self, vertices: np.ndarray, colors: np.ndarray) -> None:
        if not self._frame_open:
            raise RuntimeError("submit_lines outside begin/end_frame")
        self.draw_log.append(
            DrawCall(
                "line",
                {
                    "count": int(vertices.shape[0]) // 2,
                    "vertices": np.asarray(vertices, dtype=np.float32).copy(),
                    "colors": np.asarray(colors, dtype=np.float32).copy(),
                },
            )
        )

    def set_camera(self, view_matrix, proj_matrix) -> None:
        v = np.asarray(view_matrix, dtype=np.float32).copy()
        p = np.asarray(proj_matrix, dtype=np.float32).copy()
        self._current_camera = (v, p)
        self.draw_log.append(DrawCall("camera", {"view": v, "proj": p}))

    def set_lights(self, lights: list[Light]) -> None:
        self._current_lights = list(lights)
        ubo = pack_lights_ubo(self._current_lights)
        self.draw_log.append(
            DrawCall(
                "lights",
                {"count": len(self._current_lights), "ubo": ubo.copy()},
            )
        )

    # ------------------------------------------------------------------
    # Upload / read-back
    # ------------------------------------------------------------------
    def _upload_mesh(self, mesh):
        from .mesh import MeshHandle
        return MeshHandle(
            buffer_id=next(self._mesh_ids),
            vertex_count=int(mesh.vertices.shape[0]),
            index_count=int(mesh.indices.shape[0]),
            gpu_buffers=None,
        )

    def upload_texture(self, pixels: np.ndarray, *, format: str = "rgba8unorm"):
        from .material import TextureHandle
        px = np.asarray(pixels)
        return TextureHandle(
            id=next(self._tex_ids),
            width=int(px.shape[1]),
            height=int(px.shape[0]),
            format=format,
            gpu_texture=None,
        )

    def read_pixels(self) -> np.ndarray:
        w, h = self.window_size
        img = np.zeros((h, w, 4), dtype=np.uint8)
        r, g, b, a = self.clear_color
        img[..., 0] = int(round(r * 255))
        img[..., 1] = int(round(g * 255))
        img[..., 2] = int(round(b * 255))
        img[..., 3] = int(round(a * 255))
        return img

    # ------------------------------------------------------------------
    # Introspection helpers used by tests + HH1 hookup
    # ------------------------------------------------------------------
    def clear_log(self) -> None:
        self.draw_log.clear()

    def calls_of(self, kind: str) -> list[DrawCall]:
        return [c for c in self.draw_log if c.kind == kind]

    @property
    def frame_count(self) -> int:
        return self._frame_count
