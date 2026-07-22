"""Perf regression tripwire around the ``hello_ragdoll`` demo.

This module is the single import point for perf sprints — it wires the
demo up as a fixed-load benchmark, captures per-frame timing with
``time.perf_counter_ns`` (nanosecond resolution, monotonic on every
supported platform), summarises the results into a
:class:`PerfResult`, persists them as YAML and compares two runs into
a pass/fail :class:`ComparisonReport`.

The design is deliberately narrow: exactly one demo (``hello_ragdoll``),
exactly one solver step per frame, ``time.perf_counter_ns`` only, YAML
only. Everything else — CLI wrappers, richer stats, multi-demo — layers
on top through the public :class:`PerfTripwire` class.

``python -m pharos_engine.perf.tripwire`` executes the CLI defined in
:mod:`pharos_engine.perf.cli`.
"""
from __future__ import annotations

import datetime as _dt
import importlib.util
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # pragma: no cover - pyyaml is a hard dep in-repo but keep the fallback
    import yaml as _yaml
except Exception:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Constants and paths
# ---------------------------------------------------------------------------

#: The demo the tripwire always benches.
DEMO_NAME: str = "hello_ragdoll"

#: Fixed-dt integration step used by the baseline.
DEFAULT_DT: float = 1.0 / 60.0

#: Path to the YAML baseline that ships alongside this module.
DEFAULT_BASELINE_PATH: Path = Path(__file__).with_name("baseline_ragdoll.yaml")


def _repo_root() -> Path:
    """Return the SlapPyEngine repository root.

    ``__file__`` lives at ``<repo>/python/pharos_engine/perf/tripwire.py``,
    so three ``.parent`` hops land on the repo root.
    """
    return Path(__file__).resolve().parents[3]


def _demo_path() -> Path:
    """Absolute path to the read-only ``hello_ragdoll.py`` example."""
    return _repo_root() / "SlapPyEngineExamples" / "examples" / "hello_ragdoll.py"


def _load_demo() -> Any:
    """Import the ``hello_ragdoll.py`` file as a module without touching sys.path."""
    demo_path = _demo_path()
    if not demo_path.exists():
        raise FileNotFoundError(
            f"hello_ragdoll demo not found at {demo_path}"
        )
    spec = importlib.util.spec_from_file_location(
        "pharos_engine_perf_hello_ragdoll", demo_path
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"could not spec-load {demo_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git_sha() -> str:
    """Return the short git SHA of ``HEAD`` or ``"unknown"``.

    Uses ``git rev-parse --short HEAD``. Never raises — the tripwire
    must survive a detached-worktree / non-git deploy without dying.
    """
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_repo_root()),
            stderr=subprocess.DEVNULL,
            timeout=5.0,
        )
    except Exception:  # pragma: no cover - defensive git guard
        return "unknown"
    return out.decode("utf-8", errors="replace").strip() or "unknown"


def _now_iso() -> str:
    """UTC ISO-8601 timestamp with second precision."""
    return _dt.datetime.now(tz=_dt.timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class PerfResult:
    """One benchmark run's summary statistics.

    Attributes
    ----------
    demo:
        Name of the demo that was benched. Always ``"hello_ragdoll"``
        for :meth:`PerfTripwire.run_ragdoll_bench`, but kept as a field
        so the schema is future-proof for more demos.
    steps:
        Number of measured ``world.step`` calls **per trial** (warmup
        excluded).
    trials:
        Number of independent trial runs; every trial rebuilds the
        world from scratch to avoid caching between trials.
    mean_ms:
        Arithmetic mean of every measured per-frame duration across all
        trials, in milliseconds.
    median_ms:
        Median of every measured per-frame duration across all trials.
    p95_ms:
        95th percentile of every measured per-frame duration.
    p99_ms:
        99th percentile of every measured per-frame duration.
    total_ms:
        Wall-clock time spent in the measured phase (excluding warmup)
        across all trials.
    commit_sha:
        ``git rev-parse --short HEAD`` at capture time, or
        ``"unknown"`` when git is unavailable.
    timestamp:
        UTC ISO-8601 timestamp with second precision.
    """

    demo: str
    steps: int
    trials: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    p99_ms: float
    total_ms: float
    commit_sha: str
    timestamp: str

    #: The metrics compared field-by-field in :meth:`PerfTripwire.compare`.
    _METRIC_FIELDS: tuple[str, ...] = field(
        default=("mean_ms", "median_ms", "p95_ms", "p99_ms"),
        repr=False,
        compare=False,
    )

    def to_dict(self) -> dict[str, Any]:
        """Return the plain-dict form used for YAML serialisation."""
        d = asdict(self)
        d.pop("_METRIC_FIELDS", None)
        return d

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PerfResult":
        """Reconstruct a :class:`PerfResult` from ``to_dict`` output.

        Extra keys are ignored so future schema additions don't
        break older tripwires; missing keys raise :class:`KeyError`
        with the specific field name.
        """
        required = (
            "demo", "steps", "trials", "mean_ms", "median_ms",
            "p95_ms", "p99_ms", "total_ms", "commit_sha", "timestamp",
        )
        for key in required:
            if key not in data:
                raise KeyError(f"PerfResult missing required field: {key!r}")
        return cls(
            demo=str(data["demo"]),
            steps=int(data["steps"]),
            trials=int(data["trials"]),
            mean_ms=float(data["mean_ms"]),
            median_ms=float(data["median_ms"]),
            p95_ms=float(data["p95_ms"]),
            p99_ms=float(data["p99_ms"]),
            total_ms=float(data["total_ms"]),
            commit_sha=str(data["commit_sha"]),
            timestamp=str(data["timestamp"]),
        )


@dataclass
class ComparisonReport:
    """Outcome of comparing a fresh :class:`PerfResult` to a baseline.

    Attributes
    ----------
    passed:
        ``True`` iff every metric stays within the tolerance band.
    deltas:
        Signed relative delta per metric (``current / baseline - 1.0``).
        Positive == slower, negative == faster.
    regressed_metrics:
        Names of metrics whose delta exceeded ``tolerance_pct``.
    improvements:
        Names of metrics whose speedup exceeded 5%.
    tolerance_pct:
        The tolerance band applied. Recorded so a printed report can
        say "within +/- 15%" without re-plumbing state through the CLI.
    """

    passed: bool
    deltas: dict[str, float]
    regressed_metrics: list[str]
    improvements: list[str]
    tolerance_pct: float = 15.0

    def format_table(self) -> str:
        """Return a monospace table that lines up per-metric deltas.

        The output is deliberately terminal-friendly (no ANSI colour):
        the CLI wraps this in a pass/fail banner. Column widths are
        fixed so the block aligns even under redirected output.
        """
        header = f"  {'metric':<12} {'delta':>9}  status"
        rule = "  " + "-" * 34
        lines: list[str] = [header, rule]
        for name, delta in self.deltas.items():
            pct = delta * 100.0
            if name in self.regressed_metrics:
                status = "REGRESS"
            elif name in self.improvements:
                status = "faster"
            else:
                status = "ok"
            lines.append(f"  {name:<12} {pct:>+8.2f}%  {status}")
        verdict = "PASS" if self.passed else "FAIL"
        lines.append(rule)
        lines.append(
            f"  verdict: {verdict}  (tolerance +/- {self.tolerance_pct:.1f}%)"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _percentile(samples: list[float], q: float) -> float:
    """Compute a percentile with linear interpolation, no numpy dep.

    ``q`` is in [0.0, 1.0]. Empty input raises :class:`ValueError`.
    Matches ``numpy.percentile`` closely enough for the tripwire
    (nearest-rank on tiny samples, linear on bigger ones).
    """
    if not samples:
        raise ValueError("percentile of empty sample")
    if len(samples) == 1:
        return float(samples[0])
    q = max(0.0, min(1.0, float(q)))
    ordered = sorted(samples)
    pos = q * (len(ordered) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


class PerfTripwire:
    """Run the ``hello_ragdoll`` bench and manage baseline comparisons.

    The class is intentionally stateless — every entry point takes the
    parameters it needs — so a caller can share one instance between
    the CLI, the pytest suite, and an ad-hoc REPL exploration.
    """

    #: Default tolerance percentage used by :meth:`compare` when the
    #: caller does not pass ``tolerance_pct`` explicitly.
    DEFAULT_TOLERANCE_PCT: float = 15.0

    #: Threshold below which a negative delta counts as an "improvement".
    IMPROVEMENT_THRESHOLD_PCT: float = 5.0

    # ------------------------------------------------------------------
    # Bench
    # ------------------------------------------------------------------

    def run_ragdoll_bench(
        self,
        *,
        steps: int = 60,
        warmup: int = 10,
        trials: int = 3,
        dt: float = DEFAULT_DT,
    ) -> PerfResult:
        """Time ``world.step`` on the ``hello_ragdoll`` demo.

        Each trial builds a fresh world via ``demo.build_world`` and then
        runs ``warmup`` unmeasured steps (JIT / numpy allocator warmup)
        followed by ``steps`` measured steps. The per-frame duration is
        recorded with :func:`time.perf_counter_ns`.

        Parameters
        ----------
        steps:
            Measured steps per trial. Must be ``>= 1``.
        warmup:
            Unmeasured warmup steps per trial. Must be ``>= 0``.
        trials:
            Number of independent trials. Must be ``>= 1``. Every trial
            starts from a fresh world so cache effects don't compound.
        dt:
            Fixed integration timestep. Defaults to the demo's own
            ``DEFAULT_DT`` (1/60 s).

        Returns
        -------
        PerfResult
            Aggregated stats across every measured frame.

        Raises
        ------
        ValueError
            If ``steps`` or ``trials`` is not positive, or ``warmup`` is
            negative.
        """
        if steps < 1:
            raise ValueError(f"steps must be >= 1, got {steps}")
        if warmup < 0:
            raise ValueError(f"warmup must be >= 0, got {warmup}")
        if trials < 1:
            raise ValueError(f"trials must be >= 1, got {trials}")

        demo = _load_demo()
        durations_ms: list[float] = []
        total_ns = 0

        for _ in range(trials):
            world, body, _spec = demo.build_world()

            # Warmup — unmeasured, results discarded but keep the ground
            # clamp in the loop so warmup and measurement follow the
            # exact same code path.
            for _ in range(warmup):
                world.step(dt)
                demo._ground_clamp(world)

            # Measured phase.
            for _ in range(steps):
                t0 = time.perf_counter_ns()
                world.step(dt)
                demo._ground_clamp(world)
                t1 = time.perf_counter_ns()
                dur_ns = t1 - t0
                total_ns += dur_ns
                durations_ms.append(dur_ns / 1_000_000.0)

        mean_ms = statistics.fmean(durations_ms)
        median_ms = statistics.median(durations_ms)
        p95_ms = _percentile(durations_ms, 0.95)
        p99_ms = _percentile(durations_ms, 0.99)
        total_ms = total_ns / 1_000_000.0

        return PerfResult(
            demo=DEMO_NAME,
            steps=int(steps),
            trials=int(trials),
            mean_ms=float(mean_ms),
            median_ms=float(median_ms),
            p95_ms=float(p95_ms),
            p99_ms=float(p99_ms),
            total_ms=float(total_ms),
            commit_sha=_git_sha(),
            timestamp=_now_iso(),
        )

    # ------------------------------------------------------------------
    # YAML I/O
    # ------------------------------------------------------------------

    def write_baseline(
        self, result: PerfResult, path: Path | str = DEFAULT_BASELINE_PATH
    ) -> Path:
        """Persist ``result`` as YAML at ``path``. Returns the written path.

        Parent directories are created on demand. The file is written
        with a stable key order and a short banner comment so a diff
        against a previous baseline is human-readable.
        """
        if _yaml is None:  # pragma: no cover - pyyaml is a hard repo dep
            raise RuntimeError("pyyaml is required for baseline I/O")
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = result.to_dict()
        header = (
            "# SlapPyEngine perf tripwire baseline for hello_ragdoll.\n"
            "# Regenerate with: python -m pharos_engine.perf.tripwire --write-baseline\n"
        )
        body = _yaml.safe_dump(payload, sort_keys=True, default_flow_style=False)
        out.write_text(header + body, encoding="utf-8")
        return out

    def read_baseline(
        self, path: Path | str = DEFAULT_BASELINE_PATH
    ) -> PerfResult:
        """Load a :class:`PerfResult` from a YAML baseline.

        Raises :class:`FileNotFoundError` when the file is absent so
        the CLI can surface a specific "missing baseline" error.
        """
        if _yaml is None:  # pragma: no cover
            raise RuntimeError("pyyaml is required for baseline I/O")
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"perf baseline not found: {p}")
        raw = p.read_text(encoding="utf-8")
        data = _yaml.safe_load(raw)
        if not isinstance(data, Mapping):
            raise ValueError(
                f"perf baseline {p} did not decode to a mapping: {type(data).__name__}"
            )
        return PerfResult.from_dict(data)

    # ------------------------------------------------------------------
    # Comparison
    # ------------------------------------------------------------------

    def compare(
        self,
        current: PerfResult,
        baseline: PerfResult,
        tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    ) -> ComparisonReport:
        """Compare ``current`` against ``baseline`` metric-by-metric.

        A metric is a regression iff
        ``current / baseline - 1.0 > tolerance_pct / 100``.
        A metric is an improvement iff the delta drops below
        ``-IMPROVEMENT_THRESHOLD_PCT / 100``.

        The overall ``passed`` flag is the AND of "no regressed
        metrics" across every field in
        :attr:`PerfResult._METRIC_FIELDS`.
        """
        tol = float(tolerance_pct) / 100.0
        improve = self.IMPROVEMENT_THRESHOLD_PCT / 100.0

        # Prefer the class-level metric list — the private attribute on
        # the dataclass instance is a tuple field but instance access
        # still returns it.
        metric_fields: Iterable[str] = current._METRIC_FIELDS  # type: ignore[assignment]

        deltas: dict[str, float] = {}
        regressed: list[str] = []
        improved: list[str] = []

        for name in metric_fields:
            cur = float(getattr(current, name))
            base = float(getattr(baseline, name))
            if base <= 0.0:
                # Degenerate baseline — treat as pass so we don't
                # falsely fail on a broken record.
                deltas[name] = 0.0
                continue
            delta = (cur / base) - 1.0
            deltas[name] = float(delta)
            if delta > tol:
                regressed.append(name)
            elif delta < -improve:
                improved.append(name)

        passed = not regressed
        return ComparisonReport(
            passed=passed,
            deltas=deltas,
            regressed_metrics=regressed,
            improvements=improved,
            tolerance_pct=float(tolerance_pct),
        )


# ---------------------------------------------------------------------------
# Module CLI dispatch
# ---------------------------------------------------------------------------

def _main(argv: list[str] | None = None) -> int:  # pragma: no cover
    """Delegate to :mod:`pharos_engine.perf.cli`.

    Kept here so ``python -m pharos_engine.perf.tripwire`` works even
    though the argparse plumbing lives in ``cli.py``.
    """
    from .cli import main as _cli_main

    return _cli_main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_main())
