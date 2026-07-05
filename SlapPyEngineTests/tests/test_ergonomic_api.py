"""Tripwire suite for the HH1 ergonomic top-level API.

Covers :mod:`slappyengine.app`:

* Two-line ``slappyengine.launch(...)`` render pattern.
* :class:`slappyengine.App` lifecycle (``begin`` / ``tick`` / ``end``).
* :class:`ModelHandle` mutation + trace log.
* Multi-extension model loader dispatch (``.obj`` / ``.gltf`` / ``.glb`` /
  ``.fbx``).
* :class:`AppConfig` YAML round-trip + missing-file first-run scaffold.
* Headless fallback fires all hooks (``enable_gpu=False``).
* :meth:`App.close` idempotency + post-close guard.
* Module-level ``slappyengine.load_model`` implicit global.

See ``python/slappyengine/app.py`` for the surface under test.
"""
from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest

import slappyengine
from slappyengine.app import (
    App,
    AppConfig,
    CameraHandle,
    LightHandle,
    ModelHandle,
    TextureHandle,
    launch,
    load_model,
    load_texture,
    register_model_loader,
)


# ---------------------------------------------------------------------------
# Top-level exports
# ---------------------------------------------------------------------------


def test_top_level_exports_present():
    for name in (
        "App",
        "AppConfig",
        "ModelHandle",
        "TextureHandle",
        "CameraHandle",
        "LightHandle",
        "launch",
        "load_model",
        "load_texture",
    ):
        assert hasattr(slappyengine, name), f"missing top-level export: {name}"


def test_top_level_exports_in_all():
    for name in (
        "App",
        "AppConfig",
        "launch",
        "load_model",
        "load_texture",
    ):
        assert name in slappyengine.__all__


# ---------------------------------------------------------------------------
# 2-line render pattern
# ---------------------------------------------------------------------------


def test_two_line_render_pattern():
    """The whole point of the HH1 sprint — 2 lines to render."""
    app = slappyengine.launch(
        on_begin=lambda a: a.load_model("bunny.obj"),
        max_frames=60,
    )
    assert app.frame_count == 60
    assert len(app.models) == 1
    assert app.models[0].path.endswith("bunny.obj")
    app.close()


def test_launch_returns_app():
    app = launch(max_frames=1)
    assert isinstance(app, App)
    app.close()


def test_launch_fires_all_three_lifecycle_hooks():
    calls = []
    app = launch(
        on_begin=lambda a: calls.append("begin"),
        on_tick=lambda a, dt: calls.append(("tick", dt)),
        on_end=lambda a: calls.append("end"),
        max_frames=3,
    )
    assert calls[0] == "begin"
    assert calls[-1] == "end"
    tick_calls = [c for c in calls if isinstance(c, tuple) and c[0] == "tick"]
    assert len(tick_calls) == 3
    app.close()


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


def test_app_default_construction():
    app = App()
    assert isinstance(app.config, AppConfig)
    assert app.frame_count == 0
    assert app.elapsed == 0.0
    assert app.is_running is False
    assert app.is_closed is False
    app.close()


def test_app_with_explicit_config():
    cfg = AppConfig(window_title="unit-test", target_fps=30, max_frames=5)
    app = App(cfg)
    app.run()
    assert app.frame_count == 5
    app.close()


def test_app_run_lifecycle_order():
    app = App(AppConfig(max_frames=2))
    order: list[str] = []
    app.run(
        on_begin=lambda a: order.append("begin"),
        on_tick=lambda a, dt: order.append(f"tick:{dt:.4f}"),
        on_end=lambda a: order.append("end"),
    )
    assert order[0] == "begin"
    assert order[-1] == "end"
    assert order.count("begin") == 1
    assert order.count("end") == 1
    app.close()


def test_app_stop_breaks_loop_early():
    app = App(AppConfig(max_frames=1000))

    def kill(a, dt):
        if a.frame_count >= 3:
            a.stop()

    app.run(on_tick=kill)
    assert app.frame_count in (3, 4)  # exact count depends on top-vs-bottom check
    app.close()


# ---------------------------------------------------------------------------
# ModelHandle
# ---------------------------------------------------------------------------


def test_load_model_returns_handle_with_id():
    app = App()
    handle = app.load_model("bunny.obj")
    assert isinstance(handle, ModelHandle)
    assert handle.id >= 0
    assert handle.path.endswith("bunny.obj")
    assert handle.visible is True
    assert handle.position == (0.0, 0.0, 0.0)
    app.close()


def test_model_handle_move_to():
    app = App()
    h = app.load_model("a.obj")
    h.move_to(1.0, 2.0, 3.0)
    assert h.position == (1.0, 2.0, 3.0)
    app.close()


def test_model_handle_move_by():
    app = App()
    h = app.load_model("a.obj")
    h.move_to(1.0, 1.0, 1.0)
    h.move_by(0.5, -0.5, 2.0)
    assert h.position == (1.5, 0.5, 3.0)
    app.close()


def test_model_handle_rotate_by_and_rotate_to():
    app = App()
    h = app.load_model("a.obj")
    h.rotate_by(0.1, 0.2, 0.3)
    assert h.rotation == pytest.approx((0.1, 0.2, 0.3))
    h.rotate_to(1.0, 2.0, 3.0)
    assert h.rotation == (1.0, 2.0, 3.0)
    app.close()


def test_model_handle_scale():
    app = App()
    h = app.load_model("a.obj")
    h.scale_to(2.0, 2.0, 2.0)
    assert h.scale == (2.0, 2.0, 2.0)
    app.close()


def test_model_handle_visibility():
    app = App()
    h = app.load_model("a.obj")
    assert h.visible is True
    h.set_visible(False)
    assert h.visible is False
    app.close()


def test_model_handle_destroy_removes_from_app():
    app = App()
    h = app.load_model("a.obj")
    assert h in app.models
    h.destroy()
    assert h not in app.models
    # Idempotent
    h.destroy()
    app.close()


def test_multiple_models_coexist():
    app = App()
    handles = [app.load_model(f"model_{i}.obj") for i in range(5)]
    assert len(app.models) == 5
    ids = {h.id for h in handles}
    assert len(ids) == 5
    app.close()


def test_trace_log_records_mutations():
    app = App()
    h = app.load_model("a.obj")
    h.move_to(1, 2, 3)
    h.rotate_by(0.1, 0.0, 0.0)
    ops = [e for e in app.trace if e[0] == "model" and e[1] == h.id]
    assert any(op[2] == "move_to" for op in ops)
    assert any(op[2] == "rotate_by" for op in ops)
    app.close()


# ---------------------------------------------------------------------------
# Loader dispatch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("ext", [".obj", ".gltf", ".glb", ".fbx", ".ply", ".stl"])
def test_load_model_extensions_all_return_handle(ext):
    app = App()
    h = app.load_model(f"foo{ext}")
    assert isinstance(h, ModelHandle)
    assert h.path.endswith(ext)
    app.close()


def test_load_model_unknown_extension_still_returns_handle():
    app = App()
    h = app.load_model("weird.xyz")
    assert isinstance(h, ModelHandle)
    app.close()


def test_register_model_loader_hook_fires():
    calls = []

    def loader(path: str):
        calls.append(path)
        return {"position": (9.0, 9.0, 9.0)}

    register_model_loader(".hh1", loader)
    app = App()
    h = app.load_model("custom.hh1")
    assert calls == ["custom.hh1"]
    assert h.position == (9.0, 9.0, 9.0)
    app.close()


# ---------------------------------------------------------------------------
# Textures / lights / cameras
# ---------------------------------------------------------------------------


def test_load_texture_returns_handle():
    app = App()
    t = app.load_texture("stone.png")
    assert isinstance(t, TextureHandle)
    assert t.id >= 0
    app.close()


def test_spawn_light_and_camera():
    app = App()
    light = app.spawn_light(position=(5, 5, 5), color=(1, 0, 0), intensity=2.0)
    cam = app.spawn_camera(position=(0, 0, 10), look_at=(0, 0, 0))
    assert isinstance(light, LightHandle)
    assert isinstance(cam, CameraHandle)
    assert light.position == (5, 5, 5)
    assert light.color == (1, 0, 0)
    assert light.intensity == 2.0
    assert cam.position == (0, 0, 10)
    assert app.active_camera is cam
    app.close()


def test_camera_and_light_mutation():
    app = App()
    light = app.spawn_light()
    cam = app.spawn_camera()
    light.move_to(1, 2, 3).set_color(0, 1, 0).set_intensity(5)
    cam.move_to(10, 10, 10).aim_at(0, 0, 0)
    assert light.position == (1, 2, 3)
    assert light.color == (0, 1, 0)
    assert light.intensity == 5
    assert cam.position == (10, 10, 10)
    assert cam.look_at == (0, 0, 0)
    app.close()


# ---------------------------------------------------------------------------
# AppConfig — YAML round-trip
# ---------------------------------------------------------------------------


def test_appconfig_defaults_construct():
    cfg = AppConfig()
    assert cfg.window_title == "SlapPyEngine"
    assert cfg.window_size == (1280, 720)
    assert cfg.target_fps == 60
    assert cfg.enable_editor is False


def test_appconfig_has_every_documented_option():
    """The user spec requires *every* config option documented with a
    default. Check the field count matches the documented surface."""
    names = {f.name for f in fields(AppConfig)}
    required = {
        "window_title",
        "window_size",
        "fullscreen",
        "vsync",
        "target_fps",
        "clear_color",
        "msaa_samples",
        "enable_gpu",
        "enable_editor",
        "project_root",
    }
    missing = required - names
    assert not missing, f"AppConfig missing required fields: {missing}"


def test_appconfig_to_yaml_and_back():
    cfg = AppConfig(window_title="test", target_fps=120, enable_editor=True)
    yaml_str = cfg.to_yaml()
    assert "window_title: test" in yaml_str
    assert "target_fps: 120" in yaml_str
    round = AppConfig.from_yaml(yaml_str)
    assert round.window_title == "test"
    assert round.target_fps == 120
    assert round.enable_editor is True


def test_appconfig_yaml_tuple_fields_survive_round_trip():
    cfg = AppConfig(window_size=(1920, 1080), clear_color=(0.5, 0.5, 0.5, 1.0))
    round = AppConfig.from_yaml(cfg.to_yaml())
    assert round.window_size == (1920, 1080)
    assert round.clear_color == (0.5, 0.5, 0.5, 1.0)


def test_appconfig_from_yaml_file(tmp_path):
    cfg = AppConfig(window_title="from-file")
    p = tmp_path / "app.yml"
    p.write_text(cfg.to_yaml(), encoding="utf-8")
    round = AppConfig.from_yaml_file(p)
    assert round.window_title == "from-file"


def test_appconfig_from_yaml_ignores_unknown_keys():
    cfg = AppConfig.from_yaml("window_title: hello\nnope: 42\n")
    assert cfg.window_title == "hello"


def test_missing_config_file_writes_default_yaml(tmp_path):
    p = tmp_path / "default.yml"
    assert not p.exists()
    app = App(config_path=p)
    assert p.exists()
    body = p.read_text(encoding="utf-8")
    # Every field appears (commented) in the scaffold.
    assert "# window_title:" in body
    assert "# target_fps:" in body
    assert "# enable_gpu:" in body
    # App still booted with defaults.
    assert app.config.window_title == "SlapPyEngine"
    app.close()


def test_existing_config_file_is_loaded(tmp_path):
    p = tmp_path / "app.yml"
    p.write_text("window_title: real-value\ntarget_fps: 30\n", encoding="utf-8")
    app = App(config_path=p)
    assert app.config.window_title == "real-value"
    assert app.config.target_fps == 30
    app.close()


# ---------------------------------------------------------------------------
# Headless fallback
# ---------------------------------------------------------------------------


def test_enable_gpu_false_forces_headless():
    app = App(AppConfig(enable_gpu=False))
    assert app.is_headless is True
    app.close()


def test_headless_mode_still_fires_all_hooks():
    events: list[str] = []
    cfg = AppConfig(enable_gpu=False, max_frames=5)
    app = App(cfg)

    app.add_before_tick(lambda a, dt: events.append("before"))
    app.add_after_tick(lambda a, dt: events.append("after"))
    app.add_before_frame_render(lambda a: events.append("render"))

    app.run(
        on_begin=lambda a: events.append("begin"),
        on_tick=lambda a, dt: events.append("tick"),
        on_end=lambda a: events.append("end"),
    )
    assert events.count("begin") == 1
    assert events.count("end") == 1
    assert events.count("tick") == 5
    assert events.count("before") == 5
    assert events.count("after") == 5
    assert events.count("render") == 5
    app.close()


def test_stub_renderer_records_draw_calls():
    app = App(AppConfig(enable_gpu=False, max_frames=2))
    app.load_model("bunny.obj")
    app.load_model("cube.obj")
    app.run()
    log = app._renderer.log  # noqa: SLF001
    draw_events = [e for e in log if e[0] == "draw_model"]
    # 2 models * 2 frames = 4 draw calls
    assert len(draw_events) == 4
    app.close()


def test_invisible_models_are_skipped_by_renderer():
    app = App(AppConfig(enable_gpu=False, max_frames=1))
    a = app.load_model("a.obj")
    b = app.load_model("b.obj")
    b.set_visible(False)
    app.run()
    log = app._renderer.log  # noqa: SLF001
    drawn_ids = [e[1]["id"] for e in log if e[0] == "draw_model"]
    assert a.id in drawn_ids
    assert b.id not in drawn_ids
    app.close()


# ---------------------------------------------------------------------------
# Close semantics
# ---------------------------------------------------------------------------


def test_app_close_idempotent():
    app = App()
    app.close()
    assert app.is_closed
    app.close()  # no-op
    assert app.is_closed


def test_run_after_close_raises():
    app = App()
    app.close()
    with pytest.raises(RuntimeError):
        app.run(max_frames=1)


def test_close_calls_renderer_close():
    app = App(AppConfig(enable_gpu=False))
    app.close()
    assert ("close", None) in app._renderer.log  # noqa: SLF001


# ---------------------------------------------------------------------------
# Module-level implicit-global-app helpers
# ---------------------------------------------------------------------------


def test_module_level_load_model_creates_implicit_app():
    App._clear_implicit()
    h = load_model("implicit.obj")
    assert isinstance(h, ModelHandle)
    assert App._implicit is not None
    App._implicit.close()
    App._clear_implicit()


def test_module_level_load_texture_shares_implicit_app():
    App._clear_implicit()
    m = load_model("a.obj")
    t = load_texture("b.png")
    assert m._app is t._app  # noqa: SLF001
    App._implicit.close()
    App._clear_implicit()


# ---------------------------------------------------------------------------
# Hook registration
# ---------------------------------------------------------------------------


def test_hooks_lists_start_empty():
    app = App()
    assert app._before_tick == []  # noqa: SLF001
    assert app._after_tick == []  # noqa: SLF001
    assert app._before_frame_render == []  # noqa: SLF001
    app.close()


def test_hooks_fire_in_registration_order():
    app = App(AppConfig(enable_gpu=False, max_frames=1))
    order: list[str] = []
    app.add_before_tick(lambda a, dt: order.append("bt1"))
    app.add_before_tick(lambda a, dt: order.append("bt2"))
    app.add_after_tick(lambda a, dt: order.append("at1"))
    app.run(on_tick=lambda a, dt: order.append("tick"))
    assert order == ["bt1", "bt2", "tick", "at1"]
    app.close()
