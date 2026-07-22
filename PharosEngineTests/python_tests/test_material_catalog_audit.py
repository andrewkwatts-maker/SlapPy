"""Material catalog audit — guards the softbody + fluid material catalogs.

These tests don't simulate anything; they assert structural invariants on
``config/softbody.yml`` and ``config/fluid.yml`` so that a fat-fingered
edit (e.g. plasticity_rate=10000 on steel) is caught before it produces
silly-putty chassis in a demo.

Both catalogs are loaded fresh from disk via ``load_catalog()`` to
exercise the YAML round-trip path, then the in-memory ``MATERIALS``
dict is also checked.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pharos_engine.fluid.material import MATERIALS as FLUID_MATERIALS
from pharos_engine.fluid.material import FluidMaterial
from pharos_engine.fluid.material import load_catalog as load_fluid_catalog
from pharos_engine.softbody.material import MATERIALS as SOFT_MATERIALS
from pharos_engine.softbody.material import Material
from pharos_engine.softbody.material import load_catalog as load_soft_catalog


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SOFTBODY_YAML = REPO_ROOT / "config" / "softbody.yml"
FLUID_YAML = REPO_ROOT / "config" / "fluid.yml"


# ---------------------------------------------------------------------------
# Softbody catalog
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def soft_catalog() -> dict[str, Material]:
    return load_soft_catalog(SOFTBODY_YAML)


def test_softbody_catalog_nonempty(soft_catalog: dict[str, Material]) -> None:
    assert soft_catalog, "softbody catalog loaded empty from YAML"
    # Sanity: in-memory MATERIALS and a freshly-loaded catalog must agree.
    assert set(SOFT_MATERIALS.keys()) == set(soft_catalog.keys())


def test_softbody_densities_plausible(soft_catalog: dict[str, Material]) -> None:
    # Bound is intentionally loose: 50 kg/m^2 < d < 30000 catches typos
    # like "0.5" or "780000" without rejecting any real material.
    for name, mat in soft_catalog.items():
        assert 50.0 < mat.density < 30000.0, (
            f"softbody material {name!r} has implausible density {mat.density}"
        )


def test_softbody_yield_le_break(soft_catalog: dict[str, Material]) -> None:
    """yield_strain must come before break_strain (or coincide for brittle)."""
    for name, mat in soft_catalog.items():
        assert mat.yield_strain <= mat.break_strain, (
            f"softbody material {name!r}: yield_strain {mat.yield_strain} "
            f"> break_strain {mat.break_strain}"
        )


def test_softbody_plastic_materials_have_room_to_flow(
    soft_catalog: dict[str, Material],
) -> None:
    """Plastic materials need yield < break (strictly) so plastic flow has
    a non-degenerate strain band to operate in. yield == break with
    plasticity > 0 is a contradictory spec: the beam breaks at the same
    instant it would start to flow."""
    for name, mat in soft_catalog.items():
        if mat.plasticity_rate > 0.0:
            assert mat.yield_strain < mat.break_strain, (
                f"plastic material {name!r} has yield_strain == break_strain "
                f"({mat.yield_strain}); plasticity_rate={mat.plasticity_rate} "
                f"has no strain band to flow in"
            )


def test_softbody_brittle_materials_clean_snap(
    soft_catalog: dict[str, Material],
) -> None:
    """Brittle materials (plasticity_rate == 0) must have
    yield_strain == break_strain. Otherwise the elastic band above yield
    is wasted (no plastic flow can occur there), and worse, a beam that
    sits between yield and break confuses the renderer's damage tint."""
    for name, mat in soft_catalog.items():
        if mat.plasticity_rate == 0.0:
            assert mat.yield_strain == mat.break_strain, (
                f"brittle material {name!r} has yield_strain {mat.yield_strain} "
                f"!= break_strain {mat.break_strain}; plasticity_rate==0 "
                f"requires a clean snap"
            )


def test_softbody_steel_is_ductile_not_silly_putty(
    soft_catalog: dict[str, Material],
) -> None:
    """Regression: steel.plasticity_rate was 10000 paired with yield_strain
    0.002 — the chassis flowed under wheel torque alone (silly-putty).

    The fix is twofold:
      * yield_strain must be high enough that normal driving loads (strain
        ~0.5%) sit safely below it.
      * plasticity_rate must be bounded — it can be higher than a pure
        creep rate to absorb impulsive impact spikes via per-substep flow,
        but never so high that even tiny strains relax the rest length.
    """
    steel = soft_catalog["steel"]
    # Bounded but generous: the old 10000 is excluded, sensible values
    # between ~50 (slow creep) and ~3000 (fast impulse dissipation) pass.
    assert 50.0 <= steel.plasticity_rate <= 3000.0, (
        f"steel.plasticity_rate={steel.plasticity_rate} is outside the "
        f"sensible band [50, 3000] (was 10000 — silly-putty regression)"
    )
    # And there must be enough elastic headroom for normal driving loads.
    assert steel.yield_strain >= 0.005, (
        f"steel.yield_strain={steel.yield_strain} is too low; the chassis "
        f"will yield under gravity + wheel torque"
    )


def test_softbody_stiffness_ordering(
    soft_catalog: dict[str, Material],
) -> None:
    """Relative stiffness ordering steel > stone > wood > rubber must hold."""
    s = {n: m.stiffness for n, m in soft_catalog.items()}
    assert s["steel"] > s["stone"] > s["wood"] > s["rubber"], (
        f"stiffness ordering broken: steel={s['steel']:g} stone={s['stone']:g} "
        f"wood={s['wood']:g} rubber={s['rubber']:g}"
    )


def test_softbody_brittle_break_lowest(
    soft_catalog: dict[str, Material],
) -> None:
    """Brittle materials (stone) should break at lower strain than ductile
    materials (rubber). This is just a sanity ordering."""
    assert soft_catalog["stone"].break_strain < soft_catalog["rubber"].break_strain


# ---------------------------------------------------------------------------
# Fluid catalog
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def fluid_catalog() -> dict[str, FluidMaterial]:
    return load_fluid_catalog(FLUID_YAML)


def test_fluid_catalog_nonempty(fluid_catalog: dict[str, FluidMaterial]) -> None:
    assert fluid_catalog, "fluid catalog loaded empty from YAML"
    assert set(FLUID_MATERIALS.keys()) == set(fluid_catalog.keys())


def test_fluid_densities_plausible(
    fluid_catalog: dict[str, FluidMaterial],
) -> None:
    for name, mat in fluid_catalog.items():
        assert 50.0 < mat.rest_density < 30000.0, (
            f"fluid material {name!r} has implausible rest_density "
            f"{mat.rest_density}"
        )


def test_fluid_phase_change_targets_exist(
    fluid_catalog: dict[str, FluidMaterial],
) -> None:
    """Every melt_to / freeze_to name must reference another fluid material."""
    names = set(fluid_catalog.keys())
    for name, mat in fluid_catalog.items():
        if mat.melt_to:
            assert mat.melt_to in names, (
                f"fluid material {name!r} melt_to={mat.melt_to!r} is unknown"
            )
        if mat.freeze_to:
            assert mat.freeze_to in names, (
                f"fluid material {name!r} freeze_to={mat.freeze_to!r} is unknown"
            )


# ---------------------------------------------------------------------------
# Cross-catalog sanity ordering
# ---------------------------------------------------------------------------

def test_cross_catalog_density_ordering(
    soft_catalog: dict[str, Material],
    fluid_catalog: dict[str, FluidMaterial],
) -> None:
    """ice < water < stone(softbody) < steel(softbody).

    Mixes 3D fluid rest_density (kg/m^3) with 2D softbody density
    (kg/m^2). The numerical values still line up because each entry was
    populated from the real-world figure for that material — this catches
    anyone entering a wildly-wrong magnitude.
    """
    ice = fluid_catalog["ice"].rest_density
    water = fluid_catalog["water"].rest_density
    stone = soft_catalog["stone"].density
    steel = soft_catalog["steel"].density
    assert ice < water < stone < steel, (
        f"density ordering broken: ice={ice} water={water} stone={stone} "
        f"steel={steel}"
    )


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------

def test_softbody_yaml_round_trip() -> None:
    """Every key in the softbody.yml materials: section must load into a
    valid Material via load_catalog."""
    with SOFTBODY_YAML.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    section = raw.get("materials") or {}
    assert section, "softbody.yml has no materials: section"
    loaded = load_soft_catalog(SOFTBODY_YAML)
    for name in section.keys():
        assert name in loaded, f"softbody.yml key {name!r} failed to load"
        assert isinstance(loaded[name], Material)


def test_fluid_yaml_round_trip() -> None:
    """Every key in the fluid.yml materials: section must load into a
    valid FluidMaterial via load_catalog."""
    with FLUID_YAML.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    section = raw.get("materials") or {}
    assert section, "fluid.yml has no materials: section"
    loaded = load_fluid_catalog(FLUID_YAML)
    for name in section.keys():
        assert name in loaded, f"fluid.yml key {name!r} failed to load"
        assert isinstance(loaded[name], FluidMaterial)
