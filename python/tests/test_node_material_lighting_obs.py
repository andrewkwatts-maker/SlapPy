"""Engine tests for NodeMaterial (material/node_material.py) and Observable
lighting data classes (PointLight, DirectionalLight, ConeLight).
All headless — no GPU required.
"""
from __future__ import annotations
import json
import pytest


# ---------------------------------------------------------------------------
# NodeDef factory functions
# ---------------------------------------------------------------------------

class TestNodeDefFactories:
    def test_uv_node(self):
        from slappyengine.material.node_material import UVNode
        n = UVNode()
        assert n.node_type == "UV"
        assert n.params == {}
        assert n.id  # non-empty id

    def test_pixel_color_node(self):
        from slappyengine.material.node_material import PixelColorNode
        n = PixelColorNode()
        assert n.node_type == "PixelColor"

    def test_pixel_channel_node(self):
        from slappyengine.material.node_material import PixelChannelNode
        n = PixelChannelNode("roughness")
        assert n.node_type == "PixelChannel"
        assert n.params["channel"] == "roughness"

    def test_add_node(self):
        from slappyengine.material.node_material import AddNode
        n = AddNode()
        assert n.node_type == "Add"

    def test_multiply_node(self):
        from slappyengine.material.node_material import MultiplyNode
        assert MultiplyNode().node_type == "Multiply"

    def test_lerp_node(self):
        from slappyengine.material.node_material import LerpNode
        assert LerpNode().node_type == "Lerp"

    def test_clamp_node_params(self):
        from slappyengine.material.node_material import ClampNode
        n = ClampNode(min_val=0.1, max_val=0.9)
        assert n.node_type == "Clamp"
        assert n.params["min"] == pytest.approx(0.1)
        assert n.params["max"] == pytest.approx(0.9)

    def test_gravity_warp_node_params(self):
        from slappyengine.material.node_material import GravityWarpNode
        n = GravityWarpNode(strength=3.0, radius=0.5)
        assert n.node_type == "GravityWarp"
        assert n.params["strength"] == pytest.approx(3.0)
        assert n.params["radius"] == pytest.approx(0.5)

    def test_sample_texture_node(self):
        from slappyengine.material.node_material import SampleTextureNode
        assert SampleTextureNode().node_type == "SampleTexture"

    def test_final_color_node(self):
        from slappyengine.material.node_material import FinalColorNode
        assert FinalColorNode().node_type == "FinalColor"

    def test_discard_node(self):
        from slappyengine.material.node_material import DiscardNode
        assert DiscardNode().node_type == "Discard"

    def test_read_field_node(self):
        from slappyengine.material.node_material import ReadFieldNode
        n = ReadFieldNode("puddle")
        assert n.node_type == "read_field"
        assert n.params["field"] == "puddle"

    def test_write_field_node(self):
        from slappyengine.material.node_material import WriteFieldNode
        n = WriteFieldNode("temperature")
        assert n.node_type == "write_field"
        assert n.params["field"] == "temperature"

    def test_sample_sim_field_node(self):
        from slappyengine.material.node_material import SampleSimFieldNode
        n = SampleSimFieldNode(field_ref="atmos", channel="density")
        assert n.node_type == "sample_sim_field"
        assert n.params["field_ref"] == "atmos"
        assert n.params["channel"] == "density"

    def test_sin_node(self):
        from slappyengine.material.node_material import SinNode
        assert SinNode().node_type == "sin"

    def test_cos_node(self):
        from slappyengine.material.node_material import CosNode
        assert CosNode().node_type == "cos"

    def test_pow_node(self):
        from slappyengine.material.node_material import PowNode
        n = PowNode(exponent=3.0)
        assert n.node_type == "pow"
        assert n.params["exponent"] == pytest.approx(3.0)

    def test_remap_node(self):
        from slappyengine.material.node_material import RemapNode
        n = RemapNode(in_min=0.0, in_max=1.0, out_min=0.5, out_max=2.0)
        assert n.node_type == "remap"
        assert n.params["out_max"] == pytest.approx(2.0)

    def test_length_node(self):
        from slappyengine.material.node_material import LengthNode
        assert LengthNode().node_type == "length"

    def test_normalize_node(self):
        from slappyengine.material.node_material import NormalizeNode
        assert NormalizeNode().node_type == "normalize"

    def test_dot_node(self):
        from slappyengine.material.node_material import DotNode
        assert DotNode().node_type == "dot"

    def test_noise_node(self):
        from slappyengine.material.node_material import NoiseNode
        n = NoiseNode(mode="worley", octaves=6)
        assert n.node_type == "noise"
        assert n.params["mode"] == "worley"
        assert n.params["octaves"] == 6

    def test_world_pos_node(self):
        from slappyengine.material.node_material import WorldPosNode
        assert WorldPosNode().node_type == "world_pos"

    def test_time_node(self):
        from slappyengine.material.node_material import TimeNode
        assert TimeNode().node_type == "time"

    def test_offset_uv_node(self):
        from slappyengine.material.node_material import OffsetUVNode
        assert OffsetUVNode().node_type == "offset_uv"

    def test_reflect_uv_node(self):
        from slappyengine.material.node_material import ReflectUVNode
        assert ReflectUVNode().node_type == "reflect_uv"

    def test_accumulate_node(self):
        from slappyengine.material.node_material import AccumulateNode
        n = AccumulateNode(decay=0.95)
        assert n.node_type == "accumulate"
        assert n.params["decay"] == pytest.approx(0.95)

    def test_ray_march_node(self):
        from slappyengine.material.node_material import RayMarchNode
        n = RayMarchNode(steps=8, direction=(1.0, 0.0))
        assert n.node_type == "ray_march"
        assert n.params["steps"] == 8
        assert n.params["direction"] == [1.0, 0.0]

    def test_force_output_node(self):
        from slappyengine.material.node_material import ForceOutputNode
        assert ForceOutputNode().node_type == "force_output"

    def test_reduce_output_node(self):
        from slappyengine.material.node_material import ReduceOutputNode
        n = ReduceOutputNode(field="damage", op="max")
        assert n.node_type == "reduce_output"
        assert n.params["field"] == "damage"
        assert n.params["op"] == "max"

    def test_each_factory_has_unique_id(self):
        from slappyengine.material.node_material import UVNode
        n1 = UVNode()
        n2 = UVNode()
        assert n1.id != n2.id


# ---------------------------------------------------------------------------
# NodeMaterial
# ---------------------------------------------------------------------------

class TestNodeMaterialBasics:
    def test_instantiates(self):
        from slappyengine.material.node_material import NodeMaterial
        m = NodeMaterial("effect")
        assert m is not None

    def test_name_stored(self):
        from slappyengine.material.node_material import NodeMaterial
        m = NodeMaterial("puddle_fill")
        assert m.name == "puddle_fill"

    def test_blend_default(self):
        from slappyengine.material.node_material import NodeMaterial
        assert NodeMaterial("x").blend == "normal"

    def test_wgsl_none_initially(self):
        from slappyengine.material.node_material import NodeMaterial
        m = NodeMaterial("x")
        assert m.wgsl is None

    def test_node_adds_to_material(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode
        m = NodeMaterial("test")
        n = m.node(UVNode())
        assert n in m._nodes

    def test_node_returns_same_nodedef(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode
        m = NodeMaterial("test")
        nd = UVNode()
        result = m.node(nd)
        assert result is nd

    def test_connect_adds_edge(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode, FinalColorNode
        m = NodeMaterial("test")
        uv = m.node(UVNode())
        fc = m.node(FinalColorNode())
        m.connect(uv, "uv", fc, "color")
        assert len(m._edges) == 1
        assert m._edges[0]["from_port"] == "uv"
        assert m._edges[0]["to_port"] == "color"

    def test_connect_returns_self_for_chaining(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode, FinalColorNode
        m = NodeMaterial("test")
        uv = m.node(UVNode())
        fc = m.node(FinalColorNode())
        result = m.connect(uv, "uv", fc, "color")
        assert result is m


class TestNodeMaterialSerialization:
    def test_to_json_returns_string(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode
        m = NodeMaterial("test")
        m.node(UVNode())
        result = m.to_json()
        assert isinstance(result, str)

    def test_to_json_contains_nodes_and_edges(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode
        m = NodeMaterial("test")
        m.node(UVNode())
        data = json.loads(m.to_json())
        assert "nodes" in data
        assert "edges" in data

    def test_to_json_node_type_preserved(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode
        m = NodeMaterial("test")
        m.node(UVNode())
        data = json.loads(m.to_json())
        assert data["nodes"][0]["type"] == "UV"

    def test_from_json_roundtrip_name(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode
        m = NodeMaterial("roundtrip")
        m.node(UVNode())
        json_str = m.to_json()
        m2 = NodeMaterial.from_json("roundtrip", json_str)
        assert m2.name == "roundtrip"

    def test_from_json_restores_nodes(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode, FinalColorNode
        m = NodeMaterial("test")
        m.node(UVNode())
        m.node(FinalColorNode())
        json_str = m.to_json()
        m2 = NodeMaterial.from_json("test", json_str)
        assert len(m2._nodes) == 2

    def test_from_json_restores_edges(self):
        from slappyengine.material.node_material import NodeMaterial, UVNode, FinalColorNode
        m = NodeMaterial("test")
        uv = m.node(UVNode())
        fc = m.node(FinalColorNode())
        m.connect(uv, "uv", fc, "color")
        json_str = m.to_json()
        m2 = NodeMaterial.from_json("test", json_str)
        assert len(m2._edges) == 1


class TestNodeMaterialOutputMode:
    def test_final_color_node_gives_render_mode(self):
        from slappyengine.material.node_material import NodeMaterial, FinalColorNode
        m = NodeMaterial("render_mat")
        m.node(FinalColorNode())
        assert m.output_mode == "render"

    def test_write_field_node_gives_sim_write_mode(self):
        from slappyengine.material.node_material import NodeMaterial, WriteFieldNode
        m = NodeMaterial("sim_mat")
        m.node(WriteFieldNode("puddle"))
        assert m.output_mode == "sim_write"

    def test_force_output_node_gives_force_mode(self):
        from slappyengine.material.node_material import NodeMaterial, ForceOutputNode
        m = NodeMaterial("force_mat")
        m.node(ForceOutputNode())
        assert m.output_mode == "force"

    def test_reduce_output_node_gives_reduce_mode(self):
        from slappyengine.material.node_material import NodeMaterial, ReduceOutputNode
        m = NodeMaterial("reduce_mat")
        m.node(ReduceOutputNode())
        assert m.output_mode == "reduce"

    def test_empty_material_defaults_to_render(self):
        from slappyengine.material.node_material import NodeMaterial
        m = NodeMaterial("empty")
        assert m.output_mode == "render"


# ---------------------------------------------------------------------------
# Observable lighting — PointLight, DirectionalLight, ConeLight
# ---------------------------------------------------------------------------

class TestPointLightObservable:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_intensity_change_fires_event(self):
        from slappyengine.lighting import PointLight
        from slappyengine.event_bus import subscribe
        events = []
        l = PointLight()
        subscribe("PointLight.intensity", lambda e: events.append(e))
        l.intensity = 3.0
        assert len(events) >= 1

    def test_color_change_fires_event(self):
        from slappyengine.lighting import PointLight
        from slappyengine.event_bus import subscribe
        events = []
        l = PointLight()
        subscribe("PointLight.color", lambda e: events.append(e))
        l.color = (1.0, 0.0, 0.0)
        assert len(events) >= 1

    def test_position_change_fires_event(self):
        from slappyengine.lighting import PointLight
        from slappyengine.event_bus import subscribe
        events = []
        l = PointLight()
        subscribe("PointLight.position", lambda e: events.append(e))
        l.position = (100.0, 200.0)
        assert len(events) >= 1

    def test_tags_does_not_fire_event(self):
        from slappyengine.lighting import PointLight
        from slappyengine.event_bus import subscribe
        events = []
        l = PointLight()
        subscribe("PointLight.tags", lambda e: events.append(e))
        l.tags = {"neon"}
        assert len(events) == 0

    def test_cast_shadows_does_not_fire_event(self):
        from slappyengine.lighting import PointLight
        from slappyengine.event_bus import subscribe
        events = []
        l = PointLight()
        subscribe("PointLight.cast_shadows", lambda e: events.append(e))
        l.cast_shadows = True
        assert len(events) == 0


class TestDirectionalLightObservable:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_intensity_change_fires_event(self):
        from slappyengine.lighting import DirectionalLight
        from slappyengine.event_bus import subscribe
        events = []
        l = DirectionalLight()
        subscribe("DirectionalLight.intensity", lambda e: events.append(e))
        l.intensity = 0.5
        assert len(events) >= 1

    def test_color_change_fires_event(self):
        from slappyengine.lighting import DirectionalLight
        from slappyengine.event_bus import subscribe
        events = []
        l = DirectionalLight()
        subscribe("DirectionalLight.color", lambda e: events.append(e))
        l.color = (0.9, 0.9, 1.0)
        assert len(events) >= 1

    def test_tags_does_not_fire_event(self):
        from slappyengine.lighting import DirectionalLight
        from slappyengine.event_bus import subscribe
        events = []
        l = DirectionalLight()
        subscribe("DirectionalLight.tags", lambda e: events.append(e))
        l.tags = {"sun"}
        assert len(events) == 0


class TestConeLightObservable:
    def setup_method(self):
        from slappyengine.event_bus import global_bus
        global_bus.clear()

    def test_intensity_change_fires_event(self):
        from slappyengine.lighting import ConeLight
        from slappyengine.event_bus import subscribe
        events = []
        l = ConeLight()
        subscribe("ConeLight.intensity", lambda e: events.append(e))
        l.intensity = 5.0
        assert len(events) >= 1

    def test_radius_change_fires_event(self):
        from slappyengine.lighting import ConeLight
        from slappyengine.event_bus import subscribe
        events = []
        l = ConeLight()
        subscribe("ConeLight.radius", lambda e: events.append(e))
        l.radius = 500.0
        assert len(events) >= 1

    def test_tags_does_not_fire_event(self):
        from slappyengine.lighting import ConeLight
        from slappyengine.event_bus import subscribe
        events = []
        l = ConeLight()
        subscribe("ConeLight.tags", lambda e: events.append(e))
        l.tags = {"headlight"}
        assert len(events) == 0

    def test_no_subscriber_no_crash(self):
        from slappyengine.lighting import ConeLight
        l = ConeLight()
        l.intensity = 2.0  # should not raise even with no subscribers
