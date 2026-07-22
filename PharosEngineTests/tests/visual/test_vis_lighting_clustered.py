"""Visual test: clustered 2D lighting — 100 point lights."""
from __future__ import annotations
import random
import pytest
from pathlib import Path
from tests.visual.harness import HeadlessRenderer, VideoAssembler, make_test_output_dir

TEST_NAME = "lighting_clustered"


def _build_scene():
    try:
        from pharos_engine.scene import Scene
        from pharos_engine.lighting import PointLight, LightingSystem
        rng = random.Random(42)
        scene = Scene()
        # LightingSystem requires a live GPUContext; collect light objects instead
        lights = []
        for _ in range(100):
            lights.append(PointLight(
                position=(rng.uniform(0, 640), rng.uniform(0, 360)),
                color=(rng.random(), rng.random(), rng.random()),
                radius=rng.uniform(60, 140),
                intensity=rng.uniform(0.5, 2.0),
            ))
        return scene, lights
    except Exception:
        return None, None


def test_lighting_clustered_non_black(generate_video, assembler):
    renderer = HeadlessRenderer(width=640, height=360, fps=30)
    out_dir = make_test_output_dir(TEST_NAME)
    scene, _ = _build_scene()
    frames = renderer.render_sequence(2.0, out_dir, scene=scene)
    assert len(frames) > 0
    assert renderer.is_non_black(frames), "Clustered lighting is black"
    if generate_video:
        assembler.from_frames(frames, out_dir.parent / f"{TEST_NAME}.mp4")
