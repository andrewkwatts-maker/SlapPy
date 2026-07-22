"""Tests for ``examples/hello_render.py`` — the 2-line pip-install demo.

Pins nine behaviours of the flagship "getting started" example:

1. :func:`minimal` runs without exception and returns a live app.
2. :func:`with_light_and_camera` rotates its model over the run window.
3. :func:`custom_lifecycle` fires begin, tick, and end hooks the right
   number of times.
4. :func:`with_config_yaml` accepts a missing path and still boots.
5. :func:`with_config_yaml` accepts a real YAML file with an ``[app]``
   section and honours its ``target_fps``.
6. Every variant produces at least one model in ``app.models``.
7. Every variant records at least one ``draw_model`` in the stub
   renderer's log.
8. The bundled ``assets/triangle.obj`` is present and non-empty.
9. The 2-line pattern the user asked for actually works: ``import
   pharos_engine`` + a single call to ``pharos_engine.launch`` produces a
   rendered model with zero further plumbing.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Demo module loader
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_render.py"
_TRIANGLE_OBJ = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "assets" / "triangle.obj"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_render_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_render_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _draw_calls(app) -> list:
    """Return only the draw_model entries from the stub renderer log."""
    log = getattr(app._renderer, "log", [])
    return [entry for entry in log if entry and entry[0] == "draw_model"]


# ---------------------------------------------------------------------------
# 1. minimal() runs and returns a live app
# ---------------------------------------------------------------------------


def test_minimal_runs_without_exception(demo):
    app = demo.minimal()
    assert app is not None
    assert app.frame_count == 60
    # The 2-line pattern must leave a usable app for introspection.
    assert not app.is_closed


# ---------------------------------------------------------------------------
# 2. with_light_and_camera rotates + spawns light + camera
# ---------------------------------------------------------------------------


def test_with_light_and_camera_rotates_model(demo):
    app = demo.with_light_and_camera()
    assert app.frame_count == 60
    assert len(app.models) == 1
    assert len(app.lights) == 1
    assert app.active_camera is not None

    model = app.models[0]
    # 60 rotate_by calls at dt = 1/60 → ry ≈ 1.0 radian.
    assert model.rotation[1] == pytest.approx(1.0, rel=0.02)
    # x and z untouched.
    assert model.rotation[0] == 0.0
    assert model.rotation[2] == 0.0


# ---------------------------------------------------------------------------
# 3. custom_lifecycle hook counts
# ---------------------------------------------------------------------------


def test_custom_lifecycle_hook_counts(demo, capsys):
    app = demo.custom_lifecycle()
    assert app._begin_fired == 1
    assert app._end_fired == 1
    assert app._tick_fired == 60
    # The demo prints "Rendered N frames" from on_end -- make sure it
    # actually reached the console.
    captured = capsys.readouterr().out
    assert "Rendered 60 frames" in captured


# ---------------------------------------------------------------------------
# 4. with_config_yaml boots with a missing path
# ---------------------------------------------------------------------------


def test_with_config_yaml_missing_path_boots(demo, tmp_path):
    """A path that does not exist must not raise -- defaults are used."""
    missing = tmp_path / "does_not_exist.yaml"
    app = demo.with_config_yaml(missing)
    assert app is not None
    assert app.frame_count == 60
    assert len(app.models) == 1


# ---------------------------------------------------------------------------
# 5. with_config_yaml honours a real YAML file
# ---------------------------------------------------------------------------


def test_with_config_yaml_honours_target_fps(demo, tmp_path):
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        "app:\n"
        "  target_fps: 30\n"
        "  window_title: hello_render_test\n",
        encoding="utf-8",
    )
    app = demo.with_config_yaml(cfg_path)
    assert app.config.target_fps == 30
    assert app.config.window_title == "hello_render_test"
    assert app.frame_count == 60


# ---------------------------------------------------------------------------
# 6. Every variant produces at least one model
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    ["minimal", "with_light_and_camera", "with_config_yaml", "custom_lifecycle"],
)
def test_every_variant_produces_a_model(demo, variant, tmp_path):
    fn = getattr(demo, variant)
    if variant == "with_config_yaml":
        app = fn(tmp_path / "unused.yaml")
    else:
        app = fn()
    assert len(app.models) >= 1
    # The model must be the bundled triangle.
    assert app.models[0].path.endswith("triangle.obj")


# ---------------------------------------------------------------------------
# 7. Every variant records draw_model calls in the stub renderer log
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    ["minimal", "with_light_and_camera", "with_config_yaml", "custom_lifecycle"],
)
def test_every_variant_records_draw_calls(demo, variant, tmp_path):
    fn = getattr(demo, variant)
    if variant == "with_config_yaml":
        app = fn(tmp_path / "unused.yaml")
    else:
        app = fn()
    calls = _draw_calls(app)
    assert len(calls) >= 1, f"{variant} produced no draw_model log entries"
    # With one visible model over 60 frames the stub renderer records
    # exactly 60 draw calls.
    assert len(calls) == 60


# ---------------------------------------------------------------------------
# 8. Bundled asset exists on disk
# ---------------------------------------------------------------------------


def test_bundled_triangle_asset_exists():
    assert _TRIANGLE_OBJ.exists(), f"missing bundled asset at {_TRIANGLE_OBJ}"
    text = _TRIANGLE_OBJ.read_text(encoding="utf-8")
    # Sanity: at least 3 vertex lines and one face line.
    assert text.count("\nv ") + text.startswith("v ") >= 3
    assert "\nf " in text or text.startswith("f ")


# ---------------------------------------------------------------------------
# 9. The literal 2-line pattern works end-to-end
# ---------------------------------------------------------------------------


def test_two_line_pattern_end_to_end():
    """This is the user's ask -- if this fails we've broken the promise.

    Two lines: ``import pharos_engine`` + a single ``launch(...)`` call
    with a lambda loading the triangle must produce a rendered model
    without any other setup.
    """
    import pharos_engine

    triangle = str(_TRIANGLE_OBJ)
    app = pharos_engine.launch(
        on_begin=lambda a: a.load_model(triangle),
        max_frames=3,
        config=pharos_engine.AppConfig(enable_gpu=False, renderer_backend="stub"),
    )
    assert app is not None
    assert len(app.models) == 1
    assert app.frame_count == 3
    calls = _draw_calls(app)
    assert len(calls) == 3


# ---------------------------------------------------------------------------
# 10. Trace log contains lifecycle markers for every variant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    ["minimal", "with_light_and_camera", "with_config_yaml", "custom_lifecycle"],
)
def test_trace_contains_lifecycle_markers(demo, variant, tmp_path):
    fn = getattr(demo, variant)
    if variant == "with_config_yaml":
        app = fn(tmp_path / "unused.yaml")
    else:
        app = fn()
    ops = [entry[0] for entry in app.trace]
    assert "run_begin" in ops
    assert "on_begin_fired" in ops
    assert "run_end" in ops
    assert "on_end_fired" in ops
