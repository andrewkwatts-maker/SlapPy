"""Shader compile cache — dedupe WGSL module/pipeline compilation by content hash.

Every ``create_shader_module(code=...)`` and ``create_compute_pipeline(...)`` call
recompiles WGSL even if the source is unchanged.  On mobile / low-power targets
this is wasteful.  :class:`ShaderCache` keys modules by a SHA-256 prefix of the
source string and pipelines by ``(module_key, entry_point)``, so identical
sources are compiled exactly once per device.

Usage
-----
::

    cache = ShaderCache()
    pipeline = cache.get_or_create_compute(device, wgsl_src, entry_point="main")
    print(cache.stats())  # {"modules": 1, "pipelines": 1}
"""
from __future__ import annotations

import hashlib
from typing import Any


class ShaderCache:
    """Content-addressed cache for WGSL shader modules and compute pipelines."""

    def __init__(self) -> None:
        self._modules: dict[str, Any] = {}      # hash -> GPUShaderModule
        self._pipelines: dict[tuple, Any] = {}  # (hash, entry_point, layout_key) -> GPUComputePipeline

    def get_or_create_module(self, device: Any, src: str) -> tuple[Any, str]:
        """Return ``(module, key)`` — module is reused for identical *src*."""
        key = hashlib.sha256(src.encode()).hexdigest()[:16]
        if key not in self._modules:
            self._modules[key] = device.create_shader_module(code=src)
        return self._modules[key], key

    def get_or_create_compute(self, device: Any, src: str,
                              entry_point: str = "main") -> Any:
        """Return a compute pipeline, reusing module + pipeline when possible."""
        mod, key = self.get_or_create_module(device, src)
        pipe_key = (key, entry_point)
        if pipe_key not in self._pipelines:
            self._pipelines[pipe_key] = device.create_compute_pipeline(
                layout="auto",
                compute={"module": mod, "entry_point": entry_point},
            )
        return self._pipelines[pipe_key]

    def stats(self) -> dict:
        """Return ``{"modules": N, "pipelines": M}`` for diagnostics."""
        return {"modules": len(self._modules), "pipelines": len(self._pipelines)}

    def clear(self) -> None:
        """Drop all cached modules and pipelines."""
        self._modules.clear()
        self._pipelines.clear()
