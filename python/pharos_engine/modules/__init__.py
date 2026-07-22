"""Modules subpackage — lazy-loaded."""
from __future__ import annotations

__all__ = ["FluidParamsModule", "HealthModule", "PhysicsModule", "PixelPhysicsModule"]

_LAZY_MAP: dict[str, str] = {
    "FluidParamsModule":  ".fluid_params",
    "HealthModule":       ".health",
    "PhysicsModule":      ".physics",
    "PixelPhysicsModule": ".pixel_physics",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
