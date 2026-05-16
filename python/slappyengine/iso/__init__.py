"""slappyengine.iso — Isometric 2D-grid-with-Z rendering subsystem.

This subpackage adds isometric grid rendering to SlapPyEngine.  It has
**zero hard dependencies on wgpu** at import time; all rendering flows
through the engine's existing pipeline.

Quick start::

    from slappyengine.iso import IsoScene, IsoTileDef, IsoEntity, IsoViewpoint

    scene = IsoScene(grid_w=20, grid_h=20, grid_d=4)
    floor = IsoTileDef("floor", "assets/floor.png")
    scene.grid.set_tile(0, 0, 0, floor)

    hero = IsoEntity(grid_x=3.0, grid_y=3.0)
    scene.add_iso_entity(hero)

    scene.camera.rotate_cw()  # change viewpoint

Public API
----------
The following names are importable directly from ``slappyengine.iso``:
"""

from .projection import IsoViewpoint
from .iso_grid import IsoGrid, IsoCell, IsoTileDef
from .iso_camera import IsoCamera
from .iso_entity import IsoEntity
from .iso_scene import IsoScene

__all__ = [
    "IsoGrid",
    "IsoCell",
    "IsoCamera",
    "IsoEntity",
    "IsoScene",
    "IsoViewpoint",
    "IsoTileDef",
]
