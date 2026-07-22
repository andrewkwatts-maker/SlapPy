"""
Bench :mod:`pharos_engine.telemetry` under high subscriber count.

Scenarios
---------
1.  One subscriber, 100k emits.
2.  100 subscribers all on ``"*"`` (catch-all), 10k emits.
3.  100 subscribers all on ``"physics.*"``, 10k emits to ``"physics.step"``.
4.  1000 subscribers across 10 distinct first-segment patterns, 10k emits
    evenly distributed across those segments. Re-run with the opt-in
    pattern index ON to measure the speedup.
5.  History capacity 0 (off) vs 1000 (default) at zero subscribers, 100k
    emits. Shows the ring-buffer overhead on the no-subscriber path.

Usage
-----
    cd <worktree-root>
    PYTHONPATH=python python tools/bench_telemetry.py

Output is a markdown table on stdout, ready to paste into the design doc.
"""
from __future__ import annotations

import gc
import sys
import time
from pathlib import Path

# Allow running from the repo root without installing the package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_PY_SRC = _REPO_ROOT / "python"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))

from pharos_engine import telemetry  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _reset() -> None:
    """Drop every subscription + reset history + index to a clean state."""
    for handle in list(telemetry._subscribers):
        telemetry.unsubscribe(handle)
    telemetry.set_history_capacity(1000)
    telemetry.clear_history()
    telemetry.enable_pattern_index(False)
    gc.collect()


def _noop(_event: telemetry.TelemetryEvent) -> None:
    pass


def _time_emits(emit_count: int, name_for_i) -> float:
    """Run ``emit_count`` emits, return elapsed wall time in seconds."""
    gc.collect()
    start = time.perf_counter()
    for i in range(emit_count):
        telemetry.emit(name_for_i(i))
    return time.perf_counter() - start


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def scenario_single_subscriber() -> dict:
    _reset()
    telemetry.set_history_capacity(0)  # isolate dispatch cost
    received = [0]

    def cb(_e):
        received[0] += 1

    telemetry.subscribe("physics.step", cb)
    emits = 100_000
    elapsed = _time_emits(emits, lambda i: "physics.step")
    return {
        "name": "1 sub on `physics.step`, 100k emits",
        "subscribers": 1,
        "emits": emits,
        "elapsed_s": elapsed,
        "ns_per_emit": elapsed * 1e9 / emits,
        "callbacks_per_s": received[0] / elapsed if elapsed > 0 else float("inf"),
        "callbacks_total": received[0],
    }


def scenario_100_catchall() -> dict:
    _reset()
    telemetry.set_history_capacity(0)
    received = [0]

    def cb(_e):
        received[0] += 1

    for _ in range(100):
        telemetry.subscribe("*", cb)

    emits = 10_000
    elapsed = _time_emits(emits, lambda i: "physics.step")
    return {
        "name": "100 subs on `*` (catch-all), 10k emits",
        "subscribers": 100,
        "emits": emits,
        "elapsed_s": elapsed,
        "ns_per_emit": elapsed * 1e9 / emits,
        "callbacks_per_s": received[0] / elapsed if elapsed > 0 else float("inf"),
        "callbacks_total": received[0],
    }


def scenario_100_physics() -> dict:
    _reset()
    telemetry.set_history_capacity(0)
    received = [0]

    def cb(_e):
        received[0] += 1

    for _ in range(100):
        telemetry.subscribe("physics.*", cb)

    emits = 10_000
    elapsed = _time_emits(emits, lambda i: "physics.step")
    return {
        "name": "100 subs on `physics.*`, 10k emits",
        "subscribers": 100,
        "emits": emits,
        "elapsed_s": elapsed,
        "ns_per_emit": elapsed * 1e9 / emits,
        "callbacks_per_s": received[0] / elapsed if elapsed > 0 else float("inf"),
        "callbacks_total": received[0],
    }


_SEGMENTS = (
    "physics",
    "render",
    "audio",
    "input",
    "thermal",
    "lighting",
    "asset",
    "scene",
    "ui",
    "ai",
)


def _populate_mixed(index_enabled: bool) -> list:
    telemetry.enable_pattern_index(index_enabled)
    received = [0]

    def cb(_e):
        received[0] += 1

    # 1000 subscribers spread across 10 segments — 100 per bucket.
    for seg in _SEGMENTS:
        for _ in range(100):
            telemetry.subscribe(f"{seg}.*", cb)
    return received


def scenario_1000_mixed(index_enabled: bool) -> dict:
    _reset()
    telemetry.set_history_capacity(0)
    received = _populate_mixed(index_enabled)

    emits = 10_000
    # Cycle through segments so dispatch is evenly distributed.
    segs = _SEGMENTS

    def name_for(i: int) -> str:
        return f"{segs[i % len(segs)]}.step"

    elapsed = _time_emits(emits, name_for)
    return {
        "name": (
            f"1000 subs / 10 patterns, 10k emits ({'INDEX ON' if index_enabled else 'INDEX OFF'})"
        ),
        "subscribers": 1000,
        "emits": emits,
        "elapsed_s": elapsed,
        "ns_per_emit": elapsed * 1e9 / emits,
        "callbacks_per_s": received[0] / elapsed if elapsed > 0 else float("inf"),
        "callbacks_total": received[0],
    }


def scenario_history_off() -> dict:
    _reset()
    telemetry.set_history_capacity(0)
    emits = 100_000
    elapsed = _time_emits(emits, lambda i: "physics.step")
    return {
        "name": "0 subs, history capacity 0, 100k emits (no-op fast path)",
        "subscribers": 0,
        "emits": emits,
        "elapsed_s": elapsed,
        "ns_per_emit": elapsed * 1e9 / emits,
        "callbacks_per_s": 0.0,
        "callbacks_total": 0,
    }


def scenario_history_on_no_subs() -> dict:
    _reset()
    telemetry.set_history_capacity(1000)
    emits = 100_000
    elapsed = _time_emits(emits, lambda i: "physics.step")
    return {
        "name": "0 subs, history capacity 1000, 100k emits (ring buffer only)",
        "subscribers": 0,
        "emits": emits,
        "elapsed_s": elapsed,
        "ns_per_emit": elapsed * 1e9 / emits,
        "callbacks_per_s": 0.0,
        "callbacks_total": 0,
    }


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------
def _format_results(results: list) -> str:
    lines = []
    lines.append("| Scenario | Subs | Emits | Elapsed (s) | ns/emit | callbacks/s |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for r in results:
        cbs_per_s = r["callbacks_per_s"]
        cbs_per_s_str = f"{cbs_per_s:,.0f}" if cbs_per_s > 0 else "—"
        lines.append(
            "| {name} | {subs} | {emits:,} | {elapsed:.4f} | {ns:,.0f} | {cbs} |".format(
                name=r["name"],
                subs=r["subscribers"],
                emits=r["emits"],
                elapsed=r["elapsed_s"],
                ns=r["ns_per_emit"],
                cbs=cbs_per_s_str,
            )
        )
    return "\n".join(lines)


def main() -> int:
    print("# `pharos_engine.telemetry` bench\n")
    print(
        f"Python {sys.version.split()[0]} on {sys.platform}. "
        f"perf_counter resolution {time.get_clock_info('perf_counter').resolution:.0e}s.\n"
    )

    results = [
        scenario_single_subscriber(),
        scenario_100_catchall(),
        scenario_100_physics(),
        scenario_1000_mixed(index_enabled=False),
        scenario_1000_mixed(index_enabled=True),
        scenario_history_off(),
        scenario_history_on_no_subs(),
    ]

    print(_format_results(results))
    print()

    # Speedup summary for the 1000-subscriber scenario.
    off = next(r for r in results if "INDEX OFF" in r["name"])
    on = next(r for r in results if "INDEX ON" in r["name"])
    speedup = off["elapsed_s"] / on["elapsed_s"] if on["elapsed_s"] > 0 else float("inf")
    print(
        f"Index speedup at 1000 mixed-pattern subscribers: "
        f"**{speedup:.2f}x** ({off['ns_per_emit']:,.0f} -> {on['ns_per_emit']:,.0f} ns/emit)"
    )
    _reset()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
