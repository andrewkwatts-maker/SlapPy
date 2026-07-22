"""Regression tests for MaterialGraphBridge FF2 fix — binding heuristic.

The V5 :mod:`pharos_engine.visual_scripting.material_nodes` palette adds
helper-function markers (``perlin2d``, ``worley2d``, ``_hash2``) to the
emit context's ``used_uniforms`` set so that
:meth:`MaterialGraphBridge.emit_full_shader` can auto-insert the helper
WGSL definition once per shader. Before FF2, ``emit_full_shader``
incorrectly promoted every non-``u_``-prefixed name in ``used_uniforms``
into a ``texture_2d`` binding, producing WGSL that failed to compile in
``wgpu``.

This file covers:

* Helper-function markers are excluded from the binding block.
* ``strict_mode=True`` raises :class:`MaterialGraphError` on names that
  don't match any recognised classifier bucket.
* ``strict_mode=False`` warns via :mod:`warnings` and skips.
* ``perlin2d`` no longer emits a ``texture_2d`` binding.
* The fixed ``hello_material_graph_perlin_ramp.wgsl`` passes the AA6
  :func:`lint_wgsl` structural checks clean.
* :func:`_classify_uniform` returns the correct kind per name pattern.
* :class:`_FunctionRegistry` behaves as a first-write-wins ordered
  registry.
* ``register_helper_function`` on the emit context idempotently adds
  markers and definitions.
"""
from __future__ import annotations

import warnings
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bridge():
    from pharos_editor.ui.editor.material_graph_bridge import (
        MaterialGraphBridge,
    )
    return MaterialGraphBridge()


@pytest.fixture
def perlin_graph():
    """A minimal graph exercising the perlin2d helper injection."""
    from pharos_engine.visual_scripting import (
        MaterialOutputNode, NodeGraph, PerlinNoiseNode,
    )
    g = NodeGraph(name="perlin_only")
    g.add_node(PerlinNoiseNode())
    g.add_node(MaterialOutputNode())
    return g


# ---------------------------------------------------------------------------
# 1. Classifier — smoke-test every rule bucket.
# ---------------------------------------------------------------------------


def test_classify_helper_marker_perlin2d() -> None:
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("perlin2d") == "helper"


def test_classify_helper_marker_worley2d() -> None:
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("worley2d") == "helper"


def test_classify_helper_marker_hash2() -> None:
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("_hash2") == "helper"


def test_classify_function_call_fragment() -> None:
    """A name that leaked a WGSL function-call fragment is a helper."""
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("perlin2d(uv)") == "helper"


def test_classify_sampler_by_suffix() -> None:
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("u_albedo_sampler") == "sampler"
    assert _classify_uniform("u_sampler") == "sampler"


def test_classify_texture_by_suffix() -> None:
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("u_albedo_texture") == "texture"
    assert _classify_uniform("u_normal_tex") == "texture"
    assert _classify_uniform("u_texture") == "texture"


def test_classify_generic_uniform() -> None:
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("u_time") == "uniform"
    assert _classify_uniform("u_scale") == "uniform"
    assert _classify_uniform("u_theme_color") == "uniform"


def test_classify_unknown() -> None:
    """Bare lowercase names with no ``u_`` prefix are unknown."""
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("some_helper") == "unknown"
    assert _classify_uniform("bogus") == "unknown"


def test_classify_empty_or_non_string() -> None:
    from pharos_editor.ui.editor.material_graph_bridge import _classify_uniform
    assert _classify_uniform("") == "unknown"
    assert _classify_uniform(None) == "unknown"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Helper-function markers exclusion from binding block.
# ---------------------------------------------------------------------------


def test_helper_function_names_excluded_from_bindings(bridge, perlin_graph):
    """perlin2d used to become ``var perlin2d: texture_2d<f32>``; now it must not."""
    src = bridge.emit_full_shader(perlin_graph)
    # The old bug produced this exact line.
    assert "var perlin2d: texture_2d<f32>" not in src, (
        "perlin2d must not be bound as a texture"
    )
    # And no ``@binding(N) var perlin2d`` at all.
    assert "@binding" not in src or "perlin2d" not in _binding_lines(src)


def test_perlin2d_helper_definition_injected(bridge, perlin_graph):
    """The perlin2d function definition should be prepended once."""
    src = bridge.emit_full_shader(perlin_graph)
    assert "fn perlin2d(" in src
    # helper appears exactly once (dedup by name).
    assert src.count("fn perlin2d(") == 1
    # _hash2 helper is bundled with perlin2d.
    assert "fn _hash2(" in src


def test_perlin2d_appears_before_uniforms(bridge, perlin_graph):
    src = bridge.emit_full_shader(perlin_graph)
    perlin_idx = src.find("fn perlin2d(")
    uniform_idx = src.find("var<uniform>")
    assert perlin_idx > 0
    if uniform_idx > 0:  # u_time from TimeNode isn't in perlin_only
        assert perlin_idx < uniform_idx


# ---------------------------------------------------------------------------
# 3. strict_mode behaviour.
# ---------------------------------------------------------------------------


def _make_leaky_node():
    """Build a MaterialNode subclass that leaks an unclassified name."""
    from pharos_engine.visual_scripting.material_nodes import MaterialNode

    class _UnclassifiedLeakNode(MaterialNode):
        NODE_TYPE = "leak.raw"
        DISPLAY_NAME = "Leak"
        INPUT_PORTS = ()
        OUTPUT_PORTS = ()
        DEFAULT_PARAMS: dict = {}

        def emit_wgsl(self, context, inputs=None):
            # Push a name that isn't ``u_``-prefixed, not a sampler,
            # not a helper marker — the classifier must flag it as
            # ``unknown``.
            context.used_uniforms.add("some_leaked_helper")
            sym = context.alloc_symbol("leak")
            return f"let {sym} = 0.0;"

    return _UnclassifiedLeakNode()


def _make_leaky_graph():
    from pharos_engine.visual_scripting import MaterialOutputNode, NodeGraph
    g = NodeGraph(name="leaky")
    g.add_node(_make_leaky_node())
    g.add_node(MaterialOutputNode())
    return g


def test_strict_mode_raises_on_unclassified(bridge):
    from pharos_editor.ui.editor.material_graph_bridge import MaterialGraphError
    graph = _make_leaky_graph()
    with pytest.raises(MaterialGraphError) as excinfo:
        bridge.emit_full_shader(graph, strict_mode=True)
    assert "some_leaked_helper" in str(excinfo.value)


def test_strict_mode_default_is_true(bridge):
    """emit_full_shader must default to strict_mode=True."""
    from pharos_editor.ui.editor.material_graph_bridge import MaterialGraphError
    graph = _make_leaky_graph()
    with pytest.raises(MaterialGraphError):
        bridge.emit_full_shader(graph)  # no explicit strict_mode


def test_non_strict_mode_warns_and_skips(bridge):
    graph = _make_leaky_graph()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        src = bridge.emit_full_shader(graph, strict_mode=False)
    # At least one warning fired about ``some_leaked_helper``.
    msgs = [str(w.message) for w in caught]
    assert any("some_leaked_helper" in m for m in msgs), (
        f"expected warning about leaked name; got {msgs}"
    )
    # And the unclassified name must not appear as a binding.
    assert "var some_leaked_helper" not in src
    assert "@binding" not in src or "some_leaked_helper" not in _binding_lines(src)


def test_strict_mode_still_emits_clean_shader_for_valid_graph(
    bridge, perlin_graph,
):
    """A valid graph must produce a shader under strict_mode without error."""
    src = bridge.emit_full_shader(perlin_graph, strict_mode=True)
    assert "@fragment" in src
    assert "fs_main" in src


# ---------------------------------------------------------------------------
# 4. perlin_ramp lint clean.
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PERLIN_RAMP_WGSL = (
    _REPO_ROOT / "PharosEngineExamples" / "examples"
    / "hello_material_graph_perlin_ramp.wgsl"
)


def test_fixed_perlin_ramp_wgsl_passes_structural_lint():
    from pharos_editor.ui.theme.shader_lint import lint_wgsl
    assert _PERLIN_RAMP_WGSL.exists(), (
        f"expected regenerated fixture at {_PERLIN_RAMP_WGSL}"
    )
    source = _PERLIN_RAMP_WGSL.read_text(encoding="utf-8")
    result = lint_wgsl(
        "perlin_ramp",
        source,
        contract={
            "max_bytes": 4096,
            "entry_point": "fs_main",
            "require_location_0": True,
            "forbid_deprecated": True,
        },
    )
    # We tolerate wgpu parse fails (soft — GPU may be unavailable on
    # CI), but every *structural* error must be gone.
    structural = [
        (line, msg) for line, msg in result.errors
        if not msg.startswith("wgpu parse failed")
    ]
    assert not structural, (
        f"perlin_ramp still has structural lint errors: {structural}"
    )


def test_fixed_perlin_ramp_declares_perlin2d_function():
    """The regenerated shader must define perlin2d, not bind it."""
    source = _PERLIN_RAMP_WGSL.read_text(encoding="utf-8")
    assert "fn perlin2d(" in source
    # Old bug — must not be present.
    assert "var perlin2d: texture_2d" not in source


def test_fixed_perlin_ramp_wgpu_compiles_when_available():
    """When wgpu can spin up a device, the shader must actually compile."""
    from pharos_editor.ui.theme.shader_lint import (
        _get_wgpu_device, wgpu_available,
    )
    if not wgpu_available():
        pytest.skip("wgpu not importable")
    device = _get_wgpu_device()
    if device is None:
        pytest.skip("no wgpu device available")
    source = _PERLIN_RAMP_WGSL.read_text(encoding="utf-8")
    # If this raises, the fix regressed.
    device.create_shader_module(code=source)


# ---------------------------------------------------------------------------
# 5. _FunctionRegistry behaviour.
# ---------------------------------------------------------------------------


def test_function_registry_first_write_wins():
    from pharos_editor.ui.editor.material_graph_bridge import _FunctionRegistry
    reg = _FunctionRegistry()
    reg.register("perlin2d", "fn perlin2d() { return 1.0; }")
    reg.register("perlin2d", "fn perlin2d() { return 2.0; }")
    defs = dict(reg.definitions())
    assert defs["perlin2d"] == "fn perlin2d() { return 1.0; }"


def test_function_registry_insertion_order():
    from pharos_editor.ui.editor.material_graph_bridge import _FunctionRegistry
    reg = _FunctionRegistry()
    reg.register("_hash2", "fn _hash2() { return 0.0; }")
    reg.register("perlin2d", "fn perlin2d() { return 0.0; }")
    reg.register("worley", "fn worley() { return 0.0; }")
    assert reg.names() == ["_hash2", "perlin2d", "worley"]


def test_function_registry_rejects_non_string_name():
    from pharos_editor.ui.editor.material_graph_bridge import _FunctionRegistry
    reg = _FunctionRegistry()
    with pytest.raises(TypeError):
        reg.register(123, "fn x() {}")  # type: ignore[arg-type]


def test_function_registry_rejects_empty_name():
    from pharos_editor.ui.editor.material_graph_bridge import _FunctionRegistry
    reg = _FunctionRegistry()
    with pytest.raises(ValueError):
        reg.register("", "fn x() {}")


def test_function_registry_as_wgsl_joins_bodies():
    from pharos_editor.ui.editor.material_graph_bridge import _FunctionRegistry
    reg = _FunctionRegistry()
    reg.register("a", "fn a() {}")
    reg.register("b", "fn b() {}")
    src = reg.as_wgsl()
    assert "fn a()" in src and "fn b()" in src


# ---------------------------------------------------------------------------
# 6. register_helper_function on the emit context.
# ---------------------------------------------------------------------------


def test_register_helper_function_adds_marker_and_definition():
    from pharos_editor.ui.editor.material_graph_bridge import _BridgeEmitContext
    ctx = _BridgeEmitContext()
    ctx.register_helper_function("custom_noise", "fn custom_noise() { return 0.0; }")
    assert "custom_noise" in ctx.HELPER_FUNCTION_MARKERS
    assert "custom_noise" in ctx.function_registry


def test_register_helper_function_is_idempotent():
    from pharos_editor.ui.editor.material_graph_bridge import _BridgeEmitContext
    ctx = _BridgeEmitContext()
    ctx.register_helper_function("h1", "fn h1() {}")
    ctx.register_helper_function("h1", "fn h1_v2() {}")
    defs = dict(ctx.function_registry.definitions())
    assert defs["h1"] == "fn h1() {}"


def test_bridge_context_seed_from_module_markers():
    """A fresh context inherits the module-level marker set."""
    from pharos_editor.ui.editor.material_graph_bridge import (
        HELPER_FUNCTION_MARKERS, _BridgeEmitContext,
    )
    ctx = _BridgeEmitContext()
    for marker in HELPER_FUNCTION_MARKERS:
        assert marker in ctx.HELPER_FUNCTION_MARKERS


def test_bridge_is_helper_marker_predicate():
    from pharos_editor.ui.editor.material_graph_bridge import _BridgeEmitContext
    ctx = _BridgeEmitContext()
    assert ctx.is_helper_marker("perlin2d") is True
    assert ctx.is_helper_marker("perlin2d(uv)") is True
    assert ctx.is_helper_marker("u_time") is False
    assert ctx.is_helper_marker(123) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 7. End-to-end integration — the full 4-graph demo.
# ---------------------------------------------------------------------------


def test_all_four_demo_wgsl_pass_structural_lint():
    """Every regenerated demo shader must pass the lint's structural checks."""
    from pharos_editor.ui.theme.shader_lint import lint_wgsl
    examples_dir = _REPO_ROOT / "PharosEngineExamples" / "examples"
    contract = {
        "max_bytes": 4096,
        "entry_point": "fs_main",
        "require_location_0": True,
        "forbid_deprecated": True,
    }
    files = sorted(examples_dir.glob("hello_material_graph_*.wgsl"))
    assert len(files) == 4, f"expected 4 wgsl files, got {[f.name for f in files]}"
    for path in files:
        source = path.read_text(encoding="utf-8")
        result = lint_wgsl(path.stem, source, contract=contract)
        structural = [
            (line, msg) for line, msg in result.errors
            if not msg.startswith("wgpu parse failed")
        ]
        assert not structural, (
            f"{path.name} has structural errors: {structural}"
        )


def test_helper_marker_never_becomes_binding_end_to_end(bridge, perlin_graph):
    """Sanity: no line in the perlin shader treats a helper as a binding."""
    src = bridge.emit_full_shader(perlin_graph)
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("@group") or stripped.startswith("@binding"):
            assert "perlin2d" not in stripped, (
                f"binding line still references perlin2d: {stripped!r}"
            )
            assert "_hash2" not in stripped, (
                f"binding line still references _hash2: {stripped!r}"
            )


def test_texture_binding_uses_texture_2d_type(bridge):
    """Names matching ``u_*_texture`` bind as texture_2d<f32>, not scalar."""
    from pharos_engine.visual_scripting import (
        MaterialOutputNode, NodeGraph, TextureSampleNode,
    )
    g = NodeGraph(name="tex")
    g.add_node(TextureSampleNode(params={
        "texture": "u_albedo_texture",
        "sampler": "u_albedo_sampler",
    }))
    g.add_node(MaterialOutputNode())
    src = bridge.emit_full_shader(g)
    assert "var u_albedo_texture: texture_2d<f32>" in src
    assert "var u_albedo_sampler: sampler" in src
    # And the old wrong-type bindings must not be present.
    assert "var<uniform> u_albedo_texture" not in src
    assert "var<uniform> u_albedo_sampler" not in src


def test_helper_library_contains_perlin2d():
    """The module-level HELPER_FUNCTION_LIBRARY ships perlin2d out of the box."""
    from pharos_editor.ui.editor.material_graph_bridge import (
        HELPER_FUNCTION_LIBRARY,
    )
    assert "perlin2d" in HELPER_FUNCTION_LIBRARY
    assert "fn perlin2d(" in HELPER_FUNCTION_LIBRARY["perlin2d"]


def test_module_exports_new_symbols():
    from pharos_editor.ui.editor import material_graph_bridge as mod
    assert "HELPER_FUNCTION_MARKERS" in mod.__all__
    assert "HELPER_FUNCTION_LIBRARY" in mod.__all__


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _binding_lines(source: str) -> str:
    """Return the concatenation of every ``@group`` / ``@binding`` line."""
    return "\n".join(
        line for line in source.splitlines()
        if "@group" in line or "@binding" in line
    )
