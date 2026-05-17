"""SlapPyEngine.ext — optional extension modules.

Everything in this subpackage is optional and may require extra
dependencies beyond the base ``SlapPyEngine`` install:

Core install (pip install SlapPyEngine):
    SlapPyEngine.engine, .scene, .entity, .asset, .layer, .camera,
    .material, .compute, .gpu, .residency, .post_process

Extensions (always included but heavier, activate via extras):
    SlapPyEngine.ext.lighting       — GPU lighting system   (wgpu)
    SlapPyEngine.ext.fluid_sim      — fluid simulation      (wgpu + numpy)
    SlapPyEngine.ext.angle_sprite   — angle-blended sprites (Pillow)
    SlapPyEngine.ext.split_screen   — N-player split screen
    SlapPyEngine.ext.iso            — isometric rendering
    SlapPyEngine.ext.net            — P2P networking        [network] extra
    SlapPyEngine.ext.ai             — AI code tools         [ai] extra
    SlapPyEngine.ext.animation      — full animation system [video] extra
    SlapPyEngine.ext.input          — action map / bindings
    SlapPyEngine.ext.ui             — editor UI             [editor] extra

Backward-compatible aliases are kept in the original locations
(SlapPyEngine.lighting, SlapPyEngine.iso, etc.) — both import paths work.
"""

__all__ = [
    "lighting", "fluid_sim", "angle_sprite", "split_screen",
    "iso", "net", "ai", "animation", "input", "ui",
]
