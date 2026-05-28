"""SlapPyEngine — compute-shader-driven 2D game engine."""
from __future__ import annotations

__version__ = "0.1.0"
__author__ = "SlapPyEngine Contributors"

# ---------------------------------------------------------------------------
# _core detection (Rust extension) — lightweight, just an import attempt
# ---------------------------------------------------------------------------
try:
    from slappyengine import _core  # noqa: F401
    HAS_NATIVE = True
except ImportError:
    HAS_NATIVE = False

# ---------------------------------------------------------------------------
# config is pure Python + PyYAML — safe to import eagerly
# ---------------------------------------------------------------------------
from slappyengine.config import engine_config  # noqa: E402

# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------
__all__ = [
    # core identifiers
    "HAS_NATIVE",
    "engine_config",
    # entity / scene
    "Entity",
    "Scene",
    "Engine",
    "Camera",
    # scripts
    "Script",
    "ScriptComponent",
    # assets / render targets
    "Asset",
    "CubeArray",
    "RenderTarget",
    # landscape
    "Landscape",
    "Tile",
    "TileCoord",
    # residency
    "ResidencyManager",
    # animation
    "AnimationGraph",
    "AnimState",
    "AnimTransition",
    "AnimUpdate",
    "ProceduralRig",
    "ControlPoint",
    # material
    "MaterialMap",
    "ColorRange",
    "MaterialDef",
    "NodeMaterial",
    "NodeDef",
    "UVNode",
    "PixelColorNode",
    "PixelChannelNode",
    "AddNode",
    "MultiplyNode",
    "LerpNode",
    "ClampNode",
    "GravityWarpNode",
    "SampleTextureNode",
    "FinalColorNode",
    "DiscardNode",
    # post-process
    "PostProcessChain",
    "PostProcessPass",
    "OutlinePass",
    "BlurPass",
    "PixelatePass",
    # ui
    "SceneUIEntity",
    # lighting
    "LightingSystem",
    "DirectionalLight",
    "PointLight",
    "ConeLight",
    "FlashLight",
    # fluid sim
    "GlobalFluidSim",
    "FluidSimConfig",
    # angle sprite
    "AngleSpriteMap",
    "AngleEntry",
    "make_angle_map_from_spritesheet",
    # input action maps
    "ActionMap",
    # split-screen
    "SplitScreenManager",
    "Viewport",
    # components
    "Component",
    "ComponentBase",
    "PhysicsComponent",
    "CollisionComponent",
    # collision
    "CollisionManager",
    "CollisionWorld",
    "AABBShape",
    "CircleShape",
    # generic data / events
    "DataComponent",
    "EventBus",
    # ui helpers
    "draw_stat_bar",
    # sdf shapes
    "SdfCanvas",
    # sdf 3D extrusion
    "SdfExtruder",
    # 3D / PBR
    "PbrMaterial",
    # layer classes
    "Layer",
    "Layer2D",
    "Layer3D",
    "LayerDataBuffer",
    # asset database
    "AssetDatabase",
]

# ---------------------------------------------------------------------------
# Lazy-load map: symbol -> dotted module path (relative to this package)
# Only symbols that correspond to real files are listed here.
# ---------------------------------------------------------------------------
_LAZY_MAP: dict[str, str] = {
    # entity / scene
    "Entity":           ".entity",
    "Scene":            ".scene",
    "Engine":           ".engine",
    "Camera":           ".camera",
    # scripts
    "Script":           ".script",
    "ScriptComponent":  ".script",
    # assets / render targets
    "Asset":            ".asset",
    "CubeArray":        ".cube_array",
    "RenderTarget":     ".render_target",
    # landscape
    "Landscape":        ".landscape",
    "Tile":             ".landscape",
    "TileCoord":        ".landscape",
    # residency
    "ResidencyManager": ".residency.manager",
    # animation
    "AnimationGraph":   ".animation.graph",
    "AnimState":        ".animation.graph",
    "AnimTransition":   ".animation.graph",
    "AnimUpdate":       ".animation.graph",
    "ProceduralRig":    ".animation.procedural",
    "ControlPoint":     ".animation.procedural",
    # material
    "MaterialMap":      ".material.map",
    "ColorRange":       ".material.map",
    "MaterialDef":      ".material.map",
    "NodeMaterial":     ".material.node_material",
    "NodeDef":          ".material.node_material",
    "UVNode":           ".material.node_material",
    "PixelColorNode":   ".material.node_material",
    "PixelChannelNode": ".material.node_material",
    "AddNode":          ".material.node_material",
    "MultiplyNode":     ".material.node_material",
    "LerpNode":         ".material.node_material",
    "ClampNode":        ".material.node_material",
    "GravityWarpNode":  ".material.node_material",
    "SampleTextureNode":".material.node_material",
    "FinalColorNode":   ".material.node_material",
    "DiscardNode":      ".material.node_material",
    # post-process
    "PostProcessChain": ".post_process.chain",
    "PostProcessPass":  ".post_process.chain",
    # ui
    "SceneUIEntity":    ".ui.scene_ui",
    # lighting
    "LightingSystem":   ".lighting",
    "DirectionalLight": ".lighting",
    "PointLight":       ".lighting",
    "ConeLight":        ".lighting",
    "FlashLight":       ".lighting",
    # fluid sim
    "GlobalFluidSim":   ".fluid_sim",
    "FluidSimConfig":   ".fluid_sim",
    # angle sprite
    "AngleSpriteMap":                  ".angle_sprite",
    "AngleEntry":                      ".angle_sprite",
    "make_angle_map_from_spritesheet": ".angle_sprite",
    # input action maps
    "ActionMap":                       ".input.action_map",
    # split-screen
    "SplitScreenManager":              ".split_screen",
    "Viewport":                        ".split_screen",
    # components
    "Component":                       ".components",
    "ComponentBase":                   ".components",
    "PhysicsComponent":                ".components",
    "CollisionComponent":              ".components",
    # collision shapes / managers
    "CollisionManager":                ".collision",
    "CollisionWorld":                  ".collision",
    "AABBShape":                       ".collision",
    "CircleShape":                     ".collision",
    # generic data / events
    "DataComponent":                   ".data_component",
    "EventBus":                        ".event_bus",
    # ui helpers
    "draw_stat_bar":                   ".ui.hud_widgets",
    # sdf shapes
    "SdfCanvas":                       ".sdf_shapes",
    # sdf 3D extrusion
    "SdfExtruder":                     ".gpu.sdf_extruder",
    # 3D / PBR
    "PbrMaterial":                     ".gpu.pbr_material",
    # layer classes
    "Layer":                           ".layer",
    "Layer2D":                         ".layer",
    "Layer3D":                         ".layer",
    "LayerDataBuffer":                 ".layer",
    # asset database
    "AssetDatabase":                   ".assets.database",
    # thermal (heat-Laplacian repackage — Phase B)
    "thermal":                         ".thermal",
}

# ---------------------------------------------------------------------------
# Post-process factory helpers — defined here so they don't require wgpu
# ---------------------------------------------------------------------------

def OutlinePass(color=(1.0, 0.0, 0.0, 1.0), threshold=0.1):
    """Return a :class:`PostProcessPass` configured for outline rendering."""
    import importlib
    _chain = importlib.import_module(".post_process.chain", package=__name__)
    return _chain.PostProcessPass(
        shader_path="outline.wgsl",
        params={
            "outline_r": color[0], "outline_g": color[1],
            "outline_b": color[2], "outline_a": color[3],
            "threshold": threshold,
        },
        label="outline",
    )


def BlurPass(radius: int = 2):
    """Return a :class:`PostProcessPass` configured for blur."""
    import importlib
    _chain = importlib.import_module(".post_process.chain", package=__name__)
    return _chain.PostProcessPass(
        shader_path="blur.wgsl", params={"radius": radius}, label="blur"
    )


def PixelatePass(block_size: int = 4):
    """Return a :class:`PostProcessPass` configured for pixelation."""
    import importlib
    _chain = importlib.import_module(".post_process.chain", package=__name__)
    return _chain.PostProcessPass(
        shader_path="pixelate.wgsl", params={"block_size": block_size}, label="pixelate"
    )


# ---------------------------------------------------------------------------
# PEP 562 — lazy attribute resolution
# ---------------------------------------------------------------------------

def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        # Cache in module globals so subsequent accesses bypass __getattr__
        globals()[name] = val
        return val

    # Subpackages returned as modules
    _subpackages = {
        "animation",
        "assets",
        "compute",
        "dynamics",
        "ext",
        "gpu",
        "input",
        "material",
        "modules",
        "numerics",
        "post_process",
        "residency",
        "thermal",
        "tools",
        "ui",
        "ai",
        # Phase B: generic zone primitive (damage zones, trigger volumes,
        # spawn pads). Registered as a subpackage so
        # ``from slappyengine import zones`` returns the module itself.
        # See ``slappyengine.zones.RectZone`` / ``ThresholdZone`` /
        # ``ZoneManager`` for the public surface.
        "zones",
    }
    if name in _subpackages:
        import importlib
        mod = importlib.import_module(f".{name}", package=__name__)
        globals()[name] = mod
        return mod

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
