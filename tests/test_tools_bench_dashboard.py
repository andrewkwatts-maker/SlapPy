"""Tests for ``tools/bench_dashboard.py``.

The dashboard is the source of truth for engine-wide perf trends; these
tests assert *structure*, not specific timing numbers (which fluctuate
machine-to-machine and run-to-run). The byte-identical idempotency check
relies on the ``--mock-metrics`` mode that replaces real timer reads
with fixed placeholder values.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import bench_dashboard  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run(out_path: Path, *, date: str = "2026-05-29", mock: bool = True,
         prev: Path | None = None) -> str:
    """Invoke ``bench_dashboard.run_dashboard`` and return the markdown."""
    if prev is None:
        # Point at a file that does not exist so the trend section is
        # the deterministic "no previous dashboard" branch.
        prev = out_path.parent / "no_such_file.md"
    bench_dashboard.run_dashboard(
        out_path,
        date=date,
        prev_path=prev,
        mock_metrics=mock,
    )
    return out_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Required tests
# ---------------------------------------------------------------------------
def test_dashboard_writes_markdown(tmp_path: Path) -> None:
    """Running the dashboard creates ``docs/perf_dashboard.md`` (or --out)."""
    out = tmp_path / "perf_dashboard.md"
    bench_dashboard.run_dashboard(
        out,
        date="2026-05-29",
        prev_path=tmp_path / "missing.md",
        mock_metrics=True,
    )
    assert out.is_file()
    body = out.read_text(encoding="utf-8")
    assert body.startswith("# SlapPyEngine perf dashboard -- 2026-05-29")
    # Must end with a trailing newline -- the dashboard is a unix-style
    # text file and we want diffs to be clean.
    assert body.endswith("\n")


def test_dashboard_includes_all_subsystems(tmp_path: Path) -> None:
    """Markdown mentions thermal, topology, numerics, dynamics, telemetry, zones."""
    out = tmp_path / "perf_dashboard.md"
    body = _run(out)
    for subsystem in (
        "thermal",
        "topology",
        "numerics",
        "dynamics",
        "telemetry",
        "zones",
    ):
        assert subsystem in body, f"missing subsystem {subsystem!r} in dashboard"


def test_dashboard_has_summary_table(tmp_path: Path) -> None:
    """Markdown contains the at-a-glance table header."""
    out = tmp_path / "perf_dashboard.md"
    body = _run(out)
    assert "## At a glance" in body
    # Table header row -- subsystem | scenario | median | bound.
    assert "| subsystem | scenario | median | bound |" in body
    assert "|---|---|---|---|" in body


def test_dashboard_idempotent(tmp_path: Path) -> None:
    """Two runs with ``--date 2026-05-29 --mock-metrics`` are byte-identical."""
    out1 = tmp_path / "a.md"
    out2 = tmp_path / "b.md"
    body1 = _run(out1)
    body2 = _run(out2)
    assert body1 == body2, "dashboard output drifted between two mocked runs"
    # And there must be no machine timestamp anywhere in the body besides
    # the pinned date stamp.
    assert body1.count("2026-05-29") == 1
    assert "time.strftime" not in body1


def test_individual_bench_inline_thermal() -> None:
    """The inline thermal bench function runs without error."""
    result = bench_dashboard.bench_inline_thermal()
    assert result["subsystem"] == "thermal"
    assert result["unit"] == "ms/step"
    assert isinstance(result["median_ns"], float)
    assert result["median_ns"] > 0.0


# ---------------------------------------------------------------------------
# Extra coverage (cheap, no new bench scripts)
# ---------------------------------------------------------------------------
def test_dashboard_hot_paths_names_slowest_and_fastest(tmp_path: Path) -> None:
    """Hot-paths section identifies the slowest inline subsystem."""
    out = tmp_path / "perf_dashboard.md"
    body = _run(out)
    assert "## Hot paths" in body
    assert "Fastest inline subsystem" in body
    assert "Slowest inline subsystem" in body
    # The mock numbers make dynamics the slowest (12 ms/frame).
    assert "Slowest inline subsystem:** `dynamics`" in body


def test_dashboard_trend_skipped_when_no_prev(tmp_path: Path) -> None:
    """Without a previous dashboard the trend section says so explicitly."""
    out = tmp_path / "perf_dashboard.md"
    body = _run(out)
    assert "## Trend" in body
    assert "No previous dashboard" in body


def test_dashboard_trend_diffs_against_prev(tmp_path: Path) -> None:
    """When a previous dashboard exists the trend section emits a diff."""
    prev = tmp_path / "prev.md"
    # Use the dashboard itself to write a "previous" snapshot.
    _run(prev)
    out = tmp_path / "next.md"
    body = _run(out, prev=prev)
    assert "## Trend" in body
    # All metrics in mocked mode are identical -> unchanged section.
    assert "Unchanged" in body or "Regressions" in body or "Improvements" in body


def test_inline_topology_runs() -> None:
    result = bench_dashboard.bench_inline_topology()
    assert result["subsystem"] == "topology"
    assert result["median_ns"] > 0.0


def test_inline_numerics_runs() -> None:
    result = bench_dashboard.bench_inline_numerics()
    assert result["subsystem"] == "numerics"
    assert result["median_ns"] > 0.0


def test_inline_dynamics_runs() -> None:
    result = bench_dashboard.bench_inline_dynamics()
    assert result["subsystem"] == "dynamics"
    assert result["median_ns"] > 0.0


def test_parse_metrics_recognises_ns_per_emit() -> None:
    metrics = bench_dashboard._parse_metrics(
        "scenario foo: 123.4 ns/emit, 50,000 ns/emit at scale"
    )
    assert "ns/emit" in metrics
    assert 123.4 in metrics["ns/emit"]
    assert 50_000.0 in metrics["ns/emit"]


def test_parse_metrics_recognises_speedup() -> None:
    metrics = bench_dashboard._parse_metrics(
        "spatial hash gives **10.9x** speedup at 1000 entities"
    )
    assert "speedup" in metrics
    assert 10.9 in metrics["speedup"]


def test_discover_bench_scripts_excludes_dashboard(tmp_path: Path) -> None:
    """``bench_dashboard.py`` itself must not be re-invoked as a subprocess."""
    tools = tmp_path
    (tools / "bench_dashboard.py").write_text("# dashboard")
    (tools / "bench_foo.py").write_text("# foo")
    (tools / "bench_bar.py").write_text("# bar")
    (tools / "not_a_bench.py").write_text("# nope")
    scripts = bench_dashboard.discover_bench_scripts(tools)
    names = sorted(p.name for p in scripts)
    assert names == ["bench_bar.py", "bench_foo.py"]


def test_main_writes_to_out(tmp_path: Path) -> None:
    """The ``--out`` flag controls where the markdown is written."""
    out = tmp_path / "custom.md"
    rc = bench_dashboard.main([
        "--out", str(out),
        "--date", "2026-05-29",
        "--mock-metrics",
        "--prev", str(tmp_path / "no_prev.md"),
    ])
    assert rc == 0
    assert out.is_file()
    body = out.read_text(encoding="utf-8")
    assert "2026-05-29" in body


def test_subprocess_bench_failure_recorded(tmp_path: Path) -> None:
    """A bench script that exits non-zero is recorded as FAILED, not crashed."""
    script = tmp_path / "bench_broken.py"
    script.write_text("import sys; sys.exit(1)")
    result = bench_dashboard.run_subprocess_bench(script, timeout_s=10.0)
    assert result["status"] == "FAILED"
    assert result["bound"] == "FAILED"
    assert "broken" in str(result["subsystem"])
