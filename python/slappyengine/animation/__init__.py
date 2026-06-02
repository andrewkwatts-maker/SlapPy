"""Animation subpackage — lazy-loaded."""
from __future__ import annotations

__all__ = [
    "AnimState",
    "AnimTransition",
    "AnimUpdate",
    "AnimationGraph",
    "ControlPoint",
    "ProceduralRig",
]

_LAZY_MAP: dict[str, str] = {
    "AnimState":       ".graph",
    "AnimTransition":  ".graph",
    "AnimUpdate":      ".graph",
    "AnimationGraph":  ".graph",
    "ControlPoint":    ".procedural",
    "ProceduralRig":   ".procedural",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
