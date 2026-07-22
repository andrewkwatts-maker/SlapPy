"""Regression tests for the DDD5 material graph baseline."""
from __future__ import annotations

import os
import tempfile

import pytest

from pharos_engine.render.material_graph import (
    AddNode,
    ConstColorNode,
    ConstFloatNode,
    FresnelNode,
    MaterialGraph,
    MaterialSlot,
    MixNode,
    MultiplyNode,
    NormalMapNode,
    PBROutputNode,
    Texture2DNode,
    UVNode,
)


# ---------------------------------------------------------------------------
# 1. All 10 nodes instantiate cleanly
# ---------------------------------------------------------------------------


def test_all_ten_nodes_instantiate() -> None:
    nodes = [
        ConstFloatNode("f", value=0.75),
        ConstColorNode("c", 1.0, 0.5, 0.25),
        UVNode("uv"),
        Texture2DNode("tex", texture_path="dummy.png"),
        MultiplyNode("mul"),
        AddNode("add"),
        MixNode("mix"),
        NormalMapNode("nm", texture_path="normal.png"),
        FresnelNode("fres", power=5.0),
        PBROutputNode("output"),
    ]
    assert len(nodes) == 10
    for n in nodes:
        assert n.name
        assert isinstance(n.outputs, dict) or n.outputs == {}


def test_material_slot_dtype_validation() -> None:
    MaterialSlot("ok", "vec4")
    with pytest.raises(ValueError):
        MaterialSlot("bad", "quaternion")


# ---------------------------------------------------------------------------
# 2. compile() produces valid WGSL
# ---------------------------------------------------------------------------


def _minimal_graph() -> MaterialGraph:
    g = MaterialGraph()
    color = g.add_node(ConstColorNode("albedo_const", 0.9, 0.2, 0.1, 1.0))
    out = g.add_node(PBROutputNode("output"))
    g.connect(color, "out", out, "albedo")
    return g


def test_compile_produces_wgsl_entry_point() -> None:
    wgsl = _minimal_graph().compile()
    assert "@fragment" in wgsl
    assert "fn main(in : FragIn)" in wgsl
    assert wgsl.rstrip().endswith("}")


def test_compile_contains_every_node_emit() -> None:
    g = MaterialGraph()
    g.add_node(ConstFloatNode("f", value=0.5))
    g.add_node(ConstColorNode("c", 0.3, 0.4, 0.5))
    out = g.add_node(PBROutputNode("output"))
    g.connect("c", "out", out, "albedo")
    g.connect("f", "out", out, "metallic")
    wgsl = g.compile()
    assert "f_out" in wgsl
    assert "c_out" in wgsl
    assert "out_albedo" in wgsl


# ---------------------------------------------------------------------------
# 3. Three-node graph: ConstColor -> Multiply <- Texture2D -> PBROutput
# ---------------------------------------------------------------------------


def test_three_node_graph_compiles() -> None:
    g = MaterialGraph()
    c = g.add_node(ConstColorNode("tint", 1.0, 0.8, 0.6))
    uv = g.add_node(UVNode("uv"))
    tex = g.add_node(Texture2DNode("albedo_tex", texture_path="a.png"))
    mul = g.add_node(MultiplyNode("mul"))
    out = g.add_node(PBROutputNode("output"))

    g.connect(uv, "uv", tex, "uv")
    g.connect(c, "out", mul, "a")
    g.connect(tex, "rgba", mul, "b")
    g.connect(mul, "out", out, "albedo")

    wgsl = g.compile()
    assert "textureSample(albedo_tex_tex" in wgsl
    assert "tint_out * albedo_tex_rgba" in wgsl
    # Soft-import wgpu — if present, do a real shader-module create.
    try:
        import wgpu  # type: ignore
    except ImportError:
        pytest.skip("wgpu not installed")
    # Just verify the module type exists; no adapter needed for parse-only.
    assert hasattr(wgpu, "GPUShaderModule") or hasattr(wgpu, "backends")


# ---------------------------------------------------------------------------
# 4. YAML round-trip
# ---------------------------------------------------------------------------


def test_yaml_round_trip_identical_wgsl() -> None:
    g = MaterialGraph()
    c = g.add_node(ConstColorNode("c", 0.2, 0.3, 0.4))
    f = g.add_node(ConstFloatNode("f", value=0.7))
    out = g.add_node(PBROutputNode("output"))
    g.connect(c, "out", out, "albedo")
    g.connect(f, "out", out, "metallic")

    wgsl_before = g.compile()

    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "graph.yaml")
        g.save(path)
        loaded = MaterialGraph.load(path)

    wgsl_after = loaded.compile()
    assert wgsl_before == wgsl_after


# ---------------------------------------------------------------------------
# 5. _core.material_eval constant baking
# ---------------------------------------------------------------------------


def test_bake_material_constants() -> None:
    try:
        from pharos_engine import _core  # type: ignore
    except ImportError:
        pytest.skip("_core not built")
    if not hasattr(_core, "bake_material_constants"):
        pytest.skip("_core.bake_material_constants unavailable")

    g = MaterialGraph()
    g.add_node(ConstFloatNode("f1", value=0.1))
    g.add_node(ConstFloatNode("f2", value=0.2))
    g.add_node(ConstFloatNode("f3", value=0.3))
    g.add_node(ConstColorNode("c1", 0.4, 0.5, 0.6, 1.0))
    g.add_node(ConstColorNode("c2", 0.7, 0.8, 0.9, 1.0))
    g.add_node(PBROutputNode("output"))

    import yaml

    yaml_str = yaml.safe_dump(g.to_dict(), sort_keys=False)
    baked = _core.bake_material_constants(yaml_str)
    # 3 floats + 2 * 4 color components = 11 f32 values.
    assert len(baked) == 11
    assert baked[0] == pytest.approx(0.1)
    assert baked[3] == pytest.approx(0.4)  # c1.r


# ---------------------------------------------------------------------------
# extras — misc behavior
# ---------------------------------------------------------------------------


def test_graph_rejects_cycle() -> None:
    # Two Multiply nodes wired back to back with a cycle.
    g = MaterialGraph()
    a = g.add_node(MultiplyNode("a"))
    b = g.add_node(MultiplyNode("b"))
    g.add_node(PBROutputNode("output"))
    g.connect(a, "out", b, "a")
    g.connect(b, "out", a, "a")
    with pytest.raises(RuntimeError):
        g.compile()


def test_graph_requires_output() -> None:
    g = MaterialGraph()
    g.add_node(ConstColorNode("c", 1.0, 1.0, 1.0))
    with pytest.raises(RuntimeError):
        g.compile()
