"""Fly camera controller for the v2 viewport.

Reads imgui input state each frame; produces updated
``(position, target)`` tuples that get pushed into the Rust
`pharos_engine._core.render.Renderer` camera setters.

Controls (matches Nova3D / Unity / UE conventions):
- **RMB drag** — yaw + pitch around the target.
- **MMB drag** — pan the target along the view plane.
- **Scroll wheel** — dolly in/out.
- **WASD** (while RMB held) — fly forward/back/left/right.
- **Q/E** (while RMB held) — descend/ascend.
"""
from __future__ import annotations

import math

from imgui_bundle import imgui


class FlyCameraController:
    """Yaw/pitch/dolly camera state driven by imgui mouse + key input."""

    def __init__(self) -> None:
        # Spherical coords around target: (radius, yaw, pitch).
        self.radius: float = 3.5
        self.yaw: float = math.radians(35.0)
        self.pitch: float = math.radians(-25.0)
        self.target: list[float] = [0.0, 0.0, 0.0]
        # Sensitivity — tuned to match Blender's default feel.
        self.orbit_sens: float = 0.008
        self.pan_sens: float = 0.005
        self.dolly_sens: float = 0.20
        self.fly_speed: float = 5.0

    def position(self) -> tuple[float, float, float]:
        """Compute world-space camera position from spherical state."""
        cp = math.cos(self.pitch)
        sp = math.sin(self.pitch)
        cy = math.cos(self.yaw)
        sy = math.sin(self.yaw)
        # Standard right-handed y-up spherical -> cartesian.
        offset = (
            self.radius * cp * sy,
            self.radius * sp,
            self.radius * cp * cy,
        )
        return (
            self.target[0] + offset[0],
            self.target[1] + offset[1],
            self.target[2] + offset[2],
        )

    def _forward(self) -> tuple[float, float, float]:
        pos = self.position()
        return (
            self.target[0] - pos[0],
            self.target[1] - pos[1],
            self.target[2] - pos[2],
        )

    def _view_axes(self) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Right vector + up vector in world space (unit length)."""
        fwd = self._forward()
        fl = math.sqrt(sum(c * c for c in fwd))
        if fl < 1e-8:
            return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        f = (fwd[0] / fl, fwd[1] / fl, fwd[2] / fl)
        world_up = (0.0, 1.0, 0.0)
        # right = normalize(cross(fwd, up))
        rx = f[1] * world_up[2] - f[2] * world_up[1]
        ry = f[2] * world_up[0] - f[0] * world_up[2]
        rz = f[0] * world_up[1] - f[1] * world_up[0]
        rl = math.sqrt(rx * rx + ry * ry + rz * rz)
        if rl < 1e-6:
            return (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)
        r = (rx / rl, ry / rl, rz / rl)
        # up = cross(right, fwd) — orthonormalise.
        u = (
            r[1] * f[2] - r[2] * f[1],
            r[2] * f[0] - r[0] * f[2],
            r[0] * f[1] - r[1] * f[0],
        )
        return r, u

    def tick(self, viewport_hovered: bool) -> bool:
        """Sample imgui state for the current frame.

        Returns ``True`` if any camera parameter changed — the caller
        uses this to decide whether to push new values into the
        Renderer (skip on unchanged frames for zero-cost idle).
        """
        io = imgui.get_io()
        changed = False

        # ── Scroll dolly (works whenever the viewport is hovered) ─────
        if viewport_hovered and abs(io.mouse_wheel) > 0.0:
            self.radius = max(0.1, self.radius * math.exp(-io.mouse_wheel * self.dolly_sens))
            changed = True

        # ── Right-mouse drag: orbit (yaw / pitch) ─────────────────────
        rmb = imgui.MouseButton_.right.value
        mmb = imgui.MouseButton_.middle.value
        if imgui.is_mouse_dragging(rmb, 0.5):
            dx, dy = io.mouse_delta.x, io.mouse_delta.y
            if dx or dy:
                self.yaw -= dx * self.orbit_sens
                self.pitch = max(-1.55, min(1.55, self.pitch - dy * self.orbit_sens))
                imgui.reset_mouse_drag_delta(rmb)
                changed = True

            # ── WASD + QE while RMB held: fly along view axes ─────────
            r, u = self._view_axes()
            fwd = self._forward()
            fl = math.sqrt(sum(c * c for c in fwd))
            f = (fwd[0] / fl, fwd[1] / fl, fwd[2] / fl) if fl > 1e-6 else (0.0, 0.0, -1.0)
            step = self.fly_speed * io.delta_time
            dv = [0.0, 0.0, 0.0]
            keymap = [
                (imgui.Key.w, f, +1.0),
                (imgui.Key.s, f, -1.0),
                (imgui.Key.d, r, +1.0),
                (imgui.Key.a, r, -1.0),
                (imgui.Key.e, u, +1.0),
                (imgui.Key.q, u, -1.0),
            ]
            for key, axis, sign in keymap:
                if imgui.is_key_down(key):
                    dv[0] += axis[0] * sign * step
                    dv[1] += axis[1] * sign * step
                    dv[2] += axis[2] * sign * step
            if dv != [0.0, 0.0, 0.0]:
                self.target[0] += dv[0]
                self.target[1] += dv[1]
                self.target[2] += dv[2]
                changed = True

        # ── Middle-mouse drag: pan target along view plane ────────────
        if imgui.is_mouse_dragging(mmb, 0.5):
            r, u = self._view_axes()
            dx, dy = io.mouse_delta.x, io.mouse_delta.y
            if dx or dy:
                self.target[0] -= (r[0] * dx - u[0] * dy) * self.pan_sens * self.radius
                self.target[1] -= (r[1] * dx - u[1] * dy) * self.pan_sens * self.radius
                self.target[2] -= (r[2] * dx - u[2] * dy) * self.pan_sens * self.radius
                imgui.reset_mouse_drag_delta(mmb)
                changed = True

        return changed

    def reset(self) -> None:
        self.radius = 3.5
        self.yaw = math.radians(35.0)
        self.pitch = math.radians(-25.0)
        self.target = [0.0, 0.0, 0.0]
