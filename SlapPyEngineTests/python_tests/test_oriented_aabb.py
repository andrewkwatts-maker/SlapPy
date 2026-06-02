"""Tests for rotation-aware AABBs on HullTree.

These exercise :meth:`HullTree._recompute_oriented_aabb` directly and the
batched path inside :meth:`HullTree.integrate_transforms`.  Before this
sprint the AABB stayed axis-aligned in body-local frame, which under-
covered rotated elongated bodies (a 128×32 chassis at 45° fits inside an
80-wide bounding box, missing contacts at the corners).
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from slappyengine.physics import hull as hull_mod
from slappyengine.physics.cell import CELL_GRID_SIZE
from slappyengine.physics.hull import HullTree


def _aabb_size(tree: HullTree, hid: int) -> tuple[float, float]:
    """Return (width, height) of hull ``hid``'s AABB."""
    x0, y0, x1, y1 = (float(v) for v in tree.aabb[hid])
    return (x1 - x0, y1 - y0)


def _spawn(tree: HullTree, csx: float, csy: float, x: float = 0.0,
           y: float = 0.0) -> int:
    return tree.spawn_root(
        x=x, y=y,
        cell_size_x=csx, cell_size_y=csy,
        mass=1.0, inertia=1.0, material_id=1,
    )


# ---------------------------------------------------------------------- tests


def test_aabb_grows_at_45_degrees():
    """Non-square (128 x 32) body rotated 45 deg has a strictly larger AABB."""
    tree = HullTree()
    hid = _spawn(tree, csx=4.0, csy=1.0)  # 128 x 32 in world units.
    w0, h0 = _aabb_size(tree, hid)
    assert w0 == pytest.approx(128.0)
    assert h0 == pytest.approx(32.0)

    tree.angle[hid] = math.pi / 4.0
    tree._recompute_oriented_aabb(hid)
    w1, h1 = _aabb_size(tree, hid)

    # Corners stick out: extreme = |cos|*Wx + |sin|*Wy on each axis.
    expected = abs(math.cos(math.pi / 4.0)) * 128.0 + abs(math.sin(math.pi / 4.0)) * 32.0
    assert w1 == pytest.approx(expected, rel=1e-5)
    assert h1 == pytest.approx(expected, rel=1e-5)
    # The height (short axis) grows dramatically: was 32, now > 110.  The
    # width (long axis) shrinks because we lost most of the long edge to the
    # diagonal — but the *corner reach* (h1) is what matters for collision.
    assert h1 > h0  # corner sticks out far past the unrotated height.
    assert w1 > 32.0  # width is at least the old short-axis extent.


def test_aabb_unchanged_for_square_body():
    """A square body rotated 45 deg has a SQRT(2) larger AABB (corners stick out)."""
    tree = HullTree()
    hid = _spawn(tree, csx=2.0, csy=2.0)  # 64 x 64.
    w0, h0 = _aabb_size(tree, hid)
    assert w0 == pytest.approx(64.0)
    assert h0 == pytest.approx(64.0)

    tree.angle[hid] = math.pi / 4.0
    tree._recompute_oriented_aabb(hid)
    w1, h1 = _aabb_size(tree, hid)

    assert w1 == pytest.approx(64.0 * math.sqrt(2.0), rel=1e-5)
    assert h1 == pytest.approx(64.0 * math.sqrt(2.0), rel=1e-5)


def test_aabb_back_to_original_at_90_degrees():
    """Non-square body rotated 90 deg swaps its extents."""
    tree = HullTree()
    hid = _spawn(tree, csx=4.0, csy=1.0)  # 128 x 32.
    tree.angle[hid] = math.pi / 2.0
    tree._recompute_oriented_aabb(hid)
    w, h = _aabb_size(tree, hid)
    # Width and height swap: now 32 x 128.
    assert w == pytest.approx(32.0, abs=1e-4)
    assert h == pytest.approx(128.0, abs=1e-4)


def test_integrate_transforms_updates_aabb_after_rotation():
    """integrate(omega=pi/2, dt=1) should rotate by 90 deg and refresh AABB."""
    tree = HullTree()
    hid = _spawn(tree, csx=4.0, csy=1.0)
    tree.omega[hid] = math.pi / 2.0

    tree.integrate_transforms(1.0)

    assert float(tree.angle[hid]) == pytest.approx(math.pi / 2.0, rel=1e-5)
    w, h = _aabb_size(tree, hid)
    assert w == pytest.approx(32.0, abs=1e-4)
    assert h == pytest.approx(128.0, abs=1e-4)


def test_aabb_padding_applied(monkeypatch):
    """With AABB_PADDING = 1.0 the AABB grows by exactly 1 px on each side."""
    # Bare AABB (no padding) for a 64 x 64 unrotated square.
    tree = HullTree()
    hid = _spawn(tree, csx=2.0, csy=2.0)
    w0, h0 = _aabb_size(tree, hid)
    assert w0 == pytest.approx(64.0)
    assert h0 == pytest.approx(64.0)

    # Patch the module-level constant and recompute.
    monkeypatch.setattr(hull_mod, "AABB_PADDING", 1.0)
    tree._recompute_oriented_aabb(hid)
    w1, h1 = _aabb_size(tree, hid)
    # Half-extent grows by 1 on each side, so total width/height grow by 2.
    assert w1 == pytest.approx(w0 + 2.0)
    assert h1 == pytest.approx(h0 + 2.0)
