"""Tests for CollisionWorld.stamp_entity — the previously-no-op silhouette stamp.

These tests use a fake GPU device/queue that captures every write_texture call,
so they exercise the stamping logic without needing a real wgpu adapter. They
exist specifically to guard against the regression where stamp_entity was a
``pass`` and dispatch_pixel_scan therefore always saw an empty mask.
"""
from __future__ import annotations

import numpy as np
import pytest

from slappyengine.collision import AABBShape, CollisionWorld
from slappyengine.entity import Entity
from slappyengine.layer import Layer


# ---------------------------------------------------------------------------
# Fake GPU plumbing
# ---------------------------------------------------------------------------

class _FakeQueue:
    def __init__(self) -> None:
        self.writes: list[dict] = []

    def write_texture(self, dest, data, layout, size):
        self.writes.append({
            "origin": dest.get("origin"),
            "data": bytes(data),
            "bytes_per_row": layout["bytes_per_row"],
            "rows_per_image": layout["rows_per_image"],
            "size": tuple(size),
        })


class _FakeTexture:
    pass


class _FakeDevice:
    def __init__(self) -> None:
        self.queue = _FakeQueue()

    def create_texture(self, **kwargs):  # noqa: ARG002
        return _FakeTexture()

    def create_buffer(self, **kwargs):  # noqa: ARG002
        return object()


class _FakeGPU:
    def __init__(self) -> None:
        self.device = _FakeDevice()

    def write_buffer(self, *args, **kwargs):  # noqa: ARG002
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_world(width: int = 64, height: int = 64) -> CollisionWorld:
    """Build a CollisionWorld with fake GPU resources installed."""
    world = CollisionWorld()
    gpu = _FakeGPU()
    # Skip init_gpu (it imports wgpu); set the fields it would have set.
    world._gpu = gpu
    world._mask_width = width
    world._mask_height = height
    world._mask_texture = _FakeTexture()
    world._hit_buffer = object()
    world._mask_initialized = True
    return world


def _make_entity_with_alpha(x: float, y: float, size: int = 8) -> Entity:
    """Entity whose primary Layer2D is a fully-opaque size×size square."""
    e = Entity(name="stamper")
    e.position = (x, y)
    e.collision_shape = AABBShape(width=size, height=size)
    img = np.zeros((size, size, 4), dtype=np.uint8)
    img[:, :, 3] = 255  # fully opaque silhouette
    layer = Layer.blank(size, size)
    layer._image_data = img
    e.layers = [layer]
    return e


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_stamp_entity_writes_to_mask_texture():
    """Regression: stamp_entity used to be a `pass` — verify it now uploads."""
    world = _make_world(64, 64)
    entity = _make_entity_with_alpha(10.0, 12.0, size=8)

    world.stamp_entity(encoder=None, entity=entity, entity_idx=7)

    writes = world._gpu.device.queue.writes
    assert len(writes) == 1, "stamp_entity should issue exactly one write_texture"
    w = writes[0]
    # Origin matches entity position (rounded)
    assert w["origin"] == (10, 12, 0)
    assert w["size"] == (8, 8, 1)
    # r32uint = 4 bytes per pixel
    assert w["bytes_per_row"] == 8 * 4

    stamp = np.frombuffer(w["data"], dtype=np.uint32).reshape(8, 8)
    # Every pixel of the fully-opaque silhouette must carry entity_idx
    assert (stamp == 7).all(), "every alpha>127 pixel must be stamped with idx"


def test_stamp_entity_zero_idx_is_skipped():
    """entity_idx 0 is reserved for 'empty' in the collision_mask shader."""
    world = _make_world(64, 64)
    entity = _make_entity_with_alpha(0.0, 0.0)
    world.stamp_entity(encoder=None, entity=entity, entity_idx=0)
    assert world._gpu.device.queue.writes == []


def test_stamp_entity_respects_alpha_threshold():
    """Pixels with alpha <= 127 must NOT carry the entity id."""
    world = _make_world(64, 64)
    e = Entity(name="halfalpha")
    e.position = (0.0, 0.0)
    e.collision_shape = AABBShape(width=4, height=4)
    img = np.zeros((4, 4, 4), dtype=np.uint8)
    img[:2, :, 3] = 255   # top half opaque
    img[2:, :, 3] = 50    # bottom half transparent
    layer = Layer.blank(4, 4)
    layer._image_data = img
    e.layers = [layer]

    world.stamp_entity(encoder=None, entity=e, entity_idx=3)
    stamp = np.frombuffer(world._gpu.device.queue.writes[0]["data"],
                          dtype=np.uint32).reshape(4, 4)
    assert (stamp[:2, :] == 3).all()
    assert (stamp[2:, :] == 0).all()


def test_stamp_entity_clips_to_mask_bounds():
    """Entity partly off the mask must clip without crashing."""
    world = _make_world(16, 16)
    entity = _make_entity_with_alpha(-4.0, -4.0, size=8)
    world.stamp_entity(encoder=None, entity=entity, entity_idx=2)
    writes = world._gpu.device.queue.writes
    assert len(writes) == 1
    # Only the in-bounds 4×4 region should be uploaded
    assert writes[0]["origin"] == (0, 0, 0)
    assert writes[0]["size"] == (4, 4, 1)


def test_stamp_entity_fully_offscreen_is_noop():
    world = _make_world(16, 16)
    entity = _make_entity_with_alpha(100.0, 100.0, size=8)
    world.stamp_entity(encoder=None, entity=entity, entity_idx=5)
    assert world._gpu.device.queue.writes == []


def test_stamp_entity_without_gpu_is_noop():
    """If init_gpu was never called, stamp_entity must silently no-op."""
    world = CollisionWorld()
    entity = _make_entity_with_alpha(0.0, 0.0)
    # Must not raise
    world.stamp_entity(encoder=None, entity=entity, entity_idx=1)


def test_stamp_all_entities_clears_then_stamps():
    """stamp_all_entities should clear the mask once then stamp each collidable."""
    world = _make_world(32, 32)
    e1 = _make_entity_with_alpha(0.0, 0.0)
    e2 = _make_entity_with_alpha(16.0, 16.0)
    # Non-collidable entity (no shape) must be skipped
    e3 = Entity(name="ghost")
    e3.position = (4.0, 4.0)
    e3.collision_shape = None

    world.stamp_all_entities(encoder=None, entities=[e1, e3, e2])

    writes = world._gpu.device.queue.writes
    # 1 clear + 2 stamps = 3 writes
    assert len(writes) == 3
    # First write is the full-mask clear
    assert writes[0]["size"] == (32, 32, 1)
    clear_data = np.frombuffer(writes[0]["data"], dtype=np.uint32)
    assert (clear_data == 0).all()
    # Following writes carry entity ids 1 and 2 (in collidable order)
    stamp1 = np.frombuffer(writes[1]["data"], dtype=np.uint32)
    stamp2 = np.frombuffer(writes[2]["data"], dtype=np.uint32)
    assert stamp1.max() == 1
    assert stamp2.max() == 2
