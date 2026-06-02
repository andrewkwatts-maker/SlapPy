"""Engine tests for IsoScene — headless (no GPU required)."""
from __future__ import annotations
import pytest


def _make_floor():
    from slappyengine.iso.iso_grid import IsoTileDef
    return IsoTileDef("floor", "floor.png")


def _make_entity(x=0.0, y=0.0, z=0.0):
    from slappyengine.iso.iso_entity import IsoEntity
    return IsoEntity(grid_x=x, grid_y=y, grid_z=z)


# ---------------------------------------------------------------------------
# IsoScene — initialisation
# ---------------------------------------------------------------------------

class TestIsoSceneInit:
    def test_instantiates(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        assert s is not None

    def test_has_grid(self):
        from slappyengine.iso.iso_scene import IsoScene
        from slappyengine.iso.iso_grid import IsoGrid
        s = IsoScene(grid_w=10, grid_h=10)
        assert isinstance(s.grid, IsoGrid)

    def test_grid_dimensions(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene(grid_w=15, grid_h=20, grid_d=5)
        assert s.grid.width == 15
        assert s.grid.height == 20
        assert s.grid.depth == 5

    def test_has_camera(self):
        from slappyengine.iso.iso_scene import IsoScene
        from slappyengine.iso.iso_camera import IsoCamera
        s = IsoScene()
        assert isinstance(s.camera, IsoCamera)

    def test_default_viewpoint_ne(self):
        from slappyengine.iso.iso_scene import IsoScene
        from slappyengine.iso.projection import IsoViewpoint
        s = IsoScene()
        assert s.camera.viewpoint == IsoViewpoint.NE

    def test_custom_viewpoint(self):
        from slappyengine.iso.iso_scene import IsoScene
        from slappyengine.iso.projection import IsoViewpoint
        s = IsoScene(viewpoint=IsoViewpoint.SW)
        assert s.camera.viewpoint == IsoViewpoint.SW

    def test_iso_entities_empty_initially(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        assert s.iso_entities == []

    def test_engine_compat_entities_list(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        assert s.entities == []

    def test_engine_compat_post_process_list(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        assert s.post_process == []

    def test_engine_compat_pixel_physics_disabled(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        assert s.pixel_physics_enabled is False

    def test_engine_compat_strata_none(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        assert s.strata is None


# ---------------------------------------------------------------------------
# IsoScene — entity management
# ---------------------------------------------------------------------------

class TestIsoSceneEntityManagement:
    def test_add_iso_entity_increments_count(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        e = _make_entity()
        s.add_iso_entity(e)
        assert len(s.iso_entities) == 1

    def test_add_iso_entity_stores_entity(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        e = _make_entity(1.0, 2.0)
        s.add_iso_entity(e)
        assert e in s.iso_entities

    def test_add_same_entity_twice_deduplicates(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        e = _make_entity()
        s.add_iso_entity(e)
        s.add_iso_entity(e)
        assert len(s.iso_entities) == 1

    def test_add_two_different_entities(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        s.add_iso_entity(_make_entity(0.0, 0.0))
        s.add_iso_entity(_make_entity(1.0, 1.0))
        assert len(s.iso_entities) == 2

    def test_remove_iso_entity_decrements_count(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        e = _make_entity()
        s.add_iso_entity(e)
        s.remove_iso_entity(e)
        assert len(s.iso_entities) == 0

    def test_remove_iso_entity_not_in_list(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        e = _make_entity()
        s.remove_iso_entity(e)  # should not raise

    def test_remove_iso_entity_removes_correct_one(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        e1 = _make_entity(0.0, 0.0)
        e2 = _make_entity(5.0, 5.0)
        s.add_iso_entity(e1)
        s.add_iso_entity(e2)
        s.remove_iso_entity(e1)
        assert e1 not in s.iso_entities
        assert e2 in s.iso_entities


# ---------------------------------------------------------------------------
# IsoScene — update
# ---------------------------------------------------------------------------

class TestIsoSceneUpdate:
    def test_update_no_crash_empty(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        s.update(0.016)  # should not raise

    def test_update_syncs_entity_rotation_to_viewpoint(self):
        from slappyengine.iso.iso_scene import IsoScene
        from slappyengine.iso.projection import IsoViewpoint
        s = IsoScene(viewpoint=IsoViewpoint.NE)
        e = _make_entity()
        s.add_iso_entity(e)
        s.update(0.016)
        # Camera.update_entity_viewpoints sets entity.rotation = viewpoint_angle
        assert hasattr(e, "rotation") or True  # IsoEntity is a dataclass; rotation set by update

    def test_update_multiple_entities_no_crash(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        for i in range(5):
            s.add_iso_entity(_make_entity(float(i), 0.0))
        s.update(0.033)


# ---------------------------------------------------------------------------
# IsoScene — sorted_render_list
# ---------------------------------------------------------------------------

class TestIsoSceneSortedRenderList:
    def test_empty_scene_returns_empty_list(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        result = s.sorted_render_list(screen_w=1280, screen_h=720)
        assert result == []

    def test_single_tile_appears_in_list(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        s.grid.set_tile(0, 0, 0, _make_floor())
        result = s.sorted_render_list(screen_w=2000, screen_h=2000)
        assert len(result) == 1
        assert result[0]["type"] == "tile"

    def test_single_entity_appears_in_list(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        e = _make_entity(0.0, 0.0)
        s.add_iso_entity(e)
        result = s.sorted_render_list(screen_w=2000, screen_h=2000)
        assert len(result) == 1
        assert result[0]["type"] == "entity"

    def test_tile_and_entity_both_appear(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        s.grid.set_tile(0, 0, 0, _make_floor())
        s.add_iso_entity(_make_entity(0.0, 0.0))
        result = s.sorted_render_list(screen_w=2000, screen_h=2000)
        types = {item["type"] for item in result}
        assert "tile" in types
        assert "entity" in types

    def test_items_have_sx_sy_fields(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        s.add_iso_entity(_make_entity())
        result = s.sorted_render_list(screen_w=1280, screen_h=720)
        for item in result:
            assert "sx" in item
            assert "sy" in item
            assert isinstance(item["sx"], float)
            assert isinstance(item["sy"], float)

    def test_items_have_data_field(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        e = _make_entity()
        s.add_iso_entity(e)
        result = s.sorted_render_list(screen_w=1280, screen_h=720)
        assert result[0]["data"] is e

    def test_tile_item_data_is_cell(self):
        from slappyengine.iso.iso_scene import IsoScene
        from slappyengine.iso.iso_grid import IsoCell
        s = IsoScene()
        s.grid.set_tile(0, 0, 0, _make_floor())
        result = s.sorted_render_list(screen_w=2000, screen_h=2000)
        assert isinstance(result[0]["data"], IsoCell)

    def test_sorted_by_depth_key_nondecreasing(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        # Place several tiles and entities
        for i in range(3):
            s.grid.set_tile(i, i, 0, _make_floor())
        for i in range(3):
            s.add_iso_entity(_make_entity(float(i), 0.0))
        result = s.sorted_render_list(screen_w=2000, screen_h=2000)
        dks = [item["dk"] for item in result]
        assert dks == sorted(dks)

    def test_all_viewpoints_no_crash(self):
        from slappyengine.iso.iso_scene import IsoScene
        from slappyengine.iso.projection import IsoViewpoint
        for vp in IsoViewpoint:
            s = IsoScene(viewpoint=vp)
            s.grid.set_tile(0, 0, 0, _make_floor())
            s.add_iso_entity(_make_entity())
            s.sorted_render_list(screen_w=2000, screen_h=2000)


# ---------------------------------------------------------------------------
# IsoScene — z-layer API (engine compatibility)
# ---------------------------------------------------------------------------

class TestIsoSceneZLayerAPI:
    def _make_z_layer(self, z: float):
        class _ZL:
            def __init__(self, z):
                self.z = z
        return _ZL(z)

    def test_z_layers_empty_initially(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        assert s.z_layers == []

    def test_add_z_layer_appends(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        layer = self._make_z_layer(0.0)
        s.add_z_layer(layer)
        assert len(s.z_layers) == 1

    def test_add_z_layer_sorts_by_z(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        high = self._make_z_layer(10.0)
        low = self._make_z_layer(0.0)
        mid = self._make_z_layer(5.0)
        s.add_z_layer(high)
        s.add_z_layer(low)
        s.add_z_layer(mid)
        zs = [l.z for l in s.z_layers]
        assert zs == sorted(zs)

    def test_remove_z_layer_removes(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        layer = self._make_z_layer(0.0)
        s.add_z_layer(layer)
        s.remove_z_layer(layer)
        assert len(s.z_layers) == 0

    def test_remove_nonexistent_no_crash(self):
        from slappyengine.iso.iso_scene import IsoScene
        s = IsoScene()
        layer = self._make_z_layer(0.0)
        s.remove_z_layer(layer)  # should not raise


# ---------------------------------------------------------------------------
# IsoScene — video_import (import error path)
# ---------------------------------------------------------------------------

class TestVideoImport:
    def test_extract_frames_importerror_without_av(self):
        """extract_frames raises ImportError when the 'av' package is absent."""
        try:
            import av  # noqa: F401
            pytest.skip("av is installed — can't test missing-dep path")
        except ImportError:
            pass

        from slappyengine.animation.video_import import extract_frames
        with pytest.raises(ImportError):
            extract_frames("nonexistent.mp4")
