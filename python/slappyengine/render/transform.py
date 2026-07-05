"""3D transform (position + quaternion rotation + scale) with matrix composition.

Quaternion convention: (x, y, z, w) — right-handed.
Matrix convention: column-major math using row-major numpy storage; the
returned 4x4 is ready to multiply column vectors as ``M @ v``.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def _identity_quat() -> tuple[float, float, float, float]:
    return (0.0, 0.0, 0.0, 1.0)


@dataclass
class Transform3D:
    """Rigid + scale transform.

    Attributes
    ----------
    position : (x, y, z)
    rotation : quaternion (x, y, z, w). Identity is (0, 0, 0, 1).
    scale    : (sx, sy, sz)
    """

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float, float] = field(default_factory=_identity_quat)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)

    # ------------------------------------------------------------------
    # Fluent builders
    # ------------------------------------------------------------------
    def translate(self, x: float, y: float, z: float) -> "Transform3D":
        px, py, pz = self.position
        return Transform3D((px + x, py + y, pz + z), self.rotation, self.scale)

    def rotate_x(self, rad: float) -> "Transform3D":
        return self._compose_axis((1.0, 0.0, 0.0), rad)

    def rotate_y(self, rad: float) -> "Transform3D":
        return self._compose_axis((0.0, 1.0, 0.0), rad)

    def rotate_z(self, rad: float) -> "Transform3D":
        return self._compose_axis((0.0, 0.0, 1.0), rad)

    def scale_by(self, sx: float, sy: float, sz: float) -> "Transform3D":
        cx, cy, cz = self.scale
        return Transform3D(self.position, self.rotation, (cx * sx, cy * sy, cz * sz))

    def _compose_axis(self, axis: tuple[float, float, float], rad: float) -> "Transform3D":
        ax, ay, az = axis
        s = math.sin(rad * 0.5)
        c = math.cos(rad * 0.5)
        qa = (ax * s, ay * s, az * s, c)
        qb = self.rotation
        # Hamilton product qa * qb.
        ax_, ay_, az_, aw = qa
        bx, by, bz, bw = qb
        rx = aw * bx + ax_ * bw + ay_ * bz - az_ * by
        ry = aw * by - ax_ * bz + ay_ * bw + az_ * bx
        rz = aw * bz + ax_ * by - ay_ * bx + az_ * bw
        rw = aw * bw - ax_ * bx - ay_ * by - az_ * bz
        return Transform3D(self.position, (rx, ry, rz, rw), self.scale)

    # ------------------------------------------------------------------
    # Matrix
    # ------------------------------------------------------------------
    def matrix(self) -> np.ndarray:
        """Return 4x4 model matrix M = T · R · S."""
        qx, qy, qz, qw = self.rotation
        # Normalise defensively (avoid drift-poisoning downstream matrices).
        n = math.sqrt(qx * qx + qy * qy + qz * qz + qw * qw) or 1.0
        qx, qy, qz, qw = qx / n, qy / n, qz / n, qw / n
        xx, yy, zz = qx * qx, qy * qy, qz * qz
        xy, xz, yz = qx * qy, qx * qz, qy * qz
        wx, wy, wz = qw * qx, qw * qy, qw * qz
        sx, sy, sz = self.scale
        px, py, pz = self.position
        m = np.array(
            [
                [(1 - 2 * (yy + zz)) * sx, 2 * (xy - wz) * sy, 2 * (xz + wy) * sz, px],
                [2 * (xy + wz) * sx, (1 - 2 * (xx + zz)) * sy, 2 * (yz - wx) * sz, py],
                [2 * (xz - wy) * sx, 2 * (yz + wx) * sy, (1 - 2 * (xx + yy)) * sz, pz],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
        return m


@dataclass
class Transform2D:
    """2D transform used by :meth:`Renderer.submit_sprite`."""

    position: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0  # radians
    scale: tuple[float, float] = (1.0, 1.0)

    def matrix(self) -> np.ndarray:
        c = math.cos(self.rotation)
        s = math.sin(self.rotation)
        sx, sy = self.scale
        px, py = self.position
        return np.array(
            [
                [c * sx, -s * sy, px],
                [s * sx, c * sy, py],
                [0.0, 0.0, 1.0],
            ],
            dtype=np.float32,
        )
