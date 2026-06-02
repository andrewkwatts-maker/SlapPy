"""Headless tests for the remaining uncovered editor panels and net/discovery.

Covers:
- slappyengine.ui.editor.anim_graph_panel    (AnimGraphPanel)
- slappyengine.ui.editor.layer_lighting_panel (LayerLightingPanel + _LIGHTING_MODES)
- slappyengine.ui.editor.material_editor      (MaterialEditor + _ALPHA_MEANINGS)
- slappyengine.ui.editor.mesh_inspector       (MeshInspector)
- slappyengine.ui.editor.node_graph_panel     (NodeGraphPanel + module constants)
- slappyengine.ui.editor.shell                (EditorShell)
- slappyengine.net.discovery                  (module-level constants)

DPG guard: force a safe MagicMock so panel methods can be called headlessly.
"""
from __future__ import annotations
import sys
import unittest.mock
import pytest

# ---------------------------------------------------------------------------
# DPG mock — prevents segfault from dearpygui without a viewport context.
# ---------------------------------------------------------------------------
_DPG_MOCK = unittest.mock.MagicMock()
_DPG_MOCK.does_item_exist.return_value = False
if 'dearpygui.dearpygui' not in sys.modules:
    sys.modules['dearpygui'] = unittest.mock.MagicMock()
    sys.modules['dearpygui.dearpygui'] = _DPG_MOCK
else:
    # Ensure a safe mock is active even if a real module snuck in
    sys.modules['dearpygui.dearpygui'] = _DPG_MOCK


# ---------------------------------------------------------------------------
# AnimGraphPanel
# ---------------------------------------------------------------------------

class TestAnimGraphPanelInit:
    def test_instantiates(self):
        from slappyengine.ui.editor.anim_graph_panel import AnimGraphPanel
        p = AnimGraphPanel()
        assert p is not None

    def test_graph_none_initially(self):
        from slappyengine.ui.editor.anim_graph_panel import AnimGraphPanel
        p = AnimGraphPanel()
        assert p._graph is None

    def test_cube_array_none_initially(self):
        from slappyengine.ui.editor.anim_graph_panel import AnimGraphPanel
        p = AnimGraphPanel()
        assert p._cube_array is None

    def test_panel_tag(self):
        from slappyengine.ui.editor.anim_graph_panel import AnimGraphPanel
        p = AnimGraphPanel()
        assert p._panel_tag == "anim_graph_panel"

    def test_editor_tag(self):
        from slappyengine.ui.editor.anim_graph_panel import AnimGraphPanel
        p = AnimGraphPanel()
        assert p._editor_tag == "anim_graph_editor"

    def test_state_attr_tags_empty(self):
        from slappyengine.ui.editor.anim_graph_panel import AnimGraphPanel
        p = AnimGraphPanel()
        assert p._state_attr_tags == {}

    def test_selected_state_none(self):
        from slappyengine.ui.editor.anim_graph_panel import AnimGraphPanel
        p = AnimGraphPanel()
        assert p._selected_state is None


# ---------------------------------------------------------------------------
# LayerLightingPanel + module constant
# ---------------------------------------------------------------------------

class TestLightingModeConstant:
    def test_lighting_modes_is_list(self):
        from slappyengine.ui.editor.layer_lighting_panel import _LIGHTING_MODES
        assert isinstance(_LIGHTING_MODES, list)

    def test_contains_none_mode(self):
        from slappyengine.ui.editor.layer_lighting_panel import _LIGHTING_MODES
        assert "none" in _LIGHTING_MODES

    def test_contains_global_mode(self):
        from slappyengine.ui.editor.layer_lighting_panel import _LIGHTING_MODES
        assert "global" in _LIGHTING_MODES

    def test_contains_local_mode(self):
        from slappyengine.ui.editor.layer_lighting_panel import _LIGHTING_MODES
        assert "local" in _LIGHTING_MODES

    def test_contains_cross_mode(self):
        from slappyengine.ui.editor.layer_lighting_panel import _LIGHTING_MODES
        assert "cross" in _LIGHTING_MODES

    def test_has_four_modes(self):
        from slappyengine.ui.editor.layer_lighting_panel import _LIGHTING_MODES
        assert len(_LIGHTING_MODES) == 4


class TestLayerLightingPanelInit:
    def test_instantiates(self):
        from slappyengine.ui.editor.layer_lighting_panel import LayerLightingPanel
        p = LayerLightingPanel()
        assert p is not None

    def test_layer_none_initially(self):
        from slappyengine.ui.editor.layer_lighting_panel import LayerLightingPanel
        p = LayerLightingPanel()
        assert p._layer is None

    def test_panel_tag(self):
        from slappyengine.ui.editor.layer_lighting_panel import LayerLightingPanel
        p = LayerLightingPanel()
        assert p._panel_tag == "layer_lighting_panel"


# ---------------------------------------------------------------------------
# MaterialEditor + module constant
# ---------------------------------------------------------------------------

class TestMaterialEditorAlphaMeanings:
    def test_alpha_meanings_is_list(self):
        from slappyengine.ui.editor.material_editor import MaterialEditor
        assert isinstance(MaterialEditor._ALPHA_MEANINGS, list)

    def test_opacity_present(self):
        from slappyengine.ui.editor.material_editor import MaterialEditor
        assert "opacity" in MaterialEditor._ALPHA_MEANINGS

    def test_health_present(self):
        from slappyengine.ui.editor.material_editor import MaterialEditor
        assert "health" in MaterialEditor._ALPHA_MEANINGS

    def test_at_least_four_meanings(self):
        from slappyengine.ui.editor.material_editor import MaterialEditor
        assert len(MaterialEditor._ALPHA_MEANINGS) >= 4


class TestMaterialEditorInit:
    def test_instantiates(self):
        from slappyengine.ui.editor.material_editor import MaterialEditor
        p = MaterialEditor()
        assert p is not None

    def test_material_map_none_initially(self):
        from slappyengine.ui.editor.material_editor import MaterialEditor
        p = MaterialEditor()
        assert p._material_map is None

    def test_panel_tag(self):
        from slappyengine.ui.editor.material_editor import MaterialEditor
        p = MaterialEditor()
        assert p._panel_tag == "material_editor"


# ---------------------------------------------------------------------------
# MeshInspector
# ---------------------------------------------------------------------------

class TestMeshInspectorInit:
    def test_instantiates(self):
        from slappyengine.ui.editor.mesh_inspector import MeshInspector
        p = MeshInspector()
        assert p is not None

    def test_layer_none_initially(self):
        from slappyengine.ui.editor.mesh_inspector import MeshInspector
        p = MeshInspector()
        assert p._layer is None

    def test_panel_tag(self):
        from slappyengine.ui.editor.mesh_inspector import MeshInspector
        p = MeshInspector()
        assert p._panel_tag == "mesh_inspector_panel"


# ---------------------------------------------------------------------------
# NodeGraphPanel + module-level constants
# ---------------------------------------------------------------------------

class TestNodeGraphPanelModuleConstants:
    def test_port_schema_is_dict(self):
        from slappyengine.ui.editor.node_graph_panel import _PORT_SCHEMA
        assert isinstance(_PORT_SCHEMA, dict)

    def test_port_schema_has_final_color(self):
        from slappyengine.ui.editor.node_graph_panel import _PORT_SCHEMA
        assert "FinalColor" in _PORT_SCHEMA

    def test_port_schema_has_add(self):
        from slappyengine.ui.editor.node_graph_panel import _PORT_SCHEMA
        assert "Add" in _PORT_SCHEMA

    def test_port_schema_has_multiply(self):
        from slappyengine.ui.editor.node_graph_panel import _PORT_SCHEMA
        assert "Multiply" in _PORT_SCHEMA

    def test_port_schema_has_lerp(self):
        from slappyengine.ui.editor.node_graph_panel import _PORT_SCHEMA
        assert "Lerp" in _PORT_SCHEMA

    def test_float_params_is_frozenset(self):
        from slappyengine.ui.editor.node_graph_panel import _FLOAT_PARAMS
        assert isinstance(_FLOAT_PARAMS, frozenset)

    def test_float_params_has_min_max(self):
        from slappyengine.ui.editor.node_graph_panel import _FLOAT_PARAMS
        assert "min" in _FLOAT_PARAMS
        assert "max" in _FLOAT_PARAMS

    def test_add_menu_is_dict(self):
        from slappyengine.ui.editor.node_graph_panel import _ADD_MENU
        assert isinstance(_ADD_MENU, dict)

    def test_add_menu_has_output_category(self):
        from slappyengine.ui.editor.node_graph_panel import _ADD_MENU
        assert "Output" in _ADD_MENU

    def test_add_menu_has_source_category(self):
        from slappyengine.ui.editor.node_graph_panel import _ADD_MENU
        assert "Source" in _ADD_MENU

    def test_add_menu_has_math_category(self):
        from slappyengine.ui.editor.node_graph_panel import _ADD_MENU
        assert "Math" in _ADD_MENU

    def test_default_params_is_dict(self):
        from slappyengine.ui.editor.node_graph_panel import _DEFAULT_PARAMS
        assert isinstance(_DEFAULT_PARAMS, dict)

    def test_default_params_clamp_has_min_max(self):
        from slappyengine.ui.editor.node_graph_panel import _DEFAULT_PARAMS
        if "Clamp" in _DEFAULT_PARAMS:
            assert "min" in _DEFAULT_PARAMS["Clamp"]
            assert "max" in _DEFAULT_PARAMS["Clamp"]

    def test_port_schema_entry_has_inputs_outputs(self):
        from slappyengine.ui.editor.node_graph_panel import _PORT_SCHEMA
        for node_type, ports in _PORT_SCHEMA.items():
            assert "inputs" in ports, f"{node_type} missing inputs"
            assert "outputs" in ports, f"{node_type} missing outputs"


class TestNodeGraphPanelInit:
    def test_instantiates(self):
        from slappyengine.ui.editor.node_graph_panel import NodeGraphPanel
        p = NodeGraphPanel()
        assert p is not None

    def test_material_none_initially(self):
        from slappyengine.ui.editor.node_graph_panel import NodeGraphPanel
        p = NodeGraphPanel()
        assert p._material is None

    def test_panel_tag(self):
        from slappyengine.ui.editor.node_graph_panel import NodeGraphPanel
        p = NodeGraphPanel()
        assert p._panel_tag == "node_graph_panel"

    def test_editor_tag(self):
        from slappyengine.ui.editor.node_graph_panel import NodeGraphPanel
        p = NodeGraphPanel()
        assert p._editor_tag == "node_graph_editor"

    def test_node_tags_empty(self):
        from slappyengine.ui.editor.node_graph_panel import NodeGraphPanel
        p = NodeGraphPanel()
        assert p._node_tags == {}

    def test_attr_meta_empty(self):
        from slappyengine.ui.editor.node_graph_panel import NodeGraphPanel
        p = NodeGraphPanel()
        assert p._attr_meta == {}

    def test_link_tags_empty(self):
        from slappyengine.ui.editor.node_graph_panel import NodeGraphPanel
        p = NodeGraphPanel()
        assert p._link_tags == {}

    def test_tag_counter_zero(self):
        from slappyengine.ui.editor.node_graph_panel import NodeGraphPanel
        p = NodeGraphPanel()
        assert p._tag_counter == 0


# ---------------------------------------------------------------------------
# EditorShell
# ---------------------------------------------------------------------------

class TestEditorShellInit:
    def test_instantiates_with_none_engine(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell is not None

    def test_engine_stored(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._engine is None

    def test_default_title(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert "Editor" in shell._title

    def test_custom_title(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None, title="MyEditor")
        assert shell._title == "MyEditor"

    def test_default_dimensions(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._width > 0
        assert shell._height > 0

    def test_custom_dimensions(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None, width=800, height=600)
        assert shell._width == 800
        assert shell._height == 600

    def test_panels_empty_initially(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._panels == []

    def test_running_false_initially(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._running is False

    def test_play_mode_false_initially(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._play_mode is False

    def test_editor_mode_2d(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._editor_mode == "2D"

    def test_register_panel_appends(self):
        from slappyengine.ui.editor.shell import EditorShell

        class FakePanel:
            def build(self, parent_tag): pass

        shell = EditorShell(engine=None)
        p = FakePanel()
        shell.register_panel(p)
        assert len(shell._panels) == 1
        assert shell._panels[0] is p

    def test_register_multiple_panels(self):
        from slappyengine.ui.editor.shell import EditorShell

        class FakePanel:
            def build(self, parent_tag): pass

        shell = EditorShell(engine=None)
        shell.register_panel(FakePanel())
        shell.register_panel(FakePanel())
        assert len(shell._panels) == 2

    def test_dragging_window_false(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._dragging_window is False

    def test_toolbar_none_initially(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._toolbar is None

    def test_scene_outliner_none_initially(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._scene_outliner is None

    def test_content_browser_none_initially(self):
        from slappyengine.ui.editor.shell import EditorShell
        shell = EditorShell(engine=None)
        assert shell._content_browser is None


# ---------------------------------------------------------------------------
# net/discovery.py — module-level constants (no network calls)
# ---------------------------------------------------------------------------

class TestDiscoveryModuleConstants:
    def test_dht_bootstrap_is_list(self):
        from slappyengine.net.discovery import _DHT_BOOTSTRAP
        assert isinstance(_DHT_BOOTSTRAP, list)

    def test_dht_bootstrap_has_entries(self):
        from slappyengine.net.discovery import _DHT_BOOTSTRAP
        assert len(_DHT_BOOTSTRAP) >= 1

    def test_dht_bootstrap_entries_are_tuples(self):
        from slappyengine.net.discovery import _DHT_BOOTSTRAP
        for entry in _DHT_BOOTSTRAP:
            assert isinstance(entry, tuple)
            assert len(entry) == 2

    def test_dht_bootstrap_ports_are_ints(self):
        from slappyengine.net.discovery import _DHT_BOOTSTRAP
        for host, port in _DHT_BOOTSTRAP:
            assert isinstance(port, int)
            assert port > 0

    def test_dht_bootstrap_hosts_are_strings(self):
        from slappyengine.net.discovery import _DHT_BOOTSTRAP
        for host, port in _DHT_BOOTSTRAP:
            assert isinstance(host, str)
            assert len(host) > 0

    def test_stun_servers_is_list(self):
        from slappyengine.net.discovery import _STUN_SERVERS
        assert isinstance(_STUN_SERVERS, list)

    def test_stun_servers_has_entries(self):
        from slappyengine.net.discovery import _STUN_SERVERS
        assert len(_STUN_SERVERS) >= 1

    def test_stun_servers_entries_are_tuples(self):
        from slappyengine.net.discovery import _STUN_SERVERS
        for entry in _STUN_SERVERS:
            assert isinstance(entry, tuple)
            assert len(entry) == 2

    def test_stun_servers_ports_are_ints(self):
        from slappyengine.net.discovery import _STUN_SERVERS
        for host, port in _STUN_SERVERS:
            assert isinstance(port, int)
            assert port > 0

    def test_stun_servers_include_google(self):
        from slappyengine.net.discovery import _STUN_SERVERS
        hosts = [h for h, _ in _STUN_SERVERS]
        assert any("google" in h.lower() for h in hosts)

    def test_discovery_module_importable(self):
        import slappyengine.net.discovery as d
        assert d is not None
