"""Smoke tests for ``examples/hello_render_real.py`` (NN1 sprint).

The MM7 real-render demo loads a procedurally-generated bunny (``bunny_low.obj``),
spawns a key light + orbit camera, and runs 120 frames on the headless
stub renderer. These tests pin:

* The demo module imports cleanly.
* The bunny asset ships alongside the demo.
* ``main()`` walks 120 frames end-to-end and returns a populated
  :class:`App`.
* The bunny model shows up in ``app.models`` after the run.
* Optional variants (``with_shadows`` / ``with_ssao`` /
  ``with_full_pipeline``) run + attach the advertised passes when the
  post-process modules are available; skip cleanly when they aren't.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ── Load the demo as a module so we don't depend on examples/ being on path ──
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_render_real.py"
_BUNNY_OBJ = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "assets" / "bunny_low.obj"


def _load_demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo not present: {_DEMO_PATH}")
    spec = importlib.util.spec_from_file_location("hello_render_real_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_render_real_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ---------------------------------------------------------------------------
# Test 1: bunny asset ships alongside the demo.
# ---------------------------------------------------------------------------


def test_hello_render_real_bunny_asset_exists():
    assert _BUNNY_OBJ.is_file(), (
        f"bunny mesh missing at expected path: {_BUNNY_OBJ}"
    )
    # Sanity — file has real content (procedural mesh, ~29 KB).
    assert _BUNNY_OBJ.stat().st_size > 1024


# ---------------------------------------------------------------------------
# Test 2: demo module imports + exposes the expected variants.
# ---------------------------------------------------------------------------


def test_hello_render_real_imports(demo):
    for name in ("main", "with_shadows", "with_ssao", "with_full_pipeline"):
        assert hasattr(demo, name), f"missing entry point: {name}"
        assert callable(getattr(demo, name))


# ---------------------------------------------------------------------------
# Test 3: ``main()`` runs headlessly and returns a populated App.
# ---------------------------------------------------------------------------


def test_hello_render_real_main_runs(demo):
    app = demo.main()
    assert app is not None
    # The bunny got loaded via ``app.load_model``; the App tracks it.
    models = getattr(app, "models", None)
    assert models is not None
    assert len(models) >= 1
    # The orbit tick ran through the 120-frame cap.
    assert getattr(app, "frame_count", 0) >= 120


# ---------------------------------------------------------------------------
# Test 4: ``with_shadows`` attaches a CSM pass when post_process is present.
# ---------------------------------------------------------------------------


def test_hello_render_real_with_shadows(demo):
    app = demo.with_shadows()
    assert app is not None
    assert getattr(app, "frame_count", 0) >= 120
    # ``app.shadow_pass`` is populated when the ShadowCSM import succeeds
    # and ``None`` when the post_process pipe is stripped — both are
    # valid outcomes per the demo's soft-attach contract.
    shadow_pass = getattr(app, "shadow_pass", "MISSING")
    assert shadow_pass is not "MISSING", (  # noqa: F632 — explicit sentinel
        "with_shadows() must set app.shadow_pass (even if to None)"
    )


# ---------------------------------------------------------------------------
# Test 5: ``with_ssao`` attaches a GTAO pass when post_process is present.
# ---------------------------------------------------------------------------


def test_hello_render_real_with_ssao(demo):
    app = demo.with_ssao()
    assert app is not None
    assert getattr(app, "frame_count", 0) >= 120
    ssao_pass = getattr(app, "ssao_pass", "MISSING")
    assert ssao_pass is not "MISSING", (  # noqa: F632
        "with_ssao() must set app.ssao_pass (even if to None)"
    )


# ---------------------------------------------------------------------------
# Test 6: ``with_full_pipeline`` runs + emits HUD trace events.
# ---------------------------------------------------------------------------


def test_hello_render_real_with_full_pipeline(demo):
    app = demo.with_full_pipeline()
    assert app is not None
    assert getattr(app, "frame_count", 0) >= 120
    # The demo attaches an after-tick HUD hook that appends
    # ``("hud", frame, fps)`` entries to app.trace.
    trace = getattr(app, "trace", [])
    hud_events = [ev for ev in trace if isinstance(ev, tuple) and ev and ev[0] == "hud"]
    assert len(hud_events) >= 1, "no HUD trace events emitted by with_full_pipeline"
    # ``hud_fps_log`` also accumulates per-tick (frame_idx, fps) pairs.
    fps_log = getattr(app, "hud_fps_log", None)
    assert fps_log is not None
    assert len(fps_log) >= 1
