"""SlapPyEngine — compute-shader-driven 2D game engine.

A Python game engine where every hot path ports to Rust (via ``_core``) and
every authoring surface stays in Python. Targets 60+ fps on the rebuild stack
(softbody / fluid / GI) with full pixel-collision and reactive HUD wiring.

Quickstart
----------
>>> from slappyengine import Engine, Scene, Entity, Camera
>>> from slappyengine.studio import softbody_stage, record
>>> stage = softbody_stage(view_box=(-2, -1, 2, 5))

Top-level package
~~~~~~~~~~~~~~~~~
``Engine``, ``Scene``, ``Entity``, ``Camera``, ``Script``, ``Component``,
``Asset``, ``Layer`` / ``Layer2D`` / ``Layer3D``, ``EventBus``,
``DataComponent``, ``Observable``, ``ResidencyManager``, ``CacheMode``,
``ActionMap``, ``StrataWorld`` / ``StrataLayer``, ``TriggerSystem`` /
``TriggerVolume``, ``LightingSystem`` + lights, ``CollisionManager``,
``GpuParticleSystem`` / ``ParticleEmitter``, ``SplitScreenManager``. See
``__all__`` for the full top-level surface.

Subpackages — engine-as-library tour
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Simulation:

* :mod:`slappyengine.softbody` — XPBD lattice + beam softbody solver
  (lattice / vehicle / humanoid body builders, ``World.step``).
* :mod:`slappyengine.fluid`    — PBF fluid (``FluidWorld``,
  ``apply_fluid_buoyancy``, surface extraction).
* :mod:`slappyengine.dynamics` — unified ``Body`` / ``Material`` /
  ``JointSpec`` / ``RagdollSpec`` / ``IKChainSpec`` over the XPBD substrate.
* :mod:`slappyengine.physics`  — legacy per-pixel hierarchical-hull solver
  (compat surface; new code prefers ``softbody`` / ``fluid``).
* :mod:`slappyengine.thermal`  — ``HeatField`` Laplacian + two-region
  exchange for cross-system heat transport.
* :mod:`slappyengine.topology` — connected-components labelling for
  fragmentation / fracture (``connected_components``, ``_grid``).
* :mod:`slappyengine.numerics` — V-cycle Poisson solver
  (``vcycle_poisson``, ``sor_smooth``, ``compute_residual``).
* :mod:`slappyengine.math`     — symbolic + numeric formula evaluation
  (``Formula`` / ``evaluate`` backed by Arithma when the ``[math]``
  extra is installed; falls back to a Python eval sandbox otherwise) +
  ``AnimationCurve`` / ``Bezier`` / ``Catmull`` / ``ease`` /
  ``Vec2`` / ``Vec3`` / ``Vec4``.
* :mod:`slappyengine.zones`    — generic ``RectZone`` / ``ThresholdZone``
  / ``ZoneManager`` (pickup, spawn pad, damage zone).

Rendering + GPU:

* :mod:`slappyengine.gpu`         — wgpu context, mesh / PBR / cluster
  pipelines, SDF renderer.
* :mod:`slappyengine.gi`          — radiance cascades, ReSTIR, SVGF.
* :mod:`slappyengine.post_process` — TAA, GTAO, bloom, DoF, tonemap,
  shadow CSM, volumetric fog, preset chains.
* :mod:`slappyengine.material`    — node-graph material authoring
  (``NodeMaterial`` + factory nodes, ``MaterialMap``).
* :mod:`slappyengine.compute`     — ``ComputePass`` / ``ComputePipeline``,
  stats / spatial / mutator helpers, ``AssetComputeAPI``.
* :mod:`slappyengine.residency`   — three-tier (GPU/RAM/DISK) residency
  + ``.slap`` binary format.

Authoring + tooling:

* :mod:`slappyengine.studio`     — ``softbody_stage`` / ``fluid_stage`` /
  ``humanoid_stage`` + ``record()`` GIF capture (15-line demo helpers).
* :mod:`slappyengine.iso`        — isometric grid + scene + combat
  (Stone Keep tower-defence surface).
* :mod:`slappyengine.animation`  — ``AnimationGraph`` state machine +
  ``ProceduralRig`` / ``ControlPoint`` IK.
* :mod:`slappyengine.ui` / ``ui.editor`` — DearPyGui editor shell, panels,
  spawn menu, scene outliner.
* :mod:`slappyengine.input`       — action-map / bindings layer.
* :mod:`slappyengine.audio_runtime` — sounddevice backend (or no-op stub).
* :mod:`slappyengine.testing`    — ``assert_scene_matches`` golden-frame
  visual diff harness.
* :mod:`slappyengine.telemetry`  — ``emit`` / ``subscribe`` pattern bus
  with optional pattern index for hot paths.
* :mod:`slappyengine.tools`      — CLI subcommands (``slappy`` entry).
* :mod:`slappyengine.ext`        — back-compat aliases for the pre-0.3
  flat layout (``ext.lighting`` → ``slappyengine.lighting`` etc.).

Game-compat / misc:

* :mod:`slappyengine.modules`    — game-side plugin discovery hook.
* :mod:`slappyengine.ai`         — AI code tools (``slappy code`` agent).
* :mod:`slappyengine.assets`     — ``AssetDatabase``.
* :mod:`slappyengine.net`        — P2P networking.

Lifecycle flags
~~~~~~~~~~~~~~~
* ``HAS_NATIVE`` — ``True`` iff the Rust ``_core`` extension imported.
* ``engine_config`` — YAML-backed numeric defaults (single source of truth
  for all tunable parameters per user directive).

See ``docs/api/<subpackage>.md`` for the hand-authored API reference of each
subpackage. ``docs/engine_surface_v030.md`` enumerates the locked top-level
surface for the v0.3 ship.
"""
from __future__ import annotations

__version__ = "0.3.0b0"
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
    # asset import (HH5)
    "import_asset",
    "AssetImportDispatcher",
    "ImportResult",
    "TextureData",
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
    # spline + track (race / spline-driven scenes)
    "CatmullRomSpline": ".spline",
    "SplineTrack":      ".track",
    # input + collision (race scene + game systems)
    "PlayerInputProvider": ".input_provider",
    "CacheMode":           ".residency.manager",
    "PixelCollisionPass":  ".collision_pixel",
    # vehicle (softbody.vehicle re-exports for legacy game imports)
    "build_vehicle":          ".softbody.vehicle",
    "VehicleSpec":            ".softbody.vehicle",
    "WheelSpec":              ".softbody.vehicle",
    "apply_drivetrain_torque":".softbody.vehicle",
    # post-process passes Ochema's RaceScene composes
    "DofPass":         ".post_process.dof",
    "MotionBlurPass":  ".post_process.motion_blur",
    "GTAOPass":        ".post_process.gtao",
    # render channels (Ochema's render-channel ordering)
    "RenderPass":      ".render_channel",
    "NightVisionPass": ".render_channel",
    # GI configuration (lighting context flag in race scene)
    "RadianceCascadeConfig": ".lighting",
    "LightingContext":       ".lighting",
    # sim frequency / deform controller (per-frame physics budget)
    # Phase D step 4 (2026-06-01): repointed from `.deform_controller` /
    # `.deform_modes` / `.deform_zones` to `._compat` so the lazy-map
    # never imports the doomed legacy modules. See
    # docs/phase_d_strip_plan_2026_05_31.md §(b) for the migration
    # matrix. `ZoneMap` is a thin alias for `zones.ZoneManager`; the
    # other five symbols are retired-feature stubs preserved for the
    # multi-game compat tripwire.
    "SimFrequencyBudget": "._compat",
    "SimState":           "._compat",
    "DeformController":   "._compat",
    # Bullet Strata surface (per project_bullet_strata.md)
    "TriggerSystem":      ".trigger",
    "TriggerVolume":      ".trigger",
    "StrataWorld":        ".strata",
    "StrataLayer":        ".strata",
    "ZoneMap":            "._compat",
    "MaterialPreset":     "._compat",
    "CrackMode":          "._compat",
    "GpuParticleSystem":  ".particles",
    "ParticleEmitter":    ".particles",
    "PixelMaterialMap":   ".pixel_material",
    "Observable":         ".event_bus",
    # residency
    # ("CacheMode" already mapped above next to PixelCollisionPass — the
    # duplicate key was a 2026-05 merge artefact; see
    # docs/dead_code_audit_2026_06_02.md.)
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
    # asset import (HH5)
    "load_model":            ".asset_import.dispatcher",
    "load_texture":          ".asset_import.dispatcher",
    "import_asset":          ".asset_import.dispatcher",
    "AssetImportDispatcher": ".asset_import.dispatcher",
    "ImportResult":          ".asset_import.import_result",
    "TextureData":           ".asset_import.import_result",
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
        "asset_import",
        "assets",
        "compute",
        "dynamics",
        "ext",
        "gpu",
        "input",
        "iso",
        "material",
        "math",
        "modules",
        "numerics",
        "post_process",
        "projects",
        "residency",
        "telemetry",
        "audio_runtime",
        "testing",
        "thermal",
        "tools",
        "ui",
        "ai",
        # Visual scripting backbone (graph data model + Python codegen +
        # 20-node starter palette). Editor UI ships in a later sprint —
        # this subpackage stays headless / framework-agnostic.
        "visual_scripting",
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


# ---------------------------------------------------------------------------
# HH1 (2026-07-04): ergonomic top-level API — App + launch() + load_model()
#
# Eager import so ``import slappyengine; slappyengine.launch(...)`` works
# without hitting the PEP 562 lazy path (which only covers symbols in
# ``_LAZY_MAP``). The ``app`` module has no heavy dependencies (soft-imports
# the renderer) so the eager import cost is negligible.
# ---------------------------------------------------------------------------
from slappyengine.app import (  # noqa: E402
    App,
    AppConfig,
    ModelHandle,
    TextureHandle,
    CameraHandle,
    LightHandle,
    launch,
    load_model,
    load_texture,
)

# Extend __all__ append-only so the locked pre-HH1 ordering is preserved.
__all__ = list(__all__) + [
    "App",
    "AppConfig",
    "ModelHandle",
    "TextureHandle",
    "CameraHandle",
    "LightHandle",
    "launch",
    "load_model",
    "load_texture",
]

# ---------------------------------------------------------------------------
# Diagnostics aggregator (OO6) — subsystem warning/error surface for the HUD.
# Lightweight import: pure Python, stdlib only.
# ---------------------------------------------------------------------------
from slappyengine.diagnostics import (  # noqa: E402
    DiagnosticEvent,
    DiagnosticsCollector,
    get_global_collector,
)

__all__ = list(__all__) + [
    "DiagnosticEvent",
    "DiagnosticsCollector",
    "get_global_collector",
]
