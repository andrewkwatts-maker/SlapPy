import pytest

from slappyengine.material.node_material import (
    NodeMaterial, ReadFieldNode, WriteFieldNode, SampleSimFieldNode,
    SinNode, CosNode, RemapNode, NoiseNode, TimeNode, WorldPosNode,
    ForceOutputNode, ReduceOutputNode, OffsetUVNode, FinalColorNode,
    AccumulateNode, LerpNode,
)


def test_new_node_types_create():
    for fn in [ReadFieldNode("puddle"), WriteFieldNode("puddle"),
               SampleSimFieldNode("atmos", "density"),
               SinNode(), CosNode(), RemapNode(0, 1, 0, 10),
               NoiseNode("fbm", 4), TimeNode(), WorldPosNode(),
               ForceOutputNode(), ReduceOutputNode("alpha", "mean"),
               OffsetUVNode(), AccumulateNode(0.95)]:
        assert fn.node_type  # has a type string


def test_output_mode_render():
    m = NodeMaterial("test")
    m.node(FinalColorNode())
    assert m.output_mode == "render"


def test_output_mode_sim_write():
    m = NodeMaterial("test")
    m.node(WriteFieldNode("puddle"))
    assert m.output_mode == "sim_write"


def test_output_mode_force():
    m = NodeMaterial("test")
    m.node(ForceOutputNode())
    assert m.output_mode == "force"


def test_output_mode_reduce():
    m = NodeMaterial("test")
    m.node(ReduceOutputNode("alpha", "max"))
    assert m.output_mode == "reduce"


def test_node_chain_builds():
    m = NodeMaterial("puddle_fill")
    rain = m.node(ReadFieldNode("rainfall_rate"))
    sin_t = m.node(SinNode())
    clamped = m.node(RemapNode(0, 1, 0, 0.5))
    out = m.node(WriteFieldNode("puddle"))
    # Should not raise
