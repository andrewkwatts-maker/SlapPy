"""Compute subpackage — lazy-loaded to avoid eager wgpu/numpy imports."""
from __future__ import annotations

__all__ = [
    "AABB",
    "AssetComputeAPI",
    "ComputePass",
    "ComputePipeline",
    "PixelAPI",
    "PixelMutator",
    "ReadbackBuffer",
    "SpatialCompute",
    "StatsCompute",
    "StatsResult",
]

_LAZY_MAP: dict[str, str] = {
    "AABB":             ".spatial",
    "AssetComputeAPI":  ".asset_compute",
    "ComputePass":      ".pipeline",
    "ComputePipeline":  ".pipeline",
    "PixelAPI":         ".asset_compute",
    "PixelMutator":     ".mutator",
    "ReadbackBuffer":   ".readback",
    "SpatialCompute":   ".spatial",
    "StatsCompute":     ".stats",
    "StatsResult":      ".stats",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
