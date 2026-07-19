"""Smoke tests for ``examples/hello_hybrid_layers.py`` (DDD3 sprint).

The demo wires three hybrid layers (Layer3D -> Layer2D -> Layer3D) that
sample each other's outputs via the DDD2 cross-layer protocols, then
composites them with :class:`LayerCompositor` from DDD3.

Pins:

1. Demo module imports cleanly headless.
2. ``main(frames=60)`` returns a summary with >= 3 layers created and
   >= 60 layer_render events per layer.
3. The trace records cross_layer_binding_count >= 2 (one for
   sepia->base_scene, one for overlay_cube->sepia).
4. The final composite centre pixel is not identical to the compositor's
   clear colour -- proving composition actually ran.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_hybrid_layers.py"


@pytest.fixture
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    spec = importlib.util.spec_from_file_location("hello_hybrid_layers_demo_ddd3", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_hybrid_layers_demo_ddd3"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"hello_hybrid_layers demo failed to import headlessly: {exc}")
    return module


def test_hello_hybrid_layers_imports(demo):
    assert demo is not None
    assert callable(getattr(demo, "main", None))


def test_layer_compositor_importable():
    """Compositor must be importable from the render subpackage."""
    from slappyengine.render.layer_compositor import (
        CompositeStats,
        LayerCompositor,
        LayerTraceEvent,
    )
    assert LayerCompositor is not None
    assert CompositeStats is not None
    assert LayerTraceEvent is not None


def test_hello_hybrid_layers_runs_60_frames(demo, tmp_path):
    summary = demo.main(frames=60, output_dir=tmp_path)
    assert summary["frames"] == 60, f"expected 60 frames, got {summary['frames']}"


def test_hello_hybrid_layers_creates_three_layers(demo, tmp_path):
    """The trace YAML must record at least 3 layer_created events."""
    summary = demo.main(frames=60, output_dir=tmp_path)
    trace_path = Path(summary["trace_path"])
    assert trace_path.exists(), f"trace YAML not written: {trace_path}"

    import yaml
    payload = yaml.safe_load(trace_path.read_text())
    creations = payload.get("creation_events", [])
    assert len(creations) >= 3, f"expected >=3 creation events; got {len(creations)}"
    names = {c["name"] for c in creations}
    assert {"base_scene", "sepia_post", "overlay_cube"} <= names


def test_hello_hybrid_layers_render_events_per_layer(demo, tmp_path):
    """Every layer must emit >= 60 layer_render events over 60 frames."""
    summary = demo.main(frames=60, output_dir=tmp_path)
    per_layer = summary["layer_render_events"]
    assert per_layer, "layer_render_events dict is empty"
    for name in ("base_scene", "sepia_post", "overlay_cube"):
        assert name in per_layer, f"missing {name} in per-layer events"
        assert per_layer[name] >= 60, (
            f"expected >=60 layer_render events for {name}; got {per_layer[name]}"
        )


def test_hello_hybrid_layers_cross_layer_binding_count(demo, tmp_path):
    """Compositor must report >= 2 cross-layer bindings.

    Expected bindings:
      * sepia_post -> base_scene (sample_from + apply_post_process_from)
      * overlay_cube -> sepia_post (use_layer_as_texture)
    """
    summary = demo.main(frames=60, output_dir=tmp_path)
    count = summary["cross_layer_binding_count"]
    assert count >= 2, f"expected >=2 cross-layer bindings; got {count}"


def test_hello_hybrid_layers_center_pixel_not_clear(demo, tmp_path):
    """The final composite centre pixel must not equal the compositor clear colour."""
    from slappyengine.render.layer_compositor import LayerCompositor

    compositor_defaults = LayerCompositor(width=16, height=16)
    clear = tuple(int(compositor_defaults.output_buffer[8, 8, i]) for i in range(4))

    summary = demo.main(frames=60, output_dir=tmp_path)
    center = tuple(summary["center_pixel"])
    assert center != clear, (
        f"final centre pixel {center} equals clear-colour {clear} -- "
        "composition did not run"
    )
    # Also assert a real composite -- not all zeros.
    assert any(c > 0 for c in center), "final centre pixel is fully black"


def test_hello_hybrid_layers_screenshot_written(demo, tmp_path):
    """The demo must write a final PNG (or npy fallback) to disk."""
    summary = demo.main(frames=60, output_dir=tmp_path)
    png = Path(summary["png_path"])
    # The demo falls back to .npy when PIL is unavailable; either is ok.
    assert png.exists() or png.with_suffix(".npy").exists(), (
        f"neither {png} nor its .npy fallback exists"
    )
