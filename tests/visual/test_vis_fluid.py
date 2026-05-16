"""Visual test: Navier-Stokes fluid simulation."""
from __future__ import annotations
import pytest
from pathlib import Path
from tests.visual.harness import HeadlessRenderer, VideoAssembler, make_test_output_dir

TEST_NAME = "fluid"

def test_fluid_non_black(generate_video, assembler):
    renderer = HeadlessRenderer(width=640, height=360, fps=30)
    out_dir = make_test_output_dir(TEST_NAME)
    frames = renderer.render_sequence(5.0, out_dir)
    assert len(frames) > 0
    assert renderer.is_non_black(frames)
    if generate_video:
        assembler.from_frames(frames, out_dir.parent / f"{TEST_NAME}.mp4")
