"""AI subpackage — lazy-loaded (requires [ai] extra: httpx)."""
from __future__ import annotations

__all__ = [
    "LLMClient",
    "ScriptGenerator",
    "CodeSyncWatcher",
    "prompt_to_code",
    "code_to_prompt",
]

_LAZY_MAP: dict[str, str] = {
    "LLMClient":       ".llm_client",
    "ScriptGenerator": ".script_gen",
    "CodeSyncWatcher": ".code_sync",
    "prompt_to_code":  ".code_sync",
    "code_to_prompt":  ".code_sync",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
