"""Compute subpackage — lazy-loaded to avoid eager wgpu/numpy imports."""
from __future__ import annotations

__all__ = [
    "ComputePass", "ComputePipeline", "ReadbackBuffer",
    "StatsCompute", "StatsResult",
    "SpatialCompute", "AABB",
    "PixelMutator",
    "AssetComputeAPI", "PixelAPI",
]

_LAZY_MAP: dict[str, str] = {
    "ComputePass":      ".pipeline",
    "ComputePipeline":  ".pipeline",
    "ReadbackBuffer":   ".readback",
    "StatsCompute":     ".stats",
    "StatsResult":      ".stats",
    "SpatialCompute":   ".spatial",
    "AABB":             ".spatial",
    "PixelMutator":     ".mutator",
    "AssetComputeAPI":  ".asset_compute",
    "PixelAPI":         ".asset_compute",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
