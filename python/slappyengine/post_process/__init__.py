"""Post-process subpackage — lazy-loaded to avoid eager wgpu imports."""
from __future__ import annotations

__all__ = [
    "PostProcessChain",
    "PostProcessPass",
    "PostProcessExecutor",
    "TAAPass",
    "GTAOPass",
    "ShadowCSM",
    "VolumetricFog",
    "cinematic_chain",
    "arcade_chain",
    "iso_strategy_chain",
]

_LAZY_MAP: dict[str, str] = {
    "PostProcessChain":    ".chain",
    "PostProcessPass":     ".chain",
    "PostProcessExecutor": ".executor",
    "TAAPass":             ".taa",
    "GTAOPass":            ".gtao",
    "ShadowCSM":           ".shadow_csm",
    "VolumetricFog":       ".volumetric_fog",
    "cinematic_chain":     ".preset_chains",
    "arcade_chain":        ".preset_chains",
    "iso_strategy_chain":  ".preset_chains",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
