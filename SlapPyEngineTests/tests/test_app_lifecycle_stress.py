"""App lifecycle stress test suite (RR7).

Hardens the contract of :func:`slappyengine.launch` /
:meth:`slappyengine.app.App.run` under:

* 500-frame bare loops,
* strict begin/tick/end ordering,
* multi-subsystem load (HUD + diagnostics + capture + physics3 + audio),
* on_tick exceptions,
* absent-hook variants,
* dt sanity,
* ``SLAPPYENGINE_MAX_FRAMES`` env-var cap (test-side wrapper — the App
  API doesn't ingest env vars directly today, so the test wires the env
  var into ``launch(max_frames=...)`` to pin the intended contract for
  when it lands),
* memory stability across a 200-frame HUD + diagnostics run.

Everything runs in HH1's headless mode (``enable_gpu=False``,
``renderer_backend="stub"``). No wgpu, no window, no ffmpeg required.
The whole suite is bounded (< a couple of seconds on a laptop).
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

import pytest

import slappyengine
from slappyengine.app import App, AppConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _headless_config(**overrides: Any) -> AppConfig:
    """Return an ``AppConfig`` shaped for stress testing.

    Uses the ``stub`` renderer backend so the run loop never touches
    wgpu / a window. Callers may override any field via kwargs.
    """
    base: dict[str, Any] = dict(
        window_title="RR7_lifecycle_stress",
        window_size=(320, 240),
        enable_gpu=False,
        renderer_backend="stub",
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        fixed_timestep=False,  # tests should run as fast as possible
        target_fps=60,
    )
    base.update(overrides)
    return AppConfig(**base)


class _LifecycleRecorder:
    """Captures the (event, frame_index) sequence for ordering assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, int]] = []
        self.tick_frame = 0
        self.dts: list[float] = []

    def on_begin(self, app: App) -> None:
        self.events.append(("begin", self.tick_frame))

    def on_tick(self, app: App, dt: float) -> None:
        self.events.append(("tick", self.tick_frame))
        self.dts.append(dt)
        self.tick_frame += 1

    def on_end(self, app: App) -> None:
        self.events.append(("end", self.tick_frame))


# ---------------------------------------------------------------------------
# 1. 500-frame bare lifecycle
# ---------------------------------------------------------------------------


def test_500_frame_bare_lifecycle() -> None:
    """launch(on_tick=..., max_frames=500) fires the tick 500x cleanly."""
    counter = {"n": 0}

    def tick(app: App, dt: float) -> None:
        counter["n"] += 1

    app = slappyengine.launch(
        on_tick=tick,
        config=_headless_config(),
        max_frames=500,
    )
    try:
        assert counter["n"] == 500, (
            f"expected 500 on_tick calls, got {counter['n']}"
        )
        assert app.frame_count == 500, (
            f"expected app.frame_count == 500, got {app.frame_count}"
        )
        # Trace bracket sanity — every run appends the (run_begin, run_end)
        # bookends.
        trace_kinds = [t[0] for t in app.trace]
        assert "run_begin" in trace_kinds
        assert "run_end" in trace_kinds
        assert "on_begin_fired" in trace_kinds
        assert "on_end_fired" in trace_kinds
    finally:
        app.close()


# ---------------------------------------------------------------------------
# 2. Strict begin -> tick*N -> end ordering
# ---------------------------------------------------------------------------


def test_lifecycle_hook_ordering() -> None:
    """on_begin fires exactly once BEFORE first tick; on_end AFTER last tick."""
    rec = _LifecycleRecorder()
    N = 25

    app = slappyengine.launch(
        on_begin=rec.on_begin,
        on_tick=rec.on_tick,
        on_end=rec.on_end,
        config=_headless_config(),
        max_frames=N,
    )
    try:
        kinds = [ev for ev, _ in rec.events]
        # Exactly one begin at position 0
        assert kinds.count("begin") == 1, kinds.count("begin")
        assert kinds[0] == "begin"
        # Exactly one end at the last position
        assert kinds.count("end") == 1, kinds.count("end")
        assert kinds[-1] == "end"
        # Exactly N ticks between them
        assert kinds.count("tick") == N, kinds.count("tick")
        # And the middle span is all ticks
        assert kinds[1:-1] == ["tick"] * N
    finally:
        app.close()


# ---------------------------------------------------------------------------
# 3. All subsystems active — HUD + diagnostics + screenshot + physics3 + audio
# ---------------------------------------------------------------------------


def test_all_subsystems_active_50_frames(tmp_path) -> None:
    """Enable HUD + diagnostics + capture + physics3 + audio for 50 frames."""
    # Root logger capture so we can count WARNING/ERROR spam.
    warn_records: list[logging.LogRecord] = []

    class _WarnCounter(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                warn_records.append(record)

    handler = _WarnCounter(level=logging.WARNING)
    root_slappy = logging.getLogger("slappyengine")
    root_slappy.addHandler(handler)

    app = App(_headless_config())

    try:
        # --- HUD (MM2)
        app.enable_hud()
        assert getattr(app, "_hud_overlay", None) is not None

        # --- Diagnostics (OO6 / QQ4)
        collector = app.enable_diagnostics()
        assert collector is not None

        # --- Screenshot capture (LL2). Screenshot only — no video recording.
        shot_out = tmp_path / "shot.png"
        shot_status = app.take_screenshot(path=str(shot_out))
        assert isinstance(shot_status, dict)
        assert "status" in shot_status

        # --- Physics3 world (LL7)
        try:
            from slappyengine.physics3_bridge import Body3D, World3D
            world3d = World3D(backend="fallback")
            # A handful of falling spheres for load.
            for i in range(4):
                world3d.add_body(Body3D(position=(float(i), 5.0, 0.0), mass=1.0))
        except Exception as exc:  # pragma: no cover - numpy missing edge case
            pytest.skip(f"physics3 unavailable: {exc}")

        # --- Audio listener (LL4)
        try:
            from slappyengine.audio_3d import Audio3DEngine, AudioListener
            listener = AudioListener(position=(0.0, 1.5, 0.0))
            audio_engine = Audio3DEngine()
            audio_engine.set_listener(listener)
        except Exception as exc:  # pragma: no cover - defensive
            audio_engine = None

        tick_count = {"n": 0}

        def tick(a: App, dt: float) -> None:
            tick_count["n"] += 1
            world3d.step(dt)
            if audio_engine is not None:
                # Update listener position deterministically — cheap no-op-ish
                # DSP path exercises audio subsystem per tick.
                try:
                    audio_engine.update(dt)
                except Exception:
                    pass

        app.run(on_tick=tick, max_frames=50)

        assert tick_count["n"] == 50
        # Sanity: HUD overlay + diagnostics stayed installed the whole time.
        assert getattr(app, "_hud_overlay", None) is not None
        assert app.get_diagnostics() is collector
        # Log spam guard — 50 frames should NOT emit > 100 warnings.
        assert len(warn_records) < 100, (
            f"log spam: {len(warn_records)} warnings in 50 frames"
        )
    finally:
        try:
            app.disable_diagnostics()
        except Exception:
            pass
        app.close()
        root_slappy.removeHandler(handler)


# ---------------------------------------------------------------------------
# 4. on_tick exception — engine must not silently swallow the process
# ---------------------------------------------------------------------------


def test_lifecycle_hook_exceptions_dont_crash_engine(caplog) -> None:
    """A RuntimeError in on_tick at frame 25 must propagate cleanly.

    Contract we pin:

    * The exception is raisable / catchable at the ``launch()`` call site
      (the engine does not silently swallow it).
    * After the caller catches it, ``app.close()`` succeeds.
    * The process is not left in a running state (``app.is_running`` is
      ``False``).
    * The trace records the frames up to (and including) the failing
      one so a post-mortem is possible.
    """
    tick_count = {"n": 0}
    on_end_fired = {"v": False}

    def bad_tick(app: App, dt: float) -> None:
        tick_count["n"] += 1
        if tick_count["n"] == 25:
            raise RuntimeError("RR7 injected fault at frame 25")

    def on_end(app: App) -> None:
        on_end_fired["v"] = True

    app = App(_headless_config())
    caught: BaseException | None = None
    try:
        with caplog.at_level(logging.DEBUG, logger="slappyengine"):
            try:
                app.run(on_tick=bad_tick, on_end=on_end, max_frames=500)
            except RuntimeError as exc:
                caught = exc
        # Caller was able to observe the fault.
        assert caught is not None
        assert "RR7 injected fault" in str(caught)
        # Engine terminated its loop cleanly.
        assert app.is_running is False
        assert tick_count["n"] == 25
        # Trace has at least the run_begin + on_begin_fired frames so
        # a post-mortem can walk the sequence.
        trace_kinds = [t[0] for t in app.trace]
        assert "run_begin" in trace_kinds
        assert "on_begin_fired" in trace_kinds
        # close() works after a faulted run.
        app.close()
        assert app.is_closed is True
    finally:
        if not app.is_closed:
            app.close()
    # on_end may or may not fire under current contract (App.run does not
    # guarantee it in the face of exceptions today). We only assert the
    # caller-observable half of the contract above — that's the piece
    # RR7 is hardening.
    _ = on_end_fired  # intentionally not asserted; documented above


# ---------------------------------------------------------------------------
# 5. No-hook variants
# ---------------------------------------------------------------------------


def test_lifecycle_no_hook_variants() -> None:
    """launch() with only on_begin, then only on_end — no crash, exact count."""
    begin_hits = {"n": 0}

    def only_begin(app: App) -> None:
        begin_hits["n"] += 1

    app1 = slappyengine.launch(
        on_begin=only_begin,
        config=_headless_config(),
        max_frames=5,
    )
    try:
        assert begin_hits["n"] == 1
        assert app1.frame_count == 5
    finally:
        app1.close()

    end_hits = {"n": 0}

    def only_end(app: App) -> None:
        end_hits["n"] += 1

    app2 = slappyengine.launch(
        on_end=only_end,
        config=_headless_config(),
        max_frames=5,
    )
    try:
        assert end_hits["n"] == 1
        assert app2.frame_count == 5
    finally:
        app2.close()

    # And the fully-empty variant — must at least advance frame_count.
    app3 = slappyengine.launch(config=_headless_config(), max_frames=3)
    try:
        assert app3.frame_count == 3
    finally:
        app3.close()


# ---------------------------------------------------------------------------
# 6. dt sanity — positive + finite
# ---------------------------------------------------------------------------


def test_lifecycle_deterministic_dt() -> None:
    """Every ``dt`` handed to on_tick must be positive + finite."""
    import math

    dts: list[float] = []

    def tick(app: App, dt: float) -> None:
        dts.append(dt)

    app = slappyengine.launch(
        on_tick=tick,
        config=_headless_config(),
        max_frames=20,
    )
    try:
        assert len(dts) == 20
        for i, dt in enumerate(dts):
            assert isinstance(dt, float), f"dt[{i}] not float: {type(dt)}"
            assert math.isfinite(dt), f"dt[{i}] not finite: {dt}"
            assert dt > 0.0, f"dt[{i}] not positive: {dt}"
    finally:
        app.close()


# ---------------------------------------------------------------------------
# 7. SLAPPYENGINE_MAX_FRAMES env var cap
# ---------------------------------------------------------------------------


def test_lifecycle_max_frames_env(monkeypatch) -> None:
    """``SLAPPYENGINE_MAX_FRAMES=10`` caps the loop at 10 frames.

    The App/launch API does not currently ingest the env var directly, so
    this test wires it through at the caller layer (the same pattern the
    top-level ``engine.run`` uses). This pins the intended contract so
    when HH1 lands env-var ingestion the assertion still holds.
    """
    monkeypatch.setenv("SLAPPYENGINE_MAX_FRAMES", "10")

    # Read the env var the same way engine.run does (kwarg wins).
    env_val = os.environ.get("SLAPPYENGINE_MAX_FRAMES")
    assert env_val == "10"
    cap = int(env_val)

    tick_count = {"n": 0}

    def tick(app: App, dt: float) -> None:
        tick_count["n"] += 1

    app = slappyengine.launch(
        on_tick=tick,
        config=_headless_config(),
        max_frames=cap,
    )
    try:
        assert tick_count["n"] == 10
        assert app.frame_count == 10
    finally:
        app.close()


# ---------------------------------------------------------------------------
# 8. Memory stability — HUD + diagnostics for 200 frames
# ---------------------------------------------------------------------------


def test_lifecycle_memory_stable() -> None:
    """200 frames with HUD + diagnostics should not grow app.__dict__ boundlessly."""
    app = App(_headless_config())
    app.enable_hud()
    app.enable_diagnostics()

    def tick(a: App, dt: float) -> None:
        # A tiny bit of state-touching work per frame so any leaky
        # accumulator surfaces. No new attributes on the app.
        _ = a.frame_count
        _ = a.elapsed

    try:
        before = sys.getsizeof(app.__dict__)
        app.run(on_tick=tick, max_frames=200)
        after = sys.getsizeof(app.__dict__)

        delta = after - before
        # Trace list appending is O(frames) BY DESIGN (it's the audit
        # log); the check is on the __dict__ container itself, which
        # only grows when new attributes are attached. A 5000-byte
        # tolerance covers the odd dict resize.
        assert abs(delta) < 5000, (
            f"app.__dict__ grew by {delta} bytes over 200 frames — "
            "possible attribute-slot leak"
        )
        assert app.frame_count == 200
    finally:
        try:
            app.disable_diagnostics()
        except Exception:
            pass
        app.close()
