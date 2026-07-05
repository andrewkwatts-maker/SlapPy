"""Tests for slappyengine.render.scene_walker — JJ5 Nova3D parity.

Covers:
* EntityDrawInfo composition (mesh_ref, prefab_ref, defaults).
* Transform matrix composition (T · R · S).
* Frustum culling in and out.
* Renderer submission counts on NullRenderer.
* AssetCache hit / miss / TTL / invalidate.
* RenderStats population.
* Empty scene / missing prefab safety.
* App bridge helper.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pytest

from slappyengine.render import NullRenderer
from slappyengine.render.camera import Camera3D
from slappyengine.render.light import Light
from slappyengine.render.material import Material
from slappyengine.render.mesh import Mesh, cube
from slappyengine.render.scene_walker import (
    AssetCache,
    EntityDrawInfo,
    Frustum,
    RenderStats,
    SceneWalker,
    _compose_trs,
    _euler_to_quat,
    _normalise_position,
    _normalise_rotation,
    _normalise_scale,
    bridge_render_scene,
    render_scene,
)
from slappyengine.scenes.scene import Scene


# ----------------------------------------------------------------------
# Fixtures / helpers
# ----------------------------------------------------------------------


@dataclass
class _FakePrefab:
    name: str
    mesh: Mesh | None = None


class _FakePrefabLibrary:
    """Minimal drop-in for :class:`PrefabLibrary` — get() by name only."""

    def __init__(self) -> None:
        self._entries: dict[str, _FakePrefab] = {}

    def register(self, prefab: _FakePrefab) -> None:
        self._entries[prefab.name] = prefab

    def get(self, name: str) -> _FakePrefab | None:
        return self._entries.get(name)


def _open_null() -> NullRenderer:
    r = NullRenderer()
    r.begin_frame()
    return r


def _tri_mesh() -> Mesh:
    v = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]],
        dtype=np.float32,
    )
    i = np.array([[0, 1, 2]], dtype=np.uint32)
    return Mesh(vertices=v, indices=i)


def _scene_with(entities: list[dict[str, Any]]) -> Scene:
    scene = Scene(name="test")
    for e in entities:
        scene.add_entity(e)
    return scene


# ----------------------------------------------------------------------
# EntityDrawInfo / defaults
# ----------------------------------------------------------------------


def test_entity_draw_info_default_material():
    info = EntityDrawInfo(
        entity_id="e1",
        mesh=None,
        material=Material(),
        transform_matrix=np.eye(4, dtype=np.float32),
    )
    assert info.entity_id == "e1"
    assert info.visible is True
    assert info.bounding_box[0] == (0.0, 0.0, 0.0)


def test_scene_walker_rejects_none_scene():
    with pytest.raises(TypeError):
        SceneWalker(None)  # type: ignore[arg-type]


def test_scene_walker_rejects_non_scene():
    class NotAScene:
        pass

    with pytest.raises(TypeError):
        SceneWalker(NotAScene())  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# resolve_entity paths
# ----------------------------------------------------------------------


def test_resolve_entity_inline_mesh_ref_default():
    """kind == 'box' has no mesh_path but falls back to default_mesh."""
    scene = _scene_with([
        {"id": "e0", "kind": "box", "position": [0.0, 0.0],
         "params": {"width": 1.0, "height": 1.0}},
    ])
    walker = SceneWalker(scene)
    info = walker.resolve_entity(scene.entities[0])
    assert info is not None
    assert info.entity_id == "e0"
    assert info.mesh is walker._default_mesh
    assert info.visible is True


def test_resolve_entity_mesh_ref_with_inline_mesh_object():
    """params['mesh'] passthrough — no asset_import call needed."""
    mesh = _tri_mesh()
    scene = Scene(name="s")
    scene.add_entity({
        "id": "e0", "kind": "point",
        "position": [1.0, 2.0], "params": {"mesh": mesh},
    })
    walker = SceneWalker(scene)
    info = walker.resolve_entity(scene.entities[0])
    assert info is not None
    assert info.mesh is mesh


def test_resolve_entity_prefab_ref(caplog):
    """prefab_ref resolves through the library — mesh from prefab wins."""
    lib = _FakePrefabLibrary()
    lib.register(_FakePrefab(name="rocket", mesh=_tri_mesh()))
    scene = Scene(name="s")
    scene.add_entity({
        "id": "e0", "kind": "point",
        "position": [0.0, 0.0], "params": {},
        "prefab_ref": "rocket",
    })
    walker = SceneWalker(scene, prefab_library=lib)
    info = walker.resolve_entity(scene.entities[0])
    assert info is not None
    assert info.mesh is not None
    assert int(info.mesh.indices.shape[0]) == 1


def test_resolve_entity_prefab_ref_missing_warn(caplog):
    """Unknown prefab_ref → warns and returns None (entity skipped)."""
    lib = _FakePrefabLibrary()
    scene = Scene(name="s")
    scene.add_entity({
        "id": "gone", "kind": "point",
        "position": [0.0, 0.0], "params": {},
        "prefab_ref": "nope",
    })
    walker = SceneWalker(scene, prefab_library=lib)
    with caplog.at_level(logging.WARNING):
        info = walker.resolve_entity(scene.entities[0])
    assert info is None
    assert any("nope" in rec.message for rec in caplog.records)


def test_resolve_entity_prefab_ref_no_library(caplog):
    """prefab_ref set but no library → warn + skip."""
    scene = Scene(name="s")
    scene.add_entity({
        "id": "orphan", "kind": "point",
        "position": [0.0, 0.0], "params": {},
        "prefab_ref": "rocket",
    })
    walker = SceneWalker(scene)  # no prefab_library
    with caplog.at_level(logging.WARNING):
        info = walker.resolve_entity(scene.entities[0])
    assert info is None


def test_resolve_entity_non_dict_returns_none(caplog):
    walker = SceneWalker(Scene(name="s"))
    with caplog.at_level(logging.WARNING):
        assert walker.resolve_entity("not a dict") is None  # type: ignore[arg-type]


def test_resolve_entity_visibility_false():
    scene = _scene_with([
        {"id": "hidden", "kind": "point",
         "position": [0.0, 0.0], "params": {"visible": False}},
    ])
    walker = SceneWalker(scene)
    info = walker.resolve_entity(scene.entities[0])
    assert info is not None
    assert info.visible is False


# ----------------------------------------------------------------------
# Transform composition
# ----------------------------------------------------------------------


def test_compose_trs_identity():
    m = _compose_trs((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
    np.testing.assert_allclose(m, np.eye(4, dtype=np.float32), atol=1e-6)


def test_compose_trs_translation():
    m = _compose_trs((3.0, 4.0, 5.0), (0.0, 0.0, 0.0, 1.0), (1.0, 1.0, 1.0))
    assert m[0, 3] == pytest.approx(3.0)
    assert m[1, 3] == pytest.approx(4.0)
    assert m[2, 3] == pytest.approx(5.0)


def test_compose_trs_uniform_scale_only():
    m = _compose_trs((0.0, 0.0, 0.0), (0.0, 0.0, 0.0, 1.0), (2.0, 3.0, 4.0))
    assert m[0, 0] == pytest.approx(2.0)
    assert m[1, 1] == pytest.approx(3.0)
    assert m[2, 2] == pytest.approx(4.0)


def test_compose_trs_order_is_TRS():
    """M = T · R · S: rotate (1,0,0), scale x by 2, translate (10,0,0).
    Point (1,0,0) → scale gives (2,0,0) → rotate about z 90° → (0,2,0)
    → translate → (10,2,0).
    """
    theta = math.pi / 2.0
    q = (0.0, 0.0, math.sin(theta / 2.0), math.cos(theta / 2.0))
    m = _compose_trs((10.0, 0.0, 0.0), q, (2.0, 1.0, 1.0))
    p = np.array([1.0, 0.0, 0.0, 1.0], dtype=np.float32)
    out = m @ p
    assert out[0] == pytest.approx(10.0, abs=1e-5)
    assert out[1] == pytest.approx(2.0, abs=1e-5)


def test_normalise_position_2d_pads_z():
    assert _normalise_position([1.0, 2.0]) == (1.0, 2.0, 0.0)


def test_normalise_position_3d_pass():
    assert _normalise_position([1.0, 2.0, 3.0]) == (1.0, 2.0, 3.0)


def test_normalise_rotation_scalar_is_z_quat():
    q = _normalise_rotation(math.pi)
    assert q[0] == pytest.approx(0.0)
    assert q[1] == pytest.approx(0.0)
    assert q[2] == pytest.approx(1.0, abs=1e-6)
    assert q[3] == pytest.approx(0.0, abs=1e-6)


def test_normalise_rotation_euler_3seq():
    q = _euler_to_quat((0.0, 0.0, 0.0))
    assert q == (0.0, 0.0, 0.0, 1.0)


def test_normalise_scale_uniform_scalar():
    assert _normalise_scale(2.5) == (2.5, 2.5, 2.5)


# ----------------------------------------------------------------------
# Frustum
# ----------------------------------------------------------------------


def test_frustum_from_camera_shape():
    cam = Camera3D()
    f = Frustum.from_camera(cam)
    assert f.planes.shape == (6, 4)


def test_frustum_rejects_non_camera():
    with pytest.raises(TypeError):
        Frustum.from_camera(42)  # type: ignore[arg-type]


def test_frustum_rejects_bad_matrix_shape():
    with pytest.raises(ValueError):
        Frustum.from_camera(np.eye(3, dtype=np.float32))


def test_frustum_origin_inside_default_camera():
    """Default Camera3D looks at origin from (0,0,5) — origin AABB is inside."""
    cam = Camera3D()
    f = Frustum.from_camera(cam)
    assert f.intersects_aabb(((-0.5, -0.5, -0.5), (0.5, 0.5, 0.5))) is True


def test_frustum_behind_camera_is_culled():
    cam = Camera3D()  # eye at (0,0,5) looking at origin (−z direction)
    f = Frustum.from_camera(cam)
    # An AABB well behind the camera should fail the near-plane test.
    assert f.intersects_aabb(((-0.5, -0.5, 20.0), (0.5, 0.5, 21.0))) is False


def test_frustum_far_side_culled():
    cam = Camera3D(far=10.0)
    f = Frustum.from_camera(cam)
    # AABB far past the far plane (in front of camera in −z direction).
    assert f.intersects_aabb(((-0.5, -0.5, -100.0), (0.5, 0.5, -99.0))) is False


def test_frustum_off_to_side_culled():
    cam = Camera3D()
    f = Frustum.from_camera(cam)
    # Way off to the right in world space.
    assert f.intersects_aabb(((100.0, -0.5, -0.5), (101.0, 0.5, 0.5))) is False


# ----------------------------------------------------------------------
# walk()
# ----------------------------------------------------------------------


def test_walk_empty_scene():
    scene = Scene(name="empty")
    walker = SceneWalker(scene)
    r = _open_null()
    stats = walker.walk(r, Camera3D())
    r.end_frame()
    assert stats.entities_walked == 0
    assert stats.draw_calls == 0
    assert len(r.calls_of("mesh")) == 0


def test_walk_submits_one_mesh_per_visible_entity():
    scene = _scene_with([
        {"id": f"e{i}", "kind": "point", "position": [0.0, 0.0], "params": {}}
        for i in range(3)
    ])
    walker = SceneWalker(scene)
    r = _open_null()
    stats = walker.walk(r, Camera3D())
    r.end_frame()
    assert stats.entities_walked == 3
    assert stats.draw_calls == 3
    assert len(r.calls_of("mesh")) == 3


def test_walk_frustum_culls_far_entity():
    scene = _scene_with([
        {"id": "near", "kind": "point", "position": [0.0, 0.0], "params": {}},
        # 500m off to the side — outside the FOV.
        {"id": "far", "kind": "point", "position": [500.0, 0.0], "params": {}},
    ])
    walker = SceneWalker(scene)
    r = _open_null()
    stats = walker.walk(r, Camera3D())
    r.end_frame()
    assert stats.entities_walked == 2
    assert stats.entities_culled == 1
    assert stats.draw_calls == 1


def test_walk_no_camera_disables_culling():
    """Passing camera=None must not cull anything on the frustum test."""
    scene = _scene_with([
        {"id": "far", "kind": "point", "position": [999.0, 999.0], "params": {}},
    ])
    walker = SceneWalker(scene)
    r = _open_null()
    stats = walker.walk(r, None)
    r.end_frame()
    assert stats.draw_calls == 1


def test_walk_invisible_entity_skipped():
    scene = _scene_with([
        {"id": "vis", "kind": "point", "position": [0.0, 0.0], "params": {}},
        {"id": "hidden", "kind": "point", "position": [0.0, 0.0],
         "params": {"visible": False}},
    ])
    walker = SceneWalker(scene)
    r = _open_null()
    stats = walker.walk(r, Camera3D())
    r.end_frame()
    assert stats.entities_walked == 2
    assert stats.draw_calls == 1


def test_walk_rejects_renderer_without_submit_mesh():
    scene = Scene(name="s")
    walker = SceneWalker(scene)

    class NoSubmit:
        pass

    with pytest.raises(TypeError):
        walker.walk(NoSubmit(), None)


def test_walk_rejects_none_renderer():
    with pytest.raises(TypeError):
        SceneWalker(Scene(name="s")).walk(None, None)


def test_walk_stats_populated_wall_ms():
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0], "params": {}},
    ])
    walker = SceneWalker(scene)
    r = _open_null()
    stats = walker.walk(r, Camera3D())
    r.end_frame()
    assert stats.wall_ms >= 0.0


def test_walk_pushes_camera_to_renderer():
    scene = Scene(name="s")
    walker = SceneWalker(scene)
    r = _open_null()
    walker.walk(r, Camera3D())
    r.end_frame()
    assert len(r.calls_of("camera")) >= 1


# ----------------------------------------------------------------------
# walk_with_lights
# ----------------------------------------------------------------------


def test_walk_with_lights_submits_lights_before_meshes():
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0], "params": {}},
    ])
    walker = SceneWalker(scene)
    r = _open_null()
    lights = [Light(kind="directional", color=(1.0, 1.0, 1.0))]
    walker.walk_with_lights(r, Camera3D(), lights)
    r.end_frame()
    kinds = [c.kind for c in r.draw_log]
    lights_idx = kinds.index("lights")
    mesh_idx = kinds.index("mesh")
    assert lights_idx < mesh_idx


def test_walk_with_lights_none_lights_skipped():
    scene = Scene(name="s")
    walker = SceneWalker(scene)
    r = _open_null()
    walker.walk_with_lights(r, Camera3D(), None)
    r.end_frame()
    assert len(r.calls_of("lights")) == 0


def test_walk_with_lights_rejects_none_renderer():
    with pytest.raises(TypeError):
        SceneWalker(Scene(name="s")).walk_with_lights(None, None, None)


# ----------------------------------------------------------------------
# AssetCache
# ----------------------------------------------------------------------


def test_asset_cache_hit_miss_counts():
    cache = AssetCache()
    assert cache.get("a") is None
    assert cache.misses == 1
    m = _tri_mesh()
    cache.put("a", m)
    assert cache.get("a") is m
    assert cache.hits == 1
    assert len(cache) == 1


def test_asset_cache_ttl_expiry():
    cache = AssetCache(default_ttl_seconds=1.0)
    now = 100.0
    cache.put("a", _tri_mesh(), now=now)
    assert cache.get("a", now=now + 0.5) is not None
    assert cache.get("a", now=now + 2.0) is None


def test_asset_cache_invalidate_one():
    cache = AssetCache()
    cache.put("a", _tri_mesh())
    cache.put("b", _tri_mesh())
    cache.invalidate("a")
    assert cache.get("a") is None
    assert cache.get("b") is not None


def test_asset_cache_invalidate_all():
    cache = AssetCache()
    cache.put("a", _tri_mesh())
    cache.put("b", _tri_mesh())
    cache.invalidate()
    assert len(cache) == 0


def test_asset_cache_rejects_bad_ttl():
    with pytest.raises(ValueError):
        AssetCache(default_ttl_seconds=0.0)
    with pytest.raises(TypeError):
        AssetCache(default_ttl_seconds="oops")  # type: ignore[arg-type]


def test_asset_cache_ignores_empty_path():
    cache = AssetCache()
    cache.put("", _tri_mesh())
    assert cache.get("") is None


def test_scene_walker_reuses_cached_mesh_from_path(monkeypatch):
    """Second entity with same mesh_path must NOT re-invoke import_asset.

    We attach the mesh_ref entities directly to ``scene.entities`` because
    FF3's :meth:`Scene.add_entity` rejects unknown kinds without a prefab
    ref. The walker still consumes them from the same list.
    """
    from dataclasses import dataclass as _dc

    call_count = {"n": 0}

    @_dc
    class _Result:
        primary_mesh: Any

    def _fake_import(path):
        call_count["n"] += 1
        return _Result(primary_mesh=_tri_mesh())

    import slappyengine.render.scene_walker as scene_walker

    def _fake_dispatch(mesh_path):
        return _fake_import(mesh_path)

    def _fake_resolve(self, mesh_path):
        cached = self.asset_cache.get(mesh_path)
        if cached is not None:
            return cached
        res = _fake_dispatch(mesh_path)
        mesh = res.primary_mesh
        self.asset_cache.put(mesh_path, mesh)
        return mesh

    monkeypatch.setattr(
        scene_walker.SceneWalker, "_resolve_mesh_from_path", _fake_resolve,
    )

    scene = Scene(name="cache-test")
    scene.entities.extend([
        {"id": "a", "kind": "mesh_ref", "position": [0.0, 0.0],
         "params": {"mesh_path": "foo.obj"}},
        {"id": "b", "kind": "mesh_ref", "position": [1.0, 0.0],
         "params": {"mesh_path": "foo.obj"}},
    ])
    walker = SceneWalker(scene)
    walker.resolve_entity(scene.entities[0])
    walker.resolve_entity(scene.entities[1])
    assert call_count["n"] == 1


# ----------------------------------------------------------------------
# render_scene convenience
# ----------------------------------------------------------------------


def test_render_scene_convenience_opens_frame():
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0], "params": {}},
    ])
    r = NullRenderer()
    stats = render_scene(scene, r, Camera3D())
    assert stats.draw_calls == 1
    # begin_frame + end_frame both fired
    assert len(r.calls_of("clear")) == 1
    assert r.frame_count == 1


def test_render_scene_rejects_none_scene():
    with pytest.raises(TypeError):
        render_scene(None, NullRenderer(), None)  # type: ignore[arg-type]


def test_render_scene_rejects_none_renderer():
    with pytest.raises(TypeError):
        render_scene(Scene(name="s"), None, None)  # type: ignore[arg-type]


def test_render_scene_with_lights():
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0], "params": {}},
    ])
    r = NullRenderer()
    lights = [Light(kind="ambient", color=(0.2, 0.2, 0.2))]
    stats = render_scene(scene, r, Camera3D(), lights=lights)
    assert stats.draw_calls == 1


# ----------------------------------------------------------------------
# bridge_render_scene
# ----------------------------------------------------------------------


class _FakeApp:
    def __init__(self) -> None:
        self.camera = Camera3D()
        self.lights = None
        self.prefab_library = None
        self.asset_cache = None


def test_bridge_render_scene_uses_app_camera():
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0], "params": {}},
    ])
    app = _FakeApp()
    r = NullRenderer()
    stats = bridge_render_scene(app, scene, r)
    assert stats.draw_calls == 1


def test_bridge_render_scene_rejects_none_scene():
    with pytest.raises(TypeError):
        bridge_render_scene(_FakeApp(), None, NullRenderer())  # type: ignore[arg-type]


def test_bridge_render_scene_rejects_none_renderer():
    with pytest.raises(TypeError):
        bridge_render_scene(_FakeApp(), Scene(name="s"), None)  # type: ignore[arg-type]


def test_bridge_render_scene_camera_override():
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0], "params": {}},
    ])
    app = _FakeApp()
    app.camera = None  # would blow if bridge used it blindly
    r = NullRenderer()
    stats = bridge_render_scene(app, scene, r, camera=Camera3D())
    assert stats.draw_calls == 1


# ----------------------------------------------------------------------
# Material registry
# ----------------------------------------------------------------------


def test_material_registry_lookup():
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0],
         "params": {"material_id": "red"}},
    ])
    walker = SceneWalker(scene)
    red = Material(name="red", base_color=(1.0, 0.0, 0.0, 1.0))
    walker.register_material("red", red)
    info = walker.resolve_entity(scene.entities[0])
    assert info is not None
    assert info.material.name == "red"


def test_material_inline_override():
    """params['material'] should win over registry lookup."""
    mat = Material(name="inline", base_color=(0.0, 1.0, 0.0, 1.0))
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0],
         "params": {"material": mat}},
    ])
    walker = SceneWalker(scene)
    info = walker.resolve_entity(scene.entities[0])
    assert info is not None
    assert info.material is mat


# ----------------------------------------------------------------------
# RenderStats
# ----------------------------------------------------------------------


def test_render_stats_defaults():
    s = RenderStats()
    assert s.entities_walked == 0
    assert s.entities_culled == 0
    assert s.draw_calls == 0
    assert s.wall_ms == 0.0


def test_render_stats_reused_across_walks():
    scene = _scene_with([
        {"id": "e0", "kind": "point", "position": [0.0, 0.0], "params": {}},
    ])
    walker = SceneWalker(scene)
    stats = RenderStats()
    r = _open_null()
    walker.walk(r, Camera3D(), stats=stats)
    r.end_frame()
    r2 = _open_null()
    walker.walk(r2, Camera3D(), stats=stats)
    r2.end_frame()
    # Accumulates because caller reused the same stats object.
    assert stats.entities_walked == 2
    assert stats.draw_calls == 2
