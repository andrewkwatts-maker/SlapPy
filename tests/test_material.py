"""
Tests for ColorRange, MaterialDef, and MaterialMap — no GPU required.
"""
from pathlib import Path

import pytest

from slappyengine.material import ColorRange, MaterialDef, MaterialMap


# ---------------------------------------------------------------------------
# test_color_range_matches
# ---------------------------------------------------------------------------

def test_color_range_matches():
    cr = ColorRange(r=(0, 40), g=(0, 80), b=(180, 255))
    assert cr.matches(20, 40, 200)
    assert not cr.matches(50, 40, 200)   # r out of range
    assert not cr.matches(20, 90, 200)   # g out of range
    assert not cr.matches(20, 40, 100)   # b out of range


# ---------------------------------------------------------------------------
# test_color_range_boundaries
# ---------------------------------------------------------------------------

def test_color_range_boundaries():
    cr = ColorRange(r=(100, 100), g=(100, 100), b=(100, 100))
    # Exact boundary value must match (inclusive on both ends)
    assert cr.matches(100, 100, 100)
    assert not cr.matches(99, 100, 100)
    assert not cr.matches(101, 100, 100)
    assert not cr.matches(100, 99, 100)
    assert not cr.matches(100, 100, 101)


# ---------------------------------------------------------------------------
# test_color_range_full_span
# ---------------------------------------------------------------------------

def test_color_range_full_span():
    cr = ColorRange(r=(0, 255), g=(0, 255), b=(0, 255))
    assert cr.matches(0, 0, 0)
    assert cr.matches(255, 255, 255)
    assert cr.matches(128, 128, 128)


# ---------------------------------------------------------------------------
# test_material_map_add_and_match
# ---------------------------------------------------------------------------

def test_material_map_add_and_match():
    mm = MaterialMap()
    mm.add("water", ColorRange(r=(0, 40), g=(0, 80), b=(180, 255)))
    mm.add("soil", ColorRange(r=(80, 160), g=(50, 120), b=(0, 60)))

    water = mm.match(20, 40, 200)
    assert water is not None
    assert water.name == "water"

    soil = mm.match(100, 80, 30)
    assert soil is not None
    assert soil.name == "soil"

    # No material covers mid-grey
    assert mm.match(128, 128, 128) is None


# ---------------------------------------------------------------------------
# test_material_map_no_match_returns_none
# ---------------------------------------------------------------------------

def test_material_map_no_match_returns_none():
    mm = MaterialMap()
    mm.add("water", ColorRange(r=(0, 40), g=(0, 80), b=(180, 255)))
    assert mm.match(255, 255, 0) is None


# ---------------------------------------------------------------------------
# test_material_map_first_wins
# ---------------------------------------------------------------------------

def test_material_map_first_wins():
    """First matching material wins when ranges overlap."""
    mm = MaterialMap()
    mm.add("first", ColorRange(r=(0, 255), g=(0, 255), b=(0, 255)))
    mm.add("second", ColorRange(r=(0, 100), g=(0, 100), b=(0, 100)))
    result = mm.match(50, 50, 50)
    assert result is not None
    assert result.name == "first"


# ---------------------------------------------------------------------------
# test_material_map_empty
# ---------------------------------------------------------------------------

def test_material_map_empty():
    mm = MaterialMap()
    assert mm.match(0, 0, 0) is None
    assert mm._materials == []


# ---------------------------------------------------------------------------
# test_material_map_from_yaml
# ---------------------------------------------------------------------------

def test_material_map_from_yaml():
    yml = Path(__file__).parent.parent / "config" / "materials.yml"
    if not yml.exists():
        pytest.skip("materials.yml not found")

    mm = MaterialMap.from_yaml(yml)
    assert len(mm._materials) > 0

    # Each loaded entry must be a MaterialDef with a non-empty name
    for m in mm._materials:
        assert isinstance(m, MaterialDef)
        assert m.name


# ---------------------------------------------------------------------------
# test_material_map_from_yaml_known_entries
# ---------------------------------------------------------------------------

def test_material_map_from_yaml_known_entries():
    yml = Path(__file__).parent.parent / "config" / "materials.yml"
    if not yml.exists():
        pytest.skip("materials.yml not found")

    mm = MaterialMap.from_yaml(yml)
    names = [m.name for m in mm._materials]

    assert "water" in names
    assert "soil" in names

    water = next(m for m in mm._materials if m.name == "water")
    assert water.alpha_meaning == "strength"
    assert "fluid" in water.behaviors
    assert water.params.get("viscosity") == pytest.approx(0.001)


# ---------------------------------------------------------------------------
# test_material_map_from_yaml_match
# ---------------------------------------------------------------------------

def test_material_map_from_yaml_match():
    yml = Path(__file__).parent.parent / "config" / "materials.yml"
    if not yml.exists():
        pytest.skip("materials.yml not found")

    mm = MaterialMap.from_yaml(yml)
    # A deep-blue pixel should resolve to water
    result = mm.match(10, 20, 220)
    assert result is not None
    assert result.name == "water"


# ---------------------------------------------------------------------------
# test_material_def_params
# ---------------------------------------------------------------------------

def test_material_def_params():
    mm = MaterialMap()
    m = mm.add(
        "water",
        ColorRange(r=(0, 40), g=(0, 80), b=(180, 255)),
        alpha_meaning="strength",
        behaviors=["fluid"],
        params={"viscosity": 0.001},
    )
    assert m.alpha_meaning == "strength"
    assert "fluid" in m.behaviors
    assert m.params["viscosity"] == pytest.approx(0.001)


# ---------------------------------------------------------------------------
# test_material_def_defaults
# ---------------------------------------------------------------------------

def test_material_def_defaults():
    mm = MaterialMap()
    m = mm.add("plain", ColorRange())
    # Default alpha_meaning is "opacity"
    assert m.alpha_meaning == "opacity"
    assert m.behaviors == []
    assert m.params == {}


# ---------------------------------------------------------------------------
# test_material_def_behaviors_independent
# ---------------------------------------------------------------------------

def test_material_def_behaviors_independent():
    """Two materials must not share the same behaviors list."""
    mm = MaterialMap()
    a = mm.add("a", ColorRange(r=(0, 10), g=(0, 10), b=(0, 10)))
    b = mm.add("b", ColorRange(r=(20, 30), g=(20, 30), b=(20, 30)))
    a.behaviors.append("fluid")
    assert "fluid" not in b.behaviors


# ---------------------------------------------------------------------------
# test_material_map_add_returns_material_def
# ---------------------------------------------------------------------------

def test_material_map_add_returns_material_def():
    mm = MaterialMap()
    result = mm.add("rock", ColorRange(r=(100, 180), g=(100, 180), b=(100, 180)))
    assert isinstance(result, MaterialDef)
    assert result.name == "rock"
    assert result in mm._materials


# ---------------------------------------------------------------------------
# test_material_map_multiple_materials_order
# ---------------------------------------------------------------------------

def test_material_map_multiple_materials_order():
    """Materials are matched in insertion order."""
    mm = MaterialMap()
    mm.add("a", ColorRange(r=(0, 50), g=(0, 50), b=(0, 50)))
    mm.add("b", ColorRange(r=(0, 50), g=(0, 50), b=(0, 50)))
    mm.add("c", ColorRange(r=(0, 50), g=(0, 50), b=(0, 50)))
    assert mm.match(25, 25, 25).name == "a"
