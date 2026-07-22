"""Profiling harness + benchmark scenarios for the physics engine.

This module provides:

- :class:`FrameTimer` — a lightweight per-label wall-clock recorder. Each
  ``with timer.time('label'): ...`` block contributes one sample to the
  rolling list of times for that label. ``report()`` returns mean / median /
  p95 / p99 in milliseconds per label.
- :class:`BenchmarkScenario` — a reproducible scene description that can
  build a :class:`PhysicsWorld` ready to simulate. Six baseline scenarios
  are exported via :func:`baseline_scenarios`.
- :func:`run_benchmark` — drive a scenario for ``frame_count`` frames,
  recording per-frame ``step`` wall-clock, contact counts, and peak
  tracemalloc memory; returns a summary dict.

The scenarios are designed to cover the realistic perf surface of the
hierarchical-hull simulator: a single-body baseline, a small mixed bag,
a 50-body broadphase stress test, a fluid pool with an impactor, a
brittle-glass shatter scene, and a settled pile where most bodies should
skip the per-pixel substep.
"""
from __future__ import annotations

import json
import time
import tracemalloc
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from pharos_engine.physics.body import (
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.world import PhysicsWorld

if TYPE_CHECKING:  # pragma: no cover
    pass


# ---------------------------------------------------------------------------
# FrameTimer
# ---------------------------------------------------------------------------


class _TimerContext(AbstractContextManager):
    """Context manager produced by :meth:`FrameTimer.time`.

    Records elapsed wall-clock seconds (converted to ms on report) into the
    parent timer's ``times`` map for the supplied label.
    """

    __slots__ = ("_timer", "_label", "_t0")

    def __init__(self, timer: "FrameTimer", label: str) -> None:
        self._timer = timer
        self._label = label
        self._t0 = 0.0

    def __enter__(self) -> "_TimerContext":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        dt = time.perf_counter() - self._t0
        self._timer._record(self._label, dt)
        return None


@dataclass
class FrameTimer:
    """Records the wall-clock time spent in each labeled section of a frame.

    Samples accumulate across calls; ``reset()`` clears them. Per-label
    statistics (mean, median, p95, p99) are computed lazily in
    :meth:`report` and are reported in milliseconds.
    """

    labels: list[str] = field(default_factory=list)
    times: dict[str, list[float]] = field(default_factory=dict)

    def __init__(self) -> None:  # type: ignore[override]
        # dataclass-style fields, but we want a hand-written __init__ so the
        # public API stays minimal and pickle-friendly.
        self.labels = []
        self.times = {}

    # -- recording -----------------------------------------------------------

    def _record(self, label: str, seconds: float) -> None:
        bucket = self.times.get(label)
        if bucket is None:
            bucket = []
            self.times[label] = bucket
            self.labels.append(label)
        bucket.append(float(seconds))

    def time(self, label: str) -> _TimerContext:
        """Return a context manager that records elapsed time under ``label``."""
        return _TimerContext(self, label)

    def reset(self) -> None:
        """Drop all recorded samples (keeps the timer reusable)."""
        self.labels.clear()
        self.times.clear()

    # -- reporting -----------------------------------------------------------

    def report(self) -> dict[str, dict]:
        """Return ``{label: {mean_ms, median_ms, p95_ms, p99_ms, n}}``."""
        out: dict[str, dict] = {}
        for label in self.labels:
            samples = self.times.get(label, [])
            if not samples:
                out[label] = {
                    "mean_ms": 0.0,
                    "median_ms": 0.0,
                    "p95_ms": 0.0,
                    "p99_ms": 0.0,
                    "n": 0,
                }
                continue
            arr = np.asarray(samples, dtype=np.float64) * 1000.0
            out[label] = {
                "mean_ms": float(arr.mean()),
                "median_ms": float(np.median(arr)),
                "p95_ms": float(np.percentile(arr, 95)),
                "p99_ms": float(np.percentile(arr, 99)),
                "n": int(arr.size),
            }
        return out

    def to_markdown(self) -> str:
        """Render :meth:`report` as a GitHub-flavored markdown table."""
        rep = self.report()
        lines = [
            "| label | n | mean ms | median ms | p95 ms | p99 ms |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for label, stats in rep.items():
            lines.append(
                f"| {label} | {stats['n']} | "
                f"{stats['mean_ms']:.3f} | {stats['median_ms']:.3f} | "
                f"{stats['p95_ms']:.3f} | {stats['p99_ms']:.3f} |"
            )
        return "\n".join(lines)

    def to_json(self) -> str:
        """Serialize :meth:`report` as a JSON string."""
        return json.dumps(self.report(), indent=2, sort_keys=True)


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@dataclass
class BenchmarkScenario:
    """A reproducible benchmark setup.

    The ``build_world`` method constructs a fresh :class:`PhysicsWorld`
    populated with bodies whose layout is deterministic given ``name``
    and ``n_bodies``. Scenario authors may register additional names via
    :func:`register_scenario_builder`.
    """

    name: str
    n_bodies: int
    materials: list[str]
    world_bounds: tuple[float, float, float, float]
    gravity: tuple[float, float]
    frame_count: int
    description: str

    def build_world(self) -> PhysicsWorld:
        """Construct a :class:`PhysicsWorld` ready to simulate."""
        builder = _SCENARIO_BUILDERS.get(self.name, _build_default_grid)
        world = PhysicsWorld(world_bounds=self.world_bounds)
        # Override gravity without disturbing the rest of WorldConfig.
        world.config.world = type(world.config.world)(
            default_dt=world.config.world.default_dt,
            substeps=world.config.world.substeps,
            gravity=self.gravity,
        )
        # Disable GPU dispatch for deterministic CPU benchmarking.
        world.config.gpu.enabled = False
        world.config.gpu.debug_force_cpu = True
        builder(self, world)
        return world


# -- scenario builders -----------------------------------------------------

_GROUND_THICKNESS = 16  # pixels
_DEFAULT_BALL_DIAMETER = 32


def _make_ground(world: PhysicsWorld, material: str = "stone") -> None:
    """Create a wide fixed slab spanning the world bounds along y = y1 - h/2."""
    assert world.world_bounds is not None
    x0, y0, x1, y1 = world.world_bounds
    width = max(int(x1 - x0), 32)
    silhouette = make_rect_silhouette(width=width, height=_GROUND_THICKNESS)
    ground_y = y1 - _GROUND_THICKNESS * 0.5
    ground_x = (x0 + x1) * 0.5
    world.create_body(
        silhouette=silhouette,
        material=material,
        position=(ground_x, ground_y),
        fixed=True,
    )


def _build_solo_drop(scenario: BenchmarkScenario, world: PhysicsWorld) -> None:
    _make_ground(world, material="stone")
    ball = make_circle_silhouette(_DEFAULT_BALL_DIAMETER)
    world.create_body(
        silhouette=ball,
        material="steel",
        position=(0.0, -40.0),
    )


def _build_multi_body(scenario: BenchmarkScenario, world: PhysicsWorld) -> None:
    """Pack ``n_bodies`` mixed-material balls into a grid above the ground."""
    _make_ground(world, material="stone")
    assert world.world_bounds is not None
    x0, _, x1, _ = world.world_bounds
    materials = scenario.materials or ["steel"]
    n = scenario.n_bodies
    # Choose grid columns so the layout fits within world bounds.
    cols = max(1, int(np.ceil(np.sqrt(n))))
    spacing_x = max(_DEFAULT_BALL_DIAMETER + 4, (x1 - x0 - 8) / cols)
    spacing_y = _DEFAULT_BALL_DIAMETER + 4
    start_x = x0 + spacing_x * 0.5 + 4
    start_y = -120.0
    ball = make_circle_silhouette(_DEFAULT_BALL_DIAMETER)
    for i in range(n):
        col = i % cols
        row = i // cols
        material = materials[i % len(materials)]
        world.create_body(
            silhouette=ball,
            material=material,
            position=(start_x + col * spacing_x, start_y - row * spacing_y),
            velocity=(0.0, 0.0),
        )


def _build_fluid_pool(scenario: BenchmarkScenario, world: PhysicsWorld) -> None:
    """Water rectangle sitting in the world; a steel ball drops into it."""
    _make_ground(world, material="stone")
    assert world.world_bounds is not None
    x0, _, x1, y1 = world.world_bounds
    pool_w = max(int((x1 - x0) * 0.6), 32)
    pool_h = 24
    pool_y = y1 - _GROUND_THICKNESS - pool_h * 0.5
    pool_x = (x0 + x1) * 0.5
    water_sil = make_rect_silhouette(width=pool_w, height=pool_h)
    world.create_body(
        silhouette=water_sil,
        material="water",
        position=(pool_x, pool_y),
        fixed=False,
    )
    ball = make_circle_silhouette(_DEFAULT_BALL_DIAMETER)
    world.create_body(
        silhouette=ball,
        material="steel",
        position=(pool_x, pool_y - 80.0),
        velocity=(0.0, 60.0),
    )


def _build_fracture(scenario: BenchmarkScenario, world: PhysicsWorld) -> None:
    """Glass ball impacting a stone slab — exercises the brittle / crack path."""
    _make_ground(world, material="stone")
    assert world.world_bounds is not None
    x0, _, x1, _ = world.world_bounds
    cx = (x0 + x1) * 0.5
    glass = make_circle_silhouette(_DEFAULT_BALL_DIAMETER)
    world.create_body(
        silhouette=glass,
        material="glass",
        position=(cx, -30.0),
        velocity=(0.0, 240.0),  # high downward velocity → brittle damage path
    )


def _build_idle_settled(scenario: BenchmarkScenario, world: PhysicsWorld) -> None:
    """``n_bodies`` already-settled balls floating with no contacts.

    Bodies are spawned with no velocity and no gravity (overridden by the
    scenario) at positions far enough apart that no broadphase pair ever
    overlaps.  No contacts are generated, so :meth:`PhysicsWorld._is_active`
    returns ``False`` for every body and the per-pixel substep is skipped.
    This exercises the inactive-body fast path.
    """
    # NOTE: idle_settled overrides gravity to zero in baseline_scenarios()
    # so the balls genuinely stay put without bouncing on the ground.
    assert world.world_bounds is not None
    x0, _, x1, y1 = world.world_bounds
    n = scenario.n_bodies
    # Spread bodies generously so AABBs never overlap.
    spacing = max(_DEFAULT_BALL_DIAMETER * 2 + 4, (x1 - x0 - 8) / max(n, 1))
    rest_y = (y1 - _GROUND_THICKNESS) * 0.25  # high above any potential floor
    start_x = x0 + spacing * 0.5 + 4
    ball = make_circle_silhouette(_DEFAULT_BALL_DIAMETER)
    material = (scenario.materials or ["stone"])[0]
    for i in range(n):
        world.create_body(
            silhouette=ball,
            material=material,
            position=(start_x + i * spacing, rest_y),
            velocity=(0.0, 0.0),
        )


def _build_default_grid(scenario: BenchmarkScenario, world: PhysicsWorld) -> None:
    _build_multi_body(scenario, world)


_SCENARIO_BUILDERS: dict[str, callable] = {
    "solo_drop": _build_solo_drop,
    "multi_body_5": _build_multi_body,
    "multi_body_50": _build_multi_body,
    "fluid_pool": _build_fluid_pool,
    "fracture": _build_fracture,
    "idle_settled": _build_idle_settled,
}


def register_scenario_builder(name: str, builder) -> None:
    """Register a scenario builder for use with custom :class:`BenchmarkScenario`s."""
    _SCENARIO_BUILDERS[name] = builder


# -- baseline scenarios ----------------------------------------------------


def baseline_scenarios() -> list[BenchmarkScenario]:
    """Return the six built-in benchmark scenarios."""
    return [
        BenchmarkScenario(
            name="solo_drop",
            n_bodies=1,
            materials=["steel"],
            world_bounds=(-128.0, -256.0, 128.0, 64.0),
            gravity=(0.0, 196.0),
            frame_count=60,
            description="1 steel ball onto a stone slab — single-body baseline.",
        ),
        BenchmarkScenario(
            name="multi_body_5",
            n_bodies=5,
            materials=["steel", "iron", "stone", "rubber", "wood"],
            world_bounds=(-192.0, -256.0, 192.0, 64.0),
            gravity=(0.0, 196.0),
            frame_count=60,
            description="5 mixed-material balls falling onto stone ground.",
        ),
        BenchmarkScenario(
            name="multi_body_50",
            n_bodies=50,
            materials=["steel", "iron", "stone", "rubber", "wood", "glass"],
            world_bounds=(-384.0, -384.0, 384.0, 96.0),
            gravity=(0.0, 196.0),
            frame_count=60,
            description="50 balls — stress test for O(N^2) broadphase + contact loop.",
        ),
        BenchmarkScenario(
            name="fluid_pool",
            n_bodies=2,
            materials=["water", "steel"],
            world_bounds=(-160.0, -256.0, 160.0, 64.0),
            gravity=(0.0, 196.0),
            frame_count=60,
            description="Water pool + steel impactor — fluid path exercise.",
        ),
        BenchmarkScenario(
            name="fracture",
            n_bodies=1,
            materials=["glass", "stone"],
            world_bounds=(-128.0, -256.0, 128.0, 64.0),
            gravity=(0.0, 196.0),
            frame_count=60,
            description="Glass ball onto stone — brittle damage + cc_label path.",
        ),
        BenchmarkScenario(
            name="idle_settled",
            n_bodies=20,
            materials=["stone"],
            world_bounds=(-2560.0, -256.0, 2560.0, 256.0),
            gravity=(0.0, 0.0),  # zero gravity so bodies actually idle
            frame_count=60,
            description="20 idle bodies with no contacts — exercises inactive-body fast path.",
        ),
    ]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_benchmark(
    scenario: BenchmarkScenario,
    timer: FrameTimer | None = None,
    warmup_frames: int = 2,
) -> dict:
    """Run ``scenario`` and return a summary dict.

    Parameters
    ----------
    scenario:
        The scenario to run.
    timer:
        Optional :class:`FrameTimer` to record per-frame ``step`` time. A
        fresh timer is used if ``None``.
    warmup_frames:
        Number of initial frames excluded from statistics, to absorb the
        cost of first-touch allocation and JIT warm-up.

    Returns
    -------
    dict with keys ``name``, ``fps``, ``mean_ms``, ``median_ms``, ``p95_ms``,
    ``p99_ms``, ``contacts_per_frame_mean``, ``mem_bytes_peak``,
    ``frame_count``, and ``n_bodies``.
    """
    if timer is None:
        timer = FrameTimer()

    world = scenario.build_world()

    # Memory tracking — start fresh so peak reflects only the simulation.
    was_tracing = tracemalloc.is_tracing()
    if not was_tracing:
        tracemalloc.start()
    tracemalloc.reset_peak()

    contacts_per_frame: list[int] = []
    total_frames = max(warmup_frames + scenario.frame_count, 1)

    for frame_idx in range(total_frames):
        if frame_idx < warmup_frames:
            # Warm-up frames are not recorded into the per-label timer.
            try:
                contacts = world.step()
            except Exception:
                contacts = []
            continue

        with timer.time(f"{scenario.name}.step"):
            contacts = world.step()
        contacts_per_frame.append(len(contacts) if contacts is not None else 0)

    _, peak = tracemalloc.get_traced_memory()
    if not was_tracing:
        tracemalloc.stop()

    report = timer.report()
    label = f"{scenario.name}.step"
    stats = report.get(label, {"mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "n": 0})
    mean_ms = stats["mean_ms"]
    fps = (1000.0 / mean_ms) if mean_ms > 0.0 else float("inf")

    return {
        "name": scenario.name,
        "n_bodies": scenario.n_bodies,
        "frame_count": scenario.frame_count,
        "fps": float(fps),
        "mean_ms": float(mean_ms),
        "median_ms": float(stats["median_ms"]),
        "p95_ms": float(stats["p95_ms"]),
        "p99_ms": float(stats["p99_ms"]),
        "contacts_per_frame_mean": (
            float(sum(contacts_per_frame) / len(contacts_per_frame))
            if contacts_per_frame
            else 0.0
        ),
        "mem_bytes_peak": int(peak),
        "description": scenario.description,
    }


__all__ = [
    "BenchmarkScenario",
    "FrameTimer",
    "baseline_scenarios",
    "register_scenario_builder",
    "run_benchmark",
]
