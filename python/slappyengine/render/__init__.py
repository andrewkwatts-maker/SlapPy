"""slappyengine.render — wgpu-based 2D+3D forward-rasterization renderer.

Public surface — designed to be pluggable into HH1's ``App`` API::

    from slappyengine.render import (
        Renderer, NullRenderer,
        Mesh, MeshHandle,
        Material, TextureHandle,
        Light,
        Camera3D, Camera2D,
        Transform3D, Transform2D,
        get_shader, STOCK_SHADERS,
    )

Design notes
------------
* wgpu is a soft dependency. If wgpu is missing (or its adapter request
  fails), ``Renderer`` transparently degrades to :class:`NullRenderer`,
  which records every draw call. HH1 uses this path for headless CI and
  for ``App(enable_gpu=False)``.
* No shadow maps, no PBR, no refractive indices — the user asked for a
  straightforward forward rasteriser.
* Meshes render *unlit* until at least one non-ambient light is added
  (matches the user's explicit spec).
"""
from __future__ import annotations

from .camera import Camera2D, Camera3D
from .layer_sampling import (
    BLEND_MODES,
    LayerSampleBinding,
    LayerTextureBinding,
    PostProcessDescriptor,
    apply_post_process_from,
    bind_sampled_layers,
    fallback_texture_view,
    load_composite_shader,
    make_layer_sample_binding,
    use_layer_as_texture,
)
from .light import Light, MAX_LIGHTS, pack_lights_ubo, is_unlit
from .material import Material, TextureHandle
from .mesh import Mesh, MeshHandle, cube, quad
from .null_renderer import DrawCall, NullRenderer
from .passes import (
    DepthPrepass,
    EarlyZPass,
    MSAAResolvePass,
    PassChain,
    RenderPass,
    install_default_passes,
)
from .renderer import Renderer, is_wgpu_available
from .scene_walker import (
    AssetCache,
    EntityDrawInfo,
    Frustum,
    RenderStats,
    SceneWalker,
    bridge_render_scene,
    render_scene,
)
from .shader_stock import (
    DEPTH_ONLY_WGSL,
    LINE_3D_WGSL,
    PHONG_3D_WGSL,
    SPRITE_2D_WGSL,
    STOCK_SHADERS,
    ShaderSource,
    UNLIT_3D_WGSL,
    get_shader,
)
from .shadows import (
    CSMBuilder,
    CascadeSplit,
    SHADOW_DEPTH_ONLY_WGSL,
    SHADOW_SAMPLE_WGSL_SNIPPET,
    SHADOW_SAMPLER_DESC,
    ShadowMapConfig,
    find_cascade_for_world_pos,
    pack_cascade_ubo,
)
from .skybox import (
    ALL_FACES,
    CubeFace,
    CubemapData,
    SKYBOX_WGSL,
    Skybox,
    procedural_gradient_sky,
    sample_direction_from_cubemap,
)
from .transform import Transform2D, Transform3D

__all__ = [
    "AssetCache",
    "BLEND_MODES",
    "CSMBuilder",
    "Camera2D",
    "Camera3D",
    "LayerSampleBinding",
    "LayerTextureBinding",
    "PostProcessDescriptor",
    "apply_post_process_from",
    "bind_sampled_layers",
    "fallback_texture_view",
    "load_composite_shader",
    "make_layer_sample_binding",
    "use_layer_as_texture",
    "CascadeSplit",
    "DEPTH_ONLY_WGSL",
    "DepthPrepass",
    "DrawCall",
    "EarlyZPass",
    "EntityDrawInfo",
    "Frustum",
    "Light",
    "LINE_3D_WGSL",
    "MAX_LIGHTS",
    "MSAAResolvePass",
    "Material",
    "Mesh",
    "MeshHandle",
    "NullRenderer",
    "PHONG_3D_WGSL",
    "PassChain",
    "RenderPass",
    "RenderStats",
    "Renderer",
    "SHADOW_DEPTH_ONLY_WGSL",
    "SHADOW_SAMPLE_WGSL_SNIPPET",
    "SHADOW_SAMPLER_DESC",
    "SKYBOX_WGSL",
    "SPRITE_2D_WGSL",
    "STOCK_SHADERS",
    "Skybox",
    "CubeFace",
    "CubemapData",
    "procedural_gradient_sky",
    "sample_direction_from_cubemap",
    "SceneWalker",
    "ShaderSource",
    "ShadowMapConfig",
    "TextureHandle",
    "Transform2D",
    "Transform3D",
    "UNLIT_3D_WGSL",
    "bridge_render_scene",
    "cube",
    "find_cascade_for_world_pos",
    "get_shader",
    "install_default_passes",
    "is_unlit",
    "is_wgpu_available",
    "pack_cascade_ubo",
    "pack_lights_ubo",
    "quad",
    "render_scene",
]
