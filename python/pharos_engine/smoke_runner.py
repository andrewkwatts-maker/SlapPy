"""Batch smoke-test runner for Pharos Engine ``hello_*.py`` examples.

This module walks ``PharosEngineExamples/examples/`` for every ``hello_*.py``
demo, launches each in a subprocess with ``SLAPPY_HEADLESS=1``, and reports
pass / fail / skip / timeout without any pytest infrastructure.

Design goals
------------
* Zero pytest coupling — usable from a CLI, a CI hook, or a scratch script.
* Sequential *and* parallel modes so a developer can trade determinism for
  wall-clock speed.
* Machine-readable YAML report plus a human-readable ANSI summary table.
* Hard-coded skip list for demos that only make sense inside a GPU / DPG
  viewport session (they'd hang or crash on a headless CI runner).

Typical usage
-------------
::

    python -m pharos_engine.smoke_runner              # sequential, all demos
    python -m pharos_engine.smoke_runner --parallel   # thread-pool fan-out
    python -m pharos_engine.smoke_runner --report out.yml

Exit code is ``0`` when every non-skipped demo passed, ``1`` otherwise.
"""

from __future__ import annotations

import argparse
import concurrent.futures as _cf
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

try:  # pragma: no cover — pyyaml is a hard dep in-repo but keep the fallback
    import yaml as _yaml
except Exception:  # pragma: no cover
    _yaml = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: Demos that require a live GPU device and/or a DearPyGui viewport and are
#: therefore unsafe to run on a headless CI runner. The runner will mark
#: these as ``"skip"`` instead of spawning a subprocess.
SKIP_LIST: frozenset[str] = frozenset({
    # ``se.Engine().run()`` opens a WGPU canvas and blocks the event loop —
    # there's no ``max_frames`` short-circuit in the demo, so it would hang.
    "hello_world",
    "hello_lighting",
    "hello_physics",
    "hello_pixel",
})

#: Default per-example timeout, in seconds. Physics / softbody rebuilds are
#: heavy on cold Rust import; keep this generous.
DEFAULT_TIMEOUT_S: float = 60.0

#: Default worker count for :meth:`SmokeRunner.run_all_parallel`.
DEFAULT_MAX_WORKERS: int = 4

#: Number of characters of stdout to persist in the result for quick triage.
_OUTPUT_HEAD_CHARS: int = 800


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _repo_root() -> Path:
    """Return the Pharos Engine repository root.

    ``__file__`` lives at ``<repo>/python/pharos_engine/smoke_runner.py``, so
    two ``.parent`` hops land on the package root and one more on the repo.
    """
    return Path(__file__).resolve().parents[2]


def _default_examples_dir() -> Path:
    """Return the canonical ``PharosEngineExamples/examples`` directory."""
    return _repo_root() / "PharosEngineExamples" / "examples"


# ---------------------------------------------------------------------------
# Result record
# ---------------------------------------------------------------------------

@dataclass
class SmokeResult:
    """One row in the smoke-test scoreboard.

    Attributes
    ----------
    example:
        The ``hello_<name>`` stem (no ``.py``, no directory prefix).
    status:
        One of ``"pass"``, ``"fail"``, ``"skip"``, ``"timeout"``.
    duration_s:
        Wall-clock time spent inside the subprocess (0.0 for ``"skip"``).
    output_head:
        First :data:`_OUTPUT_HEAD_CHARS` chars of merged stdout/stderr —
        enough to eyeball a stack trace without hoarding megabytes.
    error:
        Human-readable error summary when ``status != "pass"``; ``None``
        for passes.
    """

    example: str
    status: str
    duration_s: float = 0.0
    output_head: str = ""
    error: Optional[str] = None

    def to_dict(self) -> dict:
        """Return a plain-dict view suitable for YAML/JSON serialisation."""
        return asdict(self)


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

@dataclass
class SmokeRunner:
    """Walk the examples directory and run each ``hello_*.py`` demo.

    Parameters
    ----------
    skip_list:
        Overrides :data:`SKIP_LIST` — pass an empty frozenset to force
        every demo to run (mostly useful for tests).
    python_executable:
        Interpreter to invoke; defaults to ``sys.executable`` so the
        runner honours virtualenvs.
    """

    skip_list: frozenset[str] = field(default_factory=lambda: SKIP_LIST)
    python_executable: str = field(default_factory=lambda: sys.executable)

    # -- discovery ---------------------------------------------------------

    def discover(self, examples_dir: Optional[Path] = None) -> List[Path]:
        """Return the sorted list of ``hello_*.py`` paths.

        Parameters
        ----------
        examples_dir:
            Directory to scan. Defaults to
            ``PharosEngineExamples/examples`` under the repo root.
        """
        root = Path(examples_dir) if examples_dir is not None else _default_examples_dir()
        if not root.is_dir():
            return []
        return sorted(root.glob("hello_*.py"))

    # -- one subprocess ----------------------------------------------------

    def run_one(
        self,
        example_path: Path,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> SmokeResult:
        """Spawn a single demo subprocess and classify its outcome.

        The subprocess inherits ``os.environ`` but has ``SLAPPY_HEADLESS=1``
        and ``PYTHONUNBUFFERED=1`` forced so demos that respect the flag
        skip their viewport bring-up and stream output on timeout.
        """
        example_path = Path(example_path)
        stem = example_path.stem

        # Hard-skip demos that we know need a GPU / DPG viewport.
        if stem in self.skip_list:
            return SmokeResult(
                example=stem,
                status="skip",
                duration_s=0.0,
                output_head="",
                error="in SKIP_LIST (requires GPU / DPG viewport)",
            )

        if not example_path.exists():
            return SmokeResult(
                example=stem,
                status="fail",
                duration_s=0.0,
                output_head="",
                error=f"example not found: {example_path}",
            )

        env = os.environ.copy()
        env["SLAPPY_HEADLESS"] = "1"
        env.setdefault("PYTHONUNBUFFERED", "1")
        # Make sure the child finds the in-repo package even if the caller
        # forgot to ``pip install -e .``.
        pkg_path = str(_repo_root() / "python")
        existing = env.get("PYTHONPATH", "")
        if pkg_path not in existing.split(os.pathsep):
            env["PYTHONPATH"] = (
                pkg_path + (os.pathsep + existing if existing else "")
            )

        argv = [self.python_executable, str(example_path)]
        started = time.perf_counter()

        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=timeout_s,
                env=env,
                cwd=str(_repo_root()),
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.perf_counter() - started
            head = _head((exc.stdout or "") + (exc.stderr or ""))
            return SmokeResult(
                example=stem,
                status="timeout",
                duration_s=elapsed,
                output_head=head,
                error=f"timeout after {timeout_s:.1f}s (killed subprocess)",
            )
        except Exception as exc:  # pragma: no cover — spawn error, rare
            elapsed = time.perf_counter() - started
            return SmokeResult(
                example=stem,
                status="fail",
                duration_s=elapsed,
                output_head="",
                error=f"failed to spawn subprocess: {exc!r}",
            )

        elapsed = time.perf_counter() - started
        head = _head((completed.stdout or "") + (completed.stderr or ""))
        if completed.returncode == 0:
            return SmokeResult(
                example=stem,
                status="pass",
                duration_s=elapsed,
                output_head=head,
                error=None,
            )
        return SmokeResult(
            example=stem,
            status="fail",
            duration_s=elapsed,
            output_head=head,
            error=f"exit code {completed.returncode}",
        )

    # -- sequential --------------------------------------------------------

    def run_all(
        self,
        examples_dir: Optional[Path] = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        progress: Optional[Callable[[int, int, SmokeResult], None]] = None,
    ) -> List[SmokeResult]:
        """Run every discovered example in order.

        Parameters
        ----------
        examples_dir:
            Directory to scan. See :meth:`discover`.
        timeout_s:
            Per-example timeout.
        progress:
            Optional callback ``(index, total, result)`` — invoked once per
            demo *after* it finishes, useful for a live progress bar.
        """
        examples = self.discover(examples_dir)
        total = len(examples)
        results: List[SmokeResult] = []
        for idx, path in enumerate(examples, start=1):
            result = self.run_one(path, timeout_s=timeout_s)
            results.append(result)
            if progress is not None:
                try:
                    progress(idx, total, result)
                except Exception:  # pragma: no cover — never fail the sweep
                    pass
        return results

    # -- parallel ----------------------------------------------------------

    def run_all_parallel(
        self,
        examples_dir: Optional[Path] = None,
        max_workers: int = DEFAULT_MAX_WORKERS,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> List[SmokeResult]:
        """Run every discovered example in a thread pool.

        Results are returned in the same sorted-by-path order as
        :meth:`run_all` — the pool is just for wall-clock reduction, not
        for interleaving output.
        """
        examples = self.discover(examples_dir)
        if not examples:
            return []
        # Clamp workers to something sensible.
        workers = max(1, min(int(max_workers), len(examples)))
        results: dict[Path, SmokeResult] = {}
        with _cf.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self.run_one, path, timeout_s): path
                for path in examples
            }
            for fut in _cf.as_completed(futures):
                path = futures[fut]
                results[path] = fut.result()
        return [results[p] for p in examples]

    # -- formatting --------------------------------------------------------

    def format_summary(
        self,
        results: Sequence[SmokeResult],
        use_color: bool = True,
    ) -> str:
        """Return a pretty ANSI-coloured table of results.

        The output is safe to write to a file (colours are OFF when
        ``use_color`` is False).
        """
        return _format_summary(results, use_color=use_color)

    # -- report ------------------------------------------------------------

    def write_report(
        self,
        results: Sequence[SmokeResult],
        out_path: Path,
    ) -> Path:
        """Write results to disk as YAML.

        Returns the resolved output path. The YAML document is a mapping::

            generated_at: <iso8601>
            total: N
            pass: N
            fail: N
            skip: N
            timeout: N
            results:
              - example: hello_foo
                status: pass
                ...
        """
        out_path = Path(out_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total": len(results),
            "pass": _count(results, "pass"),
            "fail": _count(results, "fail"),
            "skip": _count(results, "skip"),
            "timeout": _count(results, "timeout"),
            "results": [r.to_dict() for r in results],
        }
        if _yaml is not None:
            text = _yaml.safe_dump(payload, sort_keys=False)
        else:  # pragma: no cover — fallback dumper
            text = _fallback_yaml(payload)
        out_path.write_text(text, encoding="utf-8")
        return out_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _head(text: str, n: int = _OUTPUT_HEAD_CHARS) -> str:
    """Return the first ``n`` chars of ``text`` (safe on ``None``)."""
    if not text:
        return ""
    if len(text) <= n:
        return text
    return text[:n] + "\n...[truncated]"


def _count(results: Iterable[SmokeResult], status: str) -> int:
    """Count results whose ``.status`` equals ``status``."""
    return sum(1 for r in results if r.status == status)


# ANSI colour glyphs — kept as module-level constants so tests can grep for
# them without duplicating the escape codes.
_GLYPH_PASS = "✔"  # ✔
_GLYPH_FAIL = "✘"  # ✘
_GLYPH_SKIP = "–"  # –
_GLYPH_TIME = "⧖"  # ⧖ (hourglass-ish)

_ANSI_GREEN = "\x1b[32m"
_ANSI_RED = "\x1b[31m"
_ANSI_YELLOW = "\x1b[33m"
_ANSI_DIM = "\x1b[2m"
_ANSI_RESET = "\x1b[0m"


def _paint(text: str, code: str, use_color: bool) -> str:
    """Wrap ``text`` in an ANSI escape when ``use_color`` is true."""
    if not use_color:
        return text
    return f"{code}{text}{_ANSI_RESET}"


def _format_summary(
    results: Sequence[SmokeResult], use_color: bool = True
) -> str:
    """Build the human-readable summary table for :meth:`format_summary`."""
    if not results:
        return "(no examples discovered)"

    name_w = max(len(r.example) for r in results)
    name_w = max(name_w, len("example"))
    lines: list[str] = []
    lines.append(
        "  " + "example".ljust(name_w) + "   status   duration"
    )
    lines.append("  " + "-" * name_w + "   ------   --------")
    for r in results:
        if r.status == "pass":
            glyph = _paint(_GLYPH_PASS + " pass", _ANSI_GREEN, use_color)
        elif r.status == "fail":
            glyph = _paint(_GLYPH_FAIL + " fail", _ANSI_RED, use_color)
        elif r.status == "timeout":
            glyph = _paint(_GLYPH_TIME + " time", _ANSI_YELLOW, use_color)
        elif r.status == "skip":
            glyph = _paint(_GLYPH_SKIP + " skip", _ANSI_DIM, use_color)
        else:
            glyph = r.status
        lines.append(
            f"  {r.example.ljust(name_w)}   {glyph}   {r.duration_s:6.2f}s"
        )

    total = len(results)
    p = _count(results, "pass")
    f = _count(results, "fail")
    s = _count(results, "skip")
    t = _count(results, "timeout")
    lines.append("")
    lines.append(
        f"  {total} total : "
        f"{_paint(str(p) + ' pass', _ANSI_GREEN, use_color)} / "
        f"{_paint(str(f) + ' fail', _ANSI_RED, use_color)} / "
        f"{_paint(str(t) + ' timeout', _ANSI_YELLOW, use_color)} / "
        f"{_paint(str(s) + ' skip', _ANSI_DIM, use_color)}"
    )
    return "\n".join(lines)


def _fallback_yaml(payload: dict) -> str:  # pragma: no cover
    """Emit a minimal YAML document without pyyaml (last-resort fallback)."""
    lines: list[str] = []
    for key in ("generated_at", "total", "pass", "fail", "skip", "timeout"):
        lines.append(f"{key}: {payload[key]}")
    lines.append("results:")
    for r in payload["results"]:
        lines.append(f"  - example: {r['example']}")
        lines.append(f"    status: {r['status']}")
        lines.append(f"    duration_s: {r['duration_s']}")
        head = (r.get("output_head") or "").replace("\n", " ")
        lines.append(f"    output_head: {head!r}")
        err = r.get("error")
        lines.append(f"    error: {'' if err is None else err!r}")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint. Returns exit code (0 pass, 1 any fail/timeout)."""
    parser = argparse.ArgumentParser(
        prog="pharos_engine.smoke_runner",
        description="Batch smoke-test every Pharos Engine hello_* example.",
    )
    parser.add_argument(
        "--examples-dir",
        type=Path,
        default=None,
        help="Override the default PharosEngineExamples/examples location.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_S,
        help=f"Per-example timeout in seconds (default {DEFAULT_TIMEOUT_S:.0f}).",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Use a thread pool instead of sequential execution.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_MAX_WORKERS,
        help=f"Worker count when --parallel (default {DEFAULT_MAX_WORKERS}).",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write a YAML report to this path.",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Suppress ANSI colour codes in the summary.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    runner = SmokeRunner()

    def _progress(idx: int, total: int, result: SmokeResult) -> None:
        marker = {
            "pass": "ok",
            "fail": "FAIL",
            "skip": "skip",
            "timeout": "TIME",
        }.get(result.status, result.status)
        print(f"  [{idx:>2d}/{total}] {result.example:32s} {marker}")

    if args.parallel:
        results = runner.run_all_parallel(
            examples_dir=args.examples_dir,
            max_workers=args.workers,
            timeout_s=args.timeout,
        )
        for i, r in enumerate(results, start=1):
            _progress(i, len(results), r)
    else:
        results = runner.run_all(
            examples_dir=args.examples_dir,
            timeout_s=args.timeout,
            progress=_progress,
        )

    print()
    print(runner.format_summary(results, use_color=not args.no_color))

    if args.report is not None:
        runner.write_report(results, args.report)
        print(f"\nreport written to {args.report}")

    # Non-zero when any demo failed or timed out. Skips are OK.
    bad = _count(results, "fail") + _count(results, "timeout")
    return 1 if bad else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_cli())
