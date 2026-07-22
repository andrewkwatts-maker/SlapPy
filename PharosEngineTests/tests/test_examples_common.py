"""Tests for :mod:`pharos_engine.examples_common`.

The helper exposes three public surfaces:

* :func:`build_demo_arg_parser` — argparse factory with the demo flags.
* :func:`record_or_smoke` — fork between ``stage.record(...)`` and a
  step-only smoke loop driven by ``--no-gif`` / ``--render``.
* :func:`should_record` + :func:`resolve_out_path` — small helpers
  exercised indirectly by the fork.

These tests pin the parser surface (defaults + the three common flags
the task brief asked for) and the fork logic in both directions using a
stub :class:`pharos_engine.studio.Stage`-shaped object.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from types import SimpleNamespace

import pytest

from pharos_engine.examples_common import (
    build_demo_arg_parser,
    record_or_smoke,
    resolve_out_path,
    should_record,
)


# ────────────────────────────────────────────────────────────────────────────
# build_demo_arg_parser
# ────────────────────────────────────────────────────────────────────────────

def test_parser_has_common_flags() -> None:
    """``--frames``, ``--no-gif``, ``--out`` are wired with sane defaults."""
    parser = build_demo_arg_parser("dummy demo", default_frames=42)

    # All five flags must be present in the namespace.
    ns = parser.parse_args([])
    assert ns.frames == 42
    assert ns.no_gif is False
    assert ns.render is False
    assert ns.out is None
    assert ns.seed is None

    # And accept the documented invocations end-to-end.
    ns2 = parser.parse_args(
        ["--frames", "5", "--no-gif", "--out", "out/foo.gif", "--seed", "7"]
    )
    assert ns2.frames == 5
    assert ns2.no_gif is True
    assert ns2.out == Path("out/foo.gif")
    assert ns2.seed == 7


def test_parser_render_flag_overrides_no_gif() -> None:
    """``--render`` must beat ``--no-gif`` per the documented precedence."""
    parser = build_demo_arg_parser("dummy demo")
    ns = parser.parse_args(["--no-gif", "--render"])
    assert ns.no_gif is True
    assert ns.render is True
    assert should_record(ns) is True


def test_parser_no_gif_disables_recording() -> None:
    """``--no-gif`` alone forces the smoke / step-only branch."""
    parser = build_demo_arg_parser("dummy demo")
    ns = parser.parse_args(["--no-gif"])
    assert should_record(ns) is False


def test_parser_default_records() -> None:
    """No flags = record (the conventional default)."""
    parser = build_demo_arg_parser("dummy demo")
    ns = parser.parse_args([])
    assert should_record(ns) is True


def test_parser_default_out_path_is_typed() -> None:
    """``default_out`` round-trips through ``Path``."""
    parser = build_demo_arg_parser("dummy demo", default_out="out/dummy.gif")
    ns = parser.parse_args([])
    assert ns.out == Path("out/dummy.gif")


# ────────────────────────────────────────────────────────────────────────────
# resolve_out_path
# ────────────────────────────────────────────────────────────────────────────

def test_resolve_out_path_creates_parent(tmp_path: Path) -> None:
    """``resolve_out_path`` mkdir's the parent so callers don't need to."""
    target = tmp_path / "nested" / "deeper" / "out.gif"
    args = argparse.Namespace(out=None)
    result = resolve_out_path(args, default_out=target)
    assert result == target
    assert target.parent.is_dir()


def test_resolve_out_path_respects_explicit_arg(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.gif"
    args = argparse.Namespace(out=explicit)
    result = resolve_out_path(args, default_out=tmp_path / "ignored.gif")
    assert result == explicit


# ────────────────────────────────────────────────────────────────────────────
# record_or_smoke: record branch
# ────────────────────────────────────────────────────────────────────────────

class _StubStage:
    """Quack like ``studio.Stage`` for both branches."""

    def __init__(self) -> None:
        self.dt = 1.0 / 60.0
        self.recorded: dict | None = None
        self.world = SimpleNamespace(steps=0, step=self._world_step)
        # Branches: smoke uses softbody/fluid/dynamics; record uses .record.
        self.softbody = None
        self.fluid = None
        self.dynamics = SimpleNamespace(
            steps=0,
            step=self._dyn_step,
        )

    def _world_step(self, dt: float) -> None:
        self.world.steps += 1

    def _dyn_step(self, dt: float) -> None:
        self.dynamics.steps += 1

    def record(self, out_path, *, frames, fps, step_world,
               pre_step, post_step, overlay) -> Path:
        self.recorded = {
            "out_path": Path(out_path),
            "frames": int(frames),
            "fps": int(fps),
            "step_world": bool(step_world),
            "pre_step": pre_step,
            "post_step": post_step,
            "overlay": overlay,
        }
        return Path(out_path)


def test_record_or_smoke_calls_record_on_default(tmp_path: Path) -> None:
    """No ``--no-gif`` flag = stage.record(...) is called with args.frames."""
    parser = build_demo_arg_parser("dummy", default_frames=11)
    ns = parser.parse_args([])
    stage = _StubStage()
    default_out = tmp_path / "out" / "dummy.gif"

    written = record_or_smoke(stage, ns, default_out=default_out)

    assert written == default_out
    assert stage.recorded is not None
    assert stage.recorded["frames"] == 11
    assert stage.recorded["out_path"] == default_out
    # The smoke loop must not have stepped the dynamics world.
    assert stage.dynamics.steps == 0


def test_record_or_smoke_uses_explicit_out_path(tmp_path: Path) -> None:
    """``--out`` overrides the demo's default path on the record branch."""
    parser = build_demo_arg_parser("dummy")
    explicit = tmp_path / "explicit.gif"
    ns = parser.parse_args(["--out", str(explicit)])
    stage = _StubStage()

    written = record_or_smoke(stage, ns, default_out=tmp_path / "ignored.gif")

    assert written == explicit
    assert stage.recorded["out_path"] == explicit


# ────────────────────────────────────────────────────────────────────────────
# record_or_smoke: smoke branch
# ────────────────────────────────────────────────────────────────────────────

def test_record_or_smoke_smoke_branch_steps_dynamics(tmp_path: Path) -> None:
    """``--no-gif`` skips record and steps the dynamics world per frame."""
    parser = build_demo_arg_parser("dummy", default_frames=7)
    ns = parser.parse_args(["--no-gif"])
    stage = _StubStage()

    result = record_or_smoke(stage, ns, default_out=tmp_path / "unused.gif")

    assert result is None
    assert stage.recorded is None
    assert stage.dynamics.steps == 7


def test_record_or_smoke_smoke_runs_post_step_each_frame(tmp_path: Path) -> None:
    """``post_step`` is invoked on every frame in the smoke branch."""
    parser = build_demo_arg_parser("dummy", default_frames=4)
    ns = parser.parse_args(["--no-gif"])
    stage = _StubStage()
    seen: list[int] = []

    def post_step(s, f: int) -> None:
        assert s is stage
        seen.append(f)

    result = record_or_smoke(
        stage, ns,
        default_out=tmp_path / "unused.gif",
        post_step=post_step,
    )

    assert result is None
    assert seen == [0, 1, 2, 3]


def test_record_or_smoke_smoke_branch_honours_step_world_false(
    tmp_path: Path,
) -> None:
    """``step_world=False`` is the pose-only path; ``post_step`` still fires."""
    parser = build_demo_arg_parser("dummy", default_frames=5)
    ns = parser.parse_args(["--no-gif"])
    stage = _StubStage()
    ticks: list[int] = []

    record_or_smoke(
        stage, ns,
        default_out=tmp_path / "unused.gif",
        step_world=False,
        post_step=lambda s, f: ticks.append(f),
    )

    # Dynamics must not have been stepped.
    assert stage.dynamics.steps == 0
    # But post_step still ran each frame.
    assert ticks == [0, 1, 2, 3, 4]


# ────────────────────────────────────────────────────────────────────────────
# --render flag forces the record branch even with --no-gif
# ────────────────────────────────────────────────────────────────────────────

def test_render_flag_forces_record(tmp_path: Path) -> None:
    """``--render`` overrides ``--no-gif`` and calls stage.record."""
    parser = build_demo_arg_parser("dummy", default_frames=3)
    ns = parser.parse_args(["--no-gif", "--render"])
    stage = _StubStage()
    default_out = tmp_path / "forced.gif"

    written = record_or_smoke(stage, ns, default_out=default_out)

    assert written == default_out
    assert stage.recorded is not None
    assert stage.recorded["frames"] == 3
