"""E1-I: NodeGraph compiler output mode tests.

Findings
--------
* There is NO compiler.py in the material package.
* NodeMaterial.compile() delegates entirely to the Rust extension
  ``pharos_engine._core.compile_node_graph(json_str)``.  If _core is absent
  (the common headless case) it raises RuntimeError — it does NOT produce any
  WGSL itself.
* Output mode is determined purely by which terminal NodeDef type is present
  in NodeMaterial._nodes (the ``output_mode`` property).
* There is no ConstantNode and no evaluate()/_evaluate() on any node type.
  All node "classes" are plain factory functions that return NodeDef dataclass
  instances; computation is exclusively in the Rust extension at runtime.
* ray_march is NOT in graph_schema.KNOWN_NODE_TYPES (gap — it exists in
  node_material.py but was never added to the schema frozenset).
"""
from __future__ import annotations

import json
import pytest


# ---------------------------------------------------------------------------
# Helper: build a minimal NodeMaterial graph without importing from the
# package-level __init__ (avoids the eager deform_modes import chain).
# ---------------------------------------------------------------------------
from pharos_engine.material.node_material import (
    NodeDef,
    NodeMaterial,
    UVNode,
    PixelColorNode,
    PixelChannelNode,
    AddNode,
    MultiplyNode,
    LerpNode,
    ClampNode,
    GravityWarpNode,
    SampleTextureNode,
    FinalColorNode,
    DiscardNode,
    ReadFieldNode,
    WriteFieldNode,
    SampleSimFieldNode,
    SinNode,
    CosNode,
    PowNode,
    RemapNode,
    LengthNode,
    NormalizeNode,
    DotNode,
    NoiseNode,
    WorldPosNode,
    TimeNode,
    OffsetUVNode,
    ReflectUVNode,
    AccumulateNode,
    RayMarchNode,
    ForceOutputNode,
    ReduceOutputNode,
)


# ---------------------------------------------------------------------------
# TestNodeGraphNodes
# ---------------------------------------------------------------------------

class TestNodeGraphNodes:
    """Verify all node factory functions are importable and return NodeDef."""

    _FACTORIES = [
        ("UVNode",           lambda: UVNode()),
        ("PixelColorNode",   lambda: PixelColorNode()),
        ("PixelChannelNode", lambda: PixelChannelNode("r")),
        ("AddNode",          lambda: AddNode()),
        ("MultiplyNode",     lambda: MultiplyNode()),
        ("LerpNode",         lambda: LerpNode()),
        ("ClampNode",        lambda: ClampNode()),
        ("GravityWarpNode",  lambda: GravityWarpNode()),
        ("SampleTextureNode",lambda: SampleTextureNode()),
        ("FinalColorNode",   lambda: FinalColorNode()),
        ("DiscardNode",      lambda: DiscardNode()),
        ("ReadFieldNode",    lambda: ReadFieldNode("health")),
        ("WriteFieldNode",   lambda: WriteFieldNode("density")),
        ("SampleSimFieldNode",lambda: SampleSimFieldNode()),
        ("SinNode",          lambda: SinNode()),
        ("CosNode",          lambda: CosNode()),
        ("PowNode",          lambda: PowNode()),
        ("RemapNode",        lambda: RemapNode()),
        ("LengthNode",       lambda: LengthNode()),
        ("NormalizeNode",    lambda: NormalizeNode()),
        ("DotNode",          lambda: DotNode()),
        ("NoiseNode",        lambda: NoiseNode()),
        ("WorldPosNode",     lambda: WorldPosNode()),
        ("TimeNode",         lambda: TimeNode()),
        ("OffsetUVNode",     lambda: OffsetUVNode()),
        ("ReflectUVNode",    lambda: ReflectUVNode()),
        ("AccumulateNode",   lambda: AccumulateNode()),
        ("RayMarchNode",     lambda: RayMarchNode()),
        ("ForceOutputNode",  lambda: ForceOutputNode()),
        ("ReduceOutputNode", lambda: ReduceOutputNode()),
    ]

    def test_all_node_types_importable(self):
        """Every factory function must be importable and callable without error."""
        for name, factory in self._FACTORIES:
            node = factory()
            assert isinstance(node, NodeDef), (
                f"{name}() did not return a NodeDef — got {type(node)}"
            )

    def test_all_nodes_have_non_empty_id(self):
        for name, factory in self._FACTORIES:
            node = factory()
            assert node.id and len(node.id) > 0, f"{name}() returned empty id"

    def test_all_nodes_have_node_type_string(self):
        for name, factory in self._FACTORIES:
            node = factory()
            assert isinstance(node.node_type, str) and node.node_type, (
                f"{name}() has empty node_type"
            )

    def test_node_ids_are_unique(self):
        """Two calls to the same factory produce distinct IDs."""
        a = UVNode()
        b = UVNode()
        assert a.id != b.id

    # ConstantNode / evaluate — these do NOT exist in the current codebase.
    # The tests below document this explicitly so the sprint audit is clear.

    def test_no_constant_node_in_module(self):
        """ConstantNode is NOT defined; node computation is Rust-side only."""
        import pharos_engine.material.node_material as nm
        assert not hasattr(nm, "ConstantNode"), (
            "ConstantNode now exists — update E1-I tests to cover evaluate()."
        )

    def test_no_evaluate_method_on_nodedef(self):
        """NodeDef is a plain dataclass; there is no CPU-side evaluate()."""
        node = UVNode()
        assert not hasattr(node, "evaluate"), (
            "evaluate() now exists on NodeDef — add CPU evaluation tests."
        )

    def test_clamp_node_params_stored(self):
        node = ClampNode(min_val=0.2, max_val=0.8)
        assert node.params["min"] == pytest.approx(0.2)
        assert node.params["max"] == pytest.approx(0.8)

    def test_gravity_warp_params(self):
        node = GravityWarpNode(strength=5.0, radius=0.1)
        assert node.params["strength"] == pytest.approx(5.0)
        assert node.params["radius"] == pytest.approx(0.1)

    def test_pow_node_exponent_param(self):
        node = PowNode(exponent=3.0)
        assert node.params["exponent"] == pytest.approx(3.0)

    def test_ray_march_node_steps_and_direction(self):
        node = RayMarchNode(steps=8, direction=(1.0, 0.0))
        assert node.params["steps"] == 8
        assert node.params["direction"] == [1.0, 0.0]

    def test_accumulate_decay_param(self):
        node = AccumulateNode(decay=0.95)
        assert node.params["decay"] == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# TestCompilerOutputModes
# ---------------------------------------------------------------------------

class TestCompilerOutputModes:
    """output_mode property — determined by which terminal node is present."""

    def test_final_color_node_gives_render_mode(self):
        m = NodeMaterial("render_mat")
        m.node(FinalColorNode())
        assert m.output_mode == "render"

    def test_write_field_node_gives_sim_write_mode(self):
        m = NodeMaterial("sim_mat")
        m.node(WriteFieldNode("density"))
        assert m.output_mode == "sim_write"

    def test_force_output_node_gives_force_mode(self):
        m = NodeMaterial("force_mat")
        m.node(ForceOutputNode())
        assert m.output_mode == "force"

    def test_reduce_output_node_gives_reduce_mode(self):
        m = NodeMaterial("reduce_mat")
        m.node(ReduceOutputNode())
        assert m.output_mode == "reduce"

    def test_empty_material_defaults_to_render(self):
        m = NodeMaterial("empty")
        assert m.output_mode == "render"

    def test_output_mode_ignores_non_terminal_nodes(self):
        """Intermediate nodes (UV, Add, …) must not flip the output mode."""
        m = NodeMaterial("mix")
        m.node(UVNode())
        m.node(AddNode())
        m.node(WriteFieldNode("foo"))
        assert m.output_mode == "sim_write"

    def test_render_mode_compile_raises_without_core(self):
        """compile() raises RuntimeError when _core is unavailable — not a stub."""
        import pharos_engine
        if pharos_engine.HAS_NATIVE:
            pytest.skip("_core is present; compile() would attempt real WGSL generation")
        m = NodeMaterial("render_mat")
        m.node(FinalColorNode())
        with pytest.raises(RuntimeError, match="_core"):
            m.compile()

    def test_sim_write_mode_compile_raises_without_core(self):
        import pharos_engine
        if pharos_engine.HAS_NATIVE:
            pytest.skip("_core is present; compile() would attempt real WGSL generation")
        m = NodeMaterial("sim_mat")
        m.node(WriteFieldNode("density"))
        with pytest.raises(RuntimeError, match="_core"):
            m.compile()

    def test_force_mode_compile_raises_without_core(self):
        import pharos_engine
        if pharos_engine.HAS_NATIVE:
            pytest.skip("_core is present; compile() would attempt real WGSL generation")
        m = NodeMaterial("force_mat")
        m.node(ForceOutputNode())
        with pytest.raises(RuntimeError, match="_core"):
            m.compile()


# ---------------------------------------------------------------------------
# TestCompiledWGSL
# ---------------------------------------------------------------------------

class TestCompiledWGSL:
    """When _core IS present, compile() must return a non-empty WGSL string."""

    def _require_core(self):
        import pharos_engine
        if not pharos_engine.HAS_NATIVE:
            pytest.skip("_core Rust extension not available in this environment")

    def test_render_output_compile_returns_string(self):
        self._require_core()
        m = NodeMaterial("render_mat")
        m.node(UVNode())
        m.node(SampleTextureNode())
        m.node(FinalColorNode())
        result = m.compile()
        assert isinstance(result, str) and result, "compile() returned empty string"

    @pytest.mark.xfail(reason="Rust _core.compile_node_graph does not yet support write_field/read_field node types")
    def test_sim_write_mode_compile_returns_string(self):
        self._require_core()
        m = NodeMaterial("sim_mat")
        m.node(ReadFieldNode("density"))
        m.node(WriteFieldNode("density"))
        result = m.compile()
        assert isinstance(result, str) and result

    @pytest.mark.xfail(reason="Rust _core.compile_node_graph does not yet support force_output node type")
    def test_force_mode_compile_returns_string(self):
        self._require_core()
        m = NodeMaterial("force_mat")
        m.node(ForceOutputNode())
        result = m.compile()
        assert isinstance(result, str) and result

    def test_render_output_has_entry_point(self):
        """Compiled WGSL must contain a @compute or @fragment entry point."""
        self._require_core()
        m = NodeMaterial("render_ep")
        m.node(FinalColorNode())
        wgsl = m.compile()
        assert "@compute" in wgsl or "@fragment" in wgsl, (
            f"Expected @compute or @fragment in WGSL output; got:\n{wgsl[:500]}"
        )

    def test_wgsl_property_set_after_compile(self):
        """NodeMaterial.wgsl property must be set to the compiled string."""
        self._require_core()
        m = NodeMaterial("wgsl_prop")
        m.node(FinalColorNode())
        result = m.compile()
        assert m.wgsl == result

    def test_wgsl_is_none_before_compile(self):
        """wgsl property is None until compile() is called."""
        m = NodeMaterial("fresh")
        assert m.wgsl is None

    @pytest.mark.xfail(reason="Rust _core.compile_node_graph does not yet support force_output node type")
    def test_force_output_wgsl_references_force(self):
        """ForceOutputNode graph WGSL should reference force semantics."""
        self._require_core()
        m = NodeMaterial("force_wgsl")
        m.node(ForceOutputNode())
        wgsl = m.compile()
        # The Rust compiler should emit something force-related
        assert any(kw in wgsl.lower() for kw in ("force", "fx", "fy", "vec2")), (
            f"WGSL for ForceOutputNode graph has no force-related keywords:\n{wgsl[:500]}"
        )


# ---------------------------------------------------------------------------
# TestNodeMaterialSerialization (compile-path adjacency checks)
# ---------------------------------------------------------------------------

class TestNodeMaterialSerializationForCompiler:
    """Ensure the JSON fed to compile() is correctly structured."""

    def test_to_json_is_valid_json(self):
        m = NodeMaterial("ser")
        m.node(UVNode())
        data = json.loads(m.to_json())
        assert "nodes" in data and "edges" in data

    def test_node_type_preserved_in_json(self):
        m = NodeMaterial("types")
        m.node(FinalColorNode())
        m.node(WriteFieldNode("foo"))
        m.node(ForceOutputNode())
        data = json.loads(m.to_json())
        types = {n["type"] for n in data["nodes"]}
        assert "FinalColor" in types
        assert "write_field" in types
        assert "force_output" in types

    def test_edges_preserved_in_json(self):
        m = NodeMaterial("edges")
        uv = m.node(UVNode())
        tex = m.node(SampleTextureNode())
        fc = m.node(FinalColorNode())
        m.connect(uv, "uv", tex, "uv")
        m.connect(tex, "color", fc, "color")
        data = json.loads(m.to_json())
        assert len(data["edges"]) == 2

    def test_from_json_roundtrip_preserves_output_mode(self):
        m = NodeMaterial("roundtrip")
        m.node(WriteFieldNode("heat"))
        json_str = m.to_json()
        m2 = NodeMaterial.from_json("roundtrip", json_str)
        assert m2.output_mode == "sim_write"

    def test_reduce_output_roundtrip(self):
        m = NodeMaterial("reduce")
        m.node(ReduceOutputNode(field="alpha", op="mean"))
        json_str = m.to_json()
        m2 = NodeMaterial.from_json("reduce", json_str)
        assert m2.output_mode == "reduce"


# ---------------------------------------------------------------------------
# TestGraphSchemaRayMarch — documents a known gap
# ---------------------------------------------------------------------------

class TestGraphSchemaRayMarch:
    """ray_march gap fixed: added to KNOWN_NODE_TYPES and KNOWN_PORT_TYPES in graph_schema.py."""

    def test_ray_march_in_known_node_types(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        assert "ray_march" in KNOWN_NODE_TYPES

    def test_ray_march_validate_no_unknown_warning(self):
        """validate_node_graph() must not flag ray_march as unknown type."""
        from pharos_engine.material.graph_schema import validate_node_graph
        node = RayMarchNode()
        graph = {
            "nodes": [{"id": node.id, "type": node.node_type, "params": node.params}],
            "edges": [],
        }
        errors = validate_node_graph(graph)
        assert not any("unknown node type" in e and "ray_march" in e for e in errors)
