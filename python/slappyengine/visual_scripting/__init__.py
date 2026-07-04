"""Visual scripting — graph data model + Python code generation.

This subpackage owns the *backbone* of the visual node graph: the
:class:`Node` / :class:`NodePort` / :class:`Edge` / :class:`NodeGraph`
data model, a YAML round-trip, a topological sort + validator, and a
Python code-generator that compiles graphs into runnable functions. The
editor UI that surfaces all of this lands in a separate sprint.

A starter palette of 20 builtin node prototypes ships under
:data:`BUILTIN_NODES` (10 math, 5 logic, 3 flow, 2 IO); each one is
registered into a process-wide :data:`BUILTIN_REGISTRY` so callers can
``get_node("math.add")`` without setting up their own registry.

Example
-------
>>> from slappyengine.visual_scripting import (
...     NodeGraph, get_node, graph_to_python,
... )
>>> g = NodeGraph(name="hello")
>>> a = get_node("math.constant").clone(); a.params["value"] = 2.0
>>> b = get_node("math.constant").clone(); b.params["value"] = 3.0
>>> add = get_node("math.add").clone()
>>> g.add_node(a); g.add_node(b); g.add_node(add)  # doctest: +ELLIPSIS
<...Node...>
>>> g.add_edge(a, "value", add, "a")  # doctest: +ELLIPSIS
Edge(...)
>>> g.add_edge(b, "value", add, "b")  # doctest: +ELLIPSIS
Edge(...)
>>> source = graph_to_python(g)
>>> "v_" in source
True

See :doc:`../docs/api/visual_scripting.md` for the full reference.
"""
from __future__ import annotations

from .codegen_python import graph_to_python, python_to_graph
from .graph import Edge, GraphValidationError, NodeGraph
from .node import (
    NODE_KINDS,
    PORT_KINDS,
    Node,
    NodeKind,
    NodePort,
    NodeRegistry,
    PortKind,
    ports_compatible,
)
from .palette import BUILTIN_NODES, BUILTIN_REGISTRY, get_node, list_nodes

# --- V5: material-graph WGSL node palette ---------------------------------
from .material_nodes import (
    MATERIAL_CATEGORY,
    MATERIAL_NODE_TYPES,
    AbsNode,
    AddNode,
    ClampNode,
    CrossNode,
    DefaultWgslEmitContext,
    DotNode,
    FresnelNode,
    GradientRampNode,
    LerpNode,
    MaterialNode,
    MaterialOutputNode,
    MultiplyNode,
    NormalizeNode,
    PerlinNoiseNode,
    PowerNode,
    SaturateNode,
    SqrtNode,
    TextureSampleNode,
    TimeNode,
    UVOffsetNode,
    WgslEmitContext,
    WorleyNoiseNode,
    register_material_nodes,
)


__all__ = [
    # node primitives
    "Node",
    "NodeKind",
    "NodePort",
    "PortKind",
    "NodeRegistry",
    "NODE_KINDS",
    "PORT_KINDS",
    "ports_compatible",
    # graph
    "Edge",
    "NodeGraph",
    "GraphValidationError",
    # codegen
    "graph_to_python",
    "python_to_graph",
    # palette
    "BUILTIN_NODES",
    "BUILTIN_REGISTRY",
    "get_node",
    "list_nodes",
    # V5: material-graph WGSL palette (append-only extension)
    "MaterialNode",
    "WgslEmitContext",
    "DefaultWgslEmitContext",
    "AddNode",
    "MultiplyNode",
    "LerpNode",
    "SaturateNode",
    "ClampNode",
    "PowerNode",
    "SqrtNode",
    "AbsNode",
    "DotNode",
    "NormalizeNode",
    "CrossNode",
    "FresnelNode",
    "PerlinNoiseNode",
    "WorleyNoiseNode",
    "GradientRampNode",
    "TextureSampleNode",
    "UVOffsetNode",
    "TimeNode",
    "MaterialOutputNode",
    "MATERIAL_NODE_TYPES",
    "MATERIAL_CATEGORY",
    "register_material_nodes",
]
