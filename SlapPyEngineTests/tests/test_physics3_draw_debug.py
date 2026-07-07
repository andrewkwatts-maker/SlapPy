"""Tests for World3D.draw_debug + debug_stats — QQ7.

Coverage:
* draw_debug on empty world returns zeros.
* draw_debug(show_aabbs=True) on a 3-body world emits 3*12 = 36 lines.
* draw_debug(show_bvh_nodes=True) after build_bvh on a 10-body world
  produces at least one bvh_nodes_drawn.
* max_bvh_depth caps the traversal.
* draw_debug(renderer=None) raises TypeError.
* debug_stats returns the expected shape (body_count / bvh_built /
  bvh_dirty / bvh_depth).
* Uses a headless null-renderer with a ``draw_log`` list so no GPU is
  required.
"""
from __future__ import annotations

import pytest

from slappyengine.physics3_bridge import Body3D, World3D


# ---------------------------------------------------------------------------
# Null renderer — mirrors the pattern used elsewhere in the SlapPyEngine
# test suite: an object with just a ``draw_log`` list is enough to
# capture every debug primitive.
# ---------------------------------------------------------------------------


class _NullRenderer:
    """Minimal headless-safe renderer.

    ``draw_debug`` will detect the missing ``draw_line`` method and
    fall back on ``draw_log.append`` — exactly the shape we want to
    exercise here.
    """

    def __init__(self) -> None:
        self.draw_log: list[dict] = []


class _CallbackRenderer:
    """Renderer variant that exposes ``draw_line`` directly."""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple, tuple, tuple]] = []

    def draw_line(self, p0, p1, color) -> None:
        self.calls.append((p0, p1, color))


def _make_box_body(pos=(0.0, 0.0, 0.0), he=(0.5, 0.5, 0.5)) -> Body3D:
    return Body3D(
        position=pos,
        mass=1.0,
        shape_kind="box",
        shape_params={"half_extents": he},
    )


# ---------------------------------------------------------------------------
# draw_debug
# ---------------------------------------------------------------------------


def test_draw_debug_empty_world_returns_zeros() -> None:
    world = World3D(backend="fallback")
    r = _NullRenderer()
    stats = world.draw_debug(r)
    assert stats == {
        "aabbs_drawn": 0,
        "bvh_nodes_drawn": 0,
        "line_count": 0,
    }
    assert r.draw_log == []


def test_draw_debug_three_bodies_emits_36_lines() -> None:
    """3 bodies * 12 edges per box = 36 debug_line records."""
    world = World3D(backend="fallback")
    world.add_body(_make_box_body(pos=(0.0, 0.0, 0.0)))
    world.add_body(_make_box_body(pos=(5.0, 0.0, 0.0)))
    world.add_body(_make_box_body(pos=(0.0, 5.0, 0.0)))
    r = _NullRenderer()
    stats = world.draw_debug(r, show_aabbs=True, show_bvh_nodes=False)
    assert stats["aabbs_drawn"] == 3
    assert stats["bvh_nodes_drawn"] == 0
    assert stats["line_count"] == 36
    assert len(r.draw_log) == 36
    # Every record has the debug_line kind + a 4-tuple colour.
    for record in r.draw_log:
        assert record["kind"] == "debug_line"
        assert len(record["p0"]) == 3
        assert len(record["p1"]) == 3
        assert len(record["color"]) == 4


def test_draw_debug_show_bvh_nodes_after_build() -> None:
    """After build_bvh, show_bvh_nodes emits at least one node box."""
    world = World3D(backend="fallback")
    for i in range(10):
        world.add_body(_make_box_body(pos=(float(i * 3), 0.0, 0.0)))
    world.build_bvh()
    r = _NullRenderer()
    stats = world.draw_debug(r, show_aabbs=False, show_bvh_nodes=True)
    assert stats["aabbs_drawn"] == 0
    assert stats["bvh_nodes_drawn"] > 0
    assert stats["line_count"] == 12 * stats["bvh_nodes_drawn"]
    assert len(r.draw_log) == stats["line_count"]


def test_draw_debug_bvh_without_build_is_noop() -> None:
    """When the BVH has never been built, show_bvh_nodes stays a no-op."""
    world = World3D(backend="fallback")
    world.add_body(_make_box_body(pos=(0.0, 0.0, 0.0)))
    r = _NullRenderer()
    stats = world.draw_debug(r, show_aabbs=False, show_bvh_nodes=True)
    assert stats["bvh_nodes_drawn"] == 0


def test_draw_debug_max_bvh_depth_limits_traversal() -> None:
    """max_bvh_depth=1 must emit strictly fewer nodes than the full walk."""
    world = World3D(backend="fallback")
    # Enough bodies to guarantee an internal node exists in the SAH tree.
    for i in range(20):
        world.add_body(
            _make_box_body(
                pos=(float(i * 3), float((i % 4) * 3), float((i % 3) * 3))
            )
        )
    world.build_bvh()
    r_full = _NullRenderer()
    full = world.draw_debug(
        r_full, show_aabbs=False, show_bvh_nodes=True
    )
    r_capped = _NullRenderer()
    capped = world.draw_debug(
        r_capped, show_aabbs=False, show_bvh_nodes=True, max_bvh_depth=1
    )
    r_root = _NullRenderer()
    root_only = world.draw_debug(
        r_root, show_aabbs=False, show_bvh_nodes=True, max_bvh_depth=0
    )
    assert full["bvh_nodes_drawn"] > capped["bvh_nodes_drawn"]
    assert capped["bvh_nodes_drawn"] >= root_only["bvh_nodes_drawn"]
    # Depth 0 draws exactly the root node (1 box).
    assert root_only["bvh_nodes_drawn"] == 1


def test_draw_debug_both_aabbs_and_bvh() -> None:
    world = World3D(backend="fallback")
    for i in range(6):
        world.add_body(_make_box_body(pos=(float(i * 2), 0.0, 0.0)))
    world.build_bvh()
    r = _NullRenderer()
    stats = world.draw_debug(
        r, show_aabbs=True, show_bvh_nodes=True
    )
    assert stats["aabbs_drawn"] == 6
    assert stats["bvh_nodes_drawn"] >= 1
    expected_lines = 12 * (stats["aabbs_drawn"] + stats["bvh_nodes_drawn"])
    assert stats["line_count"] == expected_lines
    assert len(r.draw_log) == expected_lines


def test_draw_debug_callback_renderer_path() -> None:
    """When the renderer exposes draw_line, that path is used instead."""
    world = World3D(backend="fallback")
    world.add_body(_make_box_body(pos=(0.0, 0.0, 0.0)))
    r = _CallbackRenderer()
    stats = world.draw_debug(r)
    assert stats["aabbs_drawn"] == 1
    assert stats["line_count"] == 12
    assert len(r.calls) == 12
    # Colour propagated verbatim.
    _, _, color = r.calls[0]
    assert color == (0.2, 1.0, 0.2, 1.0)


def test_draw_debug_none_renderer_raises_type_error() -> None:
    world = World3D(backend="fallback")
    with pytest.raises(TypeError):
        world.draw_debug(None)


def test_draw_debug_renderer_missing_surface_raises() -> None:
    """A renderer with neither draw_line nor draw_log must fail loudly."""
    world = World3D(backend="fallback")
    world.add_body(_make_box_body())

    class _Dummy:
        pass

    with pytest.raises(TypeError):
        world.draw_debug(_Dummy())


def test_draw_debug_box_edges_span_min_and_max() -> None:
    """Sanity-check that the 12 emitted edges actually touch every corner."""
    world = World3D(backend="fallback")
    world.add_body(_make_box_body(pos=(0.0, 0.0, 0.0), he=(1.0, 2.0, 3.0)))
    r = _NullRenderer()
    world.draw_debug(r)
    corners = set()
    for record in r.draw_log:
        corners.add(record["p0"])
        corners.add(record["p1"])
    # A cube has 8 distinct corners.
    assert len(corners) == 8


# ---------------------------------------------------------------------------
# debug_stats
# ---------------------------------------------------------------------------


def test_debug_stats_empty_world_shape() -> None:
    world = World3D(backend="fallback")
    stats = world.debug_stats()
    assert stats["body_count"] == 0
    assert stats["bvh_built"] is False
    assert stats["bvh_dirty"] is True
    assert stats["bvh_depth"] is None
    assert set(stats.keys()) == {
        "body_count", "bvh_built", "bvh_dirty", "bvh_depth"
    }


def test_debug_stats_reflects_body_count_and_bvh_state() -> None:
    world = World3D(backend="fallback")
    for i in range(5):
        world.add_body(_make_box_body(pos=(float(i * 2), 0.0, 0.0)))
    before = world.debug_stats()
    assert before["body_count"] == 5
    assert before["bvh_built"] is False
    assert before["bvh_dirty"] is True

    world.build_bvh()
    after = world.debug_stats()
    assert after["body_count"] == 5
    assert after["bvh_built"] is True
    assert after["bvh_dirty"] is False
    assert isinstance(after["bvh_depth"], int)
    assert after["bvh_depth"] >= 0


def test_debug_stats_dirty_after_add_body_post_build() -> None:
    world = World3D(backend="fallback")
    for i in range(3):
        world.add_body(_make_box_body(pos=(float(i * 2), 0.0, 0.0)))
    world.build_bvh()
    assert world.debug_stats()["bvh_dirty"] is False
    world.add_body(_make_box_body(pos=(100.0, 0.0, 0.0)))
    # BVH object still cached but should be flagged dirty.
    stats = world.debug_stats()
    assert stats["bvh_dirty"] is True
    assert stats["bvh_built"] is True
    assert stats["body_count"] == 4
