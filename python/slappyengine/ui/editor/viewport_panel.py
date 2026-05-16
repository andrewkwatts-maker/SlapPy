from __future__ import annotations

import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.engine import Engine


# ---------------------------------------------------------------------------
# Module-level math helpers
# ---------------------------------------------------------------------------

def _look_at(eye: list[float], target: list[float], up: list[float]) -> list[float]:
    """Build a column-major 4×4 view matrix (OpenGL/wgpu convention).

    Parameters
    ----------
    eye:    Camera position in world space.
    target: Point the camera looks at.
    up:     World-space up vector (usually [0, 1, 0]).

    Returns
    -------
    16 floats in column-major order (mat4 columns stored consecutively).
    """
    # Forward (from eye toward target, negated to get -Z in view space)
    fx = target[0] - eye[0]
    fy = target[1] - eye[1]
    fz = target[2] - eye[2]
    inv_f = 1.0 / math.sqrt(fx * fx + fy * fy + fz * fz)
    fx, fy, fz = fx * inv_f, fy * inv_f, fz * inv_f

    # Right = forward × up
    rx = fy * up[2] - fz * up[1]
    ry = fz * up[0] - fx * up[2]
    rz = fx * up[1] - fy * up[0]
    inv_r = 1.0 / math.sqrt(rx * rx + ry * ry + rz * rz)
    rx, ry, rz = rx * inv_r, ry * inv_r, rz * inv_r

    # True up = right × forward
    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx

    # Translation components: -dot(right, eye), -dot(up, eye), dot(forward, eye)
    tx = -(rx * eye[0] + ry * eye[1] + rz * eye[2])
    ty = -(ux * eye[0] + uy * eye[1] + uz * eye[2])
    tz =  (fx * eye[0] + fy * eye[1] + fz * eye[2])

    # Column-major mat4 — each group of four values is one column
    # col0: right.x  right.y  right.z  0
    # col1: up.x     up.y     up.z     0
    # col2: -fwd.x  -fwd.y   -fwd.z   0
    # col3: tx       ty       tz       1
    return [
        rx,   ry,   rz,   0.0,   # col 0
        ux,   uy,   uz,   0.0,   # col 1
        -fx, -fy,  -fz,   0.0,   # col 2
        tx,   ty,   tz,   1.0,   # col 3
    ]


def _make_blank_pixels(width: int, height: int) -> list[float]:
    """Return a flat RGBA float32 list of zeros for a width×height image."""
    return [0.0] * (width * height * 4)


# ---------------------------------------------------------------------------
# ViewportPanel
# ---------------------------------------------------------------------------

class ViewportPanel:
    """
    Bridges wgpu render output into a DPG image widget.

    wgpu renders to self._offscreen_texture → CPU readback → DPG raw texture.
    Full wgpu integration requires engine._gpu to be initialized.

    The panel supports two camera modes selected via :meth:`set_mode`:

    * ``"2D"`` — orthographic pan/zoom (original behaviour).
    * ``"3D"`` — perspective orbit/pan/zoom around a look-at target.
      Call :meth:`get_view_matrix` and :meth:`get_proj_matrix` each frame to
      obtain column-major mat4 data ready for ``MeshRenderer.update_camera()``.

    Usage::

        panel = ViewportPanel(engine, width=1280, height=720)
        panel.build(parent_tag="primary_window")

        # Switch modes (e.g. wired to toolbar 2D/3D toggle):
        panel.set_mode("3D")

        # Each frame:
        panel.update(flat_rgba_floats)

        # In 3D mode — pass matrices to the mesh renderer:
        w, h = panel.get_size()
        view = panel.get_view_matrix()
        proj = panel.get_proj_matrix(aspect=w / h)
        mesh_renderer.update_camera(model, view, proj, normal_matrix)
    """

    # ------------------------------------------------------------------
    # Drag button constants (DPG mouse button indices)
    # ------------------------------------------------------------------
    _BTN_LEFT   = 0  # orbit
    _BTN_RIGHT  = 1  # pan
    _BTN_MIDDLE = 2  # pan (alias)

    def __init__(self, engine: "Engine", width: int, height: int) -> None:
        self._engine = engine
        self._width = width
        self._height = height
        self._texture_tag: str = "viewport_texture"
        self._image_tag: str = "viewport_image"
        # Flat RGBA float32 list, initialised to a fully-transparent black frame.
        self._pixel_data: list[float] = _make_blank_pixels(width, height)

        # ------------------------------------------------------------------
        # 3D orbit camera state
        # ------------------------------------------------------------------
        self._cam_yaw: float = 0.0        # degrees — azimuth around world-Y
        self._cam_pitch: float = 30.0     # degrees — elevation from XZ plane
        self._cam_distance: float = 5.0   # units from target to camera eye
        self._cam_target: list[float] = [0.0, 0.0, 0.0]  # look-at point
        self._cam_fov: float = 60.0       # vertical field-of-view in degrees

        # ------------------------------------------------------------------
        # Mode ("2D" | "3D")
        # ------------------------------------------------------------------
        self._mode: str = "2D"

        # ------------------------------------------------------------------
        # Internal drag tracking for 3D mouse handlers
        # ------------------------------------------------------------------
        # Previous mouse position used to compute per-frame delta manually,
        # because dpg.get_mouse_drag_delta resets when the button is released.
        self._prev_mouse: tuple[float, float] = (0.0, 0.0)
        self._dragging_left: bool = False
        self._dragging_right: bool = False

    # ------------------------------------------------------------------
    # Public API — panel protocol
    # ------------------------------------------------------------------

    def build(self, parent_tag) -> None:
        """
        Register the raw texture and attach an image widget to *parent_tag*.

        Must be called after ``dpg.create_context()`` and before the first
        render loop iteration.
        """
        import dearpygui.dearpygui as dpg

        # Raw textures must be registered inside a texture_registry in DPG 2.x
        with dpg.texture_registry():
            dpg.add_raw_texture(
                self._width,
                self._height,
                self._pixel_data,
                tag=self._texture_tag,
                format=dpg.mvFormat_Float_rgba,
            )
        dpg.add_image(
            self._texture_tag,
            parent=parent_tag,
            width=self._width,
            height=self._height,
            tag=self._image_tag,
        )

    def update(self, pixel_data_flat: list | None = None) -> None:
        """
        Push a new frame into the DPG texture registry and process 3D mouse
        input (when in 3D mode).

        *pixel_data_flat* must be a flat list (or numpy array) of float32
        values in RGBA order, length == width * height * 4, values 0.0–1.0.
        Pass ``None`` (or omit) to skip the texture upload while still
        processing mouse input — useful when there is no new render output
        this frame.

        Called each frame with data from the wgpu CPU readback.
        """
        import dearpygui.dearpygui as dpg

        if pixel_data_flat is not None:
            dpg.set_value(self._texture_tag, pixel_data_flat)

        if self._mode == "3D":
            self._handle_3d_mouse()

    def get_size(self) -> tuple[int, int]:
        """Return ``(width, height)`` of the viewport in pixels."""
        return (self._width, self._height)

    # ------------------------------------------------------------------
    # Public API — mode switching
    # ------------------------------------------------------------------

    def set_mode(self, mode: str) -> None:
        """Switch between ``"2D"`` orthographic and ``"3D"`` perspective camera.

        When switching to ``"3D"`` the orbit/pan/zoom handlers activate
        automatically inside :meth:`update`.  When switching back to ``"2D"``
        they are disabled and the original 2D pan/zoom behaviour is restored
        (the 2D camera state is untouched by 3D orbit operations).

        Parameters
        ----------
        mode:
            ``"2D"`` or ``"3D"`` (case-sensitive).
        """
        if mode not in ("2D", "3D"):
            raise ValueError(f"mode must be '2D' or '3D', got {mode!r}")
        self._mode = mode
        # Reset drag tracking so stale deltas from the previous mode don't
        # bleed into the new one.
        self._dragging_left = False
        self._dragging_right = False

    # ------------------------------------------------------------------
    # Public API — 3D camera matrices
    # ------------------------------------------------------------------

    def get_view_matrix(self) -> list[float]:
        """Return 16 floats (column-major mat4) for the current 3D view matrix.

        Spherical-to-Cartesian conversion positions the camera eye on a sphere
        of radius ``_cam_distance`` centred on ``_cam_target``, oriented by
        ``_cam_yaw`` (azimuth) and ``_cam_pitch`` (elevation).

        Returns
        -------
        list[float]
            16-element column-major 4×4 matrix compatible with
            ``MeshRenderer.update_camera(view=...)``.
        """
        yaw   = math.radians(self._cam_yaw)
        pitch = math.radians(self._cam_pitch)

        # Spherical → Cartesian offset from target
        cx = self._cam_distance * math.cos(pitch) * math.sin(yaw)
        cy = self._cam_distance * math.sin(pitch)
        cz = self._cam_distance * math.cos(pitch) * math.cos(yaw)

        eye = [
            self._cam_target[0] + cx,
            self._cam_target[1] + cy,
            self._cam_target[2] + cz,
        ]
        return _look_at(eye, self._cam_target, [0.0, 1.0, 0.0])

    def get_proj_matrix(self, aspect: float) -> list[float]:
        """Return 16 floats (column-major mat4) for perspective projection.

        Uses a reversed-Z convention (near=0.1, far=1000) and a
        right-handed coordinate system matching wgpu's NDC.

        Parameters
        ----------
        aspect:
            Viewport width / height ratio.

        Returns
        -------
        list[float]
            16-element column-major 4×4 perspective matrix compatible with
            ``MeshRenderer.update_camera(proj=...)``.
        """
        fov  = math.radians(self._cam_fov)
        near = 0.1
        far  = 1000.0
        f    = 1.0 / math.tan(fov / 2.0)

        # Column-major perspective matrix (right-handed, maps Z to [-1, 1])
        return [
            f / aspect, 0.0,  0.0,                          0.0,   # col 0
            0.0,        f,    0.0,                          0.0,   # col 1
            0.0,        0.0,  (far + near) / (near - far), -1.0,  # col 2
            0.0,        0.0,  (2.0 * far * near) / (near - far), 0.0,  # col 3
        ]

    # ------------------------------------------------------------------
    # 3D mouse input (called from update() when mode == "3D")
    # ------------------------------------------------------------------

    def _handle_3d_mouse(self) -> None:
        """Process one frame of 3D orbit/pan/zoom mouse input via DPG.

        Left-drag  → orbit  (yaw + pitch).
        Right-drag → pan    (translate cam_target in view right/up plane).
        Scroll     → zoom   (change cam_distance).

        All three operations are independent and can overlap.
        """
        import dearpygui.dearpygui as dpg

        mouse: tuple[float, float] = dpg.get_mouse_pos(local=False)
        mx, my = mouse[0], mouse[1]

        # ---- Orbit (left drag) -------------------------------------------
        left_down = dpg.is_mouse_button_down(self._BTN_LEFT)

        if left_down:
            if self._dragging_left:
                dx = mx - self._prev_mouse[0]
                dy = my - self._prev_mouse[1]
                # Sensitivity: 0.4 degrees per screen pixel
                sensitivity = 0.4
                self._cam_yaw   += dx * sensitivity
                self._cam_pitch -= dy * sensitivity  # drag up → pitch increases
                # Clamp pitch to avoid gimbal lock at the poles
                self._cam_pitch = max(-89.0, min(89.0, self._cam_pitch))
            else:
                self._dragging_left = True
        else:
            self._dragging_left = False

        # ---- Pan (right or middle drag) ----------------------------------
        right_down = dpg.is_mouse_button_down(self._BTN_RIGHT) or \
                     dpg.is_mouse_button_down(self._BTN_MIDDLE)

        if right_down:
            if self._dragging_right:
                dx = mx - self._prev_mouse[0]
                dy = my - self._prev_mouse[1]
                self._pan_camera(dx, dy)
            else:
                self._dragging_right = True
        else:
            self._dragging_right = False

        # ---- Zoom (scroll wheel) ----------------------------------------
        scroll_y: float = dpg.get_mouse_wheel()
        if scroll_y != 0.0:
            # Scroll up → zoom in (decrease distance); scroll down → zoom out
            zoom_speed = 0.1 * self._cam_distance
            self._cam_distance -= scroll_y * zoom_speed
            self._cam_distance = max(0.1, min(1000.0, self._cam_distance))

        # Store current mouse position for next frame's delta computation
        self._prev_mouse = (mx, my)

    def _pan_camera(self, screen_dx: float, screen_dy: float) -> None:
        """Translate ``_cam_target`` in the camera's right/up plane.

        Converts a screen-space pixel delta into a world-space translation
        along the camera's right axis (for horizontal drag) and the camera's
        true-up axis (for vertical drag), then offsets the look-at target so
        the whole orbit sphere shifts without changing the viewing angle.

        Parameters
        ----------
        screen_dx:
            Horizontal mouse delta in screen pixels (positive = right).
        screen_dy:
            Vertical mouse delta in screen pixels (positive = down).
        """
        yaw   = math.radians(self._cam_yaw)
        pitch = math.radians(self._cam_pitch)

        # Camera forward (from target toward eye — opposite look direction)
        fx = math.cos(pitch) * math.sin(yaw)
        fy = math.sin(pitch)
        fz = math.cos(pitch) * math.cos(yaw)

        # World up
        up = [0.0, 1.0, 0.0]

        # Right = forward × up (normalised)
        rx = fy * up[2] - fz * up[1]
        ry = fz * up[0] - fx * up[2]
        rz = fx * up[1] - fy * up[0]
        inv_r = 1.0 / math.sqrt(rx * rx + ry * ry + rz * rz)
        rx, ry, rz = rx * inv_r, ry * inv_r, rz * inv_r

        # True camera up = right × forward (normalised)
        ux = ry * fz - rz * fy
        uy = rz * fx - rx * fz
        uz = rx * fy - ry * fx
        inv_u = 1.0 / math.sqrt(ux * ux + uy * uy + uz * uz)
        ux, uy, uz = ux * inv_u, uy * inv_u, uz * inv_u

        # Pan speed proportional to distance so far-away scenes feel natural
        pan_speed = self._cam_distance * 0.001

        # Positive screen_dx → move right → target moves in +right direction
        # Positive screen_dy → move down  → target moves in -up direction
        self._cam_target[0] -= rx * screen_dx * pan_speed
        self._cam_target[1] -= ry * screen_dx * pan_speed
        self._cam_target[2] -= rz * screen_dx * pan_speed

        self._cam_target[0] += ux * screen_dy * pan_speed
        self._cam_target[1] += uy * screen_dy * pan_speed
        self._cam_target[2] += uz * screen_dy * pan_speed
