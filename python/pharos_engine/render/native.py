"""Native GPU render surface — wgpu-backed Renderer / RenderScene /
Camera3D / VcrPipeline exposed by ``pharos_engine._core.render``.

Sprint 2 migration lands the pharos_render Rust crate as the GPU
backend. This submodule re-exports the PyO3 wrappers so downstream
code can write::

    from pharos_engine.render.native import Renderer, RenderScene, VcrPipeline

The parent ``pharos_engine.render`` package keeps its existing pure-Python
surface (a soft-wgpu forward renderer with NullRenderer fallback) so
downstream games do not break. Use ``.native`` when you specifically
want the Rust-backed wgpu path.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = ["Renderer", "RenderScene", "Camera3D", "VcrPipeline"]


def _load_core_render():
    try:
        from pharos_engine import _core  # type: ignore[attr-defined]
    except ImportError as e:
        raise ImportError(
            "pharos_engine._core is not installed. Build the wheel with "
            "`python scripts/build_wheel.py` before importing "
            "pharos_engine.render.native."
        ) from e
    return _core.render


def __getattr__(name: str):
    if name in __all__:
        val = getattr(_load_core_render(), name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:  # help IDEs without importing the native extension eagerly.
    Renderer = object
    RenderScene = object
    Camera3D = object
    VcrPipeline = object
