"""Cross-subsystem perf refresh — 2026-05-31.

Measures medians for the kernels called out in the perf-refresh sprint:

* PBF bridge step (inside ``ParticleField.step`` on scenario B)
* Softbody / XPBD step (``dynamics.World.step`` on a 20-node rope, reused
  from ``tests/test_perf_no_regression.py``)
* ``_kinetic_relax`` (CPU vectorised path, scenario C)
* ``_kinetic_relax`` (GPU path, via ``gpu_kinetic_relax`` — falls back to
  the numpy reference inside ``particle_gpu`` when wgpu isn't available;
  we still time the dispatch wrapper to capture the same code path that
  ships)
* Bloom pyramid (``downsample_mn13`` 256x256 + ``upsample_tent9`` back to
  256x256 — one full pyramid stage)
* TAA resolve (``TAAPass.resolve_numpy`` at 128x128, zero-motion case
  with ``tight_variance_clip=True``)
* GTAO (CPU adaptive-radius helper; no numpy reference for the full pass
  exists so we time the per-pixel ``compute_adaptive_radius`` over a
  representative depth buffer — same arithmetic the WGSL shader runs)

Per the sprint constraints:

* ``time.perf_counter()`` only.
* At least 5 iterations + report median (we run 7 to give a stable
  median with two warmups discarded — for the heavier benches we ramp
  up to 10 iterations).
* Does not touch ``python/slappyengine/softbody/`` or
  ``python/slappyengine/fluid/`` (those directories don't exist in this
  layout — the actual Rust softbody is reached via dynamics.World).

Usage::

    python benchmarks/refresh_2026_05_31.py

Echoes a per-bench median + std% table and exits 0 on success.  The
caller (`baseline_report.md` refresh task) reads the printed table and
splices it into the report.
"""
from __future__ import annotations

import gc
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np


# Make the in-tree package importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PKG_ROOT = _REPO_ROOT / "python"
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))


# ──────────────────────────────────────────────────────────────────────
# Bench harness
# ──────────────────────────────────────────────────────────────────────


def measure(fn: Callable[[], None], *, iters: int = 7, warmup: int = 2) -> tuple[float, float, list[float]]:
    """Run ``fn`` ``iters`` times, return ``(median_ms, std_pct, samples_ms)``.

    ``samples_ms`` excludes warmup. ``std_pct`` is ``stdev / median * 100``
    — a stability number we use downstream to decide which benches are
    safe to pin into ``test_perf_no_regression.py`` (<5% goes in).
    """
    for _ in range(warmup):
        fn()
    gc.collect()
    samples_s: list[float] = []
    for _ in range(iters):
        t0 = time.perf_counter()
        fn()
        samples_s.append(time.perf_counter() - t0)
    samples_ms = [s * 1000.0 for s in samples_s]
    med = statistics.median(samples_ms)
    sd = statistics.pstdev(samples_ms) if len(samples_ms) > 1 else 0.0
    pct = (sd / med * 100.0) if med > 0 else 0.0
    return med, pct, samples_ms


# ──────────────────────────────────────────────────────────────────────
# Bench definitions
# ──────────────────────────────────────────────────────────────────────


def bench_pbf_bridge_step() -> tuple[float, float, list[float]]:
    """Scenario B medium — measures the combined snow+mud field.step.
    The PBF bridge inside particle_field.step() dominates this scenario
    (~30% share per the baseline report)."""
    from slappyengine.physics.particle_field import ParticleField
    from slappyengine.physics.splatter_presets import get
    from slappyengine.physics.blast import detonate

    W, H = 640, 360
    GROUND_Y = 280
    DT = 1.0 / 60.0

    def _make(preset_name: str) -> ParticleField:
        preset = get(preset_name)
        f = ParticleField(width=W, height=H, gravity=preset.gravity)
        f.fill_ground(top_y=GROUND_Y, color=(180, 150, 90), sub_color=(60, 44, 28))
        return f

    snow = _make("snow")
    mud = _make("mud")
    rng_a = np.random.default_rng(11)
    rng_b = np.random.default_rng(22)
    detonate(snow, get("snow"), x=320.0, y=280.0, crater_radius=60.0, crater_depth=28.0, rng=rng_a)
    detonate(mud, get("mud"), x=320.0, y=280.0, crater_radius=60.0, crater_depth=28.0, rng=rng_b)
    # Warm a few frames before measurement.
    for _ in range(3):
        snow.step(DT)
        mud.step(DT)

    def step():
        snow.step(DT)
        mud.step(DT)

    return measure(step, iters=7, warmup=2)


def bench_softbody_step() -> tuple[float, float, list[float]]:
    """20-node distance-joint rope, one ``World.step`` at steady-state.
    This is the same surrogate ``test_perf_no_regression.py`` uses for
    the XPBD/Rust dynamics core."""
    from slappyengine.dynamics import JointSpec, World

    world = World(gravity=(0.0, -9.81))
    pos = np.array([(float(i), 0.0) for i in range(20)], dtype=np.float64)
    offset, _ = world.add_nodes(pos, masses=1.0)
    for i in range(19):
        world.add_joint(JointSpec(
            kind="distance",
            node_a=offset + i,
            node_b=offset + i + 1,
            params={"rest_length": 1.0, "compliance": 0.0},
        ))
    world.warn_overdamping = False
    for _ in range(5):
        world.step(1.0 / 60.0)

    def step():
        world.step(1.0 / 60.0)

    return measure(step, iters=10, warmup=3)


def _build_scenario_c_field():
    """Replicates scenario C from baseline_report.md (10 staggered sand
    detonates, ~10200 particles).  Returns the warmed field."""
    from slappyengine.physics.particle_field import ParticleField
    from slappyengine.physics.splatter_presets import get
    from slappyengine.physics.blast import detonate

    W, H = 640, 360
    GROUND_Y = 280
    BLAST_X = W // 2
    DT = 1.0 / 60.0

    preset = get("sand")
    f = ParticleField(width=W, height=H, gravity=preset.gravity)
    f.fill_ground(top_y=GROUND_Y, color=(180, 150, 90), sub_color=(60, 44, 28))
    blast_xs = np.linspace(BLAST_X - 200, BLAST_X + 200, 10).astype(int)
    for i, x in enumerate(blast_xs.tolist()):
        rng = np.random.default_rng(100 + i)
        detonate(f, preset, x=float(x), y=float(GROUND_Y),
                 crater_radius=60.0, crater_depth=28.0, rng=rng)
        for _ in range(3):
            f.step(DT)
    for _ in range(3):
        f.step(DT)
    return f, DT


def bench_kinetic_relax_cpu() -> tuple[float, float, list[float]]:
    """Times only the vectorised ``_kinetic_relax`` on scenario C."""
    field, dt = _build_scenario_c_field()

    def step():
        field._kinetic_relax(dt)

    return measure(step, iters=10, warmup=3)


def bench_kinetic_relax_gpu() -> tuple[float, float, list[float]]:
    """Times ``gpu_kinetic_relax`` on scenario C.  Falls back to the
    numpy reference when wgpu isn't available — the wrapper still
    iterates 3 sub-steps internally so it captures the Sprint 3B
    sub-iter cost."""
    from slappyengine.physics.particle_gpu import gpu_kinetic_relax
    field, dt = _build_scenario_c_field()

    def step():
        gpu_kinetic_relax(field, dt)

    return measure(step, iters=7, warmup=2)


def bench_bloom_pyramid() -> tuple[float, float, list[float]]:
    """One full pyramid stage: downsample 256x256 -> 128x128 then
    upsample back to 256x256.  Uses ``karis_clamp=False`` on the
    downsample (linear low-pass) to match the steady-state pyramid."""
    from slappyengine.post_process.bloom import downsample_mn13, upsample_tent9

    rng = np.random.default_rng(0xB100)
    rgb = rng.random((256, 256, 3), dtype=np.float32) * 4.0  # HDR-ish

    def step():
        half = downsample_mn13(rgb, karis_clamp=False)
        upsample_tent9(half, (256, 256))

    return measure(step, iters=5, warmup=1)


def bench_taa_resolve() -> tuple[float, float, list[float]]:
    """TAA resolve_numpy on a 128x128 frame, zero-motion path, with the
    Sprint 3D tight variance clip turned on (the post-refresh default
    in the lighting-AAAA polish work)."""
    from slappyengine.post_process.taa import TAAPass

    taa = TAAPass(alpha=0.1, variance_clip_gamma=1.0,
                  karis_weight=False, tight_variance_clip=True)
    rng = np.random.default_rng(0x7AA0)
    current = rng.random((128, 128, 3), dtype=np.float32)
    history = rng.random((128, 128, 3), dtype=np.float32)

    def step():
        taa.resolve_numpy(current, history, motion_uv=None)

    return measure(step, iters=7, warmup=2)


def bench_gtao_adaptive_radius() -> tuple[float, float, list[float]]:
    """Per-pixel ``compute_adaptive_radius`` over a 128x128 depth buffer.
    The full GTAO pass is GPU-only; this is the CPU reference for the
    Jimenez 2016 adaptive-radius helper, called once per pixel."""
    from slappyengine.post_process.gtao import compute_adaptive_radius

    rng = np.random.default_rng(0x6740)
    depth = rng.random((128, 128), dtype=np.float32) * 10.0
    depth_flat = depth.ravel().tolist()
    world_radius = 0.5
    falloff = 0.1

    def step():
        # Tight Python loop — same arithmetic as the WGSL shader.
        for z in depth_flat:
            compute_adaptive_radius(world_radius, z, falloff, 0.25, 1.0)

    return measure(step, iters=5, warmup=1)


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────


BENCHES: list[tuple[str, Callable[[], tuple[float, float, list[float]]]]] = [
    ("pbf_bridge_step (scenario B combined)", bench_pbf_bridge_step),
    ("softbody_step (20-node rope, dynamics.World)", bench_softbody_step),
    ("kinetic_relax (CPU, scenario C)", bench_kinetic_relax_cpu),
    ("kinetic_relax (GPU wrapper, scenario C)", bench_kinetic_relax_gpu),
    ("bloom pyramid (256x256 down+up)", bench_bloom_pyramid),
    ("taa_resolve (128x128, tight clip)", bench_taa_resolve),
    ("gtao adaptive_radius (128x128 depth)", bench_gtao_adaptive_radius),
]


def main() -> None:
    print(f"# Perf refresh — {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    print(f"{'bench':<48} {'median_ms':>12} {'std%':>8} {'iters':>6}")
    print(f"{'-'*48} {'-'*12} {'-'*8} {'-'*6}")
    results: dict[str, tuple[float, float, int]] = {}
    for name, fn in BENCHES:
        print(f"running: {name} ...", flush=True)
        med, pct, samples = fn()
        results[name] = (med, pct, len(samples))
        print(f"{name:<48} {med:>12.4f} {pct:>7.2f}% {len(samples):>6d}", flush=True)
    print()
    # Emit a markdown-friendly table for splice-in.
    print("## Markdown table (for baseline_report.md)")
    print()
    print("| bench | median ms | stdev % | iters |")
    print("|---|---:|---:|---:|")
    for name, (med, pct, n) in results.items():
        print(f"| {name} | {med:.4f} | {pct:.2f}% | {n} |")


if __name__ == "__main__":
    main()
