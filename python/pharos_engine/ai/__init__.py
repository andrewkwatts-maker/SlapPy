"""AI subpackage — lazy-loaded (requires [ai] extra: httpx)."""
from __future__ import annotations

from ._protocol import LLMBackendProtocol

__all__ = [
    "CodeSyncWatcher",
    "LLMBackendProtocol",
    "LLMClient",
    "ScriptGenerator",
    "code_to_prompt",
    "prompt_to_code",
]

_LAZY_MAP: dict[str, str] = {
    "CodeSyncWatcher": ".code_sync",
    "LLMClient":       ".llm_client",
    "ScriptGenerator": ".script_gen",
    "code_to_prompt":  ".code_sync",
    "prompt_to_code":  ".code_sync",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
