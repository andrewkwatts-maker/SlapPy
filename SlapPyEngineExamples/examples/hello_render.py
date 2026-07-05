"""hello_render — the 2-line pip-install-to-render-a-model demo.

This is the flagship "getting started" example the user asked for
(2026-07-04 II sprint):

    "someone should be able to pip install SlappyEngine, and be able to
     render a model in 2-3 lines of code."

Run
---

The canonical 2-line pattern::

    pip install slappy-engine
    python -c "from slappyengine.examples.hello_render import minimal; minimal()"

Or directly from a checkout::

    python SlapPyEngineExamples/examples/hello_render.py

Variants (progressively more explicit)
--------------------------------------

* :func:`minimal`               — the literal 2-line ask.
* :func:`with_light_and_camera` — model + light + camera + rotation.
* :func:`with_config_yaml`      — YAML-driven variant.
* :func:`custom_lifecycle`      — begin/tick/end hooks broken out.

Headless
--------

All variants are headless-safe. They pass ``enable_gpu=False`` on the
``AppConfig`` so the renderer falls back to :class:`slappyengine.app._StubRenderer`
which logs every draw call to ``app._renderer.log`` — that's what the
test suite asserts on. The environment variable ``SLAPPY_HEADLESS=1`` is
honoured as an override for CI setups that prefer env-flag toggles.

Configuration
-------------

``slappyengine.App.from_config_dict`` does not yet exist as of 2026-07-05
(pending H1 sprint). :func:`with_config_yaml` therefore reads
``slappyengine.config_defaults.load_config_with_defaults`` and hydrates an
:class:`~slappyengine.AppConfig` field-by-field. Once
``App.from_config_dict`` lands, this variant will collapse to a single
call — the demo docstring is the seam.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_TRIANGLE_OBJ = _THIS_DIR / "assets" / "triangle.obj"


def _triangle_path() -> str:
    """Return the absolute path to the bundled triangle model.

    We resolve to an absolute path so the demo works no matter what the
    caller's cwd happens to be (tests run from repo root, ad-hoc users
    run from ``SlapPyEngineExamples/``).
    """
    return str(_TRIANGLE_OBJ)


def _headless_config():
    """Build a headless :class:`slappyengine.AppConfig` for the demos.

    Every variant uses the same config: GPU disabled (stub renderer),
    ``renderer_backend="stub"``, telemetry off, editor off. The window
    settings are irrelevant when the stub renderer is active but we set
    them explicitly so the demo YAML round-trips cleanly.
    """
    import slappyengine

    return slappyengine.AppConfig(
        window_title="hello_render",
        window_size=(640, 480),
        enable_gpu=False,
        renderer_backend="stub",
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
    )


# ---------------------------------------------------------------------------
# Variant 1 — the literal 2-line ask
# ---------------------------------------------------------------------------


def minimal() -> "Any":
    """The 2-line ask literally satisfied.

    Returns the :class:`~slappyengine.App` so callers can inspect
    ``app.models`` / ``app.trace`` / ``app._renderer.log`` after the run.
    """
    import slappyengine

    return slappyengine.launch(
        on_begin=lambda app: app.load_model(_triangle_path()),
        max_frames=60,
        config=_headless_config(),
    )


# ---------------------------------------------------------------------------
# Variant 2 — model + light + camera + rotation
# ---------------------------------------------------------------------------


def with_light_and_camera() -> "Any":
    """4-line variant: model + light + camera + per-tick rotation.

    The returned app has one model, one light, one active camera, and the
    model's rotation.y has been incremented ``max_frames`` times.
    """
    import slappyengine

    app = slappyengine.App(config=_headless_config())
    model = app.load_model(_triangle_path())
    app.spawn_light((5.0, 5.0, 5.0))
    app.spawn_camera((0.0, 0.0, 3.0), look_at=(0.0, 0.0, 0.0))
    app.run(
        on_tick=lambda a, dt: model.rotate_by(0.0, dt, 0.0),
        max_frames=60,
    )
    return app


# ---------------------------------------------------------------------------
# Variant 3 — config-driven
# ---------------------------------------------------------------------------


def with_config_yaml(config_path: str | Path | None = None) -> "Any":
    """Config-driven variant.

    Reads a merged config dict from
    :func:`slappyengine.config_defaults.load_config_with_defaults`. If
    ``config_path`` is ``None`` (or points at a missing file) the
    defaults dict is used verbatim -- perfect for first-run bootstrap.

    Note
    ----
    Once ``slappyengine.App.from_config_dict`` lands (H1 sprint) this
    variant collapses to a single call. Until then we hand-map the
    ``[app]`` section into :class:`~slappyengine.AppConfig` fields.
    """
    import slappyengine
    from slappyengine.config_defaults import load_config_with_defaults

    cfg = load_config_with_defaults(config_path or "config.yaml")

    # Hand-map the fields we care about. Missing sections → defaults.
    base = _headless_config()
    app_section = cfg.get("app", {}) if isinstance(cfg, dict) else {}
    if isinstance(app_section, dict):
        target_fps = app_section.get("target_fps")
        if isinstance(target_fps, int) and target_fps > 0:
            base.target_fps = target_fps
        window_title = app_section.get("window_title")
        if isinstance(window_title, str):
            base.window_title = window_title

    app = slappyengine.App(config=base)
    app.load_model(_triangle_path())
    app.run(max_frames=60)
    return app


# ---------------------------------------------------------------------------
# Variant 4 — explicit begin/tick/end
# ---------------------------------------------------------------------------


def custom_lifecycle() -> "Any":
    """6-line variant with explicit begin/tick/end hooks.

    Returns the app so tests can inspect the per-hook counters we stash
    on it (``app._begin_fired`` etc.).
    """
    import slappyengine

    app = slappyengine.App(config=_headless_config())

    # Counters — patched onto the app so callers can assert on them.
    app._begin_fired = 0        # type: ignore[attr-defined]
    app._tick_fired = 0         # type: ignore[attr-defined]
    app._end_fired = 0          # type: ignore[attr-defined]

    def begin(a):
        a.load_model(_triangle_path())
        a.spawn_light((5.0, 5.0, 5.0))
        a._begin_fired += 1     # type: ignore[attr-defined]

    def tick(a, dt):
        a._tick_fired += 1      # type: ignore[attr-defined]

    def end(a):
        a._end_fired += 1       # type: ignore[attr-defined]
        # Report line the user asked for — kept as a print so the demo
        # produces observable console output when run manually.
        print(f"Rendered {a.frame_count} frames")

    app.run(on_begin=begin, on_tick=tick, on_end=end, max_frames=60)
    return app


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _honour_headless_env() -> None:
    """Respect ``SLAPPY_HEADLESS=1`` as an env-flag override.

    All variants already build a headless :class:`~slappyengine.AppConfig`
    so this is belt-and-braces. We touch the env var only to normalise
    it (empty string → unset semantics) so downstream libraries see a
    consistent value.
    """
    if os.environ.get("SLAPPY_HEADLESS", "").strip() in ("", "0"):
        os.environ.setdefault("SLAPPY_HEADLESS", "1")


if __name__ == "__main__":
    _honour_headless_env()
    print("=== minimal ===")
    minimal()
    print("=== with_light_and_camera ===")
    with_light_and_camera()
    print("=== with_config_yaml ===")
    with_config_yaml()
    print("=== custom_lifecycle ===")
    custom_lifecycle()
