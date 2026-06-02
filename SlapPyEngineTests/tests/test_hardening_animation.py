"""Hardening round 6 — animation graph public boundaries."""
from __future__ import annotations

import math
import pytest

from slappyengine.animation.graph import (
    AnimState,
    AnimTransition,
    AnimationGraph,
)


# ── AnimState ──────────────────────────────────────────────────────────────

def test_animstate_empty_name_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        AnimState(name="")


def test_animstate_non_str_name_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        AnimState(name=42)  # type: ignore[arg-type]


def test_animstate_negative_clip_index_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        AnimState(name="run", clip_indices=[0, -1, 2])


def test_animstate_non_int_clip_index_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        AnimState(name="run", clip_indices=[0, 1.5])  # type: ignore[list-item]


def test_animstate_non_list_clip_indices_rejected() -> None:
    with pytest.raises(TypeError, match="must be a list"):
        AnimState(name="run", clip_indices="0,1,2")  # type: ignore[arg-type]


def test_animstate_zero_fps_rejected() -> None:
    with pytest.raises(ValueError, match="> 0"):
        AnimState(name="run", fps=0.0)


def test_animstate_negative_fps_rejected() -> None:
    with pytest.raises(ValueError, match="> 0"):
        AnimState(name="run", fps=-24.0)


def test_animstate_nan_fps_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        AnimState(name="run", fps=float("nan"))


def test_animstate_inf_fps_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        AnimState(name="run", fps=float("inf"))


def test_animstate_string_fps_rejected() -> None:
    with pytest.raises(TypeError, match="numeric"):
        AnimState(name="run", fps="24")  # type: ignore[arg-type]


# ── AnimTransition ──────────────────────────────────────────────────────────

def test_animtransition_empty_from_rejected() -> None:
    with pytest.raises(ValueError, match="from_state"):
        AnimTransition(from_state="", to_state="run")


def test_animtransition_empty_to_rejected() -> None:
    with pytest.raises(ValueError, match="to_state"):
        AnimTransition(from_state="idle", to_state="")


def test_animtransition_non_callable_condition_rejected() -> None:
    with pytest.raises(TypeError, match="callable"):
        AnimTransition(
            from_state="idle",
            to_state="run",
            condition="lambda: True",  # type: ignore[arg-type]
        )


# ── AnimationGraph ──────────────────────────────────────────────────────────

def test_graph_add_state_rejects_non_animstate() -> None:
    g = AnimationGraph()
    with pytest.raises(TypeError, match="AnimState"):
        g.add_state("idle")  # type: ignore[arg-type]


def test_graph_add_transition_rejects_non_animtransition() -> None:
    g = AnimationGraph()
    with pytest.raises(TypeError, match="AnimTransition"):
        g.add_transition({"from": "idle", "to": "run"})  # type: ignore[arg-type]


def test_graph_set_initial_unknown_state_rejected() -> None:
    g = AnimationGraph()
    g.add_state(AnimState(name="idle"))
    with pytest.raises(ValueError, match="unknown state"):
        g.set_initial("run")


def test_graph_set_initial_empty_rejected() -> None:
    g = AnimationGraph()
    with pytest.raises(ValueError, match="non-empty"):
        g.set_initial("")


def test_graph_update_negative_dt_rejected() -> None:
    g = AnimationGraph()
    g.add_state(AnimState(name="idle"))
    g.set_initial("idle")
    with pytest.raises(ValueError, match="≥ 0"):
        g.update(-0.1)


def test_graph_update_nan_dt_rejected() -> None:
    g = AnimationGraph()
    g.add_state(AnimState(name="idle"))
    g.set_initial("idle")
    with pytest.raises(ValueError, match="finite"):
        g.update(float("nan"))


def test_graph_update_non_numeric_dt_rejected() -> None:
    g = AnimationGraph()
    g.add_state(AnimState(name="idle"))
    g.set_initial("idle")
    with pytest.raises(TypeError, match="numeric"):
        g.update("0.016")  # type: ignore[arg-type]


# ── Positive smoke ──────────────────────────────────────────────────────────

def test_graph_positive_path_unaffected() -> None:
    g = AnimationGraph()
    g.add_state(AnimState(name="idle", clip_indices=[0, 1, 2], fps=12.0))
    g.add_state(AnimState(name="run", clip_indices=[3, 4, 5], fps=24.0))
    g.add_transition(AnimTransition(
        from_state="idle", to_state="run", condition=lambda: True,
    ))
    g.set_initial("idle")
    upd = g.update(1.0 / 60.0)
    assert upd is not None
    assert upd.state_name in {"idle", "run"}
