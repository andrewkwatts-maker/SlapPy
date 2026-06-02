"""Negative-path tests for :class:`Camera` public-boundary validation
(hardening round 4).

The positive paths (``Camera(position=(...), zoom=...)``, world ↔ screen
transforms, ``follow``) are covered by ``test_basic.py`` and
``test_render_pipeline.py``. This file only exercises the rejection cases
in the new ``position`` / ``zoom`` property setters.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

from slappyengine.camera import Camera  # noqa: E402


# ---------------------------------------------------------------------------
# Camera constructor — position
# ---------------------------------------------------------------------------

def test_camera_rejects_position_wrong_length():
    with pytest.raises(ValueError, match="must have length 2"):
        Camera(position=(1.0, 2.0, 3.0), zoom=1.0)


def test_camera_rejects_position_string():
    with pytest.raises(TypeError, match="position must be a 2-tuple"):
        Camera(position="origin", zoom=1.0)


def test_camera_rejects_position_with_nan():
    with pytest.raises(ValueError, match=r"position\[0\] must be finite"):
        Camera(position=(float("nan"), 0.0), zoom=1.0)


def test_camera_rejects_position_with_inf():
    with pytest.raises(ValueError, match=r"position\[1\] must be finite"):
        Camera(position=(0.0, float("inf")), zoom=1.0)


def test_camera_rejects_position_with_bool_member():
    # Sneak True past the contract: would silently become 1.0.
    with pytest.raises(TypeError, match=r"position\[0\] must be a real number"):
        Camera(position=(True, 0.0), zoom=1.0)


# ---------------------------------------------------------------------------
# Camera constructor — zoom
# ---------------------------------------------------------------------------

def test_camera_rejects_zero_zoom():
    # zoom == 0 would div-by-zero inside view_matrix() and screen_to_world().
    with pytest.raises(ValueError, match="zoom must be > 0"):
        Camera(position=(0.0, 0.0), zoom=0.0)


def test_camera_rejects_negative_zoom():
    with pytest.raises(ValueError, match="zoom must be > 0"):
        Camera(position=(0.0, 0.0), zoom=-1.0)


def test_camera_rejects_nan_zoom():
    with pytest.raises(ValueError, match="zoom must be finite"):
        Camera(position=(0.0, 0.0), zoom=float("nan"))


def test_camera_rejects_string_zoom():
    with pytest.raises(TypeError, match="zoom must be a real number"):
        Camera(position=(0.0, 0.0), zoom="2x")


# ---------------------------------------------------------------------------
# Property setters — position / zoom
# ---------------------------------------------------------------------------

def test_camera_position_setter_rejects_nan():
    cam = Camera()
    with pytest.raises(ValueError, match="position.*must be finite"):
        cam.position = (float("nan"), 0.0)


def test_camera_zoom_setter_rejects_zero():
    cam = Camera()
    with pytest.raises(ValueError, match="zoom must be > 0"):
        cam.zoom = 0.0


def test_camera_position_setter_rejects_three_tuple():
    cam = Camera()
    with pytest.raises(ValueError, match="must have length 2"):
        cam.position = (1.0, 2.0, 3.0)


def test_camera_position_setter_accepts_int_pair():
    # Positive path: integer coordinates round-trip to floats.
    cam = Camera()
    cam.position = (10, 20)
    assert cam.position == (10.0, 20.0)


def test_camera_zoom_setter_accepts_int_positive():
    cam = Camera()
    cam.zoom = 4
    assert cam.zoom == 4.0
