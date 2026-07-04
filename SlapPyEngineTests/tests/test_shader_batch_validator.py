"""Tests for :mod:`slappyengine.ui.theme.shader_batch_validator` (DD6).

Covers:

* The end-to-end sweep produces a non-empty summary.
* Every built-in library (washi tape / page linings / edge strokes)
  is present in the summary and reports zero failures.
* The ``by_library`` payload categorises correctly and records
  matching ``passed``/``failed`` counters.
* Report generation always yields a Markdown table.
* The timeout budget is honoured — a patched clock that races the
  deadline forces the sweep to short-circuit.
* :func:`save_shader_manifest` writes a document that either parses
  as YAML or as JSON (the two-tier fallback is intentional).
* Missing search directories are skipped without raising.
* When wgpu is unavailable the linter-only path still returns a
  populated summary.
* CLI helper functions round-trip through disk without leaking.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from slappyengine.ui.theme import shader_batch_validator as sbv
from slappyengine.ui.theme.shader_batch_validator import (
    ValidationSummary,
    _collect_wgsl_manifest_entries,
    _iter_theme_library_sources,
    _lint_one,
    _result_to_dict,
    generate_report,
    save_shader_manifest,
    validate_all_shaders,
    write_report,
)
from slappyengine.ui.theme.shader_lint import WGSLLintResult


# ---------------------------------------------------------------------------
# Sweep — happy path
# ---------------------------------------------------------------------------


def test_validate_all_shaders_returns_non_empty_summary() -> None:
    summary = validate_all_shaders()
    assert isinstance(summary, ValidationSummary)
    assert summary.total > 0
    # We expect at least 15 washi + 15 linings + 15 edge stroke shaders.
    assert summary.total >= 45
    assert summary.passed + summary.failed == summary.total
    assert summary.wall_seconds >= 0.0


def test_validate_all_shaders_categorises_libraries() -> None:
    summary = validate_all_shaders()
    assert "washi_tape" in summary.by_library
    assert "page_linings" in summary.by_library
    assert "edge_strokes" in summary.by_library
    for name in ("washi_tape", "page_linings", "edge_strokes"):
        bucket = summary.by_library[name]
        assert bucket["total"] > 0
        assert (
            bucket["passed"] + bucket["failed"] + bucket.get("skipped", 0)
            == bucket["total"] + bucket.get("skipped", 0)
        )
        # Each bucket carries the wgpu-available flag.
        assert "wgpu_available" in bucket
        assert isinstance(bucket["results"], list)


def test_builtin_library_shaders_all_pass() -> None:
    summary = validate_all_shaders()
    for name in ("washi_tape", "page_linings", "edge_strokes"):
        bucket = summary.by_library[name]
        assert bucket["failed"] == 0, (
            f"library {name!r} unexpectedly failed some shaders: "
            f"{[r['source_id'] for r in bucket['results'] if not r['parseable']]}"
        )
    # No built-in id should ever appear in the failing list.
    for full_id in summary.failing_ids:
        library = full_id.split("::", 1)[0]
        assert library not in {"washi_tape", "page_linings", "edge_strokes"}


# ---------------------------------------------------------------------------
# Sweep — flag switches
# ---------------------------------------------------------------------------


def test_hello_examples_can_be_toggled_off() -> None:
    with_hellos = validate_all_shaders(include_hello_examples=True)
    without_hellos = validate_all_shaders(include_hello_examples=False)
    assert without_hellos.total <= with_hellos.total
    assert "hello_examples" not in without_hellos.by_library


def test_baked_can_be_toggled_off() -> None:
    with_baked = validate_all_shaders(include_baked=True)
    without_baked = validate_all_shaders(include_baked=False)
    # ``baked_wgsl`` may not exist on disk — either way, dropping the
    # flag must not increase the total.
    assert without_baked.total <= with_baked.total


# ---------------------------------------------------------------------------
# Sweep — argument validation
# ---------------------------------------------------------------------------


def test_validate_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError):
        validate_all_shaders(timeout_s=0.0)
    with pytest.raises(ValueError):
        validate_all_shaders(timeout_s=-1.0)


def test_validate_rejects_wrong_type_kwargs() -> None:
    with pytest.raises(TypeError):
        validate_all_shaders(include_hello_examples="yes")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validate_all_shaders(include_baked=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        validate_all_shaders(timeout_s="30")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Sweep — timeout patching
# ---------------------------------------------------------------------------


class _StepClock:
    """A monotonic clock that advances by ``step`` on every call."""

    def __init__(self, step: float = 5.0) -> None:
        self._t = 0.0
        self._step = step

    def __call__(self) -> float:
        now = self._t
        self._t += self._step
        return now


def test_timeout_short_circuits_sweep() -> None:
    # Each tick advances the clock 5s → the second lint call already
    # blows the 1s budget.
    clock = _StepClock(step=5.0)
    summary = validate_all_shaders(timeout_s=1.0, clock=clock)
    # At least one library should have picked up skips.
    total_skipped = sum(
        bucket.get("skipped", 0) for bucket in summary.by_library.values()
    )
    assert total_skipped >= 1
    # The reported wall-clock reflects the patched clock.
    assert summary.wall_seconds > 0.0


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def test_generate_report_contains_markdown_table() -> None:
    summary = validate_all_shaders(include_hello_examples=False, include_baked=False)
    text = generate_report(summary)
    assert isinstance(text, str)
    assert text.startswith("# WGSL Shader Batch Validation Report")
    # Table markers.
    assert "| Library | Total | Passed | Failed |" in text
    assert "|---|---:|---:|---:|" in text
    # Per-library headers.
    assert "`washi_tape`" in text
    assert "`page_linings`" in text
    assert "`edge_strokes`" in text


def test_generate_report_rejects_wrong_type() -> None:
    with pytest.raises(TypeError):
        generate_report({"total": 0})  # type: ignore[arg-type]


def test_generate_report_no_failures_says_so() -> None:
    summary = ValidationSummary(total=3, passed=3, failed=0, by_library={
        "washi_tape": {
            "total": 3, "passed": 3, "failed": 0, "skipped": 0,
            "wgpu_available": False, "results": [
                {"source_id": "a", "size_bytes": 100, "entry_point_name": "fs_main",
                 "has_entry_point": True, "uniforms": [], "errors": [],
                 "warnings": [], "parseable": True},
            ],
        },
    })
    text = generate_report(summary)
    assert "_No failures" in text


def test_generate_report_lists_failing_sources() -> None:
    summary = ValidationSummary(
        total=1, passed=0, failed=1,
        failing_ids=["hello_examples::bad_shader"],
        by_library={
            "hello_examples": {
                "total": 1, "passed": 0, "failed": 1, "skipped": 0,
                "wgpu_available": False, "results": [
                    {"source_id": "bad_shader", "size_bytes": 42,
                     "entry_point_name": "", "has_entry_point": False,
                     "uniforms": [], "errors": [[0, "missing @fragment entry point"]],
                     "warnings": [], "parseable": False},
                ],
            },
        },
    )
    text = generate_report(summary)
    assert "`hello_examples::bad_shader`" in text
    assert "missing @fragment entry point" in text


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def test_write_report_creates_file(tmp_path: Path) -> None:
    summary = validate_all_shaders(include_hello_examples=False, include_baked=False)
    out = tmp_path / "sub" / "shader_report.md"
    result_path = write_report(summary, out)
    assert result_path == out
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# WGSL Shader Batch Validation Report")


def test_write_report_accepts_str_path(tmp_path: Path) -> None:
    summary = ValidationSummary()
    out = str(tmp_path / "report.md")
    result_path = write_report(summary, out)
    assert result_path.exists()


def test_write_report_rejects_wrong_type() -> None:
    summary = ValidationSummary()
    with pytest.raises(TypeError):
        write_report(summary, 42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# YAML manifest
# ---------------------------------------------------------------------------


def _parse_yaml_or_json(text: str) -> Any:
    try:
        import yaml  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - env-dependent
        return json.loads(text)
    return yaml.safe_load(text)


def test_save_shader_manifest_produces_parseable_document(tmp_path: Path) -> None:
    out = tmp_path / "shader_manifest.yaml"
    save_shader_manifest(out)
    assert out.exists()
    payload = _parse_yaml_or_json(out.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    assert payload["schema"] == "slappyengine.shader_manifest"
    assert payload["version"] == 1
    assert isinstance(payload["shaders"], list)
    assert payload["count"] == len(payload["shaders"])
    # Manifest carries at least every built-in library shader.
    assert payload["count"] >= 45
    for entry in payload["shaders"]:
        assert isinstance(entry["library"], str)
        assert isinstance(entry["source_id"], str)
        assert isinstance(entry["origin"], str)
        assert isinstance(entry["size_bytes"], int)
        assert entry["size_bytes"] >= 0


def test_save_shader_manifest_rejects_wrong_type() -> None:
    with pytest.raises(TypeError):
        save_shader_manifest(123)  # type: ignore[arg-type]


def test_save_shader_manifest_creates_parent(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "deeper" / "manifest.yaml"
    save_shader_manifest(out)
    assert out.exists()


# ---------------------------------------------------------------------------
# Missing directories + linter-only path
# ---------------------------------------------------------------------------


def test_missing_directory_handled_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    # Point every search dir at something that doesn't exist. The sweep
    # must still complete on the theme libraries alone.
    monkeypatch.setattr(
        sbv,
        "WGSL_SEARCH_DIRS",
        [("phantom", "does/not/exist")],
    )
    summary = validate_all_shaders(include_hello_examples=False, include_baked=False)
    # Built-in libraries still contribute.
    assert summary.total >= 45
    # The phantom directory produced no entries → no phantom bucket.
    assert "phantom" not in summary.by_library


def test_wgpu_unavailable_returns_populated_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sbv, "wgpu_available", lambda: False)
    summary = validate_all_shaders(include_hello_examples=False, include_baked=False)
    assert summary.total > 0
    for bucket in summary.by_library.values():
        assert bucket["wgpu_available"] is False


# ---------------------------------------------------------------------------
# Helper coverage
# ---------------------------------------------------------------------------


def test_lint_one_reports_empty_source_as_failure() -> None:
    result = _lint_one("hello_examples", "empty", "", {"max_bytes": 100})
    assert isinstance(result, WGSLLintResult)
    assert not result.parseable
    assert result.errors
    assert result.errors[0][1] == "empty or unreadable source file"


def test_result_to_dict_round_trip() -> None:
    dummy = WGSLLintResult(
        source_id="x",
        size_bytes=10,
        has_entry_point=True,
        entry_point_name="fs_main",
        uniforms=["u_time"],
        errors=[(1, "boom")],
        warnings=[(2, "warn")],
        parseable=False,
    )
    d = _result_to_dict(dummy)
    assert d["source_id"] == "x"
    assert d["errors"] == [[1, "boom"]]
    assert d["warnings"] == [[2, "warn"]]
    assert d["parseable"] is False


def test_theme_iterator_yields_expected_libraries() -> None:
    libs = {row[0] for row in _iter_theme_library_sources()}
    assert libs == {"washi_tape", "page_linings", "edge_strokes"}


def test_manifest_entries_include_embedded_and_examples() -> None:
    entries = _collect_wgsl_manifest_entries()
    origins = {entry["origin"] for entry in entries}
    assert "embedded" in origins
    # Every entry has non-empty ids.
    for entry in entries:
        assert entry["library"]
        assert entry["source_id"]


def test_public_api_exports_are_available() -> None:
    for name in (
        "ValidationSummary",
        "validate_all_shaders",
        "generate_report",
        "write_report",
        "save_shader_manifest",
    ):
        assert hasattr(sbv, name)
    # __all__ is a superset of the required deliverables.
    assert "ValidationSummary" in sbv.__all__
    assert "validate_all_shaders" in sbv.__all__
    assert "generate_report" in sbv.__all__
    assert "write_report" in sbv.__all__
    assert "save_shader_manifest" in sbv.__all__
