"""
Tests for the node-based material graph system.

The NodeMaterial class lives in playslap.material.node_material, which is
being created by a parallel agent.  Every import of that subpackage is wrapped
in a try/except ImportError so the suite degrades gracefully when the module
(or the Rust _core extension) is not yet present.
"""
import json
import pytest


# ---------------------------------------------------------------------------
# test_node_def_auto_id
# ---------------------------------------------------------------------------

def test_node_def_auto_id():
    try:
        from playslap.material.node_material import NodeDef, UVNode
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    n = UVNode()
    assert isinstance(n.id, str)
    assert len(n.id) > 0
    assert n.node_type == "UV"


# ---------------------------------------------------------------------------
# test_node_def_ids_are_unique
# ---------------------------------------------------------------------------

def test_node_def_ids_are_unique():
    try:
        from playslap.material.node_material import UVNode
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    ids = {UVNode().id for _ in range(50)}
    assert len(ids) == 50


# ---------------------------------------------------------------------------
# test_node_material_build_and_serialize
# ---------------------------------------------------------------------------

def test_node_material_build_and_serialize():
    try:
        from playslap.material.node_material import (
            NodeMaterial,
            UVNode,
            GravityWarpNode,
            SampleTextureNode,
            FinalColorNode,
        )
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    mat = NodeMaterial("test")
    uv = mat.node(UVNode())
    warp = mat.node(GravityWarpNode(strength=1.5, radius=0.2))
    sample = mat.node(SampleTextureNode())
    out = mat.node(FinalColorNode())

    mat.connect(uv, "uv", warp, "uv")
    mat.connect(warp, "out_uv", sample, "uv")
    mat.connect(sample, "color", out, "color")

    j = mat.to_json()
    graph = json.loads(j)

    assert len(graph["nodes"]) == 4
    assert len(graph["edges"]) == 3


# ---------------------------------------------------------------------------
# test_node_material_roundtrip
# ---------------------------------------------------------------------------

def test_node_material_roundtrip():
    try:
        from playslap.material.node_material import (
            NodeMaterial,
            UVNode,
            FinalColorNode,
        )
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    mat = NodeMaterial("rt")
    mat.node(UVNode())
    mat.node(FinalColorNode())

    j = mat.to_json()
    mat2 = NodeMaterial.from_json("rt2", j)

    assert len(mat2._nodes) == 2
    assert mat2._nodes[0].node_type == "UV"


# ---------------------------------------------------------------------------
# test_node_material_roundtrip_name
# ---------------------------------------------------------------------------

def test_node_material_roundtrip_name():
    """from_json must use the supplied name, not one from the JSON blob."""
    try:
        from playslap.material.node_material import (
            NodeMaterial,
            UVNode,
        )
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    mat = NodeMaterial("original")
    mat.node(UVNode())

    mat2 = NodeMaterial.from_json("overridden", mat.to_json())
    assert mat2.name == "overridden"


# ---------------------------------------------------------------------------
# test_node_material_json_structure
# ---------------------------------------------------------------------------

def test_node_material_json_structure():
    """Serialised JSON must contain top-level 'nodes' and 'edges' keys."""
    try:
        from playslap.material.node_material import NodeMaterial, UVNode
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    mat = NodeMaterial("s")
    mat.node(UVNode())
    graph = json.loads(mat.to_json())

    assert "nodes" in graph
    assert "edges" in graph
    assert isinstance(graph["nodes"], list)
    assert isinstance(graph["edges"], list)


# ---------------------------------------------------------------------------
# test_node_material_node_entries
# ---------------------------------------------------------------------------

def test_node_material_node_entries():
    """Each serialised node must carry at least 'id' and 'type'."""
    try:
        from playslap.material.node_material import (
            NodeMaterial,
            UVNode,
            FinalColorNode,
        )
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    mat = NodeMaterial("s")
    uv = mat.node(UVNode())
    mat.node(FinalColorNode())

    graph = json.loads(mat.to_json())
    node_map = {n["id"]: n for n in graph["nodes"]}

    assert uv.id in node_map
    assert node_map[uv.id]["type"] == "UV"


# ---------------------------------------------------------------------------
# test_graph_schema_valid
# ---------------------------------------------------------------------------

def test_graph_schema_valid():
    try:
        from playslap.material.graph_schema import validate_node_graph
    except ImportError:
        pytest.skip("playslap.material.graph_schema not available")

    graph = {
        "nodes": [
            {"id": "a", "type": "UV", "params": {}},
            {"id": "b", "type": "FinalColor", "params": {}},
        ],
        "edges": [
            {
                "from_node": "a",
                "from_port": "uv",
                "to_node": "b",
                "to_port": "color",
            }
        ],
    }
    errors = validate_node_graph(graph)
    assert errors == []


# ---------------------------------------------------------------------------
# test_graph_schema_duplicate_ids
# ---------------------------------------------------------------------------

def test_graph_schema_duplicate_ids():
    try:
        from playslap.material.graph_schema import validate_node_graph
    except ImportError:
        pytest.skip("playslap.material.graph_schema not available")

    graph = {
        "nodes": [
            {"id": "a", "type": "UV", "params": {}},
            {"id": "a", "type": "FinalColor", "params": {}},  # duplicate id
        ],
        "edges": [],
    }
    errors = validate_node_graph(graph)
    assert any("duplicate" in e.lower() or "unique" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# test_graph_schema_bad_edge_ref
# ---------------------------------------------------------------------------

def test_graph_schema_bad_edge_ref():
    try:
        from playslap.material.graph_schema import validate_node_graph
    except ImportError:
        pytest.skip("playslap.material.graph_schema not available")

    graph = {
        "nodes": [{"id": "a", "type": "UV", "params": {}}],
        "edges": [
            {
                "from_node": "MISSING",
                "from_port": "uv",
                "to_node": "a",
                "to_port": "uv",
            }
        ],
    }
    errors = validate_node_graph(graph)
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# test_graph_schema_empty_graph
# ---------------------------------------------------------------------------

def test_graph_schema_empty_graph():
    try:
        from playslap.material.graph_schema import validate_node_graph
    except ImportError:
        pytest.skip("playslap.material.graph_schema not available")

    graph = {"nodes": [], "edges": []}
    errors = validate_node_graph(graph)
    # An empty graph is structurally valid (no duplicate ids, no bad refs)
    assert isinstance(errors, list)


# ---------------------------------------------------------------------------
# test_graph_schema_edge_to_missing_target
# ---------------------------------------------------------------------------

def test_graph_schema_edge_to_missing_target():
    try:
        from playslap.material.graph_schema import validate_node_graph
    except ImportError:
        pytest.skip("playslap.material.graph_schema not available")

    graph = {
        "nodes": [{"id": "a", "type": "UV", "params": {}}],
        "edges": [
            {
                "from_node": "a",
                "from_port": "uv",
                "to_node": "NONEXISTENT",
                "to_port": "color",
            }
        ],
    }
    errors = validate_node_graph(graph)
    assert len(errors) > 0


# ---------------------------------------------------------------------------
# test_node_material_compile_requires_core
# ---------------------------------------------------------------------------

def test_node_material_compile_requires_core():
    try:
        from playslap.material.node_material import (
            NodeMaterial,
            UVNode,
            FinalColorNode,
        )
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    mat = NodeMaterial("test")
    mat.node(UVNode())
    mat.node(FinalColorNode())

    try:
        mat.compile()
    except RuntimeError:
        # Expected when _core is not built — compile signals this via RuntimeError
        pass
    except Exception:
        # If _core IS built, compile() should succeed without raising; any
        # other exception type would be a real bug, but we let it propagate
        # naturally so pytest reports it.
        raise


# ---------------------------------------------------------------------------
# test_gravity_warp_node_params
# ---------------------------------------------------------------------------

def test_gravity_warp_node_params():
    try:
        from playslap.material.node_material import GravityWarpNode
    except ImportError:
        pytest.skip("playslap.material.node_material not available")

    node = GravityWarpNode(strength=2.0, radius=0.5)
    assert node.node_type == "GravityWarp"
    # Params must be preserved
    assert node.params.get("strength") == pytest.approx(2.0)
    assert node.params.get("radius") == pytest.approx(0.5)
