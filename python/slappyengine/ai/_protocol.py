"""Structural Protocol for LLM backends.

The shipped :class:`~slappyengine.ai.LLMClient` talks to a local Ollama
server. The Code Mode panel, ``ScriptGenerator``, and code-sync watcher
all accept *any* object that exposes the three methods below — making
it trivial to wire in alternative backends (Anthropic, OpenAI, local
``llama.cpp``, recorded fixtures for tests) without touching the
consumer code.

* ``generate(prompt, system_prompt='', temperature=0.2) -> str`` —
  synchronous text generation.
* ``is_available() -> bool`` — cheap reachability probe.
* ``list_models() -> list[str]`` — enumeration of available models.

Marked ``@runtime_checkable`` so tests / authoring tools can
``isinstance(backend, LLMBackendProtocol)`` to filter mixed pools or
verify mock conformance.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMBackendProtocol(Protocol):
    """Structural type for anything :class:`ScriptGenerator` can drive.

    Required methods:

    * ``generate(prompt, system_prompt='', temperature=0.2) -> str``
    * ``is_available() -> bool``
    * ``list_models() -> list[str]``
    """

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        temperature: float = 0.2,
    ) -> str:  # noqa: D401
        ...  # pragma: no cover — Protocol stub

    def is_available(self) -> bool:  # noqa: D401
        ...  # pragma: no cover — Protocol stub

    def list_models(self) -> list[str]:  # noqa: D401
        ...  # pragma: no cover — Protocol stub


__all__ = ["LLMBackendProtocol"]
