"""Tripwire for the material-graph WGSL node palette (V5).

Covers:

* Each of the 19 material-graph node types instantiates cleanly and
  exposes the right ``input_ports`` / ``output_ports`` shape.
* :func:`register_material_nodes` populates a fresh :class:`NodeRegistry`
  with every prototype (and refuses to double-register).
* Round-trip via the graph YAML serialiser preserves ``node_type`` and
  ``params`` for a graph built from material nodes.
* :meth:`emit_wgsl` returns syntactically-plausible WGSL for a spread
  of representative nodes (add / fresnel / perlin / material output).
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx():
    from pharos_engine.visual_scripting import DefaultWgslEmitContext
    return DefaultWgslEmitContext()


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_module_exports_material_symbols() -> None:
    from pharos_engine.visual_scripting import (
        MaterialNode,
        WgslEmitContext,
        DefaultWgslEmitContext,
        AddNode, MultiplyNode, LerpNode, SaturateNode, ClampNode,
        PowerNode, SqrtNode, AbsNode, DotNode, NormalizeNode, CrossNode,
        FresnelNode, PerlinNoiseNode, WorleyNoiseNode, GradientRampNode,
        TextureSampleNode, UVOffsetNode, TimeNode, MaterialOutputNode,
        MATERIAL_NODE_TYPES, MATERIAL_CATEGORY, register_material_nodes,
    )
    assert MaterialNode is not None
    assert WgslEmitContext is not None
    assert DefaultWgslEmitContext is not None
    assert MATERIAL_CATEGORY == "Material"
    assert register_material_nodes is not None
    # ensure the master list contains all the classes we imported
    assert len(MATERIAL_NODE_TYPES) >= 18
    for cls in (
        AddNode, MultiplyNode, LerpNode, SaturateNode, ClampNode,
        PowerNode, SqrtNode, AbsNode, DotNode, NormalizeNode, CrossNode,
        FresnelNode, PerlinNoiseNode, WorleyNoiseNode, GradientRampNode,
        TextureSampleNode, UVOffsetNode, TimeNode, MaterialOutputNode,
    ):
        assert cls in MATERIAL_NODE_TYPES


def test_all_material_node_types_subclass_node() -> None:
    from pharos_engine.visual_scripting import (
        MATERIAL_NODE_TYPES, Node, MaterialNode,
    )
    for cls in MATERIAL_NODE_TYPES:
        assert issubclass(cls, MaterialNode)
        assert issubclass(cls, Node)


def test_material_node_count_meets_spec() -> None:
    from pharos_engine.visual_scripting import MATERIAL_NODE_TYPES
    assert len(MATERIAL_NODE_TYPES) >= 18
    # the shipped palette is 19 (18 body nodes + MaterialOutput root)
    assert len(MATERIAL_NODE_TYPES) == 19


def test_sampler2d_added_to_port_kinds() -> None:
    from pharos_engine.visual_scripting import PORT_KINDS, ports_compatible
    assert "sampler2d" in PORT_KINDS
    assert ports_compatible("sampler2d", "sampler2d")
    assert ports_compatible("any", "sampler2d")
    assert ports_compatible("sampler2d", "any")
    # sampler2d does NOT flow into float / vec3 etc.
    assert not ports_compatible("sampler2d", "float")


# ---------------------------------------------------------------------------
# Per-node port-shape checks — one test per node type (19 tests)
# ---------------------------------------------------------------------------


def _assert_ports(node, in_names, in_kinds, out_names, out_kinds):
    assert [p.name for p in node.input_ports] == in_names
    assert [p.port_kind for p in node.input_ports] == in_kinds
    assert [p.name for p in node.output_ports] == out_names
    assert [p.port_kind for p in node.output_ports] == out_kinds
    # aliases stay in sync with the underlying dataclass fields
    assert node.input_ports is node.inputs
    assert node.output_ports is node.outputs


def test_add_node_ports() -> None:
    from pharos_engine.visual_scripting import AddNode
    n = AddNode()
    _assert_ports(n, ["a", "b"], ["float", "float"], ["out"], ["float"])
    assert n.node_type == "material.add"
    assert n.default_params == {}


def test_multiply_node_ports() -> None:
    from pharos_engine.visual_scripting import MultiplyNode
    n = MultiplyNode()
    _assert_ports(n, ["a", "b"], ["float", "float"], ["out"], ["float"])
    assert n.node_type == "material.multiply"


def test_lerp_node_ports() -> None:
    from pharos_engine.visual_scripting import LerpNode
    n = LerpNode()
    _assert_ports(n, ["a", "b", "t"], ["float", "float", "float"],
                  ["out"], ["float"])
    assert n.node_type == "material.lerp"


def test_saturate_node_ports() -> None:
    from pharos_engine.visual_scripting import SaturateNode
    n = SaturateNode()
    _assert_ports(n, ["x"], ["float"], ["out"], ["float"])
    assert n.node_type == "material.saturate"


def test_clamp_node_ports_and_defaults() -> None:
    from pharos_engine.visual_scripting import ClampNode
    n = ClampNode()
    _assert_ports(n, ["x"], ["float"], ["out"], ["float"])
    assert n.default_params == {"min": 0.0, "max": 1.0}
    assert n.params["min"] == 0.0
    assert n.params["max"] == 1.0


def test_power_node_ports() -> None:
    from pharos_engine.visual_scripting import PowerNode
    n = PowerNode()
    _assert_ports(n, ["base", "exp"], ["float", "float"],
                  ["out"], ["float"])


def test_sqrt_node_ports() -> None:
    from pharos_engine.visual_scripting import SqrtNode
    n = SqrtNode()
    _assert_ports(n, ["x"], ["float"], ["out"], ["float"])


def test_abs_node_ports() -> None:
    from pharos_engine.visual_scripting import AbsNode
    n = AbsNode()
    _assert_ports(n, ["x"], ["float"], ["out"], ["float"])


def test_dot_node_ports() -> None:
    from pharos_engine.visual_scripting import DotNode
    n = DotNode()
    _assert_ports(n, ["a", "b"], ["vec3", "vec3"], ["out"], ["float"])


def test_normalize_node_ports() -> None:
    from pharos_engine.visual_scripting import NormalizeNode
    n = NormalizeNode()
    _assert_ports(n, ["v"], ["vec3"], ["out"], ["vec3"])


def test_cross_node_ports() -> None:
    from pharos_engine.visual_scripting import CrossNode
    n = CrossNode()
    _assert_ports(n, ["a", "b"], ["vec3", "vec3"], ["out"], ["vec3"])


def test_fresnel_node_ports_and_default_strength() -> None:
    from pharos_engine.visual_scripting import FresnelNode
    n = FresnelNode()
    _assert_ports(n, ["normal", "view"], ["vec3", "vec3"],
                  ["out"], ["float"])
    assert n.default_params == {"strength": 1.0}
    assert n.params["strength"] == 1.0


def test_perlin_noise_node_ports_and_params() -> None:
    from pharos_engine.visual_scripting import PerlinNoiseNode
    n = PerlinNoiseNode()
    _assert_ports(n, ["uv"], ["vec2"], ["out"], ["float"])
    assert n.default_params == {"frequency": 1.0, "octaves": 1}


def test_worley_noise_node_ports_and_params() -> None:
    from pharos_engine.visual_scripting import WorleyNoiseNode
    n = WorleyNoiseNode()
    _assert_ports(n, ["uv"], ["vec2"], ["out"], ["float"])
    assert n.default_params == {"frequency": 4.0}


def test_gradient_ramp_node_ports_and_stops() -> None:
    from pharos_engine.visual_scripting import GradientRampNode
    n = GradientRampNode()
    _assert_ports(n, ["t"], ["float"], ["out"], ["vec4"])
    stops = n.default_params["stops"]
    assert len(stops) == 2
    for stop in stops:
        assert len(stop) == 4  # (t, r, g, b)


def test_texture_sample_node_ports() -> None:
    from pharos_engine.visual_scripting import TextureSampleNode
    n = TextureSampleNode()
    _assert_ports(n, ["tex", "uv"], ["sampler2d", "vec2"],
                  ["out"], ["vec4"])
    assert n.default_params["texture"] == "u_texture"
    assert n.default_params["sampler"] == "u_sampler"


def test_uv_offset_node_ports() -> None:
    from pharos_engine.visual_scripting import UVOffsetNode
    n = UVOffsetNode()
    _assert_ports(n, ["uv", "offset"], ["vec2", "vec2"],
                  ["out"], ["vec2"])


def test_time_node_ports() -> None:
    from pharos_engine.visual_scripting import TimeNode
    n = TimeNode()
    _assert_ports(n, [], [], ["out"], ["float"])


def test_material_output_node_ports() -> None:
    from pharos_engine.visual_scripting import MaterialOutputNode
    n = MaterialOutputNode()
    _assert_ports(
        n,
        ["base_color", "metallic", "roughness", "emissive", "normal"],
        ["vec3", "float", "float", "vec3", "vec3"],
        [], [],
    )


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


def test_register_material_nodes_fills_registry() -> None:
    from pharos_engine.visual_scripting import (
        NodeRegistry, register_material_nodes, MATERIAL_NODE_TYPES,
    )
    reg = NodeRegistry()
    assert len(reg) == 0
    registered = register_material_nodes(reg)
    assert len(reg) == len(MATERIAL_NODE_TYPES)
    assert len(registered) == len(MATERIAL_NODE_TYPES)
    for cls in MATERIAL_NODE_TYPES:
        assert cls.NODE_TYPE in reg


def test_register_material_nodes_tags_material_category() -> None:
    from pharos_engine.visual_scripting import (
        NodeRegistry, register_material_nodes, MATERIAL_CATEGORY,
    )
    reg = NodeRegistry()
    register_material_nodes(reg)
    for proto in reg.values():
        assert proto.params.get("_category") == MATERIAL_CATEGORY


def test_register_material_nodes_rejects_non_registry() -> None:
    from pharos_engine.visual_scripting import register_material_nodes
    with pytest.raises(TypeError):
        register_material_nodes("not_a_registry")


def test_register_material_nodes_double_register_raises() -> None:
    from pharos_engine.visual_scripting import (
        NodeRegistry, register_material_nodes,
    )
    reg = NodeRegistry()
    register_material_nodes(reg)
    with pytest.raises(ValueError):
        register_material_nodes(reg)


def test_registered_prototypes_can_be_spawned() -> None:
    from pharos_engine.visual_scripting import (
        NodeRegistry, register_material_nodes,
    )
    reg = NodeRegistry()
    register_material_nodes(reg)
    spawned = reg.spawn("material.fresnel")
    assert spawned.node_type == "material.fresnel"
    # spawn returns a clone with a fresh id
    other = reg.spawn("material.fresnel")
    assert spawned.id != other.id


# ---------------------------------------------------------------------------
# Graph serialisation round-trip
# ---------------------------------------------------------------------------


def test_material_graph_yaml_round_trip() -> None:
    from pharos_engine.visual_scripting import (
        NodeGraph, NodeRegistry, register_material_nodes,
    )
    reg = NodeRegistry()
    register_material_nodes(reg)
    g = NodeGraph(name="mat_graph")
    add = reg.spawn("material.add")
    fresnel = reg.spawn("material.fresnel", params={"strength": 2.5})
    output = reg.spawn("material.output")
    g.add_node(add)
    g.add_node(fresnel)
    g.add_node(output)
    g.add_edge(fresnel, "out", output, "metallic")

    src = g.to_yaml()
    g2 = NodeGraph.from_yaml(src)
    assert g2.name == "mat_graph"
    assert len(g2.nodes) == 3
    types = [n.node_type for n in g2.nodes]
    assert "material.add" in types
    assert "material.fresnel" in types
    assert "material.output" in types
    fresnel2 = next(n for n in g2.nodes if n.node_type == "material.fresnel")
    assert fresnel2.params.get("strength") == 2.5
    assert len(g2.edges) == 1
    assert g2.edges[0].from_port == "out"
    assert g2.edges[0].to_port == "metallic"


# ---------------------------------------------------------------------------
# emit_wgsl — syntactic-plausibility spot-checks
# ---------------------------------------------------------------------------


def test_emit_wgsl_add(ctx) -> None:
    from pharos_engine.visual_scripting import AddNode
    src = AddNode().emit_wgsl(ctx, inputs={"a": "x", "b": "y"})
    assert "let add_" in src
    assert "+" in src
    assert "(x)" in src and "(y)" in src


def test_emit_wgsl_multiply(ctx) -> None:
    from pharos_engine.visual_scripting import MultiplyNode
    src = MultiplyNode().emit_wgsl(ctx, inputs={"a": "u", "b": "v"})
    assert "let mul_" in src
    assert "*" in src


def test_emit_wgsl_lerp_uses_mix(ctx) -> None:
    from pharos_engine.visual_scripting import LerpNode
    src = LerpNode().emit_wgsl(ctx, inputs={"a": "aa", "b": "bb", "t": "tt"})
    assert "mix(aa, bb, tt)" in src


def test_emit_wgsl_saturate_clamps_unit_range(ctx) -> None:
    from pharos_engine.visual_scripting import SaturateNode
    src = SaturateNode().emit_wgsl(ctx, inputs={"x": "q"})
    assert "clamp(q, 0.0, 1.0)" in src


def test_emit_wgsl_clamp_uses_param_range(ctx) -> None:
    from pharos_engine.visual_scripting import ClampNode
    n = ClampNode()
    n.params["min"] = -2.0
    n.params["max"] = 3.0
    src = n.emit_wgsl(ctx, inputs={"x": "z"})
    assert "-2.0" in src and "3.0" in src
    assert "clamp(z" in src


def test_emit_wgsl_power_uses_pow(ctx) -> None:
    from pharos_engine.visual_scripting import PowerNode
    src = PowerNode().emit_wgsl(ctx, inputs={"base": "b", "exp": "e"})
    assert "pow(b, e)" in src


def test_emit_wgsl_sqrt_uses_sqrt(ctx) -> None:
    from pharos_engine.visual_scripting import SqrtNode
    src = SqrtNode().emit_wgsl(ctx, inputs={"x": "q"})
    assert "sqrt(" in src


def test_emit_wgsl_abs_uses_abs(ctx) -> None:
    from pharos_engine.visual_scripting import AbsNode
    src = AbsNode().emit_wgsl(ctx, inputs={"x": "q"})
    assert "abs(q)" in src


def test_emit_wgsl_dot_uses_dot(ctx) -> None:
    from pharos_engine.visual_scripting import DotNode
    src = DotNode().emit_wgsl(ctx, inputs={"a": "n", "b": "v"})
    assert "dot(n, v)" in src


def test_emit_wgsl_normalize_uses_normalize(ctx) -> None:
    from pharos_engine.visual_scripting import NormalizeNode
    src = NormalizeNode().emit_wgsl(ctx, inputs={"v": "vv"})
    assert "normalize(vv)" in src


def test_emit_wgsl_cross_uses_cross(ctx) -> None:
    from pharos_engine.visual_scripting import CrossNode
    src = CrossNode().emit_wgsl(ctx, inputs={"a": "aa", "b": "bb"})
    assert "cross(aa, bb)" in src


def test_emit_wgsl_fresnel_uses_pow_5(ctx) -> None:
    from pharos_engine.visual_scripting import FresnelNode
    n = FresnelNode()
    n.params["strength"] = 0.75
    src = n.emit_wgsl(ctx, inputs={"normal": "N", "view": "V"})
    # must contain the 5-th power fresnel signature
    assert "pow(" in src
    assert "5.0" in src
    assert "dot(N, V)" in src
    assert "0.75" in src
    assert "let fresnel_" in src


def test_emit_wgsl_perlin_uses_helper_and_octaves(ctx) -> None:
    from pharos_engine.visual_scripting import PerlinNoiseNode
    n = PerlinNoiseNode()
    n.params["octaves"] = 4
    n.params["frequency"] = 2.0
    src = n.emit_wgsl(ctx, inputs={"uv": "uv0"})
    assert "perlin2d" in src
    assert "for" in src
    # marks the perlin helper as required
    assert "perlin2d" in ctx.used_uniforms
    # frequency is reflected as initial f value
    assert "2.0" in src


def test_emit_wgsl_worley_uses_distance_search(ctx) -> None:
    from pharos_engine.visual_scripting import WorleyNoiseNode
    src = WorleyNoiseNode().emit_wgsl(ctx, inputs={"uv": "uv0"})
    assert "distance" in src
    assert "for" in src


def test_emit_wgsl_gradient_ramp_builds_mix_chain(ctx) -> None:
    from pharos_engine.visual_scripting import GradientRampNode
    n = GradientRampNode()
    n.params["stops"] = [
        (0.0, 1.0, 0.0, 0.0),
        (0.5, 0.0, 1.0, 0.0),
        (1.0, 0.0, 0.0, 1.0),
    ]
    src = n.emit_wgsl(ctx, inputs={"t": "tt"})
    assert "mix(" in src
    assert "vec4<f32>" in src
    assert "let ramp_" in src


def test_emit_wgsl_texture_sample_uses_texture_sample(ctx) -> None:
    from pharos_engine.visual_scripting import TextureSampleNode
    src = TextureSampleNode().emit_wgsl(ctx, inputs={"uv": "uv0"})
    assert "textureSample(" in src
    # binding names registered as uniforms
    assert "u_texture" in ctx.used_uniforms
    assert "u_sampler" in ctx.used_uniforms


def test_emit_wgsl_uv_offset_is_vec_add(ctx) -> None:
    from pharos_engine.visual_scripting import UVOffsetNode
    src = UVOffsetNode().emit_wgsl(ctx,
                                    inputs={"uv": "uv0", "offset": "d"})
    assert "uv0 + d" in src


def test_emit_wgsl_time_registers_uniform(ctx) -> None:
    from pharos_engine.visual_scripting import TimeNode
    src = TimeNode().emit_wgsl(ctx)
    assert "u_time" in src
    assert "u_time" in ctx.used_uniforms


def test_emit_wgsl_material_output_writes_channels(ctx) -> None:
    from pharos_engine.visual_scripting import MaterialOutputNode
    src = MaterialOutputNode().emit_wgsl(ctx, inputs={
        "base_color": "col",
        "metallic": "m",
        "roughness": "r",
        "emissive": "e",
        "normal": "n",
    })
    assert "material_output.base_color = col;" in src
    assert "material_output.metallic = m;" in src
    assert "material_output.roughness = r;" in src
    assert "material_output.emissive = e;" in src
    assert "material_output.normal = n;" in src


# ---------------------------------------------------------------------------
# Emit context behaviour
# ---------------------------------------------------------------------------


def test_default_wgsl_context_allocates_unique_symbols() -> None:
    from pharos_engine.visual_scripting import DefaultWgslEmitContext
    ctx = DefaultWgslEmitContext()
    s1 = ctx.alloc_symbol("foo")
    s2 = ctx.alloc_symbol("foo")
    assert s1 != s2
    assert s1.startswith("foo_")
    assert s2.startswith("foo_")


def test_default_wgsl_context_sanitises_bad_prefix() -> None:
    from pharos_engine.visual_scripting import DefaultWgslEmitContext
    ctx = DefaultWgslEmitContext()
    s = ctx.alloc_symbol("hi there!")
    # symbol is a valid WGSL identifier (no spaces / punctuation)
    for ch in s:
        assert ch.isalnum() or ch == "_"


def test_default_wgsl_context_tracks_uniforms() -> None:
    from pharos_engine.visual_scripting import (
        DefaultWgslEmitContext, TimeNode, TextureSampleNode,
    )
    ctx = DefaultWgslEmitContext()
    TimeNode().emit_wgsl(ctx)
    TextureSampleNode().emit_wgsl(ctx, inputs={"uv": "uv0"})
    assert "u_time" in ctx.used_uniforms
    assert "u_texture" in ctx.used_uniforms
    assert "u_sampler" in ctx.used_uniforms


# ---------------------------------------------------------------------------
# Kind / integration
# ---------------------------------------------------------------------------


def test_material_nodes_use_render_kind() -> None:
    from pharos_engine.visual_scripting import MATERIAL_NODE_TYPES
    for cls in MATERIAL_NODE_TYPES:
        n = cls()
        assert n.kind == "render"


def test_material_node_types_have_unique_node_type_keys() -> None:
    from pharos_engine.visual_scripting import MATERIAL_NODE_TYPES
    keys = [cls.NODE_TYPE for cls in MATERIAL_NODE_TYPES]
    assert len(keys) == len(set(keys))
    for k in keys:
        assert k.startswith("material.")


def test_material_node_clone_mints_new_id() -> None:
    from pharos_engine.visual_scripting import FresnelNode
    n = FresnelNode()
    c = n.clone()
    assert c.id != n.id
    assert c.node_type == n.node_type


def test_material_node_default_params_is_a_copy() -> None:
    from pharos_engine.visual_scripting import FresnelNode
    n = FresnelNode()
    dp = n.default_params
    dp["strength"] = 999.0
    # mutating the returned dict must not leak into the class-level default
    assert FresnelNode().default_params["strength"] == 1.0
