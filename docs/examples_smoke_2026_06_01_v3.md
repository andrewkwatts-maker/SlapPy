# Examples Smoke Audit v3 — 2026-06-01

## What changed since v2

The v2 audit (`docs/examples_smoke_2026_06_01.md`) introduced the
`Engine.run(max_frames=N)` runpy injection harness. Driving demos with
explicit kwarg patches requires touching every harness entry point, so
v3 adds two engine-side ergonomics that let CI configure the smoke run
without source patches:

1. **`SLAPPYENGINE_MAX_FRAMES` environment variable.** When `Engine.run`
   is called with no `max_frames` kwarg, the env var is consulted as a
   fallback. The explicit kwarg always wins — env var is only used when
   the demo invokes `engine.run()` with no arguments.
2. **`Engine.run(target_fps=N)` frame pacing.** Optional sleep between
   frames so headless smoke runs don't hammer the CPU when N is large.
   Ignored in the live event-loop path.

Both ship with regression tests in `tests/test_engine_max_frames.py`:
`test_env_var_sets_max_frames_when_kwarg_omitted`,
`test_kwarg_wins_over_env_var`,
`test_env_var_invalid_value_raises`, and
`test_engine_run_with_max_frames_returns_within_2x_expected_duration`.

## CI helper invocation

The v2 harness wrapped every `engine.run()` demo with a runpy
monkey-patch. In v3 the same end-to-end smoke can be driven directly:

```bash
PYTHONPATH=python SLAPPYENGINE_MAX_FRAMES=5 python examples/hello_world.py
```

This drives the demo's per-frame draw callback exactly five times and
returns 0 — no event loop, no window blocking. For pacing-sensitive
demos (large particle counts, GPU-bound shaders) the demo author can
opt into a target FPS without changing the script:

```python
# Inside a demo:
engine.run()  # picks up SLAPPYENGINE_MAX_FRAMES from CI env
```

```python
# Inside a manual smoke harness:
engine.run(max_frames=10, target_fps=60.0)  # ≈0.167s wall clock
```

## Engine.run shutdown contract

`Engine.run` now invokes `_shutdown_gpu_resources()` from a `try/finally`
in both the live and headless paths. This calls
`BufferManager.destroy_all()` + `TextureManager.destroy_all()` and clears
the cached 3D mesh pipeline + per-layer mesh renderers. CI loops that
recreate an `Engine` per example no longer leak GPU handles between
runs, and a user-update exception still triggers teardown before the
exception propagates to the caller.

Covered by `test_engine_run_clean_shutdown_releases_gpu_resources` and
`test_engine_run_handles_exception_in_update`.

## Status snapshot

The v2 47-example matrix is unchanged by these changes — they are
ergonomics, not behaviour. The two GPU-pipeline bugs called out in v2
(`hello_3d_layer.py`, `hello_bake.py`) were addressed separately by
Sprint 6G (`d3871b9` "Fix MeshPipeline shader-binding mismatch") and
R2S1-E (`5956440` "Wire --frames N through hello_3d_layer/hello_bake to
Engine.run(max_frames=N)"). The next full re-run should land all 47
GREEN; that audit will publish as v4.
