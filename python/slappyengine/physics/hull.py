"""Hierarchical-hull tree (structure-of-arrays).

Three tiers:
- T0 = transform-only (just rigid pose, no solver).
- T1 = reduced solver (analytic / coarse).
- T2 = full per-pixel solver; owns one ``CellGridPool`` slot.

Backing is SoA numpy arrays for cache-friendly iteration and trivial GPU
upload.  No double-buffering yet (that's Sprint 2); a single ``dirty`` flag
lets external code know when buffers need re-upload.

Children are stored in a flat ``_children`` array with per-hull
``(child_offset, child_count)`` indices.  Slot reuse is handled by a free
list.
"""
from __future__ import annotations

import numpy as np

# --- Tunables (no magic numbers in method bodies) ---------------------------

INITIAL_HULL_CAPACITY = 256
INITIAL_CHILD_CAPACITY = 512
GROWTH_FACTOR = 2  # both hull and children arrays double when full.

# Tier encoding.
TIER_T0: int = 0  # transform-only.
TIER_T1: int = 1  # reduced solver.
TIER_T2: int = 2  # full per-pixel.

# Sentinels.
NO_PARENT: int = -1
NO_CELL_GRID: int = -1

# AABB padding around the bounding circle (world units).  Keeps the AABB a
# touch loose so a single integration step can't pop a hull out of it.
AABB_PADDING = 0.0


class HullTree:
    """SoA hierarchical-hull container.

    Public layout (all parallel arrays of length ``capacity``):
      - ``id`` is implicit — it's the row index.
      - ``parent_id`` int32 (``NO_PARENT`` for roots).
      - ``depth`` uint8.
      - ``root_id`` int32 (self for roots).
      - ``position`` float32 (capacity, 2).
      - ``angle`` float32.
      - ``stretch`` float32 (capacity, 2).
      - ``shear`` float32.
      - ``velocity`` float32 (capacity, 2).
      - ``omega`` float32.
      - ``centre_local`` float32 (capacity, 2).
      - ``radius`` float32.
      - ``mass`` float32.
      - ``inertia`` float32.
      - ``aabb`` float32 (capacity, 4)  (x0, y0, x1, y1).
      - ``tier`` uint8.
      - ``disagreement`` float32.
      - ``hysteresis`` uint8.
      - ``material_id`` uint16.
      - ``cell_grid_id`` int32 (``NO_CELL_GRID`` for T0/T1).
      - ``fixed`` bool.
      - children: ``child_offset`` int32, ``child_count`` int32 into the flat
        ``_children`` int32 array.

    The ``_alive`` bool array marks rows that are currently in use; freed
    rows are kept on ``_free_hulls`` for reuse.
    """

    def __init__(
        self,
        capacity: int = INITIAL_HULL_CAPACITY,
        child_capacity: int = INITIAL_CHILD_CAPACITY,
    ) -> None:
        """Create an empty tree with the given starting capacities."""
        self._capacity: int = capacity
        self._child_capacity: int = child_capacity
        self._count: int = 0  # number of live hulls.
        self._dirty: bool = False

        # --- Per-hull SoA arrays --------------------------------------------
        self.parent_id: np.ndarray = np.full(capacity, NO_PARENT, dtype=np.int32)
        self.depth: np.ndarray = np.zeros(capacity, dtype=np.uint8)
        self.root_id: np.ndarray = np.zeros(capacity, dtype=np.int32)
        self.position: np.ndarray = np.zeros((capacity, 2), dtype=np.float32)
        self.angle: np.ndarray = np.zeros(capacity, dtype=np.float32)
        self.stretch: np.ndarray = np.ones((capacity, 2), dtype=np.float32)
        self.shear: np.ndarray = np.zeros(capacity, dtype=np.float32)
        self.velocity: np.ndarray = np.zeros((capacity, 2), dtype=np.float32)
        self.omega: np.ndarray = np.zeros(capacity, dtype=np.float32)
        self.centre_local: np.ndarray = np.zeros((capacity, 2), dtype=np.float32)
        # World units per cell, per axis. The cell grid is always 32×32 in
        # body-local frame; cell_size_xy controls how big that footprint is
        # in world space. AABB and bounding radius are derived from these.
        self.cell_size_x: np.ndarray = np.ones(capacity, dtype=np.float32)
        self.cell_size_y: np.ndarray = np.ones(capacity, dtype=np.float32)
        self.radius: np.ndarray = np.zeros(capacity, dtype=np.float32)
        self.mass: np.ndarray = np.zeros(capacity, dtype=np.float32)
        self.inertia: np.ndarray = np.zeros(capacity, dtype=np.float32)
        self.aabb: np.ndarray = np.zeros((capacity, 4), dtype=np.float32)
        self.tier: np.ndarray = np.zeros(capacity, dtype=np.uint8)
        self.disagreement: np.ndarray = np.zeros(capacity, dtype=np.float32)
        self.hysteresis: np.ndarray = np.zeros(capacity, dtype=np.uint8)
        self.material_id: np.ndarray = np.zeros(capacity, dtype=np.uint16)
        self.cell_grid_id: np.ndarray = np.full(capacity, NO_CELL_GRID, dtype=np.int32)
        self.fixed: np.ndarray = np.zeros(capacity, dtype=bool)
        self.child_offset: np.ndarray = np.zeros(capacity, dtype=np.int32)
        self.child_count: np.ndarray = np.zeros(capacity, dtype=np.int32)
        # Phase A activation map: hot/warm/quiescent gating for substep skip.
        # ``activation_level``: 0=quiescent (skip substep), 1=warm (decayed),
        # 2=hot (recently contacted). ``active_until_frame``: frame index after
        # which this hull falls quiescent; -1 = never been active.
        self.activation_level: np.ndarray = np.zeros(capacity, dtype=np.uint8)
        self.active_until_frame: np.ndarray = np.full(capacity, -1, dtype=np.int32)
        self._alive: np.ndarray = np.zeros(capacity, dtype=bool)

        # Free list of hull slots (newest at end; pop from end for cache).
        self._free_hulls: list[int] = list(range(capacity - 1, -1, -1))

        # --- Flat children storage ------------------------------------------
        self._children: np.ndarray = np.full(child_capacity, NO_PARENT, dtype=np.int32)
        # Simple bump allocator for now.  Sprint 4 introduces a real allocator
        # when ``coalesce`` starts freeing ranges.
        self._children_used: int = 0

    # ------------------------------------------------------------------ props

    @property
    def capacity(self) -> int:
        """Current per-hull SoA capacity."""
        return self._capacity

    @property
    def count(self) -> int:
        """Number of live hulls."""
        return self._count

    @property
    def dirty(self) -> bool:
        """True if buffers have changed since the last ``clear_dirty``."""
        return self._dirty

    @property
    def children_buffer(self) -> np.ndarray:
        """Flat children array; index with ``child_offset`` + ``child_count``."""
        return self._children

    # --------------------------------------------------------- dirty tracking

    def mark_dirty(self) -> None:
        """Flag the buffers as needing re-upload to the GPU."""
        self._dirty = True

    def clear_dirty(self) -> None:
        """Reset the dirty flag after a successful upload."""
        self._dirty = False

    # ----------------------------------------------------------- growth helpers

    def _grow_hulls(self) -> None:
        """Double the per-hull SoA capacity."""
        old = self._capacity
        new = old * GROWTH_FACTOR

        def _resize(arr: np.ndarray, fill: float | int | bool = 0) -> np.ndarray:
            shape = (new,) + arr.shape[1:]
            out = np.full(shape, fill, dtype=arr.dtype) if fill != 0 else np.zeros(shape, dtype=arr.dtype)
            out[:old] = arr
            return out

        self.parent_id = _resize(self.parent_id, NO_PARENT)
        self.depth = _resize(self.depth)
        self.root_id = _resize(self.root_id)
        self.position = _resize(self.position)
        self.angle = _resize(self.angle)
        # ``stretch`` defaults to 1.0 — handle specially.
        new_stretch = np.ones((new, 2), dtype=np.float32)
        new_stretch[:old] = self.stretch
        self.stretch = new_stretch
        self.shear = _resize(self.shear)
        self.velocity = _resize(self.velocity)
        self.omega = _resize(self.omega)
        self.centre_local = _resize(self.centre_local)
        # cell_size defaults to 1.0 — handle specially.
        new_csx = np.ones(new, dtype=np.float32)
        new_csx[:old] = self.cell_size_x
        self.cell_size_x = new_csx
        new_csy = np.ones(new, dtype=np.float32)
        new_csy[:old] = self.cell_size_y
        self.cell_size_y = new_csy
        self.radius = _resize(self.radius)
        self.mass = _resize(self.mass)
        self.inertia = _resize(self.inertia)
        self.aabb = _resize(self.aabb)
        self.tier = _resize(self.tier)
        self.disagreement = _resize(self.disagreement)
        self.hysteresis = _resize(self.hysteresis)
        self.material_id = _resize(self.material_id)
        self.cell_grid_id = _resize(self.cell_grid_id, NO_CELL_GRID)
        self.fixed = _resize(self.fixed)
        self.child_offset = _resize(self.child_offset)
        self.child_count = _resize(self.child_count)
        # Phase A activation map columns: defaults 0 / -1.
        self.activation_level = _resize(self.activation_level)
        self.active_until_frame = _resize(self.active_until_frame, -1)
        self._alive = _resize(self._alive)

        # New slots go to the free list (newest highest indices last so pop()
        # hands them out next).
        self._free_hulls = list(range(new - 1, old - 1, -1)) + self._free_hulls
        self._capacity = new
        self._dirty = True

    # ------------------------------------------------------------ allocation

    def _allocate_slot(self) -> int:
        """Pop a slot off the free list, growing if needed."""
        if not self._free_hulls:
            self._grow_hulls()
        slot = self._free_hulls.pop()
        self._alive[slot] = True
        self._count += 1
        return slot

    # ------------------------------------------------------------------ AABB

    def _recompute_aabb(self, idx: int) -> None:
        """Recompute the AABB for hull ``idx`` from position + half-extents.

        Half-extents come from the cell grid footprint: ``GRID_SIZE/2 *
        cell_size``.  ``GRID_SIZE`` is fixed at 32 (see
        :mod:`slappyengine.physics.cell`).
        """
        from slappyengine.physics.cell import CELL_GRID_SIZE
        px = float(self.position[idx, 0])
        py = float(self.position[idx, 1])
        hx = 0.5 * CELL_GRID_SIZE * float(self.cell_size_x[idx]) + AABB_PADDING
        hy = 0.5 * CELL_GRID_SIZE * float(self.cell_size_y[idx]) + AABB_PADDING
        self.aabb[idx, 0] = px - hx
        self.aabb[idx, 1] = py - hy
        self.aabb[idx, 2] = px + hx
        self.aabb[idx, 3] = py + hy

    # ------------------------------------------------------------- public API

    def spawn_root(
        self,
        x: float,
        y: float,
        cell_size_x: float,
        cell_size_y: float,
        mass: float,
        inertia: float,
        material_id: int,
        tier: int = TIER_T0,
        fixed: bool = False,
    ) -> int:
        """Create a root hull at ``(x, y)`` and return its id.

        The body occupies a 32×32 cell grid in body-local frame.  Its
        world-space footprint is ``32 * (cell_size_x, cell_size_y)``;
        the bounding radius is the half-diagonal of that rectangle.
        ``mass`` and ``inertia`` should be integrated from the cell
        density field by the caller (single source of truth).
        """
        from slappyengine.physics.cell import CELL_GRID_SIZE
        idx = self._allocate_slot()
        self.parent_id[idx] = NO_PARENT
        self.depth[idx] = 0
        self.root_id[idx] = idx
        self.position[idx, 0] = x
        self.position[idx, 1] = y
        self.angle[idx] = 0.0
        self.stretch[idx, 0] = 1.0
        self.stretch[idx, 1] = 1.0
        self.shear[idx] = 0.0
        self.velocity[idx, 0] = 0.0
        self.velocity[idx, 1] = 0.0
        self.omega[idx] = 0.0
        self.centre_local[idx, 0] = 0.0
        self.centre_local[idx, 1] = 0.0
        self.cell_size_x[idx] = cell_size_x
        self.cell_size_y[idx] = cell_size_y
        # Bounding-circle radius = half-diagonal of the cell-grid footprint.
        hx = 0.5 * CELL_GRID_SIZE * cell_size_x
        hy = 0.5 * CELL_GRID_SIZE * cell_size_y
        self.radius[idx] = float(np.sqrt(hx * hx + hy * hy))
        self.mass[idx] = mass
        self.inertia[idx] = inertia
        self.tier[idx] = tier
        self.disagreement[idx] = 0.0
        self.hysteresis[idx] = 0
        self.material_id[idx] = material_id
        self.cell_grid_id[idx] = NO_CELL_GRID
        self.fixed[idx] = fixed
        self.child_offset[idx] = 0
        self.child_count[idx] = 0
        # Phase A: new hulls are quiescent until something marks them active.
        self.activation_level[idx] = 0
        self.active_until_frame[idx] = -1
        self._recompute_oriented_aabb(idx)
        self._dirty = True
        return idx

    def point_velocity(
        self, hull_id: int, world_point: tuple[float, float]
    ) -> tuple[float, float]:
        """World-space velocity at ``world_point`` on hull ``hull_id``.

        Rigid-body kinematics:  ``v_point = v + ω × r``  where
        ``r = world_point - position``.  In 2D, ``ω × r = (-ω*ry, ω*rx)``
        (positive ω = CCW).
        """
        rx = float(world_point[0]) - float(self.position[hull_id, 0])
        ry = float(world_point[1]) - float(self.position[hull_id, 1])
        om = float(self.omega[hull_id])
        vx = float(self.velocity[hull_id, 0]) - om * ry
        vy = float(self.velocity[hull_id, 1]) + om * rx
        return (vx, vy)

    def _recompute_oriented_aabb(self, hull_id: int) -> None:
        """Rotate-aware AABB for a hull whose angle != 0.

        The cell grid is 32×32 in body-local frame so the body's
        rectangular footprint has half-extents ``(Wx, Wy) = (16 *
        cell_size_x, 16 * cell_size_y)``.  Rotate the four corners
        ``(±Wx, ±Wy)`` by ``angle`` into world space, take the
        component-wise min/max, then pad by ``AABB_PADDING``.

        Cost is a handful of FLOPs per call — see ``integrate_transforms``
        for the vectorised batch version used during the per-step refresh.
        """
        from slappyengine.physics.cell import CELL_GRID_SIZE
        wx = 0.5 * CELL_GRID_SIZE * float(self.cell_size_x[hull_id])
        wy = 0.5 * CELL_GRID_SIZE * float(self.cell_size_y[hull_id])
        ang = float(self.angle[hull_id])
        c = float(np.cos(ang))
        s = float(np.sin(ang))
        # Four body-local corners.  After R(angle) = [[c,-s],[s,c]] they
        # become (c*lx - s*ly, s*lx + c*ly) for each corner.  We only need
        # the extreme x and y, which for an axis-aligned rectangle reduces
        # to |c|*Wx + |s|*Wy on x and |s|*Wx + |c|*Wy on y.
        ex = abs(c) * wx + abs(s) * wy + AABB_PADDING
        ey = abs(s) * wx + abs(c) * wy + AABB_PADDING
        px = float(self.position[hull_id, 0])
        py = float(self.position[hull_id, 1])
        self.aabb[hull_id, 0] = px - ex
        self.aabb[hull_id, 1] = py - ey
        self.aabb[hull_id, 2] = px + ex
        self.aabb[hull_id, 3] = py + ey

    def half_extents(self, hull_id: int) -> tuple[float, float]:
        """Body-local half-extents in world units (one per axis)."""
        from slappyengine.physics.cell import CELL_GRID_SIZE
        return (
            0.5 * CELL_GRID_SIZE * float(self.cell_size_x[hull_id]),
            0.5 * CELL_GRID_SIZE * float(self.cell_size_y[hull_id]),
        )

    # --------------------------------------------------------- children alloc

    def _allocate_child_range(self, count: int) -> int:
        """Allocate ``count`` contiguous slots in ``_children``, growing if needed.

        Uses a simple bump allocator (``_children_used``).  Returns the start
        offset.  Sprint 4 will replace this with a real free-range allocator
        so ``coalesce`` can reuse holes; for now coalesced ranges leak the
        slot indices but the values become stale (-1) so they're harmless.
        """
        if count <= 0:
            return self._children_used
        need = self._children_used + count
        if need > self._child_capacity:
            new_cap = max(self._child_capacity * GROWTH_FACTOR, need)
            new_buf = np.full(new_cap, NO_PARENT, dtype=np.int32)
            new_buf[: self._child_capacity] = self._children
            self._children = new_buf
            self._child_capacity = new_cap
        offset = self._children_used
        self._children_used += count
        return offset

    # ------------------------------------------------------- subdivide/coalesce

    # Number of children produced by a single subdivide: centre + 6 hex ring.
    _SUBDIVIDE_FANOUT: int = 7
    # Ring radius for hex children = parent.radius / sqrt(2).
    _RING_RADIUS_SCALE: float = 1.0 / float(np.sqrt(2.0))
    # Children cell-size shrinks by 1/sqrt(2) on each axis.
    _CELL_SIZE_SCALE: float = 1.0 / float(np.sqrt(2.0))

    def subdivide(
        self,
        hull_id: int,
        cell_pool: "object | None" = None,
    ) -> list[int]:
        """Split ``hull_id`` into 7 children (centre + hex ring at √2 inner R).

        Children inherit the parent's transform and bulk state.  Their cell
        grids are scaled by 1/√2 on each axis (so each child covers √2× less
        area per side; 4 hex children plus overlap from the centre cover the
        parent's footprint with conservative redundancy).

        If ``cell_pool`` (a :class:`CellGridPool`) is provided, each child
        acquires its own slot and the parent's cell field is downsampled
        into it.  When ``cell_pool`` is None we only build the hull tree —
        the per-cell refinement is the caller's problem.

        Idempotent: if the hull already has children we return them as-is.
        """
        if not self._alive[hull_id]:
            raise ValueError(f"hull {hull_id} is not alive")
        existing = int(self.child_count[hull_id])
        if existing > 0:
            off = int(self.child_offset[hull_id])
            return [int(self._children[off + i]) for i in range(existing)]

        from slappyengine.physics.cell import CELL_GRID_SIZE

        parent_pos_x = float(self.position[hull_id, 0])
        parent_pos_y = float(self.position[hull_id, 1])
        parent_vx = float(self.velocity[hull_id, 0])
        parent_vy = float(self.velocity[hull_id, 1])
        parent_omega = float(self.omega[hull_id])
        parent_radius = float(self.radius[hull_id])
        parent_mass = float(self.mass[hull_id])
        parent_inertia = float(self.inertia[hull_id])
        parent_csx = float(self.cell_size_x[hull_id])
        parent_csy = float(self.cell_size_y[hull_id])
        parent_tier = int(self.tier[hull_id])
        parent_material = int(self.material_id[hull_id])
        parent_fixed = bool(self.fixed[hull_id])
        parent_depth = int(self.depth[hull_id])
        parent_root = int(self.root_id[hull_id])
        # Phase A: children inherit the parent's activation state so newly-
        # subdivided hulls don't drop into quiescent and skip a substep that
        # the parent would have run.
        parent_activation = int(self.activation_level[hull_id])
        parent_active_until = int(self.active_until_frame[hull_id])

        child_csx = parent_csx * self._CELL_SIZE_SCALE
        child_csy = parent_csy * self._CELL_SIZE_SCALE
        child_mass = parent_mass / self._SUBDIVIDE_FANOUT
        child_inertia = parent_inertia / self._SUBDIVIDE_FANOUT
        child_radius_world = float(
            np.sqrt(
                (0.5 * CELL_GRID_SIZE * child_csx) ** 2
                + (0.5 * CELL_GRID_SIZE * child_csy) ** 2
            )
        )

        # Ring distance from parent centre = parent.radius / √2.
        ring_r = parent_radius * self._RING_RADIUS_SCALE
        # Centre + 6 ring offsets in parent-local frame (parent angle ignored
        # for the first cut — children's pose tracks the parent's frame).
        offsets: list[tuple[float, float]] = [(0.0, 0.0)]
        for k in range(6):
            theta = k * (np.pi / 3.0)
            offsets.append((ring_r * float(np.cos(theta)),
                            ring_r * float(np.sin(theta))))

        # Pre-grab the parent's cell-field view (if any) so we can downsample.
        parent_cells = None
        if cell_pool is not None:
            parent_gid = int(self.cell_grid_id[hull_id])
            if parent_gid != NO_CELL_GRID:
                try:
                    parent_cells = cell_pool.slot_view(parent_gid)
                except Exception:
                    parent_cells = None

        child_ids: list[int] = []
        for ox, oy in offsets:
            cid = self._allocate_slot()
            self.parent_id[cid] = hull_id
            self.depth[cid] = parent_depth + 1
            self.root_id[cid] = parent_root
            self.position[cid, 0] = parent_pos_x + ox
            self.position[cid, 1] = parent_pos_y + oy
            self.angle[cid] = float(self.angle[hull_id])
            self.stretch[cid, 0] = 1.0
            self.stretch[cid, 1] = 1.0
            self.shear[cid] = 0.0
            self.velocity[cid, 0] = parent_vx
            self.velocity[cid, 1] = parent_vy
            self.omega[cid] = parent_omega
            # Child centre_local is the offset from the parent's centre in
            # parent-local frame.
            self.centre_local[cid, 0] = ox
            self.centre_local[cid, 1] = oy
            self.cell_size_x[cid] = child_csx
            self.cell_size_y[cid] = child_csy
            self.radius[cid] = child_radius_world
            self.mass[cid] = child_mass
            self.inertia[cid] = child_inertia
            self.tier[cid] = parent_tier
            self.disagreement[cid] = 0.0
            self.hysteresis[cid] = 0
            self.material_id[cid] = parent_material
            self.cell_grid_id[cid] = NO_CELL_GRID
            self.fixed[cid] = parent_fixed
            self.child_offset[cid] = 0
            self.child_count[cid] = 0
            # Phase A: propagate the parent's activation to every child so
            # the substep gate continues to fire for them.
            self.activation_level[cid] = parent_activation
            self.active_until_frame[cid] = parent_active_until
            self._recompute_oriented_aabb(cid)
            child_ids.append(cid)

        # Cell-pool refinement: each child gets its own grid sampled from the
        # parent's at half-resolution per axis (the cell-grid stays 32×32 in
        # body-local frame but maps a √2× smaller world footprint).
        if cell_pool is not None and parent_cells is not None:
            for child_idx, (cid, (ox, oy)) in enumerate(zip(child_ids, offsets)):
                slot = cell_pool.acquire()
                self.cell_grid_id[cid] = slot
                child_cells = cell_pool.slot_view(slot)
                self._downsample_parent_to_child(
                    parent_cells, child_cells,
                    parent_csx, parent_csy,
                    child_csx, child_csy,
                    ox, oy,
                )

        # Record children in the flat _children array.
        offset = self._allocate_child_range(self._SUBDIVIDE_FANOUT)
        for i, cid in enumerate(child_ids):
            self._children[offset + i] = cid
        self.child_offset[hull_id] = offset
        self.child_count[hull_id] = self._SUBDIVIDE_FANOUT

        self._dirty = True
        return child_ids

    @staticmethod
    def _downsample_parent_to_child(
        parent_cells: np.ndarray,
        child_cells: np.ndarray,
        parent_csx: float,
        parent_csy: float,
        child_csx: float,
        child_csy: float,
        ox: float,
        oy: float,
    ) -> None:
        """Sample the parent's 32×32 cell field into the child's grid.

        Each child cell at local index (i, j) sits at body-local world offset
        ``((i - 15.5) * child_csx, (j - 15.5) * child_csy)`` plus the child's
        ``(ox, oy)`` offset from the parent's centre.  Convert that back into
        the parent's index space and nearest-neighbour sample.

        Out-of-bounds samples are clamped to the parent's edge — fine for the
        first cut; Sprint 3 may want a "vacuum" fill instead.
        """
        from slappyengine.physics.cell import CELL_GRID_SIZE
        N = CELL_GRID_SIZE
        c_idx = (N - 1) * 0.5
        # Parent cell index for each child cell:
        # child world offset from parent centre = (i - c_idx)*child_csx + ox
        # parent cell index = world_offset / parent_csx + c_idx
        yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
        wx = (xx - c_idx) * child_csx + ox
        wy = (yy - c_idx) * child_csy + oy
        px = wx / parent_csx + c_idx
        py = wy / parent_csy + c_idx
        px_i = np.clip(np.round(px).astype(np.int32), 0, N - 1)
        py_i = np.clip(np.round(py).astype(np.int32), 0, N - 1)
        # parent_cells is (32, 32, C) indexed [row=y, col=x, ch].
        child_cells[...] = parent_cells[py_i, px_i, :]

    def coalesce(
        self,
        hull_id: int,
        cell_pool: "object | None" = None,
    ) -> None:
        """Merge ``hull_id``'s children back into the parent.

        Aggregates children's bulk state (mass-weighted velocity / omega) and,
        if a ``cell_pool`` is given and the parent owns a cell grid, averages
        the children's cell fields back into the parent's grid.

        Children's hull slots and cell-pool slots are released.  The flat
        ``_children`` entries are stamped with ``NO_PARENT`` (-1) so any
        lingering reader sees a clear sentinel.

        No-op if the hull has no children.
        """
        if not self._alive[hull_id]:
            return
        count = int(self.child_count[hull_id])
        if count == 0:
            return
        offset = int(self.child_offset[hull_id])
        child_ids = [int(self._children[offset + i]) for i in range(count)]

        # --- aggregate rigid state -----------------------------------------
        total_mass = 0.0
        sum_mvx = 0.0
        sum_mvy = 0.0
        sum_iomega = 0.0
        total_inertia = 0.0
        for cid in child_ids:
            m = float(self.mass[cid])
            inert = float(self.inertia[cid])
            total_mass += m
            sum_mvx += m * float(self.velocity[cid, 0])
            sum_mvy += m * float(self.velocity[cid, 1])
            sum_iomega += inert * float(self.omega[cid])
            total_inertia += inert
        if total_mass > 0.0:
            self.velocity[hull_id, 0] = sum_mvx / total_mass
            self.velocity[hull_id, 1] = sum_mvy / total_mass
        if total_inertia > 0.0:
            self.omega[hull_id] = sum_iomega / total_inertia

        # Phase A: parent inherits max(child_activation) so a single hot
        # child keeps the merged parent hot. Likewise track the latest
        # active_until_frame across the children.
        max_act = 0
        max_until = -1
        for cid in child_ids:
            a = int(self.activation_level[cid])
            if a > max_act:
                max_act = a
            u = int(self.active_until_frame[cid])
            if u > max_until:
                max_until = u
        self.activation_level[hull_id] = max_act
        self.active_until_frame[hull_id] = max_until

        # --- aggregate cell field (parent must own a grid) ------------------
        if cell_pool is not None:
            parent_gid = int(self.cell_grid_id[hull_id])
            if parent_gid != NO_CELL_GRID:
                try:
                    parent_cells = cell_pool.slot_view(parent_gid)
                    self._upsample_children_to_parent(
                        parent_cells, child_ids, hull_id, cell_pool,
                    )
                except Exception:
                    pass

        # --- release children's resources ----------------------------------
        if cell_pool is not None:
            for cid in child_ids:
                gid = int(self.cell_grid_id[cid])
                if gid != NO_CELL_GRID:
                    cell_pool.release(gid)
                    self.cell_grid_id[cid] = NO_CELL_GRID
        for cid in child_ids:
            self.free(cid)
        # Stamp the abandoned _children range so stale readers see sentinels.
        for i in range(count):
            self._children[offset + i] = NO_PARENT

        self.child_offset[hull_id] = 0
        self.child_count[hull_id] = 0
        self._dirty = True

    def _upsample_children_to_parent(
        self,
        parent_cells: np.ndarray,
        child_ids: list[int],
        parent_id: int,
        cell_pool: "object",
    ) -> None:
        """Reverse of :meth:`_downsample_parent_to_child`.

        For each parent cell, find which child it falls inside (smallest
        Euclidean distance to a child centre) and sample that child's
        nearest cell.  First cut — overlap regions get whoever-was-closest;
        no proper area-weighted blend yet.
        """
        from slappyengine.physics.cell import CELL_GRID_SIZE
        N = CELL_GRID_SIZE
        c_idx = (N - 1) * 0.5
        parent_csx = float(self.cell_size_x[parent_id])
        parent_csy = float(self.cell_size_y[parent_id])
        parent_pos_x = float(self.position[parent_id, 0])
        parent_pos_y = float(self.position[parent_id, 1])

        # Pre-fetch each child's grid + offsets.
        child_views: list[tuple[np.ndarray, float, float, float, float]] = []
        for cid in child_ids:
            gid = int(self.cell_grid_id[cid])
            if gid == NO_CELL_GRID:
                continue
            view = cell_pool.slot_view(gid)
            cpx = float(self.position[cid, 0]) - parent_pos_x
            cpy = float(self.position[cid, 1]) - parent_pos_y
            ccsx = float(self.cell_size_x[cid])
            ccsy = float(self.cell_size_y[cid])
            child_views.append((view, cpx, cpy, ccsx, ccsy))
        if not child_views:
            return

        yy, xx = np.mgrid[0:N, 0:N].astype(np.float32)
        # Parent-cell world offsets (relative to parent centre).
        wx = (xx - c_idx) * parent_csx
        wy = (yy - c_idx) * parent_csy

        # Pick the child whose centre is closest to each parent cell.
        best_dist2 = np.full((N, N), np.inf, dtype=np.float32)
        best_idx = np.zeros((N, N), dtype=np.int32)
        for k, (_, cpx, cpy, _, _) in enumerate(child_views):
            d2 = (wx - cpx) ** 2 + (wy - cpy) ** 2
            mask = d2 < best_dist2
            best_dist2[mask] = d2[mask]
            best_idx[mask] = k

        # For each child, gather the parent cells assigned to it and sample.
        for k, (view, cpx, cpy, ccsx, ccsy) in enumerate(child_views):
            mask = best_idx == k
            if not mask.any():
                continue
            local_wx = wx[mask] - cpx
            local_wy = wy[mask] - cpy
            ci = np.clip(np.round(local_wx / ccsx + c_idx).astype(np.int32), 0, N - 1)
            cj = np.clip(np.round(local_wy / ccsy + c_idx).astype(np.int32), 0, N - 1)
            parent_cells[mask] = view[cj, ci, :]

    def spawn_fragment(
        self,
        parent_id: int,
        cell_pool: "object",
        material_lookup: "dict[int, object]",
    ) -> list[int]:
        """Detect disjoint clusters in ``parent_id``'s cell grid and spawn
        a new root hull for each one beyond the largest.

        Algorithm (Sprint 4 brittle-fracture follow-up):

        1. Run :func:`connected_components` on the parent's density + bond
           fields.  If only one cluster (or zero), nothing to do — return
           an empty list.
        2. Choose the LARGEST cluster (most solid cells) to remain in the
           parent.  All other clusters are spawned as fresh root hulls.
        3. For each non-largest cluster:

           * Cluster centroid is the mass-weighted centroid of its cells
             in parent-local frame (cell mass = ``ρ_mat × density × cell_area``).
           * Cluster mass is the integral of that cell mass.
           * Cluster centroid velocity is the parent's bulk velocity plus
             the rigid contribution of the parent's rotation at the
             cluster centroid plus the mass-weighted mean of the cells'
             body-local ``v`` field.
           * Cluster angular velocity is the parent's bulk ω plus the
             ``Σ m·(r×v) / I`` residual taken from the cells' body-local
             velocity about the cluster centroid.
           * The new body's inertia is the mass-weighted ``Σ m·r²`` about
             the cluster centroid — same formula
             :meth:`PhysicsWorld.create_body` uses, so the rigid bus stays
             the single source of truth.
           * A new cell-pool slot is acquired and the cluster's cells are
             copied in, translated so the cluster centroid lands near the
             grid centre ``(15.5, 15.5)``.
           * The parent's cells in the cluster region are zeroed (all
             channels) so the parent no longer claims them.

        4. The parent's mass + inertia are recomputed from its remaining
           cells via the same density-integral as :meth:`create_body`.

        Limitations
        -----------
        * Centroid translation onto the new grid rounds to the nearest
          integer cell — sub-cell residual is dropped.  For a 32×32 grid
          this is ≤ ½ cell of positional error in the new body.
        * The fragment's grid uses the parent's ``cell_size_x/y`` directly;
          if the cluster is small, large parts of the new 32×32 grid will
          stay at density 0.  Mass and inertia integrate over only the
          live cells, so this is harmless dynamically.
        * No T0/T1/T2 subdivision rewiring: this method assumes the parent
          is a T2 root that owns its own cell grid.  If the parent has
          subdivided children, they keep pointing at the parent — the
          caller should ``coalesce`` first.

        Parameters
        ----------
        parent_id:
            Hull id of the body whose cells should be inspected.
        cell_pool:
            The :class:`CellGridPool` that allocates per-hull cell grids.
            New hulls acquire fresh slots from it.
        material_lookup:
            Maps ``material_id`` (uint16, stored on the hull) to its
            :class:`CellMaterial`.  Used to read ``density_rho`` for the
            mass and inertia integrals.

        Returns
        -------
        list[int]
            Ids of the newly-spawned root hulls.  Empty when the cell
            grid has only one connected cluster (i.e. no fragmentation).
        """
        from slappyengine.physics.cc_label import connected_components
        from slappyengine.physics.cell import CELL_GRID_SIZE

        if not self._alive[parent_id]:
            raise ValueError(f"hull {parent_id} is not alive")
        parent_gid = int(self.cell_grid_id[parent_id])
        if parent_gid == NO_CELL_GRID:
            # No cell grid -> no per-pixel fracture possible.
            return []

        parent_cells = cell_pool.slot_view(parent_gid)
        # Per-channel views (no copies).
        density = parent_cells[..., 9]
        bond_e = parent_cells[..., 14]
        bond_s = parent_cells[..., 15]
        v_x = parent_cells[..., 2]
        v_y = parent_cells[..., 3]

        labels, n_labels = connected_components(density, bond_e, bond_s)
        if n_labels <= 1:
            return []

        # Count solid cells per cluster to pick the largest.
        cluster_sizes = np.zeros(n_labels, dtype=np.int64)
        for k in range(n_labels):
            cluster_sizes[k] = int((labels == k).sum())
        largest = int(np.argmax(cluster_sizes))

        # Material density for mass integrals.
        mat = material_lookup.get(int(self.material_id[parent_id]))
        if mat is None:
            raise ValueError(
                f"no CellMaterial registered for material_id="
                f"{int(self.material_id[parent_id])}"
            )
        rho_mat = float(mat.density_rho)

        cs_x = float(self.cell_size_x[parent_id])
        cs_y = float(self.cell_size_y[parent_id])
        cell_area = cs_x * cs_y
        c_idx = (CELL_GRID_SIZE - 1) * 0.5

        # Body-local offsets per cell (world units, parent-local frame).
        # cells are indexed (row=y, col=x); see create_body in world.py.
        yy, xx = np.mgrid[0:CELL_GRID_SIZE, 0:CELL_GRID_SIZE].astype(np.float32)
        rx_local = (xx - c_idx) * cs_x  # x offset from parent centre
        ry_local = (yy - c_idx) * cs_y  # y offset from parent centre

        parent_pos_x = float(self.position[parent_id, 0])
        parent_pos_y = float(self.position[parent_id, 1])
        parent_vx = float(self.velocity[parent_id, 0])
        parent_vy = float(self.velocity[parent_id, 1])
        parent_omega = float(self.omega[parent_id])
        parent_material_id = int(self.material_id[parent_id])
        parent_tier = int(self.tier[parent_id])
        parent_fixed = bool(self.fixed[parent_id])

        spawned: list[int] = []

        for k in range(n_labels):
            if k == largest:
                continue
            mask = labels == k
            n_cells_in_cluster = int(mask.sum())
            if n_cells_in_cluster == 0:
                continue

            # Cluster mass (cell-area integral).
            d_k = density[mask].astype(np.float64)
            cell_mass = rho_mat * d_k * cell_area
            cluster_mass = float(cell_mass.sum())
            if cluster_mass <= 0.0:
                # All-density-0 cluster shouldn't happen since the labeller
                # requires density > threshold, but defend anyway.
                continue

            # Mass-weighted centroid in parent-local frame (world units).
            rx_k = rx_local[mask].astype(np.float64)
            ry_k = ry_local[mask].astype(np.float64)
            cx_local_world = float((cell_mass * rx_k).sum() / cluster_mass)
            cy_local_world = float((cell_mass * ry_k).sum() / cluster_mass)
            # In cell-index space (for the cell-copy translation).
            cx_idx_cells = cx_local_world / cs_x + c_idx
            cy_idx_cells = cy_local_world / cs_y + c_idx

            # World position of the new body's centre of mass.
            new_x = parent_pos_x + cx_local_world
            new_y = parent_pos_y + cy_local_world

            # Mass-weighted linear velocity of the cluster.  The cells' v
            # field is body-local (zero-mean over the whole parent), so
            # the new body inherits the parent's bulk v plus the rigid
            # contribution of the parent's rotation at the cluster centroid
            # (point-velocity = v + ω × r in 2-D with positive ω = CCW),
            # plus the mean of the body-local v field over the cluster.
            vx_k = v_x[mask].astype(np.float64)
            vy_k = v_y[mask].astype(np.float64)
            mean_local_vx = float((cell_mass * vx_k).sum() / cluster_mass)
            mean_local_vy = float((cell_mass * vy_k).sum() / cluster_mass)
            new_vx = parent_vx - parent_omega * cy_local_world + mean_local_vx
            new_vy = parent_vy + parent_omega * cx_local_world + mean_local_vy

            # Offsets from the cluster's OWN centroid (for ω + inertia).
            rx_to_centroid = rx_k - cx_local_world
            ry_to_centroid = ry_k - cy_local_world
            # Cluster inertia about its centroid.
            cluster_inertia = float(
                (cell_mass * (rx_to_centroid * rx_to_centroid
                              + ry_to_centroid * ry_to_centroid)).sum()
            )

            # Residual angular velocity from the cell field about the
            # cluster centroid.  Use v relative to the cluster's mean
            # local v so a pure linear v doesn't contribute.
            rel_vx = vx_k - mean_local_vx
            rel_vy = vy_k - mean_local_vy
            L_residual = float(
                (cell_mass * (rx_to_centroid * rel_vy
                              - ry_to_centroid * rel_vx)).sum()
            )
            residual_omega = (
                L_residual / cluster_inertia if cluster_inertia > 1e-12 else 0.0
            )
            # Parent's bulk ω carries forward; the body-local field can add
            # a residual spin on top.
            new_omega = parent_omega + residual_omega

            if cluster_inertia <= 0.0:
                cluster_inertia = 1.0

            # Spawn the new root hull at the cluster centroid.
            new_id = self.spawn_root(
                x=new_x,
                y=new_y,
                cell_size_x=cs_x,
                cell_size_y=cs_y,
                mass=cluster_mass,
                inertia=cluster_inertia,
                material_id=parent_material_id,
                tier=parent_tier,
                fixed=parent_fixed,
            )
            self.velocity[new_id, 0] = float(new_vx)
            self.velocity[new_id, 1] = float(new_vy)
            self.omega[new_id] = float(new_omega)

            # Acquire a new cell-grid slot.  acquire() zeroes the slot
            # then sets bond_n/e/s = 1.0; that's the right initial state
            # for the perimeter of a new fragment.
            new_gid = cell_pool.acquire()
            self.cell_grid_id[new_id] = new_gid
            new_cells = cell_pool.slot_view(new_gid)

            # Translation in cell-index space: each parent cell at (i, j)
            # ends up at (i - di, j - dj) where di/dj round the centroid
            # shift to the nearest integer cell.  Sub-cell residual is
            # dropped (≤ ½ cell error).
            di = int(round(cy_idx_cells - c_idx))
            dj = int(round(cx_idx_cells - c_idx))
            src_i, src_j = np.nonzero(mask)
            dst_i = src_i - di
            dst_j = src_j - dj
            in_bounds = (
                (dst_i >= 0) & (dst_i < CELL_GRID_SIZE)
                & (dst_j >= 0) & (dst_j < CELL_GRID_SIZE)
            )
            if in_bounds.any():
                si = src_i[in_bounds]
                sj = src_j[in_bounds]
                ti = dst_i[in_bounds]
                tj = dst_j[in_bounds]
                # Copy ALL channels (including bonds + per-cell v + heat).
                new_cells[ti, tj, :] = parent_cells[si, sj, :]

            # Zero the parent's cells at the cluster region so the parent
            # no longer claims them.  Zero EVERY channel so lingering
            # bonds, velocity, or strain don't pretend the cells still
            # exist.
            parent_cells[mask] = 0.0
            spawned.append(new_id)

        # Recompute parent's mass and inertia from its REMAINING cells —
        # same density-integral as PhysicsWorld.create_body so the rigid
        # bus stays consistent with the cell field.
        rem_density = parent_cells[..., 9].astype(np.float64)
        rem_mass = float((rho_mat * rem_density * cell_area).sum())
        if rem_mass > 0.0:
            r2 = (rx_local * rx_local + ry_local * ry_local).astype(np.float64)
            rem_inertia = float(
                (rho_mat * rem_density * cell_area * r2).sum()
            )
            if rem_inertia <= 0.0:
                rem_inertia = 1.0
            self.mass[parent_id] = float(rem_mass)
            self.inertia[parent_id] = float(rem_inertia)
        else:
            # Parent has nothing left — keep it minimally consistent.
            self.mass[parent_id] = 1.0
            self.inertia[parent_id] = 1.0

        self._dirty = True
        return spawned

    def integrate_transforms(self, dt: float) -> None:
        """Advance every live, non-fixed hull's pose by ``dt`` and refresh AABBs.

        AABB refresh is rotation-aware: the four body-local corners are
        rotated by the (now-updated) ``angle`` and the world-space min/max
        is taken.  Done vectorised over all moved hulls in a single pass
        (no Python-level loop) so per-step cost stays O(N) with tiny
        constants — for an axis-aligned rectangle the extreme x is just
        ``|cos|*Wx + |sin|*Wy`` (and symmetrically for y), so we never
        even materialise the (N, 4, 2) corner array.
        """
        from slappyengine.physics.cell import CELL_GRID_SIZE
        if self._count == 0:
            return
        movable = self._alive & ~self.fixed
        if not movable.any():
            return
        # Position += velocity * dt.
        self.position[movable] += self.velocity[movable] * dt
        # Angle += omega * dt.
        self.angle[movable] += self.omega[movable] * dt

        idxs = np.nonzero(movable)[0]
        if idxs.size:
            wx = 0.5 * CELL_GRID_SIZE * self.cell_size_x[idxs]
            wy = 0.5 * CELL_GRID_SIZE * self.cell_size_y[idxs]
            angs = self.angle[idxs]
            ac = np.abs(np.cos(angs))
            as_ = np.abs(np.sin(angs))
            ex = ac * wx + as_ * wy + AABB_PADDING
            ey = as_ * wx + ac * wy + AABB_PADDING
            px = self.position[idxs, 0]
            py = self.position[idxs, 1]
            self.aabb[idxs, 0] = px - ex
            self.aabb[idxs, 1] = py - ey
            self.aabb[idxs, 2] = px + ex
            self.aabb[idxs, 3] = py + ey
        self._dirty = True

    def free(self, hull_id: int) -> None:
        """Return ``hull_id`` to the free list."""
        if not self._alive[hull_id]:
            return
        self._alive[hull_id] = False
        self.parent_id[hull_id] = NO_PARENT
        self.child_count[hull_id] = 0
        self.cell_grid_id[hull_id] = NO_CELL_GRID
        # Phase A: clear activation state so a reused slot doesn't inherit
        # the previous occupant's hot/quiescent flag.
        self.activation_level[hull_id] = 0
        self.active_until_frame[hull_id] = -1
        self._free_hulls.append(hull_id)
        self._count -= 1
        self._dirty = True

    def is_alive(self, hull_id: int) -> bool:
        """True if ``hull_id`` is a currently-allocated slot."""
        return bool(self._alive[hull_id])


# --------------------------------------------------------------- smoke test

if __name__ == "__main__":
    tree = HullTree()
    ids: list[int] = []
    for i in range(10):
        rid = tree.spawn_root(
            x=float(i),
            y=0.0,
            cell_size_x=2.0,
            cell_size_y=2.0,
            mass=1.0,
            inertia=1.0,
            material_id=1,
        )
        # Give every other hull some velocity so integrate actually moves things.
        if i % 2 == 0:
            tree.velocity[rid, 0] = 1.0
            tree.velocity[rid, 1] = 0.5
        tree.omega[rid] = 0.1 * i
        ids.append(rid)

    print(f"spawned {tree.count} hulls; ids={ids}")
    assert tree.count == 10
    assert tree.dirty is True
    tree.clear_dirty()
    assert tree.dirty is False

    # Capture AABBs before integration.
    aabb_before = tree.aabb[ids].copy()

    for frame in range(3):
        tree.integrate_transforms(1.0 / 60.0)

    aabb_after = tree.aabb[ids]
    moved = ~np.all(aabb_before == aabb_after, axis=1)
    print(f"hulls whose AABB changed after 3 frames: {int(moved.sum())} / {len(ids)}")
    # Even-indexed hulls had velocity, so their AABBs must have moved.
    assert moved[::2].all(), "even hulls should have moved"
    # Odd-indexed hulls had zero velocity, so their AABBs must be unchanged.
    assert not moved[1::2].any(), "odd (still) hulls should not have moved"

    # Free / allocate cycle.
    free_target = ids[3]
    tree.free(free_target)
    assert not tree.is_alive(free_target)
    print(f"freed hull {free_target}; count={tree.count}")
    reused = tree.spawn_root(99.0, 99.0, 1.0, 1.0, 1.0, 1.0, 2)
    assert reused == free_target, f"expected reuse of slot {free_target}, got {reused}"
    print(f"reused slot {reused}; count={tree.count}")

    # Subdivide now real (Sprint 2): should produce 7 children.
    kids = tree.subdivide(reused)
    assert len(kids) == 7, f"subdivide should produce 7 children, got {len(kids)}"
    # Coalesce should reverse it.
    tree.coalesce(reused)
    assert int(tree.child_count[reused]) == 0, "coalesce should clear children"

    # Fixed hulls don't move.
    fixed_id = tree.spawn_root(0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1, fixed=True)
    tree.velocity[fixed_id, 0] = 100.0
    before = tree.position[fixed_id].copy()
    tree.integrate_transforms(1.0)
    after = tree.position[fixed_id]
    assert np.all(before == after), "fixed hulls must not move"
    print(f"fixed hull {fixed_id} stayed at {tuple(after)}")

    print("smoke test OK")
