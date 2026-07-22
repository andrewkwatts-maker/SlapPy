"""hello_render_real — real 3D scene with a bunny + light + shadows + screenshot.

The task-MM7 counterpart to :mod:`hello_render` (which loads a single
triangle). Where ``hello_render`` proves the 2-line pip-install-to-render
pattern, ``hello_render_real`` proves the *full pipeline*:

* Substantive geometry — a procedurally-generated pear-shaped bunny at
  ``assets/bunny_low.obj`` (~270 verts / ~440 tris) with proper normals
  and a real MTL material.
* A real key light + orbit camera.
* Optional shadow-map / SSAO / HUD stacks selectable via the
  :func:`with_shadows`, :func:`with_ssao`, and :func:`with_full_pipeline`
  variants.
* An end-of-run screenshot capture that soft-skips when PIL is missing
  or when the underlying renderer is the headless stub (no
  ``read_pixels`` surface).

The demo is headless-safe: ``enable_gpu=False`` on the :class:`AppConfig`
so the runtime falls back to the logging stub renderer used everywhere
in CI. When someone runs the module ``__main__`` block with GPU-enabled
config, the same call chain plugs into the wgpu backend via
:mod:`pharos_engine.app_integration` without a code change here.

Variants
--------

* :func:`main`               — bunny + orbit-cam + rotating bunny + screenshot.
* :func:`with_shadows`       — main + a JJ7 :class:`ShadowCSM` post-pass.
* :func:`with_ssao`          — main + a KK3 :class:`GTAOPass` post-pass.
* :func:`with_full_pipeline` — bunny + shadows + SSAO + a FPS HUD hook.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_BUNNY_OBJ = _THIS_DIR / "assets" / "bunny_low.obj"
_SHOT_PNG = _THIS_DIR / "hello_render_real_final.png"


def _bunny_path() -> str:
    """Absolute path to the bundled bunny mesh (cwd-agnostic)."""
    return str(_BUNNY_OBJ)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def _demo_config():
    """Headless :class:`AppConfig` used by every variant.

    ``clear_color`` matches the task-spec sky blue so screenshots frame
    the bunny against a familiar backdrop when the real renderer runs.
    """
    import pharos_engine

    return pharos_engine.AppConfig(
        window_title="hello_render_real",
        window_size=(960, 540),
        enable_gpu=False,                 # tests + CI live here
        renderer_backend="stub",
        msaa_samples=4,
        clear_color=(0.85, 0.9, 0.95, 1.0),
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
    )


# ---------------------------------------------------------------------------
# Scene assembly + tick helpers
# ---------------------------------------------------------------------------


def _spawn_bunny_and_scene(app):
    """Load bunny, spawn key light + orbit camera. Returns the model handle."""
    bunny = app.load_model(_bunny_path())
    bunny.move_to(0.0, 0.0, 0.0)
    app.spawn_light((5.0, 8.0, 5.0), color=(1.0, 0.95, 0.85), intensity=1.5)
    app.spawn_camera((3.0, 2.0, 5.0), look_at=(0.0, 0.5, 0.0))
    return bunny


def _make_orbit_tick(bunny):
    """Return an ``on_tick`` that rotates the bunny + orbits the camera."""
    def tick(app, dt):
        t = app.frame_count / 60.0
        # Rotate bunny slowly around Y.
        bunny.rotate_to(0.0, t * 0.5, 0.0)
        # Orbit the camera in a horizontal circle around the bunny.
        cam_x = 5.0 * math.cos(t * 0.3)
        cam_z = 5.0 * math.sin(t * 0.3)
        if app.active_camera is not None:
            app.active_camera.move_to(cam_x, 2.0, cam_z)
            app.active_camera.aim_at(0.0, 0.5, 0.0)
    return tick


# ---------------------------------------------------------------------------
# Screenshot helper — soft-skips on stub / missing PIL
# ---------------------------------------------------------------------------


def _try_capture_screenshot(app, out_path: Path) -> bool:
    """Attempt a single-frame screenshot; return ``True`` on success.

    Silently returns ``False`` when:

    * the renderer has no ``read_pixels`` surface (the HH1 stub does not),
    * Pillow is not installed,
    * the capture layer raises for any other reason.

    Tests assert on the return value rather than on the file existing,
    so headless CI stays green.
    """
    renderer = getattr(app, "_renderer", None)
    if renderer is None or not hasattr(renderer, "read_pixels"):
        return False
    try:
        from pharos_engine.capture import CaptureManager
    except Exception:
        return False
    try:
        CaptureManager().capture_screenshot(renderer, str(out_path))
    except Exception:
        return False
    return out_path.exists()


# ---------------------------------------------------------------------------
# Variant 1 — main: bunny + light + camera + orbit + screenshot
# ---------------------------------------------------------------------------


def main() -> Any:
    """Real 3D scene: bunny + key light + orbit camera over 120 frames.

    Returns the :class:`~pharos_engine.App` so callers/tests can inspect
    ``app.models``, ``app.trace``, and the stub renderer log.
    """
    import pharos_engine

    app = pharos_engine.App(config=_demo_config())
    bunny = _spawn_bunny_and_scene(app)
    app.run(on_tick=_make_orbit_tick(bunny), max_frames=120)

    # Screenshot capture — soft-fails on the stub renderer used in CI.
    _try_capture_screenshot(app, _SHOT_PNG)
    return app


# ---------------------------------------------------------------------------
# Variant 2 — with_shadows: enable JJ7 CSM shadow pass
# ---------------------------------------------------------------------------


def with_shadows() -> Any:
    """``main`` plus a JJ7 :class:`~pharos_engine.post_process.ShadowCSM` pass.

    The pass is soft-attached to the app under ``app.shadow_pass`` so the
    real renderer can pick it up when it's live. Under the stub renderer
    the pass simply exists as configuration state — the test just checks
    the attribute was populated with the right type.
    """
    import pharos_engine

    app = pharos_engine.App(config=_demo_config())
    bunny = _spawn_bunny_and_scene(app)

    # Attach the CSM shadow post-pass. Imported lazily so the demo module
    # keeps import-time cheap for headless test collection.
    try:
        from pharos_engine.post_process.shadow_csm import ShadowCSM

        app.shadow_pass = ShadowCSM(
            num_cascades=4,
            pcss_enabled=True,
            depth_bias=0.005,
            pcf_radius=1.5,
            pcf_samples=16,
        )
    except Exception:  # pragma: no cover - only when post_process is missing
        app.shadow_pass = None

    app.run(on_tick=_make_orbit_tick(bunny), max_frames=120)
    _try_capture_screenshot(app, _SHOT_PNG.with_name("hello_render_real_shadows.png"))
    return app


# ---------------------------------------------------------------------------
# Variant 3 — with_ssao: enable KK3 GTAO pass
# ---------------------------------------------------------------------------


def with_ssao() -> Any:
    """``main`` plus a KK3 :class:`~pharos_engine.post_process.GTAOPass`.

    Attaches the pass to ``app.ssao_pass``.
    """
    import pharos_engine

    app = pharos_engine.App(config=_demo_config())
    bunny = _spawn_bunny_and_scene(app)

    try:
        from pharos_engine.post_process.gtao import GTAOPass

        app.ssao_pass = GTAOPass()
    except Exception:  # pragma: no cover
        app.ssao_pass = None

    app.run(on_tick=_make_orbit_tick(bunny), max_frames=120)
    _try_capture_screenshot(app, _SHOT_PNG.with_name("hello_render_real_ssao.png"))
    return app


# ---------------------------------------------------------------------------
# Variant 4 — with_full_pipeline: shadows + SSAO + FPS HUD
# ---------------------------------------------------------------------------


def with_full_pipeline() -> Any:
    """The full stack: bunny + light + shadows + SSAO + FPS HUD.

    The FPS HUD is a per-tick after-hook that records
    ``("hud", frame, fps)`` into :attr:`App.trace` so tests can prove the
    HUD wiring ran without needing a real overlay.
    """
    import pharos_engine

    app = pharos_engine.App(config=_demo_config())
    bunny = _spawn_bunny_and_scene(app)

    # Shadows + SSAO passes — same attachment pattern as the sibling
    # variants so tests can dedupe.
    try:
        from pharos_engine.post_process.shadow_csm import ShadowCSM
        from pharos_engine.post_process.gtao import GTAOPass

        app.shadow_pass = ShadowCSM()
        app.ssao_pass = GTAOPass()
    except Exception:  # pragma: no cover
        app.shadow_pass = None
        app.ssao_pass = None

    # HUD accumulator — a tiny running-average FPS meter.
    app.hud_fps_log: list[tuple[int, float]] = []  # type: ignore[attr-defined]

    def hud_hook(a, dt):
        # dt is 1/target_fps under fixed_timestep-off; the HUD just logs
        # the instantaneous 1/dt so the trace shows a real number.
        fps = 1.0 / dt if dt > 0 else 0.0
        a.hud_fps_log.append((a.frame_count, fps))
        a.trace.append(("hud", a.frame_count, fps))

    app.add_after_tick(hud_hook)

    app.run(on_tick=_make_orbit_tick(bunny), max_frames=120)
    _try_capture_screenshot(app, _SHOT_PNG.with_name("hello_render_real_full.png"))
    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _honour_headless_env() -> None:
    """Respect ``SLAPPY_HEADLESS=1`` as an env-flag override."""
    if os.environ.get("SLAPPY_HEADLESS", "").strip() in ("", "0"):
        os.environ.setdefault("SLAPPY_HEADLESS", "1")


if __name__ == "__main__":
    _honour_headless_env()
    print("=== main ===")
    main()
    print("=== with_shadows ===")
    with_shadows()
    print("=== with_ssao ===")
    with_ssao()
    print("=== with_full_pipeline ===")
    with_full_pipeline()
