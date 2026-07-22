"""Tests for :mod:`pharos_editor.ui.theme.shader_lint`.

Covers:

* Every shipped WGSL shader in the three notebook theme libraries
  (washi tape, page linings, edge strokes) survives
  :func:`lint_wgsl` with ``parseable=True``.
* Every shader stays inside its library's byte budget.
* Every shader declares the uniforms named in its contract.
* Every shader parses cleanly through :mod:`wgpu` when the module is
  importable (soft check).
* Deprecated ``[[block]]`` / ``[[binding(0)]]`` syntax triggers the
  warning path on synthetic inputs.
* Structural violations (missing entry point, oversize source, missing
  uniform) surface both on the :class:`WGSLLintResult` and via
  :func:`raise_on_error`.
* No stray backticks or smart quotes appear anywhere in the corpus.
"""
from __future__ import annotations

import re
from typing import Iterable

import pytest

from pharos_editor.ui.theme.shader_lint import (
    SHADER_CONTRACTS,
    WGSLLintError,
    WGSLLintResult,
    lint_all_shaders,
    lint_wgsl,
    raise_on_error,
    wgpu_available,
)


# ---------------------------------------------------------------------------
# Fixture helpers — collect all shader sources up front so every test
# parametrises over the same corpus.
# ---------------------------------------------------------------------------


def _washi_sources() -> list[tuple[str, str, str]]:
    from pharos_editor.ui.theme.washi_tape.library import WASHI_TAPES

    return [
        ("washi_tape", sid, style.wgsl_source)
        for sid, style in WASHI_TAPES.items()
    ]


def _lining_sources() -> list[tuple[str, str, str]]:
    from pharos_editor.ui.theme.page_linings.library import PAGE_LININGS

    return [
        ("page_linings", sid, style.source)
        for sid, style in PAGE_LININGS.items()
    ]


def _edge_stroke_sources() -> list[tuple[str, str, str]]:
    from pharos_editor.ui.theme.edge_strokes.library import EDGE_STROKES

    return [
        ("edge_strokes", sid, style.wgsl_source)
        for sid, style in EDGE_STROKES.items()
    ]


ALL_SOURCES: list[tuple[str, str, str]] = (
    _washi_sources() + _lining_sources() + _edge_stroke_sources()
)


def _ids(records: Iterable[tuple[str, str, str]]) -> list[str]:
    return [f"{lib}::{sid}" for lib, sid, _ in records]


# ---------------------------------------------------------------------------
# Sanity — the corpus must be non-empty and at expected size.
# ---------------------------------------------------------------------------


def test_corpus_has_at_least_45_shaders():
    # 23 washi + 15 linings + 15 strokes = 53 by construction.
    assert len(ALL_SOURCES) >= 45


def test_corpus_split_matches_libraries():
    counts: dict[str, int] = {}
    for lib, _, _ in ALL_SOURCES:
        counts[lib] = counts.get(lib, 0) + 1
    assert counts.get("washi_tape", 0) >= 23
    assert counts.get("page_linings", 0) >= 15
    assert counts.get("edge_strokes", 0) >= 15


def test_shader_contracts_cover_every_library():
    assert set(SHADER_CONTRACTS.keys()) == {
        "washi_tape",
        "page_linings",
        "edge_strokes",
    }


# ---------------------------------------------------------------------------
# Per-shader lints — every shader must be parseable + inside budget.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "library,source_id,source", ALL_SOURCES, ids=_ids(ALL_SOURCES)
)
def test_every_shader_is_parseable(library, source_id, source):
    contract = SHADER_CONTRACTS[library]
    result = lint_wgsl(source_id, source, contract=contract)
    assert result.parseable, (
        f"{library}/{source_id} failed lint: {result.errors}"
    )
    assert result.has_entry_point
    assert result.entry_point_name == "fs_main"


@pytest.mark.parametrize(
    "library,source_id,source", ALL_SOURCES, ids=_ids(ALL_SOURCES)
)
def test_every_shader_within_byte_budget(library, source_id, source):
    contract = SHADER_CONTRACTS[library]
    result = lint_wgsl(source_id, source, contract=contract)
    assert 0 < result.size_bytes <= contract["max_bytes"], (
        f"{library}/{source_id}: {result.size_bytes} bytes exceeds "
        f"{contract['max_bytes']}"
    )


@pytest.mark.parametrize(
    "library,source_id,source", ALL_SOURCES, ids=_ids(ALL_SOURCES)
)
def test_every_shader_meets_uniform_contract(library, source_id, source):
    contract = SHADER_CONTRACTS[library]
    result = lint_wgsl(source_id, source, contract=contract)
    for required in contract["required_uniforms"]:
        assert required in result.uniforms, (
            f"{library}/{source_id} missing required uniform {required!r}; "
            f"got {result.uniforms}"
        )


@pytest.mark.parametrize(
    "library,source_id,source", ALL_SOURCES, ids=_ids(ALL_SOURCES)
)
def test_every_shader_has_no_stray_backticks_or_smart_quotes(
    library, source_id, source
):
    assert "`" not in source, (
        f"{library}/{source_id}: stray backtick"
    )
    for ch in "‘’“”–—…":
        assert ch not in source, (
            f"{library}/{source_id}: smart-quote / dash U+{ord(ch):04X}"
        )
    # Full ASCII round-trip (allows raise if any non-ASCII byte).
    source.encode("ascii")


# ---------------------------------------------------------------------------
# lint_all_shaders round-trip.
# ---------------------------------------------------------------------------


def test_lint_all_shaders_reports_every_library():
    results = lint_all_shaders()
    assert set(results.keys()) == {
        "washi_tape",
        "page_linings",
        "edge_strokes",
    }
    for lib, rs in results.items():
        assert all(isinstance(r, WGSLLintResult) for r in rs)
        assert rs, f"{lib} lint results should not be empty"
        assert all(r.parseable for r in rs), (
            f"{lib} has failing shaders: "
            f"{[r.source_id for r in rs if not r.parseable]}"
        )


def test_lint_all_shaders_uniform_result_shape():
    for rs in lint_all_shaders().values():
        for r in rs:
            assert r.source_id
            assert r.size_bytes > 0
            assert r.has_entry_point is True
            assert r.entry_point_name == "fs_main"
            assert isinstance(r.uniforms, list)
            assert r.errors == []


# ---------------------------------------------------------------------------
# Synthetic sources — exercise every warning + error branch.
# ---------------------------------------------------------------------------


_VALID_WASHI = """struct U {
  u_time: f32,
  u_size: vec2<f32>,
  u_theme_color_1: vec4<f32>,
  u_theme_color_2: vec4<f32>,
}
@group(0) @binding(0) var<uniform> u: U;
@fragment fn fs_main(@builtin(position) p: vec4<f32>) -> @location(0) vec4<f32> {
  return vec4<f32>(u.u_theme_color_1.rgb, 1.0);
}
"""


def test_valid_synthetic_source_passes():
    r = lint_wgsl("synthetic", _VALID_WASHI, SHADER_CONTRACTS["washi_tape"])
    assert r.parseable
    assert r.entry_point_name == "fs_main"
    assert "u" in r.uniforms
    assert "u_time" in r.uniforms


def test_missing_entry_point_flagged_as_error():
    src = "// no entry point\n"
    r = lint_wgsl("no_entry", src)
    assert not r.parseable
    assert any("missing @fragment" in issue for _, issue in r.errors)


def test_missing_location_0_flagged():
    src = (
        "@fragment fn fs_main(@builtin(position) p: vec4<f32>) -> vec4<f32> {\n"
        "  return vec4<f32>(1.0);\n"
        "}\n"
    )
    r = lint_wgsl("no_loc0", src)
    assert not r.parseable
    assert any("@location(0)" in issue for _, issue in r.errors)


def test_over_budget_flagged():
    body = "// pad " + ("A" * 2000)
    src = body + "\n@fragment fn fs_main() -> @location(0) vec4<f32> { return vec4<f32>(1.0); }\n"
    r = lint_wgsl("too_big", src)
    assert not r.parseable
    assert any("byte budget" in issue for _, issue in r.errors)


def test_missing_required_uniform_flagged():
    r = lint_wgsl(
        "missing_uniform",
        _VALID_WASHI,
        {"required_uniforms": ["u_never_declared"]},
    )
    assert not r.parseable
    assert any(
        "u_never_declared" in issue for _, issue in r.errors
    )


def test_wrong_entry_point_name_flagged():
    src = _VALID_WASHI.replace("fs_main", "main_fs")
    r = lint_wgsl(
        "renamed",
        src,
        {"entry_point": "fs_main", "required_uniforms": []},
    )
    assert not r.parseable
    assert any("entry point named" in issue for _, issue in r.errors)


def test_deprecated_block_attribute_warns():
    src = (
        "[[block]] struct U { u_time: f32, };\n"
        "@group(0) @binding(0) var<uniform> u: U;\n"
        "@fragment fn fs_main() -> @location(0) vec4<f32> {\n"
        "  return vec4<f32>(u.u_time);\n"
        "}\n"
    )
    r = lint_wgsl("deprecated_block", src, {"required_uniforms": []})
    # Warnings fire regardless of pass/fail; parseable is fine here
    # because [[block]] is a warning, not an error.
    assert any(
        "deprecated" in issue and "block" in issue
        for _, issue in r.warnings
    )


def test_deprecated_binding_attribute_warns():
    src = (
        "struct U { x: f32, };\n"
        "[[binding(0), group(0)]] var<uniform> u: U;\n"
        "@fragment fn fs_main() -> @location(0) vec4<f32> {\n"
        "  return vec4<f32>(u.x);\n"
        "}\n"
    )
    r = lint_wgsl("deprecated_binding", src, {"required_uniforms": []})
    assert any(
        "deprecated" in issue for _, issue in r.warnings
    )


def test_backtick_in_source_errors():
    src = (
        "// stray ` in comment\n"
        "@fragment fn fs_main() -> @location(0) vec4<f32> {\n"
        "  return vec4<f32>(1.0);\n"
        "}\n"
    )
    r = lint_wgsl("backtick", src)
    assert not r.parseable
    assert any("backtick" in issue for _, issue in r.errors)


def test_smart_quote_in_source_errors():
    src = (
        "// smart quote ‘here’\n"
        "@fragment fn fs_main() -> @location(0) vec4<f32> {\n"
        "  return vec4<f32>(1.0);\n"
        "}\n"
    )
    r = lint_wgsl("smart_quote", src)
    assert not r.parseable
    assert any("smart-quote" in issue for _, issue in r.errors)


# ---------------------------------------------------------------------------
# WGSLLintError + raise_on_error.
# ---------------------------------------------------------------------------


def test_wgsl_lint_error_carries_context():
    err = WGSLLintError("some_shader", 42, "broken")
    assert err.source_id == "some_shader"
    assert err.line == 42
    assert err.issue == "broken"
    assert "some_shader" in str(err)
    assert "42" in str(err)


def test_wgsl_lint_error_rejects_empty_source_id():
    with pytest.raises(ValueError, match="source_id"):
        WGSLLintError("", 1, "x")


def test_wgsl_lint_error_rejects_negative_line():
    with pytest.raises(ValueError, match="line"):
        WGSLLintError("id", -1, "x")


def test_wgsl_lint_error_rejects_empty_issue():
    with pytest.raises(ValueError, match="issue"):
        WGSLLintError("id", 1, "")


def test_raise_on_error_noop_when_clean():
    r = lint_wgsl("ok", _VALID_WASHI, SHADER_CONTRACTS["washi_tape"])
    raise_on_error(r)  # must not raise


def test_raise_on_error_raises_on_first_error():
    r = lint_wgsl("bad", "// nothing here\n")
    with pytest.raises(WGSLLintError):
        raise_on_error(r)


# ---------------------------------------------------------------------------
# lint_wgsl input validation.
# ---------------------------------------------------------------------------


def test_lint_wgsl_rejects_non_string_source_id():
    with pytest.raises(TypeError):
        lint_wgsl(123, "x")  # type: ignore[arg-type]


def test_lint_wgsl_rejects_empty_source():
    with pytest.raises(ValueError):
        lint_wgsl("id", "")


def test_lint_wgsl_rejects_non_mapping_contract():
    with pytest.raises(TypeError):
        lint_wgsl("id", _VALID_WASHI, contract=["not", "a", "mapping"])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# wgpu-backed real parse.
# ---------------------------------------------------------------------------


def test_wgpu_available_returns_bool():
    assert isinstance(wgpu_available(), bool)


@pytest.mark.skipif(not wgpu_available(), reason="wgpu not installed")
def test_wgpu_parses_every_real_shader():
    """When wgpu is installed, every corpus shader must survive a real
    ``create_shader_module`` compile.

    The core lint already runs the compile inline when a device is
    available; this test is an explicit witness so a wgpu regression
    surfaces as a dedicated failure.
    """
    for library, source_id, source in ALL_SOURCES:
        contract = SHADER_CONTRACTS[library]
        r = lint_wgsl(source_id, source, contract=contract)
        assert r.parseable, (
            f"{library}/{source_id} failed wgpu parse: {r.errors}"
        )


# ---------------------------------------------------------------------------
# Uniform-set consistency.
# ---------------------------------------------------------------------------


def test_washi_shaders_all_expose_theme_colors():
    for lib, source_id, source in _washi_sources():
        r = lint_wgsl(source_id, source, SHADER_CONTRACTS["washi_tape"])
        assert "u_theme_color_1" in r.uniforms
        assert "u_theme_color_2" in r.uniforms


def test_edge_stroke_shaders_all_expose_theme_colors():
    for lib, source_id, source in _edge_stroke_sources():
        r = lint_wgsl(source_id, source, SHADER_CONTRACTS["edge_strokes"])
        assert "u_theme_color_1" in r.uniforms
        assert "u_theme_color_2" in r.uniforms


def test_page_linings_have_no_uniforms_by_contract():
    # Page-lining shaders bake their palette in as literals; the
    # contract accepts zero uniforms, but let's confirm none of them
    # accidentally sprouted a uniform binding block (which would break
    # the pipeline layout the renderer expects).
    for lib, source_id, source in _lining_sources():
        r = lint_wgsl(source_id, source, SHADER_CONTRACTS["page_linings"])
        # Zero uniform bindings expected — struct field discovery is
        # allowed to find nothing.
        binding_re = re.compile(r"var\s*<\s*uniform\s*>")
        assert not binding_re.search(source), (
            f"{source_id}: unexpected var<uniform> binding"
        )
        assert r.parseable


def test_washi_source_ids_are_unique():
    seen: set[str] = set()
    for _, sid, _ in _washi_sources():
        assert sid not in seen
        seen.add(sid)


def test_edge_stroke_source_ids_are_unique():
    seen: set[str] = set()
    for _, sid, _ in _edge_stroke_sources():
        assert sid not in seen
        seen.add(sid)


def test_lining_source_ids_are_unique():
    seen: set[str] = set()
    for _, sid, _ in _lining_sources():
        assert sid not in seen
        seen.add(sid)
