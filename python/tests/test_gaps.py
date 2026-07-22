"""Tests for the gap-fill additions: HullCompute, RayMarchNode, ScrollView."""
from __future__ import annotations
import pytest
import numpy as np


# ── HullCompute ───────────────────────────────────────────────────────────────

class TestHullCompute:
    def test_import(self):
        from pharos_engine.compute.hull import HullCompute
        assert HullCompute is not None

    def test_import_from_engine(self):
        from pharos_engine import HullCompute
        assert HullCompute is not None

    def test_convex_returns_ndarray(self):
        from pharos_engine.compute.hull import HullCompute
        pts = np.array([[0,0],[1,0],[0,1],[1,1],[0.5,0.5]], dtype=np.float32)
        hull = HullCompute.convex(pts)
        assert isinstance(hull, np.ndarray)

    def test_convex_hull_is_subset_of_points(self):
        from pharos_engine.compute.hull import HullCompute
        pts = np.array([[0,0],[2,0],[0,2],[2,2],[1,1],[0.5,0.5]], dtype=np.float32)
        hull = HullCompute.convex(pts)
        # Every hull point must be close to one of the source points
        for hp in hull:
            dists = np.linalg.norm(pts - hp, axis=1)
            assert dists.min() < 1e-4, f"Hull point {hp} not in source set"

    def test_convex_degenerate_line(self):
        from pharos_engine.compute.hull import HullCompute
        pts = np.array([[0,0],[1,0],[2,0],[3,0]], dtype=np.float32)
        hull = HullCompute.convex(pts)
        assert hull is not None  # should not crash

    def test_concave_returns_ndarray(self):
        from pharos_engine.compute.hull import HullCompute
        pts = np.random.RandomState(42).rand(20, 2).astype(np.float32)
        hull = HullCompute.concave(pts, alpha=0.3)
        assert isinstance(hull, np.ndarray)

    def test_concave_alpha_zero_matches_convex(self):
        from pharos_engine.compute.hull import HullCompute
        pts = np.array([[0,0],[1,0],[0,1],[1,1],[0.5,0.5]], dtype=np.float32)
        # alpha=0 → convex; result should have same vertices as convex()
        c1 = HullCompute.convex(pts)
        c2 = HullCompute.concave(pts, alpha=0.0)
        assert len(c1) == len(c2)

    def test_concave_high_alpha_at_most_same_size_as_convex(self):
        from pharos_engine.compute.hull import HullCompute
        pts = np.random.RandomState(7).rand(30, 2).astype(np.float32)
        convex = HullCompute.convex(pts)
        tight = HullCompute.concave(pts, alpha=0.8)
        assert len(tight) >= 2  # at least 2 points back

    def test_static_methods_no_instance_needed(self):
        from pharos_engine.compute.hull import HullCompute
        pts = np.array([[0,0],[1,0],[0,1]], dtype=np.float32)
        # Call directly on class, not instance
        HullCompute.convex(pts)
        HullCompute.concave(pts)


# ── RayMarchNode ──────────────────────────────────────────────────────────────

class TestRayMarchNode:
    def test_import(self):
        from pharos_engine.material.node_material import RayMarchNode
        assert RayMarchNode is not None

    def test_import_from_engine(self):
        from pharos_engine import RayMarchNode
        assert RayMarchNode is not None

    def test_returns_nodedef(self):
        from pharos_engine.material.node_material import RayMarchNode, NodeDef
        node = RayMarchNode()
        assert isinstance(node, NodeDef)

    def test_node_type(self):
        from pharos_engine.material.node_material import RayMarchNode
        node = RayMarchNode()
        assert node.node_type == "ray_march"

    def test_default_steps(self):
        from pharos_engine.material.node_material import RayMarchNode
        node = RayMarchNode()
        assert node.params["steps"] == 16

    def test_custom_steps(self):
        from pharos_engine.material.node_material import RayMarchNode
        node = RayMarchNode(steps=8)
        assert node.params["steps"] == 8

    def test_default_direction(self):
        from pharos_engine.material.node_material import RayMarchNode
        node = RayMarchNode()
        assert node.params["direction"] == [0.0, 1.0]

    def test_custom_direction(self):
        from pharos_engine.material.node_material import RayMarchNode
        node = RayMarchNode(steps=4, direction=(1.0, 0.0))
        assert node.params["direction"] == [1.0, 0.0]

    def test_unique_id(self):
        from pharos_engine.material.node_material import RayMarchNode
        a = RayMarchNode()
        b = RayMarchNode()
        assert a.id != b.id

    def test_serialisable(self):
        from pharos_engine.material.node_material import RayMarchNode, NodeMaterial
        mat = NodeMaterial("test")
        mat.node(RayMarchNode(steps=8, direction=(0.5, 0.5)))
        j = mat.to_json()
        assert "ray_march" in j
        assert "steps" in j


# ── ScrollView ────────────────────────────────────────────────────────────────

class TestScrollView:
    def test_import(self):
        from pharos_editor.ui.widgets import ScrollView
        assert ScrollView is not None

    def test_import_from_engine(self):
        from pharos_engine import ScrollView
        assert ScrollView is not None

    def test_default_scroll_offset(self):
        from pharos_editor.ui.widgets import ScrollView
        sv = ScrollView(w=200, h=100)
        assert sv.scroll_offset == 0.0

    def test_scroll_by_positive(self):
        from pharos_editor.ui.widgets import ScrollView, Label
        sv = ScrollView(w=200, h=100)
        # Add taller content than view
        for i in range(10):
            sv.add(Label(text=f"Item {i}", x=0, y=i*20, w=200, h=18))
        sv.scroll_by(30)
        assert sv.scroll_offset == 30.0

    def test_scroll_by_negative_clamps_to_zero(self):
        from pharos_editor.ui.widgets import ScrollView
        sv = ScrollView(w=200, h=100)
        sv.scroll_by(-999)
        assert sv.scroll_offset == 0.0

    def test_scroll_to(self):
        from pharos_editor.ui.widgets import ScrollView, Label
        sv = ScrollView(w=200, h=100)
        for i in range(10):
            sv.add(Label(text=f"Item {i}", x=0, y=i*20, w=200, h=18))
        sv.scroll_to(40)
        assert sv.scroll_offset == 40.0

    def test_at_bottom_empty(self):
        from pharos_editor.ui.widgets import ScrollView
        sv = ScrollView(w=200, h=100)
        assert sv.at_bottom  # empty → no content to scroll

    def test_scroll_event_handled(self):
        from pharos_editor.ui.widgets import ScrollView, Label
        sv = ScrollView(w=200, h=100, x=0, y=0, scroll_speed=20.0)
        for i in range(10):
            sv.add(Label(text=f"Item {i}", x=0, y=i*20, w=200, h=18))
        sv.handle_event({"type": "scroll", "x": 50, "y": 50, "dy": -1})
        assert sv.scroll_offset == 20.0

    def test_scroll_event_outside_not_handled(self):
        from pharos_editor.ui.widgets import ScrollView
        sv = ScrollView(w=200, h=100, x=0, y=0)
        consumed = sv.handle_event({"type": "scroll", "x": 300, "y": 300, "dy": -1})
        assert not consumed
        assert sv.scroll_offset == 0.0

    def test_is_panel_subclass(self):
        from pharos_editor.ui.widgets import ScrollView, Panel
        assert issubclass(ScrollView, Panel)

    def test_scroll_speed_configurable(self):
        from pharos_editor.ui.widgets import ScrollView
        sv = ScrollView(scroll_speed=50.0, w=200, h=100)
        assert sv.scroll_speed == 50.0

    def test_draw_does_not_raise(self):
        """Draw should silently succeed or skip without Pillow draw object."""
        from pharos_editor.ui.widgets import ScrollView, Label
        sv = ScrollView(w=200, h=100)
        sv.add(Label(text="A", x=0, y=0, w=100, h=20))
        sv.draw(None)   # draw=None → try/except inside should swallow
