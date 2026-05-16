"""
landscape_demo.py — Demonstrates landscape tile streaming.

- Creates a 256-pixel tile landscape
- Paints a few tiles with distinct colors
- Arrow-key camera movement streams tiles in/out
- Landscape tiles are saved to a temp directory

Note: Camera.visible_rect() exists and returns (left, top, right, bottom) in
world space. Landscape.update(camera) uses it internally to determine which
tiles are visible.
"""
import tempfile
import numpy as np
from pathlib import Path
from playslap import Engine
from playslap.scene import Scene
from playslap.camera import Camera


def paint_sample_tiles(landscape, tile_dir: Path) -> None:
    """Pre-paint some tiles with distinct colors for visual testing."""
    colors = [
        (0, 120, 80, 255),    # dark green — grass
        (180, 150, 80, 255),  # tan — sand
        (60, 100, 200, 255),  # blue — water
        (80, 60, 40, 255),    # brown — dirt
    ]
    for i in range(4):
        for j in range(4):
            color = colors[(i + j) % len(colors)]
            data = np.full((256, 256, 4), color, dtype=np.uint8)
            # Add grid lines so tile boundaries are visible
            data[0, :] = [0, 0, 0, 255]
            data[-1, :] = [0, 0, 0, 255]
            data[:, 0] = [0, 0, 0, 255]
            data[:, -1] = [0, 0, 0, 255]
            landscape.paint_tile(i, j, data)
    landscape.flush_all()


def main() -> None:
    tile_dir = Path(tempfile.mkdtemp(prefix="slap_landscape_"))
    print(f"Tile directory: {tile_dir}")

    engine = Engine(title="Landscape Demo", width=800, height=600)
    scene = Scene(name="LandscapeDemo")
    scene.camera = Camera()

    try:
        from playslap.landscape import Landscape
        landscape = Landscape(tile_size=256, tile_dir=tile_dir, cache_size=16)
        paint_sample_tiles(landscape, tile_dir)
        scene.landscape = landscape
        print(f"Landscape ready — {len(landscape.visible_tiles)} tiles initially visible")
    except ImportError:
        print("Landscape module not available")
        scene.landscape = None

    engine.load_scene(scene)
    engine.run()


if __name__ == "__main__":
    main()
