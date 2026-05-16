"""playslap.ext — optional extension modules.

Everything in this subpackage is optional and may require extra
dependencies beyond the base ``playslap`` install:

Core install (pip install playslap):
    playslap.engine, .scene, .entity, .asset, .layer, .camera,
    .material, .compute, .gpu, .residency, .post_process

Extensions (always included but heavier, activate via extras):
    playslap.ext.lighting       — GPU lighting system   (wgpu)
    playslap.ext.fluid_sim      — fluid simulation      (wgpu + numpy)
    playslap.ext.angle_sprite   — angle-blended sprites (Pillow)
    playslap.ext.split_screen   — N-player split screen
    playslap.ext.iso            — isometric rendering
    playslap.ext.net            — P2P networking        [network] extra
    playslap.ext.ai             — AI code tools         [ai] extra
    playslap.ext.animation      — full animation system [video] extra
    playslap.ext.input          — action map / bindings
    playslap.ext.ui             — editor UI             [editor] extra

Backward-compatible aliases are kept in the original locations
(playslap.lighting, playslap.iso, etc.) — both import paths work.
"""

__all__ = [
    "lighting", "fluid_sim", "angle_sprite", "split_screen",
    "iso", "net", "ai", "animation", "input", "ui",
]
