"""Run every ``examples/hello_*.py`` and assemble a screenshot grid.

Used both as CI smoke (does every demo still run?) and as the source for
the README's "Example demos" thumbnail strip.

CLI::

    PYTHONPATH=python python tools/run_examples.py [--out path]

Each demo is invoked headlessly as::

    python <demo> --render --frames 60 --out <tmp>/<demo>.png

with a 60-second timeout.  Demos that crash, time out, or fail to
produce a PNG are recorded but never stop the runner — their cell in
the grid is rendered as a red ``FAILED`` placeholder.

The default output path is ``docs/screenshots/examples_grid.png`` so the
file checked in alongside this script is the same one the README links
to.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

# Re-use the pure-PIL composer.  Keep imports relative-tolerant so the
# script works whether invoked as a module or directly.
try:
    from tools.screenshot_grid import compose_grid
except ModuleNotFoundError:  # pragma: no cover - executed as a script
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from tools.screenshot_grid import compose_grid


# ── Tunables ─────────────────────────────────────────────────────────────────
REPO_ROOT: Path = Path(__file__).resolve().parent.parent
EXAMPLES_DIR: Path = REPO_ROOT / "PharosEngineExamples" / "examples"
DEFAULT_OUT: Path = REPO_ROOT / "docs" / "screenshots" / "examples_grid.png"
DEFAULT_TIMEOUT_S: float = 60.0
DEFAULT_FRAMES: int = 60
DEMO_GLOB: str = "hello_*.py"


@dataclass
class DemoResult:
    """Outcome of running a single demo."""
    name: str               # filename, e.g. "hello_rope.py"
    path: Path              # absolute path to the demo script
    png: Path | None        # produced PNG path (or None on failure)
    ok: bool
    elapsed_s: float
    size_bytes: int
    error: str | None = None

    @property
    def status(self) -> str:
        return "OK" if self.ok else "FAIL"


# ── Discovery ────────────────────────────────────────────────────────────────

def discover_demos(examples_dir: Path = EXAMPLES_DIR) -> list[Path]:
    """Return a sorted list of every ``examples/hello_*.py`` file.

    Sorting by filename gives a deterministic grid layout independent of
    the underlying filesystem order.
    """
    examples_dir = Path(examples_dir)
    if not examples_dir.is_dir():
        return []
    return sorted(examples_dir.glob(DEMO_GLOB))


# ── Subprocess driver ────────────────────────────────────────────────────────

def _run_one_demo(
    demo: Path,
    tmp_dir: Path,
    frames: int = DEFAULT_FRAMES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> DemoResult:
    """Invoke ``demo --render --frames N --out <tmp>/...`` once."""
    out_png = tmp_dir / f"{demo.stem}.png"
    env = None  # inherit current env (PYTHONPATH etc.)
    cmd = [
        sys.executable,
        str(demo),
        "--render",
        "--frames", str(frames),
        "--out", str(out_png),
    ]
    t0 = time.perf_counter()
    error: str | None = None
    completed_ok = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or b"").decode(errors="replace").strip().splitlines()
            error = f"exit {proc.returncode}: " + (tail[-1] if tail else "(no stderr)")
        else:
            completed_ok = True
    except subprocess.TimeoutExpired:
        error = f"timeout after {timeout_s:.0f}s"
    except FileNotFoundError as exc:
        error = f"could not launch: {exc}"
    elapsed = time.perf_counter() - t0

    png_ok = out_png.exists() and out_png.stat().st_size > 0
    size_bytes = out_png.stat().st_size if png_ok else 0
    ok = completed_ok and png_ok
    if not ok and error is None:
        error = "demo exited 0 but produced no PNG"

    return DemoResult(
        name=demo.name,
        path=demo,
        png=out_png if png_ok else None,
        ok=ok,
        elapsed_s=elapsed,
        size_bytes=size_bytes,
        error=error,
    )


def run_demos(
    demos: Sequence[Path] | None = None,
    tmp_dir: Path | None = None,
    frames: int = DEFAULT_FRAMES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> list[DemoResult]:
    """Run every demo and return per-demo results.

    Caller is responsible for cleaning up ``tmp_dir`` if it was supplied
    explicitly; when ``tmp_dir`` is ``None`` a fresh ``tempfile`` dir is
    used and left in place (the PNGs are needed afterwards for the grid).
    """
    if demos is None:
        demos = discover_demos()
    if tmp_dir is None:
        tmp_dir = Path(tempfile.mkdtemp(prefix="slappy_examples_"))
    else:
        tmp_dir = Path(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)

    results: list[DemoResult] = []
    for demo in demos:
        results.append(_run_one_demo(demo, tmp_dir, frames, timeout_s))
    return results


# ── Composition + reporting ──────────────────────────────────────────────────

def compose_grid_from_results(
    results: Sequence[DemoResult],
    out_path: Path = DEFAULT_OUT,
    cell_size: tuple[int, int] = (320, 240),
) -> Path:
    """Pass the per-demo PNGs (or sentinels for failures) to ``compose_grid``."""
    image_paths: list[Path] = []
    labels: list[str] = []
    for r in results:
        # Use the PNG path when available; otherwise a non-existent sentinel
        # so compose_grid renders a red FAILED cell.
        image_paths.append(r.png if r.png is not None else Path("/__missing__") / r.name)
        labels.append(r.name)
    return compose_grid(image_paths, out_path, cell_size=cell_size, labels=labels)


def _print_summary(results: Iterable[DemoResult]) -> None:
    results = list(results)
    name_w = max((len(r.name) for r in results), default=4)
    name_w = max(name_w, len("demo"))
    header = f"{'demo'.ljust(name_w)}  status  {'time(s)':>8}  {'bytes':>10}"
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.name.ljust(name_w)}  "
            f"{r.status:<6}  "
            f"{r.elapsed_s:8.2f}  "
            f"{r.size_bytes:10d}"
            + (f"  ({r.error})" if not r.ok and r.error else "")
        )


# ── Top-level API ────────────────────────────────────────────────────────────

def run(
    out: Path = DEFAULT_OUT,
    frames: int = DEFAULT_FRAMES,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    demos: Sequence[Path] | None = None,
    keep_tmp: bool = False,
    cell_size: tuple[int, int] = (320, 240),
) -> tuple[Path, list[DemoResult]]:
    """Run all demos, compose the grid, and return ``(grid_png, results)``.

    Exposed as a regular function so tests can drive it without going
    through ``argparse`` or ``subprocess``.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="slappy_examples_"))
    try:
        results = run_demos(
            demos=demos, tmp_dir=tmp_dir, frames=frames, timeout_s=timeout_s
        )
        grid_path = compose_grid_from_results(results, out_path=out, cell_size=cell_size)
        return grid_path, results
    finally:
        if not keep_tmp:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ── CLI entry point ──────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run every examples/hello_*.py and compose a grid PNG.",
    )
    parser.add_argument(
        "--out", type=Path, default=DEFAULT_OUT,
        help=f"output grid PNG path (default: {DEFAULT_OUT})",
    )
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"--frames forwarded to each demo (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_S,
        help=f"per-demo timeout in seconds (default: {DEFAULT_TIMEOUT_S:.0f})",
    )
    parser.add_argument(
        "--keep-tmp", action="store_true",
        help="don't delete the per-demo PNG scratch dir (for debugging)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    grid_path, results = run(
        out=args.out,
        frames=args.frames,
        timeout_s=args.timeout,
        keep_tmp=args.keep_tmp,
    )
    _print_summary(results)
    print()
    print(f"grid: {grid_path} ({grid_path.stat().st_size} bytes)")
    failed = [r for r in results if not r.ok]
    if failed:
        print(f"{len(failed)} of {len(results)} demos failed.")
    else:
        print(f"All {len(results)} demos OK.")
    # Return 0 even when individual demos failed; the grid is still useful.
    # Callers can grep the summary if they want a hard CI failure on FAIL.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
