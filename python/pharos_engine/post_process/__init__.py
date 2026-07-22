"""Post-process subpackage — lazy-loaded to avoid eager wgpu imports."""
from __future__ import annotations

__all__ = [
    "BakerResult",
    "ChainBaker",
    "ChainBakerError",
    "ChainManifest",
    "ChainManifestError",
    "ContactShadowsPass",
    "DEFAULT_CHAIN",
    "GTAOPass",
    "PassSpec",
    "PostProcessChain",
    "PostProcessExecutor",
    "PostProcessParams",
    "PostProcessPass",
    "PostProcessPassBase",
    "ShadowCSM",
    "TAAPass",
    "VolumetricFog",
    "apply_manifest",
    "arcade_chain",
    "cinematic_chain",
    "iso_strategy_chain",
    "register_pass_handler",
]

_LAZY_MAP: dict[str, str] = {
    "BakerResult":         ".chain_baker",
    "ChainBaker":          ".chain_baker",
    "ChainBakerError":     ".chain_baker",
    "ChainManifest":       ".chain_manifest",
    "ChainManifestError":  ".chain_manifest",
    "ContactShadowsPass":  ".contact_shadows",
    "DEFAULT_CHAIN":       ".chain_manifest",
    "GTAOPass":            ".gtao",
    "PassSpec":            ".chain_manifest",
    "PostProcessChain":    ".chain",
    "PostProcessExecutor": ".executor",
    "PostProcessParams":   "._pass_base",
    "PostProcessPass":     ".chain",
    "PostProcessPassBase": "._pass_base",
    "ShadowCSM":           ".shadow_csm",
    "TAAPass":             ".taa",
    "VolumetricFog":       ".volumetric_fog",
    "apply_manifest":      ".chain_manifest",
    "arcade_chain":        ".preset_chains",
    "cinematic_chain":     ".preset_chains",
    "iso_strategy_chain":  ".preset_chains",
    "register_pass_handler": ".chain_manifest",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
