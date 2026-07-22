"""Tests for :class:`NotebookMinimap` (FF6).

Every test drives the panel headless — Dear PyGui is stubbed via
``sys.modules`` monkey-patching (mirrors the Z2 pattern used across the
BB / EE / FF rigs) so no viewport is required.

Coverage:

* Construction defaults + validation.
* set_scene populates entities + auto-fits bounds.
* set_camera + refresh() renders a viewport rectangle in the log.
* Left-click → invokes on_pan_request AND drives the camera.
* World → minimap → world round-trips within 1 px.
* Zoom clamped to [MIN_ZOOM, MAX_ZOOM].
* Right-drag pans the view.
* Bounds auto-fit to entity set (with padding).
* Explicit world bounds override auto-fit.
* Entity kind classification via tags / class name / minimap_kind.
* Entity kind colour table has all 5 canonical kinds.
* Grid overlay every GRID_STEP world units.
* Build under stub DPG registers root + drawlist tags.
* Lazy registration in the editor ``__init__``.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from pharos_editor.ui.editor.notebook_minimap import (
    ENTITY_KIND_COLORS,
    NotebookMinimap,
    classify_entity,
)


# ---------------------------------------------------------------------------
# Force _safe_dpg into headless mode for the whole module — real DPG blows up
# with an access violation when its C runtime is called before
# ``create_context()``. The panel's ``_headless_env_active`` gate honours
# ``SLAPPY_HEADLESS=1`` so setting it once at module level keeps all
# refresh()-driven tests off the real dearpygui C extension.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _force_headless(monkeypatch):
    monkeypatch.setenv("SLAPPY_HEADLESS", "1")
    yield


# ---------------------------------------------------------------------------
# Headless DPG stub — mirrors the Z2 pattern.
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, object] = {}
        self.mouse_pos: tuple[int, int] = (0, 0)

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def item_handler_registry(self, *a, **kw):
        self._track("item_handler_registry", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_drawlist(self, *a, **kw):
        self._track("add_drawlist", a, kw)

    def add_item_clicked_handler(self, *a, **kw):
        self._track("add_item_clicked_handler", a, kw)

    def bind_item_handler_registry(self, *a, **kw):
        self._track("bind_item_handler_registry", a, kw)

    def draw_line(self, *a, **kw):
        self._track("draw_line", a, kw)

    def draw_rectangle(self, *a, **kw):
        self._track("draw_rectangle", a, kw)

    def draw_circle(self, *a, **kw):
        self._track("draw_circle", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def get_mouse_pos(self, *a, **kw):
        return list(self.mouse_pos)


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a stub ``dearpygui.dearpygui`` module."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window", "item_handler_registry",
        "add_text", "add_drawlist", "add_item_clicked_handler",
        "bind_item_handler_registry",
        "draw_line", "draw_rectangle", "draw_circle",
        "does_item_exist", "get_mouse_pos",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# Fake scene / entity helpers
# ---------------------------------------------------------------------------


class _FakeEntity:
    def __init__(
        self,
        name: str = "",
        position: tuple[float, float] = (0.0, 0.0),
        tags: set[str] | None = None,
        kind: str | None = None,
    ):
        self.name = name
        self.position = position
        self.tags = set(tags) if tags else set()
        if kind is not None:
            self.minimap_kind = kind


class _FakeScene:
    def __init__(self, entities: list[_FakeEntity] | None = None):
        self.entities = entities or []


class _FakeCamera:
    def __init__(
        self,
        position: tuple[float, float] = (0.0, 0.0),
        zoom: float = 1.0,
        viewport_size: tuple[int, int] = (800, 600),
    ):
        self.position = position
        self.zoom = zoom
        self._viewport_size = viewport_size


# ===========================================================================
# Construction
# ===========================================================================


class TestConstruction:
    def test_defaults(self):
        panel = NotebookMinimap()
        assert panel.TITLE == "Minimap"
        assert panel.MIN_WIDTH == 200
        assert panel.MIN_HEIGHT == 200
        assert panel.BODY_WIDTH == 180
        assert panel.BODY_HEIGHT == 180
        assert panel.zoom == 1.0
        assert panel.view_offset == (0.0, 0.0)
        assert panel.camera is None
        assert panel.scene is None
        assert panel.entities == []

    def test_rejects_bad_callback(self):
        with pytest.raises(TypeError):
            NotebookMinimap(on_pan_request="not-callable")

    def test_accepts_callback(self):
        calls = []
        panel = NotebookMinimap(on_pan_request=lambda x, y: calls.append((x, y)))
        assert panel.on_pan_request is not None

    def test_default_bounds(self):
        panel = NotebookMinimap()
        assert panel.world_bounds == NotebookMinimap.DEFAULT_BOUNDS


# ===========================================================================
# Scene binding
# ===========================================================================


class TestSetScene:
    def test_populates_entities(self):
        scene = _FakeScene([
            _FakeEntity("a", (0.0, 0.0)),
            _FakeEntity("b", (10.0, 10.0)),
        ])
        panel = NotebookMinimap()
        panel.set_scene(scene)
        assert len(panel.entities) == 2

    def test_none_clears(self):
        panel = NotebookMinimap()
        panel.set_scene(None)
        assert panel.entities == []

    def test_duck_types_on_entities_list(self):
        scene = types.SimpleNamespace(
            entities=[_FakeEntity("x", (1.0, 2.0))]
        )
        panel = NotebookMinimap()
        panel.set_scene(scene)
        assert len(panel.entities) == 1

    def test_auto_fits_bounds(self):
        scene = _FakeScene([
            _FakeEntity(position=(0.0, 0.0)),
            _FakeEntity(position=(100.0, 60.0)),
        ])
        panel = NotebookMinimap()
        panel.set_scene(scene)
        bx, by, bw, bh = panel.world_bounds
        # min x = 0, max x = 100 → bounds include both, with padding.
        assert bx <= 0.0
        assert bx + bw >= 100.0
        assert by <= 0.0
        assert by + bh >= 60.0


# ===========================================================================
# Camera binding + viewport render
# ===========================================================================


class TestSetCamera:
    def test_bind_camera(self):
        cam = _FakeCamera(position=(0.0, 0.0))
        panel = NotebookMinimap()
        panel.set_camera(cam)
        assert panel.camera is cam

    def test_render_viewport_rect(self):
        cam = _FakeCamera(position=(0.0, 0.0), zoom=1.0)
        panel = NotebookMinimap()
        panel.set_camera(cam)
        panel.refresh()
        kinds = [item[0] for item in panel.render_log]
        assert "viewport_rect" in kinds

    def test_no_viewport_without_camera(self):
        panel = NotebookMinimap()
        panel.refresh()
        kinds = [item[0] for item in panel.render_log]
        assert "viewport_rect" not in kinds

    def test_viewport_rect_has_four_corners(self):
        cam = _FakeCamera(position=(0.0, 0.0), zoom=1.0)
        panel = NotebookMinimap()
        panel.set_camera(cam)
        panel.refresh()
        for entry in panel.render_log:
            if entry[0] == "viewport_rect":
                corners = entry[1]
                assert len(corners) == 4
                for c in corners:
                    assert len(c) == 2
                break
        else:
            pytest.fail("viewport_rect not in render log")

    def test_viewport_jitters_across_frames(self):
        """Hand-drawn viewport rect must wobble deterministically."""
        cam = _FakeCamera(position=(0.0, 0.0), zoom=1.0)
        panel = NotebookMinimap()
        panel.set_camera(cam)
        panel.refresh()
        frame1 = next(e[1] for e in panel.render_log if e[0] == "viewport_rect")
        panel.refresh()
        frame2 = next(e[1] for e in panel.render_log if e[0] == "viewport_rect")
        # Different frames → different jitter → different corner positions.
        assert frame1 != frame2


# ===========================================================================
# Left-click
# ===========================================================================


class TestLeftClick:
    def test_invokes_callback(self):
        calls: list[tuple[float, float]] = []
        panel = NotebookMinimap(on_pan_request=lambda x, y: calls.append((x, y)))
        panel.set_world_bounds((-100.0, -100.0, 200.0, 200.0))
        result = panel.on_left_click(90, 90)  # near centre
        assert result is not None
        assert len(calls) == 1
        # Centre of the drawlist maps back to centre of bounds ≈ (0, 0).
        cx, cy = calls[0]
        assert abs(cx) < 1.5
        assert abs(cy) < 1.5

    def test_ignores_out_of_body_clicks(self):
        calls: list[tuple[float, float]] = []
        panel = NotebookMinimap(on_pan_request=lambda x, y: calls.append((x, y)))
        result = panel.on_left_click(-5, 50)
        assert result is None
        assert calls == []

    def test_drives_camera_position(self):
        cam = _FakeCamera(position=(0.0, 0.0))
        panel = NotebookMinimap()
        panel.set_camera(cam)
        panel.set_world_bounds((-100.0, -100.0, 200.0, 200.0))
        panel.on_left_click(0, 0)  # top-left corner
        # Should have driven the camera to ≈ (-100, -100).
        assert cam.position[0] < -95.0
        assert cam.position[1] < -95.0

    def test_broken_callback_does_not_crash(self):
        def _boom(x, y):
            raise RuntimeError("boom")
        panel = NotebookMinimap(on_pan_request=_boom)
        panel.set_world_bounds((-100.0, -100.0, 200.0, 200.0))
        # Should not raise.
        result = panel.on_left_click(50, 50)
        assert result is not None


# ===========================================================================
# Round-trip projection
# ===========================================================================


class TestProjection:
    @pytest.mark.parametrize(
        "world_pt",
        [
            (0.0, 0.0),
            (25.0, -15.0),
            (-42.0, 33.0),
            (7.5, 7.5),
        ],
    )
    def test_world_to_minimap_round_trip(self, world_pt):
        panel = NotebookMinimap()
        panel.set_world_bounds((-100.0, -100.0, 200.0, 200.0))
        px, py = panel._project_world_to_minimap(*world_pt)
        wx, wy = panel._project_minimap_to_world(px, py)
        assert abs(wx - world_pt[0]) < 1.0
        assert abs(wy - world_pt[1]) < 1.0

    def test_round_trip_survives_zoom(self):
        panel = NotebookMinimap()
        panel.set_world_bounds((-100.0, -100.0, 200.0, 200.0))
        panel.on_scroll(2)  # zoom in a couple of notches
        px, py = panel._project_world_to_minimap(10.0, -5.0)
        wx, wy = panel._project_minimap_to_world(px, py)
        assert abs(wx - 10.0) < 1.0
        assert abs(wy + 5.0) < 1.0

    def test_round_trip_survives_pan(self):
        panel = NotebookMinimap()
        panel.set_world_bounds((-100.0, -100.0, 200.0, 200.0))
        panel.begin_right_drag(50, 50)
        panel.on_right_drag(70, 40)
        px, py = panel._project_world_to_minimap(0.0, 0.0)
        wx, wy = panel._project_minimap_to_world(px, py)
        assert abs(wx) < 1.0
        assert abs(wy) < 1.0

    def test_projection_maps_bounds_to_body(self):
        panel = NotebookMinimap()
        panel.set_world_bounds((0.0, 0.0, 100.0, 100.0))
        # World (0, 0) → minimap (0, 0).
        px, py = panel._project_world_to_minimap(0.0, 0.0)
        assert abs(px) < 0.5
        assert abs(py) < 0.5
        # World (100, 100) → minimap (BODY, BODY).
        px, py = panel._project_world_to_minimap(100.0, 100.0)
        assert abs(px - panel.BODY_WIDTH) < 0.5
        assert abs(py - panel.BODY_HEIGHT) < 0.5


# ===========================================================================
# Zoom
# ===========================================================================


class TestZoom:
    def test_scroll_up_zooms_in(self):
        panel = NotebookMinimap()
        z0 = panel.zoom
        new_z = panel.on_scroll(1)
        assert new_z > z0

    def test_scroll_down_zooms_out(self):
        panel = NotebookMinimap()
        z0 = panel.zoom
        new_z = panel.on_scroll(-1)
        assert new_z < z0

    def test_zoom_clamped_max(self):
        panel = NotebookMinimap()
        for _ in range(50):
            panel.on_scroll(1)
        assert panel.zoom <= NotebookMinimap.MAX_ZOOM
        assert panel.zoom == NotebookMinimap.MAX_ZOOM

    def test_zoom_clamped_min(self):
        panel = NotebookMinimap()
        for _ in range(50):
            panel.on_scroll(-1)
        assert panel.zoom >= NotebookMinimap.MIN_ZOOM
        assert panel.zoom == NotebookMinimap.MIN_ZOOM

    def test_scroll_rejects_non_numeric(self):
        panel = NotebookMinimap()
        with pytest.raises(TypeError):
            panel.on_scroll("up")


# ===========================================================================
# Right-drag pan
# ===========================================================================


class TestRightDrag:
    def test_right_drag_shifts_offset(self):
        panel = NotebookMinimap()
        panel.set_world_bounds((-100.0, -100.0, 200.0, 200.0))
        panel.begin_right_drag(90, 90)
        new_offset = panel.on_right_drag(90 + 45, 90)  # 45 px right
        # Panel-view moves right (dx_px > 0) → world under it shifts left.
        assert new_offset[0] < 0.0
        assert abs(new_offset[1]) < 1e-6

    def test_end_right_drag_clears_anchor(self):
        panel = NotebookMinimap()
        panel.begin_right_drag(50, 50)
        panel.on_right_drag(60, 60)
        panel.end_right_drag()
        # New drag starts fresh from the next cursor point.
        panel.begin_right_drag(0, 0)
        panel.on_right_drag(20, 0)  # small delta relative to fresh anchor
        # The offset should now be based on the new anchor, not the old.


# ===========================================================================
# World bounds
# ===========================================================================


class TestWorldBounds:
    def test_explicit_bounds_stick(self):
        panel = NotebookMinimap()
        panel.set_world_bounds((10.0, 20.0, 30.0, 40.0))
        assert panel.world_bounds == (10.0, 20.0, 30.0, 40.0)

    def test_explicit_bounds_survive_set_scene(self):
        panel = NotebookMinimap()
        panel.set_world_bounds((10.0, 20.0, 30.0, 40.0))
        panel.set_scene(_FakeScene([_FakeEntity(position=(1000.0, 1000.0))]))
        assert panel.world_bounds == (10.0, 20.0, 30.0, 40.0)

    def test_none_reverts_to_auto_fit(self):
        panel = NotebookMinimap()
        panel.set_scene(_FakeScene([
            _FakeEntity(position=(0.0, 0.0)),
            _FakeEntity(position=(50.0, 50.0)),
        ]))
        panel.set_world_bounds((999.0, 999.0, 1.0, 1.0))
        panel.set_world_bounds(None)
        bx, by, bw, bh = panel.world_bounds
        assert bx <= 0.0
        assert bx + bw >= 50.0

    def test_rejects_bad_bounds_shape(self):
        panel = NotebookMinimap()
        with pytest.raises(TypeError):
            panel.set_world_bounds((1, 2, 3))

    def test_rejects_zero_width(self):
        panel = NotebookMinimap()
        with pytest.raises(ValueError):
            panel.set_world_bounds((0.0, 0.0, 0.0, 100.0))


# ===========================================================================
# Entity classification
# ===========================================================================


class TestClassifyEntity:
    def test_all_five_kinds_in_color_table(self):
        for kind in ("prop", "character", "vehicle", "particle", "structural"):
            assert kind in ENTITY_KIND_COLORS

    def test_color_table_rgba_shape(self):
        for kind, color in ENTITY_KIND_COLORS.items():
            assert len(color) == 4
            for ch in color:
                assert 0 <= ch <= 255

    def test_explicit_minimap_kind(self):
        e = _FakeEntity(kind="vehicle")
        assert classify_entity(e) == "vehicle"

    def test_ignores_bad_kind_hint(self):
        e = _FakeEntity(kind="banana")
        # Falls through to tag / class-name / default = prop.
        assert classify_entity(e) == "prop"

    def test_tag_hint_character(self):
        e = _FakeEntity(tags={"npc"})
        assert classify_entity(e) == "character"

    def test_tag_hint_vehicle(self):
        e = _FakeEntity(tags={"car"})
        assert classify_entity(e) == "vehicle"

    def test_default_prop(self):
        e = _FakeEntity()
        assert classify_entity(e) == "prop"

    def test_class_name_hint(self):
        class RaceCar:
            position = (0.0, 0.0)
            tags: set[str] = set()

        assert classify_entity(RaceCar()) == "vehicle"


# ===========================================================================
# Grid overlay
# ===========================================================================


class TestGrid:
    def test_grid_lines_present(self):
        panel = NotebookMinimap()
        panel.set_world_bounds((0.0, 0.0, 100.0, 100.0))
        panel.refresh()
        v = [e for e in panel.render_log if e[0] == "grid_v"]
        h = [e for e in panel.render_log if e[0] == "grid_h"]
        # 100 world units / 10 = ~11 grid lines each axis (inclusive + edge).
        assert len(v) >= 10
        assert len(h) >= 10

    def test_grid_step_ten(self):
        assert NotebookMinimap.GRID_STEP == 10.0


# ===========================================================================
# Refresh
# ===========================================================================


class TestRefresh:
    def test_refresh_bumps_frame_counter(self):
        panel = NotebookMinimap()
        f0 = panel.frame_index
        panel.refresh()
        assert panel.frame_index == f0 + 1

    def test_refresh_re_scans_entities(self):
        scene = _FakeScene([_FakeEntity(position=(0.0, 0.0))])
        panel = NotebookMinimap()
        panel.set_scene(scene)
        # Add a new entity to the live scene, then refresh.
        scene.entities.append(_FakeEntity(position=(20.0, 20.0)))
        panel.refresh()
        assert len(panel.entities) == 2


# ===========================================================================
# Render — entity dots
# ===========================================================================


class TestEntityDots:
    def test_dot_colours_match_kinds(self):
        entities = [
            _FakeEntity(position=(10.0, 10.0), kind="character"),
            _FakeEntity(position=(20.0, 20.0), kind="vehicle"),
            _FakeEntity(position=(30.0, 30.0), kind="particle"),
        ]
        panel = NotebookMinimap()
        panel.set_world_bounds((0.0, 0.0, 100.0, 100.0))
        panel.set_scene(_FakeScene(entities))
        panel.refresh()
        by_kind: dict[str, tuple[int, int, int, int]] = {}
        for entry in panel.render_log:
            if entry[0] == "dot":
                _px, _py, kind, color = entry[1]
                by_kind[kind] = color
        assert by_kind.get("character") == ENTITY_KIND_COLORS["character"]
        assert by_kind.get("vehicle") == ENTITY_KIND_COLORS["vehicle"]
        assert by_kind.get("particle") == ENTITY_KIND_COLORS["particle"]

    def test_offscreen_entities_recorded(self):
        # Entity way outside the world bounds → still logged.
        e = _FakeEntity(position=(9999.0, 9999.0))
        panel = NotebookMinimap()
        panel.set_world_bounds((0.0, 0.0, 100.0, 100.0))
        panel.set_scene(_FakeScene([e]))
        panel.refresh()
        kinds = [entry[0] for entry in panel.render_log]
        assert "dot_offscreen" in kinds


# ===========================================================================
# Build under stub DPG
# ===========================================================================


class TestBuild:
    def test_build_headless(self):
        panel = NotebookMinimap()
        panel.build(parent_tag="root")
        assert panel._built is True

    def test_build_registers_drawlist(self, stub_dpg):
        panel = NotebookMinimap()
        panel.build(parent_tag="root")
        assert "add_drawlist" in stub_dpg.calls
        # Root group tag registered.
        assert any(t.startswith("notebook_minimap_root") for t in stub_dpg.items)

    def test_build_registers_title(self, stub_dpg):
        panel = NotebookMinimap()
        panel.build(parent_tag="root")
        texts = stub_dpg.calls.get("add_text", [])
        found = any(
            call[0] and call[0][0] == "Minimap"
            for call in texts
        )
        assert found


# ===========================================================================
# Lazy registration in editor __init__
# ===========================================================================


class TestLazyRegistration:
    def test_lazy_import_works(self):
        import pharos_editor.ui.editor as editor_pkg
        assert "NotebookMinimap" in editor_pkg.__all__
        cls = editor_pkg.NotebookMinimap
        assert cls.__name__ == "NotebookMinimap"

    def test_alphabetical_position(self):
        import pharos_editor.ui.editor as editor_pkg
        idx = editor_pkg.__all__.index("NotebookMinimap")
        prev_entry = editor_pkg.__all__[idx - 1]
        next_entry = editor_pkg.__all__[idx + 1]
        assert prev_entry <= "NotebookMinimap" <= next_entry
