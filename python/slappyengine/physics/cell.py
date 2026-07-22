"""Per-cell pixel layout for the hierarchical-hull per-pixel solver.

Cells live inside 32x32 grids owned by T2 hulls.  The layout here MUST match
the WGSL ``PixelState`` struct used by the ``CONTINUOUS_SIM`` kernel
(canonical 16-channel layout, originally from the now-removed legacy demo)
so that the same GPU buffer can be consumed by either side.
"""
from __future__ import annotations

import numpy as np

from slappyengine.pixel_struct import PixelStruct


# One T2 hull owns one 32x32 grid; bigger bodies = more T2 children.
CELL_GRID_SIZE = 32
CELLS_PER_GRID = CELL_GRID_SIZE * CELL_GRID_SIZE  # 1024

# Default pool capacity (slots).  Each slot is 64 KB so 64 slots = 4 MB.
DEFAULT_POOL_CAPACITY = 64

# Initial neighbour-bond strength (intact).  Fracture sets to 0.
INITIAL_BOND_STRENGTH = 1.0

# Cell pixel layout.  Must match the WGSL ``PixelState`` struct in the
# CONTINUOUS_SIM kernel exactly (same field order, same widths).  This is
# the canonical 16-channel layout (originally from the now-removed legacy
# demo) and must stay in lockstep with ``physics/shaders/inject.wgsl``.
#
# 16 floats == 64 bytes per pixel; a power-of-two GPU stride.
#
# NOTE: we PRESERVE neighbour bonds as separate channels (N/E/S; west = east of
# left neighbour) so fracture can sever coupling without dropping mass.  The
# earlier kernel used density-as-bond; this richer scheme is what the current
# fracture/repair pipeline requires.
CELL_PIXEL_STRUCT = PixelStruct({
    "u":              "vec2",   # displacement   (channels 0, 1)
    "v":              "vec2",   # velocity       (channels 2, 3)
    "perm_strain_xx": "f32",    # plastic strain xx   (4)
    "perm_strain_yy": "f32",    # plastic strain yy   (5)
    "perm_strain_xy": "f32",    # plastic strain shear (6)
    "pressure":       "f32",    # (7)
    "damage":         "f32",    # (8)
    "density":        "f32",    # (9)  bond_strength = 0 == "torn", density preserved
    "stretch":        "f32",    # (10)
    "tear":           "f32",    # (11)
    "heat":           "f32",    # (12)
    "bond_n":         "f32",    # (13) bond_strength to north neighbour [0, 1]
    "bond_e":         "f32",    # (14) bond to east
    "bond_s":         "f32",    # (15) bond to south
})

# Channel names that should be initialised to INITIAL_BOND_STRENGTH on acquire.
_BOND_CHANNELS: tuple[str, ...] = ("bond_n", "bond_e", "bond_s")


class CellGridPool:
    """Fixed-size pool of 32x32 cell grids.

    T2 hulls own one slot each; T0/T1 hulls own none.  On coalesce, slot
    returns to the free list.  Each slot is contiguous in a single host-side
    numpy backing array, so the GPU upload is one big memcpy.

    Memory: ``capacity`` slots * 32 * 32 * 16 floats * 4 bytes = 64 KB/slot.
    """

    def __init__(
        self,
        capacity: int = DEFAULT_POOL_CAPACITY,
        memory_budget: "object | None" = None,
    ):
        """Build a pool with ``capacity`` empty slots on the free list.

        ``memory_budget`` is an optional
        :class:`slappyengine.physics.memory_budget.MemoryBudget` instance
        that enforces ``memory.max_cell_pool_slots`` on every
        :meth:`acquire` call (warning at ``warn_at_fraction``, raising
        :class:`MemoryBudgetExceeded` past the cap).  ``None`` skips the
        check entirely — the legacy behaviour.
        """
        self.capacity: int = capacity
        # Optional MemoryBudget for API-boundary enforcement (Sprint 7).
        self.memory_budget = memory_budget
        self._free: list[int] = list(range(capacity))
        self._in_use: set[int] = set()
        # Backing storage: (capacity, 32, 32, total_channels) float32.
        self._cells: np.ndarray = np.zeros(
            (capacity, CELL_GRID_SIZE, CELL_GRID_SIZE, CELL_PIXEL_STRUCT.total_channels),
            dtype=np.float32,
        )
        # Phase B — persistent GPU residency tracking.  These sets are
        # advisory: the GPU substep consults them to decide which slots to
        # re-upload.  Defaults (empty) mean "CPU canonical for every slot",
        # which is the legacy full-upload behaviour wrt callers that ignore
        # the API.  CPU writers call ``mark_dirty`` after mutating a slot;
        # the GPU upload path calls ``mark_gpu_resident`` once the latest
        # bytes have been pushed.  See ``docs/next_phase_plan.md`` §3.2.B.
        self._dirty: set[int] = set()
        self._gpu_resident: set[int] = set()

    # -- Phase B — persistent GPU residency API ----------------------------

    def mark_dirty(self, slot: int) -> None:
        """Mark ``slot`` as CPU-newer-than-GPU; GPU must re-upload it.

        Idempotent.  Safe to call on a slot that's already dirty or that
        has just been released — releasing automatically clears tracking
        because the slot is no longer addressable by callers.
        """
        if slot in self._in_use:
            self._dirty.add(slot)
            self._gpu_resident.discard(slot)

    def mark_gpu_resident(self, slot: int) -> None:
        """Mark ``slot`` as GPU-resident; clears the dirty flag.

        Called by the GPU upload path once the slot's bytes have been
        written to the device buffer.
        """
        if slot in self._in_use:
            self._gpu_resident.add(slot)
            self._dirty.discard(slot)

    def needs_upload(self, slot: int) -> bool:
        """Return True if ``slot``'s CPU state is newer than GPU's."""
        return slot in self._dirty

    def dirty_slots(self) -> set[int]:
        """Snapshot of currently-dirty slots (caller owns the returned set)."""
        return set(self._dirty)

    def clear_dirty(self) -> None:
        """Drop all dirty marks.  Mostly useful for tests/diagnostics."""
        self._dirty.clear()

    def mark_all_dirty(self) -> None:
        """Mark every in-use slot as dirty.

        Used after a pool resize (GPU buffer was reallocated, so even
        slots the GPU previously had cached are gone) and as the
        conservative path when the residency feature is disabled.
        """
        self._dirty = set(self._in_use)
        self._gpu_resident.clear()

    @property
    def cells(self) -> np.ndarray:
        """Direct view of the (capacity, 32, 32, C) backing array."""
        return self._cells

    @property
    def in_use_count(self) -> int:
        """Number of slots currently allocated."""
        return len(self._in_use)

    def acquire(self) -> int:
        """Allocate one slot; return its index.  Raises if pool exhausted.

        If a :class:`MemoryBudget` was supplied at construction time, the
        prospective post-allocation slot count is checked against
        ``memory.max_cell_pool_slots`` first — warning at the configured
        ``warn_at_fraction`` and raising
        :class:`MemoryBudgetExceeded` past the cap.
        """
        budget = self.memory_budget
        if budget is not None:
            budget.check_cell_slot_alloc(len(self._in_use) + 1)
        if not self._free:
            raise RuntimeError(f"CellGridPool exhausted (capacity={self.capacity})")
        slot = self._free.pop()
        self._in_use.add(slot)
        # Zero the slot so previous tenant's state is gone.
        self._cells[slot] = 0.0
        # Initialise all bonds to intact.
        for ch_name in _BOND_CHANNELS:
            view = CELL_PIXEL_STRUCT.slice_field(self._cells[slot], ch_name)
            view[...] = INITIAL_BOND_STRENGTH
        # Fresh slot has CPU-authored state the GPU hasn't seen yet.
        self._dirty.add(slot)
        self._gpu_resident.discard(slot)
        return slot

    def release(self, slot: int) -> None:
        """Return a slot to the free list.  Idempotent if already free."""
        if slot in self._in_use:
            self._in_use.remove(slot)
            self._free.append(slot)
            self._dirty.discard(slot)
            self._gpu_resident.discard(slot)

    def slot_view(self, slot: int) -> np.ndarray:
        """Return the (32, 32, C) numpy view of ``slot``'s cells."""
        if slot not in self._in_use:
            raise ValueError(f"Slot {slot} is not allocated")
        return self._cells[slot]

    def grow(self, new_capacity: int) -> None:
        """Resize the pool.  New slots are added to the free list.

        Cheap path: numpy concatenate.  GPU buffer must be re-allocated on
        the consumer side (``PhysicsWorld``) when this is called.
        """
        if new_capacity <= self.capacity:
            return
        new_cells = np.zeros(
            (new_capacity, CELL_GRID_SIZE, CELL_GRID_SIZE, CELL_PIXEL_STRUCT.total_channels),
            dtype=np.float32,
        )
        new_cells[: self.capacity] = self._cells
        self._cells = new_cells
        self._free.extend(range(self.capacity, new_capacity))
        self.capacity = new_capacity
        # GPU buffer is about to be reallocated by the consumer; every
        # slot's GPU-side copy is now invalid.  Force a full re-upload
        # on the next dispatch.
        self.mark_all_dirty()
