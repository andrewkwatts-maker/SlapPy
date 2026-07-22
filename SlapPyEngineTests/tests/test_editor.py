"""
Tests for editor panel components.

All tests run WITHOUT dearpygui installed (all DPG operations are mocked).
Data-manipulation methods on each panel must work without a live DPG context;
any method that would normally call build() or DPG widget ops is either skipped
or has DPG monkey-patched to a no-op for the duration of the test.

Module-level guard:
    The panel modules themselves do not depend on wgpu or _core, so we guard
    on the concrete packages we actually need (asset, material, animation).
    If any of those are not importable the whole module is skipped so CI stays
    green on machines where the Rust extension has not been compiled yet.
"""
import sys
import types
import pytest

# ---------------------------------------------------------------------------
# Module-level guard — import only the lightweight submodules used in tests
# ---------------------------------------------------------------------------
try:
    from pharos_engine.asset import Asset          # noqa: F401
    from pharos_engine.layer import Layer          # noqa: F401
    from pharos_engine.material.map import MaterialMap, ColorRange  # noqa: F401
    from pharos_engine.animation.graph import (    # noqa: F401
        AnimationGraph, AnimState, AnimTransition,
    )
except Exception as _import_err:
    pytest.skip(
        f"SlapPyEngine submodules not importable: {_import_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# DPG stub fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def stub_dearpygui(monkeypatch):
    """
    Inject a minimal stub for dearpygui.dearpygui so that any panel that
    calls ``import dearpygui.dearpygui as dpg`` gets a no-op object rather
    than an ImportError (or a real GUI context).

    The stub makes ``dpg.does_item_exist(...)`` always return ``False`` so
    that _refresh() guards short-circuit immediately without trying to call
    real DPG widget operations.
    """
    stub = types.ModuleType("dearpygui.dearpygui")
    # Any attribute access on the stub returns a no-op callable.
    class _NoOpModule:
        def __getattr__(self, name):
            return lambda *a, **kw: None

        def does_item_exist(self, *a, **kw):
            return False

    stub_instance = _NoOpModule()
    # Make attribute look-ups on the module itself fall through to the stub.
    stub.__getattr__ = lambda name: getattr(stub_instance, name)

    dpg_pkg = types.ModuleType("dearpygui")
    dpg_pkg.dearpygui = stub_instance

    monkeypatch.setitem(sys.modules, "dearpygui", dpg_pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", stub_instance)

    yield stub_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset(width=64, height=64, n_layers=1):
    """Return a minimal Asset with n_layers blank layers (no GPU needed)."""
    from pharos_engine.asset import Asset
    from pharos_engine.layer import Layer

    asset = Asset(name="test_asset", size=(width, height))
    for i in range(n_layers):
        asset.add_layer(Layer.blank(width, height, name=f"Layer {i + 1}"))
    return asset


def _make_material_map():
    """Return a MaterialMap with two pre-populated entries."""
    from pharos_engine.material.map import MaterialMap, ColorRange

    mm = MaterialMap()
    mm.add("water", ColorRange(r=(0, 40), g=(0, 80), b=(180, 255)),
           behaviors=["fluid"])
    mm.add("soil", ColorRange(r=(80, 160), g=(50, 120), b=(0, 60)),
           behaviors=["rigid"])
    return mm


def _make_anim_graph():
    """Return an AnimationGraph with two states and one transition."""
    from pharos_engine.animation.graph import AnimationGraph, AnimState, AnimTransition

    graph = AnimationGraph()
    graph.add_state(AnimState(name="idle", clip_indices=[0, 1], fps=12.0))
    graph.add_state(AnimState(name="run",  clip_indices=[2, 3, 4], fps=24.0))
    graph.add_transition(AnimTransition(from_state="idle", to_state="run"))
    graph.set_initial("idle")
    return graph


# ===========================================================================
# LayerPanel tests
# ===========================================================================

class TestLayerPanel:
    """Tests 1–5: LayerPanel data-layer operations (no DPG context required)."""

    def _panel(self):
        try:
            from pharos_editor.ui.editor.layer_panel import LayerPanel
        except ImportError as e:
            pytest.skip(f"LayerPanel not importable: {e}")
        return LayerPanel()

    # 1. Instantiation
    def test_layer_panel_instantiates(self):
        panel = self._panel()
        assert panel is not None
        assert panel._asset is None

    # 2. set_asset stores the asset reference
    def test_layer_panel_set_asset_stores_reference(self):
        panel = self._panel()
        asset = _make_asset()
        panel.set_asset(asset)
        assert panel._asset is asset

    # 3. _add_layer appends a layer to the asset
    def test_layer_panel_add_layer_increases_count(self):
        panel = self._panel()
        asset = _make_asset(n_layers=1)
        panel._asset = asset
        initial_count = len(asset.layers)
        panel._add_layer()
        assert len(asset.layers) == initial_count + 1

    # 3b. _add_layer is a no-op when no asset is set
    def test_layer_panel_add_layer_no_asset_is_noop(self):
        panel = self._panel()
        # Must not raise
        panel._add_layer()

    # 4. _delete_layer removes the layer at the given index
    def test_layer_panel_delete_layer_removes_correct_index(self):
        panel = self._panel()
        asset = _make_asset(n_layers=3)
        panel._asset = asset
        # Record the name of the layer we expect to keep
        name_0 = asset.layers[0].name
        name_2 = asset.layers[2].name
        panel._delete_layer(1)  # remove middle
        assert len(asset.layers) == 2
        assert asset.layers[0].name == name_0
        assert asset.layers[1].name == name_2

    # 4b. _delete_layer refuses to remove the last remaining layer
    def test_layer_panel_delete_layer_guards_single_layer(self):
        panel = self._panel()
        asset = _make_asset(n_layers=1)
        panel._asset = asset
        panel._delete_layer(0)
        assert len(asset.layers) == 1  # still 1

    # 5. _move_layer direction=-1 moves layer toward top (higher index)
    def test_layer_panel_move_layer_up(self):
        panel = self._panel()
        asset = _make_asset(n_layers=3)
        panel._asset = asset
        name_before_0 = asset.layers[0].name
        name_before_1 = asset.layers[1].name
        # direction=-1 means "visual up" → swap layer[0] with layer[1]
        panel._move_layer(0, -1)
        assert asset.layers[0].name == name_before_1
        assert asset.layers[1].name == name_before_0

    # 5b. _move_layer direction=+1 moves layer toward bottom (lower index)
    def test_layer_panel_move_layer_down(self):
        panel = self._panel()
        asset = _make_asset(n_layers=3)
        panel._asset = asset
        name_before_1 = asset.layers[1].name
        name_before_2 = asset.layers[2].name
        # direction=+1 means "visual down" → swap layer[2] with layer[1]
        panel._move_layer(2, 1)
        assert asset.layers[2].name == name_before_1
        assert asset.layers[1].name == name_before_2


# ===========================================================================
# PropertyInspector tests
# ===========================================================================

class TestPropertyInspector:
    """Tests 6–7: PropertyInspector data-layer operations."""

    def _panel(self):
        try:
            from pharos_editor.ui.editor.property_inspector import PropertyInspector
        except ImportError as e:
            pytest.skip(f"PropertyInspector not importable: {e}")
        return PropertyInspector()

    # 6. Instantiation
    def test_property_inspector_instantiates(self):
        panel = self._panel()
        assert panel is not None
        assert panel._obj is None

    # 7. set_object stores the object
    def test_property_inspector_set_object_stores_reference(self):
        panel = self._panel()
        asset = _make_asset()
        panel.set_object(asset)
        assert panel._obj is asset

    # Extra: set_object replaces a previously set object
    def test_property_inspector_set_object_replaces(self):
        panel = self._panel()
        asset_a = _make_asset()
        asset_b = _make_asset()
        panel.set_object(asset_a)
        panel.set_object(asset_b)
        assert panel._obj is asset_b

    # Extra: _iter_fields returns public attributes of a plain object
    def test_property_inspector_iter_fields_plain_object(self):
        from pharos_engine.animation.graph import AnimState

        panel = self._panel()
        state = AnimState(name="idle")
        panel._obj = state
        fields = dict(panel._iter_fields())
        assert "name" in fields
        assert fields["name"] == "idle"


# ===========================================================================
# MaterialEditor tests
# ===========================================================================

class TestMaterialEditor:
    """Tests 8–11: MaterialEditor data-layer operations."""

    def _panel(self):
        try:
            from pharos_editor.ui.editor.material_editor import MaterialEditor
        except ImportError as e:
            pytest.skip(f"MaterialEditor not importable: {e}")
        return MaterialEditor()

    # 8. Instantiation
    def test_material_editor_instantiates(self):
        panel = self._panel()
        assert panel is not None
        assert panel._material_map is None

    # 9. set_material_map stores the map
    def test_material_editor_set_material_map_stores_reference(self):
        panel = self._panel()
        mm = _make_material_map()
        panel.set_material_map(mm)
        assert panel._material_map is mm

    # 10. _add_material appends a new entry to the map
    def test_material_editor_add_material_increases_count(self):
        panel = self._panel()
        mm = _make_material_map()
        panel._material_map = mm
        initial_count = len(mm._materials)
        panel._add_material()
        assert len(mm._materials) == initial_count + 1

    # 10b. _add_material new entry has the default name "new_material"
    def test_material_editor_add_material_default_name(self):
        panel = self._panel()
        mm = _make_material_map()
        panel._material_map = mm
        panel._add_material()
        assert mm._materials[-1].name == "new_material"

    # 11. _delete_material removes the correct index
    def test_material_editor_delete_material_removes_correct_index(self):
        panel = self._panel()
        mm = _make_material_map()
        panel._material_map = mm
        name_first = mm._materials[0].name   # "water"
        name_last  = mm._materials[-1].name  # "soil"
        # Delete index 0 (water); soil should become index 0
        panel._delete_material(0)
        assert len(mm._materials) == 1
        assert mm._materials[0].name == name_last

    # 11b. _delete_material is a no-op when no map is set
    def test_material_editor_delete_material_no_map_is_noop(self):
        panel = self._panel()
        panel._delete_material(0)  # must not raise

    # Extra: _on_name_change mutates the material name in place
    def test_material_editor_on_name_change(self):
        panel = self._panel()
        mm = _make_material_map()
        panel._material_map = mm
        panel._on_name_change(0, "lava")
        assert mm._materials[0].name == "lava"

    # Extra: _on_behaviors_change parses comma-separated string
    def test_material_editor_on_behaviors_change(self):
        panel = self._panel()
        mm = _make_material_map()
        panel._material_map = mm
        panel._on_behaviors_change(0, "solid, flammable, heavy")
        assert mm._materials[0].behaviors == ["solid", "flammable", "heavy"]


# ===========================================================================
# TagPainter tests
# ===========================================================================

class TestTagPainter:
    """Test 12: TagPainter instantiation and basic API."""

    def _panel(self):
        try:
            from pharos_editor.ui.editor.tag_painter import TagPainter
        except ImportError as e:
            pytest.skip(f"TagPainter not importable: {e}")
        return TagPainter()

    # 12. Instantiation
    def test_tag_painter_instantiates(self):
        panel = self._panel()
        assert panel is not None

    # Extra: set_asset stores the asset (TagPainter.set_asset takes asset + registry)
    def test_tag_painter_set_asset_stores_reference(self):
        panel = self._panel()
        asset = _make_asset()
        # TagPainter.set_asset signature: set_asset(asset, tag_registry)
        panel.set_asset(asset, tag_registry=None)
        assert panel._asset is asset

    # Extra: _selected_tag is None on fresh instance
    def test_tag_painter_initial_selected_tag_is_none(self):
        panel = self._panel()
        assert panel._selected_tag is None

    # Extra: paint_mode default
    def test_tag_painter_default_paint_mode(self):
        panel = self._panel()
        assert panel._paint_mode == "Color Range"


# ===========================================================================
# AnimGraphPanel tests
# ===========================================================================

class TestAnimGraphPanel:
    """Tests 13–14: AnimGraphPanel data-layer operations."""

    def _panel(self):
        try:
            from pharos_editor.ui.editor.anim_graph_panel import AnimGraphPanel
        except ImportError as e:
            pytest.skip(f"AnimGraphPanel not importable: {e}")
        return AnimGraphPanel()

    # 13. Instantiation
    def test_anim_graph_panel_instantiates(self):
        panel = self._panel()
        assert panel is not None
        assert panel._graph is None

    # 14. set_graph stores the graph
    def test_anim_graph_panel_set_graph_stores_reference(self):
        panel = self._panel()
        graph = _make_anim_graph()
        panel.set_graph(graph)
        assert panel._graph is graph

    # Extra: set_graph replaces a previously bound graph
    def test_anim_graph_panel_set_graph_replaces(self):
        panel = self._panel()
        graph_a = _make_anim_graph()
        graph_b = _make_anim_graph()
        panel.set_graph(graph_a)
        panel.set_graph(graph_b)
        assert panel._graph is graph_b

    # Extra: _add_state appends a new AnimState to the graph
    def test_anim_graph_panel_add_state_increases_count(self):
        panel = self._panel()
        graph = _make_anim_graph()
        panel._graph = graph
        initial = len(graph._states)
        panel._add_state()
        assert len(graph._states) == initial + 1

    # Extra: _add_state assigns a unique name each call
    def test_anim_graph_panel_add_state_unique_names(self):
        panel = self._panel()
        graph = _make_anim_graph()
        panel._graph = graph
        panel._add_state()
        panel._add_state()
        names = list(graph._states.keys())
        assert len(names) == len(set(names)), "Duplicate state names found"

    # Extra: _set_initial_state sets current to the selected state
    def test_anim_graph_panel_set_initial_state(self):
        panel = self._panel()
        graph = _make_anim_graph()
        panel._graph = graph
        panel._selected_state = "run"
        panel._set_initial_state()
        assert graph._current == "run"
