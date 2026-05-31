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
    from slappyengine import engine as engine_mod

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

    import slappyengine as se

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

    import slappyengine as se

    engine = se.Engine()
    engine.run(max_frames=0)
    assert engine._frame_index == 0


def test_run_max_frames_negative_raises(monkeypatch):
    """run(max_frames=-1) is a programming error and rejected."""
    _install_stubs(monkeypatch)

    import slappyengine as se

    engine = se.Engine()
    with pytest.raises(ValueError):
        engine.run(max_frames=-1)
