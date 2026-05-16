"""Extension shim — re-exports from playslap.fluid_sim.

This module's canonical home is playslap.ext.fluid_sim.
Import via either path; both are supported.
"""
from playslap.fluid_sim import (
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
