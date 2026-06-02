"""Smoke tests for the 3D example demos.

Both ``examples/hello_3d_layer.py`` and ``examples/hello_bake.py`` exercise
the 3D-layer render path. Sprint 7B fixed their shader-binding mismatches so
they now reach the engine loop; this sprint wires ``--frames N`` through to
``Engine.run(max_frames=N)`` so they exit cleanly under CI smoke runs.

Each test spawns the demo as a subprocess with ``--frames 5`` and asserts:

* The subprocess exits with code 0 inside a 10s wall-clock budget.
* The wall-clock elapsed time is well under the 10s ceiling — proves that
  ``max_frames`` short-circuits the live event loop rather than relying on a
  test-side timeout to terminate the process.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _REPO_ROOT / "SlapPyEngineExamples" / "examples"

_SMOKE_TIMEOUT_S = 10.0
_FRAMES = 5


def _run_example(name: str) -> tuple[int, str, str, float]:
    """Spawn ``examples/<name>.py --frames 5`` and return (rc, stdout, stderr, elapsed)."""
    env = os.environ.copy()
    py_path = env.get("PYTHONPATH", "")
    pkg_path = str(_REPO_ROOT / "python")
    if pkg_path not in py_path.split(os.pathsep):
        env["PYTHONPATH"] = (
            pkg_path + (os.pathsep + py_path if py_path else "")
        )
    env.setdefault("PYTHONUNBUFFERED", "1")

    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(_EXAMPLES / f"{name}.py"), "--frames", str(_FRAMES)],
        capture_output=True,
        text=True,
        timeout=_SMOKE_TIMEOUT_S,
        env=env,
        cwd=str(_REPO_ROOT),
    )
    elapsed = time.perf_counter() - started
    return completed.returncode, completed.stdout, completed.stderr, elapsed


@pytest.mark.parametrize("name", ["hello_3d_layer", "hello_bake"])
def test_3d_example_smoke(name: str) -> None:
    """The 3D example must exit 0 within the 10s smoke budget."""
    try:
        rc, stdout, stderr, elapsed = _run_example(name)
    except subprocess.TimeoutExpired as exc:
        pytest.fail(
            f"{name}: timed out after {_SMOKE_TIMEOUT_S:.0f}s — "
            f"--frames is not short-circuiting Engine.run()\n"
            f"--- stdout ---\n{exc.stdout or ''}\n"
            f"--- stderr ---\n{exc.stderr or ''}"
        )

    assert rc == 0, (
        f"{name}: exit={rc} (elapsed={elapsed:.2f}s)\n"
        f"--- stdout ---\n{stdout}\n"
        f"--- stderr ---\n{stderr}"
    )
    assert elapsed < _SMOKE_TIMEOUT_S, (
        f"{name}: ran for {elapsed:.2f}s, expected < {_SMOKE_TIMEOUT_S:.0f}s"
    )
