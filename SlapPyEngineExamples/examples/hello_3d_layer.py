"""Hello 3D Layer — 3D mesh on a 3D-mode layer, composited over a 2D background.

A 2D background layer provides the sky/ground colour. A separate layer with
mode="3D" holds a unit cube mesh with a metallic PBR material. The engine
renders the 3D layer to an offscreen texture each frame and blits it on top
of the 2D scene.

Camera matrices are identity in the current sprint; the cube appears
at the centre of the viewport in a orthographic-like projection.

Run:
    PYTHONPATH=python python examples/hello_3d_layer.py
    PYTHONPATH=python python examples/hello_3d_layer.py --frames 5
"""
from __future__ import annotations

import argparse
import sys

import pharos_engine as se
from pharos_engine.asset import Asset
from pharos_engine.layer import Layer
from pharos_engine.scene import Scene
from pharos_engine.gpu.mesh import GpuMesh
from pharos_engine.gpu.pbr_material import PbrMaterial
from pharos_engine.lighting import LightingContext, PointLight


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello 3D Layer - SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=None,
        help="exit after N draw callbacks (smoke-test mode); "
             "omit to run the live event loop until the window is closed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    engine = se.Engine(width=640, height=360, title="Hello 3D Layer")
    scene = Scene(name="Hello3DLayer")
    asset = Asset(name="world", size=(640, 360))

    # ------------------------------------------------------------------
    # 2D background — simple gradient-ish sky colour
    # ------------------------------------------------------------------
    bg = Layer.blank(640, 360, name="Background")
    bg._image_data[:] = [30, 30, 60, 255]   # dark blue-grey sky

    asset.add_layer(bg)

    # ------------------------------------------------------------------
    # 3D layer — unit cube with a rust-coloured metallic PBR material
    # ------------------------------------------------------------------
    cube_layer = Layer.blank(640, 360, name="Cube3D", mode="3D")
    cube_layer.mesh_geometry = GpuMesh.unit_cube()
    cube_layer.mesh_material = PbrMaterial(
        metallic=0.8,
        roughness=0.2,
        albedo_color=(0.7, 0.3, 0.1, 1.0),
    )

    # Independent point light for the 3D layer
    cube_layer.lighting = LightingContext()
    cube_layer.lighting.add_light(
        PointLight(
            position=(320.0, 180.0),
            color=(1.0, 0.9, 0.7),
            radius=400.0,
            intensity=2.0,
        )
    )

    asset.add_layer(cube_layer)
    scene.add(asset)

    engine.load_scene(scene)
    engine.run(max_frames=args.frames)
    return 0


if __name__ == "__main__":
    sys.exit(main())
