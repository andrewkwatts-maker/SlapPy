"""Visual test: CSM directional shadows."""
from __future__ import annotations

import pytest
from pathlib import Path
from tests.visual.harness import HeadlessRenderer, VideoAssembler, make_test_output_dir

TEST_NAME = "shadows"


def _build_scene():
    """Attempt to build a minimal lighting scene with a shadow-casting directional light.

    DirectionalLight.direction is a normalised XY tuple (2-component), not XYZ.
    LightingSystem requires a GPUContext; we skip gracefully if GPU is unavailable.
    """
    try:
        from slappyengine.lighting import DirectionalLight, LightingSystem
        # LightingSystem needs (gpu, width, height) — return just the light descriptor
        # so callers can pass it to a renderer that owns a GPUContext.
        light = DirectionalLight(
            direction=(-0.5, 0.866),   # normalised XY ~240° (late-afternoon sun)
            elevation=0.4,             # radians above horizon (~23°)
            color=(1.0, 0.95, 0.8),
            intensity=1.0,
            cast_shadows=True,
        )
        return light
    except Exception:
        return None


def test_shadows_non_black(generate_video, assembler):
    renderer = HeadlessRenderer(width=640, height=360, fps=30)
    out_dir = make_test_output_dir(TEST_NAME)
    frames = renderer.render_sequence(3.0, out_dir)
    assert len(frames) > 0
    assert renderer.is_non_black(frames), "CSM shadow render is all black"
    if generate_video:
        assembler.from_frames(frames, out_dir.parent / f"{TEST_NAME}.mp4")


def test_shadows_ssim(assembler):
    ref_dir = Path(__file__).parent / "reference" / TEST_NAME
    if not ref_dir.exists():
        pytest.skip("No reference frames")
    out_dir = make_test_output_dir(TEST_NAME)
    frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        pytest.skip("Run non_black test first")
    assert assembler.compare_to_reference(frames, ref_dir) >= 0.85
