"""Visual test: froxel volumetric fog.

Validates the froxelated volumetric lighting pass (volumetric_fog.wgsl).
The pass ray-marches from fog_start to fog_end, applies Henyey-Greenstein
phase scattering from the sun direction, and outputs rgba16float for additive
compositing over the PBR scene.
"""
from __future__ import annotations

import pytest
from pathlib import Path
from tests.visual.harness import HeadlessRenderer, VideoAssembler, make_test_output_dir

TEST_NAME = "fog"


def test_fog_non_black(generate_video, assembler):
    renderer = HeadlessRenderer(width=640, height=360, fps=30)
    out_dir = make_test_output_dir(TEST_NAME)
    frames = renderer.render_sequence(3.0, out_dir)
    assert len(frames) > 0
    assert renderer.is_non_black(frames), "Volumetric fog render is all black"
    if generate_video:
        assembler.from_frames(frames, out_dir.parent / f"{TEST_NAME}.mp4")


def test_fog_ssim(assembler):
    ref_dir = Path(__file__).parent / "reference" / TEST_NAME
    if not ref_dir.exists():
        pytest.skip("No reference frames")
    out_dir = make_test_output_dir(TEST_NAME)
    frames = sorted(out_dir.glob("frame_*.png"))
    if not frames:
        pytest.skip("Run non_black test first")
    assert assembler.compare_to_reference(frames, ref_dir) >= 0.85
