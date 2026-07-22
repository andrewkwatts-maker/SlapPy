"""E2 — WGSL chunk loader tests.

Verifies that the shared WGSL snippets in ``shaders/chunks/`` are loadable
via ``pharos_engine.compute.wgsl_chunks`` and that ``compose`` produces
concatenated source ready for shader-module creation.

These tests do not touch the GPU — they only validate text loading/joining.
"""
from __future__ import annotations

from pharos_engine.compute.wgsl_chunks import chunk, compose


def test_chunk_pack_rgba_contains_symbol():
    src = chunk("pack_rgba")
    assert isinstance(src, str)
    assert "pack_rgba" in src


def test_chunk_falloff_contains_smoothstep_idiom():
    src = chunk("falloff")
    assert isinstance(src, str)
    assert ("smoothstep" in src) or ("t * t" in src)


def test_compose_concatenates_chunk_and_main():
    main = "@compute @workgroup_size(8,8) fn main() {}"
    out = compose("pack_rgba", main)
    assert "pack_rgba" in out
    assert main in out
    # The chunk must appear before the main source.
    assert out.index("pack_rgba") < out.index("@compute")


def test_compose_luminance_chunk_produces_compilable_wgsl():
    """The `luminance` chunk + a minimal main entry must concatenate into a
    WGSL string that references the chunk symbol exactly once and orders the
    helper before its caller (the only thing wgpu cares about textually)."""
    main = (
        "@compute @workgroup_size(1)\n"
        "fn main() {\n"
        "    let _l = luminance(vec3<f32>(0.5, 0.5, 0.5));\n"
        "}\n"
    )
    out = compose("luminance", main)
    # Helper definition is present and Rec.709 coefficients match the engine
    # convention used by bloom/tonemap/SVGF/ReSTIR.
    assert "fn luminance(c: vec3<f32>) -> f32" in out
    assert "0.2126" in out and "0.7152" in out and "0.0722" in out
    # Definition precedes the call site — required for WGSL forward references.
    assert out.index("fn luminance") < out.index("@compute")
    # Exactly one definition (no duplicate from the main source).
    assert out.count("fn luminance(c: vec3<f32>) -> f32") == 1
