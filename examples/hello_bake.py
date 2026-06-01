"""Hello Bake — 3D-to-2D baking and 2D-to-3D heightmap displacement.

Demonstrates two cross-layer baking operations:

  1. 3D → 2D   : bake_to_2d() renders a 3D layer to a flat RGBA texture that
                 can be used as a 2D sprite or cached asset.

  2. 2D → 3D   : apply_heightmap() displaces a quad mesh's vertex Z positions
                 using the luminance of a CPU-side 2D gradient image.

Both operations work on CPU-side data before the engine GPU loop starts, so
the prints are immediate. The final scene renders the baked 2D layer.

Run:
    PYTHONPATH=python python examples/hello_bake.py
    PYTHONPATH=python python examples/hello_bake.py --frames 5
"""
from __future__ import annotations

import argparse
import sys

import numpy as np
import slappyengine as se
from slappyengine.asset import Asset
from slappyengine.layer import Layer
from slappyengine.scene import Scene
from slappyengine.gpu.mesh import GpuMesh
from slappyengine.gpu.pbr_material import PbrMaterial


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Bake - SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=None,
        help="exit after N draw callbacks (smoke-test mode); "
             "omit to run the live event loop until the window is closed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    engine = se.Engine(width=640, height=360, title="Hello Bake")
    scene = Scene(name="HelloBake")
    asset = Asset(name="world", size=(640, 360))

    # ------------------------------------------------------------------
    # 3D → 2D : bake a 3D layer to a flat texture
    # ------------------------------------------------------------------
    cube_layer = Layer.blank(256, 256, name="Cube3D", mode="3D")
    cube_layer.mesh_geometry = GpuMesh.unit_cube()
    cube_layer.mesh_material = PbrMaterial(metallic=0.5, roughness=0.4)

    # bake_to_2d() returns a new 2D Layer. Before the engine GPU is live the
    # internal MeshRenderer is None, so the method returns a blank placeholder —
    # when called at runtime inside a draw callback it would contain real pixel data.
    baked = cube_layer.bake_to_2d(size=(128, 128))
    print(f"Baked layer: mode={baked.mode!r}, name={baked.name!r}, "
          f"size={baked.size}")

    asset.add_layer(baked)

    # ------------------------------------------------------------------
    # 2D → 3D : use a gradient image to displace mesh vertex Z positions
    # ------------------------------------------------------------------
    quad_layer = Layer.blank(256, 256, name="HeightQuad", mode="3D")
    quad_layer.mesh_geometry = GpuMesh.unit_quad()
    quad_layer.mesh_material = PbrMaterial(metallic=0.1, roughness=0.9,
                                            albedo_color=(0.3, 0.7, 0.3, 1.0))

    # Build a 256×256 gradient: left column = black (0), right column = white (255)
    gradient_layer = Layer.blank(256, 256, name="Gradient")
    ramp = np.linspace(0, 255, 256, dtype=np.uint8)        # shape (256,)
    gradient_layer._image_data[:, :, 0] = ramp[np.newaxis, :]  # R
    gradient_layer._image_data[:, :, 1] = ramp[np.newaxis, :]  # G
    gradient_layer._image_data[:, :, 2] = ramp[np.newaxis, :]  # B
    gradient_layer._image_data[:, :, 3] = 255                   # A

    quad_layer.apply_heightmap(gradient_layer, scale=2.0)

    z_vals = [v.position[2] for v in quad_layer.mesh_geometry._vertices]
    print(f"Heightmap applied: vertex Z range = "
          f"[{min(z_vals):.3f}, {max(z_vals):.3f}]")

    asset.add_layer(quad_layer)

    scene.add(asset)
    engine.load_scene(scene)
    engine.run(max_frames=args.frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
