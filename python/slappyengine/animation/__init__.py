"""Animation subpackage — lazy-loaded."""
from __future__ import annotations

__all__ = [
    "AnimState",
    "AnimTransition",
    "AnimUpdate",
    "AnimationGraph",
    "ControlPoint",
    "ProceduralRig",
    # JJ4 skeletal runtime.
    "PoseState",
    "PosedSkeleton",
    "Skeleton",
    "SkeletonNode",
    "SkinnedMeshData",
    "AnimationChannel",
    "AnimationClip",
    "Skinner",
    "Animator",
    "quat_slerp",
    "compose_trs",
]

_LAZY_MAP: dict[str, str] = {
    "AnimState":         ".graph",
    "AnimTransition":    ".graph",
    "AnimUpdate":        ".graph",
    "AnimationGraph":    ".graph",
    "ControlPoint":      ".procedural",
    "ProceduralRig":     ".procedural",
    # JJ4.
    "PoseState":         ".skeleton_runtime",
    "PosedSkeleton":     ".skeleton_runtime",
    "Skeleton":          ".skeleton_runtime",
    "SkeletonNode":      ".skeleton_runtime",
    "SkinnedMeshData":   ".skeleton_runtime",
    "compose_trs":       ".skeleton_runtime",
    "AnimationChannel":  ".clip",
    "AnimationClip":     ".clip",
    "quat_slerp":        ".clip",
    "Skinner":           ".skinner",
    "Animator":          ".skinner",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
