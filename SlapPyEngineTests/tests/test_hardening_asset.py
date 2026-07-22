"""Negative-path tests for :class:`Asset` public-boundary validation
(hardening round 12).

The positive paths — constructing an Asset with finite coords, baking it
to a .slap file, loading via ``from_image`` — are exercised by the
residency / editor / example suites. This file only covers the rejection
cases added by ``pharos_engine._asset_validation``.

Two silent-acceptance bugs landed alongside this round:

1. ``Asset(position=(float("nan"), 0))`` used to construct fine and emit
   a blank texture on the very next render tick (NaN propagates through
   every per-frame transform).
2. ``asset.add_layer(None)`` used to land in ``RenderTarget.layers`` and
   only crashed several frames later when ``tick`` dereferenced
   ``layer.tick``, with no breadcrumb back to the offending call site.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

from pharos_engine.asset import Asset  # noqa: E402
from pharos_engine.layer import Layer  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def png_file(tmp_path) -> Path:
    """Minimal valid PNG on disk (1x1 transparent pixel)."""
    from PIL import Image
    p = tmp_path / "tiny.png"
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(p)
    return p


# ---------------------------------------------------------------------------
# Asset.__init__  (name)
# ---------------------------------------------------------------------------

def test_init_rejects_int_name():
    with pytest.raises(TypeError, match="name must be a str"):
        Asset(name=42)


def test_init_rejects_none_name():
    with pytest.raises(TypeError, match="name must be a str"):
        Asset(name=None)


def test_init_rejects_bytes_name():
    with pytest.raises(TypeError, match="name must be a str"):
        Asset(name=b"hero")


def test_init_rejects_bool_name():
    # bool is int subclass — would silently flow through as the literal
    # "True" / "False" string otherwise.
    with pytest.raises(TypeError, match="name must be a str"):
        Asset(name=True)


def test_init_accepts_empty_name():
    """Positive sanity: ``Asset()`` with no name remains the default."""
    a = Asset()
    assert a.name == ""


# ---------------------------------------------------------------------------
# Asset.__init__  (position)  — silent-acceptance bug #1: NaN position
# ---------------------------------------------------------------------------

def test_init_rejects_nan_position():
    """SILENT-ACCEPTANCE BUG #1: NaN coords used to construct fine and then
    propagate through every per-frame transform, blanking the renderer."""
    with pytest.raises(ValueError, match="position.*must be finite"):
        Asset(position=(float("nan"), 0.0))


def test_init_rejects_inf_position():
    with pytest.raises(ValueError, match="position.*must be finite"):
        Asset(position=(float("inf"), 0.0))


def test_init_rejects_short_position():
    with pytest.raises(ValueError, match="position must have length 2"):
        Asset(position=(1.0,))


def test_init_rejects_string_position():
    with pytest.raises(TypeError, match="position must be a 2-tuple"):
        Asset(position="00")


def test_init_rejects_none_position():
    with pytest.raises(TypeError, match="position must be a 2-tuple"):
        Asset(position=None)


def test_init_rejects_bool_in_position():
    with pytest.raises(TypeError, match=r"position\[0\] must be a real number"):
        Asset(position=(True, 0.0))


# ---------------------------------------------------------------------------
# Asset.__init__  (size)
# ---------------------------------------------------------------------------

def test_init_rejects_zero_size():
    """A 0-wide texture is a degenerate render target — crash on present."""
    with pytest.raises(ValueError, match=r"size\[0\] \(width\) must be >= 1"):
        Asset(size=(0, 64))


def test_init_rejects_negative_size():
    with pytest.raises(ValueError, match=r"size\[1\] \(height\) must be >= 1"):
        Asset(size=(64, -8))


def test_init_rejects_float_size():
    with pytest.raises(TypeError, match=r"size\[0\] \(width\) must be an int"):
        Asset(size=(32.5, 32))


def test_init_rejects_string_size():
    with pytest.raises(TypeError, match="size must be a 2-tuple"):
        Asset(size="64x64")


def test_init_rejects_long_size():
    with pytest.raises(ValueError, match="size must have length 2"):
        Asset(size=(64, 64, 64))


# ---------------------------------------------------------------------------
# Asset.add_layer  — silent-acceptance bug #2: None layer
# ---------------------------------------------------------------------------

def test_add_layer_rejects_none():
    """SILENT-ACCEPTANCE BUG #2: ``add_layer(None)`` used to land in
    ``RenderTarget.layers`` and only crashed several frames later when
    ``tick`` dereferenced ``layer.tick``."""
    a = Asset(size=(16, 16))
    with pytest.raises(TypeError, match="layer must be a Layer"):
        a.add_layer(None)


def test_add_layer_rejects_dict():
    a = Asset(size=(16, 16))
    with pytest.raises(TypeError, match="layer must be a Layer"):
        a.add_layer({"name": "fake"})


def test_add_layer_rejects_string():
    a = Asset(size=(16, 16))
    with pytest.raises(TypeError, match="layer must be a Layer"):
        a.add_layer("background")


def test_add_layer_accepts_blank_layer():
    """Positive sanity: a real Layer instance still flows through."""
    a = Asset(size=(16, 16))
    layer = Layer.blank(8, 8, name="bg")
    out = a.add_layer(layer)
    assert out is layer
    assert layer in a.layers


# ---------------------------------------------------------------------------
# Asset.add_effect(mat, blend)
# ---------------------------------------------------------------------------

def test_add_effect_rejects_non_material_mat():
    a = Asset(size=(16, 16))
    with pytest.raises(TypeError, match="mat must be a NodeMaterial"):
        a.add_effect("not a material")


def test_add_effect_rejects_none_mat():
    a = Asset(size=(16, 16))
    with pytest.raises(TypeError, match="mat must be a NodeMaterial"):
        a.add_effect(None)


def test_add_effect_rejects_int_blend():
    from pharos_engine.material.node_material import NodeMaterial
    a = Asset(size=(16, 16))
    mat = NodeMaterial(name="fx")
    with pytest.raises(TypeError, match="blend must be a str"):
        a.add_effect(mat, blend=42)


def test_add_effect_rejects_none_blend():
    from pharos_engine.material.node_material import NodeMaterial
    a = Asset(size=(16, 16))
    mat = NodeMaterial(name="fx")
    with pytest.raises(TypeError, match="blend must be a str"):
        a.add_effect(mat, blend=None)


def test_add_effect_rejects_empty_blend():
    from pharos_engine.material.node_material import NodeMaterial
    a = Asset(size=(16, 16))
    mat = NodeMaterial(name="fx")
    with pytest.raises(ValueError, match="blend must not be empty"):
        a.add_effect(mat, blend="")


# ---------------------------------------------------------------------------
# Asset.from_image(path, name)
# ---------------------------------------------------------------------------

def test_from_image_rejects_int_path():
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        Asset.from_image(123)


def test_from_image_rejects_none_path():
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        Asset.from_image(None)


def test_from_image_rejects_bytes_path():
    # Path(b'x') is platform-dependent on Windows — a known footgun.
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        Asset.from_image(b"sprite.png")


def test_from_image_rejects_bool_path():
    with pytest.raises(TypeError, match="path must be str or pathlib.Path"):
        Asset.from_image(True)


def test_from_image_rejects_empty_path():
    with pytest.raises(ValueError, match="path must not be empty"):
        Asset.from_image("")


def test_from_image_rejects_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError, match="path not found"):
        Asset.from_image(tmp_path / "does_not_exist.png")


def test_from_image_rejects_directory(tmp_path):
    """A directory path resolves but isn't a regular file."""
    with pytest.raises(FileNotFoundError, match="not a regular file"):
        Asset.from_image(tmp_path)


def test_from_image_rejects_traversal_to_missing(tmp_path):
    """``../../../etc/passwd`` style — Path accepts it, .exists() rejects."""
    bogus = tmp_path / ".." / ".." / "does_not_exist_anywhere.png"
    with pytest.raises(FileNotFoundError):
        Asset.from_image(bogus)


def test_from_image_rejects_url_string():
    """``http://example.com/foo.png`` — Path() accepts but the file is absent."""
    with pytest.raises(FileNotFoundError):
        Asset.from_image("http://example.com/sprite.png")


def test_from_image_rejects_int_name(png_file):
    with pytest.raises(TypeError, match="name must be a str or None"):
        Asset.from_image(png_file, name=42)


def test_from_image_rejects_bool_name(png_file):
    with pytest.raises(TypeError, match="name must be a str or None"):
        Asset.from_image(png_file, name=True)


def test_from_image_accepts_path_object(png_file):
    """Positive sanity: pathlib.Path is canonical."""
    a = Asset.from_image(png_file)
    assert a.name == png_file.stem
    assert len(a.layers) == 1


def test_from_image_accepts_explicit_name(png_file):
    """Positive sanity: explicit name overrides stem."""
    a = Asset.from_image(png_file, name="custom")
    assert a.name == "custom"


# ---------------------------------------------------------------------------
# Asset.bake_data_layer(output_path)
# ---------------------------------------------------------------------------

def test_bake_rejects_int_output_path():
    a = Asset(size=(16, 16))
    with pytest.raises(
        TypeError, match="output_path must be str, pathlib.Path, or None"
    ):
        a.bake_data_layer(output_path=42)


def test_bake_rejects_bytes_output_path():
    a = Asset(size=(16, 16))
    with pytest.raises(
        TypeError, match="output_path must be str, pathlib.Path, or None"
    ):
        a.bake_data_layer(output_path=b"out.slap")


def test_bake_rejects_bool_output_path():
    a = Asset(size=(16, 16))
    with pytest.raises(
        TypeError, match="output_path must be str, pathlib.Path, or None"
    ):
        a.bake_data_layer(output_path=True)


def test_bake_rejects_empty_output_path():
    a = Asset(size=(16, 16))
    with pytest.raises(ValueError, match="output_path must not be empty"):
        a.bake_data_layer(output_path="")


def test_bake_accepts_explicit_path(tmp_path):
    """Positive sanity: validator doesn't break the documented contract."""
    a = Asset(size=(16, 16))
    out = tmp_path / "explicit.slap"
    a.bake_data_layer(output_path=out)
    assert out.exists()


def test_bake_accepts_none_default(tmp_path, monkeypatch):
    """Positive sanity: None means "use default path"."""
    monkeypatch.chdir(tmp_path)
    a = Asset(size=(16, 16))
    a.bake_data_layer()
    expected = tmp_path / f"{a.id}_baked.slap"
    assert expected.exists()
