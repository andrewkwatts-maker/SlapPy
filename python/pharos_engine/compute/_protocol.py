"""Structural Protocol for compute kernels dispatchable by :class:`ComputePipeline`.

A *compute kernel* is anything :class:`ComputePipeline.dispatch` can
schedule onto the GPU. The shipped :class:`ComputePass` is the
reference implementation; third-party extensions that synthesise WGSL
on the fly (procedural generators, asset-compute libraries, mod
hooks) only need to expose the three attributes the pipeline actually
reads.

* ``source: str`` — WGSL shader source.
* ``entry_point: str`` — WGSL entry-point name (typically ``"main"``).
* ``label: str`` — human-readable label for debug captures.

Marked ``@runtime_checkable`` so the pipeline's eventual
``isinstance(pass_, ComputeKernelProtocol)`` guard works for both the
canonical class and structural lookalikes.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ComputeKernelProtocol(Protocol):
    """Structural type for anything dispatchable by :class:`ComputePipeline`.

    Required attributes:

    * ``source: str`` — WGSL source.
    * ``entry_point: str`` — entry-point name.
    * ``label: str`` — debug label.
    """

    source: str
    entry_point: str
    label: str


__all__ = ["ComputeKernelProtocol"]
