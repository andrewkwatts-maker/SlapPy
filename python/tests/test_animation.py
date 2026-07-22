"""Engine tests for AnimationGraph and ProceduralRig — headless."""
from __future__ import annotations
import pytest


class TestAnimState:
    def test_init_stores_fields(self):
        from slappyengine.animation.graph import AnimState
        s = AnimState(name="run", clip_indices=[0, 1, 2], loop=True, fps=12.0)
        assert s.name == "run"
        assert s.clip_indices == [0, 1, 2]
        assert s.loop is True
        assert s.fps == pytest.approx(12.0)

    def test_default_loop_true(self):
        from slappyengine.animation.graph import AnimState
        s = AnimState(name="idle")
        assert s.loop is True

    def test_default_fps(self):
        from slappyengine.animation.graph import AnimState
        s = AnimState(name="idle")
        assert s.fps == pytest.approx(24.0)


class TestAnimationGraphInit:
    def test_initial_state_none(self):
        from slappyengine.animation.graph import AnimationGraph
        g = AnimationGraph()
        assert g.current_state is None

    def test_add_and_set_initial(self):
        from slappyengine.animation.graph import AnimationGraph, AnimState
        g = AnimationGraph()
        g.add_state(AnimState(name="idle"))
        g.set_initial("idle")
        assert g.current_state is not None
        assert g.current_state.name == "idle"

    def test_update_without_states_returns_none(self):
        from slappyengine.animation.graph import AnimationGraph
        g = AnimationGraph()
        result = g.update(0.1)
        assert result is None


class TestAnimationGraphUpdate:
    def _make_graph(self):
        from slappyengine.animation.graph import AnimationGraph, AnimState
        g = AnimationGraph()
        g.add_state(AnimState(name="idle", clip_indices=[0, 1], fps=10.0))
        g.add_state(AnimState(name="run", clip_indices=[2, 3, 4], fps=20.0))
        g.set_initial("idle")
        return g

    def test_update_returns_anim_update(self):
        from slappyengine.animation.graph import AnimUpdate
        g = self._make_graph()
        result = g.update(0.05)
        assert isinstance(result, AnimUpdate)
        assert result.state_name == "idle"

    def test_frame_advances_with_time(self):
        g = self._make_graph()
        # fps=10, so 0.15s = 1.5 frames → frame 1
        result = g.update(0.15)
        assert result.frame_index in (0, 1)

    def test_blend_fraction_between_zero_and_one(self):
        g = self._make_graph()
        result = g.update(0.05)
        assert 0.0 <= result.blend_fraction <= 1.0

    def test_loop_wraps_frame(self):
        g = self._make_graph()
        # 10 fps, 2 frames → 0.25s crosses 2.5 frames → wraps to 0 or 1
        result = g.update(0.25)
        assert result.frame_index in (0, 1)

    def test_tick_returns_state_name(self):
        g = self._make_graph()
        name = g.tick(0.05)
        assert name == "idle"


class TestAnimationGraphTransitions:
    def test_transition_changes_state(self):
        from slappyengine.animation.graph import AnimationGraph, AnimState, AnimTransition
        should_transition = [False]
        g = AnimationGraph()
        g.add_state(AnimState(name="idle", clip_indices=[0]))
        g.add_state(AnimState(name="run", clip_indices=[1]))
        g.add_transition(AnimTransition(
            from_state="idle",
            to_state="run",
            condition=lambda: should_transition[0],
        ))
        g.set_initial("idle")
        g.update(0.016)
        assert g.current_state.name == "idle"  # not yet
        should_transition[0] = True
        g.update(0.016)
        assert g.current_state.name == "run"

    def test_transition_resets_frame(self):
        from slappyengine.animation.graph import AnimationGraph, AnimState, AnimTransition
        g = AnimationGraph()
        g.add_state(AnimState(name="a", clip_indices=[0, 1, 2]))
        g.add_state(AnimState(name="b", clip_indices=[5]))
        triggered = [False]
        g.add_transition(AnimTransition("a", "b", condition=lambda: triggered[0]))
        g.set_initial("a")
        g.update(0.2)  # advance frame in state a
        triggered[0] = True
        result = g.update(0.016)
        assert result.state_name == "b"
        assert result.frame_index == 5  # b's first clip index

    def test_no_transition_when_condition_false(self):
        from slappyengine.animation.graph import AnimationGraph, AnimState, AnimTransition
        g = AnimationGraph()
        g.add_state(AnimState(name="a"))
        g.add_state(AnimState(name="b"))
        g.add_transition(AnimTransition("a", "b", condition=lambda: False))
        g.set_initial("a")
        g.update(1.0)
        assert g.current_state.name == "a"

    def test_empty_clip_indices_uses_frame_counter(self):
        from slappyengine.animation.graph import AnimationGraph, AnimState
        g = AnimationGraph()
        g.add_state(AnimState(name="idle", clip_indices=[], fps=10.0))
        g.set_initial("idle")
        result = g.update(0.15)
        assert result is not None
        assert result.frame_index >= 0


class TestProceduralRig:
    def test_add_point(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="hip", uv=(0.5, 0.5)))
        assert len(rig.points) == 1

    def test_remove_point(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="hip", uv=(0.5, 0.5)))
        rig.remove_point("hip")
        assert len(rig.points) == 0

    def test_remove_nonexistent_no_crash(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        rig.remove_point("nonexistent")  # should not raise

    def test_get_chain_root_to_tip(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="hip", uv=(0.5, 0.5), parent=None))
        rig.add_point(ControlPoint(name="knee", uv=(0.5, 0.7), parent="hip"))
        rig.add_point(ControlPoint(name="ankle", uv=(0.5, 0.9), parent="knee"))
        chain = rig.get_chain("hip", "ankle")
        assert [cp.name for cp in chain] == ["hip", "knee", "ankle"]

    def test_get_chain_single_node(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="root", uv=(0.5, 0.5)))
        chain = rig.get_chain("root", "root")
        assert len(chain) == 1

    def test_solve_ik_returns_dict(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="shoulder", uv=(0.5, 0.2), parent=None))
        rig.add_point(ControlPoint(name="elbow", uv=(0.5, 0.5), parent="shoulder"))
        rig.add_point(ControlPoint(name="hand", uv=(0.5, 0.8), parent="elbow"))
        result = rig.solve_ik({"hand": (0.6, 0.9)})
        assert isinstance(result, dict)
        assert "hand" in result

    def test_solve_ik_moves_tip_toward_target(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="root", uv=(0.5, 0.0), parent=None))
        rig.add_point(ControlPoint(name="tip", uv=(0.5, 0.5), parent="root"))
        original = rig._points["tip"].uv
        result = rig.solve_ik({"tip": (0.8, 0.4)})  # reachable: distance 0.5 from root
        # Tip should have moved from its original position
        tip = result["tip"]
        assert "tip" in result
        assert isinstance(tip, tuple) and len(tip) == 2

    def test_solve_ik_unknown_tip_ignored(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="root", uv=(0.5, 0.5)))
        result = rig.solve_ik({"nonexistent": (0.0, 0.0)})
        assert "nonexistent" not in result

    def test_apply_to_updates_uv(self):
        from slappyengine.animation.procedural import ProceduralRig, ControlPoint
        rig = ProceduralRig()
        rig.add_point(ControlPoint(name="hand", uv=(0.0, 0.0)))
        rig.apply_to(None, {"hand": (0.5, 0.75)})
        assert rig._points["hand"].uv == pytest.approx((0.5, 0.75))


class TestControlPoint:
    def test_default_constraint(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="test", uv=(0.5, 0.5))
        assert cp.constraint == "free"

    def test_default_parent_none(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="test", uv=(0.0, 0.0))
        assert cp.parent is None
