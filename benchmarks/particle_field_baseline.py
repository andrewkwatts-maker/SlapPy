"""ParticleField CPU baseline harness.

Measures per-step wall-clock time for the ParticleField hot paths across
three particle-count regimes (small / medium / large). The output is the
reference we will compare against once these kernels are ported to GPU.

Usage::

    python benchmarks/particle_field_baseline.py

Writes a markdown summary to ``benchmarks/baseline_report.md`` and also
echoes it to stdout. Does NOT modify engine source — methods are wrapped
by monkey-patching the instance / the ``particle_field`` module namespace
with ``time.perf_counter`` deltas, then restored on teardown.
"""
from __future__ import annotations

import functools
import statistics
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import numpy as np

# Make the in-tree package importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PKG_ROOT = _REPO_ROOT / "python"
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from slappyengine.physics import particle_field as _pf_module  # noqa: E402
from slappyengine.physics.blast import detonate  # noqa: E402
from slappyengine.physics.particle_field import ParticleField  # noqa: E402
from slappyengine.physics.splatter_presets import get as get_preset  # noqa: E402


# Methods we time on the field instance.
_INSTANCE_METHODS = (
    "_integrate",
    "_collide",
    "_drill_through",
    "_kinetic_relax",
    "_pbf_bridge_step",
    "_slide",
    "_slump_loose",
    "_thermal_step",
)

# Module-level function (imported into particle_field's namespace, called
# unqualified inside step()). We wrap the symbol on the module object so
# the unqualified call inside step() resolves to the wrapped version.
_MODULE_FUNCS = ("bake_settled_particles",)


class Timer:
    """Per-method wall-clock accumulator + per-call sample list."""

    def __init__(self) -> None:
        # samples[name] = list[float] in seconds, one entry per call
        self.samples: dict[str, list[float]] = {}
        # step_samples is the outer-loop wrapper around ParticleField.step()
        self.step_samples: list[float] = []

    def record(self, name: str, dt: float) -> None:
        self.samples.setdefault(name, []).append(dt)

    def record_step(self, dt: float) -> None:
        self.step_samples.append(dt)


def _wrap_instance_method(field: ParticleField, name: str, timer: Timer,
                          originals: dict[str, Callable]) -> None:
    """Replace ``field.<name>`` with a perf_counter-timed wrapper.

    We bind on the instance so multiple fields stay independent and so
    the wrap is trivially undone by ``delattr`` in restore().
    """
    if not hasattr(field, name):
        return
    original = getattr(field, name)
    originals[f"instance::{name}"] = original

    @functools.wraps(original)
    def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        t0 = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            timer.record(name, time.perf_counter() - t0)

    setattr(field, name, wrapped)


def _wrap_module_func(name: str, timer: Timer,
                      originals: dict[str, Callable]) -> None:
    """Wrap a function in the ``particle_field`` module namespace.

    The call inside ``ParticleField.step()`` uses the unqualified name,
    which resolves to the module-level binding — so patching the module
    attribute is enough.
    """
    original = getattr(_pf_module, name)
    originals[f"module::{name}"] = original

    @functools.wraps(original)
    def wrapped(*args, **kwargs):  # type: ignore[no-untyped-def]
        t0 = time.perf_counter()
        try:
            return original(*args, **kwargs)
        finally:
            timer.record(name, time.perf_counter() - t0)

    setattr(_pf_module, name, wrapped)


def _restore(field: ParticleField, originals: dict[str, Callable]) -> None:
    for key, original in originals.items():
        scope, name = key.split("::", 1)
        if scope == "instance":
            # Remove the instance attribute so the class-level method
            # shows through again (cleaner than rebinding).
            try:
                delattr(field, name)
            except AttributeError:
                setattr(field, name, original)
        else:
            setattr(_pf_module, name, original)


@contextmanager
def instrument(field: ParticleField, timer: Timer):
    """Context manager: install all wrappers, restore on exit."""
    originals: dict[str, Callable] = {}
    try:
        for m in _INSTANCE_METHODS:
            _wrap_instance_method(field, m, timer, originals)
        for f in _MODULE_FUNCS:
            _wrap_module_func(f, timer, originals)
        yield
    finally:
        _restore(field, originals)


# ── Scenario builders ──────────────────────────────────────────────────


W, H = 640, 360
GROUND_Y = 280
BLAST_X = W // 2
CRATER_RADIUS = 60
CRATER_DEPTH = 28
DT = 1.0 / 60.0


def _make_field(preset_name: str, *, gravity: float | None = None) -> ParticleField:
    preset = get_preset(preset_name)
    f = ParticleField(
        width=W, height=H,
        gravity=preset.gravity if gravity is None else gravity,
    )
    f.fill_ground(
        top_y=GROUND_Y,
        color=(180, 150, 90),
        sub_color=(60, 44, 28),
    )
    return f


def _detonate_once(field: ParticleField, preset_name: str,
                   *, x: int = BLAST_X, y: int = GROUND_Y,
                   seed: int = 2026) -> int:
    rng = np.random.default_rng(seed)
    preset = get_preset(preset_name)
    return detonate(
        field, preset,
        x=float(x), y=float(y),
        crater_radius=float(CRATER_RADIUS),
        crater_depth=float(CRATER_DEPTH),
        rng=rng,
    )


# ── Reporting ──────────────────────────────────────────────────────────


def _pct(num: float, denom: float) -> float:
    return 100.0 * num / denom if denom > 0 else 0.0


def _p95(samples: list[float]) -> float:
    if not samples:
        return 0.0
    # statistics.quantiles n=20 → 5%-spaced quantiles; index 18 = 95th.
    if len(samples) < 20:
        s = sorted(samples)
        idx = max(0, int(round(0.95 * (len(s) - 1))))
        return s[idx]
    return statistics.quantiles(samples, n=20)[18]


def _summarise(scenario: str, n_particles: int, timer: Timer,
               extra_note: str = "") -> str:
    step_total_s = sum(timer.step_samples)
    step_mean_ms = 1000.0 * statistics.fmean(timer.step_samples) if timer.step_samples else 0.0
    step_p95_ms = 1000.0 * _p95(timer.step_samples)
    fps = 1.0 / statistics.fmean(timer.step_samples) if timer.step_samples else 0.0

    # Build a row per tracked method, plus a final total-step row.
    rows: list[tuple[str, float, float, float]] = []
    # Preserve declared order, but emit method even if zero calls.
    tracked = list(_INSTANCE_METHODS) + ["bake_settled_particles"]
    for name in tracked:
        samples = timer.samples.get(name, [])
        if not samples:
            rows.append((name, 0.0, 0.0, 0.0))
            continue
        mean_per_step_ms = 1000.0 * (sum(samples) / len(timer.step_samples))
        p95_ms = 1000.0 * _p95(samples)
        share = _pct(sum(samples), step_total_s)
        rows.append((name, mean_per_step_ms, p95_ms, share))

    # Hot path = highest-share method (excluding total).
    nonzero = [r for r in rows if r[3] > 0]
    nonzero.sort(key=lambda r: r[3], reverse=True)
    top3 = nonzero[:3]

    lines: list[str] = []
    lines.append(f"## Scenario {scenario} (~{n_particles} particles)")
    if extra_note:
        lines.append("")
        lines.append(extra_note)
    lines.append("")
    lines.append("| method | mean ms/step | p95 ms/step | % total |")
    lines.append("|---|---:|---:|---:|")
    for name, mean_ms, p95_ms, share in rows:
        lines.append(f"| {name} | {mean_ms:.3f} | {p95_ms:.3f} | {share:.1f}% |")
    lines.append(
        f"| **total step()** | **{step_mean_ms:.3f}** | **{step_p95_ms:.3f}** | **100.0%** |"
    )
    lines.append("")
    if top3:
        hot = ", ".join(f"`{n}` ({s:.0f}%)" for n, _, _, s in top3)
    else:
        hot = "(no hot methods recorded)"
    lines.append(f"Steady-state: **{fps:.1f} fps**. Top 3: {hot}.")
    lines.append("")
    return "\n".join(lines)


# ── Scenarios ──────────────────────────────────────────────────────────


N_STEPS = 100
WARMUP_STEPS = 3  # one frame after detonate to let arrays size up + JIT-warm any caches


def run_scenario_a() -> tuple[str, list[tuple[str, float]], float, int]:
    """Small: sloppy preset, single blast (~680 particles)."""
    field = _make_field("sloppy")
    n_spawned = _detonate_once(field, "sloppy")

    timer = Timer()
    # Warm-up runs (no measurement).
    for _ in range(WARMUP_STEPS):
        field.step(DT)

    with instrument(field, timer):
        for _ in range(N_STEPS):
            t0 = time.perf_counter()
            field.step(DT)
            timer.record_step(time.perf_counter() - t0)

    report = _summarise(
        scenario="A (small, sloppy preset)",
        n_particles=n_spawned,
        timer=timer,
    )
    top3 = _top3_for(timer)
    fps = _fps_for(timer)
    return report, top3, fps, n_spawned


def run_scenario_b() -> tuple[str, list[tuple[str, float]], float, int]:
    """Medium: snow field + mud field, aggregated (~2350 particles)."""
    field_snow = _make_field("snow")
    field_mud = _make_field("mud")
    n_snow = _detonate_once(field_snow, "snow", seed=11)
    n_mud = _detonate_once(field_mud, "mud", seed=22)
    n_total = n_snow + n_mud

    timer = Timer()
    # Warm-up.
    for _ in range(WARMUP_STEPS):
        field_snow.step(DT)
        field_mud.step(DT)

    with instrument(field_snow, timer):
        # Also instrument the mud field — same timer, same module wraps
        # (module wraps are global so they cover both fields).
        with instrument(field_mud, timer):
            for _ in range(N_STEPS):
                t0 = time.perf_counter()
                field_snow.step(DT)
                field_mud.step(DT)
                timer.record_step(time.perf_counter() - t0)

    report = _summarise(
        scenario="B (medium, snow + mud, aggregated)",
        n_particles=n_total,
        timer=timer,
        extra_note=(
            f"Two separate fields stepped in lockstep — snow={n_snow}, mud={n_mud}. "
            "ms/step is the combined wall time per (snow.step + mud.step) pair."
        ),
    )
    top3 = _top3_for(timer)
    fps = _fps_for(timer)
    return report, top3, fps, n_total


def run_scenario_c() -> tuple[str, list[tuple[str, float]], float, int]:
    """Large: ~10000 particles via N=10 staggered sand detonates."""
    field = _make_field("sand")
    n_total = 0
    n_blasts = 10
    # Stagger the detonates across the first ~30 frames so the field has
    # particles at mixed lifetimes — closer to a real combat scene.
    # We tick a few frames between each to let earlier blasts integrate.
    stagger_frames = 3
    blast_xs = np.linspace(BLAST_X - 200, BLAST_X + 200, n_blasts).astype(int)
    rng_seeds = list(range(100, 100 + n_blasts))
    blast_iter = iter(zip(blast_xs.tolist(), rng_seeds))
    pending = n_blasts
    setup_frames = 0
    while pending > 0:
        x, seed = next(blast_iter)
        n_total += _detonate_once(field, "sand", x=int(x), seed=seed)
        pending -= 1
        for _ in range(stagger_frames):
            field.step(DT)
            setup_frames += 1

    # Brief warmup AFTER all blasts are in flight.
    for _ in range(WARMUP_STEPS):
        field.step(DT)

    timer = Timer()
    with instrument(field, timer):
        for _ in range(N_STEPS):
            t0 = time.perf_counter()
            field.step(DT)
            timer.record_step(time.perf_counter() - t0)

    report = _summarise(
        scenario="C (large, 10x sand detonates staggered)",
        n_particles=n_total,
        timer=timer,
        extra_note=(
            f"Synthesised by {n_blasts} sand detonate() calls staggered across "
            f"{setup_frames} setup frames (so particles are at mixed lifetimes "
            f"before the timing window starts)."
        ),
    )
    top3 = _top3_for(timer)
    fps = _fps_for(timer)
    return report, top3, fps, n_total


# ── Helpers for the cross-scenario summary ─────────────────────────────


def _top3_for(timer: Timer) -> list[tuple[str, float]]:
    step_total_s = sum(timer.step_samples)
    if step_total_s <= 0:
        return []
    pairs: list[tuple[str, float]] = []
    for name, samples in timer.samples.items():
        share = _pct(sum(samples), step_total_s)
        if share > 0:
            pairs.append((name, share))
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs[:3]


def _fps_for(timer: Timer) -> float:
    if not timer.step_samples:
        return 0.0
    return 1.0 / statistics.fmean(timer.step_samples)


# ── Main ───────────────────────────────────────────────────────────────


def main() -> None:
    header = (
        "# ParticleField CPU baseline\n\n"
        f"- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- Steps measured per scenario: {N_STEPS} (after {WARMUP_STEPS}-step warmup)\n"
        f"- dt: {DT:.5f} s (60 Hz reference)\n"
        f"- Field size: {W}x{H}\n"
        "- Per-method wall time captured by perf_counter wrappers; total step()\n"
        "  is the outer-loop perf_counter delta around `field.step(dt)`.\n"
        "\n"
    )

    print("Running scenario A (small)...", flush=True)
    report_a, top_a, fps_a, n_a = run_scenario_a()
    print(f"  -> {fps_a:.1f} fps, top hot path: {top_a[0][0] if top_a else 'n/a'}",
          flush=True)

    print("Running scenario B (medium)...", flush=True)
    report_b, top_b, fps_b, n_b = run_scenario_b()
    print(f"  -> {fps_b:.1f} fps, top hot path: {top_b[0][0] if top_b else 'n/a'}",
          flush=True)

    print("Running scenario C (large)...", flush=True)
    report_c, top_c, fps_c, n_c = run_scenario_c()
    print(f"  -> {fps_c:.1f} fps, top hot path: {top_c[0][0] if top_c else 'n/a'}",
          flush=True)

    # Cross-scenario rollup.
    rollup_lines = ["## Cross-scenario rollup", "",
                    "| scenario | particles | fps | top 1 | top 2 | top 3 |",
                    "|---|---:|---:|---|---|---|"]

    def _fmt_top(top: list[tuple[str, float]], i: int) -> str:
        if i >= len(top):
            return "—"
        n, s = top[i]
        return f"{n} ({s:.0f}%)"

    for name, n, fps, top in (
        ("A small", n_a, fps_a, top_a),
        ("B medium", n_b, fps_b, top_b),
        ("C large", n_c, fps_c, top_c),
    ):
        rollup_lines.append(
            f"| {name} | {n} | {fps:.1f} | "
            f"{_fmt_top(top, 0)} | {_fmt_top(top, 1)} | {_fmt_top(top, 2)} |"
        )
    rollup_lines.append("")

    final = "\n".join([
        header,
        report_a,
        report_b,
        report_c,
        "\n".join(rollup_lines),
    ])

    out = Path(__file__).resolve().parent / "baseline_report.md"
    out.write_text(final, encoding="utf-8")
    print()
    print(final)
    print(f"\nReport written to: {out}")


if __name__ == "__main__":
    main()
