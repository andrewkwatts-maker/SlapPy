"""
Tests for the FABRIK inverse-kinematics solver exposed by SlapPyEngine._core.

All tests use pytest.importorskip so the suite degrades gracefully when the
Rust extension has not been built yet (i.e. before `maturin develop` is run).
"""
import math
import pytest


# ---------------------------------------------------------------------------
# test_compute_bone_lengths_basic
# ---------------------------------------------------------------------------

def test_compute_bone_lengths_basic():
    _core = pytest.importorskip("SlapPyEngine._core")
    positions = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    lengths = _core.compute_bone_lengths(positions)
    assert len(lengths) == 2
    assert abs(lengths[0] - 1.0) < 0.001
    assert abs(lengths[1] - 1.0) < 0.001


# ---------------------------------------------------------------------------
# test_compute_bone_lengths_diagonal
# ---------------------------------------------------------------------------

def test_compute_bone_lengths_diagonal():
    _core = pytest.importorskip("SlapPyEngine._core")
    positions = [(0.0, 0.0), (1.0, 1.0)]
    lengths = _core.compute_bone_lengths(positions)
    assert abs(lengths[0] - math.sqrt(2.0)) < 0.001


# ---------------------------------------------------------------------------
# test_solve_ik_reaches_target
# ---------------------------------------------------------------------------

def test_solve_ik_reaches_target():
    """End effector should reach the target within tolerance."""
    _core = pytest.importorskip("SlapPyEngine._core")
    # 2-link chain, each bone length 1.0
    chain = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    lengths = _core.compute_bone_lengths(chain)
    target = (1.0, 1.0)
    solved = _core.solve_ik(chain, target, lengths, max_iter=20, tolerance=0.001)
    assert len(solved) == 3
    end = solved[-1]
    dist = math.sqrt((end[0] - target[0])**2 + (end[1] - target[1])**2)
    assert dist < 0.01, f"End effector didn't reach target: dist={dist:.4f}"


# ---------------------------------------------------------------------------
# test_solve_ik_root_stays_fixed
# ---------------------------------------------------------------------------

def test_solve_ik_root_stays_fixed():
    """Root joint must not move after solving."""
    _core = pytest.importorskip("SlapPyEngine._core")
    chain = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)]
    lengths = _core.compute_bone_lengths(chain)
    target = (0.5, 1.5)
    solved = _core.solve_ik(chain, target, lengths)
    assert abs(solved[0][0] - 0.0) < 0.001
    assert abs(solved[0][1] - 0.0) < 0.001


# ---------------------------------------------------------------------------
# test_solve_ik_bone_lengths_preserved
# ---------------------------------------------------------------------------

def test_solve_ik_bone_lengths_preserved():
    """Each bone length should be approximately preserved after solving."""
    _core = pytest.importorskip("SlapPyEngine._core")
    chain = [(0.0, 0.0), (0.0, 1.0), (0.0, 2.0), (0.0, 3.0)]
    lengths = _core.compute_bone_lengths(chain)
    target = (1.0, 2.0)
    solved = _core.solve_ik(chain, target, lengths, max_iter=30, tolerance=0.001)
    for i in range(len(lengths)):
        dx = solved[i + 1][0] - solved[i][0]
        dy = solved[i + 1][1] - solved[i][1]
        actual_len = math.sqrt(dx * dx + dy * dy)
        assert abs(actual_len - lengths[i]) < 0.02, (
            f"Bone {i} length changed: {actual_len:.3f} vs {lengths[i]:.3f}"
        )


# ---------------------------------------------------------------------------
# test_solve_ik_unreachable_target
# ---------------------------------------------------------------------------

def test_solve_ik_unreachable_target():
    """When target is beyond reach, chain should stretch toward it without crashing."""
    _core = pytest.importorskip("SlapPyEngine._core")
    chain = [(0.0, 0.0), (1.0, 0.0)]
    lengths = _core.compute_bone_lengths(chain)
    target = (100.0, 0.0)  # far beyond reach
    solved = _core.solve_ik(chain, target, lengths)
    assert len(solved) == 2
    # Chain should stretch toward target
    assert solved[1][0] > solved[0][0]


# ---------------------------------------------------------------------------
# test_solve_ik_three_link
# ---------------------------------------------------------------------------

def test_solve_ik_three_link():
    """Three-link chain IK test."""
    _core = pytest.importorskip("SlapPyEngine._core")
    chain = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
    lengths = _core.compute_bone_lengths(chain)
    target = (0.0, 3.0)  # 90-degree rotation
    solved = _core.solve_ik(chain, target, lengths, max_iter=50, tolerance=0.001)
    end = solved[-1]
    dist = math.sqrt((end[0] - target[0])**2 + (end[1] - target[1])**2)
    assert dist < 0.05


# ---------------------------------------------------------------------------
# test_solve_ik_already_at_target
# ---------------------------------------------------------------------------

def test_solve_ik_already_at_target():
    """No-op: end effector is already at target."""
    _core = pytest.importorskip("SlapPyEngine._core")
    chain = [(0.0, 0.0), (1.0, 0.0)]
    lengths = _core.compute_bone_lengths(chain)
    target = (1.0, 0.0)
    solved = _core.solve_ik(chain, target, lengths)
    assert abs(solved[-1][0] - 1.0) < 0.001
    assert abs(solved[-1][1] - 0.0) < 0.001
