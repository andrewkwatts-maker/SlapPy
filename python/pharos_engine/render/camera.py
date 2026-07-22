"""Cameras for the forward renderer.

* :class:`Camera3D` — right-handed perspective camera with ``look_at`` target.
* :class:`Camera2D` — orthographic camera for sprite / UI rendering.

All matrices are returned as 4x4 ``float32`` numpy arrays in the
``M @ column_vector`` convention (row-major numpy storage, column-vector
math). The projection uses reverse-Y clip space to match WebGPU
(``[-1, 1]`` XY, ``[0, 1]`` Z).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


# ----------------------------------------------------------------------
# 3D camera
# ----------------------------------------------------------------------
@dataclass
class Camera3D:
    position: tuple[float, float, float] = (0.0, 0.0, 5.0)
    look_at: tuple[float, float, float] = (0.0, 0.0, 0.0)
    up: tuple[float, float, float] = (0.0, 1.0, 0.0)
    fov_degrees: float = 60.0
    near: float = 0.1
    far: float = 500.0
    aspect: float = 16.0 / 9.0

    def view_matrix(self) -> np.ndarray:
        eye = np.asarray(self.position, dtype=np.float32)
        target = np.asarray(self.look_at, dtype=np.float32)
        up = np.asarray(self.up, dtype=np.float32)

        f = target - eye
        fn = np.linalg.norm(f)
        if fn < 1e-8:
            return np.eye(4, dtype=np.float32)
        f = f / fn

        s = np.cross(f, up)
        sn = np.linalg.norm(s)
        if sn < 1e-8:
            # Fallback: pick a non-collinear up.
            s = np.cross(f, np.array([0.0, 0.0, 1.0], dtype=np.float32))
            sn = np.linalg.norm(s) or 1.0
        s = s / sn
        u = np.cross(s, f)

        m = np.eye(4, dtype=np.float32)
        m[0, :3] = s
        m[1, :3] = u
        m[2, :3] = -f
        m[0, 3] = -float(np.dot(s, eye))
        m[1, 3] = -float(np.dot(u, eye))
        m[2, 3] = float(np.dot(f, eye))
        return m

    def projection_matrix(self) -> np.ndarray:
        """Reverse-Y perspective, mapping z ∈ [near, far] → [0, 1]."""
        fov_rad = math.radians(self.fov_degrees)
        f = 1.0 / math.tan(fov_rad * 0.5)
        near = float(self.near)
        far = float(self.far)
        aspect = float(self.aspect) or 1.0
        m = np.zeros((4, 4), dtype=np.float32)
        m[0, 0] = f / aspect
        m[1, 1] = f
        m[2, 2] = far / (near - far)
        m[2, 3] = (near * far) / (near - far)
        m[3, 2] = -1.0
        return m

    def view_projection(self) -> np.ndarray:
        return self.projection_matrix() @ self.view_matrix()


# ----------------------------------------------------------------------
# 2D camera
# ----------------------------------------------------------------------
@dataclass
class Camera2D:
    position: tuple[float, float] = (0.0, 0.0)
    zoom: float = 1.0
    viewport_size: tuple[int, int] = (1280, 720)

    def view_matrix(self) -> np.ndarray:
        m = np.eye(4, dtype=np.float32)
        px, py = self.position
        m[0, 3] = -px
        m[1, 3] = -py
        return m

    def projection_matrix(self) -> np.ndarray:
        w, h = self.viewport_size
        z = float(self.zoom) or 1.0
        half_w = 0.5 * w / z
        half_h = 0.5 * h / z
        m = np.eye(4, dtype=np.float32)
        m[0, 0] = 1.0 / half_w
        m[1, 1] = 1.0 / half_h
        # Depth: 2D scene lives on z ≈ 0; map any z ∈ [-1, 1] linearly to [0, 1].
        m[2, 2] = 0.5
        m[2, 3] = 0.5
        return m

    def view_projection(self) -> np.ndarray:
        return self.projection_matrix() @ self.view_matrix()
