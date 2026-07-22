"""Unified engine-wide perf dashboard.

Discovers existing ``tools/bench_*.py`` scripts and invokes each as a
subprocess; parses each bench's stdout for measurable numbers
(``ns/emit``, ``ms/frame``, ``ms/call``, ``speedup``, ``MB/s``); also
runs *inline* benches for subsystems that don't have a dedicated script
yet (thermal, topology, numerics, dynamics); composes a single markdown
report at ``docs/perf_dashboard.md`` (or ``--out``).

Design constraints
------------------
* Subprocess timeout per bench: 60 s. Slow benches are recorded as
  ``FAILED`` rather than crashing the dashboard.
* The dashboard markdown is the source of truth; tests assert structure,
  not specific numbers (which vary by machine).
* Run-twice idempotency: pass ``--date <iso>`` to pin the date stamp.
  The body never emits machine timestamps -- only the ``<date>`` slot
  in the header carries a date. For byte-identical regression tests
  also pass ``--mock-metrics`` so measurements are replaced with fixed
  placeholder numbers (real measurements still fluctuate run-to-run by
  a few percent on any modern timer).
* If the previous dashboard exists at ``docs/perf_dashboard_prev.md``
  the trend section diffs medians and reports regressions / wins.

Usage
-----
    cd <worktree-root>
    PYTHONPATH=python python tools/bench_dashboard.py
    PYTHONPATH=python python tools/bench_dashboard.py --out /tmp/dash.md --date 2026-05-29
"""
from __future__ import annotations

import argparse
import gc
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np


# Allow running from the repo root without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PY_SRC = _REPO_ROOT / "python"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
SUBPROCESS_TIMEOUT_S = 60.0

# Patterns the dashboard recognises in subprocess bench stdout. Match the
# first numeric capture in each pattern -- callers see a "kind: value"
# headline per match.
_METRIC_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ns/emit", re.compile(r"([\d,\.]+)\s*ns/emit", re.IGNORECASE)),
    ("ms/frame", re.compile(r"([\d,\.]+)\s*ms/frame", re.IGNORECASE)),
    ("ms/call", re.compile(r"([\d,\.]+)\s*ms/call", re.IGNORECASE)),
    ("us/call", re.compile(r"([\d,\.]+)\s*us/call", re.IGNORECASE)),
    ("speedup", re.compile(r"([\d,\.]+)\s*[xX]\s*(?:speedup|faster)?", re.IGNORECASE)),
    ("MB/s", re.compile(r"([\d,\.]+)\s*MB/s", re.IGNORECASE)),
]


# ---------------------------------------------------------------------------
# Inline bench helpers
# ---------------------------------------------------------------------------
def _median_ns_per_call(fn: Callable[[], None], n_calls: int) -> float:
    """Run ``fn`` ``n_calls`` times and return the median per-call cost in ns."""
    samples: list[float] = []
    # Warm-up to avoid first-call import overhead.
    fn()
    gc.collect()
    for _ in range(n_calls):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        samples.append((t1 - t0) * 1e9)
    return statistics.median(samples)


def bench_inline_thermal() -> dict[str, float | str]:
    """``HeatField.step(dt)`` on a 64x64 grid.

    Returns ``{"name", "scenario", "median_ns", "median_ms", "bound"}``.
    """
    from pharos_engine.thermal import HeatField

    rng = np.random.default_rng(0)
    grid = rng.standard_normal((64, 64)).astype(np.float64)
    field = HeatField(grid, conductivity=1.0, diffusivity=0.1)
    median_ns = _median_ns_per_call(lambda: field.step(0.05), n_calls=30)
    return {
        "subsystem": "thermal",
        "scenario": "HeatField.step on 64x64 grid",
        "median_ns": median_ns,
        "median_ms": median_ns / 1e6,
        "unit": "ms/step",
        "bound": "memory-bound (numpy stencil on 32 KiB grid)",
    }


def bench_inline_topology() -> dict[str, float | str]:
    """``connected_components`` on a 1000-node random graph."""
    from pharos_engine.topology import connected_components

    rng = np.random.default_rng(0xC0FFEE)
    # Sparse-ish: ~2 edges per node so we get a handful of components.
    edges = rng.integers(0, 1000, size=(2000, 2), dtype=np.int64)
    median_ns = _median_ns_per_call(
        lambda: connected_components(1000, edges), n_calls=30,
    )
    return {
        "subsystem": "topology",
        "scenario": "connected_components on 1000-node graph (2000 edges)",
        "median_ns": median_ns,
        "median_ms": median_ns / 1e6,
        "unit": "ms/call",
        "bound": "Python loop-bound (union-find, no vectorisation)",
    }


def bench_inline_numerics() -> dict[str, float | str]:
    """``vcycle_poisson`` on a 64x64 grid, 1 V-cycle."""
    from pharos_engine.numerics import vcycle_poisson

    rng = np.random.default_rng(0xBEEF)
    rhs = rng.standard_normal((64, 64)).astype(np.float32)
    mask = np.ones((64, 64), dtype=bool)
    median_ns = _median_ns_per_call(
        lambda: vcycle_poisson(rhs, mask, n_cycles=1), n_calls=20,
    )
    return {
        "subsystem": "numerics",
        "scenario": "vcycle_poisson on 64x64 grid (1 V-cycle)",
        "median_ns": median_ns,
        "median_ms": median_ns / 1e6,
        "unit": "ms/call",
        "bound": "allocation-bound (per-cycle restrict/prolong scratch arrays)",
    }


def bench_inline_dynamics() -> dict[str, float | str]:
    """``World.step`` on a 100-node lattice. Cites the existing port plan."""
    from pharos_engine.dynamics import JointSpec, World

    world = World(gravity=(0.0, -9.81))
    # 10x10 lattice.
    grid_n = 10
    pos = np.array(
        [(float(i), float(j)) for i in range(grid_n) for j in range(grid_n)],
        dtype=np.float64,
    )
    offset, _ = world.add_nodes(pos, masses=1.0)
    # Wire horizontal, vertical, and both diagonal distance joints -- this
    # is the same "100-node lattice" Scenario C in the port plan.
    def idx(i: int, j: int) -> int:
        return offset + i * grid_n + j

    for i in range(grid_n):
        for j in range(grid_n):
            here = idx(i, j)
            if j + 1 < grid_n:
                world.add_joint(JointSpec(
                    kind="distance",
                    node_a=here, node_b=idx(i, j + 1),
                    params={"rest_length": 1.0, "compliance": 0.0},
                ))
            if i + 1 < grid_n:
                world.add_joint(JointSpec(
                    kind="distance",
                    node_a=here, node_b=idx(i + 1, j),
                    params={"rest_length": 1.0, "compliance": 0.0},
                ))
            if i + 1 < grid_n and j + 1 < grid_n:
                world.add_joint(JointSpec(
                    kind="distance",
                    node_a=here, node_b=idx(i + 1, j + 1),
                    params={"rest_length": float(np.sqrt(2.0)), "compliance": 0.0},
                ))
            if i + 1 < grid_n and j - 1 >= 0:
                world.add_joint(JointSpec(
                    kind="distance",
                    node_a=here, node_b=idx(i + 1, j - 1),
                    params={"rest_length": float(np.sqrt(2.0)), "compliance": 0.0},
                ))
    # Silence the overdamping warning -- our default joints are not damped.
    world.warn_overdamping = False

    median_ns = _median_ns_per_call(lambda: world.step(1.0 / 60.0), n_calls=30)
    return {
        "subsystem": "dynamics",
        "scenario": "World.step on 100-node lattice (~340 joints; cf. port plan Scenario C)",
        "median_ns": median_ns,
        "median_ms": median_ns / 1e6,
        "unit": "ms/frame",
        "bound": "Python-loop-bound (per-joint numpy.linalg.norm; see docs/rust_port_plan_dynamics.md)",
    }


INLINE_BENCHES: list[Callable[[], dict[str, float | str]]] = [
    bench_inline_thermal,
    bench_inline_topology,
    bench_inline_numerics,
    bench_inline_dynamics,
]


# Mock results -- fixed numbers used when --mock-metrics is passed. Kept
# in roughly the right magnitude range so the markdown still reads as a
# plausible report card, but identical run-to-run so regression tests can
# assert byte equality.
_MOCK_INLINE_RESULTS: list[dict[str, float | str]] = [
    {
        "subsystem": "thermal",
        "scenario": "HeatField.step on 64x64 grid",
        "median_ns": 34_000.0,
        "median_ms": 0.034,
        "unit": "ms/step",
        "bound": "memory-bound (numpy stencil on 32 KiB grid)",
    },
    {
        "subsystem": "topology",
        "scenario": "connected_components on 1000-node graph (2000 edges)",
        "median_ns": 2_100_000.0,
        "median_ms": 2.100,
        "unit": "ms/call",
        "bound": "Python loop-bound (union-find, no vectorisation)",
    },
    {
        "subsystem": "numerics",
        "scenario": "vcycle_poisson on 64x64 grid (1 V-cycle)",
        "median_ns": 760_000.0,
        "median_ms": 0.760,
        "unit": "ms/call",
        "bound": "allocation-bound (per-cycle restrict/prolong scratch arrays)",
    },
    {
        "subsystem": "dynamics",
        "scenario": "World.step on 100-node lattice (~340 joints; cf. port plan Scenario C)",
        "median_ns": 12_000_000.0,
        "median_ms": 12.000,
        "unit": "ms/frame",
        "bound": "Python-loop-bound (per-joint numpy.linalg.norm; see docs/rust_port_plan_dynamics.md)",
    },
]


_MOCK_SUBPROCESS_RESULTS: list[dict[str, object]] = [
    {
        "subsystem": "telemetry",
        "status": "OK",
        "scenario": "bench_telemetry.py",
        "metrics": {"ns/emit": [30_000.0]},
        "bound": "allocation-bound (per-emit list / dict ops dominate)",
        "median_repr": "30,000 ns/emit",
        "unit": "ns/emit",
    },
    {
        "subsystem": "zones",
        "status": "OK",
        "scenario": "bench_zones.py",
        "metrics": {"speedup": [9.00]},
        "bound": "vectorised numpy-bound (small spatial-hash buckets)",
        "median_repr": "9.00x speedup",
        "unit": "speedup",
    },
]


# ---------------------------------------------------------------------------
# Subprocess bench discovery + parsing
# ---------------------------------------------------------------------------
def discover_bench_scripts(tools_dir: Path) -> list[Path]:
    """Find ``tools/bench_*.py`` scripts (excluding this dashboard)."""
    scripts: list[Path] = []
    for path in sorted(tools_dir.glob("bench_*.py")):
        if path.name == "bench_dashboard.py":
            continue
        scripts.append(path)
    return scripts


def _parse_metrics(stdout: str) -> dict[str, list[float]]:
    """Pull every recognised metric out of the bench stdout.

    Returns a dict ``{metric_kind: [values...]}`` -- callers reduce to a
    median for the at-a-glance row.
    """
    found: dict[str, list[float]] = {}
    for kind, pat in _METRIC_PATTERNS:
        for m in pat.finditer(stdout):
            try:
                v = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            # Filter the "1.0x" speedup noise -- need at least one digit
            # after the decimal or > 1 to count as a real speedup figure.
            if kind == "speedup" and v == 1.0:
                continue
            found.setdefault(kind, []).append(v)
    return found


def _bound_class(name: str, metrics: dict[str, list[float]]) -> str:
    """Best-effort classification of what's bounding the scenario.

    Heuristics are deliberately coarse -- the dashboard reports
    structure, not a profile.
    """
    if not metrics:
        return "no metrics parsed"
    if "ns/emit" in metrics:
        median = statistics.median(metrics["ns/emit"])
        if median < 200:
            return "dispatch-bound (sub-200 ns/emit hot path)"
        if median < 2000:
            return "callback-bound (per-subscriber dispatch dominates)"
        return "allocation-bound (per-emit list / dict ops dominate)"
    if "ms/frame" in metrics:
        return "Python loop-bound (per-frame interpreter overhead)"
    if "us/call" in metrics:
        median = statistics.median(metrics["us/call"])
        if median < 100:
            return "vectorised numpy-bound (small spatial-hash buckets)"
        return "allocation-bound (per-call array constructions)"
    if "ms/call" in metrics:
        return "allocation-bound (per-call scratch buffers)"
    return "uncategorised"


def run_subprocess_bench(
    script: Path,
    timeout_s: float = SUBPROCESS_TIMEOUT_S,
) -> dict[str, object]:
    """Invoke ``python <script>`` and capture its stdout for parsing."""
    env = os.environ.copy()
    py_src = str(_PY_SRC)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        py_src + (os.pathsep + existing if existing else "")
    )
    name = script.stem.replace("bench_", "")
    try:
        result = subprocess.run(
            [sys.executable, str(script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "subsystem": name,
            "status": "FAILED",
            "scenario": f"{script.name} timed out after {timeout_s:.0f}s",
            "metrics": {},
            "bound": "FAILED",
            "median_repr": "FAILED",
            "unit": "n/a",
        }
    except OSError as exc:  # pragma: no cover - depends on host
        return {
            "subsystem": name,
            "status": "FAILED",
            "scenario": f"{script.name}: {exc}",
            "metrics": {},
            "bound": "FAILED",
            "median_repr": "FAILED",
            "unit": "n/a",
        }

    if result.returncode != 0:
        return {
            "subsystem": name,
            "status": "FAILED",
            "scenario": f"{script.name} exited rc={result.returncode}",
            "metrics": {},
            "bound": "FAILED",
            "median_repr": "FAILED",
            "unit": "n/a",
        }

    stdout = result.stdout.decode("utf-8", errors="replace")
    metrics = _parse_metrics(stdout)

    # Choose a headline metric for the at-a-glance table.
    if "ns/emit" in metrics:
        median = statistics.median(metrics["ns/emit"])
        median_repr = f"{median:,.0f} ns/emit"
        unit = "ns/emit"
    elif "ms/frame" in metrics:
        median = statistics.median(metrics["ms/frame"])
        median_repr = f"{median:.3f} ms/frame"
        unit = "ms/frame"
    elif "ms/call" in metrics:
        median = statistics.median(metrics["ms/call"])
        median_repr = f"{median:.3f} ms/call"
        unit = "ms/call"
    elif "us/call" in metrics:
        median = statistics.median(metrics["us/call"])
        median_repr = f"{median:.1f} us/call"
        unit = "us/call"
    elif "speedup" in metrics:
        median = statistics.median(metrics["speedup"])
        median_repr = f"{median:.2f}x speedup"
        unit = "speedup"
    else:
        median_repr = "no metric parsed"
        unit = "n/a"

    return {
        "subsystem": name,
        "status": "OK",
        "scenario": script.name,
        "metrics": metrics,
        "bound": _bound_class(name, metrics),
        "median_repr": median_repr,
        "unit": unit,
    }


# ---------------------------------------------------------------------------
# Markdown composition
# ---------------------------------------------------------------------------
def _format_inline_row(result: dict[str, float | str]) -> str:
    name = str(result["subsystem"])
    scenario = str(result["scenario"])
    unit = str(result["unit"])
    median_ms = float(result["median_ms"])
    if unit == "ms/step":
        repr_ = f"{median_ms:.3f} ms/step"
    elif unit == "ms/frame":
        repr_ = f"{median_ms:.3f} ms/frame"
    elif unit == "ms/call":
        repr_ = f"{median_ms:.3f} ms/call"
    else:
        repr_ = f"{median_ms:.3f} ms"
    bound = str(result["bound"])
    return f"| {name} | {scenario} | {repr_} | {bound} |"


def _format_subprocess_row(result: dict[str, object]) -> str:
    name = str(result["subsystem"])
    scenario = str(result["scenario"])
    repr_ = str(result["median_repr"])
    bound = str(result["bound"])
    return f"| {name} | {scenario} | {repr_} | {bound} |"


def _slowest_inline(inline: list[dict[str, float | str]]) -> dict[str, float | str]:
    """Return the inline row with the largest median_ms."""
    return max(inline, key=lambda r: float(r["median_ms"]))


def _fastest_inline(inline: list[dict[str, float | str]]) -> dict[str, float | str]:
    return min(inline, key=lambda r: float(r["median_ms"]))


def _parse_prev_table(prev_md: str) -> dict[str, str]:
    """Parse the previous dashboard's at-a-glance table.

    Returns ``{subsystem: median_repr}`` so the trend section can compare
    headline metrics without re-parsing the whole markdown.
    """
    by_name: dict[str, str] = {}
    in_table = False
    for line in prev_md.splitlines():
        stripped = line.strip()
        if stripped.startswith("| subsystem | scenario | median |"):
            in_table = True
            continue
        if in_table:
            if not stripped.startswith("|"):
                break
            if stripped.startswith("|---"):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if len(cells) >= 3:
                by_name[cells[0]] = cells[2]
    return by_name


def _extract_first_number(s: str) -> float | None:
    m = re.search(r"([\d,]+\.?\d*)", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


def _trend_lines(
    current_rows: list[tuple[str, str]],
    prev_path: Path,
) -> list[str]:
    if not prev_path.is_file():
        return ["_No previous dashboard at `docs/perf_dashboard_prev.md` -- skipping trend._"]
    prev = _parse_prev_table(prev_path.read_text(encoding="utf-8"))
    if not prev:
        return ["_Previous dashboard at `docs/perf_dashboard_prev.md` has no parseable summary table -- skipping trend._"]
    lines: list[str] = []
    regressions: list[str] = []
    improvements: list[str] = []
    unchanged: list[str] = []
    for name, repr_ in current_rows:
        old_repr = prev.get(name)
        if old_repr is None:
            lines.append(f"* `{name}`: NEW (no prior datapoint).")
            continue
        old_v = _extract_first_number(old_repr)
        new_v = _extract_first_number(repr_)
        if old_v is None or new_v is None or old_v == 0.0:
            unchanged.append(f"`{name}`: {old_repr} -> {repr_} (no comparable number)")
            continue
        delta = (new_v - old_v) / old_v * 100.0
        # >10% slower is a regression; >10% faster is a win.
        if delta > 10.0:
            regressions.append(f"`{name}`: {old_repr} -> {repr_} ({delta:+.1f}%)")
        elif delta < -10.0:
            improvements.append(f"`{name}`: {old_repr} -> {repr_} ({delta:+.1f}%)")
        else:
            unchanged.append(f"`{name}`: {old_repr} -> {repr_} ({delta:+.1f}%)")
    if regressions:
        lines.append("**Regressions (>10% slower):**")
        for r in regressions:
            lines.append(f"* {r}")
    if improvements:
        lines.append("")
        lines.append("**Improvements (>10% faster):**")
        for i in improvements:
            lines.append(f"* {i}")
    if unchanged:
        lines.append("")
        lines.append("**Unchanged (within +/-10%):**")
        for u in unchanged:
            lines.append(f"* {u}")
    return lines


def compose_markdown(
    inline_results: list[dict[str, float | str]],
    subprocess_results: list[dict[str, object]],
    *,
    date: str,
    prev_path: Path,
) -> str:
    lines: list[str] = []
    lines.append(f"# SlapPyEngine perf dashboard -- {date}")
    lines.append("")

    lines.append("## At a glance")
    lines.append("")
    lines.append("| subsystem | scenario | median | bound |")
    lines.append("|---|---|---|---|")

    # Stable ordering: inline benches first (alphabetical), then subprocess
    # benches (also alphabetical). Stable order is what makes
    # ``--date`` pinning sufficient for byte-identical idempotency.
    inline_sorted = sorted(inline_results, key=lambda r: str(r["subsystem"]))
    subprocess_sorted = sorted(subprocess_results, key=lambda r: str(r["subsystem"]))

    summary_rows: list[tuple[str, str]] = []
    for r in inline_sorted:
        lines.append(_format_inline_row(r))
        median_ms = float(r["median_ms"])
        unit = str(r["unit"])
        if unit == "ms/step":
            repr_ = f"{median_ms:.3f} ms/step"
        elif unit == "ms/frame":
            repr_ = f"{median_ms:.3f} ms/frame"
        elif unit == "ms/call":
            repr_ = f"{median_ms:.3f} ms/call"
        else:
            repr_ = f"{median_ms:.3f} ms"
        summary_rows.append((str(r["subsystem"]), repr_))
    for r in subprocess_sorted:
        lines.append(_format_subprocess_row(r))
        summary_rows.append((str(r["subsystem"]), str(r["median_repr"])))

    lines.append("")
    lines.append("## Hot paths")
    lines.append("")
    if inline_sorted:
        fastest = _fastest_inline(inline_sorted)
        slowest = _slowest_inline(inline_sorted)
        lines.append(
            f"* **Fastest inline subsystem:** `{fastest['subsystem']}` "
            f"at {float(fastest['median_ms']):.3f} ms ({fastest['bound']})."
        )
        lines.append(
            f"* **Slowest inline subsystem:** `{slowest['subsystem']}` "
            f"at {float(slowest['median_ms']):.3f} ms ({slowest['bound']})."
        )
    failed = [r for r in subprocess_sorted if r.get("status") == "FAILED"]
    if failed:
        names = ", ".join(f"`{r['subsystem']}`" for r in failed)
        lines.append(f"* **FAILED subprocess benches:** {names}.")
    lines.append(
        "* **Rust ports planned:** `dynamics.World.step` is the engine's "
        "current Python-loop hotspot (see `docs/rust_port_plan_dynamics.md` "
        "-- 100-node lattice spends ~12 ms/frame in pure Python, ~85% in "
        "`_project_distance`). Port lands as part of the dynamics Phase 1 MVP."
    )

    lines.append("")
    lines.append("## Trend")
    lines.append("")
    for line in _trend_lines(summary_rows, prev_path):
        lines.append(line)

    # Trailing newline so the file ends cleanly.
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def run_dashboard(
    out_path: Path,
    *,
    date: str,
    tools_dir: Path | None = None,
    prev_path: Path | None = None,
    mock_metrics: bool = False,
) -> Path:
    """Run all benches and write the markdown report to ``out_path``.

    Parameters
    ----------
    mock_metrics
        If ``True`` skip the real measurements and use fixed
        :data:`_MOCK_INLINE_RESULTS` / :data:`_MOCK_SUBPROCESS_RESULTS`
        instead. Used by the regression tests to assert byte-identical
        output run-to-run (real measurements always fluctuate by a few
        percent on any modern timer).
    """
    tools_dir = tools_dir or (_REPO_ROOT / "tools")
    prev_path = prev_path or (_REPO_ROOT / "docs" / "perf_dashboard_prev.md")

    if mock_metrics:
        inline_results = list(_MOCK_INLINE_RESULTS)
        subprocess_results = list(_MOCK_SUBPROCESS_RESULTS)
    else:
        inline_results = [fn() for fn in INLINE_BENCHES]
        scripts = discover_bench_scripts(tools_dir)
        subprocess_results = [run_subprocess_bench(s) for s in scripts]

    md = compose_markdown(
        inline_results,
        subprocess_results,
        date=date,
        prev_path=prev_path,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    return out_path


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run all engine subsystem benches and emit a unified markdown dashboard.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "docs" / "perf_dashboard.md",
        help="Output markdown path (default: docs/perf_dashboard.md).",
    )
    parser.add_argument(
        "--date",
        default=time.strftime("%Y-%m-%d"),
        help="Date stamp used in the header (default: today). Pin this for byte-identical idempotency.",
    )
    parser.add_argument(
        "--prev",
        type=Path,
        default=_REPO_ROOT / "docs" / "perf_dashboard_prev.md",
        help="Previous dashboard to diff for the trend section.",
    )
    parser.add_argument(
        "--mock-metrics",
        action="store_true",
        help="Skip real measurements and emit fixed placeholder numbers (used by regression tests for byte-identical idempotency).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    out = run_dashboard(
        args.out,
        date=args.date,
        prev_path=args.prev,
        mock_metrics=args.mock_metrics,
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
