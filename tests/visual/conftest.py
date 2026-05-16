"""pytest fixtures for visual tests."""
import pytest
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption("--generate-video", action="store_true", default=False)
    parser.addoption("--output-dir", type=str, default=None)


@pytest.fixture
def generate_video(request) -> bool:
    return request.config.getoption("--generate-video")


@pytest.fixture
def renderer():
    from tests.visual.harness import HeadlessRenderer
    return HeadlessRenderer(width=640, height=360, fps=30)


@pytest.fixture
def assembler():
    from tests.visual.harness import VideoAssembler
    return VideoAssembler()
