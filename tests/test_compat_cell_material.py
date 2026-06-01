"""Regression test pinning the Phase D step 6 unblock port.

``CellMaterial`` and ``cell_material_for`` moved from
``slappyengine.deform_modes`` into ``slappyengine._compat`` so the five
legacy ``physics/*`` consumers (``body.py``, ``boundary_exchange.py``,
``pressure_multigrid.py``, ``scene_loader.py``, ``world.py``) survive
the eventual deletion of ``deform_modes.py``.

This test asserts that:

(a) ``CellMaterial`` constructs with no args and the defaults match the
    original ``deform_modes.CellMaterial`` field-by-field;
(b) every field's runtime type matches the dataclass annotation
    (catches accidental int/float swaps that would corrupt the
    ``_pack_params`` WGSL upload);
(c) ``cell_material_for("sand")`` returns a ``CellMaterial`` instance.
"""
from __future__ import annotations

import dataclasses

import pytest

from slappyengine._compat import CellMaterial, cell_material_for


# Expected default values for every field on the CellMaterial dataclass.
# Sourced verbatim from python/slappyengine/deform_modes.py (the
# pre-port reference) so the port stays a true verbatim copy.
_EXPECTED_DEFAULTS = {
    # Mechanical
    "E": 80.0,
    "wave_crossing_frames": 8.0,
    "Y": 0.20,
    "brittle_modulus": 999.0,
    "viscosity": 0.95,
    "torn_damping": 0.999,
    "density_rho": 1.0,
    "restitution": 0.30,
    "restitution_velocity_threshold": 0.0,
    "static_friction_coefficient": 0.4,
    "kinetic_friction_coefficient": 0.3,
    # Bonding / fracture
    "bond_intact_threshold": 0.7,
    "bond_intact_slope": 3.0,
    "brittle_damage_rate": 18.0,
    "brittle_tear_rate": 15.0,
    "brittle_bond_loss_rate": 12.0,
    "brittle_stretch_amplification": 3.0,
    "ductile_plastic_strain_rate": 0.4,
    "ductile_poisson_ratio": 0.5,
    "ductile_damage_rate": 3.0,
    "tear_strength": 999.0,
    "tear_growth_rate": 8.0,
    "remold_rate": 0.0,
    # Thermal
    "melt_point": 9.0,
    "melt_anneal_rate": 0.98,
    "melt_viscous_damping": 0.85,
    "thermal_k": 4.0,
    "emissivity": 0.002,
    "thermal_softening_coefficient": 0.08,
    "damage_weakening_coefficient": 0.6,
    "heat_strain_energy_factor": 2.0,
    "initial_heat": 0.0,
    # Fluid
    "is_fluid": False,
    "fluid_pressure_coupling": 0.5,
    "fluid_pressure_smoothing": 0.20,
    "fluid_pressure_decay": 0.99,
    "fluid_projection_iters": 10,
    "use_multigrid": False,
    # Rendering
    "radiance": 0.0,
    "noise_overlay_amplitude": 0.0,
    "noise_overlay_color": (255, 255, 255),
    "foam_amplitude": 0.0,
    "ripple_amplitude": 0.0,
}


def test_cell_material_constructs_with_no_args_and_defaults_match() -> None:
    """Bare ``CellMaterial()`` returns an instance whose every field
    equals the verbatim default ported from ``deform_modes``."""
    cm = CellMaterial()
    for field_name, expected_value in _EXPECTED_DEFAULTS.items():
        actual = getattr(cm, field_name)
        assert actual == expected_value, (
            f"CellMaterial.{field_name} = {actual!r}, "
            f"expected {expected_value!r}"
        )


def test_cell_material_field_set_is_complete() -> None:
    """The dataclass field set matches the expected key set exactly —
    no fields added that the WGSL uploader doesn't know about, none
    dropped that the uploader needs."""
    actual_fields = {f.name for f in dataclasses.fields(CellMaterial)}
    expected_fields = set(_EXPECTED_DEFAULTS.keys())
    assert actual_fields == expected_fields, (
        f"Field set diff: extra={actual_fields - expected_fields}, "
        f"missing={expected_fields - actual_fields}"
    )


def test_cell_material_field_types_preserved() -> None:
    """Each field's runtime value type matches the dataclass annotation,
    so the ``_pack_params`` WGSL upload doesn't get int-where-float or
    float-where-bool corruption."""
    cm = CellMaterial()
    type_map = {
        bool: bool,
        int: int,
        float: float,
        tuple: tuple,
    }
    for field_name, expected_value in _EXPECTED_DEFAULTS.items():
        actual = getattr(cm, field_name)
        # ``isinstance(True, int)`` is True in Python, so check bool first.
        if isinstance(expected_value, bool):
            assert isinstance(actual, bool), (
                f"{field_name} should be bool, got {type(actual).__name__}"
            )
        elif isinstance(expected_value, int) and not isinstance(expected_value, bool):
            assert isinstance(actual, int) and not isinstance(actual, bool), (
                f"{field_name} should be int, got {type(actual).__name__}"
            )
        elif isinstance(expected_value, float):
            assert isinstance(actual, float), (
                f"{field_name} should be float, got {type(actual).__name__}"
            )
        elif isinstance(expected_value, tuple):
            assert isinstance(actual, tuple), (
                f"{field_name} should be tuple, got {type(actual).__name__}"
            )
            assert len(actual) == len(expected_value), (
                f"{field_name} tuple len mismatch"
            )
        else:
            pytest.fail(
                f"Unknown expected type for {field_name}: {type(expected_value)}"
            )


def test_cell_material_for_sand_returns_cell_material() -> None:
    """``cell_material_for("sand")`` resolves the built-in ``SAND``
    preset to its attached ``CellMaterial`` instance."""
    mat = cell_material_for("sand")
    assert mat is not None, "cell_material_for('sand') returned None"
    assert isinstance(mat, CellMaterial), (
        f"Expected CellMaterial, got {type(mat).__name__}"
    )


def test_cell_material_bond_strength_alias_matches_restitution() -> None:
    """Back-compat alias: ``bond_strength`` is a read-only proxy for
    ``restitution`` (preserved from the original dataclass surface)."""
    cm = CellMaterial(restitution=0.42)
    assert cm.bond_strength == pytest.approx(0.42)
