"""Pharos Engine.ext — optional extension modules.

Everything in this subpackage is optional and may require extra
dependencies beyond the base ``Pharos Engine`` install:

Core install (pip install Pharos Engine):
    Pharos Engine.engine, .scene, .entity, .asset, .layer, .camera,
    .material, .compute, .gpu, .residency, .post_process

Extensions (always included but heavier, activate via extras):
    Pharos Engine.ext.lighting       — GPU lighting system   (wgpu)
    Pharos Engine.ext.fluid_sim      — fluid simulation      (wgpu + numpy)
    Pharos Engine.ext.angle_sprite   — angle-blended sprites (Pillow)
    Pharos Engine.ext.split_screen   — N-player split screen
    Pharos Engine.ext.iso            — isometric rendering
    Pharos Engine.ext.net            — P2P networking        [network] extra
    Pharos Engine.ext.ai             — AI code tools         [ai] extra
    Pharos Engine.ext.animation      — full animation system [video] extra
    Pharos Engine.ext.input          — action map / bindings
    Pharos Engine.ext.ui             — editor UI             [editor] extra

Backward-compatible aliases are kept in the original locations
(Pharos Engine.lighting, Pharos Engine.iso, etc.) — both import paths work.
"""

__all__ = [
    "ai",
    "angle_sprite",
    "animation",
    "fluid_sim",
    "input",
    "iso",
    "lighting",
    "net",
    "split_screen",
    "ui",
]
