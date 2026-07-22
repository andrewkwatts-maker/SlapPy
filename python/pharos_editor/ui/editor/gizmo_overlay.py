"""Legacy Nova3D reference. The shipping editor uses notebook_* siblings — see docs/ui_pattern_audit_2026_06_03.md."""
from __future__ import annotations

import math
from typing import Any


class GizmoOverlay:
    """2D transform gizmo drawn on a DPG viewport drawlist over the wgpu viewport image.

    Tool modes
    ----------
    "select"    — dashed bounding-box highlight around the selected entity
    "translate" — red X arrow + green Y arrow from entity centre + centre circle
    "rotate"    — orbit circle with a draggable handle dot; arc sweep while dragging
    "scale"     — four corner squares + centre square

    Usage::

        overlay = GizmoOverlay()
        overlay.build()               # call once after dpg.create_context()
        # per-frame in the render loop:
        overlay.set_entity(entity)
        overlay.set_camera(camera)
        overlay.set_tool(toolbar.active_tool)
        overlay.update()
    """

    # ------------------------------------------------------------------ constants
    HANDLE_RADIUS: int = 8
    ARROW_LEN: int = 50
    ROTATE_RADIUS: int = 45
    SCALE_HANDLE_SIZE: int = 10

    COLOR_X = (255, 80, 80, 220)
    COLOR_Y = (80, 220, 80, 220)
    COLOR_CENTER = (220, 220, 80, 220)
    COLOR_HOVER = (255, 255, 255, 255)
    COLOR_BBOX = (102, 153, 255, 120)
    COLOR_BBOX_LINE = (102, 153, 255, 200)
    COLOR_ROTATE_RING = (180, 140, 255, 200)
    COLOR_ARC = (255, 200, 60, 200)

    # 3D gizmo arrow lengths and ring radii (screen pixels)
    ARROW_3D_LEN: int = 40
    RING_3D_RX: int = 36     # X-ring (horizontal ellipse) x-radius
    RING_3D_RY: int = 10     # X-ring (horizontal ellipse) y-radius
    RING_3D_VRX: int = 10    # Y-ring (vertical ellipse) x-radius
    RING_3D_VRY: int = 36    # Y-ring (vertical ellipse) y-radius
    RING_3D_CR: int = 36     # Z-ring (circle) radius

    COLOR_Z = (80, 140, 255, 220)   # blue for Z axis

    def __init__(self) -> None:
        self._entity: Any = None
        self._camera: Any = None
        self._tool: str = "select"
        self._vp_w: int = 1280
        self._vp_h: int = 720
        self._dragging: str | None = None
        self._drag_start_mouse: tuple[float, float] = (0.0, 0.0)
        self._drag_start_entity_pos: tuple[float, float] = (0.0, 0.0)
        self._drag_start_entity_rot: float = 0.0
        self._drag_start_entity_scale: tuple[float, float] = (1.0, 1.0)
        self._dl_tag: str = "gizmo_drawlist"
        # Mouse position tracked every frame for hover effects
        self._mouse: tuple[float, float] = (0.0, 0.0)
        # 3D mode flag (WP-5.8)
        self._mode_3d: bool = False

    # ------------------------------------------------------------------ public API

    def set_entity(self, entity: Any) -> None:
        """Bind the gizmo to *entity*.  Pass ``None`` to deselect."""
        self._entity = entity

    def set_camera(self, camera: Any) -> None:
        """Bind the camera used for world-to-screen conversion."""
        self._camera = camera

    def set_tool(self, tool: str) -> None:
        """Set the active tool mode: 'select', 'translate', 'rotate', or 'scale'."""
        if tool != self._tool:
            self._dragging = None
        self._tool = tool

    def set_mode(self, mode: str) -> None:
        """Switch between 2D and 3D gizmo rendering.

        Parameters
        ----------
        mode:
            ``"3D"`` — draw 3-axis arrows (X/Y/Z) and axis-aligned rings.
            Any other value (e.g. ``"2D"``) — restore standard 2D gizmo.
        """
        self._mode_3d = (mode == "3D")

    def set_viewport_size(self, w: int, h: int) -> None:
        """Update the known viewport image dimensions (pixels)."""
        self._vp_w = w
        self._vp_h = h

    def build(self) -> None:
        """Create the front viewport drawlist.  Call once after ``dpg.create_context()``."""
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._dl_tag):
            dpg.add_viewport_drawlist(front=True, tag=self._dl_tag)

    def update(self) -> None:
        """Redraw all gizmo handles and process mouse interaction.

        Call every frame inside the render loop *before* ``dpg.render_dearpygui_frame()``.
        """
        import dearpygui.dearpygui as dpg

        if not dpg.does_item_exist(self._dl_tag):
            return

        dpg.delete_item(self._dl_tag, children_only=True)

        if self._entity is None:
            return

        # Resolve entity screen position
        pos = getattr(self._entity, "position", (0.0, 0.0))
        if not (isinstance(pos, (list, tuple)) and len(pos) >= 2):
            return

        sx, sy = self.world_to_screen(float(pos[0]), float(pos[1]))

        # Update cached mouse position
        self._mouse = dpg.get_mouse_pos(local=False)

        # Mouse interaction first so drag deltas are applied before drawing
        self._handle_mouse(sx, sy)

        # Re-resolve position in case a drag just moved the entity
        pos = getattr(self._entity, "position", (0.0, 0.0))
        sx, sy = self.world_to_screen(float(pos[0]), float(pos[1]))

        if self._mode_3d:
            self._draw_3d_gizmo(sx, sy)
        elif self._tool == "select":
            self._draw_bbox(sx, sy)
        elif self._tool == "translate":
            self._draw_translate(sx, sy)
        elif self._tool == "rotate":
            self._draw_rotate(sx, sy)
        elif self._tool == "scale":
            self._draw_scale(sx, sy)

    # ------------------------------------------------------------------ coordinate helpers

    def world_to_screen(self, wx: float, wy: float) -> tuple[float, float]:
        """Convert 2-D world coordinates to OS-window pixel coordinates.

        Falls back to viewport-centre origin with scale=1 when no camera is set.
        """
        import dearpygui.dearpygui as dpg

        origin_x = self._vp_w / 2.0
        origin_y = self._vp_h / 2.0
        scale = 1.0

        img_offset_x = 0.0
        img_offset_y = 0.0

        if dpg.does_item_exist("viewport_image"):
            try:
                rect_min = dpg.get_item_rect_min("viewport_image")
                img_offset_x = rect_min[0]
                img_offset_y = rect_min[1]
            except Exception:
                pass

        cam = self._camera
        cam_x = 0.0
        cam_y = 0.0
        if cam is not None:
            cam_pos = getattr(cam, "position", (0.0, 0.0))
            if isinstance(cam_pos, (list, tuple)) and len(cam_pos) >= 2:
                cam_x = float(cam_pos[0])
                cam_y = float(cam_pos[1])
            scale = float(getattr(cam, "zoom", 1.0))
            if scale == 0.0:
                scale = 1.0

        sx = img_offset_x + origin_x + (wx - cam_x) * scale
        sy = img_offset_y + origin_y + (wy - cam_y) * scale
        return (sx, sy)

    def screen_delta_to_world(self, sdx: float, sdy: float) -> tuple[float, float]:
        """Convert a screen-space pixel delta to a world-space delta."""
        scale = 1.0
        if self._camera is not None:
            scale = float(getattr(self._camera, "zoom", 1.0))
            if scale == 0.0:
                scale = 1.0
        return (sdx / scale, sdy / scale)

    # ------------------------------------------------------------------ hit testing

    def _dist(self, ax: float, ay: float, bx: float, by: float) -> float:
        return math.hypot(ax - bx, ay - by)

    def _hit_circle(self, mx: float, my: float, cx: float, cy: float, r: float) -> bool:
        return self._dist(mx, my, cx, cy) <= r

    def _hit_rect(
        self,
        mx: float,
        my: float,
        cx: float,
        cy: float,
        half: float,
    ) -> bool:
        return abs(mx - cx) <= half and abs(my - cy) <= half

    # ------------------------------------------------------------------ translate handle positions

    def _translate_handles(self, sx: float, sy: float) -> dict[str, tuple[float, float]]:
        """Return centre positions of each translate handle in screen space."""
        return {
            "x": (sx + self.ARROW_LEN, sy),
            "y": (sx, sy - self.ARROW_LEN),  # screen Y is inverted vs world Y
            "xy": (sx, sy),
        }

    # ------------------------------------------------------------------ scale handle positions

    def _scale_corner_handles(self, sx: float, sy: float) -> dict[str, tuple[float, float]]:
        h = self.SCALE_HANDLE_SIZE * 1.5  # offset from centre to corner
        return {
            "scale_tl": (sx - h, sy - h),
            "scale_tr": (sx + h, sy - h),
            "scale_bl": (sx - h, sy + h),
            "scale_br": (sx + h, sy + h),
            "scale_c": (sx, sy),
        }

    # ------------------------------------------------------------------ mouse interaction

    def _handle_mouse(self, sx: float, sy: float) -> None:
        import dearpygui.dearpygui as dpg

        mouse = self._mouse
        mx, my = mouse[0], mouse[1]

        pressed = dpg.is_mouse_button_down(0)
        just_pressed = dpg.is_mouse_button_clicked(0)
        just_released = dpg.is_mouse_button_released(0)

        if just_released:
            self._dragging = None
            return

        if just_pressed and not self._dragging:
            self._dragging = self._hit_test(mx, my, sx, sy)
            if self._dragging:
                self._drag_start_mouse = (mx, my)
                raw_pos = getattr(self._entity, "position", (0.0, 0.0))
                self._drag_start_entity_pos = (float(raw_pos[0]), float(raw_pos[1]))
                self._drag_start_entity_rot = float(
                    getattr(self._entity, "rotation", 0.0)
                )
                raw_scale = getattr(self._entity, "scale", (1.0, 1.0))
                if isinstance(raw_scale, (int, float)):
                    raw_scale = (float(raw_scale), float(raw_scale))
                self._drag_start_entity_scale = (float(raw_scale[0]), float(raw_scale[1]))

        if self._dragging and pressed and self._entity is not None:
            dx = mx - self._drag_start_mouse[0]
            dy = my - self._drag_start_mouse[1]
            self._apply_drag(dx, dy, sx, sy)

    def _hit_test(self, mx: float, my: float, sx: float, sy: float) -> str | None:
        """Return the drag handle key that the mouse is over, or None."""
        r = float(self.HANDLE_RADIUS)
        half = self.SCALE_HANDLE_SIZE / 2.0

        if self._tool == "translate":
            handles = self._translate_handles(sx, sy)
            # Test arrow-tip circles; prefer x/y over centre
            for key in ("x", "y", "xy"):
                hx, hy = handles[key]
                if self._hit_circle(mx, my, hx, hy, r):
                    return key

        elif self._tool == "rotate":
            # Draggable dot at top of rotate ring
            dot_x = sx
            dot_y = sy - self.ROTATE_RADIUS
            if self._hit_circle(mx, my, dot_x, dot_y, r):
                return "rotate"

        elif self._tool == "scale":
            corners = self._scale_corner_handles(sx, sy)
            for key, (hx, hy) in corners.items():
                if self._hit_rect(mx, my, hx, hy, half + 4):
                    return key

        return None

    def _apply_drag(
        self, dx: float, dy: float, sx: float, sy: float
    ) -> None:
        """Apply the current drag delta to the entity."""
        entity = self._entity
        if entity is None:
            return

        if self._tool == "translate":
            if self._dragging == "x":
                wdx, _ = self.screen_delta_to_world(dx, 0.0)
                wdy = 0.0
            elif self._dragging == "y":
                wdx = 0.0
                _, wdy = self.screen_delta_to_world(0.0, dy)
                wdy = -wdy  # screen Y is inverted; drag up → positive world Y
            elif self._dragging == "xy":
                wdx, wdy_raw = self.screen_delta_to_world(dx, dy)
                wdy = -wdy_raw
            else:
                return

            new_pos = (
                self._drag_start_entity_pos[0] + wdx,
                self._drag_start_entity_pos[1] + wdy,
            )
            old = list(getattr(entity, "position", [0.0, 0.0]))
            old[0] = new_pos[0]
            old[1] = new_pos[1]
            entity.position = tuple(old)

        elif self._tool == "rotate":
            # Compute angle from entity screen centre to mouse
            cur_angle = math.atan2(
                self._drag_start_mouse[1] - sy,
                self._drag_start_mouse[0] - sx,
            )
            new_angle = math.atan2(
                self._drag_start_mouse[1] + dy - sy,
                self._drag_start_mouse[0] + dx - sx,
            )
            delta_deg = math.degrees(new_angle - cur_angle)
            try:
                entity.rotation = self._drag_start_entity_rot + delta_deg
            except (AttributeError, TypeError):
                pass

        elif self._tool == "scale" and self._dragging and self._dragging.startswith("scale_"):
            # Uniform scale from drag distance
            dist_start = math.hypot(
                self._drag_start_mouse[0] - sx,
                self._drag_start_mouse[1] - sy,
            )
            dist_now = math.hypot(
                self._drag_start_mouse[0] + dx - sx,
                self._drag_start_mouse[1] + dy - sy,
            )
            if dist_start > 1.0:
                ratio = dist_now / dist_start
                sx0, sy0 = self._drag_start_entity_scale
                new_scale = (sx0 * ratio, sy0 * ratio)
                try:
                    raw = getattr(entity, "scale", None)
                    if isinstance(raw, (int, float)):
                        entity.scale = new_scale[0]
                    else:
                        entity.scale = new_scale
                except (AttributeError, TypeError):
                    pass

    # ------------------------------------------------------------------ drawing helpers

    def _draw_bbox(self, sx: float, sy: float) -> None:
        """Draw a semi-transparent bounding box around the entity."""
        import dearpygui.dearpygui as dpg

        size = getattr(self._entity, "size", None)
        if size is None:
            size = getattr(self._entity, "bounds", None)

        if isinstance(size, (list, tuple)) and len(size) >= 2:
            hw = float(size[0]) / 2.0
            hh = float(size[1]) / 2.0
        else:
            # Default 32×32 px bounding box in screen space when size unknown
            hw = hh = 16.0

        # Scale half-extents by camera zoom
        scale = 1.0
        if self._camera is not None:
            scale = float(getattr(self._camera, "zoom", 1.0)) or 1.0
        hw_s = hw * scale
        hh_s = hh * scale

        x0, y0 = sx - hw_s, sy - hh_s
        x1, y1 = sx + hw_s, sy + hh_s

        dpg.draw_rectangle(
            (x0, y0),
            (x1, y1),
            color=self.COLOR_BBOX_LINE,
            fill=self.COLOR_BBOX,
            thickness=1.5,
            parent=self._dl_tag,
        )

    def _draw_translate(self, sx: float, sy: float) -> None:
        """Draw X/Y translation arrows and a centre handle."""
        import dearpygui.dearpygui as dpg

        handles = self._translate_handles(sx, sy)
        tip_x, tip_y = handles["x"]
        tip_yx, tip_yy = handles["y"]
        mx, my = self._mouse

        # X arrow (red, points right)
        x_hovered = self._hit_circle(mx, my, tip_x, tip_y, self.HANDLE_RADIUS)
        x_col = self.COLOR_HOVER if (x_hovered or self._dragging == "x") else self.COLOR_X
        dpg.draw_arrow(
            (tip_x, tip_y),
            (sx, sy),
            color=x_col,
            thickness=2,
            size=8,
            parent=self._dl_tag,
        )

        # Y arrow (green, points up in screen = negative screen Y)
        y_hovered = self._hit_circle(mx, my, tip_yx, tip_yy, self.HANDLE_RADIUS)
        y_col = self.COLOR_HOVER if (y_hovered or self._dragging == "y") else self.COLOR_Y
        dpg.draw_arrow(
            (tip_yx, tip_yy),
            (sx, sy),
            color=y_col,
            thickness=2,
            size=8,
            parent=self._dl_tag,
        )

        # Centre circle (yellow, free move)
        c_hovered = self._hit_circle(mx, my, sx, sy, self.HANDLE_RADIUS)
        c_col = self.COLOR_HOVER if (c_hovered or self._dragging == "xy") else self.COLOR_CENTER
        dpg.draw_circle(
            (sx, sy),
            self.HANDLE_RADIUS,
            color=c_col,
            fill=c_col,
            parent=self._dl_tag,
        )

    def _draw_rotate(self, sx: float, sy: float) -> None:
        """Draw a rotation ring with a draggable handle dot."""
        import dearpygui.dearpygui as dpg

        r = float(self.ROTATE_RADIUS)
        dot_x = sx
        dot_y = sy - r
        mx, my = self._mouse

        # Ring
        dpg.draw_circle(
            (sx, sy),
            r,
            color=self.COLOR_ROTATE_RING,
            thickness=2,
            parent=self._dl_tag,
        )

        # Arc sweep indicator while dragging
        if self._dragging == "rotate" and self._entity is not None:
            start_rot = self._drag_start_entity_rot
            cur_rot = float(getattr(self._entity, "rotation", start_rot))
            delta = cur_rot - start_rot
            if abs(delta) > 0.5:
                # Draw arc from 270° (top) spanning delta degrees
                # DPG draw_arc uses degrees, angles measured from 3 o'clock CW
                arc_start = -90.0
                arc_end = arc_start + delta
                a0, a1 = (
                    (arc_start, arc_end)
                    if delta >= 0
                    else (arc_end, arc_start)
                )
                dpg.draw_arc(
                    (sx, sy),
                    r,
                    a0,
                    a1,
                    color=self.COLOR_ARC,
                    thickness=4,
                    parent=self._dl_tag,
                )

        # Handle dot
        dot_hovered = self._hit_circle(mx, my, dot_x, dot_y, self.HANDLE_RADIUS)
        dot_col = (
            self.COLOR_HOVER
            if (dot_hovered or self._dragging == "rotate")
            else self.COLOR_ROTATE_RING
        )
        dpg.draw_circle(
            (dot_x, dot_y),
            self.HANDLE_RADIUS,
            color=dot_col,
            fill=dot_col,
            parent=self._dl_tag,
        )

    def _draw_scale(self, sx: float, sy: float) -> None:
        """Draw four corner squares and a centre square for scaling."""
        import dearpygui.dearpygui as dpg

        h = self.SCALE_HANDLE_SIZE / 2.0
        corners = self._scale_corner_handles(sx, sy)
        mx, my = self._mouse

        # Cross-lines from centre to corners
        for key in ("scale_tl", "scale_tr", "scale_bl", "scale_br"):
            hx, hy = corners[key]
            dpg.draw_line(
                (sx, sy),
                (hx, hy),
                color=(180, 180, 180, 160),
                thickness=1,
                parent=self._dl_tag,
            )

        for key, (hx, hy) in corners.items():
            hovered = self._hit_rect(mx, my, hx, hy, h + 4)
            active = self._dragging == key

            if key == "scale_c":
                col = self.COLOR_HOVER if (hovered or active) else self.COLOR_CENTER
            else:
                col = self.COLOR_HOVER if (hovered or active) else self.COLOR_X

            dpg.draw_rectangle(
                (hx - h, hy - h),
                (hx + h, hy + h),
                color=col,
                fill=col,
                parent=self._dl_tag,
            )

    # ------------------------------------------------------------------ 3D gizmo (WP-5.8)

    def _draw_3d_arrowhead(
        self,
        canvas_tag: str,
        from_pt: tuple[float, float],
        to_pt: tuple[float, float],
        color: tuple[int, int, int, int],
    ) -> None:
        """Draw a small filled triangle arrowhead at *to_pt* pointing away from *from_pt*.

        Parameters
        ----------
        canvas_tag:
            DPG parent drawlist tag.
        from_pt:
            Arrow shaft start in screen pixels.
        to_pt:
            Arrow tip in screen pixels — the apex of the triangle.
        color:
            RGBA tuple.
        """
        import dearpygui.dearpygui as dpg

        dx = to_pt[0] - from_pt[0]
        dy = to_pt[1] - from_pt[1]
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return

        # Unit vector along shaft and its perpendicular
        ux, uy = dx / length, dy / length
        px, py = -uy, ux

        head_len = 9.0
        head_half = 4.5

        # Base centre of the triangle (step back from tip)
        bx = to_pt[0] - ux * head_len
        by = to_pt[1] - uy * head_len

        p1 = (to_pt[0], to_pt[1])                           # apex
        p2 = (bx + px * head_half, by + py * head_half)    # base left
        p3 = (bx - px * head_half, by - py * head_half)    # base right

        dpg.draw_triangle(
            p1, p2, p3,
            color=color,
            fill=color,
            parent=canvas_tag,
        )

    def _draw_3d_gizmo(self, sx: float, sy: float) -> None:
        """Draw 3D axis arrows and axis-aligned rotation rings.

        Arrows (screen-space offsets from entity centre):
          X — right  (+40 px, 0)         red
          Y — up     (0, -40 px)         green
          Z — iso    (-20 px, -20 px)    blue

        Rings:
          X — horizontal ellipse (rx=36, ry=10)
          Y — vertical ellipse   (rx=10, ry=36)
          Z — circle             (r=36)
        """
        import dearpygui.dearpygui as dpg

        L = float(self.ARROW_3D_LEN)
        tag = self._dl_tag

        # Arrow shaft endpoints (to_pt is the tip)
        x_tip = (sx + L,        sy)
        y_tip = (sx,             sy - L)
        z_tip = (sx - L * 0.5,  sy - L * 0.5)
        center = (sx, sy)

        # --- X arrow (red) ---
        dpg.draw_line(
            center, x_tip,
            color=self.COLOR_X,
            thickness=2,
            parent=tag,
        )
        self._draw_3d_arrowhead(tag, center, x_tip, self.COLOR_X)

        # --- Y arrow (green) ---
        dpg.draw_line(
            center, y_tip,
            color=self.COLOR_Y,
            thickness=2,
            parent=tag,
        )
        self._draw_3d_arrowhead(tag, center, y_tip, self.COLOR_Y)

        # --- Z arrow (blue, isometric offset into screen) ---
        dpg.draw_line(
            center, z_tip,
            color=self.COLOR_Z,
            thickness=2,
            parent=tag,
        )
        self._draw_3d_arrowhead(tag, center, z_tip, self.COLOR_Z)

        # --- Centre dot ---
        dpg.draw_circle(
            center,
            5,
            color=self.COLOR_CENTER,
            fill=self.COLOR_CENTER,
            parent=tag,
        )

        # --- Rotation rings ---
        ring_thickness = 1.5
        ring_alpha = 160

        # X-ring: horizontal ellipse (represents rotation around X axis)
        x_ring_color = (self.COLOR_X[0], self.COLOR_X[1], self.COLOR_X[2], ring_alpha)
        dpg.draw_ellipse(
            (sx - self.RING_3D_RX, sy - self.RING_3D_RY),
            (sx + self.RING_3D_RX, sy + self.RING_3D_RY),
            color=x_ring_color,
            thickness=ring_thickness,
            parent=tag,
        )

        # Y-ring: vertical ellipse (represents rotation around Y axis)
        y_ring_color = (self.COLOR_Y[0], self.COLOR_Y[1], self.COLOR_Y[2], ring_alpha)
        dpg.draw_ellipse(
            (sx - self.RING_3D_VRX, sy - self.RING_3D_VRY),
            (sx + self.RING_3D_VRX, sy + self.RING_3D_VRY),
            color=y_ring_color,
            thickness=ring_thickness,
            parent=tag,
        )

        # Z-ring: circle (represents rotation around Z axis / screen plane)
        z_ring_color = (self.COLOR_Z[0], self.COLOR_Z[1], self.COLOR_Z[2], ring_alpha)
        dpg.draw_circle(
            center,
            float(self.RING_3D_CR),
            color=z_ring_color,
            thickness=ring_thickness,
            parent=tag,
        )
