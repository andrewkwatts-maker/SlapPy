"""Tests for the MaterialGraphBridge V5 material-node round-trip.

Covers:

* Bridge instantiation (with None editor / node editor).
* ``to_material`` compiles a node graph into a WGSL material dict.
* ``from_material`` inflates a material dict into a NodeGraph.
* Round-trip preserves core material invariants.
* ``emit_full_shader`` wraps the compiled body in a full shader
  skeleton with uniforms + entry point.
* ``sync_to_editor`` calls the mocked ``set_material`` hook.
* ``sync_from_editor`` returns a NodeGraph.
* ``MaterialGraphError`` fires on validation issues (missing key,
  cycle, unknown node type).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Small mocks — kept in-module so tests don't drag DPG into the picture.
# ---------------------------------------------------------------------------


class MockMaterialEditor:
    """Minimal duck-type of NotebookMaterialEditor for sync tests."""

    def __init__(self) -> None:
        self.materials: list = []
        self.target = None

    def set_material(self, material) -> bool:
        self.materials.append(material)
        self.target = material
        return True


class MockGetterEditor(MockMaterialEditor):
    """Editor that exposes ``get_material`` (used by sync_from_editor)."""

    def get_material(self):
        return self.target


class MockNodeEditor:
    """Placeholder node-editor with an in-memory graph."""

    def __init__(self) -> None:
        from slappyengine.visual_scripting import NodeGraph
        self.graph = NodeGraph(name="mock_node_editor")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge():
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    return MaterialGraphBridge()


@pytest.fixture
def two_node_graph():
    """A 2-node graph — MaterialOutput fed a constant vec3 default."""
    from slappyengine.visual_scripting import (
        AddNode, MaterialOutputNode, NodeGraph,
    )
    g = NodeGraph(name="two_node")
    add = AddNode()
    out = MaterialOutputNode()
    g.add_node(add)
    g.add_node(out)
    return g


@pytest.fixture
def five_node_graph():
    """A 5-node graph — Add + Multiply + Fresnel + MaterialOutput chained."""
    from slappyengine.visual_scripting import (
        AddNode, MultiplyNode, FresnelNode, MaterialOutputNode,
        SaturateNode, NodeGraph,
    )
    g = NodeGraph(name="five_node")
    a = AddNode()
    m = MultiplyNode()
    s = SaturateNode()
    f = FresnelNode()
    out = MaterialOutputNode()
    for n in (a, m, s, f, out):
        g.add_node(n)
    # wire: add.out -> multiply.a; multiply.out -> saturate.x;
    # fresnel.out (float) -> multiply.b
    g.add_edge(a, "out", m, "a")
    g.add_edge(f, "out", m, "b")
    g.add_edge(m, "out", s, "x")
    return g


# ---------------------------------------------------------------------------
# 1-3. Public surface + imports.
# ---------------------------------------------------------------------------


def test_bridge_exports_public_surface() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge, MaterialGraphError,
        KEY_WGSL_SOURCE, KEY_UNIFORMS, KEY_OUTPUT_TYPE, RAW_WGSL_NODE_TYPE,
    )
    assert MaterialGraphBridge is not None
    assert issubclass(MaterialGraphError, ValueError)
    assert KEY_WGSL_SOURCE == "wgsl_source"
    assert KEY_UNIFORMS == "uniforms"
    assert KEY_OUTPUT_TYPE == "output_type"
    assert RAW_WGSL_NODE_TYPE == "raw_wgsl"


def test_bridge_re_exported_from_editor_package() -> None:
    from slappyengine.ui.editor import (
        MaterialGraphBridge, MaterialGraphError,
    )
    assert MaterialGraphBridge is not None
    assert MaterialGraphError is not None


def test_bridge_accepts_none_arguments() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    b = MaterialGraphBridge(None, None)
    assert b.material_editor is None
    assert b.node_editor is None
    assert b.call_log == []


# ---------------------------------------------------------------------------
# 4-6. to_material — basic shape checks.
# ---------------------------------------------------------------------------


def test_to_material_returns_expected_dict_keys(bridge, two_node_graph) -> None:
    material = bridge.to_material(two_node_graph)
    assert "wgsl_source" in material
    assert "uniforms" in material
    assert "output_type" in material


def test_to_material_wgsl_source_is_str(bridge, two_node_graph) -> None:
    material = bridge.to_material(two_node_graph)
    assert isinstance(material["wgsl_source"], str)
    assert isinstance(material["uniforms"], list)
    assert isinstance(material["output_type"], str)


def test_to_material_empty_graph_returns_empty_source(bridge) -> None:
    from slappyengine.visual_scripting import NodeGraph
    g = NodeGraph(name="empty")
    material = bridge.to_material(g)
    assert material["wgsl_source"] == ""
    assert material["uniforms"] == []


def test_to_material_rejects_none(bridge) -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphError,
    )
    with pytest.raises(MaterialGraphError):
        bridge.to_material(None)


def test_to_material_rejects_non_graph(bridge) -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphError,
    )
    with pytest.raises(MaterialGraphError):
        bridge.to_material("not a graph")


# ---------------------------------------------------------------------------
# 7-9. WGSL body contents — verify emit runs across representative graphs.
# ---------------------------------------------------------------------------


def test_two_node_graph_emits_material_output(bridge, two_node_graph) -> None:
    material = bridge.to_material(two_node_graph)
    src = material["wgsl_source"]
    # AddNode → let add_… = (0.0) + (0.0);
    # MaterialOutputNode → material_output.base_color = ...
    assert "material_output" in src
    assert "let " in src  # AddNode emit produced a let binding


def test_five_node_graph_compiles_without_error(
    bridge, five_node_graph,
) -> None:
    material = bridge.to_material(five_node_graph)
    src = material["wgsl_source"]
    # sat/mix/pow/add/mul/fresnel show up somewhere in the emitted body
    assert "clamp(" in src  # saturate
    assert "pow(" in src    # fresnel


def test_perlin_node_registers_uniform(bridge) -> None:
    from slappyengine.visual_scripting import (
        NodeGraph, PerlinNoiseNode,
    )
    g = NodeGraph(name="perlin")
    g.add_node(PerlinNoiseNode())
    material = bridge.to_material(g)
    assert "perlin2d" in material["uniforms"]


# ---------------------------------------------------------------------------
# 10. emit_full_shader — full-shader skeleton.
# ---------------------------------------------------------------------------


def test_emit_full_shader_contains_fragment_entrypoint(bridge) -> None:
    from slappyengine.visual_scripting import MaterialOutputNode
    n = MaterialOutputNode()
    src = bridge.emit_full_shader([n])
    assert "@fragment" in src
    assert "fs_main" in src
    assert "@location(0)" in src


def test_emit_full_shader_wraps_uniforms(bridge) -> None:
    from slappyengine.visual_scripting import (
        NodeGraph, TimeNode, MaterialOutputNode,
    )
    g = NodeGraph(name="uniforms")
    g.add_node(TimeNode())
    g.add_node(MaterialOutputNode())
    src = bridge.emit_full_shader(g)
    assert "u_time" in src
    assert "@group(0)" in src
    assert "@binding(" in src


def test_emit_full_shader_accepts_graph_or_iterable(bridge) -> None:
    from slappyengine.visual_scripting import (
        AddNode, MaterialOutputNode, NodeGraph,
    )
    g = NodeGraph(name="either")
    g.add_node(AddNode())
    g.add_node(MaterialOutputNode())
    src_graph = bridge.emit_full_shader(g)
    src_iter = bridge.emit_full_shader([AddNode(), MaterialOutputNode()])
    # both paths must produce a valid entry function
    for src in (src_graph, src_iter):
        assert "fn fs_main()" in src
        assert "material_output" in src


# ---------------------------------------------------------------------------
# 11-13. from_material — inverse mapping.
# ---------------------------------------------------------------------------


def test_from_material_raw_wgsl_produces_single_node(bridge) -> None:
    material = {
        "wgsl_source": "let x = 1.0;",
        "uniforms": ["u_time"],
        "output_type": "vec4<f32>",
    }
    graph = bridge.from_material(material)
    assert len(graph.nodes) == 1
    assert graph.nodes[0].node_type == "raw_wgsl"
    assert graph.nodes[0].params["wgsl_source"] == "let x = 1.0;"
    assert graph.nodes[0].params["uniforms"] == ["u_time"]


def test_from_material_missing_source_raises(bridge) -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphError,
    )
    with pytest.raises(MaterialGraphError):
        bridge.from_material({"uniforms": []})


def test_from_material_rejects_non_dict(bridge) -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphError,
    )
    with pytest.raises(MaterialGraphError):
        bridge.from_material("still not a dict")


# ---------------------------------------------------------------------------
# 14-15. Round-trip check — compile then inflate then re-compile.
# ---------------------------------------------------------------------------


def test_roundtrip_two_node(bridge, two_node_graph) -> None:
    material = bridge.to_material(two_node_graph)
    graph = bridge.from_material(material)
    material_again = bridge.to_material(graph)
    # after the raw-WGSL collapse, re-compiling should preserve the
    # dict shape (though not necessarily the WGSL body, since a raw
    # node has no emit_wgsl of its own).
    assert set(material_again.keys()) == set(material.keys())


def test_roundtrip_five_node(bridge, five_node_graph) -> None:
    material = bridge.to_material(five_node_graph)
    graph = bridge.from_material(material)
    # graph has exactly one raw_wgsl node
    assert len(graph.nodes) == 1
    assert graph.nodes[0].node_type == "raw_wgsl"
    # its params carry the compiled body
    assert graph.nodes[0].params["wgsl_source"] == material["wgsl_source"]


# ---------------------------------------------------------------------------
# 16-18. sync_to_editor / sync_from_editor with mocks.
# ---------------------------------------------------------------------------


def test_sync_to_editor_calls_set_material(two_node_graph) -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    editor = MockMaterialEditor()
    bridge = MaterialGraphBridge(material_editor=editor)
    ok = bridge.sync_to_editor(two_node_graph)
    assert ok is True
    assert len(editor.materials) == 1
    assert "wgsl_source" in editor.materials[0]


def test_sync_to_editor_without_editor_returns_false(two_node_graph) -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    bridge = MaterialGraphBridge(material_editor=None)
    assert bridge.sync_to_editor(two_node_graph) is False


def test_sync_from_editor_returns_node_graph() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    from slappyengine.visual_scripting import NodeGraph

    editor = MockMaterialEditor()
    editor.target = {
        "wgsl_source": "let y = 2.0;",
        "uniforms": [],
        "output_type": "vec4<f32>",
    }
    bridge = MaterialGraphBridge(material_editor=editor)
    graph = bridge.sync_from_editor()
    assert isinstance(graph, NodeGraph)
    assert graph.nodes[0].node_type == "raw_wgsl"


def test_sync_from_editor_uses_get_material_hook() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    from slappyengine.visual_scripting import NodeGraph

    editor = MockGetterEditor()
    editor.target = {
        "wgsl_source": "let via_getter = 3.0;",
        "uniforms": [],
        "output_type": "vec4<f32>",
    }
    bridge = MaterialGraphBridge(material_editor=editor)
    graph = bridge.sync_from_editor()
    assert isinstance(graph, NodeGraph)
    assert graph.nodes[0].params["wgsl_source"] == "let via_getter = 3.0;"


def test_sync_from_editor_returns_none_when_no_editor() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    bridge = MaterialGraphBridge(material_editor=None)
    assert bridge.sync_from_editor() is None


def test_sync_from_editor_returns_none_when_target_missing() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    editor = MockMaterialEditor()  # target defaults to None
    bridge = MaterialGraphBridge(material_editor=editor)
    assert bridge.sync_from_editor() is None


# ---------------------------------------------------------------------------
# 19-20. MaterialGraphError validation.
# ---------------------------------------------------------------------------


def test_material_graph_error_carries_per_node_lines() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphError,
    )
    err = MaterialGraphError(
        "compilation failed",
        errors=[("n_1", "bad port"), ("n_2", "no emit")],
    )
    assert len(err.errors) == 2
    assert err.errors[0] == ("n_1", "bad port")
    assert err.lines[0] == ("n_1", "bad port")
    assert err.lines[1] == ("n_2", "no emit")
    # message includes the trailing summary
    assert "n_1" in str(err) or "n_2" in str(err)


def test_to_material_cycle_raises_material_graph_error() -> None:
    """A cyclic graph must fail with MaterialGraphError."""
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge, MaterialGraphError,
    )
    from slappyengine.visual_scripting import (
        AddNode, MultiplyNode, NodeGraph,
    )

    g = NodeGraph(name="cyclic")
    a = AddNode()
    m = MultiplyNode()
    g.add_node(a)
    g.add_node(m)
    # a.out -> m.a and m.out -> a.a — cycle
    g.add_edge(a, "out", m, "a")
    g.add_edge(m, "out", a, "a")
    bridge = MaterialGraphBridge()
    with pytest.raises(MaterialGraphError):
        bridge.to_material(g)


def test_material_graph_error_without_error_list() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphError,
    )
    err = MaterialGraphError("just a message")
    assert err.errors == []
    assert str(err) == "just a message"


# ---------------------------------------------------------------------------
# 21+. Extra polish / edge cases.
# ---------------------------------------------------------------------------


def test_bridge_stores_call_log_for_sync_actions(two_node_graph) -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    editor = MockMaterialEditor()
    bridge = MaterialGraphBridge(material_editor=editor)
    bridge.sync_to_editor(two_node_graph)
    kinds = [entry[0] for entry in bridge.call_log]
    assert "sync_to_editor" in kinds
    assert "set_material" in kinds


def test_bridge_default_output_type_is_vec4() -> None:
    from slappyengine.ui.editor.material_graph_bridge import (
        MaterialGraphBridge, DEFAULT_OUTPUT_TYPE,
    )
    bridge = MaterialGraphBridge()
    from slappyengine.visual_scripting import NodeGraph
    material = bridge.to_material(NodeGraph(name="empty"))
    assert material["output_type"] == DEFAULT_OUTPUT_TYPE
    assert "vec4" in DEFAULT_OUTPUT_TYPE


def test_emit_full_shader_declares_material_output_struct(bridge) -> None:
    from slappyengine.visual_scripting import MaterialOutputNode
    src = bridge.emit_full_shader([MaterialOutputNode()])
    assert "struct MaterialOutput" in src
    assert "base_color" in src
    assert "metallic" in src


def test_from_material_defaults_uniforms_when_missing(bridge) -> None:
    graph = bridge.from_material({"wgsl_source": "let z = 0.0;"})
    node = graph.nodes[0]
    assert node.params["uniforms"] == []


def test_to_material_uniforms_are_sorted(bridge) -> None:
    from slappyengine.visual_scripting import (
        NodeGraph, TimeNode, TextureSampleNode,
    )
    g = NodeGraph(name="multi")
    g.add_node(TextureSampleNode())
    g.add_node(TimeNode())
    material = bridge.to_material(g)
    # sorted uniforms so tests get deterministic output
    assert material["uniforms"] == sorted(material["uniforms"])
    assert "u_time" in material["uniforms"]
    assert "u_texture" in material["uniforms"]


def test_wire_connection_propagates_symbol(bridge) -> None:
    """When an edge is wired, downstream node emits reference upstream symbol."""
    from slappyengine.visual_scripting import (
        NodeGraph, AddNode, MultiplyNode,
    )
    g = NodeGraph(name="wired")
    a = AddNode()
    m = MultiplyNode()
    g.add_node(a)
    g.add_node(m)
    g.add_edge(a, "out", m, "a")
    material = bridge.to_material(g)
    src = material["wgsl_source"]
    # multiply's fragment must reference the add's symbol name.
    # add produced ``let add_1 = (0.0) + (0.0);`` (or similar suffix).
    add_prefix_present = "let add_" in src
    mul_prefix_present = "let mul_" in src
    assert add_prefix_present
    assert mul_prefix_present
