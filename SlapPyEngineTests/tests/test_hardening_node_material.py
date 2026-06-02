"""Input-validation tests for :mod:`slappyengine.material.node_material`
(hardening round 10).

Mirrors the structure of ``test_hardening_audio.py`` /
``test_hardening_dynamics_world.py``: positive paths are covered by
``test_node_material*.py``; this file only exercises the rejection
contract added on top of ``_node_validation.py``'s helpers.

Silent-acceptance bug caught: ``NodeMaterial.connect`` previously appended
edges with no cycle check, no endpoint-id check, no port-name validation,
and no self-loop rejection. A self-loop or graph cycle would silently land
in ``_edges`` and the Rust shader compiler would fail with a generic
``ShaderCompileError`` far from the authoring site.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "python"))

from slappyengine.material.node_material import (  # noqa: E402
    AccumulateNode,
    ClampNode,
    CosNode,
    FinalColorNode,
    GravityWarpNode,
    NodeDef,
    NodeMaterial,
    NoiseNode,
    PixelChannelNode,
    PowNode,
    RayMarchNode,
    ReadFieldNode,
    ReduceOutputNode,
    RemapNode,
    SinNode,
    UVNode,
    WriteFieldNode,
)


# ---------------------------------------------------------------------------
# NodeMaterial.__init__ — name
# ---------------------------------------------------------------------------


def test_init_rejects_none_name():
    with pytest.raises(TypeError, match="name"):
        NodeMaterial(None)  # type: ignore[arg-type]


def test_init_rejects_int_name():
    with pytest.raises(TypeError, match="name"):
        NodeMaterial(42)  # type: ignore[arg-type]


def test_init_rejects_empty_name():
    with pytest.raises(ValueError, match="name"):
        NodeMaterial("")


def test_init_rejects_bytes_name():
    with pytest.raises(TypeError, match="name"):
        NodeMaterial(b"x")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# NodeMaterial.node — spec validation
# ---------------------------------------------------------------------------


def test_node_rejects_none():
    m = NodeMaterial("t")
    with pytest.raises(TypeError, match="NodeDef"):
        m.node(None)  # type: ignore[arg-type]


def test_node_rejects_plain_dict():
    m = NodeMaterial("t")
    with pytest.raises(TypeError, match="NodeDef"):
        m.node({"node_type": "UV", "params": {}, "id": "abc"})  # type: ignore[arg-type]


def test_node_rejects_unknown_node_type():
    m = NodeMaterial("t")
    bad = NodeDef(node_type="UNKNOWN_NODE_TYPE", params={})
    with pytest.raises(ValueError, match="KNOWN_NODE_TYPES"):
        m.node(bad)


def test_node_rejects_non_str_node_type():
    m = NodeMaterial("t")
    bad = NodeDef(node_type=42, params={})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="node_type"):
        m.node(bad)


def test_node_rejects_empty_node_type():
    m = NodeMaterial("t")
    bad = NodeDef(node_type="", params={})
    with pytest.raises(ValueError, match="node_type"):
        m.node(bad)


def test_node_rejects_non_dict_params():
    m = NodeMaterial("t")
    bad = NodeDef(node_type="UV", params=["not", "a", "dict"])  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="params"):
        m.node(bad)


# ---------------------------------------------------------------------------
# NodeMaterial.connect — silent-acceptance bug fix (cycle / self-loop / etc.)
# ---------------------------------------------------------------------------


def test_connect_rejects_self_loop():
    """SILENT-BUG: pre-hardening, a self-loop silently landed in _edges."""
    m = NodeMaterial("t")
    uv = m.node(UVNode())
    with pytest.raises(ValueError, match="cycle"):
        m.connect(uv, "uv", uv, "uv")


def test_connect_rejects_two_node_cycle():
    """SILENT-BUG: a -> b -> a previously silently appended."""
    m = NodeMaterial("t")
    a = m.node(UVNode())
    b = m.node(GravityWarpNode())
    m.connect(a, "uv", b, "uv")
    with pytest.raises(ValueError, match="cycle"):
        m.connect(b, "out_uv", a, "uv")


def test_connect_rejects_three_node_cycle():
    m = NodeMaterial("t")
    a = m.node(UVNode())
    b = m.node(GravityWarpNode())
    c = m.node(GravityWarpNode())
    m.connect(a, "uv", b, "uv")
    m.connect(b, "out_uv", c, "uv")
    with pytest.raises(ValueError, match="cycle"):
        m.connect(c, "out_uv", a, "uv")


def test_connect_rejects_unknown_from_node():
    m = NodeMaterial("t")
    fc = m.node(FinalColorNode())
    stranger = UVNode()  # not added to the material
    with pytest.raises(ValueError, match="from_node"):
        m.connect(stranger, "uv", fc, "color")


def test_connect_rejects_unknown_to_node():
    m = NodeMaterial("t")
    uv = m.node(UVNode())
    stranger = FinalColorNode()  # not added
    with pytest.raises(ValueError, match="to_node"):
        m.connect(uv, "uv", stranger, "color")


def test_connect_rejects_none_from_node():
    m = NodeMaterial("t")
    fc = m.node(FinalColorNode())
    with pytest.raises(TypeError, match="NodeDef"):
        m.connect(None, "uv", fc, "color")  # type: ignore[arg-type]


def test_connect_rejects_empty_from_port():
    m = NodeMaterial("t")
    uv = m.node(UVNode())
    fc = m.node(FinalColorNode())
    with pytest.raises(ValueError, match="from_port"):
        m.connect(uv, "", fc, "color")


def test_connect_rejects_non_str_from_port():
    m = NodeMaterial("t")
    uv = m.node(UVNode())
    fc = m.node(FinalColorNode())
    with pytest.raises(TypeError, match="from_port"):
        m.connect(uv, 0, fc, "color")  # type: ignore[arg-type]


def test_connect_rejects_whitespace_to_port():
    m = NodeMaterial("t")
    uv = m.node(UVNode())
    fc = m.node(FinalColorNode())
    with pytest.raises(ValueError, match="to_port"):
        m.connect(uv, "uv", fc, "   ")


def test_connect_rejects_unknown_from_port_on_typed_node():
    m = NodeMaterial("t")
    uv = m.node(UVNode())
    fc = m.node(FinalColorNode())
    with pytest.raises(ValueError, match="not in UV outputs"):
        m.connect(uv, "WRONG", fc, "color")


def test_connect_rejects_unknown_to_port_on_typed_node():
    m = NodeMaterial("t")
    uv = m.node(UVNode())
    fc = m.node(FinalColorNode())
    with pytest.raises(ValueError, match="not in FinalColor inputs"):
        m.connect(uv, "uv", fc, "WRONG")


# ---------------------------------------------------------------------------
# Factory rejection — finite-float params
# ---------------------------------------------------------------------------


def test_pow_node_rejects_nan_exponent():
    with pytest.raises(ValueError, match="exponent"):
        PowNode(exponent=float("nan"))


def test_pow_node_rejects_inf_exponent():
    with pytest.raises(ValueError, match="exponent"):
        PowNode(exponent=float("inf"))


def test_pow_node_rejects_string_exponent():
    with pytest.raises(TypeError, match="exponent"):
        PowNode(exponent="2.0")  # type: ignore[arg-type]


def test_pow_node_rejects_bool_exponent():
    """bool-as-int: ``PowNode(True)`` would silently mean exponent=1.0."""
    with pytest.raises(TypeError, match="exponent"):
        PowNode(exponent=True)  # type: ignore[arg-type]


def test_clamp_node_rejects_nan_min():
    with pytest.raises(ValueError, match="min_val"):
        ClampNode(min_val=float("nan"))


def test_clamp_node_rejects_swapped_min_max():
    with pytest.raises(ValueError, match="min_val"):
        ClampNode(min_val=1.0, max_val=0.0)


def test_gravity_warp_rejects_nan_strength():
    with pytest.raises(ValueError, match="strength"):
        GravityWarpNode(strength=float("nan"))


def test_gravity_warp_rejects_zero_radius():
    with pytest.raises(ValueError, match="radius"):
        GravityWarpNode(radius=0.0)


def test_gravity_warp_rejects_neg_radius():
    with pytest.raises(ValueError, match="radius"):
        GravityWarpNode(radius=-0.5)


def test_remap_node_rejects_nan_in_min():
    with pytest.raises(ValueError, match="in_min"):
        RemapNode(in_min=float("nan"))


def test_remap_node_rejects_degenerate_in_range():
    with pytest.raises(ValueError, match="in_min"):
        RemapNode(in_min=0.5, in_max=0.5)


def test_accumulate_rejects_decay_above_one():
    with pytest.raises(ValueError, match="decay"):
        AccumulateNode(decay=1.5)


def test_accumulate_rejects_negative_decay():
    with pytest.raises(ValueError, match="decay"):
        AccumulateNode(decay=-0.1)


def test_accumulate_rejects_nan_decay():
    with pytest.raises(ValueError, match="decay"):
        AccumulateNode(decay=float("nan"))


# ---------------------------------------------------------------------------
# Factory rejection — enum / string params
# ---------------------------------------------------------------------------


def test_noise_rejects_unknown_mode():
    with pytest.raises(ValueError, match="mode"):
        NoiseNode(mode="not_a_real_mode")


def test_noise_rejects_empty_mode():
    with pytest.raises(ValueError, match="mode"):
        NoiseNode(mode="")


def test_noise_rejects_non_str_mode():
    with pytest.raises(TypeError, match="mode"):
        NoiseNode(mode=0)  # type: ignore[arg-type]


def test_noise_rejects_zero_octaves():
    with pytest.raises(ValueError, match="octaves"):
        NoiseNode(octaves=0)


def test_noise_rejects_negative_octaves():
    with pytest.raises(ValueError, match="octaves"):
        NoiseNode(octaves=-3)


def test_noise_rejects_oversize_octaves():
    """Catch oversize ints that would explode shader compile time."""
    with pytest.raises(ValueError, match="octaves"):
        NoiseNode(octaves=10_000_000)


def test_noise_rejects_float_octaves():
    with pytest.raises(TypeError, match="octaves"):
        NoiseNode(octaves=4.0)  # type: ignore[arg-type]


def test_noise_rejects_bool_octaves():
    """bool-as-int: ``NoiseNode(octaves=True)`` would silently mean 1 octave."""
    with pytest.raises(TypeError, match="octaves"):
        NoiseNode(octaves=True)  # type: ignore[arg-type]


def test_reduce_output_rejects_unknown_op():
    with pytest.raises(ValueError, match="op"):
        ReduceOutputNode(field="alpha", op="not_a_reduction")


def test_reduce_output_rejects_non_str_field():
    with pytest.raises(TypeError, match="field"):
        ReduceOutputNode(field=42, op="sum")  # type: ignore[arg-type]


def test_read_field_rejects_empty():
    with pytest.raises(ValueError, match="field"):
        ReadFieldNode("")


def test_read_field_rejects_non_str():
    with pytest.raises(TypeError, match="field"):
        ReadFieldNode(None)  # type: ignore[arg-type]


def test_write_field_rejects_empty():
    with pytest.raises(ValueError, match="field"):
        WriteFieldNode("")


def test_pixel_channel_rejects_empty():
    with pytest.raises(ValueError, match="channel"):
        PixelChannelNode("")


def test_pixel_channel_rejects_int():
    with pytest.raises(TypeError, match="channel"):
        PixelChannelNode(0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Factory rejection — RayMarchNode
# ---------------------------------------------------------------------------


def test_ray_march_rejects_short_direction():
    with pytest.raises(ValueError, match="direction"):
        RayMarchNode(direction=(1.0,))  # type: ignore[arg-type]


def test_ray_march_rejects_long_direction():
    with pytest.raises(ValueError, match="direction"):
        RayMarchNode(direction=(1.0, 0.0, 0.0))  # type: ignore[arg-type]


def test_ray_march_rejects_nan_direction():
    with pytest.raises(ValueError, match="direction"):
        RayMarchNode(direction=(float("nan"), 0.0))


def test_ray_march_rejects_string_direction():
    with pytest.raises(TypeError, match="direction"):
        RayMarchNode(direction="north")  # type: ignore[arg-type]


def test_ray_march_rejects_zero_steps():
    with pytest.raises(ValueError, match="steps"):
        RayMarchNode(steps=0)


def test_ray_march_rejects_bool_steps():
    with pytest.raises(TypeError, match="steps"):
        RayMarchNode(steps=False)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Positive sanity (must stay green)
# ---------------------------------------------------------------------------


def test_positive_connect_dag_still_works():
    m = NodeMaterial("ok")
    uv = m.node(UVNode())
    warp = m.node(GravityWarpNode())
    sample = m.node(NodeDef(node_type="SampleTexture", params={}))
    out = m.node(FinalColorNode())
    m.connect(uv, "uv", warp, "uv")
    m.connect(warp, "out_uv", sample, "uv")
    m.connect(sample, "color", out, "color")
    assert len(m._edges) == 3


def test_positive_diamond_dag_allowed():
    """A diamond a->b, a->c, b->d, c->d is a DAG, not a cycle."""
    m = NodeMaterial("diamond")
    a = m.node(UVNode())
    b = m.node(GravityWarpNode())
    c = m.node(GravityWarpNode())
    d = m.node(NodeDef(node_type="SampleTexture", params={}))
    m.connect(a, "uv", b, "uv")
    m.connect(a, "uv", c, "uv")
    m.connect(b, "out_uv", d, "uv")
    m.connect(c, "out_uv", d, "uv")
    assert len(m._edges) == 4


def test_positive_factories_with_defaults_unchanged():
    SinNode()
    CosNode()
    PowNode()
    RemapNode()
    NoiseNode()
    AccumulateNode()
    RayMarchNode()
