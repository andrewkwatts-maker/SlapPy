"""Command-line entry point for the perf tripwire.

Usage::

    python -m slappyengine.perf.tripwire            # bench + compare + table
    python -m slappyengine.perf.tripwire --write-baseline
    python -m slappyengine.perf.tripwire --steps 30 --trials 2 --tolerance 20

Exit code is ``0`` when the bench stays inside the tolerance band (or
when no baseline is present and ``--write-baseline`` was passed);
``1`` otherwise.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .tripwire import (
    DEFAULT_BASELINE_PATH,
    ComparisonReport,
    PerfResult,
    PerfTripwire,
)


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser used by both CLI + tests."""
    p = argparse.ArgumentParser(
        prog="python -m slappyengine.perf.tripwire",
        description="Bench hello_ragdoll and compare against the baseline.",
    )
    p.add_argument(
        "--steps", type=int, default=60,
        help="measured steps per trial (default: 60)",
    )
    p.add_argument(
        "--warmup", type=int, default=10,
        help="unmeasured warmup steps per trial (default: 10)",
    )
    p.add_argument(
        "--trials", type=int, default=3,
        help="independent trial runs (default: 3)",
    )
    p.add_argument(
        "--tolerance", type=float, default=15.0,
        help="regression tolerance in percent (default: 15)",
    )
    p.add_argument(
        "--baseline", type=Path, default=DEFAULT_BASELINE_PATH,
        help=f"YAML baseline path (default: {DEFAULT_BASELINE_PATH.name})",
    )
    p.add_argument(
        "--write-baseline", action="store_true",
        help="write the current run to --baseline and exit 0",
    )
    return p


def _print_result(result: PerfResult) -> None:
    """Human-readable summary of a fresh bench run."""
    print(f"perf tripwire — {result.demo}")
    print(f"  commit               : {result.commit_sha}")
    print(f"  timestamp            : {result.timestamp}")
    print(f"  trials x steps       : {result.trials} x {result.steps}")
    print(f"  mean per-frame ms    : {result.mean_ms:.4f}")
    print(f"  median per-frame ms  : {result.median_ms:.4f}")
    print(f"  p95 per-frame ms     : {result.p95_ms:.4f}")
    print(f"  p99 per-frame ms     : {result.p99_ms:.4f}")
    print(f"  total measured ms    : {result.total_ms:.2f}")


def _print_comparison(report: ComparisonReport) -> None:
    """Print the comparison table returned by ``PerfTripwire.compare``."""
    print(report.format_table())


def main(argv: list[str] | None = None) -> int:
    """Programmatic entry point for the tripwire CLI.

    Split out from ``if __name__ == "__main__"`` so tests can call it
    directly and inspect the return code.
    """
    args = _build_parser().parse_args(argv)
    tripwire = PerfTripwire()

    try:
        result = tripwire.run_ragdoll_bench(
            steps=args.steps,
            warmup=args.warmup,
            trials=args.trials,
        )
    except Exception as exc:
        print(f"perf tripwire: bench failed: {exc}", file=sys.stderr)
        return 1

    _print_result(result)

    if args.write_baseline:
        written = tripwire.write_baseline(result, args.baseline)
        print(f"  wrote baseline       : {written}")
        return 0

    baseline_path = Path(args.baseline)
    if not baseline_path.exists():
        print(
            f"perf tripwire: baseline missing at {baseline_path}; "
            "rerun with --write-baseline to capture one.",
            file=sys.stderr,
        )
        return 1

    baseline = tripwire.read_baseline(baseline_path)
    report = tripwire.compare(result, baseline, tolerance_pct=args.tolerance)
    _print_comparison(report)
    return 0 if report.passed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
