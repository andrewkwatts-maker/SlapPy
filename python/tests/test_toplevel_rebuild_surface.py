"""Lock the friendly top-level rebuild surface that users discover with
``import pharos_engine``.

These names are lazily re-exported from the new ``softbody`` / ``fluid``
/ ``dynamics`` / ``studio`` subpackages. Each entry exists so the user
can write ``pharos_engine.softbody_stage(...)``, ``pharos_engine.kick(...)``,
``pharos_engine.make_humanoid(...)`` etc. without knowing which submodule
to import from.
"""
from __future__ import annotations

import pytest


@pytest.mark.parametrize("name", [
    # Studio — scene scaffolding
    "Stage", "softbody_stage", "fluid_stage", "fluid_with_softbody_stage",
    "humanoid_stage", "record", "output_path", "terrain_overlay",
    "kick", "anchor", "centroid", "translate",
    # Softbody
    "SoftBodyWorld", "BodyMeta", "make_lattice_body",
    "make_layered_creature", "step",
    "SoftBodyRenderer", "SoftBodyRenderConfig",
    # Fluid
    "FluidWorld", "FluidMaterial", "FluidRenderer", "FluidRenderConfig",
    "pbf_step", "apply_fluid_buoyancy",
    # Dynamics
    "Body", "JointSpec", "make_distance", "make_spring", "make_motor",
    "make_humanoid", "place_feet_on_terrain", "wrap_in_flesh",
    "HumanoidSkeleton", "HumanoidProportions",
])
def test_toplevel_surface_resolves(name: str):
    """Each name must resolve when accessed on the top-level package."""
    import pharos_engine
    val = getattr(pharos_engine, name)
    assert val is not None
    # Lazy attrs are cached on access; the second lookup should hit the cache
    assert getattr(pharos_engine, name) is val


def test_friendly_demo_one_call_works():
    """The shortest demo a user could write: import, stage, body, record."""
    import pharos_engine as eng

    stage = eng.softbody_stage(view_box=(-1, -1, 1, 4), width=64, height=48,
                                 floor_y=3.0)
    body = eng.make_lattice_body(stage.world, "wood",
                                  width_cells=2, height_cells=2, cell_size=0.10,
                                  position=(-0.10, 1.0))
    body.kick(stage.world, vy=2.0)

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        out = eng.record(stage, frames=4, output=Path(td) / "demo.gif")
        assert out.exists()
        assert out.stat().st_size > 0
