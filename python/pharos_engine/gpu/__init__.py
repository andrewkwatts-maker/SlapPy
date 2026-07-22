"""GPU subpackage — lazy-loaded to avoid eager wgpu imports.

Sprint 2 deprecation: the CPU-side / soft-wgpu GPU subsystem is moving
to ``pharos_engine.render.native`` (Rust ``pharos_render`` crate). The
existing symbols keep working but a one-shot DeprecationWarning fires
on first import so downstream code can migrate.
"""
from __future__ import annotations

import warnings as _warnings

_DEPRECATION = (
    "pharos_engine.gpu is deprecated in v0.3.0 and will retire in v0.4. "
    "Use pharos_engine.render.native (Renderer / RenderScene / VcrPipeline) "
    "for the wgpu-backed GPU path."
)
_warnings.warn(_DEPRECATION, DeprecationWarning, stacklevel=2)

# Soft-import the native replacement so callers can reach the new API
# through pharos_engine.gpu.native if they need a transition alias.
try:
    from pharos_engine.render import native  # noqa: F401
except Exception:
    native = None  # type: ignore[assignment]

__all__ = [
    "BufferManager",
    "Cluster3DSystem",
    "ClusterPipeline",
    "EntityRenderer",
    "GPUContext",
    "GpuMesh",
    "IBLSystem",
    "MaterialBuffer",
    "MeshPipeline",
    "MeshRenderer",
    "MeshVertex",
    "PbrMaterial",
    "RenderPipeline",
    "SdfRenderer",
    "TextureManager",
    "native",
]

_LAZY_MAP: dict[str, str] = {
    "BufferManager":    ".buffer_manager",
    "Cluster3DSystem":  ".cluster_3d",
    "ClusterPipeline":  ".cluster_pipeline",
    "EntityRenderer":   ".entity_renderer",
    "GPUContext":       ".context",
    "GpuMesh":          ".mesh",
    "IBLSystem":        ".ibl",
    "MaterialBuffer":   ".material_buffer",
    "MeshPipeline":     ".mesh_pipeline",
    "MeshRenderer":     ".mesh_renderer",
    "MeshVertex":       ".mesh",
    "PbrMaterial":      ".pbr_material",
    "RenderPipeline":   ".render_pipeline",
    "SdfRenderer":      ".sdf_renderer",
    "TextureManager":   ".texture_manager",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
