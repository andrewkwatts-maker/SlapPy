"""Structural Protocol for post-process passes dispatchable by the executor.

Complements the existing :class:`PostProcessParams` (which formalises
the *UBO byte-payload* contract). :class:`PostProcessPassProtocol`
formalises the *dispatch record* contract — any object the
:class:`PostProcessExecutor` walks over and renders.

The shipped :class:`PostProcessPass` dataclass is the reference
implementation; third-party passes (extension chains, mods, generated
pipelines) only need the same attribute surface:

* ``shader_path: str`` — WGSL filename under ``shaders/``.
* ``label: str`` — chain key.
* ``enabled: bool`` — toggled by the executor's enable mask.

Optional attributes the executor reads when present:

* ``entry_point: str`` — defaults to ``"main"``.
* ``params: dict[str, Any]`` — executor-side packing route.
* ``raw_params_bytes: bytes | None`` — pre-packed UBO blob.
* ``depends_on: list[str]`` — labels that must precede this pass.

Marked ``@runtime_checkable``. Combined with :class:`PostProcessParams`,
the two Protocols cover both halves of the executor's read surface
without forcing inheritance.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PostProcessPassProtocol(Protocol):
    """Structural type for anything dispatchable by :class:`PostProcessExecutor`.

    The minimum the executor needs to schedule and bind a pass.
    """

    shader_path: str
    label: str
    enabled: bool


__all__ = ["PostProcessPassProtocol"]
