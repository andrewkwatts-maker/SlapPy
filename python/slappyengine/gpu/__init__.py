"""GPU subpackage — lazy-loaded to avoid eager wgpu imports."""
from __future__ import annotations

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
