"""Extension shim — re-exports from slappyengine.fluid_sim.

This module's canonical home is SlapPyEngine.ext.fluid_sim.
Import via either path; both are supported.
"""
from slappyengine.fluid_sim import (
    FluidSimConfig,
    GlobalFluidSim,
    fog_config,
    water_config,
    smoke_config,
)

__all__ = [
    "FluidSimConfig",
    "GlobalFluidSim",
    "fog_config",
    "water_config",
    "smoke_config",
]
