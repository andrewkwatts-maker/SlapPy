"""slappyengine.ext — optional extension modules.

Everything in this subpackage is optional and may require extra
dependencies beyond the base ``slappyengine`` install:

Core install (pip install slappyengine):
    slappyengine.engine, .scene, .entity, .asset, .layer, .camera,
    .material, .compute, .gpu, .residency, .post_process

Extensions (always included but heavier, activate via extras):
    slappyengine.ext.lighting       — GPU lighting system   (wgpu)
    slappyengine.ext.fluid_sim      — fluid simulation      (wgpu + numpy)
    slappyengine.ext.angle_sprite   — angle-blended sprites (Pillow)
    slappyengine.ext.split_screen   — N-player split screen
    slappyengine.ext.iso            — isometric rendering
    slappyengine.ext.net            — P2P networking        [network] extra
    slappyengine.ext.ai             — AI code tools         [ai] extra
    slappyengine.ext.animation      — full animation system [video] extra
    slappyengine.ext.input          — action map / bindings
    slappyengine.ext.ui             — editor UI             [editor] extra

Backward-compatible aliases are kept in the original locations
(slappyengine.lighting, slappyengine.iso, etc.) — both import paths work.
"""

__all__ = [
    "lighting", "fluid_sim", "angle_sprite", "split_screen",
    "iso", "net", "ai", "animation", "input", "ui",
]
