"""Tripwire for ``pharos_engine.visual_scripting``.

Backbone-only tests for the node-graph data model + 20-node starter
palette + Python codegen. The editor UI for the system lands in a
separate sprint and is tested there.
"""
from __future__ import annotations

import pytest


def test_module_imports_clean() -> None:
    from pharos_engine.visual_scripting import (
        Node, NodePort, NodeRegistry, NodeGraph, Edge,
        GraphValidationError, graph_to_python, python_to_graph,
        BUILTIN_NODES, BUILTIN_REGISTRY, get_node, list_nodes,
    )
    assert Node is not None
    assert NodePort is not None
    assert NodeRegistry is not None
    assert NodeGraph is not None
    assert Edge is not None
    assert GraphValidationError is not None
    assert graph_to_python is not None
    assert python_to_graph is not None
    assert BUILTIN_NODES is not None
    assert BUILTIN_REGISTRY is not None
    assert get_node is not None
    assert list_nodes is not None


def test_subpackage_attached_to_top_level() -> None:
    import pharos_engine
    mod = pharos_engine.visual_scripting
    assert mod is not None
    # cached subsequently
    assert pharos_engine.visual_scripting is mod


# ---------------------------------------------------------------------------
# NodePort / Node primitives
# ---------------------------------------------------------------------------


def test_nodeport_constructor_validates_port_kind() -> None:
    from pharos_engine.visual_scripting import NodePort
    with pytest.raises(ValueError):
        NodePort("p", "not_a_port_kind")


def test_node_constructor_validates_kind() -> None:
    from pharos_engine.visual_scripting import Node
    with pytest.raises(ValueError):
        Node(node_type="foo.bar", kind="not_a_kind")


def test_node_auto_assigns_id() -> None:
    from pharos_engine.visual_scripting import Node
    n1 = Node(node_type="x.y", kind="math")
    n2 = Node(node_type="x.y", kind="math")
    assert n1.id != n2.id
    assert n1.id.startswith("n_")


def test_node_clone_mints_new_id() -> None:
    from pharos_engine.visual_scripting import Node, NodePort
    n = Node(
        node_type="x.y", kind="math",
        outputs=[NodePort("o", "float")],
    )
    c = n.clone()
    assert c.id != n.id
    assert c.node_type == n.node_type


# ---------------------------------------------------------------------------
# NodeRegistry
# ---------------------------------------------------------------------------


def test_node_registry_register_and_get_roundtrip() -> None:
    from pharos_engine.visual_scripting import Node, NodePort, NodeRegistry
    reg = NodeRegistry()
    proto = Node(
        node_type="custom.identity",
        kind="math",
        inputs=[NodePort("x", "float")],
        outputs=[NodePort("y", "float")],
        to_python_template="{y} = {x}",
    )
    reg.register(proto)
    assert "custom.identity" in reg
    fetched = reg.get("custom.identity")
    assert fetched.node_type == "custom.identity"


def test_node_registry_duplicate_register_raises() -> None:
    from pharos_engine.visual_scripting import Node, NodeRegistry
    reg = NodeRegistry()
    n = Node(node_type="x.y", kind="math")
    reg.register(n)
    with pytest.raises(ValueError):
        reg.register(n)


def test_node_registry_spawn_returns_unique_id() -> None:
    from pharos_engine.visual_scripting import (
        BUILTIN_REGISTRY,
    )
    n1 = BUILTIN_REGISTRY.spawn("math.add")
    n2 = BUILTIN_REGISTRY.spawn("math.add")
    assert n1.id != n2.id
    assert n1.node_type == "math.add"


# ---------------------------------------------------------------------------
# 20 builtin palette
# ---------------------------------------------------------------------------


def test_builtin_nodes_count_is_20() -> None:
    from pharos_engine.visual_scripting import BUILTIN_NODES
    assert len(BUILTIN_NODES) == 20


def test_get_node_math_add_returns_add_def() -> None:
    from pharos_engine.visual_scripting import get_node
    add = get_node("math.add")
    assert add.node_type == "math.add"
    assert add.kind == "math"
    assert [p.name for p in add.inputs] == ["a", "b"]
    assert [p.name for p in add.outputs] == ["sum"]


def test_list_nodes_kind_math_returns_10_entries() -> None:
    from pharos_engine.visual_scripting import list_nodes
    math_nodes = list_nodes(kind="math")
    assert len(math_nodes) == 10
    types = {n.node_type for n in math_nodes}
    expected = {
        "math.constant", "math.add", "math.subtract", "math.multiply",
        "math.divide", "math.power", "math.sin", "math.cos",
        "math.lerp", "math.clamp",
    }
    assert types == expected


def test_list_nodes_kind_logic_returns_5_entries() -> None:
    from pharos_engine.visual_scripting import list_nodes
    assert len(list_nodes(kind="logic")) == 5


def test_list_nodes_kind_control_returns_3_entries() -> None:
    from pharos_engine.visual_scripting import list_nodes
    assert len(list_nodes(kind="control")) == 3


def test_list_nodes_kind_io_returns_2_entries() -> None:
    from pharos_engine.visual_scripting import list_nodes
    assert len(list_nodes(kind="io")) == 2


def test_every_builtin_has_template_or_is_control() -> None:
    from pharos_engine.visual_scripting import BUILTIN_NODES
    for n in BUILTIN_NODES:
        assert n.to_python_template, (
            f"node {n.node_type} missing to_python_template"
        )


# ---------------------------------------------------------------------------
# NodeGraph / Edge
# ---------------------------------------------------------------------------


def test_graph_add_node_and_edge_roundtrip() -> None:
    from pharos_engine.visual_scripting import NodeGraph, get_node
    g = NodeGraph(name="t")
    a = get_node("math.constant").clone()
    b = get_node("math.add").clone()
    g.add_node(a)
    g.add_node(b)
    g.add_edge(a, "value", b, "a")
    assert len(g.nodes) == 2
    assert len(g.edges) == 1
    assert g.edges[0].from_node_id == a.id
    assert g.edges[0].to_node_id == b.id


def test_graph_yaml_roundtrip_preserves_topology() -> None:
    from pharos_engine.visual_scripting import NodeGraph, get_node
    g = NodeGraph(name="rt")
    a = get_node("math.constant").clone()
    a.params["value"] = 2.5
    b = get_node("math.constant").clone()
    b.params["value"] = 4.5
    add = get_node("math.add").clone()
    g.add_node(a); g.add_node(b); g.add_node(add)
    g.add_edge(a, "value", add, "a")
    g.add_edge(b, "value", add, "b")

    text = g.to_yaml()
    g2 = NodeGraph.from_yaml(text)

    assert g2.name == "rt"
    assert len(g2.nodes) == 3
    assert len(g2.edges) == 2
    # node ids preserved
    g_ids = sorted(n.id for n in g.nodes)
    g2_ids = sorted(n.id for n in g2.nodes)
    assert g_ids == g2_ids
    # params preserved
    rt_const = next(n for n in g2.nodes if n.node_type == "math.constant"
                    and n.id == a.id)
    assert rt_const.params["value"] == 2.5


def test_graph_validate_detects_cycle() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, Edge, GraphValidationError, get_node,
    )
    g = NodeGraph()
    a = get_node("math.add").clone()
    b = get_node("math.add").clone()
    g.add_node(a); g.add_node(b)
    # a.sum -> b.a, b.sum -> a.a
    g.add_edge(a, "sum", b, "a")
    g.add_edge(b, "sum", a, "a")
    with pytest.raises(GraphValidationError):
        g.validate()


def test_graph_validate_detects_dangling_edge_ref() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, Edge, GraphValidationError, get_node,
    )
    g = NodeGraph()
    a = get_node("math.add").clone()
    g.add_node(a)
    g.edges.append(Edge(
        from_node_id="nonexistent",
        from_port="sum",
        to_node_id=a.id,
        to_port="a",
    ))
    with pytest.raises(GraphValidationError):
        g.validate()


def test_graph_validate_detects_port_kind_mismatch() -> None:
    from pharos_engine.visual_scripting import (
        Node, NodeGraph, NodePort, GraphValidationError,
    )
    g = NodeGraph()
    src = Node(
        node_type="x.src", kind="math",
        outputs=[NodePort("v", "vec3")],
        to_python_template="",
    )
    dst = Node(
        node_type="x.dst", kind="logic",
        inputs=[NodePort("v", "bool")],
        to_python_template="",
    )
    g.add_node(src); g.add_node(dst)
    g.add_edge(src, "v", dst, "v")
    with pytest.raises(GraphValidationError):
        g.validate()


def test_graph_validate_allows_int_to_float_widening() -> None:
    from pharos_engine.visual_scripting import Node, NodeGraph, NodePort
    g = NodeGraph()
    src = Node(
        node_type="x.src", kind="math",
        outputs=[NodePort("v", "int")],
        to_python_template="",
    )
    dst = Node(
        node_type="x.dst", kind="math",
        inputs=[NodePort("v", "float")],
        to_python_template="",
    )
    g.add_node(src); g.add_node(dst)
    g.add_edge(src, "v", dst, "v")
    # should not raise
    errors = g.validate(raise_on_error=False)
    assert errors == []


def test_topological_order_chain() -> None:
    from pharos_engine.visual_scripting import NodeGraph, get_node
    g = NodeGraph()
    a = get_node("math.constant").clone()
    b = get_node("math.add").clone()
    c = get_node("math.add").clone()
    g.add_node(a); g.add_node(b); g.add_node(c)
    g.add_edge(a, "value", b, "a")
    g.add_edge(b, "sum", c, "a")
    order = g.topological_order()
    ids = [n.id for n in order]
    assert ids.index(a.id) < ids.index(b.id)
    assert ids.index(b.id) < ids.index(c.id)


def test_topological_order_raises_on_cycle() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, GraphValidationError, get_node,
    )
    g = NodeGraph()
    a = get_node("math.add").clone()
    b = get_node("math.add").clone()
    g.add_node(a); g.add_node(b)
    g.add_edge(a, "sum", b, "a")
    g.add_edge(b, "sum", a, "a")
    with pytest.raises(GraphValidationError):
        g.topological_order()


# ---------------------------------------------------------------------------
# codegen
# ---------------------------------------------------------------------------


def test_graph_to_python_returns_str() -> None:
    from pharos_engine.visual_scripting import NodeGraph, graph_to_python
    g = NodeGraph()
    src = graph_to_python(g)
    assert isinstance(src, str)
    assert "def run():" in src


def test_graph_to_python_chain_compiles_and_runs() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, get_node, graph_to_python,
    )
    g = NodeGraph()
    a = get_node("math.constant").clone()
    a.params["value"] = 2.0
    b = get_node("math.constant").clone()
    b.params["value"] = 3.0
    add = get_node("math.add").clone()
    g.add_node(a); g.add_node(b); g.add_node(add)
    g.add_edge(a, "value", add, "a")
    g.add_edge(b, "value", add, "b")

    src = graph_to_python(g)
    ns: dict = {}
    exec(src, ns)
    result = ns["run"]()
    assert isinstance(result, dict)
    assert result["sum"] == 5.0


def test_graph_to_python_multiply_then_add_pipeline() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, get_node, graph_to_python,
    )
    g = NodeGraph()
    a = get_node("math.constant").clone()
    a.params["value"] = 4.0
    b = get_node("math.constant").clone()
    b.params["value"] = 5.0
    mul = get_node("math.multiply").clone()
    c = get_node("math.constant").clone()
    c.params["value"] = 1.0
    add = get_node("math.add").clone()
    g.add_node(a); g.add_node(b); g.add_node(c)
    g.add_node(mul); g.add_node(add)
    g.add_edge(a, "value", mul, "a")
    g.add_edge(b, "value", mul, "b")
    g.add_edge(mul, "product", add, "a")
    g.add_edge(c, "value", add, "b")

    src = graph_to_python(g)
    ns: dict = {}
    exec(src, ns)
    result = ns["run"]()
    # (4 * 5) + 1 == 21
    assert result["sum"] == 21.0


def test_graph_to_python_clamp_node_runs() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, get_node, graph_to_python,
    )
    g = NodeGraph()
    x = get_node("math.constant").clone()
    x.params["value"] = 5.0
    clamp = get_node("math.clamp").clone()
    g.add_node(x); g.add_node(clamp)
    g.add_edge(x, "value", clamp, "x")
    # lo/hi default to 0.0 / 1.0
    src = graph_to_python(g)
    ns: dict = {}
    exec(src, ns)
    result = ns["run"]()
    assert result["value"] == 1.0


def test_python_to_graph_reads_back_generated_code() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, get_node, graph_to_python, python_to_graph,
    )
    g = NodeGraph()
    a = get_node("math.constant").clone()
    a.params["value"] = 2.0
    b = get_node("math.constant").clone()
    b.params["value"] = 3.0
    add = get_node("math.add").clone()
    g.add_node(a); g.add_node(b); g.add_node(add)
    g.add_edge(a, "value", add, "a")
    g.add_edge(b, "value", add, "b")

    src = graph_to_python(g)
    g2 = python_to_graph(src)
    # We should recover 3 nodes and 2 edges (a->add, b->add).
    assert len(g2.nodes) == 3
    assert len(g2.edges) == 2


def test_python_to_graph_handles_empty_source() -> None:
    from pharos_engine.visual_scripting import python_to_graph
    g = python_to_graph("def f(): pass\n")
    assert len(g.nodes) == 0
    assert len(g.edges) == 0


def test_python_to_graph_raises_on_syntax_error() -> None:
    from pharos_engine.visual_scripting import python_to_graph
    with pytest.raises(ValueError):
        python_to_graph("def !!!! invalid")


def test_logic_compare_uses_param_op() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, get_node, graph_to_python,
    )
    g = NodeGraph()
    a = get_node("math.constant").clone()
    a.params["value"] = 3.0
    b = get_node("math.constant").clone()
    b.params["value"] = 3.0
    cmp_ = get_node("logic.compare").clone()
    cmp_.params["op"] = "=="
    g.add_node(a); g.add_node(b); g.add_node(cmp_)
    g.add_edge(a, "value", cmp_, "a")
    g.add_edge(b, "value", cmp_, "b")

    src = graph_to_python(g)
    ns: dict = {}
    exec(src, ns)
    result = ns["run"]()
    assert result["result"] is True


def test_control_return_terminates_function() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, get_node, graph_to_python,
    )
    g = NodeGraph()
    c = get_node("math.constant").clone()
    c.params["value"] = 42.0
    r = get_node("control.return").clone()
    g.add_node(c); g.add_node(r)
    g.add_edge(c, "value", r, "value")
    src = graph_to_python(g)
    ns: dict = {}
    exec(src, ns)
    assert ns["run"]() == 42.0


# ---------------------------------------------------------------------------
# edge / port introspection helpers
# ---------------------------------------------------------------------------


def test_graph_incoming_and_outgoing_edges() -> None:
    from pharos_engine.visual_scripting import NodeGraph, get_node
    g = NodeGraph()
    a = get_node("math.constant").clone()
    b = get_node("math.add").clone()
    g.add_node(a); g.add_node(b)
    g.add_edge(a, "value", b, "a")
    assert len(g.outgoing_edges(a.id)) == 1
    assert len(g.incoming_edges(b.id)) == 1
    assert len(g.outgoing_edges(b.id)) == 0


def test_graph_remove_node_drops_edges() -> None:
    from pharos_engine.visual_scripting import NodeGraph, get_node
    g = NodeGraph()
    a = get_node("math.constant").clone()
    b = get_node("math.add").clone()
    g.add_node(a); g.add_node(b)
    g.add_edge(a, "value", b, "a")
    g.remove_node(a.id)
    assert len(g.nodes) == 1
    assert len(g.edges) == 0


def test_ports_compatible_any_matches_everything() -> None:
    from pharos_engine.visual_scripting import ports_compatible, PORT_KINDS
    for kind in PORT_KINDS:
        assert ports_compatible("any", kind)
        assert ports_compatible(kind, "any")
