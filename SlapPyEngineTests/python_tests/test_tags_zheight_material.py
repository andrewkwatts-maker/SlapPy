"""Engine tests for tags.py, z_height.py, and material/map.py + graph_schema.py.
All headless — no GPU required.
"""
from __future__ import annotations
import pytest


# ---------------------------------------------------------------------------
# TagRegistry
# ---------------------------------------------------------------------------

class TestTagRegistryDefine:
    def test_define_returns_mask(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        mask = reg.define("enemy")
        assert mask == 1  # bit 0 → mask 1

    def test_define_second_tag_different_bit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("a")
        mask_b = reg.define("b")
        assert mask_b == 2  # bit 1 → mask 2

    def test_define_idempotent(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        m1 = reg.define("player")
        m2 = reg.define("player")
        assert m1 == m2

    def test_define_explicit_bit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        mask = reg.define("special", bit=7)
        assert mask == 128

    def test_define_beyond_max_bits_raises(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry(max_bits=4)
        with pytest.raises(ValueError):
            reg.define("overflow", bit=4)

    def test_next_bit_advances_past_explicit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("high", bit=5)
        m = reg.define("next")
        assert m == 64  # next auto-bit is 6 → mask 64


class TestTagRegistryMask:
    def test_mask_single_tag(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("player")
        assert reg.mask("player") == 1

    def test_mask_multiple_tags_ored(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("enemy")
        reg.define("hazard")
        combined = reg.mask("enemy", "hazard")
        assert combined == 3

    def test_mask_undefined_raises(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        with pytest.raises(KeyError):
            reg.mask("undefined_tag")


class TestTagRegistryLookup:
    def test_name_for_bit(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("wall")
        assert reg.name_for_bit(0) == "wall"

    def test_name_for_unused_bit_none(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        assert reg.name_for_bit(99) is None

    def test_getitem(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("loot")
        assert reg["loot"] == 1

    def test_contains_true(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("boss")
        assert "boss" in reg

    def test_contains_false(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        assert "npc" not in reg

    def test_all_tags_returns_dict(self):
        from pharos_engine.tags import TagRegistry
        reg = TagRegistry()
        reg.define("fire")
        reg.define("ice")
        t = reg.all_tags()
        assert "fire" in t
        assert "ice" in t
        assert t["fire"] == 1
        assert t["ice"] == 2


# ---------------------------------------------------------------------------
# ZLayer
# ---------------------------------------------------------------------------

class TestZLayer:
    def test_instantiates(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="ground")
        assert zl is not None

    def test_default_z(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="ground")
        assert zl.z == pytest.approx(0.0)

    def test_default_parallax(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="fg")
        assert zl.parallax_x == pytest.approx(1.0)
        assert zl.parallax_y == pytest.approx(1.0)

    def test_is_shadow_receiver_default(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="road")
        assert zl.is_shadow_receiver is True

    def test_custom_parallax(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="bg", z=10.0, parallax_x=0.5, parallax_y=0.3)
        assert zl.parallax_x == pytest.approx(0.5)

    def test_hash_is_id_based(self):
        from pharos_engine.z_height import ZLayer
        zl = ZLayer(name="test")
        assert hash(zl) == id(zl)


# ---------------------------------------------------------------------------
# ZAABBShape
# ---------------------------------------------------------------------------

class TestZAABBShape:
    def test_instantiates(self):
        from pharos_engine.z_height import ZAABBShape
        s = ZAABBShape(width=32, height=32)
        assert s is not None

    def test_defaults(self):
        from pharos_engine.z_height import ZAABBShape
        s = ZAABBShape(width=16, height=16)
        assert s.z_min == pytest.approx(0.0)
        assert s.z_max == pytest.approx(0.0)
        assert s.offset_x == pytest.approx(0.0)
        assert s.offset_y == pytest.approx(0.0)

    def test_custom_z_range(self):
        from pharos_engine.z_height import ZAABBShape
        s = ZAABBShape(width=32, height=32, z_min=0.0, z_max=10.0)
        assert s.z_max == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# ZHeightModule
# ---------------------------------------------------------------------------

class TestZHeightModule:
    def test_importable(self):
        from pharos_engine.z_height import ZHeightModule
        assert ZHeightModule is not None

    def test_name(self):
        from pharos_engine.z_height import ZHeightModule
        assert ZHeightModule.name == "z_height"

    def test_channels_present(self):
        from pharos_engine.z_height import ZHeightModule
        names = [n for n, _ in ZHeightModule.channels]
        assert "z_min" in names
        assert "z_max" in names

    def test_registers(self):
        from pharos_engine.z_height import ZHeightModule
        from pharos_engine.struct_registry import StructRegistry
        reg = StructRegistry()
        reg.register(ZHeightModule)
        names = [n for n, _ in reg.channels]
        assert "z_min" in names


# ---------------------------------------------------------------------------
# check_z_aabb
# ---------------------------------------------------------------------------

class TestCheckZAabb:
    def _entity(self, z_min, z_max, z_height=0.0):
        from pharos_engine.z_height import ZAABBShape
        e = type("E", (), {})()
        e.z_collision_shape = ZAABBShape(32, 32, z_min=z_min, z_max=z_max)
        e.z_height = z_height
        return e

    def test_overlapping_z_returns_true(self):
        from pharos_engine.z_height import check_z_aabb
        a = self._entity(0.0, 5.0)
        b = self._entity(3.0, 8.0)
        assert check_z_aabb(a, b) is True

    def test_non_overlapping_z_returns_false(self):
        from pharos_engine.z_height import check_z_aabb
        a = self._entity(0.0, 5.0)
        b = self._entity(6.0, 10.0)
        assert check_z_aabb(a, b) is False

    def test_touching_edges_is_overlap(self):
        from pharos_engine.z_height import check_z_aabb
        a = self._entity(0.0, 5.0)
        b = self._entity(5.0, 10.0)
        assert check_z_aabb(a, b) is True

    def test_no_shape_returns_true(self):
        from pharos_engine.z_height import check_z_aabb
        a = type("E", (), {})()  # no z_collision_shape
        b = self._entity(0.0, 5.0)
        assert check_z_aabb(a, b) is True

    def test_z_height_offset_applied(self):
        from pharos_engine.z_height import check_z_aabb
        # a is at z 10-15, b is at z 0-5 — no overlap
        a = self._entity(0.0, 5.0, z_height=10.0)
        b = self._entity(0.0, 5.0, z_height=0.0)
        assert check_z_aabb(a, b) is False


# ---------------------------------------------------------------------------
# ColorRange
# ---------------------------------------------------------------------------

class TestColorRange:
    def test_matches_in_range(self):
        from pharos_engine.material.map import ColorRange
        cr = ColorRange(r=(100, 150), g=(0, 50), b=(200, 255))
        assert cr.matches(125, 25, 230) is True

    def test_matches_out_of_range_r(self):
        from pharos_engine.material.map import ColorRange
        cr = ColorRange(r=(100, 150), g=(0, 255), b=(0, 255))
        assert cr.matches(200, 128, 128) is False

    def test_matches_boundary_inclusive(self):
        from pharos_engine.material.map import ColorRange
        cr = ColorRange(r=(0, 100), g=(0, 100), b=(0, 100))
        assert cr.matches(0, 0, 0) is True
        assert cr.matches(100, 100, 100) is True

    def test_default_full_range(self):
        from pharos_engine.material.map import ColorRange
        cr = ColorRange()
        assert cr.matches(0, 0, 0) is True
        assert cr.matches(255, 255, 255) is True


# ---------------------------------------------------------------------------
# MaterialDef
# ---------------------------------------------------------------------------

class TestMaterialDef:
    def test_instantiates(self):
        from pharos_engine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="grass", color_range=ColorRange(r=(50, 120)))
        assert md.name == "grass"

    def test_default_alpha_meaning(self):
        from pharos_engine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="water", color_range=ColorRange())
        assert md.alpha_meaning == "opacity"

    def test_behaviors_default_empty(self):
        from pharos_engine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="stone", color_range=ColorRange())
        assert md.behaviors == []

    def test_params_default_empty(self):
        from pharos_engine.material.map import MaterialDef, ColorRange
        md = MaterialDef(name="dirt", color_range=ColorRange())
        assert md.params == {}


# ---------------------------------------------------------------------------
# MaterialMap
# ---------------------------------------------------------------------------

class TestMaterialMap:
    def test_instantiates(self):
        from pharos_engine.material.map import MaterialMap
        mm = MaterialMap()
        assert mm is not None

    def test_add_returns_def(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        md = mm.add("rock", ColorRange(r=(60, 80)))
        assert md.name == "rock"

    def test_match_finds_material(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("grass", ColorRange(r=(30, 80), g=(100, 180), b=(30, 80)))
        result = mm.match(50, 140, 50)
        assert result is not None
        assert result.name == "grass"

    def test_match_no_result_returns_none(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("grass", ColorRange(r=(30, 80), g=(100, 180), b=(30, 80)))
        result = mm.match(200, 200, 200)
        assert result is None

    def test_match_first_wins(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        mm.add("first", ColorRange())   # matches everything
        mm.add("second", ColorRange())
        result = mm.match(128, 128, 128)
        assert result.name == "first"

    def test_add_with_behaviors(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        md = mm.add("lava", ColorRange(r=(200, 255)),
                    behaviors=["burn", "melt"])
        assert "burn" in md.behaviors

    def test_add_with_params(self):
        from pharos_engine.material.map import MaterialMap, ColorRange
        mm = MaterialMap()
        md = mm.add("oil", ColorRange(), params={"friction": 0.1})
        assert md.params["friction"] == pytest.approx(0.1)

    def test_load_defaults_no_crash(self):
        from pharos_engine.material.map import MaterialMap
        mm = MaterialMap.load_defaults()
        assert mm is not None


# ---------------------------------------------------------------------------
# material/graph_schema.py
# ---------------------------------------------------------------------------

class TestGraphSchema:
    def test_known_node_types_not_empty(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        assert len(KNOWN_NODE_TYPES) > 0

    def test_core_render_nodes_present(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        for node in ("UV", "FinalColor", "Add", "Multiply", "Lerp", "SampleTexture"):
            assert node in KNOWN_NODE_TYPES

    def test_field_nodes_present(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        assert "read_field" in KNOWN_NODE_TYPES
        assert "write_field" in KNOWN_NODE_TYPES

    def test_sim_field_node_present(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        assert "sample_sim_field" in KNOWN_NODE_TYPES

    def test_output_nodes_present(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        assert "final_color" in KNOWN_NODE_TYPES
        assert "force_output" in KNOWN_NODE_TYPES
        assert "reduce_output" in KNOWN_NODE_TYPES

    def test_math_nodes_present(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        for n in ("sin", "cos", "pow", "noise"):
            assert n in KNOWN_NODE_TYPES

    def test_is_frozenset(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES
        import builtins
        assert isinstance(KNOWN_NODE_TYPES, frozenset)

    def test_known_port_types_keys_subset_of_nodes(self):
        from pharos_engine.material.graph_schema import KNOWN_NODE_TYPES, KNOWN_PORT_TYPES
        for key in KNOWN_PORT_TYPES:
            assert key in KNOWN_NODE_TYPES

    def test_port_types_have_inputs_and_outputs(self):
        from pharos_engine.material.graph_schema import KNOWN_PORT_TYPES
        for node_name, spec in KNOWN_PORT_TYPES.items():
            assert "inputs" in spec, f"{node_name} missing inputs"
            assert "outputs" in spec, f"{node_name} missing outputs"

    def test_final_color_has_no_outputs(self):
        from pharos_engine.material.graph_schema import KNOWN_PORT_TYPES
        assert KNOWN_PORT_TYPES["FinalColor"]["outputs"] == []

    def test_uv_has_no_inputs(self):
        from pharos_engine.material.graph_schema import KNOWN_PORT_TYPES
        assert KNOWN_PORT_TYPES["UV"]["inputs"] == []
