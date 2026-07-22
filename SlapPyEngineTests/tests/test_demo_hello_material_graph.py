"""Tests for the ``examples/hello_material_graph.py`` demo (CC2).

Pins the behaviour of the four material-graph → WGSL compilations:

1. ``run()`` executes end-to-end without exception.
2. Four ``hello_material_graph_<name>.wgsl`` files land in the output dir.
3. Each compiled shader passes the AA6 :func:`lint_wgsl` structural checks
   (soft-imported — the test skips gracefully when the linter is absent).
4. The trace file contains >= 12 events.
5. Every builder produces a graph with >= 2 nodes.
6. Each shader mentions ``@fragment``, ``fs_main``, and ``@location(0)``.
7. The per-graph WGSL body has at least one ``let`` binding.
8. ``main()`` (the CLI entry point) prints a table and exits with 0.
"""
from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Demo loader — mirrors the pattern used by test_demo_hello_composite.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_material_graph.py"
)


def _load_demo():
    spec = importlib.util.spec_from_file_location(
        "hello_material_graph_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_material_graph_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ---------------------------------------------------------------------------
# Test 1: end-to-end run
# ---------------------------------------------------------------------------


def test_run_completes_without_exception(demo, tmp_path):
    result = demo.run(output_dir=tmp_path)
    assert isinstance(result, dict)
    assert "graphs" in result and "trace_path" in result
    assert set(result["graphs"]) == set(demo.GRAPH_BUILDERS)


# ---------------------------------------------------------------------------
# Test 2: 4 WGSL files land on disk
# ---------------------------------------------------------------------------


def test_four_wgsl_files_written(demo, tmp_path):
    demo.run(output_dir=tmp_path)
    wgsl_files = sorted(tmp_path.glob("hello_material_graph_*.wgsl"))
    assert len(wgsl_files) == 4, (
        f"expected 4 wgsl outputs; got {[p.name for p in wgsl_files]}"
    )
    for path in wgsl_files:
        # Every file must be non-empty.
        assert path.stat().st_size > 0, f"{path.name} is empty"


# ---------------------------------------------------------------------------
# Test 3: lint_wgsl passes (soft-imported)
# ---------------------------------------------------------------------------


def test_lint_wgsl_soft_imported(demo, tmp_path):
    try:
        from pharos_editor.ui.theme.shader_lint import lint_wgsl
    except Exception:
        pytest.skip("lint_wgsl unavailable — soft-import contract satisfied")
        return

    demo.run(output_dir=tmp_path)
    contract = {
        # Relaxed byte budget for the auto-generated demo shaders. The
        # library-shipped 1000-byte cap is aimed at library shaders; a
        # 4-graph demo composed of scalar + noise + gradient stops
        # legitimately overshoots it.
        "max_bytes": 4096,
        "entry_point": "fs_main",
        "require_location_0": True,
        "forbid_deprecated": True,
    }
    for path in sorted(tmp_path.glob("hello_material_graph_*.wgsl")):
        source = path.read_text(encoding="utf-8")
        result = lint_wgsl(path.stem, source, contract=contract)
        # Post-FF2, the demo shaders should pass every structural check
        # cleanly (helper markers are now injected as function defs, not
        # texture bindings; sampler names bind as ``sampler``; only
        # ``u_*_texture`` / ``u_*_tex`` names bind as ``texture_2d``).
        # The wgpu parse pass is soft — some CI hosts don't have a
        # working device — so we still tolerate ``wgpu parse failed``
        # entries, but every *structural* error must be absent.
        structural = [
            e for e in result.errors
            if not e[1].startswith("wgpu parse failed")
        ]
        assert not structural, (
            f"{path.name} failed structural lint_wgsl checks: {structural}"
        )


# ---------------------------------------------------------------------------
# Test 4: trace has >= 12 events
# ---------------------------------------------------------------------------


def test_trace_has_at_least_twelve_events(demo, tmp_path):
    result = demo.run(output_dir=tmp_path)
    assert result["event_count"] >= 12, (
        f"expected >= 12 trace events; got {result['event_count']}"
    )

    trace_path = Path(result["trace_path"])
    assert trace_path.exists(), f"trace file missing: {trace_path}"
    text = trace_path.read_text(encoding="utf-8")
    # Every event line begins with ``kind:`` — inline count on the raw
    # source keeps the test working whether or not pyyaml is installed.
    kind_count = text.count("kind:")
    assert kind_count >= 12, f"expected >= 12 kind entries in trace; got {kind_count}"


# ---------------------------------------------------------------------------
# Test 5: every builder graph has >= 2 nodes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["simple_diffuse", "fresnel_tinted",
                                    "perlin_ramp", "textured_pbr"])
def test_each_graph_has_at_least_two_nodes(demo, name):
    builder = demo.GRAPH_BUILDERS[name]
    graph = builder()
    assert len(graph.nodes) >= 2, (
        f"{name}: graph has {len(graph.nodes)} nodes; expected >= 2"
    )
    # At least one edge means the graph actually wires something.
    assert len(graph.edges) >= 1, f"{name}: graph has no edges"


# ---------------------------------------------------------------------------
# Test 6: shader markers present per file
# ---------------------------------------------------------------------------


def test_each_shader_has_wgsl_markers(demo, tmp_path):
    demo.run(output_dir=tmp_path)
    for path in sorted(tmp_path.glob("hello_material_graph_*.wgsl")):
        text = path.read_text(encoding="utf-8")
        assert "@fragment" in text, f"{path.name} missing @fragment"
        assert "fs_main" in text, f"{path.name} missing fs_main"
        assert "@location(0)" in text, f"{path.name} missing @location(0)"


# ---------------------------------------------------------------------------
# Test 7: bridge to_material emits >= 1 let binding for each graph
# ---------------------------------------------------------------------------


def test_bridge_body_has_let_bindings(demo):
    from pharos_editor.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )

    bridge = MaterialGraphBridge()
    for name, builder in demo.GRAPH_BUILDERS.items():
        material = bridge.to_material(builder())
        body = material["wgsl_source"]
        assert "let " in body, (
            f"{name}: to_material body missing any 'let' binding "
            f"({body!r})"
        )


# ---------------------------------------------------------------------------
# Test 8: main() prints a summary + exits 0
# ---------------------------------------------------------------------------


def test_main_prints_summary_and_returns_zero(demo, monkeypatch, tmp_path):
    # Steer the demo's ``run()`` at tmp_path so main() never touches the
    # committed example artefacts.
    original_run = demo.run

    def _patched_run(output_dir=None):
        return original_run(output_dir=tmp_path)

    monkeypatch.setattr(demo, "run", _patched_run)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = demo.main()
    assert rc == 0
    printed = buf.getvalue()
    assert "hello_material_graph" in printed
    assert "graph" in printed
    assert "trace file" in printed


# ---------------------------------------------------------------------------
# Test 9: uniforms surface for perlin + texture graphs
# ---------------------------------------------------------------------------


def test_expected_uniforms_appear(demo):
    from pharos_editor.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )

    bridge = MaterialGraphBridge()

    perlin_mat = bridge.to_material(demo.build_perlin_ramp())
    assert "u_time" in perlin_mat["uniforms"], (
        f"perlin_ramp should register u_time; got {perlin_mat['uniforms']}"
    )

    tex_mat = bridge.to_material(demo.build_textured_pbr())
    # After the FF2 fix, textures must use a ``_texture`` / ``_tex``
    # suffix so the classifier binds them as ``texture_2d<f32>``.
    assert "u_albedo_texture" in tex_mat["uniforms"], (
        f"textured_pbr should register u_albedo_texture; "
        f"got {tex_mat['uniforms']}"
    )
    assert "u_albedo_sampler" in tex_mat["uniforms"], (
        f"textured_pbr should register u_albedo_sampler; "
        f"got {tex_mat['uniforms']}"
    )


# ---------------------------------------------------------------------------
# Test 10: constant node subclasses emit valid WGSL fragments
# ---------------------------------------------------------------------------


def test_local_constant_nodes_emit_wgsl(demo):
    from pharos_engine.visual_scripting.material_nodes import (
        DefaultWgslEmitContext,
    )

    ctx = DefaultWgslEmitContext()
    frag_vec3 = demo.ConstantVec3Node(
        params={"value": (0.1, 0.2, 0.3)}
    ).emit_wgsl(ctx)
    assert "vec3<f32>(0.1, 0.2, 0.3)" in frag_vec3
    assert frag_vec3.startswith("let ")

    frag_f32 = demo.ConstantFloatNode(params={"value": 0.75}).emit_wgsl(ctx)
    assert "f32(0.75)" in frag_f32
    assert frag_f32.startswith("let ")
