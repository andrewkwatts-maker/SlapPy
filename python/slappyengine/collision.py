"""
Hybrid collision system — three layers:
  Layer 1: AABB/Circle broad phase — fast, Python-side, fires on_collision callbacks
  Layer 2: Pixel-mask GPU collision — silhouette stamp + compute shader overlap detection
  Layer 3: Pixel deformation writeback — health channel damage at collision pixels

Layer 2 and 3 require GPU context (entity._gpu); they degrade gracefully without it.
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.entity import Entity


# --- Collision Shapes ---

class CollisionShape:
    pass

@dataclass
class AABBShape(CollisionShape):
    width: float
    height: float
    offset_x: float = 0.0
    offset_y: float = 0.0

@dataclass
class CircleShape(CollisionShape):
    radius: float
    offset_x: float = 0.0
    offset_y: float = 0.0


# --- Layer 1: Broad Phase ---

def _aabb_rect(entity, shape: AABBShape) -> tuple[float, float, float, float]:
    """Return (left, top, right, bottom) for entity + AABBShape."""
    x = entity.position[0] + shape.offset_x
    y = entity.position[1] + shape.offset_y
    return x, y, x + shape.width, y + shape.height

def check_aabb(a, a_shape: AABBShape, b, b_shape: AABBShape) -> tuple[bool, tuple[float, float]]:
    """Returns (colliding, overlap_vector)."""
    al, at, ar, ab = _aabb_rect(a, a_shape)
    bl, bt, br, bb = _aabb_rect(b, b_shape)
    if ar <= bl or br <= al or ab <= bt or bb <= at:
        return False, (0.0, 0.0)
    # Minimum overlap vector
    ox = min(ar - bl, br - al)
    oy = min(ab - bt, bb - at)
    if ox < oy:
        return True, (ox if al < bl else -ox, 0.0)
    return True, (0.0, oy if at < bt else -oy)

def check_circle(a, a_shape: CircleShape, b, b_shape: CircleShape) -> tuple[bool, tuple[float, float]]:
    ax = a.position[0] + a_shape.offset_x
    ay = a.position[1] + a_shape.offset_y
    bx = b.position[0] + b_shape.offset_x
    by = b.position[1] + b_shape.offset_y
    dx, dy = bx - ax, by - ay
    dist_sq = dx * dx + dy * dy
    min_dist = a_shape.radius + b_shape.radius
    if dist_sq >= min_dist * min_dist:
        return False, (0.0, 0.0)
    dist = math.sqrt(dist_sq) or 1e-9
    overlap = min_dist - dist
    return True, (dx / dist * overlap, dy / dist * overlap)

def check_aabb_circle(box_ent, box: AABBShape, circ_ent, circ: CircleShape) -> tuple[bool, tuple[float, float]]:
    cx = circ_ent.position[0] + circ.offset_x
    cy = circ_ent.position[1] + circ.offset_y
    l, t, r, b = _aabb_rect(box_ent, box)
    nearest_x = max(l, min(cx, r))
    nearest_y = max(t, min(cy, b))
    dx, dy = cx - nearest_x, cy - nearest_y
    dist_sq = dx * dx + dy * dy
    if dist_sq >= circ.radius * circ.radius:
        return False, (0.0, 0.0)
    dist = math.sqrt(dist_sq) or 1e-9
    overlap = circ.radius - dist
    return True, (dx / dist * overlap, dy / dist * overlap)


# --- CollisionWorld (Layer 1 orchestrator) ---

class CollisionWorld:
    """
    Broad-phase AABB/Circle collision world.
    Registered on Scene as scene.collision.
    Called from scene._tick() after entity ticks.
    """
    def __init__(self):
        self._entities: list = []

    def register(self, entity) -> None:
        if entity not in self._entities:
            self._entities.append(entity)

    def unregister(self, entity) -> None:
        try:
            self._entities.remove(entity)
        except ValueError:
            pass

    def tick(self) -> list[tuple]:
        """Check all pairs, fire callbacks. Returns list of (entity_a, entity_b) hit pairs."""
        from slappyengine.z_height import check_z_aabb
        hits: list[tuple] = []
        ents = [e for e in self._entities if hasattr(e, "collision_shape") and e.collision_shape is not None]
        for i in range(len(ents)):
            for j in range(i + 1, len(ents)):
                a, b = ents[i], ents[j]
                if not check_z_aabb(a, b):
                    continue  # different Z heights — no collision
                hit, overlap = self._check_pair(a, b)
                if hit:
                    hits.append((a, b))
                    self._fire(a, b, overlap)
                    self._fire(b, a, (-overlap[0], -overlap[1]))
        return hits

    def _check_pair(self, a, b) -> tuple[bool, tuple[float, float]]:
        sa, sb = a.collision_shape, b.collision_shape
        if isinstance(sa, AABBShape) and isinstance(sb, AABBShape):
            return check_aabb(a, sa, b, sb)
        if isinstance(sa, CircleShape) and isinstance(sb, CircleShape):
            return check_circle(a, sa, b, sb)
        if isinstance(sa, AABBShape) and isinstance(sb, CircleShape):
            return check_aabb_circle(a, sa, b, sb)
        if isinstance(sa, CircleShape) and isinstance(sb, AABBShape):
            hit, ov = check_aabb_circle(b, sb, a, sa)
            return hit, (-ov[0], -ov[1])
        return False, (0.0, 0.0)

    def _fire(self, entity, other, overlap):
        for script in getattr(entity, "_scripts", []):
            if hasattr(script, "on_collision"):
                try:
                    script.on_collision(entity, other, overlap)
                except Exception as e:
                    print(f"[CollisionWorld] on_collision error: {e}")

    # --- Layer 2 / 3: GPU pixel-mask collision ---

    def init_gpu(self, gpu, width: int, height: int) -> None:
        """Initialize GPU resources for pixel-mask collision (Layer 2)."""
        import wgpu
        self._gpu = gpu
        self._mask_width = width
        self._mask_height = height
        # Create r32uint mask texture (we use r channel for entity_id)
        self._mask_texture = gpu.device.create_texture(
            size=(width, height, 1),
            format=wgpu.TextureFormat.r32uint,
            usage=wgpu.TextureUsage.STORAGE_BINDING | wgpu.TextureUsage.COPY_SRC | wgpu.TextureUsage.TEXTURE_BINDING,
        )
        # Hit buffer: count (4 bytes) + 4096 HitRecords (16 bytes each)
        self._hit_buffer = gpu.device.create_buffer(
            size=4 + 4096 * 16,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC | wgpu.BufferUsage.COPY_DST,
        )
        self._mask_initialized = True

    def stamp_entity(self, encoder, entity, entity_idx: int) -> None:
        """CPU-side: stamp entity AABB onto mask texture via buffer write."""
        # Skip if no GPU context
        if not getattr(self, '_mask_initialized', False):
            return
        # For now, mark regions in a CPU numpy array and upload at end of frame
        # Full GPU-side stamp shader is a future enhancement
        pass

    def dispatch_pixel_scan(self, encoder) -> None:
        """Dispatch the collision_mask compute shader over the mask texture."""
        if not getattr(self, '_mask_initialized', False):
            return
        import wgpu
        from pathlib import Path

        # Load and compile the collision_mask shader
        shader_path = Path(__file__).parent.parent.parent / "shaders" / "collision_mask.wgsl"
        source = shader_path.read_text(encoding="utf-8")
        device = self._gpu.device
        module = device.create_shader_module(code=source)
        pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": module, "entry_point": "main"},
        )

        # Dims uniform: vec2<u32> — width, height
        import numpy as np
        dims_data = np.array([self._mask_width, self._mask_height], dtype=np.uint32)
        dims_buf = device.create_buffer(
            size=8,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
        )
        self._gpu.write_buffer(dims_buf, dims_data)

        # Bind group
        bgl = pipeline.get_bind_group_layout(0)
        bg = device.create_bind_group(
            layout=bgl,
            entries=[
                {"binding": 0, "resource": self._mask_texture.create_view()},
                {"binding": 1, "resource": {"buffer": self._hit_buffer, "offset": 0, "size": self._hit_buffer.size}},
                {"binding": 2, "resource": {"buffer": dims_buf, "offset": 0, "size": 8}},
            ],
        )

        # Reset hit buffer count to 0 first
        encoder.clear_buffer(self._hit_buffer, 0, 4)

        # Dispatch: workgroup_size(8,8), so ceil(w/8) x ceil(h/8) groups
        wx = (self._mask_width + 7) // 8
        wy = (self._mask_height + 7) // 8
        cp = encoder.begin_compute_pass()
        cp.set_pipeline(pipeline)
        cp.set_bind_group(0, bg)
        cp.dispatch_workgroups(wx, wy)
        cp.end()

    def readback_pixel_hits(self, entities_by_idx: dict) -> list:
        """Read back the hit buffer and return (entity_a, entity_b, x, y) tuples."""
        if not getattr(self, '_mask_initialized', False):
            return []
        try:
            import numpy as np
            import wgpu

            buf_size = self._hit_buffer.size
            device = self._gpu.device

            # Copy storage buffer to a staging (MAP_READ) buffer
            staging = device.create_buffer(
                size=buf_size,
                usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
            )
            enc = device.create_command_encoder()
            enc.copy_buffer_to_buffer(self._hit_buffer, 0, staging, 0, buf_size)
            device.queue.submit([enc.finish()])

            # Synchronous map using wgpu 0.19+ API
            staging.map_sync(wgpu.MapMode.READ)
            data = np.frombuffer(staging.read_mapped(0, buf_size), dtype=np.uint32).copy()
            staging.unmap()
            staging.destroy()

            count = min(int(data[0]), 4096)
            hits = []
            for i in range(count):
                base = 1 + i * 4  # count is 1 uint32, each record is 4 uint32s
                id_a, id_b, px, py = data[base], data[base + 1], data[base + 2], data[base + 3]
                ea = entities_by_idx.get(id_a)
                eb = entities_by_idx.get(id_b)
                if ea is not None and eb is not None:
                    hits.append((ea, eb, int(px), int(py)))
            return hits
        except Exception:
            return []

    # --- step() interface (used by CollisionManager / scene wiring) ---

    def step(self) -> list[tuple]:
        """Alias for tick() that returns hit pairs without firing event bus.

        Returns list of (entity_a, entity_b) pairs for the caller to dispatch.
        Callbacks on scripts are still fired internally (same as tick).
        """
        return self.tick()

    def fire_pixel_callbacks(self, hits: list) -> None:
        """Fire on_pixel_collision callbacks and Layer 3 deformation writeback."""
        for entity_a, entity_b, px, py in hits:
            # Layer 2: fire callbacks on scripts
            for script in getattr(entity_a, '_scripts', []):
                if hasattr(script, 'on_pixel_collision'):
                    try:
                        script.on_pixel_collision(entity_a, entity_b, (px, py))
                    except Exception:
                        pass
            for script in getattr(entity_b, '_scripts', []):
                if hasattr(script, 'on_pixel_collision'):
                    try:
                        script.on_pixel_collision(entity_b, entity_a, (px, py))
                    except Exception:
                        pass

            # Layer 3: pixel deformation writeback via PixelAPI
            for entity in (entity_a, entity_b):
                pixels = getattr(entity, 'pixels', None)
                if pixels is not None:
                    try:
                        pixels.write(px, py, {"health": 0})
                    except Exception:
                        pass


# ---------------------------------------------------------------------------
# CollisionManager — thin façade over CollisionWorld, spec-compatible API
# ---------------------------------------------------------------------------

class CollisionManager(CollisionWorld):
    """
    Backwards-compatible façade that exposes the spec-requested API
    (register/unregister by shape, step(), on_collision()) while delegating
    all heavy lifting to the proven CollisionWorld implementation.

    Scene wires both:
        scene.collision  → CollisionManager instance (primary)
        (CollisionWorld subclass, so all GPU layer methods still work)

    Shape registration:
        CollisionWorld uses entity.collision_shape attributes directly.
        CollisionManager.register() sets that attribute so the two
        registration paths are fully interchangeable.
    """

    def __init__(self) -> None:
        super().__init__()
        self._callbacks: list = []

    # --- spec API ---

    def register(self, entity, shape=None) -> None:  # type: ignore[override]
        """Register entity with optional explicit shape.

        If *shape* is provided it is stored on entity.collision_shape.
        If omitted, entity.collision_shape is used as-is (already set by caller).
        Delegates to CollisionWorld.register() for list management.
        """
        if shape is not None:
            entity.collision_shape = shape
        super().register(entity)

    def unregister(self, entity) -> None:  # type: ignore[override]
        """Remove entity from the collision world."""
        super().unregister(entity)

    def step(self) -> list[tuple]:
        """Run broad-phase checks. Returns (entity_a, entity_b) pairs and fires on_collision callbacks."""
        hits = super().step()  # CollisionWorld.step() calls tick() internally
        for ea, eb in hits:
            for cb in self._callbacks:
                try:
                    cb(ea, eb)
                except Exception as exc:
                    print(f"[CollisionManager] on_collision callback error: {exc}")
        return hits

    def on_collision(self, callback) -> None:
        """Register a callback(entity_a, entity_b) fired for every broad-phase hit."""
        self._callbacks.append(callback)
