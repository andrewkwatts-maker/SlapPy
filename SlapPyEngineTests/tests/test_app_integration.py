"""HH1 ↔ HH4 ↔ HH5 integration tripwire suite.

Covers :mod:`slappyengine.app_integration` — the bridge that wires the
HH1 :class:`App` API to the HH4 forward renderer and the HH5 asset
importer. Also exercises the HH1 extensions:
:meth:`App._load_via_asset_importer`, :meth:`App.render_frame`, and
:meth:`App.get_bounding_box_of_all_models`.

The suite deliberately soft-skips any test that needs a subpackage
which isn't importable in the current environment (e.g. wgpu on
headless CI) so the whole file stays green everywhere.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

import slappyengine
from slappyengine.app import App, AppConfig, ModelHandle, _StubRenderer

# Sample asset shipped by HH5 for tests + docs.
from slappyengine.asset_import.samples import TRIANGLE_OBJ


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_app() -> App:
    """Return a freshly-constructed :class:`App` with GPU disabled by default."""
    app = App(AppConfig(enable_gpu=False, max_frames=1))
    yield app
    app.close()


def _has_render_subpackage() -> bool:
    try:
        import slappyengine.render  # noqa: F401
    except Exception:
        return False
    return True


def _wgpu_available() -> bool:
    try:
        from slappyengine.render import is_wgpu_available

        return bool(is_wgpu_available())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# default_material
# ---------------------------------------------------------------------------


def test_default_material_returns_material_instance():
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import default_material
    from slappyengine.render.material import Material

    mat = default_material()
    assert isinstance(mat, Material)


def test_default_material_is_opaque_and_light_gray():
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import default_material

    mat = default_material()
    assert mat.alpha_mode == "opaque"
    r, g, b, a = mat.base_color
    assert r == g == b  # neutral gray
    assert 0.5 <= r <= 1.0  # "light" (not dark)
    assert a == 1.0


# ---------------------------------------------------------------------------
# handle_transform_matrix
# ---------------------------------------------------------------------------


def test_handle_transform_matrix_identity(fresh_app):
    from slappyengine.app_integration import handle_transform_matrix

    h = ModelHandle(path="x.obj", id=0, _app=fresh_app)
    m = handle_transform_matrix(h)
    assert m.shape == (4, 4)
    assert np.allclose(m, np.eye(4, dtype=np.float32))


def test_handle_transform_matrix_translation(fresh_app):
    from slappyengine.app_integration import handle_transform_matrix

    h = ModelHandle(path="x.obj", id=0, _app=fresh_app, position=(3.0, 4.0, 5.0))
    m = handle_transform_matrix(h)
    assert m[0, 3] == pytest.approx(3.0)
    assert m[1, 3] == pytest.approx(4.0)
    assert m[2, 3] == pytest.approx(5.0)


def test_handle_transform_matrix_scale_applies_to_diagonal(fresh_app):
    from slappyengine.app_integration import handle_transform_matrix

    h = ModelHandle(path="x.obj", id=0, _app=fresh_app, scale=(2.0, 3.0, 4.0))
    m = handle_transform_matrix(h)
    assert m[0, 0] == pytest.approx(2.0)
    assert m[1, 1] == pytest.approx(3.0)
    assert m[2, 2] == pytest.approx(4.0)


def test_model_handle_transform_matrix_method(fresh_app):
    """ModelHandle.transform_matrix() delegates to the bridge helper."""
    h = ModelHandle(path="x.obj", id=0, _app=fresh_app, position=(1.0, 2.0, 3.0))
    m = h.transform_matrix()
    assert m is not None
    assert m.shape == (4, 4)


# ---------------------------------------------------------------------------
# bridge_load_model
# ---------------------------------------------------------------------------


def test_bridge_load_model_loads_triangle_obj(fresh_app):
    from slappyengine.app_integration import bridge_load_model

    handle = bridge_load_model(fresh_app, str(TRIANGLE_OBJ))
    assert isinstance(handle, ModelHandle)
    assert handle.mesh is not None
    # triangle.obj has 3 unique vertices in a single triangle
    assert handle.mesh.vertices.shape[0] > 0
    assert handle.mesh.vertices.shape[1] == 3


def test_bridge_load_model_appends_to_app_models(fresh_app):
    from slappyengine.app_integration import bridge_load_model

    n_before = len(fresh_app.models)
    handle = bridge_load_model(fresh_app, str(TRIANGLE_OBJ))
    assert handle in fresh_app.models
    assert len(fresh_app.models) == n_before + 1


def test_bridge_load_model_populates_bounding_box(fresh_app):
    from slappyengine.app_integration import bridge_load_model

    handle = bridge_load_model(fresh_app, str(TRIANGLE_OBJ))
    assert handle.bounding_box is not None
    (mn, mx) = handle.bounding_box
    # triangle.obj has v (0,0,0), (1,0,0), (0,1,0)
    assert mn == pytest.approx((0.0, 0.0, 0.0))
    assert mx == pytest.approx((1.0, 1.0, 0.0))


def test_bridge_load_model_sets_default_material(fresh_app):
    from slappyengine.app_integration import bridge_load_model
    from slappyengine.render.material import Material

    handle = bridge_load_model(fresh_app, str(TRIANGLE_OBJ))
    assert isinstance(handle.material, Material)


def test_bridge_load_model_records_trace_entry(fresh_app):
    from slappyengine.app_integration import bridge_load_model

    bridge_load_model(fresh_app, str(TRIANGLE_OBJ))
    kinds = {t[0] for t in fresh_app.trace}
    assert "bridge_load_model" in kinds


def test_bridge_load_model_falls_back_when_path_missing(fresh_app):
    """A missing path should not crash — falls back to the stub loader."""
    from slappyengine.app_integration import bridge_load_model

    handle = bridge_load_model(fresh_app, "no_such_file_1234.obj")
    # Falls back to the stub: no mesh attached, but the handle still exists.
    assert isinstance(handle, ModelHandle)
    assert handle.mesh is None


# ---------------------------------------------------------------------------
# bridge_submit_frame
# ---------------------------------------------------------------------------


def test_bridge_submit_frame_records_mesh_call(fresh_app):
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import bridge_load_model, bridge_submit_frame
    from slappyengine.render import NullRenderer

    bridge_load_model(fresh_app, str(TRIANGLE_OBJ))
    renderer = NullRenderer()
    renderer.begin_frame()
    bridge_submit_frame(fresh_app, renderer)
    renderer.end_frame()
    mesh_calls = renderer.calls_of("mesh")
    assert len(mesh_calls) == 1
    payload = mesh_calls[0].payload
    assert payload["vertex_count"] > 0


def test_bridge_submit_frame_records_camera_call(fresh_app):
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import bridge_submit_frame
    from slappyengine.render import NullRenderer

    fresh_app.spawn_camera(position=(0.0, 0.0, 5.0), look_at=(0.0, 0.0, 0.0))
    renderer = NullRenderer()
    renderer.begin_frame()
    bridge_submit_frame(fresh_app, renderer)
    renderer.end_frame()
    cam_calls = renderer.calls_of("camera")
    assert len(cam_calls) == 1


def test_bridge_submit_frame_records_lights_call(fresh_app):
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import bridge_submit_frame
    from slappyengine.render import NullRenderer

    fresh_app.spawn_light(position=(1.0, 2.0, 3.0), color=(1.0, 0.5, 0.25))
    renderer = NullRenderer()
    renderer.begin_frame()
    bridge_submit_frame(fresh_app, renderer)
    renderer.end_frame()
    light_calls = renderer.calls_of("lights")
    assert len(light_calls) == 1
    assert light_calls[0].payload["count"] == 1


def test_bridge_submit_frame_skips_invisible_models(fresh_app):
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import bridge_load_model, bridge_submit_frame
    from slappyengine.render import NullRenderer

    h = bridge_load_model(fresh_app, str(TRIANGLE_OBJ))
    h.set_visible(False)
    renderer = NullRenderer()
    renderer.begin_frame()
    bridge_submit_frame(fresh_app, renderer)
    renderer.end_frame()
    assert len(renderer.calls_of("mesh")) == 0


# ---------------------------------------------------------------------------
# promote_stub_renderer
# ---------------------------------------------------------------------------


def test_promote_stub_renderer_null_when_gpu_disabled():
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import promote_stub_renderer
    from slappyengine.render import NullRenderer

    app = App(AppConfig(enable_gpu=False))
    assert isinstance(app._renderer, _StubRenderer)
    promote_stub_renderer(app)
    assert isinstance(app._renderer, NullRenderer)
    app.close()


def test_promote_stub_renderer_real_when_gpu_available():
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    if not _wgpu_available():
        pytest.skip("wgpu not available in this environment")
    from slappyengine.app_integration import promote_stub_renderer
    from slappyengine.render import Renderer

    app = App(AppConfig(enable_gpu=True))
    assert isinstance(app._renderer, _StubRenderer)
    promote_stub_renderer(app)
    assert isinstance(app._renderer, Renderer)
    app.close()


def test_promote_stub_renderer_is_noop_on_second_call():
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import promote_stub_renderer

    app = App(AppConfig(enable_gpu=False))
    promote_stub_renderer(app)
    first = app._renderer
    promote_stub_renderer(app)
    assert app._renderer is first
    app.close()


def test_promote_stub_renderer_honours_stub_backend_config():
    """``renderer_backend="stub"`` should never promote to a real GPU."""
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import promote_stub_renderer
    from slappyengine.render import NullRenderer, Renderer

    app = App(AppConfig(enable_gpu=True, renderer_backend="stub"))
    promote_stub_renderer(app)
    # Should be a NullRenderer, not the wgpu-backed Renderer.
    assert isinstance(app._renderer, NullRenderer)
    assert not isinstance(app._renderer, Renderer) or app._renderer.__class__ is NullRenderer
    app.close()


# ---------------------------------------------------------------------------
# HH1's existing 2-line render pattern must still work
# ---------------------------------------------------------------------------


def test_two_line_render_pattern_still_works_after_integration():
    """The whole point of HH1 — 2 lines to render — must survive HH4 wiring."""
    app = slappyengine.launch(
        on_begin=lambda a: a.load_model("bunny.obj"),
        max_frames=3,
    )
    assert app.frame_count == 3
    assert len(app.models) == 1
    assert app.models[0].path.endswith("bunny.obj")
    app.close()


def test_stub_renderer_still_used_for_nonexistent_asset():
    """Missing files fall back to the HH1 stub loader (no crash on typo)."""
    app = App(AppConfig(enable_gpu=False, max_frames=1))
    handle = app.load_model("nonexistent_bunny.obj")
    # Stub loader path → no mesh attached.
    assert handle.mesh is None
    app.close()


# ---------------------------------------------------------------------------
# App.load_model now dispatches to HH5 when path exists
# ---------------------------------------------------------------------------


def test_app_load_model_uses_asset_importer_for_existing_obj():
    app = App(AppConfig(enable_gpu=False))
    handle = app.load_model(str(TRIANGLE_OBJ))
    # HH5 path — mesh attribute populated by the bridge.
    assert handle.mesh is not None
    assert handle.mesh.vertices.shape[0] > 0
    app.close()


def test_app_load_via_asset_importer_returns_none_for_stub_path():
    """The internal helper returns None for paths that don't exist."""
    app = App(AppConfig(enable_gpu=False))
    result = app._load_via_asset_importer("does_not_exist.obj")
    assert result is None
    app.close()


# ---------------------------------------------------------------------------
# App.render_frame
# ---------------------------------------------------------------------------


def test_render_frame_with_stub_renderer_increments_frame_count(fresh_app):
    before = fresh_app.frame_count
    fresh_app.render_frame()
    assert fresh_app.frame_count == before + 1


def test_render_frame_with_null_renderer_records_bridge_calls():
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import promote_stub_renderer

    app = App(AppConfig(enable_gpu=False))
    app.load_model(str(TRIANGLE_OBJ))  # HH5 path via load_model
    promote_stub_renderer(app)
    app.render_frame()
    assert len(app._renderer.calls_of("mesh")) >= 1
    assert len(app._renderer.calls_of("clear")) >= 1
    assert len(app._renderer.calls_of("present")) >= 1
    app.close()


# ---------------------------------------------------------------------------
# App.get_bounding_box_of_all_models
# ---------------------------------------------------------------------------


def test_bounding_box_returns_zeros_when_no_models(fresh_app):
    mn, mx = fresh_app.get_bounding_box_of_all_models()
    assert mn == (0.0, 0.0, 0.0)
    assert mx == (0.0, 0.0, 0.0)


def test_bounding_box_returns_finite_values_for_loaded_model():
    app = App(AppConfig(enable_gpu=False))
    app.load_model(str(TRIANGLE_OBJ))
    mn, mx = app.get_bounding_box_of_all_models()
    for v in (*mn, *mx):
        assert math.isfinite(v)
    # Triangle.obj sits in [0,1] x [0,1] x [0,0] at rest.
    assert mn[0] == pytest.approx(0.0)
    assert mx[0] == pytest.approx(1.0)
    app.close()


def test_bounding_box_respects_transform():
    """Translating a handle should shift the world-space bbox by the same amount."""
    app = App(AppConfig(enable_gpu=False))
    h = app.load_model(str(TRIANGLE_OBJ))
    h.move_to(10.0, 20.0, 30.0)
    mn, mx = app.get_bounding_box_of_all_models()
    assert mn[0] == pytest.approx(10.0)
    assert mn[1] == pytest.approx(20.0)
    assert mn[2] == pytest.approx(30.0)
    assert mx[0] == pytest.approx(11.0)
    assert mx[1] == pytest.approx(21.0)
    assert mx[2] == pytest.approx(30.0)
    app.close()


# ---------------------------------------------------------------------------
# End-to-end — launch(...) → real OBJ → NullRenderer submit
# ---------------------------------------------------------------------------


def test_end_to_end_launch_with_real_obj_and_null_renderer():
    """Exercises the full HH1 → HH4 → HH5 stack in one flow."""
    if not _has_render_subpackage():
        pytest.skip("slappyengine.render not importable")
    from slappyengine.app_integration import promote_stub_renderer

    triangle_path = str(TRIANGLE_OBJ)
    app = App(AppConfig(enable_gpu=False, max_frames=2))
    app.load_model(triangle_path)
    promote_stub_renderer(app)
    app.spawn_camera(position=(0.0, 0.0, 5.0))
    app.spawn_light(position=(0.0, 5.0, 0.0))

    app.run(max_frames=2)
    # 2 frames × 1 mesh submit each.
    assert len(app._renderer.calls_of("mesh")) == 2
    # camera + lights set each frame too.
    assert len(app._renderer.calls_of("camera")) == 2
    assert len(app._renderer.calls_of("lights")) == 2
    app.close()
