"""Engine tests for gpu/sdf_extruder.py, ui/hud_widgets.py, ui/html_overlay.py,
and ui/project_manager.py — all headless (no GPU required for tests here).
"""
from __future__ import annotations
import pytest
import numpy as np


# ---------------------------------------------------------------------------
# SdfExtruder — CPU fallback
# ---------------------------------------------------------------------------

class TestSdfExtruderInit:
    def test_instantiates(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        assert ext is not None

    def test_gpu_none_by_default(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        assert ext._gpu is None


class TestSdfExtruderCpuExtrude:
    def _solid_8x8(self):
        """8×8 fully-opaque mask (all pixels solid)."""
        return np.ones((8, 8), dtype=np.float32)

    def _empty_8x8(self):
        return np.zeros((8, 8), dtype=np.float32)

    def _border_mask(self):
        """Only the border row/column is solid."""
        m = np.zeros((8, 8), dtype=np.float32)
        m[0, :] = 1.0
        m[7, :] = 1.0
        m[:, 0] = 1.0
        m[:, 7] = 1.0
        return m

    def test_extrude_returns_mesh(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        from pharos_engine.gpu.mesh import GpuMesh
        ext = SdfExtruder()
        mesh = ext.extrude(self._solid_8x8())
        assert isinstance(mesh, GpuMesh)

    def test_empty_mask_produces_no_vertices(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        mesh = ext.extrude(self._empty_8x8())
        assert mesh.vertex_count == 0

    def test_solid_mask_produces_vertices(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        mesh = ext.extrude(self._solid_8x8())
        assert mesh.vertex_count > 0

    def test_solid_mask_produces_indices(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        mesh = ext.extrude(self._solid_8x8())
        assert mesh.index_count > 0

    def test_indices_multiple_of_3(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        mesh = ext.extrude(self._solid_8x8())
        assert mesh.index_count % 3 == 0

    def test_uint8_mask_accepted(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        from pharos_engine.gpu.mesh import GpuMesh
        mask = np.full((4, 4), 255, dtype=np.uint8)
        ext = SdfExtruder()
        mesh = ext.extrude(mask)
        assert isinstance(mesh, GpuMesh)

    def test_rgba_mask_uses_alpha_channel(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        # RGBA where only alpha matters
        mask = np.zeros((4, 4, 4), dtype=np.float32)
        mask[:, :, 3] = 1.0  # alpha = 1.0 → solid
        ext = SdfExtruder()
        mesh = ext.extrude(mask)
        assert mesh.vertex_count > 0

    def test_threshold_affects_result(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        mask = np.full((4, 4), 0.3, dtype=np.float32)
        ext = SdfExtruder()
        # threshold=0.5: all pixels below → empty mesh
        mesh_high = ext.extrude(mask, threshold=0.5)
        # threshold=0.1: all pixels above → solid mesh
        mesh_low = ext.extrude(mask, threshold=0.1)
        assert mesh_high.vertex_count == 0
        assert mesh_low.vertex_count > 0

    def test_depth_parameter_no_crash(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        mesh = ext.extrude(self._solid_8x8(), depth=2.0)
        assert mesh is not None

    def test_scale_parameter_no_crash(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        mesh = ext.extrude(self._solid_8x8(), scale=0.1)
        assert mesh is not None

    def test_border_mask_produces_fewer_verts_than_solid(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        solid = ext.extrude(self._solid_8x8())
        border = ext.extrude(self._border_mask())
        # Border has fewer solid pixels → fewer interior faces
        assert solid.vertex_count > border.vertex_count

    def test_1d_mask_no_crash(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        mask = np.ones((8,), dtype=np.float32)
        ext = SdfExtruder()
        mesh = ext.extrude(mask)
        assert mesh is not None

    def test_vertex_bytes_length_consistent(self):
        from pharos_engine.gpu.sdf_extruder import SdfExtruder
        ext = SdfExtruder()
        mesh = ext.extrude(self._solid_8x8())
        assert len(mesh.vertex_bytes()) == mesh.vertex_count * 48


# ---------------------------------------------------------------------------
# ui/hud_widgets.py — draw_stat_bar (uses a mock PIL draw)
# ---------------------------------------------------------------------------

class _MockDraw:
    """Minimal PIL.ImageDraw mock that records rectangle + text calls."""
    def __init__(self):
        self.rects = []
        self.texts = []

    def rectangle(self, bounds, fill=None):
        self.rects.append({"bounds": bounds, "fill": fill})

    def text(self, pos, text, fill=None):
        self.texts.append({"pos": pos, "text": text, "fill": fill})


class TestDrawStatBar:
    def test_draws_without_exception(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        draw_stat_bar(_MockDraw(), x=0, y=0, w=100, h=16, value=50, max_value=100)

    def test_always_draws_background(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        d = _MockDraw()
        draw_stat_bar(d, 0, 0, 100, 16, value=0, max_value=100)
        assert len(d.rects) >= 1

    def test_full_value_draws_two_rects(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        d = _MockDraw()
        draw_stat_bar(d, 0, 0, 100, 16, value=100, max_value=100)
        assert len(d.rects) == 2  # background + fill

    def test_zero_value_draws_only_background(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        d = _MockDraw()
        draw_stat_bar(d, 0, 0, 100, 16, value=0, max_value=100)
        assert len(d.rects) == 1  # only background (ratio == 0)

    def test_fill_color_used(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        d = _MockDraw()
        draw_stat_bar(d, 0, 0, 100, 16, value=50, max_value=100,
                      fill_color=(255, 0, 0))
        fills = [r["fill"] for r in d.rects]
        assert (255, 0, 0) in fills

    def test_label_text_drawn(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        d = _MockDraw()
        draw_stat_bar(d, 0, 0, 100, 16, value=50, max_value=100, label="HP")
        assert any(t["text"] == "HP" for t in d.texts)

    def test_no_label_no_text(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        d = _MockDraw()
        draw_stat_bar(d, 0, 0, 100, 16, value=50, max_value=100, label="")
        assert d.texts == []

    def test_zero_max_no_crash(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        d = _MockDraw()
        draw_stat_bar(d, 0, 0, 100, 16, value=50, max_value=0)

    def test_value_beyond_max_clamped(self):
        from pharos_editor.ui.hud_widgets import draw_stat_bar
        d = _MockDraw()
        draw_stat_bar(d, 0, 0, 100, 16, value=200, max_value=100)
        # Fill rect should use clamped ratio (1.0), so fill width == bar width
        fill_rect = [r for r in d.rects if r["fill"] != (40, 40, 40)]
        if fill_rect:
            x0, y0, x1, y1 = fill_rect[0]["bounds"]
            assert x1 - x0 == 100  # full width


# ---------------------------------------------------------------------------
# ui/html_overlay.py — ImportError without pywebview
# ---------------------------------------------------------------------------

class TestHtmlOverlayImport:
    def test_raises_importerror_without_pywebview(self):
        try:
            import webview  # noqa: F401
            pytest.skip("pywebview is installed; can't test missing-dep path")
        except ImportError:
            pass
        from pharos_editor.ui.html_overlay import HtmlOverlay
        with pytest.raises(ImportError, match="pywebview"):
            HtmlOverlay(width=800, height=600)


# ---------------------------------------------------------------------------
# ui/project_manager.py — file helpers and ProjectManagerAPI (no engine needed)
# ---------------------------------------------------------------------------

class TestProjectManagerHelpers:
    def test_load_recent_no_crash(self):
        from pharos_editor.ui.project_manager import _load_recent
        result = _load_recent()
        assert isinstance(result, list)

    def test_add_recent_creates_entry(self, tmp_path, monkeypatch):
        from pharos_editor.ui import project_manager as pm
        monkeypatch.setattr(pm, "_RECENT_FILE", tmp_path / "recent.json")
        pm._add_recent("/fake/path", "TestProject")
        entries = pm._load_recent()
        assert any(e["path"] == "/fake/path" for e in entries)

    def test_add_recent_max_ten(self, tmp_path, monkeypatch):
        from pharos_editor.ui import project_manager as pm
        monkeypatch.setattr(pm, "_RECENT_FILE", tmp_path / "recent.json")
        for i in range(15):
            pm._add_recent(f"/path/{i}", f"proj{i}")
        entries = pm._load_recent()
        assert len(entries) <= pm._MAX_RECENT

    def test_add_recent_deduplicates(self, tmp_path, monkeypatch):
        from pharos_editor.ui import project_manager as pm
        monkeypatch.setattr(pm, "_RECENT_FILE", tmp_path / "recent.json")
        pm._add_recent("/same/path", "A")
        pm._add_recent("/same/path", "B")
        entries = pm._load_recent()
        paths = [e["path"] for e in entries]
        assert paths.count("/same/path") == 1


class TestProjectManagerAPI:
    def _make_api(self, tmp_path):
        from pharos_editor.ui.project_manager import ProjectManagerAPI

        class _FakeManager:
            _current_asset = None
            _editor_mode = "2D"

        api = ProjectManagerAPI.__new__(ProjectManagerAPI)
        api._engine = None
        api._manager = _FakeManager()
        return api, tmp_path

    def test_create_project_creates_dirs(self, tmp_path):
        api, base = self._make_api(tmp_path)
        proj_dir = str(base / "new_project")
        result = api.create_project(proj_dir, "TestGame")
        assert result.get("ok") is True
        from pathlib import Path
        assert (Path(proj_dir) / "scenes").exists()
        assert (Path(proj_dir) / "assets" / "sprites").exists()

    def test_create_project_creates_slap_proj(self, tmp_path):
        from pathlib import Path
        api, base = self._make_api(tmp_path)
        proj_dir = str(base / "myproj")
        api.create_project(proj_dir, "MyGame")
        proj_file = Path(proj_dir) / "project.slap_proj"
        assert proj_file.exists()

    def test_create_project_returns_name(self, tmp_path):
        api, base = self._make_api(tmp_path)
        proj_dir = str(base / "named")
        result = api.create_project(proj_dir, "NamedGame")
        assert result["project"]["name"] == "NamedGame"

    def test_list_assets_empty_when_no_assets(self, tmp_path):
        api, base = self._make_api(tmp_path)
        proj_dir = str(base / "empty_proj")
        api.create_project(proj_dir, "EmptyGame")
        assets = api.list_assets(proj_dir)
        assert isinstance(assets, list)

    def test_list_assets_finds_files(self, tmp_path):
        from pathlib import Path
        api, base = self._make_api(tmp_path)
        proj_dir = str(base / "proj_with_assets")
        api.create_project(proj_dir, "AssetGame")
        (Path(proj_dir) / "assets" / "sprites" / "test.png").write_bytes(b"PNG")
        assets = api.list_assets(proj_dir)
        names = [a["name"] for a in assets]
        assert "test.png" in names

    def test_list_scenes_empty_initially(self, tmp_path):
        api, base = self._make_api(tmp_path)
        proj_dir = str(base / "no_scenes")
        api.create_project(proj_dir, "NoScenes")
        scenes = api.list_scenes(proj_dir)
        assert isinstance(scenes, list)
        assert scenes == []

    def test_list_scenes_nonexistent_dir(self, tmp_path):
        api, base = self._make_api(tmp_path)
        scenes = api.list_scenes(str(base / "nonexistent"))
        assert scenes == []

    def test_open_project_missing_file_returns_error(self, tmp_path):
        api, base = self._make_api(tmp_path)
        result = api.open_project(str(base / "no_proj"))
        assert "error" in result
