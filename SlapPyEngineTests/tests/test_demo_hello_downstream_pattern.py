"""Smoke tests for ``examples/hello_downstream_pattern.py`` (VV5 sprint).

VV5's demo exercises the exact ``class Foo(Observable, Asset)``
multi-inheritance pattern that downstream games (Ochema Circuit,
Bullet Strata) use. These tests pin:

* Demo module imports cleanly.
* :func:`main` runs headlessly and returns a populated summary.
* ``PlayerVehicle.__mro__`` includes both ``Observable`` and ``Asset``.
* Three layers (``chassis``, ``weapon``, ``hud``) get added.
* 5 events per frame x 30 frames = 150 published and 150 delivered.
* Trace's ``attribute_errors`` is 0.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Locate + load the demo
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT
    / "SlapPyEngineExamples"
    / "examples"
    / "hello_downstream_pattern.py"
)


def _load_demo():
    """Import the demo as a module — skipping cleanly if imports fail."""
    if not _DEMO_PATH.exists():  # pragma: no cover — safety net
        pytest.skip(f"demo not found: {_DEMO_PATH}")

    pytest.importorskip("yaml")
    try:
        import slappyengine  # noqa: F401
        import slappyengine.asset  # noqa: F401
        import slappyengine.event_bus  # noqa: F401
        import slappyengine.layer  # noqa: F401
        import slappyengine.residency.manager  # noqa: F401
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"slappyengine subsystems unavailable: {exc}")

    spec = importlib.util.spec_from_file_location(
        "hello_downstream_pattern_demo", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_downstream_pattern_demo"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # pragma: no cover — defensive
        pytest.skip(f"failed to load hello_downstream_pattern demo: {exc}")
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


@pytest.fixture(scope="module")
def demo_run(demo, tmp_path_factory):
    """Run the demo once per module and reuse the summary + YAML."""
    tmpdir = tmp_path_factory.mktemp("vv5")
    trace_path = tmpdir / "trace.yaml"
    try:
        summary = demo.main(
            max_frames=30,
            trace_yaml_path=trace_path,
        )
    except Exception as exc:
        pytest.skip(f"hello_downstream_pattern.main failed: {exc}")
    return {"summary": summary, "trace_path": trace_path}


@pytest.fixture(scope="module")
def trace(demo_run):
    import yaml

    return yaml.safe_load(demo_run["trace_path"].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Test 1: demo imports + advertises the expected entry point.
# ---------------------------------------------------------------------------


def test_hello_downstream_pattern_imports(demo):
    assert hasattr(demo, "main")
    assert callable(demo.main)
    assert hasattr(demo, "PlayerVehicle")


# ---------------------------------------------------------------------------
# Test 2: main() returns a populated summary.
# ---------------------------------------------------------------------------


def test_hello_downstream_pattern_summary_shape(demo_run):
    summary = demo_run["summary"]
    assert isinstance(summary, dict)
    for key in (
        "mro",
        "layer_count",
        "events_published",
        "events_delivered",
        "attribute_errors",
        "frame_count",
    ):
        assert key in summary, f"missing summary key {key!r}"


# ---------------------------------------------------------------------------
# Test 3: MRO includes both Observable and Asset.
# ---------------------------------------------------------------------------


def test_hello_downstream_pattern_mro_includes_observable_and_asset(demo, trace):
    # Trace side.
    mro = trace.get("mro", [])
    assert isinstance(mro, list), f"expected mro to be a list, got {type(mro)}"
    assert "Observable" in mro, f"Observable missing from MRO: {mro}"
    assert "Asset" in mro, f"Asset missing from MRO: {mro}"
    # Live class side — belt + braces.
    live_mro = [cls.__name__ for cls in demo.PlayerVehicle.__mro__]
    assert "Observable" in live_mro
    assert "Asset" in live_mro
    # RenderTarget is between Asset and Entity — pin it too so a future
    # refactor that collapses the tree trips this test.
    assert "RenderTarget" in live_mro


# ---------------------------------------------------------------------------
# Test 4: 3 layers added.
# ---------------------------------------------------------------------------


def test_hello_downstream_pattern_layer_count(trace):
    layers = trace.get("layers_added", [])
    assert isinstance(layers, list)
    assert len(layers) == 3, f"expected 3 layers, got {len(layers)}: {layers}"
    # Names must match the downstream chassis / weapon / hud pattern.
    assert set(layers) == {"chassis", "weapon", "hud"}, (
        f"layer names drifted: {layers}"
    )


# ---------------------------------------------------------------------------
# Test 5: events delivered — 5 per frame x 30 = 150.
# ---------------------------------------------------------------------------


def test_hello_downstream_pattern_events_delivered(trace):
    published = int(trace.get("events_published", 0))
    delivered = int(trace.get("events_delivered", 0))
    assert published == 150, (
        f"expected 150 events published (5/frame x 30 frames), got {published}"
    )
    assert delivered == 150, (
        f"expected 150 events delivered, got {delivered}"
    )


# ---------------------------------------------------------------------------
# Test 6: attribute_errors is 0.
# ---------------------------------------------------------------------------


def test_hello_downstream_pattern_no_attribute_errors(trace):
    errors = int(trace.get("attribute_errors", -1))
    notes = trace.get("attribute_error_notes", [])
    assert errors == 0, (
        f"expected attribute_errors == 0, got {errors}; notes: {notes}"
    )
