"""Tests for :mod:`pharos_engine.smoke_runner`.

The runner is deliberately thin, so we exercise it against ``tmp_path``
fixtures that stand in for the real ``PharosEngineExamples/examples``
directory. That keeps every test hermetic and fast — no real hello_ demo
gets spawned except in the two "sanity" tests that opt-in explicitly.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

import pytest
import yaml

from pharos_engine.smoke_runner import (
    DEFAULT_MAX_WORKERS,
    DEFAULT_TIMEOUT_S,
    SKIP_LIST,
    SmokeResult,
    SmokeRunner,
    _cli,
    _count,
    _format_summary,
    _head,
)


# ---------------------------------------------------------------------------
# Fixture: a fake examples directory with a mix of pass/fail/timeout stubs
# ---------------------------------------------------------------------------

_PASSING_STUB = textwrap.dedent(
    """\
    import os, sys
    print("hello from", os.path.basename(__file__))
    print("SLAPPY_HEADLESS=", os.environ.get("SLAPPY_HEADLESS"))
    sys.exit(0)
    """
)

_FAILING_STUB = textwrap.dedent(
    """\
    import sys
    print("boom", file=sys.stderr)
    sys.exit(2)
    """
)

_SLEEPING_STUB = textwrap.dedent(
    """\
    import time
    time.sleep(30)
    """
)


@pytest.fixture
def fake_examples(tmp_path: Path) -> Path:
    """Create a fake examples dir with 12 stub demos.

    * 10 pass (`hello_a` … `hello_j`)
    * 1 fail (``hello_broken``)
    * 1 non-hello file that must be ignored (``other.py``)
    """
    d = tmp_path / "examples"
    d.mkdir()
    for name in "abcdefghij":
        (d / f"hello_{name}.py").write_text(_PASSING_STUB, encoding="utf-8")
    (d / "hello_broken.py").write_text(_FAILING_STUB, encoding="utf-8")
    (d / "other.py").write_text("print('nope')\n", encoding="utf-8")
    return d


# ---------------------------------------------------------------------------
# discover()
# ---------------------------------------------------------------------------

def test_discover_finds_only_hello_files(fake_examples: Path) -> None:
    runner = SmokeRunner()
    found = runner.discover(fake_examples)
    stems = {p.stem for p in found}
    assert all(s.startswith("hello_") for s in stems)
    assert "other" not in stems
    # 10 pass stubs + 1 fail stub
    assert len(found) == 11


def test_discover_returns_sorted(fake_examples: Path) -> None:
    runner = SmokeRunner()
    found = runner.discover(fake_examples)
    assert [p.name for p in found] == sorted(p.name for p in found)


def test_discover_missing_dir_returns_empty(tmp_path: Path) -> None:
    runner = SmokeRunner()
    assert runner.discover(tmp_path / "does-not-exist") == []


def test_discover_default_finds_real_hellos() -> None:
    """The default (unpatched) dir should surface the real repo demos."""
    runner = SmokeRunner()
    found = runner.discover()
    # Soft floor 5, expected floor 10 per task spec.
    assert len(found) >= 5
    assert len(found) >= 10  # every hello_ demo committed in-repo
    stems = {p.stem for p in found}
    # A handful of well-known demos.
    for expected in ("hello_world", "hello_numerics", "hello_topology"):
        assert expected in stems


# ---------------------------------------------------------------------------
# run_one()
# ---------------------------------------------------------------------------

def test_run_one_pass_on_stub(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset())
    result = runner.run_one(fake_examples / "hello_a.py", timeout_s=15)
    assert result.status == "pass"
    assert result.example == "hello_a"
    assert result.error is None
    assert result.duration_s >= 0.0
    # SLAPPY_HEADLESS must have been injected into the child env.
    assert "SLAPPY_HEADLESS= 1" in result.output_head


def test_run_one_fail_on_nonzero_exit(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset())
    result = runner.run_one(fake_examples / "hello_broken.py", timeout_s=15)
    assert result.status == "fail"
    assert "exit code 2" in (result.error or "")


def test_run_one_missing_example(tmp_path: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset())
    result = runner.run_one(tmp_path / "hello_ghost.py", timeout_s=5)
    assert result.status == "fail"
    assert "not found" in (result.error or "")


def test_run_one_honours_skip_list(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset({"hello_a"}))
    result = runner.run_one(fake_examples / "hello_a.py", timeout_s=5)
    assert result.status == "skip"
    assert result.duration_s == 0.0
    assert "SKIP_LIST" in (result.error or "")


def test_run_one_timeout(fake_examples: Path) -> None:
    """A sleeping subprocess is classified as ``timeout``."""
    sleep_path = fake_examples / "hello_sleepy.py"
    sleep_path.write_text(_SLEEPING_STUB, encoding="utf-8")
    runner = SmokeRunner(skip_list=frozenset())
    result = runner.run_one(sleep_path, timeout_s=0.5)
    assert result.status == "timeout"
    assert "timeout" in (result.error or "").lower()
    # Sanity: the runner should have killed the child within a few seconds,
    # not waited the full 30s the stub asked for.
    assert result.duration_s < 10.0


def test_run_one_timeout_via_patch(monkeypatch: pytest.MonkeyPatch, fake_examples: Path) -> None:
    """subprocess.run raising TimeoutExpired flows through cleanly."""
    def _boom(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise subprocess.TimeoutExpired(cmd="fake", timeout=1.0, output="partial-stdout", stderr="")

    monkeypatch.setattr(subprocess, "run", _boom)
    runner = SmokeRunner(skip_list=frozenset())
    result = runner.run_one(fake_examples / "hello_a.py", timeout_s=1.0)
    assert result.status == "timeout"
    assert "partial-stdout" in result.output_head


# ---------------------------------------------------------------------------
# run_all() + run_all_parallel()
# ---------------------------------------------------------------------------

def test_run_all_sequential(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset())
    results = runner.run_all(examples_dir=fake_examples, timeout_s=15)
    assert len(results) == 11
    assert _count(results, "pass") == 10
    assert _count(results, "fail") == 1


def test_run_all_progress_callback(fake_examples: Path) -> None:
    seen: list[tuple[int, int, str]] = []

    def cb(idx: int, total: int, result: SmokeResult) -> None:
        seen.append((idx, total, result.status))

    runner = SmokeRunner(skip_list=frozenset())
    runner.run_all(examples_dir=fake_examples, timeout_s=15, progress=cb)
    assert len(seen) == 11
    # Callback receives (1..N, N) — verify total consistency and 1-based idx.
    assert {s[1] for s in seen} == {11}
    assert seen[0][0] == 1
    assert seen[-1][0] == 11


def test_run_all_parallel_matches_sequential(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset())
    seq = runner.run_all(examples_dir=fake_examples, timeout_s=15)
    par = runner.run_all_parallel(
        examples_dir=fake_examples, max_workers=4, timeout_s=15
    )
    # Same length, same stems (order preserved), same statuses.
    assert [r.example for r in seq] == [r.example for r in par]
    assert [r.status for r in seq] == [r.status for r in par]


def test_run_all_parallel_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "empty-examples"
    empty.mkdir()
    runner = SmokeRunner()
    assert runner.run_all_parallel(examples_dir=empty) == []


def test_run_all_skip_list_honoured(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset({"hello_a", "hello_b"}))
    results = runner.run_all(examples_dir=fake_examples, timeout_s=15)
    by_name = {r.example: r for r in results}
    assert by_name["hello_a"].status == "skip"
    assert by_name["hello_b"].status == "skip"
    assert by_name["hello_c"].status == "pass"


# ---------------------------------------------------------------------------
# format_summary()
# ---------------------------------------------------------------------------

def test_format_summary_contains_glyphs(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset({"hello_a"}))
    results = runner.run_all(examples_dir=fake_examples, timeout_s=15)
    text = runner.format_summary(results, use_color=False)
    # Status glyphs must appear at least once each.
    assert "✔" in text  # pass
    assert "✘" in text  # fail
    assert "–" in text  # skip
    # Header/table structure
    assert "example" in text
    assert "status" in text
    assert "total" in text


def test_format_summary_no_color_has_no_ansi(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset())
    results = runner.run_all(examples_dir=fake_examples, timeout_s=15)
    text = runner.format_summary(results, use_color=False)
    assert "\x1b[" not in text


def test_format_summary_color_has_ansi(fake_examples: Path) -> None:
    runner = SmokeRunner(skip_list=frozenset())
    results = runner.run_all(examples_dir=fake_examples, timeout_s=15)
    text = runner.format_summary(results, use_color=True)
    assert "\x1b[" in text


def test_format_summary_empty() -> None:
    assert "no examples" in _format_summary([], use_color=False).lower()


# ---------------------------------------------------------------------------
# write_report()
# ---------------------------------------------------------------------------

def test_write_report_writes_valid_yaml(
    fake_examples: Path, tmp_path: Path
) -> None:
    runner = SmokeRunner(skip_list=frozenset({"hello_a"}))
    results = runner.run_all(examples_dir=fake_examples, timeout_s=15)
    out = tmp_path / "reports" / "smoke.yml"
    written = runner.write_report(results, out)
    assert written == out
    assert out.exists()

    doc = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert doc["total"] == len(results)
    assert doc["pass"] == _count(results, "pass")
    assert doc["fail"] == _count(results, "fail")
    assert doc["skip"] == _count(results, "skip")
    assert doc["timeout"] == _count(results, "timeout")
    assert isinstance(doc["results"], list)
    assert doc["results"][0]["example"].startswith("hello_")
    assert "generated_at" in doc


def test_write_report_creates_parent_dirs(
    fake_examples: Path, tmp_path: Path
) -> None:
    runner = SmokeRunner(skip_list=frozenset())
    results = [SmokeResult(example="hello_x", status="pass", duration_s=0.1)]
    nested = tmp_path / "a" / "b" / "c" / "smoke.yml"
    runner.write_report(results, nested)
    assert nested.exists()


# ---------------------------------------------------------------------------
# SmokeResult dataclass
# ---------------------------------------------------------------------------

def test_smoke_result_to_dict_roundtrip() -> None:
    r = SmokeResult(
        example="hello_x",
        status="pass",
        duration_s=1.5,
        output_head="hi",
        error=None,
    )
    d = r.to_dict()
    assert d["example"] == "hello_x"
    assert d["status"] == "pass"
    assert d["duration_s"] == 1.5
    assert d["error"] is None


def test_smoke_result_defaults() -> None:
    r = SmokeResult(example="hello_y", status="skip")
    assert r.duration_s == 0.0
    assert r.output_head == ""
    assert r.error is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def test_head_truncates_long_output() -> None:
    text = "x" * 5000
    trimmed = _head(text, n=100)
    assert len(trimmed) <= 200  # 100 + "\n...[truncated]" marker
    assert trimmed.startswith("x" * 100)
    assert "truncated" in trimmed


def test_head_preserves_short_output() -> None:
    assert _head("short", n=100) == "short"
    assert _head("", n=100) == ""


def test_count_matches_status() -> None:
    results = [
        SmokeResult(example="a", status="pass"),
        SmokeResult(example="b", status="pass"),
        SmokeResult(example="c", status="fail"),
        SmokeResult(example="d", status="skip"),
    ]
    assert _count(results, "pass") == 2
    assert _count(results, "fail") == 1
    assert _count(results, "skip") == 1
    assert _count(results, "timeout") == 0


# ---------------------------------------------------------------------------
# Skip-list contents
# ---------------------------------------------------------------------------

def test_skip_list_is_frozenset() -> None:
    assert isinstance(SKIP_LIST, frozenset)


def test_skip_list_includes_known_gpu_demos() -> None:
    # hello_world / hello_physics call engine.run() with no headless path,
    # so they must be pre-skipped.
    for name in ("hello_world", "hello_physics", "hello_pixel", "hello_lighting"):
        assert name in SKIP_LIST


def test_default_timeout_positive() -> None:
    assert DEFAULT_TIMEOUT_S > 0
    assert DEFAULT_MAX_WORKERS >= 1


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def test_cli_returns_zero_on_all_pass(
    fake_examples: Path, capsys: pytest.CaptureFixture, tmp_path: Path
) -> None:
    # Rewrite the fake dir so nothing fails.
    (fake_examples / "hello_broken.py").write_text(_PASSING_STUB, encoding="utf-8")
    report = tmp_path / "report.yml"
    rc = _cli([
        "--examples-dir", str(fake_examples),
        "--timeout", "15",
        "--report", str(report),
        "--no-color",
    ])
    assert rc == 0
    assert report.exists()
    out = capsys.readouterr().out
    assert "pass" in out


def test_cli_returns_one_on_failure(
    fake_examples: Path, capsys: pytest.CaptureFixture
) -> None:
    rc = _cli([
        "--examples-dir", str(fake_examples),
        "--timeout", "15",
        "--no-color",
    ])
    assert rc == 1


def test_cli_parallel_mode(
    fake_examples: Path, capsys: pytest.CaptureFixture
) -> None:
    (fake_examples / "hello_broken.py").write_text(_PASSING_STUB, encoding="utf-8")
    rc = _cli([
        "--examples-dir", str(fake_examples),
        "--timeout", "15",
        "--parallel",
        "--workers", "2",
        "--no-color",
    ])
    assert rc == 0
