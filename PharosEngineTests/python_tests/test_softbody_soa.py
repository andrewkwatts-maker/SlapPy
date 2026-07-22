"""Direct unit tests for the softbody SoA primitives: NodeSoA, BeamSoA, Material.

Covers the data-only contracts of the softbody storage layer — separate
from the integrated solver/contact/render smoke tests.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from pharos_engine.softbody import MATERIALS, Material, SoftBodyWorld, load_catalog
from pharos_engine.softbody.beam import BeamSoA
from pharos_engine.softbody.node import NodeSoA


@pytest.fixture(autouse=True)
def _no_runtime_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("error", category=RuntimeWarning)
        yield


# ── NodeSoA ────────────────────────────────────────────────────────────────


def test_empty_node_soa_has_count_zero():
    s = NodeSoA()
    assert s.count == 0
    assert s.pos.shape == (0, 2)
    assert s.vel.shape == (0, 2)
    assert s.mass.shape == (0,)


def test_node_soa_append_returns_start_index():
    s = NodeSoA()
    pos = np.asarray([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32)
    start = s.append(pos=pos, mass=np.ones(2, dtype=np.float32),
                     body_id=0, layer=0,
                     damping=np.full(2, 0.05, dtype=np.float32))
    assert start == 0
    assert s.count == 2
    start2 = s.append(pos=np.asarray([[2.0, 0.0]], dtype=np.float32),
                       mass=np.ones(1, dtype=np.float32),
                       body_id=1, layer=0,
                       damping=np.full(1, 0.05, dtype=np.float32))
    assert start2 == 2
    assert s.count == 3


def test_node_soa_fixed_gets_zero_inv_mass():
    s = NodeSoA()
    s.append(pos=np.asarray([[0.0, 0.0]], dtype=np.float32),
             mass=np.asarray([5.0], dtype=np.float32),
             body_id=0, layer=0,
             damping=np.asarray([0.1], dtype=np.float32),
             fixed=np.asarray([True], dtype=bool))
    # Fixed nodes have inv_mass == 0 so XPBD ignores them in scatter.
    assert s.inv_mass[0] == 0.0
    assert s.mass[0] == 5.0


def test_node_soa_free_inv_mass_is_reciprocal():
    s = NodeSoA()
    s.append(pos=np.asarray([[0.0, 0.0]], dtype=np.float32),
             mass=np.asarray([4.0], dtype=np.float32),
             body_id=0, layer=0,
             damping=np.asarray([0.0], dtype=np.float32))
    assert s.inv_mass[0] == pytest.approx(0.25, rel=1e-5)


def test_node_soa_mismatched_lengths_raise():
    s = NodeSoA()
    with pytest.raises(ValueError):
        s.append(pos=np.zeros((3, 2), dtype=np.float32),
                 mass=np.zeros(2, dtype=np.float32),  # wrong length
                 body_id=0, layer=0,
                 damping=np.zeros(3, dtype=np.float32))


def test_node_soa_prev_pos_initialised_to_pos():
    """Velocity-Verlet substep relies on prev_pos == pos on the first frame."""
    s = NodeSoA()
    pos = np.asarray([[3.0, 5.0]], dtype=np.float32)
    s.append(pos=pos, mass=np.ones(1, dtype=np.float32),
             body_id=0, layer=0,
             damping=np.zeros(1, dtype=np.float32))
    assert np.allclose(s.prev_pos, pos)


def test_node_soa_layer_propagates():
    s = NodeSoA()
    s.append(pos=np.zeros((4, 2), dtype=np.float32),
             mass=np.ones(4, dtype=np.float32),
             body_id=0, layer=2,
             damping=np.zeros(4, dtype=np.float32))
    assert (s.layer == 2).all()


# ── BeamSoA ────────────────────────────────────────────────────────────────


def test_empty_beam_soa_has_count_zero():
    s = BeamSoA()
    assert s.count == 0


def test_beam_soa_append_basic():
    s = BeamSoA()
    start = s.append(
        node_a=np.asarray([0], dtype=np.uint32),
        node_b=np.asarray([1], dtype=np.uint32),
        rest_length=np.asarray([1.0], dtype=np.float32),
        stiffness=np.asarray([1.0e9], dtype=np.float32),
        damping=np.asarray([0.02], dtype=np.float32),
        break_strain=np.asarray([0.005], dtype=np.float32),
        body_id=0,
    )
    assert start == 0
    assert s.count == 1
    assert float(s.rest_length[0]) == 1.0
    # initial_rest_length should be cloned from rest_length on append.
    assert float(s.initial_rest_length[0]) == 1.0
    assert s.broken[0] == False  # noqa: E712


def test_beam_soa_plasticity_defaults_to_zero():
    """When yield_strain/plasticity_rate aren't supplied, they default to 0."""
    s = BeamSoA()
    s.append(
        node_a=np.asarray([0, 1], dtype=np.uint32),
        node_b=np.asarray([1, 2], dtype=np.uint32),
        rest_length=np.asarray([1.0, 1.0], dtype=np.float32),
        stiffness=np.asarray([1.0e9, 1.0e9], dtype=np.float32),
        damping=np.asarray([0.02, 0.02], dtype=np.float32),
        break_strain=np.asarray([0.005, 0.005], dtype=np.float32),
        body_id=0,
    )
    assert (s.yield_strain == 0.0).all()
    assert (s.plasticity_rate == 0.0).all()


def test_beam_soa_explicit_plasticity_persisted():
    s = BeamSoA()
    s.append(
        node_a=np.asarray([0], dtype=np.uint32),
        node_b=np.asarray([1], dtype=np.uint32),
        rest_length=np.asarray([1.0], dtype=np.float32),
        stiffness=np.asarray([1.0e9], dtype=np.float32),
        damping=np.asarray([0.02], dtype=np.float32),
        break_strain=np.asarray([0.005], dtype=np.float32),
        body_id=0,
        yield_strain=np.asarray([0.002], dtype=np.float32),
        plasticity_rate=np.asarray([500.0], dtype=np.float32),
    )
    assert float(s.yield_strain[0]) == pytest.approx(0.002)
    assert float(s.plasticity_rate[0]) == pytest.approx(500.0)


def test_beam_soa_mismatched_lengths_raise():
    s = BeamSoA()
    with pytest.raises(ValueError):
        s.append(
            node_a=np.asarray([0, 1], dtype=np.uint32),
            node_b=np.asarray([1], dtype=np.uint32),  # wrong
            rest_length=np.asarray([1.0, 1.0], dtype=np.float32),
            stiffness=np.asarray([1.0e9, 1.0e9], dtype=np.float32),
            damping=np.asarray([0.02, 0.02], dtype=np.float32),
            break_strain=np.asarray([0.005, 0.005], dtype=np.float32),
            body_id=0,
        )


def test_beam_soa_two_appends_concatenate():
    s = BeamSoA()
    s.append(
        node_a=np.asarray([0], dtype=np.uint32),
        node_b=np.asarray([1], dtype=np.uint32),
        rest_length=np.asarray([1.0], dtype=np.float32),
        stiffness=np.asarray([1.0e9], dtype=np.float32),
        damping=np.asarray([0.02], dtype=np.float32),
        break_strain=np.asarray([0.005], dtype=np.float32),
        body_id=0,
    )
    second_start = s.append(
        node_a=np.asarray([2, 3], dtype=np.uint32),
        node_b=np.asarray([3, 4], dtype=np.uint32),
        rest_length=np.asarray([2.0, 2.0], dtype=np.float32),
        stiffness=np.asarray([1.0e9, 1.0e9], dtype=np.float32),
        damping=np.asarray([0.02, 0.02], dtype=np.float32),
        break_strain=np.asarray([0.005, 0.005], dtype=np.float32),
        body_id=1,
    )
    assert second_start == 1
    assert s.count == 3
    assert int(s.body_id[0]) == 0
    assert int(s.body_id[1]) == 1


# ── Material catalog ───────────────────────────────────────────────────────


def test_material_catalog_has_canonical_set():
    """MATERIALS must include the materials game code relies on."""
    expected = {"steel", "stone", "wood", "rubber", "bone", "muscle", "skin"}
    assert expected.issubset(set(MATERIALS.keys()))


def test_each_material_has_physical_fields():
    """Every Material has the parameters the solver expects."""
    for name, mat in MATERIALS.items():
        assert isinstance(mat, Material), f"{name} is not a Material"
        assert mat.name == name
        assert mat.density > 0, f"{name}.density must be > 0"
        assert mat.stiffness > 0, f"{name}.stiffness must be > 0"
        assert 0.0 <= mat.damping <= 1.0, f"{name}.damping out of [0, 1]"
        assert mat.break_strain > 0, f"{name}.break_strain must be > 0"
        assert mat.yield_strain >= 0, f"{name}.yield_strain must be >= 0"
        # yield_strain <= break_strain (the body must yield before it breaks)
        assert mat.yield_strain <= mat.break_strain, (
            f"{name}: yield_strain {mat.yield_strain} > break_strain {mat.break_strain}"
        )


def test_steel_is_stiff_and_brittle():
    """Steel: high stiffness, low yield (rigid in elastic regime), and a
    bounded break_strain (real-engineering steel runs ~25%; ours sits well
    below that but above the silly-putty regime that caused vehicle
    chassis collapse — see config/softbody.yml comments on tuning)."""
    m = MATERIALS["steel"]
    assert m.stiffness > 1e8
    assert m.yield_strain < 0.05
    assert m.break_strain < 0.20


def test_rubber_is_soft_and_stretchy():
    """The canonical 'soft elastic' has low stiffness + high break_strain."""
    m = MATERIALS["rubber"]
    assert m.stiffness < 1e8
    assert m.break_strain > 0.1


def test_load_catalog_returns_complete_set():
    """The YAML-backed loader returns the same key set as MATERIALS."""
    cat = load_catalog()
    assert set(cat.keys()) == set(MATERIALS.keys())


def test_softbody_world_loads_with_default_config():
    """SoftBodyWorld() with no args must construct without raising."""
    w = SoftBodyWorld()
    assert w.nodes.count == 0
    assert w.beams.count == 0
    assert "default_dt" in w.config
    assert "substeps" in w.config
    assert "iters" in w.config
