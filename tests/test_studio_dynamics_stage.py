"""Regression coverage for :func:`slappyengine.studio.dynamics_stage`."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from slappyengine import studio
from slappyengine.dynamics import RopeSpec, World, build_rope


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEMO_PATH = _REPO_ROOT / "examples" / "hello_studio.py"


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_studio_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_rope_stage() -> studio.Stage:
    stage = studio.dynamics_stage(
        gravity=(0.0, -9.81),
        solver_iterations=12,
        view_box=(-3.0, -3.0, 3.0, 3.0),
        width=160,
        height=120,
        floor_y=-3.0,
    )
    build_rope(
        RopeSpec(
            node_count=12,
            total_length=4.5,
            mass_per_node=0.05,
            stiffness=1.0e6,
            damping=0.05,
            anchor_a_pinned=True,
            anchor_b_pinned=True,
        ),
        stage.dynamics,
        anchor_a=(-1.5, 2.0),
        anchor_b=(1.5, 2.0),
    )
    return stage


def test_dynamics_stage_returns_stage_with_world() -> None:
    stage = studio.dynamics_stage()
    assert isinstance(stage, studio.Stage)
    assert isinstance(stage.dynamics, World)
    assert stage.world is stage.dynamics
    assert stage.softbody is None
    assert stage.fluid is None
    assert stage.render_fn is not None


def test_dynamics_stage_accepts_existing_world() -> None:
    world = World(gravity=(0.0, -1.0))
    world.solver_iterations = 3
    stage = studio.dynamics_stage(world=world)
    assert stage.dynamics is world
    # solver_iterations / gravity must not be clobbered when the caller
    # brought their own world.
    assert stage.dynamics.solver_iterations == 3
    assert float(stage.dynamics.gravity[1]) == pytest.approx(-1.0)


def test_record_writes_non_empty_gif(tmp_path) -> None:
    stage = _build_rope_stage()
    out = tmp_path / "rope.gif"
    written = stage.record(out, frames=8, fps=30)
    assert written == out
    assert out.exists()
    assert out.stat().st_size > 0


def test_record_moves_center_of_mass(tmp_path) -> None:
    stage = _build_rope_stage()
    # CoM uses the dynamic nodes only (anchors are pinned with inv_mass==0).
    def com_y() -> float:
        pos = stage.dynamics.positions
        inv = stage.dynamics.inv_masses
        mask = inv > 0.0
        return float(pos[mask, 1].mean())

    y0 = com_y()
    stage.record(tmp_path / "trace.gif", frames=24, fps=30)
    y1 = com_y()
    # Gravity should have pulled the slack rope downwards over 24 frames.
    assert y1 < y0 - 0.05, (
        f"expected dynamic CoM to drop; before={y0:.4f} after={y1:.4f}"
    )


def test_render_fn_override(tmp_path) -> None:
    stage = _build_rope_stage()
    seen: list[int] = []

    def custom(stage_in: studio.Stage):
        from PIL import Image
        seen.append(stage_in.dynamics.frame)
        return Image.new("RGB", (32, 24), (10, 20, 30))

    stage.record(tmp_path / "custom.gif", frames=5, fps=30, render_fn=custom)
    assert len(seen) == 5
    # Frame counter advances monotonically after each World.step.
    assert seen == sorted(seen)
    # render_fn override must not stick after the call returns.
    assert stage.render_fn is studio._default_dynamics_render


def test_demo_runs_end_to_end(tmp_path) -> None:
    demo = _load_demo()
    out = tmp_path / "hello_studio.gif"
    written = demo.main(out=out)
    assert written == out
    assert out.exists() and out.stat().st_size > 0
