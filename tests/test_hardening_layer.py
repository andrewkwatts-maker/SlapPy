"""Negative-path tests for :class:`Layer` / :class:`Layer2D` /
:class:`Layer3D` / :class:`LayerDataBuffer` public-boundary validation
(hardening round 4).

The positive paths (``Layer.blank``, ``Layer.from_image``) are covered by
``test_basic.py``, ``test_mixed_2d_3d.py``, ``test_layer_lighting.py``,
``test_bake_pipeline.py``. This file only exercises the rejection cases.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

from slappyengine.layer import Layer, Layer2D, Layer3D, LayerDataBuffer  # noqa: E402


# ---------------------------------------------------------------------------
# Layer constructor — name / mode
# ---------------------------------------------------------------------------

def test_layer_rejects_non_str_name():
    with pytest.raises(TypeError, match="name must be a str"):
        Layer(name=123, mode="2D")


def test_layer_rejects_bytes_name():
    with pytest.raises(TypeError, match="name must be a str"):
        Layer(name=b"bytes_name", mode="2D")


def test_layer_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode must be one of"):
        Layer(name="L", mode="4D")


def test_layer_rejects_lowercase_mode_2d():
    # The mode allowlist is case-sensitive — "2d" silently accepted before.
    with pytest.raises(ValueError, match="mode must be one of"):
        Layer(name="L", mode="2d")


def test_layer_rejects_non_str_mode():
    with pytest.raises(TypeError, match="mode must be a str"):
        Layer(name="L", mode=2)


# ---------------------------------------------------------------------------
# Layer.blank — width / height / name
# ---------------------------------------------------------------------------

def test_layer_blank_rejects_zero_width():
    with pytest.raises(ValueError, match="width must be >= 1"):
        Layer.blank(0, 64)


def test_layer_blank_rejects_negative_height():
    with pytest.raises(ValueError, match="height must be >= 1"):
        Layer.blank(64, -8)


def test_layer_blank_rejects_float_width():
    # 1.5 would silently get truncated by numpy.zeros — refuse loudly.
    with pytest.raises(TypeError, match="width must be an int"):
        Layer.blank(1.5, 64)


def test_layer_blank_rejects_bool_width():
    # bool is technically an int subclass — `True == 1` would silently mean
    # "width=1", which is almost certainly a typo.
    with pytest.raises(TypeError, match="width must be an int"):
        Layer.blank(True, 64)


# ---------------------------------------------------------------------------
# Layer.from_image — path
# ---------------------------------------------------------------------------

def test_layer_from_image_rejects_nonexistent_path():
    with pytest.raises(FileNotFoundError, match="path not found"):
        Layer.from_image("/nonexistent/path/image.png")


def test_layer_from_image_rejects_bytes_path():
    with pytest.raises(TypeError, match="path must be a str or Path"):
        Layer.from_image(b"/some/path.png")


def test_layer_from_image_rejects_directory(tmp_path):
    with pytest.raises(FileNotFoundError, match="not a regular file"):
        Layer.from_image(tmp_path)


# ---------------------------------------------------------------------------
# Layer.bake_to_2d — size
# ---------------------------------------------------------------------------

def test_layer_bake_to_2d_rejects_wrong_size_length():
    layer = Layer(name="L3", mode="3D")
    with pytest.raises(ValueError, match="must have length 2"):
        layer.bake_to_2d((64, 64, 64))


def test_layer_bake_to_2d_rejects_zero_size():
    layer = Layer(name="L3", mode="3D")
    with pytest.raises(ValueError, match=r"width\) must be >= 1"):
        layer.bake_to_2d((0, 64))


# ---------------------------------------------------------------------------
# Layer.apply_heightmap — layer_2d / scale
# ---------------------------------------------------------------------------

def test_layer_apply_heightmap_rejects_non_layer_arg():
    layer = Layer(name="L3", mode="3D")
    with pytest.raises(TypeError, match="layer_2d must be a Layer"):
        layer.apply_heightmap({"not": "a layer"}, scale=1.0)


def test_layer_apply_heightmap_rejects_nan_scale():
    layer = Layer(name="L3", mode="3D")
    src = Layer(name="src", mode="2D")
    with pytest.raises(ValueError, match="scale must be finite"):
        layer.apply_heightmap(src, scale=float("nan"))


def test_layer_apply_heightmap_rejects_inf_scale():
    layer = Layer(name="L3", mode="3D")
    src = Layer(name="src", mode="2D")
    with pytest.raises(ValueError, match="scale must be finite"):
        layer.apply_heightmap(src, scale=float("inf"))


# ---------------------------------------------------------------------------
# Layer2D constructor — width / height
# ---------------------------------------------------------------------------

def test_layer2d_rejects_zero_width():
    with pytest.raises(ValueError, match="width must be >= 1"):
        Layer2D(name="L", width=0, height=64)


def test_layer2d_rejects_float_height():
    with pytest.raises(TypeError, match="height must be an int"):
        Layer2D(name="L", width=64, height=64.0)


def test_layer2d_blank_rejects_zero_height():
    with pytest.raises(ValueError, match="height must be >= 1"):
        Layer2D.blank(64, 0)


# ---------------------------------------------------------------------------
# LayerDataBuffer — struct_fields
# ---------------------------------------------------------------------------

def test_layer_data_buffer_rejects_empty_struct_fields():
    with pytest.raises(ValueError, match="struct_fields must be non-empty"):
        LayerDataBuffer(name="ldb", width=16, height=16, struct_fields=[])


def test_layer_data_buffer_rejects_non_str_field():
    with pytest.raises(TypeError, match=r"struct_fields\[1\] must be a str"):
        LayerDataBuffer(
            name="ldb", width=16, height=16,
            struct_fields=["temperature", 42, "humidity"],
        )


def test_layer_data_buffer_rejects_dict_struct_fields():
    # Dict is iterable but not list/tuple — refuse to silently iterate keys.
    with pytest.raises(TypeError, match="struct_fields must be a list/tuple"):
        LayerDataBuffer(
            name="ldb", width=16, height=16,
            struct_fields={"a": 1, "b": 2},
        )
