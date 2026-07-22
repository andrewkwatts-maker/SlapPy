"""Regression test for ``Engine.run(max_frames=N)`` — the CI smoke path.

Sprint E's examples audit (``docs/examples_smoke_2026_05_31.md``) flagged 11
``engine.run()`` event-loop demos as untestable end-to-end because
``Engine.run`` took no max-frames kwarg.  The fix is to make ``run(max_frames=N)``
drive the per-frame draw callback exactly ``N`` times in-process and return,
without entering the platform event loop.

This test exercises that contract with a stub GPU/canvas stack:

* ``WgpuCanvas`` is replaced with a no-op stub so no real OS window is opened.
* ``Engine._setup_gpu`` is replaced with a stub that installs the minimal
  attribute surface ``_draw`` reads (``_gpu``, ``_renderer``, ``_input``,
  ``_lighting``, ``_compositor``, ``_post_executor``).

The test then asserts ``engine._frame_index == 3`` after ``run(max_frames=3)``
and that the whole call returns in under a second.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest


def _install_stubs(monkeypatch):
    """Patch out WgpuCanvas + Engine._setup_gpu so run(max_frames=N) is GPU-free."""
    from pharos_engine import engine as engine_mod

    # --- Fake canvas ----------------------------------------------------------
    class _StubCanvas:
        def __init__(self, *_, **__):
            pass

        def request_draw(self, fn=None):
            # Accept both the decorator-style call (``@canvas.request_draw``)
            # and the function-style call (``canvas.request_draw(_draw)``).
            return fn

        def add_event_handler(self, *_, **__):
            return lambda fn: fn

    monkeypatch.setattr(engine_mod, "WgpuCanvas", _StubCanvas)

    # --- Fake event-loop entry point — should NOT be called when max_frames is set
    def _fake_run():  # pragma: no cover — guarded by the assertion below
        raise AssertionError(
            "run() event-loop entry was invoked but max_frames was given"
        )

    monkeypatch.setattr(engine_mod, "run", _fake_run)

    # --- Fake GPU stack -------------------------------------------------------
    class _StubEncoder:
        def begin_render_pass(self, **__):
            return SimpleNamespace(end=lambda: None,
                                   set_viewport=lambda *a, **k: None,
                                   set_scissor_rect=lambda *a, **k: None)

        def copy_texture_to_texture(self, *_, **__):
            pass

    class _StubTexture:
        def create_view(self, *_, **__):
            return None

        def destroy(self):
            pass

    class _StubGPU:
        surface_format = "rgba8unorm"

        def get_current_texture(self):
            return _StubTexture()

        def create_encoder(self, *_):
            return _StubEncoder()

        def submit(self, *_):
            pass

    class _StubRenderer:
        def update_camera(self, *_):
            pass

        def render(self, *_):
            pass

    class _StubInput:
        def frame_reset(self):
            pass

    def _stub_setup_gpu(self, canvas):
        self._gpu = _StubGPU()
        self._renderer = _StubRenderer()
        self._input = _StubInput()
        # Lighting / compositor / post_executor stay None — _draw's checks
        # short-circuit on None for each one.

    monkeypatch.setattr(engine_mod.Engine, "_setup_gpu", _stub_setup_gpu)


def test_run_max_frames_returns_after_n_ticks(monkeypatch):
    """run(max_frames=3) ticks _draw three times then returns."""
    _install_stubs(monkeypatch)

    import pharos_engine as se

    engine = se.Engine()
    assert engine._frame_index == 0

    t0 = time.perf_counter()
    engine.run(max_frames=3)
    elapsed = time.perf_counter() - t0

    assert engine._frame_index == 3, (
        f"expected 3 ticks, got {engine._frame_index}"
    )
    assert elapsed < 1.0, (
        f"run(max_frames=3) took {elapsed:.3f}s — should be well under 1s"
    )


def test_run_max_frames_zero_is_noop(monkeypatch):
    """run(max_frames=0) returns immediately without ticking _draw."""
    _install_stubs(monkeypatch)

    import pharos_engine as se

    engine = se.Engine()
    engine.run(max_frames=0)
    assert engine._frame_index == 0


def test_run_max_frames_negative_raises(monkeypatch):
    """run(max_frames=-1) is a programming error and rejected."""
    _install_stubs(monkeypatch)

    import pharos_engine as se

    engine = se.Engine()
    with pytest.raises(ValueError):
        engine.run(max_frames=-1)


# ---------------------------------------------------------------------------
# Frame-pacing + shutdown coverage (2026-06-01)
# ---------------------------------------------------------------------------


def test_engine_run_calls_update_max_frames_times(monkeypatch):
    """run(max_frames=N) invokes the scene tick (update) exactly N times.

    The frame counter is the engine-side proxy for ``_draw`` invocations,
    but a separate observable signal is the scene ``_tick`` callback which
    runs inside ``_draw``.  Attaching a stub scene with a counting
    ``_tick`` proves the draw closure ran end-to-end on every iteration —
    not just the loop wrapper around it.
    """
    _install_stubs(monkeypatch)

    import pharos_engine as se

    class _CountingScene:
        landscape = None
        post_process = None
        pixel_physics_enabled = False
        collision = None
        entities: list = []
        camera = None
        compute = None
        decals = None

        def __init__(self):
            self.tick_count = 0

        def _tick(self, dt):
            self.tick_count += 1

    engine = se.Engine()
    scene = _CountingScene()
    # Avoid invoking the production load_scene path (it triggers compute
    # wiring on an Asset-free scene which is fine, but we want a clean
    # observable surface).
    engine._scene = scene

    engine.run(max_frames=7)

    assert engine._frame_index == 7
    assert scene.tick_count == 7, (
        f"expected scene._tick called 7 times, got {scene.tick_count}"
    )


def test_engine_run_with_max_frames_returns_within_2x_expected_duration(monkeypatch):
    """run(max_frames=10, target_fps=60) returns inside a forgiving CI budget.

    Expected ≈ 10 / 60 = 0.167 s.  We assert ≤ 0.5 s to absorb stub-GPU
    overhead, Windows timer granularity, and CI scheduling jitter.
    """
    _install_stubs(monkeypatch)

    import pharos_engine as se

    engine = se.Engine()

    t0 = time.perf_counter()
    engine.run(max_frames=10, target_fps=60.0)
    elapsed = time.perf_counter() - t0

    assert engine._frame_index == 10
    assert elapsed <= 0.5, (
        f"run(max_frames=10, target_fps=60) took {elapsed:.3f}s — "
        "expected <= 0.5s (≈0.167s nominal)"
    )


def test_engine_run_clean_shutdown_releases_gpu_resources(monkeypatch):
    """run(max_frames=N) destroys cached GPU buffers and textures on return.

    ``BufferManager.destroy_all`` / ``TextureManager.destroy_all`` are the
    documented teardown hooks; ``Engine.run`` must invoke them as part of
    its normal exit so callers that loop ``run()`` (e.g. CI smoke harnesses
    that recreate an Engine per example) don't leak GPU handles.
    """
    _install_stubs(monkeypatch)

    from pharos_engine import engine as engine_mod

    destroyed = {"buf": 0, "tex": 0}

    class _StubBufMgr:
        def destroy_all(self):
            destroyed["buf"] += 1

    class _StubTexMgr:
        def destroy_all(self):
            destroyed["tex"] += 1

    # Extend the stubbed _setup_gpu so the two managers exist for teardown.
    real_setup = engine_mod.Engine._setup_gpu

    def _stub_setup_with_managers(self, canvas):
        real_setup(self, canvas)
        self._buf_mgr = _StubBufMgr()
        self._tex_mgr = _StubTexMgr()

    monkeypatch.setattr(engine_mod.Engine, "_setup_gpu", _stub_setup_with_managers)

    import pharos_engine as se

    engine = se.Engine()
    engine.run(max_frames=3)

    assert destroyed["buf"] == 1, "BufferManager.destroy_all not called on shutdown"
    assert destroyed["tex"] == 1, "TextureManager.destroy_all not called on shutdown"
    assert engine._mesh_pipeline is None
    assert engine._mesh_renderers == {}


def test_engine_run_handles_exception_in_update(monkeypatch):
    """Exceptions raised inside the per-frame draw propagate out of run().

    The headless path must NOT swallow user errors — if scene logic raises,
    the test harness needs to see the traceback, not a silent 0-frame
    completion.  Teardown still runs (verified by checking the config
    manager state) so a propagated exception leaves no leaked watcher.
    """
    _install_stubs(monkeypatch)

    import pharos_engine as se

    class _ExplodingScene:
        landscape = None
        post_process = None
        pixel_physics_enabled = False
        collision = None
        entities: list = []
        camera = None
        compute = None
        decals = None

        def _tick(self, dt):
            raise RuntimeError("boom from user update")

    engine = se.Engine()
    engine._scene = _ExplodingScene()

    with pytest.raises(RuntimeError, match="boom from user update"):
        engine.run(max_frames=5)

    # The exception must surface on the very first frame — no partial loop.
    assert engine._frame_index == 1
    # Teardown still happened — mesh caches were reset by _shutdown_gpu_resources.
    assert engine._mesh_pipeline is None
    assert engine._mesh_renderers == {}


# ---------------------------------------------------------------------------
# SLAPPYENGINE_MAX_FRAMES environment-variable fallback
# ---------------------------------------------------------------------------


def test_env_var_sets_max_frames_when_kwarg_omitted(monkeypatch):
    """SLAPPYENGINE_MAX_FRAMES=N drives the headless path when no kwarg is given."""
    _install_stubs(monkeypatch)
    monkeypatch.setenv("SLAPPYENGINE_MAX_FRAMES", "4")

    import pharos_engine as se

    engine = se.Engine()
    engine.run()  # no kwarg — env var must take over

    assert engine._frame_index == 4


def test_kwarg_wins_over_env_var(monkeypatch):
    """Explicit max_frames kwarg overrides the environment fallback."""
    _install_stubs(monkeypatch)
    monkeypatch.setenv("SLAPPYENGINE_MAX_FRAMES", "99")

    import pharos_engine as se

    engine = se.Engine()
    engine.run(max_frames=2)

    assert engine._frame_index == 2, "kwarg must take precedence over env var"


def test_env_var_invalid_value_raises(monkeypatch):
    """A non-integer SLAPPYENGINE_MAX_FRAMES is a configuration error."""
    _install_stubs(monkeypatch)
    monkeypatch.setenv("SLAPPYENGINE_MAX_FRAMES", "not-a-number")

    import pharos_engine as se

    engine = se.Engine()
    with pytest.raises(ValueError, match="SLAPPYENGINE_MAX_FRAMES"):
        engine.run()
