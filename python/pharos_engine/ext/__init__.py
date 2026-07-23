"""Pharos Engine.ext — optional extension modules.

Everything in this subpackage is optional and may require extra
dependencies beyond the base ``Pharos Engine`` install:

Core install (pip install Pharos Engine):
    Pharos Engine.engine, .scene, .entity, .asset, .layer, .camera,
    .material, .compute, .gpu, .residency, .post_process

Extensions (subpackages under .ext):
    Pharos Engine.ext.iso            — isometric rendering
    Pharos Engine.ext.net            — P2P networking        [network] extra
    Pharos Engine.ext.ai             — AI code tools         [ai] extra
    Pharos Engine.ext.animation      — full animation system [video] extra
    Pharos Engine.ext.input          — action map / bindings
    Pharos Engine.ext.ui             — editor UI             [editor] extra

Canonical single-file modules (imported directly from ``pharos_engine``):
    pharos_engine.lighting, pharos_engine.fluid_sim,
    pharos_engine.angle_sprite, pharos_engine.split_screen
"""

__all__ = [
    "ai",
    "animation",
    "input",
    "iso",
    "net",
    "ui",
]
