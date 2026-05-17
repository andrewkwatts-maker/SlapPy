from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class IsoEntity:
    """An entity positioned in the isometric grid.

    ``IsoEntity`` is a lightweight data-only object that holds the grid-space
    position of any game entity (character, item, decoration …).  It is
    intentionally independent of the engine's GPU entity system so that the
    iso subsystem can be used without a live wgpu context.

    Z-height integration
    ~~~~~~~~~~~~~~~~~~~~
    The engine's Z-height lighting system reads a per-pixel Z value from a
    texture.  For ISO entities, the value to write into the Z-height texture
    is::

        z_pixels = entity.total_z * grid.z_scale

    Pass this as ``z_layer`` (or the equivalent parameter) when creating a
    ``ZHeightModule`` for the entity.

    Fluid sim integration
    ~~~~~~~~~~~~~~~~~~~~~
    Set ``receives_fluid_forces = True`` to allow the fluid simulation to
    apply velocity impulses to this entity each tick.

    Attributes:
        grid_x: X position in the isometric grid (float for sub-tile motion).
        grid_y: Y position in the isometric grid.
        grid_z: Z height level in the isometric grid (0 = ground floor).
        local_z: Fine-grained Z offset *within* the grid cell, added to
            ``grid_z`` when computing ``total_z`` for lighting/shading.
        facing_angle: The entity's intrinsic facing direction in degrees
            (0 = north, 90 = east).  Independent of the camera viewpoint.
        receives_fluid_forces: Whether the fluid simulation should push this
            entity.
    """

    grid_x: float = 0.0
    grid_y: float = 0.0
    grid_z: float = 0.0
    local_z: float = 0.0
    facing_angle: float = 0.0
    receives_fluid_forces: bool = False

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    @property
    def total_z(self) -> float:
        """Combined Z position used by the lighting/shading system.

        Equals ``grid_z + local_z``.  Multiply by ``IsoGrid.z_scale`` to
        convert to pixel height for the Z-height texture.
        """
        return self.grid_z + self.local_z

    @property
    def _facing_angle(self) -> float:
        """Alias used by :meth:`IsoCamera.update_entity_viewpoints`.

        ``IsoCamera`` reads ``_facing_angle`` to combine the entity's
        intrinsic direction with the camera viewpoint angle.
        """
        return self.facing_angle

    # ------------------------------------------------------------------
    # Movement helpers
    # ------------------------------------------------------------------

    def move_to(self, gx: float, gy: float, gz: float = 0.0) -> None:
        """Teleport the entity to grid position (gx, gy, gz)."""
        self.grid_x = gx
        self.grid_y = gy
        self.grid_z = gz

    def move_by(self, dgx: float, dgy: float, dgz: float = 0.0) -> None:
        """Displace the entity by (dgx, dgy, dgz) grid units."""
        self.grid_x += dgx
        self.grid_y += dgy
        self.grid_z += dgz

    def face_toward(self, target_gx: float, target_gy: float) -> None:
        """Set :attr:`facing_angle` toward a target grid position.

        Uses ``atan2`` in grid space.  The angle is measured clockwise from
        the positive-Y axis (north), consistent with screen-up = north.

        Args:
            target_gx: Target grid X coordinate.
            target_gy: Target grid Y coordinate.
        """
        dx = target_gx - self.grid_x
        dy = target_gy - self.grid_y
        self.facing_angle = math.degrees(math.atan2(dy, dx)) % 360

    def distance_to(self, other: "IsoEntity") -> float:
        """Return the Euclidean grid distance to *other* (ignoring Z)."""
        dx = other.grid_x - self.grid_x
        dy = other.grid_y - self.grid_y
        return math.hypot(dx, dy)
