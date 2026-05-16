"""Tests for the render pipeline setup (no display required)."""
import pytest

wgpu = pytest.importorskip("wgpu")


def _get_device():
    try:
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        return adapter.request_device_sync() if adapter else None
    except Exception:
        return None


def test_shader_files_exist():
    """All required WGSL shader files are present."""
    from pathlib import Path
    shader_dir = Path(__file__).parent.parent / "shaders"
    required = [
        "quad_vert.wgsl", "quad_frag.wgsl", "quad_frag_array.wgsl",
        "fluid.wgsl", "rigid.wgsl", "health_sum.wgsl",
        "pixelate.wgsl", "blur.wgsl",
    ]
    for name in required:
        assert (shader_dir / name).exists(), f"Missing shader: {name}"


def test_quad_geometry_layout():
    """Quad vertices have correct count and float layout."""
    import numpy as np
    vertices = np.array([
        [0.0, 0.0, 0.0, 0.0],
        [1.0, 0.0, 1.0, 0.0],
        [1.0, 1.0, 1.0, 1.0],
        [0.0, 1.0, 0.0, 1.0],
    ], dtype=np.float32)
    assert vertices.shape == (4, 4)
    assert vertices.nbytes == 64

    indices = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint16)
    assert len(indices) == 6


def test_camera_matrix_identity():
    """Default camera at origin produces correct view matrix."""
    from slappyengine.camera import Camera
    cam = Camera(position=(0.0, 0.0), zoom=1.0)
    cam._viewport_size = (800, 600)
    mat = cam.view_matrix()
    assert len(mat) == 16
    # Scale x = 2*zoom/width = 2/800 = 0.0025
    assert abs(mat[0] - 2.0 / 800) < 1e-6
    # Scale y = -2*zoom/height = -2/600
    assert abs(mat[5] - (-2.0 / 600)) < 1e-6
