"""PBR material graph — Python node graph that compiles to a WGSL fragment shader.

Node graph inspired by Nova3D `AdvancedMaterial` / `MaterialGraphEditor`, but
implemented in pure Python for the Pharos PyPI wrapper. Constant folding and
uniform baking are delegated to `_core.material_eval.bake_material_constants`
when the Rust core is available.

Baseline (DDD5, 2026-07-19): 10 core node types. The remaining ~20 Nova3D
node types are follow-up sprints.

Not to be confused with `render/material.py::PbrMaterial` (a flat dataclass) —
this module lives alongside it and extends its expressiveness.

Public node types (10):
    ConstFloatNode, ConstColorNode, UVNode, Texture2DNode, MultiplyNode,
    AddNode, MixNode, NormalMapNode, FresnelNode, PBROutputNode.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

# ---------------------------------------------------------------------------
# Slot / edge primitives
# ---------------------------------------------------------------------------

_DTYPES = frozenset({"float", "vec2", "vec3", "vec4", "sampler2D"})


@dataclass
class MaterialSlot:
    """A single input or output port on a node.

    Attributes
    ----------
    name : str
        Slot name (e.g. ``"a"``, ``"albedo"``, ``"out"``).
    dtype : str
        One of ``float``, ``vec2``, ``vec3``, ``vec4``, ``sampler2D``.
    """

    name: str
    dtype: str

    def __post_init__(self) -> None:
        if self.dtype not in _DTYPES:
            raise ValueError(
                f"MaterialSlot.dtype must be one of {sorted(_DTYPES)}, got {self.dtype!r}"
            )


@dataclass
class _Edge:
    from_node: str
    from_slot: str
    to_node: str
    to_slot: str


# ---------------------------------------------------------------------------
# Node base class
# ---------------------------------------------------------------------------


class MaterialNode:
    """Base class for every material graph node.

    Subclasses populate ``inputs`` / ``outputs`` and implement
    :meth:`emit_wgsl`, which returns a small WGSL snippet that computes each
    output as a local variable named ``{node.name}_{slot_name}``.
    """

    #: Class-level marker — set True in nodes whose output can NOT be constant-
    #: folded (texture samples, UV coord, etc).
    dynamic: bool = False

    def __init__(self, name: str) -> None:
        self.name: str = name
        self.inputs: dict[str, MaterialSlot] = {}
        self.outputs: dict[str, MaterialSlot] = {}
        self.params: dict[str, Any] = {}
        # Populated by MaterialGraph.compile — maps input slot name to
        # "producing_node.output_slot" wire name for emit_wgsl().
        self._wires: dict[str, str] = {}

    # ------------------------------------------------------------------ helpers
    def _wire(self, slot: str, default: str) -> str:
        """Return the WGSL variable name feeding ``slot`` (or ``default``)."""
        return self._wires.get(slot, default)

    def var(self, slot: str) -> str:
        """Return the WGSL variable name this node emits for ``slot``."""
        return f"{self.name}_{slot}"

    # ------------------------------------------------------------------ API
    def emit_wgsl(self, binding_index_start: int) -> str:  # pragma: no cover
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": type(self).__name__,
            "params": self.params,
        }


# ---------------------------------------------------------------------------
# Core node types (10)
# ---------------------------------------------------------------------------


class ConstFloatNode(MaterialNode):
    """Outputs a compile-time float constant."""

    def __init__(self, name: str, value: float = 0.5) -> None:
        super().__init__(name)
        self.params = {"value": float(value)}
        self.outputs["out"] = MaterialSlot("out", "float")

    def emit_wgsl(self, binding_index_start: int) -> str:
        v = float(self.params["value"])
        return f"    let {self.var('out')} : f32 = {v:.6}f;"


class ConstColorNode(MaterialNode):
    """Outputs a compile-time RGBA constant."""

    def __init__(self, name: str, r: float = 1.0, g: float = 1.0, b: float = 1.0, a: float = 1.0) -> None:
        super().__init__(name)
        self.params = {"r": float(r), "g": float(g), "b": float(b), "a": float(a)}
        self.outputs["out"] = MaterialSlot("out", "vec4")

    def emit_wgsl(self, binding_index_start: int) -> str:
        p = self.params
        return (
            f"    let {self.var('out')} : vec4<f32> = "
            f"vec4<f32>({p['r']:.6}f, {p['g']:.6}f, {p['b']:.6}f, {p['a']:.6}f);"
        )


class UVNode(MaterialNode):
    """Outputs the interpolated fragment UV coordinate."""

    dynamic = True

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.outputs["uv"] = MaterialSlot("uv", "vec2")

    def emit_wgsl(self, binding_index_start: int) -> str:
        return f"    let {self.var('uv')} : vec2<f32> = in_uv;"


class Texture2DNode(MaterialNode):
    """Samples a 2D texture at the fragment UV. Emits @group(1) @binding(N)."""

    dynamic = True

    def __init__(self, name: str, texture_path: str = "") -> None:
        super().__init__(name)
        self.params = {"texture_path": str(texture_path)}
        self.inputs["uv"] = MaterialSlot("uv", "vec2")
        self.outputs["rgba"] = MaterialSlot("rgba", "vec4")

    def emit_wgsl(self, binding_index_start: int) -> str:
        uv = self._wire("uv", "in_uv")
        tex_var = f"{self.name}_tex"
        smp_var = f"{self.name}_smp"
        idx_tex = binding_index_start
        idx_smp = binding_index_start + 1
        return (
            f"@group(1) @binding({idx_tex}) var {tex_var} : texture_2d<f32>;\n"
            f"@group(1) @binding({idx_smp}) var {smp_var} : sampler;\n"
            f"__BODY__    let {self.var('rgba')} : vec4<f32> = "
            f"textureSample({tex_var}, {smp_var}, {uv});"
        )


class MultiplyNode(MaterialNode):
    """Component-wise multiply (a * b). Both inputs typed as vec4."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.inputs["a"] = MaterialSlot("a", "vec4")
        self.inputs["b"] = MaterialSlot("b", "vec4")
        self.outputs["out"] = MaterialSlot("out", "vec4")

    def emit_wgsl(self, binding_index_start: int) -> str:
        a = self._wire("a", "vec4<f32>(1.0)")
        b = self._wire("b", "vec4<f32>(1.0)")
        return f"    let {self.var('out')} : vec4<f32> = {a} * {b};"


class AddNode(MaterialNode):
    """Component-wise add (a + b)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.inputs["a"] = MaterialSlot("a", "vec4")
        self.inputs["b"] = MaterialSlot("b", "vec4")
        self.outputs["out"] = MaterialSlot("out", "vec4")

    def emit_wgsl(self, binding_index_start: int) -> str:
        a = self._wire("a", "vec4<f32>(0.0)")
        b = self._wire("b", "vec4<f32>(0.0)")
        return f"    let {self.var('out')} : vec4<f32> = {a} + {b};"


class MixNode(MaterialNode):
    """Linear interpolation mix(a, b, t)."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.inputs["a"] = MaterialSlot("a", "vec4")
        self.inputs["b"] = MaterialSlot("b", "vec4")
        self.inputs["t"] = MaterialSlot("t", "float")
        self.outputs["out"] = MaterialSlot("out", "vec4")

    def emit_wgsl(self, binding_index_start: int) -> str:
        a = self._wire("a", "vec4<f32>(0.0)")
        b = self._wire("b", "vec4<f32>(1.0)")
        t = self._wire("t", "0.5f")
        return f"    let {self.var('out')} : vec4<f32> = mix({a}, {b}, {t});"


class NormalMapNode(MaterialNode):
    """Sample a tangent-space normal map and rotate into world space.

    Assumes fragment inputs ``in_tangent`` / ``in_bitangent`` / ``in_normal``
    are declared by the vertex stage (see WGSL_HEADER).
    """

    dynamic = True

    def __init__(self, name: str, texture_path: str = "") -> None:
        super().__init__(name)
        self.params = {"texture_path": str(texture_path)}
        self.outputs["normal"] = MaterialSlot("normal", "vec3")

    def emit_wgsl(self, binding_index_start: int) -> str:
        tex_var = f"{self.name}_tex"
        smp_var = f"{self.name}_smp"
        idx_tex = binding_index_start
        idx_smp = binding_index_start + 1
        return (
            f"@group(1) @binding({idx_tex}) var {tex_var} : texture_2d<f32>;\n"
            f"@group(1) @binding({idx_smp}) var {smp_var} : sampler;\n"
            f"__BODY__    let {self.name}_ts : vec3<f32> = "
            f"textureSample({tex_var}, {smp_var}, in_uv).xyz * 2.0f - 1.0f;\n"
            f"    let {self.var('normal')} : vec3<f32> = normalize(\n"
            f"        in_tangent * {self.name}_ts.x +\n"
            f"        in_bitangent * {self.name}_ts.y +\n"
            f"        in_normal * {self.name}_ts.z);"
        )


class FresnelNode(MaterialNode):
    """Schlick's Fresnel approximation. Emits a float [0, 1]."""

    def __init__(self, name: str, power: float = 5.0) -> None:
        super().__init__(name)
        self.params = {"power": float(power)}
        self.outputs["out"] = MaterialSlot("out", "float")

    def emit_wgsl(self, binding_index_start: int) -> str:
        p = float(self.params["power"])
        return (
            f"    let {self.name}_ndv : f32 = max(dot(in_normal, in_view_dir), 0.0f);\n"
            f"    let {self.var('out')} : f32 = pow(1.0f - {self.name}_ndv, {p:.6}f);"
        )


class PBROutputNode(MaterialNode):
    """Terminal node — emits the WGSL @fragment entry point.

    Inputs default sensibly when unwired so partial graphs still compile.
    """

    def __init__(self, name: str = "output") -> None:
        super().__init__(name)
        self.inputs["albedo"] = MaterialSlot("albedo", "vec4")
        self.inputs["metallic"] = MaterialSlot("metallic", "float")
        self.inputs["roughness"] = MaterialSlot("roughness", "float")
        self.inputs["normal"] = MaterialSlot("normal", "vec3")
        self.inputs["emissive"] = MaterialSlot("emissive", "vec3")

    def emit_wgsl(self, binding_index_start: int) -> str:
        albedo = self._wire("albedo", "vec4<f32>(1.0)")
        metallic = self._wire("metallic", "0.0f")
        roughness = self._wire("roughness", "0.5f")
        normal = self._wire("normal", "in_normal")
        emissive = self._wire("emissive", "vec3<f32>(0.0)")
        return (
            f"    let out_albedo : vec4<f32> = {albedo};\n"
            f"    let out_metallic : f32 = {metallic};\n"
            f"    let out_roughness : f32 = {roughness};\n"
            f"    let out_normal : vec3<f32> = {normal};\n"
            f"    let out_emissive : vec3<f32> = {emissive};\n"
            f"    let lit : vec3<f32> = out_albedo.rgb * (1.0f - out_metallic) + out_emissive;\n"
            f"    return vec4<f32>(lit, out_albedo.a);"
        )


# Registry for YAML load
_NODE_TYPES: dict[str, type[MaterialNode]] = {
    cls.__name__: cls
    for cls in (
        ConstFloatNode,
        ConstColorNode,
        UVNode,
        Texture2DNode,
        MultiplyNode,
        AddNode,
        MixNode,
        NormalMapNode,
        FresnelNode,
        PBROutputNode,
    )
}


# ---------------------------------------------------------------------------
# Graph container
# ---------------------------------------------------------------------------


_WGSL_HEADER = """// Auto-generated by pharos_engine.render.material_graph
struct FragIn {
    @location(0) in_uv : vec2<f32>,
    @location(1) in_normal : vec3<f32>,
    @location(2) in_tangent : vec3<f32>,
    @location(3) in_bitangent : vec3<f32>,
    @location(4) in_view_dir : vec3<f32>,
};
"""


@dataclass
class MaterialGraph:
    """Container of :class:`MaterialNode` objects + wires between them."""

    nodes: dict[str, MaterialNode] = field(default_factory=dict)
    edges: list[_Edge] = field(default_factory=list)

    # ------------------------------------------------------------------ mutation
    def add_node(self, node: MaterialNode) -> MaterialNode:
        if node.name in self.nodes:
            raise ValueError(f"MaterialGraph already contains a node named {node.name!r}")
        self.nodes[node.name] = node
        return node

    def connect(
        self,
        from_node: MaterialNode | str,
        from_slot: str,
        to_node: MaterialNode | str,
        to_slot: str,
    ) -> None:
        fn = from_node.name if isinstance(from_node, MaterialNode) else from_node
        tn = to_node.name if isinstance(to_node, MaterialNode) else to_node
        if fn not in self.nodes:
            raise KeyError(f"unknown from_node {fn!r}")
        if tn not in self.nodes:
            raise KeyError(f"unknown to_node {tn!r}")
        if from_slot not in self.nodes[fn].outputs:
            raise KeyError(f"{fn!r} has no output slot {from_slot!r}")
        if to_slot not in self.nodes[tn].inputs:
            raise KeyError(f"{tn!r} has no input slot {to_slot!r}")
        self.edges.append(_Edge(fn, from_slot, tn, to_slot))

    # ------------------------------------------------------------------ compile
    def _topo_order(self) -> list[MaterialNode]:
        in_deg = {n: 0 for n in self.nodes}
        adj: dict[str, list[str]] = {n: [] for n in self.nodes}
        for e in self.edges:
            in_deg[e.to_node] += 1
            adj[e.from_node].append(e.to_node)
        queue = [n for n, d in in_deg.items() if d == 0]
        order: list[str] = []
        while queue:
            queue.sort()  # deterministic order for stable output
            n = queue.pop(0)
            order.append(n)
            for m in adj[n]:
                in_deg[m] -= 1
                if in_deg[m] == 0:
                    queue.append(m)
        if len(order) != len(self.nodes):
            raise RuntimeError("MaterialGraph contains a cycle")
        return [self.nodes[n] for n in order]

    def compile(self) -> str:
        """Emit a complete WGSL fragment shader for this graph."""
        # Wire inputs on each node from the edge list.
        for node in self.nodes.values():
            node._wires = {}
        for e in self.edges:
            src = self.nodes[e.from_node]
            self.nodes[e.to_node]._wires[e.to_slot] = src.var(e.from_slot)

        ordered = self._topo_order()
        # PBROutputNode must be last (unique).
        outs = [n for n in ordered if isinstance(n, PBROutputNode)]
        if len(outs) != 1:
            raise RuntimeError(
                f"MaterialGraph must contain exactly one PBROutputNode (found {len(outs)})"
            )
        # Move the single PBROutputNode to the end while preserving relative
        # order of the remaining nodes.
        ordered = [n for n in ordered if not isinstance(n, PBROutputNode)] + outs

        decls: list[str] = []
        body: list[str] = []
        binding_idx = 0
        for node in ordered:
            snippet = node.emit_wgsl(binding_idx)
            # Nodes that declare a binding split their emit at the __BODY__
            # marker into (decl, body).
            if "__BODY__" in snippet:
                decl, rest = snippet.split("__BODY__", 1)
                decls.append(decl.rstrip())
                body.append(rest)
                # Texture nodes consume 2 bindings (texture + sampler).
                if isinstance(node, (Texture2DNode, NormalMapNode)):
                    binding_idx += 2
            else:
                body.append(snippet)

        parts: list[str] = [_WGSL_HEADER]
        parts.extend(decls)
        parts.append("@fragment")
        parts.append("fn main(in : FragIn) -> @location(0) vec4<f32> {")
        parts.append("    let in_uv : vec2<f32> = in.in_uv;")
        parts.append("    let in_normal : vec3<f32> = in.in_normal;")
        parts.append("    let in_tangent : vec3<f32> = in.in_tangent;")
        parts.append("    let in_bitangent : vec3<f32> = in.in_bitangent;")
        parts.append("    let in_view_dir : vec3<f32> = in.in_view_dir;")
        parts.extend(body)
        parts.append("}")
        return "\n".join(parts) + "\n"

    # ------------------------------------------------------------------ YAML
    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self.nodes.values()],
            "edges": [
                {
                    "from_node": e.from_node,
                    "from_slot": e.from_slot,
                    "to_node": e.to_node,
                    "to_slot": e.to_slot,
                }
                for e in self.edges
            ],
        }

    def save(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MaterialGraph:
        g = cls()
        for n in data.get("nodes", []):
            typ = _NODE_TYPES[n["type"]]
            params = n.get("params", {}) or {}
            # Every node subclass takes `name` + kwargs matching self.params.
            node = typ(n["name"], **params)
            g.add_node(node)
        for e in data.get("edges", []):
            g.connect(e["from_node"], e["from_slot"], e["to_node"], e["to_slot"])
        return g

    @classmethod
    def load(cls, path: str) -> MaterialGraph:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.from_dict(data)


__all__ = [
    "MaterialSlot",
    "MaterialNode",
    "MaterialGraph",
    "ConstFloatNode",
    "ConstColorNode",
    "UVNode",
    "Texture2DNode",
    "MultiplyNode",
    "AddNode",
    "MixNode",
    "NormalMapNode",
    "FresnelNode",
    "PBROutputNode",
]
