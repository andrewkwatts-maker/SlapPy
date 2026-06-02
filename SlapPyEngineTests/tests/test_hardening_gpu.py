"""Negative-path tests for :mod:`slappyengine.gpu` public-boundary
validation (hardening round 13).

The GPU subpackage's deep wgpu API (``GPUDevice`` / ``GPUBuffer``) raises
its own clean errors, but the Python wrappers we expose — ``GpuMesh``,
``MeshRenderer``, ``TextureManager`` — had no input validation until now.

Silent-acceptance bugs caught here:
  * ``GpuMesh(None, None)`` silently constructed an unusable mesh and
    crashed inside ``vertex_bytes`` with an opaque
    ``TypeError: 'NoneType' object is not iterable``.
  * ``GpuMesh([], [3, 1])`` (indices length not a multiple of 3) was
    silently accepted and would dispatch a malformed draw call later.
  * ``TextureManager.create_sampler("narest")`` silently fell through to
    the ``"linear"`` branch — a typo's filter mode was bound silently.
  * ``MeshRenderer.update_camera`` accepted matrices of the wrong length
    and crashed deep inside ``struct.pack`` with ``required argument is
    not a float`` (when a NaN snuck in) or a length mismatch error.

Positive paths live in :file:`tests/test_gpu_headless.py` and
:file:`tests/test_gpu_mesh_pipeline_binding.py`. This file only covers
the rejection contract.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

# Mirror the gate used by other GPU tests — wgpu is required for the
# pipeline/renderer/texture-manager paths but the validators themselves
# do not need a device. Tests that don't touch wgpu state skip-guard via
# the per-test imports below.
_SKIP = ""
try:
    import slappyengine  # noqa: F401
    _OK = True
except Exception as exc:
    _OK = False
    _SKIP = str(exc)

pytestmark = pytest.mark.skipif(not _OK, reason=f"slappyengine unavailable: {_SKIP}")


# ---------------------------------------------------------------------------
# GpuMesh.__init__(vertices, indices)
# ---------------------------------------------------------------------------

def test_gpu_mesh_rejects_none_vertices():
    """Silent-acceptance bug: ``None`` slipped through and died in vertex_bytes."""
    from slappyengine.gpu.mesh import GpuMesh
    with pytest.raises(TypeError, match="vertices must not be None"):
        GpuMesh(None, [])  # type: ignore[arg-type]


def test_gpu_mesh_rejects_none_indices():
    from slappyengine.gpu.mesh import GpuMesh
    with pytest.raises(TypeError, match="indices must not be None"):
        GpuMesh([], None)  # type: ignore[arg-type]


def test_gpu_mesh_rejects_string_vertices():
    from slappyengine.gpu.mesh import GpuMesh
    with pytest.raises(TypeError, match="vertices must be a list or tuple"):
        GpuMesh("xyz", [])  # type: ignore[arg-type]


def test_gpu_mesh_rejects_dict_indices():
    from slappyengine.gpu.mesh import GpuMesh
    with pytest.raises(TypeError, match="indices must be a list or tuple"):
        GpuMesh([], {0: 1, 1: 2})  # type: ignore[arg-type]


def test_gpu_mesh_rejects_non_int_index():
    from slappyengine.gpu.mesh import GpuMesh
    with pytest.raises(TypeError, match=r"indices\[1\] must be an int"):
        GpuMesh([], [0, 1.5, 2])  # type: ignore[list-item]


def test_gpu_mesh_rejects_negative_index():
    from slappyengine.gpu.mesh import GpuMesh
    with pytest.raises(ValueError, match=r"indices\[2\] must be >= 0"):
        GpuMesh([], [0, 1, -1])


def test_gpu_mesh_rejects_non_triangle_index_count():
    """Silent-acceptance bug: 4 indices is not a triangle list."""
    from slappyengine.gpu.mesh import GpuMesh
    with pytest.raises(ValueError, match="multiple of 3"):
        GpuMesh([], [0, 1, 2, 0])


def test_gpu_mesh_accepts_unit_cube():
    """Positive sanity: factory still constructs correctly."""
    from slappyengine.gpu.mesh import GpuMesh
    m = GpuMesh.unit_cube()
    assert m.vertex_count == 24
    assert m.index_count == 36


# ---------------------------------------------------------------------------
# TextureManager.create_sampler / create_view
# ---------------------------------------------------------------------------

def test_create_sampler_rejects_typo_filter_mode():
    """Silent-acceptance bug: any non-"nearest" str silently mapped to linear."""
    from slappyengine.gpu._validation import validate_filter_mode
    with pytest.raises(ValueError, match="'nearest' or 'linear'"):
        validate_filter_mode("filter_mode", "TextureManager.create_sampler", "narest")


def test_create_sampler_rejects_none_filter_mode():
    from slappyengine.gpu._validation import validate_filter_mode
    with pytest.raises(TypeError, match="filter_mode must be a str"):
        validate_filter_mode("filter_mode", "TextureManager.create_sampler", None)


def test_create_sampler_rejects_empty_filter_mode():
    from slappyengine.gpu._validation import validate_filter_mode
    with pytest.raises(ValueError, match="filter_mode must be non-empty"):
        validate_filter_mode("filter_mode", "TextureManager.create_sampler", "")


def test_create_view_rejects_invalid_dimension():
    from slappyengine.gpu._validation import validate_view_dimension
    with pytest.raises(ValueError, match="'2d' or '2d-array'"):
        validate_view_dimension("dimension", "TextureManager.create_view", "3d")


def test_create_view_rejects_none_dimension():
    from slappyengine.gpu._validation import validate_view_dimension
    with pytest.raises(TypeError, match="dimension must be a str"):
        validate_view_dimension("dimension", "TextureManager.create_view", None)


# ---------------------------------------------------------------------------
# MeshRenderer.update_camera matrix validators
# ---------------------------------------------------------------------------

def test_update_camera_rejects_short_matrix():
    """Silent-acceptance bug: a 15-element list crashed deep in struct.pack."""
    from slappyengine.gpu._validation import validate_matrix16
    with pytest.raises(ValueError, match="length 16"):
        validate_matrix16("model", "MeshRenderer.update_camera", [0.0] * 15)


def test_update_camera_rejects_nan_matrix_element():
    """NaN propagates through every shader op — refuse at the boundary."""
    from slappyengine.gpu._validation import validate_matrix16
    bad = [0.0] * 16
    bad[5] = math.nan
    with pytest.raises(ValueError, match=r"model\[5\] must be finite"):
        validate_matrix16("model", "MeshRenderer.update_camera", bad)


def test_update_camera_rejects_inf_matrix_element():
    from slappyengine.gpu._validation import validate_matrix16
    bad = [0.0] * 16
    bad[10] = math.inf
    with pytest.raises(ValueError, match=r"model\[10\] must be finite"):
        validate_matrix16("model", "MeshRenderer.update_camera", bad)


def test_update_camera_rejects_string_matrix():
    from slappyengine.gpu._validation import validate_matrix16
    with pytest.raises(TypeError, match="16-element sequence"):
        validate_matrix16("model", "MeshRenderer.update_camera", "identity")


def test_update_camera_rejects_none_matrix():
    from slappyengine.gpu._validation import validate_matrix16
    with pytest.raises(TypeError, match="16-element sequence"):
        validate_matrix16("model", "MeshRenderer.update_camera", None)


# ---------------------------------------------------------------------------
# Image-array validator (upload_layer / upload_frame_array)
# ---------------------------------------------------------------------------

def test_image_array_rejects_2d_shape():
    """Layers must carry an H, W, C ndarray — refuse grayscale-shaped input."""
    import numpy as np
    from slappyengine.gpu._validation import validate_image_array
    with pytest.raises(ValueError, match="3-dimensional"):
        validate_image_array("img", "fn", np.zeros((4, 4), dtype=np.uint8))


def test_image_array_rejects_zero_height():
    import numpy as np
    from slappyengine.gpu._validation import validate_image_array
    with pytest.raises(ValueError, match="H>=1 and W>=1"):
        validate_image_array("img", "fn", np.zeros((0, 4, 4), dtype=np.uint8))


def test_image_array_rejects_5_channel():
    """Only RGB (3) or RGBA (4) are supported by upload paths."""
    import numpy as np
    from slappyengine.gpu._validation import validate_image_array
    with pytest.raises(ValueError, match="3 or 4 channels"):
        validate_image_array("img", "fn", np.zeros((4, 4, 5), dtype=np.uint8))


def test_image_array_rejects_list():
    from slappyengine.gpu._validation import validate_image_array
    with pytest.raises(TypeError, match="numpy.ndarray"):
        validate_image_array("img", "fn", [[0, 0, 0]])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Output-format & positive-int validators surfaced via gpu._validation
# ---------------------------------------------------------------------------

def test_validate_positive_int_rejects_zero_width():
    from slappyengine.gpu._validation import validate_positive_int
    with pytest.raises(ValueError, match=">= 1"):
        validate_positive_int("width", "MeshRenderer.render_to_texture", 0)


def test_validate_positive_int_rejects_bool():
    """``True`` would silently mean ``width=1`` — refuse at the boundary."""
    from slappyengine.gpu._validation import validate_positive_int
    with pytest.raises(TypeError, match="width must be an int"):
        validate_positive_int(
            "width", "MeshRenderer.render_to_texture", True,
        )


def test_validate_output_format_rejects_empty():
    from slappyengine.gpu._validation import validate_output_format
    with pytest.raises(ValueError, match="non-empty"):
        validate_output_format(
            "output_format", "MeshRenderer.render_to_texture", "",
        )


def test_validate_output_format_rejects_none():
    from slappyengine.gpu._validation import validate_output_format
    with pytest.raises(TypeError, match="output_format must be a str"):
        validate_output_format(
            "output_format", "MeshRenderer.render_to_texture", None,
        )
