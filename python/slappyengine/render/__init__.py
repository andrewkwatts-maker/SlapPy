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
from .light import Light, MAX_LIGHTS, pack_lights_ubo, is_unlit
from .material import Material, TextureHandle
from .mesh import Mesh, MeshHandle, cube, quad
from .null_renderer import DrawCall, NullRenderer
from .renderer import Renderer, is_wgpu_available
from .shader_stock import (
    LINE_3D_WGSL,
    PHONG_3D_WGSL,
    SPRITE_2D_WGSL,
    STOCK_SHADERS,
    ShaderSource,
    UNLIT_3D_WGSL,
    get_shader,
)
from .transform import Transform2D, Transform3D

__all__ = [
    "Camera2D",
    "Camera3D",
    "DrawCall",
    "Light",
    "LINE_3D_WGSL",
    "MAX_LIGHTS",
    "Material",
    "Mesh",
    "MeshHandle",
    "NullRenderer",
    "PHONG_3D_WGSL",
    "Renderer",
    "SPRITE_2D_WGSL",
    "STOCK_SHADERS",
    "ShaderSource",
    "TextureHandle",
    "Transform2D",
    "Transform3D",
    "UNLIT_3D_WGSL",
    "cube",
    "get_shader",
    "is_unlit",
    "is_wgpu_available",
    "pack_lights_ubo",
    "quad",
]
