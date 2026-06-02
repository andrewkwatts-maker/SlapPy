"""Headless tests for ControlPoint and ProceduralRig."""
from __future__ import annotations
import sys
from unittest.mock import MagicMock
import pytest

sys.modules.setdefault("wgpu", MagicMock())
sys.modules.setdefault("slappyengine.compute.asset_compute", MagicMock())


# =============================================================================
# ControlPoint
# =============================================================================

class TestControlPointInit:
    def test_name_stored(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="root", uv=(0.5, 0.5))
        assert cp.name == "root"

    def test_uv_stored(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="tip", uv=(0.1, 0.9))
        assert cp.uv == (0.1, 0.9)

    def test_parent_none_by_default(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="a", uv=(0.0, 0.0))
        assert cp.parent is None

    def test_parent_set(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="child", uv=(0.0, 0.0), parent="root")
        assert cp.parent == "root"

    def test_constraint_free_by_default(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="a", uv=(0.0, 0.0))
        assert cp.constraint == "free"

    def test_constraint_hinge(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="a", uv=(0.0, 0.0), constraint="hinge")
        assert cp.constraint == "hinge"

    def test_constraint_slider(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="a", uv=(0.0, 0.0), constraint="slider")
        assert cp.constraint == "slider"

    def test_min_angle_default(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="a", uv=(0.0, 0.0))
        assert cp.min_angle == pytest.approx(-180.0)

    def test_max_angle_default(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="a", uv=(0.0, 0.0))
        assert cp.max_angle == pytest.approx(180.0)

    def test_custom_angle_limits(self):
        from slappyengine.animation.procedural import ControlPoint
        cp = ControlPoint(name="a", uv=(0.0, 0.0), min_angle=-45.0, max_angle=90.0)
        assert cp.min_angle == pytest.approx(-45.0)
        assert cp.max_angle == pytest.approx(90.0)


# =============================================================================
# ProceduralRig — add/remove/points
# =============================================================================

class TestProceduralRigAddRemove:
    def test_init_empty(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        assert rig.points == []

    def test_add_point(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        cp = ControlPoint("root", (0.5, 0.5))
        rig.add_point(cp)
        assert len(rig.points) == 1

    def test_add_point_stored_by_name(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        cp = ControlPoint("hip", (0.5, 0.5))
        rig.add_point(cp)
        assert rig._points["hip"] is cp

    def test_add_multiple_points(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        for name in ["a", "b", "c"]:
            rig.add_point(ControlPoint(name, (0.0, 0.0)))
        assert len(rig.points) == 3

    def test_remove_point(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("x", (0.0, 0.0)))
        rig.remove_point("x")
        assert len(rig.points) == 0

    def test_remove_nonexistent_no_error(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        rig.remove_point("ghost")  # must not raise

    def test_overwrite_same_name(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("a", (0.1, 0.1)))
        rig.add_point(ControlPoint("a", (0.9, 0.9)))
        assert rig._points["a"].uv == (0.9, 0.9)


# =============================================================================
# ProceduralRig — get_chain
# =============================================================================

class TestGetChain:
    def _three_node_rig(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("root", (0.0, 0.0)))
        rig.add_point(ControlPoint("mid",  (0.5, 0.0), parent="root"))
        rig.add_point(ControlPoint("tip",  (1.0, 0.0), parent="mid"))
        return rig

    def test_chain_length(self):
        rig = self._three_node_rig()
        chain = rig.get_chain("root", "tip")
        assert len(chain) == 3

    def test_chain_order_root_first(self):
        rig = self._three_node_rig()
        chain = rig.get_chain("root", "tip")
        assert chain[0].name == "root"

    def test_chain_order_tip_last(self):
        rig = self._three_node_rig()
        chain = rig.get_chain("root", "tip")
        assert chain[-1].name == "tip"

    def test_chain_middle_node(self):
        rig = self._three_node_rig()
        chain = rig.get_chain("root", "tip")
        assert chain[1].name == "mid"

    def test_chain_root_to_root(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("root", (0.0, 0.0)))
        chain = rig.get_chain("root", "root")
        assert len(chain) == 1
        assert chain[0].name == "root"

    def test_chain_missing_tip_returns_empty(self):
        rig = self._three_node_rig()
        chain = rig.get_chain("root", "ghost")
        assert chain == []

    def test_partial_chain_stops_at_root(self):
        rig = self._three_node_rig()
        chain = rig.get_chain("mid", "tip")
        assert len(chain) == 2
        assert chain[0].name == "mid"
        assert chain[1].name == "tip"

    def test_chain_tip_not_connected_to_root(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("root", (0.0, 0.0)))
        rig.add_point(ControlPoint("tip",  (1.0, 0.0)))  # no parent link
        chain = rig.get_chain("root", "tip")
        # tip has no parent, chain will only contain tip (traversal stops before reaching root)
        assert len(chain) >= 1


# =============================================================================
# ProceduralRig — _find_root
# =============================================================================

class TestFindRoot:
    def test_single_node_is_root(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("root", (0.0, 0.0)))
        assert rig._find_root("root") == "root"

    def test_root_found_from_tip(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("r", (0.0, 0.0)))
        rig.add_point(ControlPoint("m", (0.5, 0.0), parent="r"))
        rig.add_point(ControlPoint("t", (1.0, 0.0), parent="m"))
        assert rig._find_root("t") == "r"

    def test_root_found_from_mid(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("r", (0.0, 0.0)))
        rig.add_point(ControlPoint("m", (0.5, 0.0), parent="r"))
        rig.add_point(ControlPoint("t", (1.0, 0.0), parent="m"))
        assert rig._find_root("m") == "r"

    def test_missing_name_returns_none(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        assert rig._find_root("ghost") is None

    def test_cycle_returns_none(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("a", (0.0, 0.0), parent="b"))
        rig.add_point(ControlPoint("b", (0.5, 0.0), parent="a"))
        result = rig._find_root("a")
        assert result is None

    def test_dangling_parent_treated_as_root(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("child", (0.5, 0.0), parent="missing_parent"))
        # parent not in rig → child is effectively the root
        assert rig._find_root("child") == "child"


# =============================================================================
# ProceduralRig — _simple_stretch
# =============================================================================

class TestSimpleStretch:
    def test_empty_positions_returns_empty(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        result = rig._simple_stretch([], (1.0, 1.0))
        assert result == []

    def test_single_position_moved_to_target(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        result = rig._simple_stretch([(0.0, 0.0)], (0.7, 0.8))
        assert result[-1] == (0.7, 0.8)

    def test_two_positions_last_moved(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        positions = [(0.0, 0.0), (0.5, 0.0)]
        result = rig._simple_stretch(positions, (1.0, 0.5))
        assert result[-1] == (1.0, 0.5)

    def test_first_position_unchanged(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        positions = [(0.1, 0.2), (0.5, 0.5), (0.9, 0.8)]
        result = rig._simple_stretch(positions, (2.0, 2.0))
        assert result[0] == (0.1, 0.2)

    def test_middle_positions_unchanged(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        positions = [(0.0, 0.0), (0.3, 0.1), (0.6, 0.0), (1.0, 0.0)]
        result = rig._simple_stretch(positions, (5.0, 5.0))
        assert result[1] == (0.3, 0.1)
        assert result[2] == (0.6, 0.0)

    def test_length_preserved(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        positions = [(0.0, 0.0), (0.5, 0.0), (1.0, 0.0)]
        result = rig._simple_stretch(positions, (2.0, 0.0))
        assert len(result) == 3

    def test_does_not_mutate_input(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        positions = [(0.0, 0.0), (1.0, 0.0)]
        original = list(positions)
        rig._simple_stretch(positions, (9.0, 9.0))
        assert positions == original


# =============================================================================
# ProceduralRig — solve_ik (fallback path, no _core)
# =============================================================================

class TestSolveIk:
    def _two_joint_rig(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("root", (0.0, 0.0)))
        rig.add_point(ControlPoint("tip",  (1.0, 0.0), parent="root"))
        return rig

    def test_returns_dict(self):
        rig = self._two_joint_rig()
        result = rig.solve_ik({"tip": (0.5, 0.5)})
        assert isinstance(result, dict)

    def test_all_points_in_result(self):
        rig = self._two_joint_rig()
        result = rig.solve_ik({"tip": (0.5, 0.5)})
        assert "root" in result
        assert "tip" in result

    def test_tip_result_is_tuple(self):
        rig = self._two_joint_rig()
        result = rig.solve_ik({"tip": (0.8, 0.4)})
        assert isinstance(result["tip"], tuple)
        assert len(result["tip"]) == 2

    def test_root_position_unchanged(self):
        rig = self._two_joint_rig()
        result = rig.solve_ik({"tip": (0.8, 0.4)})
        assert result["root"] == pytest.approx((0.0, 0.0))

    def test_empty_targets_returns_base_uvs(self):
        rig = self._two_joint_rig()
        result = rig.solve_ik({})
        assert result["root"] == pytest.approx((0.0, 0.0))
        assert result["tip"] == pytest.approx((1.0, 0.0))

    def test_unknown_target_name_skipped(self):
        rig = self._two_joint_rig()
        result = rig.solve_ik({"ghost": (9.0, 9.0)})
        assert "ghost" not in result

    def test_single_node_chain_skipped(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("alone", (0.5, 0.5)))
        result = rig.solve_ik({"alone": (0.9, 0.9)})
        # chain length < 2 → solve skipped; position stays at uv
        assert result["alone"] == pytest.approx((0.5, 0.5))


# =============================================================================
# ProceduralRig — apply_to
# =============================================================================

class TestApplyTo:
    def test_apply_updates_uv(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("a", (0.0, 0.0)))
        rig.apply_to(MagicMock(), {"a": (0.7, 0.3)})
        assert rig._points["a"].uv == (0.7, 0.3)

    def test_apply_unknown_name_no_error(self):
        from slappyengine.animation.procedural import ProceduralRig
        rig = ProceduralRig()
        rig.apply_to(MagicMock(), {"ghost": (0.5, 0.5)})  # must not raise

    def test_apply_updates_multiple(self):
        from slappyengine.animation.procedural import ControlPoint, ProceduralRig
        rig = ProceduralRig()
        rig.add_point(ControlPoint("a", (0.0, 0.0)))
        rig.add_point(ControlPoint("b", (0.0, 0.0)))
        rig.apply_to(MagicMock(), {"a": (0.1, 0.2), "b": (0.3, 0.4)})
        assert rig._points["a"].uv == (0.1, 0.2)
        assert rig._points["b"].uv == (0.3, 0.4)
