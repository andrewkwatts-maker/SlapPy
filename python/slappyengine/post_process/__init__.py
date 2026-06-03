"""Post-process subpackage — lazy-loaded to avoid eager wgpu imports."""
from __future__ import annotations

from ._protocol import PostProcessPassProtocol

__all__ = [
    "ContactShadowsPass",
    "GTAOPass",
    "PostProcessChain",
    "PostProcessExecutor",
    "PostProcessParams",
    "PostProcessPass",
    "PostProcessPassBase",
    "PostProcessPassProtocol",
    "ShadowCSM",
    "TAAPass",
    "VolumetricFog",
    "arcade_chain",
    "cinematic_chain",
    "iso_strategy_chain",
]

_LAZY_MAP: dict[str, str] = {
    "ContactShadowsPass":  ".contact_shadows",
    "GTAOPass":            ".gtao",
    "PostProcessChain":    ".chain",
    "PostProcessExecutor": ".executor",
    "PostProcessParams":   "._pass_base",
    "PostProcessPass":     ".chain",
    "PostProcessPassBase": "._pass_base",
    "ShadowCSM":           ".shadow_csm",
    "TAAPass":             ".taa",
    "VolumetricFog":       ".volumetric_fog",
    "arcade_chain":        ".preset_chains",
    "cinematic_chain":     ".preset_chains",
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
