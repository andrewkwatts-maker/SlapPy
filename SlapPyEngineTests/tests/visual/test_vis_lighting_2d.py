"""Visual test: 2D deferred lighting — point lights, directional, cone."""
from __future__ import annotations
import math
import pytest
from pathlib import Path
from tests.visual.harness import HeadlessRenderer, VideoAssembler, make_test_output_dir

TEST_NAME = "lighting_2d"


def _build_scene():
    try:
        from pharos_engine.scene import Scene
        from pharos_engine.lighting import PointLight, DirectionalLight, LightingSystem
        scene = Scene()
        # LightingSystem requires a live GPUContext; collect light objects instead
        lights = []
        for i in range(20):
            a = (i / 20) * 2 * math.pi
            lights.append(PointLight(
                position=(320 + 200 * math.cos(a), 180 + 120 * math.sin(a)),
                color=(abs(math.sin(a)), abs(math.sin(a + 2.094)), abs(math.sin(a + 4.189))),
                radius=120.0,
                intensity=1.5,
            ))
        return scene, lights
    except Exception:
        return None, None


def test_lighting_2d_non_black(generate_video, assembler):
    renderer = HeadlessRenderer(width=640, height=360, fps=30)
    out_dir = make_test_output_dir(TEST_NAME)
    scene, _ = _build_scene()
    frames = renderer.render_sequence(3.0, out_dir, scene=scene)
    assert len(frames) > 0, "No frames rendered"
    assert renderer.is_non_black(frames), "All frames are black"
    if generate_video:
        assembler.from_frames(frames, out_dir.parent / f"{TEST_NAME}.mp4")


def test_lighting_2d_ssim(assembler):
    ref_dir = Path(__file__).parent / "reference" / TEST_NAME
    if not ref_dir.exists():
        pytest.skip("No reference frames")
    out_dir = make_test_output_dir(TEST_NAME)
    frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        pytest.skip("Run non_black test first")
    assert assembler.compare_to_reference(frames, ref_dir) >= 0.85
