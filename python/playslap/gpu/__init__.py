"""GPU subpackage — lazy-loaded to avoid eager wgpu imports."""
from __future__ import annotations

__all__ = [
    "GPUContext",
    "TextureManager",
    "BufferManager",
    "RenderPipeline",
    "EntityRenderer",
    "MaterialBuffer",
    "PbrMaterial",
    "MeshPipeline",
    "GpuMesh",
    "MeshVertex",
    "MeshRenderer",
    "IBLSystem",
    "ClusterPipeline",
    "Cluster3DSystem",
    "SdfRenderer",
]

_LAZY_MAP: dict[str, str] = {
    "GPUContext":       ".context",
    "TextureManager":   ".texture_manager",
    "BufferManager":    ".buffer_manager",
    "RenderPipeline":   ".render_pipeline",
    "EntityRenderer":   ".entity_renderer",
    "MaterialBuffer":   ".material_buffer",
    "PbrMaterial":      ".pbr_material",
    "MeshPipeline":     ".mesh_pipeline",
    "GpuMesh":          ".mesh",
    "MeshVertex":       ".mesh",
    "MeshRenderer":     ".mesh_renderer",
    "IBLSystem":        ".ibl",
    "ClusterPipeline":  ".cluster_pipeline",
    "Cluster3DSystem":  ".cluster_3d",
    "SdfRenderer":      ".sdf_renderer",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
