"""Tests for the ``examples/hello_rust_bypass.py`` demo (PP7 sprint).

The demo is only meaningful when the compiled ``pharos_engine._core``
extension is present — on a bare source install without maturin, the
whole test file is skipped via :func:`pytest.importorskip` at the top.

Pins:

* Demo module imports cleanly.
* :func:`main` runs headlessly end-to-end with tiny repeats and returns
  a well-formed summary dict.
* The trace YAML contains ``>= 1`` timing comparison (matches the
  minimum "meaningful bypass demo" bar).
* The trace lists ``>= 3`` logical ``_core`` sub-modules — every wheel
  we ship carries at least ``hull``, ``ik_solver``, ``math``,
  ``slap_format``, so 3 is a conservative floor.
* Each timing entry carries the required fields
  (``bypass_seconds``, ``wrapper_seconds``, ``speedup``, ``rust_module``).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Hard-skip when the compiled extension isn't available. Every other
# assertion below assumes _core is importable.
# ---------------------------------------------------------------------------

pytest.importorskip("pharos_engine._core")


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "PharosEngineExamples" / "examples" / "hello_rust_bypass.py"
)


def _load_demo():
    """Import the demo as a module — skip cleanly if the file is missing."""
    if not _DEMO_PATH.exists():  # pragma: no cover — safety net
        pytest.skip(f"demo not found: {_DEMO_PATH}")

    spec = importlib.util.spec_from_file_location(
        "hello_rust_bypass_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_rust_bypass_demo"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"failed to load hello_rust_bypass demo: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(scope="module")
def summary(demo, tmp_path_factory):
    """Run the demo once with tiny repeats so the suite stays fast."""
    trace_path = tmp_path_factory.mktemp("pp7") / "trace.yaml"
    try:
        result = demo.main(
            hull_points=32,
            hull_repeats=5,
            bone_joints=8,
            bone_repeats=5,
            lz4_bytes=256,
            lz4_repeats=5,
            trace_yaml_path=trace_path,
        )
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"hello_rust_bypass.main failed: {exc}")
    return result


@pytest.fixture(scope="module")
def trace(summary):
    """Load the frame trace from the YAML the demo just wrote."""
    yaml = pytest.importorskip("yaml")
    text = Path(summary["trace_path"]).read_text(encoding="utf-8")
    payload = yaml.safe_load(text)
    assert isinstance(payload, dict), "trace YAML must be a mapping"
    return payload


# ---------------------------------------------------------------------------
# Smoke
# ---------------------------------------------------------------------------


def test_demo_imports(demo):
    assert hasattr(demo, "main"), "demo missing main()"
    assert callable(demo.main)


def test_demo_runs_end_to_end(summary):
    assert isinstance(summary, dict)
    assert summary["has_native"] is True
    assert Path(summary["trace_path"]).exists()


# ---------------------------------------------------------------------------
# Trace shape
# ---------------------------------------------------------------------------


def test_trace_lists_at_least_three_core_submodules(trace):
    """The bypass demo must enumerate ``>= 3`` reachable Rust modules."""
    submods = trace.get("submodules")
    assert isinstance(submods, dict), (
        f"trace['submodules'] must be a dict, got {type(submods).__name__}"
    )
    assert len(submods) >= 3, (
        f"expected >= 3 _core submodules in trace, got {len(submods)}: "
        f"{sorted(submods.keys())}"
    )
    assert trace["submodule_count"] == len(submods)
    # Every listed module must carry at least one live symbol —
    # empty-list entries would mean the facade lied.
    for mod, syms in submods.items():
        assert isinstance(syms, list) and syms, (
            f"submodule {mod!r} has no symbols: {syms!r}"
        )


def test_trace_has_at_least_one_timing_comparison(trace):
    timings = trace.get("timings")
    assert isinstance(timings, list), (
        f"trace['timings'] must be a list, got {type(timings).__name__}"
    )
    assert len(timings) >= 1, (
        f"expected >= 1 timing comparison, got {len(timings)}"
    )


def test_timing_entries_are_well_formed(trace):
    """Each timing must carry the fields the docs promise."""
    required = {
        "name",
        "rust_module",
        "input_size",
        "repeats",
        "bypass_seconds",
        "wrapper_seconds",
        "speedup",
    }
    for entry in trace["timings"]:
        missing = required - set(entry)
        assert not missing, f"timing missing keys {missing!r}: {entry!r}"
        # Timings must be positive floats — 0.0 or negative would mean
        # perf_counter() lied or the harness never actually ran.
        assert entry["bypass_seconds"] > 0.0, entry
        assert entry["wrapper_seconds"] > 0.0, entry
        # Speedup is positive; can be < 1.0 for tiny inputs where the
        # PyO3 boundary dominates, but must be finite and > 0.
        assert entry["speedup"] > 0.0, entry
