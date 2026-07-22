"""Sprint 10 perf regression gate.

Compares a live perf-run JSON (`current.json`) against the checked-in
`tests/perf_baseline.json`. Exits non-zero when any metric regresses
by more than the baseline's `regression_threshold_pct` (default 5%).

Higher-is-better metrics: names ending in `_fps`.
Lower-is-better metrics:  names ending in `_ms` or `_pct`.

Usage::

    python scripts/perf_gate.py --current out/perf_run.json
    python scripts/perf_gate.py --current out/perf_run.json --update  # refresh baseline
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "perf_baseline.json"


def _direction(metric_name: str) -> str:
    if metric_name.endswith("_fps"):
        return "higher"
    if metric_name.endswith(("_ms", "_pct")):
        return "lower"
    return "higher"


def _pct_delta(baseline: float, current: float, direction: str) -> float:
    if baseline == 0:
        return 0.0
    if direction == "higher":
        return (current - baseline) / baseline * 100.0
    return (baseline - current) / baseline * 100.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Pharos perf regression gate")
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    parser.add_argument("--update", action="store_true",
                        help="Overwrite the baseline with current results.")
    args = parser.parse_args()

    if not args.baseline.exists():
        raise SystemExit(f"baseline file not found: {args.baseline}")
    if not args.current.exists():
        raise SystemExit(f"current run not found: {args.current}")

    baseline_doc = json.loads(args.baseline.read_text(encoding="utf-8"))
    current_doc = json.loads(args.current.read_text(encoding="utf-8"))
    baseline = baseline_doc.get("metrics", {})
    current = current_doc.get("metrics", {})
    threshold = float(baseline_doc.get("regression_threshold_pct", 5.0))

    regressions: list[tuple[str, float, float, float]] = []
    for name, base_v in baseline.items():
        if name not in current:
            print(f"[skip] {name}: no current sample")
            continue
        cur_v = float(current[name])
        base_v = float(base_v)
        direction = _direction(name)
        delta = _pct_delta(base_v, cur_v, direction)
        marker = "OK " if delta >= -threshold else "BAD"
        print(f"{marker} {name:40s}  baseline={base_v:>10.3f}  current={cur_v:>10.3f}  Δ={delta:+.2f}%")
        if delta < -threshold:
            regressions.append((name, base_v, cur_v, delta))

    if args.update:
        baseline_doc["metrics"] = dict(current)
        args.baseline.write_text(json.dumps(baseline_doc, indent=2) + "\n", encoding="utf-8")
        print(f"updated baseline at {args.baseline}")
        return 0

    if regressions:
        print(f"\nperf_gate: {len(regressions)} regression(s) exceed the {threshold:.1f}% threshold")
        return 1
    print("\nperf_gate: all metrics within threshold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
