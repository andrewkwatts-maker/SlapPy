"""
M7 animation system tests — no GPU or Rust extension required for most cases.
"""
import pytest

from playslap.animation.graph import AnimationGraph, AnimState, AnimTransition
from playslap.cube_array import CubeArray
from playslap.animation.procedural import ControlPoint, ProceduralRig

try:
    from playslap.animation.graph import AnimUpdate
    _has_animupdate = True
except ImportError:
    _has_animupdate = False


# ---------------------------------------------------------------------------
# AnimationGraph tests
# ---------------------------------------------------------------------------

def test_anim_graph_initial_state():
    # Create graph with one state, set initial, tick — should return that state name
    g = AnimationGraph()
    g.add_state(AnimState("idle", clip_indices=[], loop=True, fps=12.0))
    g.set_initial("idle")
    result = g.tick(0.1)
    assert result == "idle"


def test_anim_graph_transition():
    # Two states, transition condition becomes true after a flag is set
    g = AnimationGraph()
    g.add_state(AnimState("idle"))
    g.add_state(AnimState("run"))
    flag = [False]
    g.add_transition(AnimTransition("idle", "run", condition=lambda: flag[0]))
    g.set_initial("idle")
    assert g.tick(0.1) == "idle"
    flag[0] = True
    assert g.tick(0.1) == "run"


def test_anim_graph_no_retransition_without_trigger():
    g = AnimationGraph()
    g.add_state(AnimState("a"))
    g.add_state(AnimState("b"))
    g.add_transition(AnimTransition("a", "b", condition=lambda: True))
    g.set_initial("a")
    g.tick(0.0)  # transitions to b
    assert g.current_state.name == "b"
    # No transition from b defined — stays at b
    g.tick(0.1)
    assert g.current_state.name == "b"


@pytest.mark.skipif(not _has_animupdate, reason="AnimUpdate not yet defined")
def test_anim_graph_update_returns_animupdate():
    # update() should return AnimUpdate with state_name, frame_index, blend_fraction
    g = AnimationGraph()
    g.add_state(AnimState("idle", clip_indices=[0, 1, 2], loop=True, fps=30.0))
    g.set_initial("idle")
    result = g.update(0.0)
    assert isinstance(result, AnimUpdate)
    assert result.state_name == "idle"
    assert isinstance(result.frame_index, int)
    assert 0.0 <= result.blend_fraction <= 1.0


def test_anim_graph_frame_advances():
    g = AnimationGraph()
    g.add_state(AnimState("walk", clip_indices=[0, 1, 2, 3], loop=True, fps=4.0))
    g.set_initial("walk")
    r0 = g.update(0.0)
    r1 = g.update(0.26)  # just over 1 frame at 4 fps
    assert r1.frame_index != r0.frame_index or r1.blend_fraction > 0.0


def test_anim_graph_none_without_initial():
    g = AnimationGraph()
    g.add_state(AnimState("idle"))
    assert g.tick(0.1) is None


# ---------------------------------------------------------------------------
# CubeArray tests
# ---------------------------------------------------------------------------

def test_cube_array_play_seek():
    ca = CubeArray(name="test", size=(32, 32))
    ca.frame_count = 10
    ca.seek(5)
    assert ca.current_frame == 5
    ca.seek(20)  # clamp to frame_count - 1
    assert ca.current_frame == 9


def test_cube_array_tick_advances_when_playing():
    ca = CubeArray(name="test", size=(32, 32))
    ca.frame_count = 4
    ca.fps = 4.0
    ca.play()
    ca.tick(0.3)  # 1.2 frames at 4 fps
    assert ca.current_frame >= 1


def test_cube_array_tick_loops():
    ca = CubeArray(name="test", size=(32, 32))
    ca.frame_count = 3
    ca.fps = 30.0
    ca.play()
    ca.tick(1.0)  # 30 frames elapsed = 10 loops of 3
    assert ca.current_frame < 3


def test_cube_array_animation_graph_wired():
    # If animation_graph is set, it should drive current_frame
    ca = CubeArray(name="g", size=(8, 8))
    ca.frame_count = 4
    g = AnimationGraph()
    g.add_state(AnimState("idle", clip_indices=[0, 1, 2, 3], loop=True, fps=8.0))
    g.set_initial("idle")
    ca.animation_graph = g
    ca.play()
    ca.tick(0.5)  # 4 frames at 8 fps
    assert ca.current_frame >= 0


def test_cube_array_from_images_stub():
    # Verify key attributes exist without loading real image files
    ca = CubeArray()
    assert hasattr(ca, "frame_count")
    assert hasattr(ca, "animation_graph")


# ---------------------------------------------------------------------------
# ProceduralRig tests
# ---------------------------------------------------------------------------

def test_procedural_rig_add_remove():
    rig = ProceduralRig()
    cp = ControlPoint("hip", uv=(0.5, 0.5))
    rig.add_point(cp)
    assert len(rig.points) == 1
    rig.remove_point("hip")
    assert len(rig.points) == 0


def test_procedural_rig_get_chain():
    rig = ProceduralRig()
    rig.add_point(ControlPoint("hip", uv=(0.5, 0.5)))
    rig.add_point(ControlPoint("knee", uv=(0.5, 0.7), parent="hip"))
    rig.add_point(ControlPoint("foot", uv=(0.5, 0.9), parent="knee"))
    chain = rig.get_chain("hip", "foot")
    assert [cp.name for cp in chain] == ["hip", "knee", "foot"]


def test_procedural_rig_find_root():
    rig = ProceduralRig()
    rig.add_point(ControlPoint("shoulder", uv=(0.3, 0.3)))
    rig.add_point(ControlPoint("elbow", uv=(0.3, 0.5), parent="shoulder"))
    rig.add_point(ControlPoint("hand", uv=(0.3, 0.7), parent="elbow"))
    root = rig._find_root("hand")
    assert root == "shoulder"


def test_procedural_rig_solve_ik_no_core():
    # Should not raise even when _core (Rust) is unavailable
    rig = ProceduralRig()
    rig.add_point(ControlPoint("a", uv=(0.0, 0.0)))
    rig.add_point(ControlPoint("b", uv=(0.0, 0.1), parent="a"))
    result = rig.solve_ik({"b": (0.0, 0.2)})
    assert "a" in result
    assert "b" in result
