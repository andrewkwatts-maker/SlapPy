from __future__ import annotations
import uuid
from dataclasses import dataclass, field


def _gen_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass
class NodeDef:
    node_type: str
    params: dict
    id: str = field(default_factory=_gen_id)


def UVNode() -> NodeDef:
    return NodeDef(node_type="UV", params={})


def PixelColorNode() -> NodeDef:
    return NodeDef(node_type="PixelColor", params={})


def PixelChannelNode(channel: str) -> NodeDef:
    return NodeDef(node_type="PixelChannel", params={"channel": channel})


def AddNode() -> NodeDef:
    return NodeDef(node_type="Add", params={})


def MultiplyNode() -> NodeDef:
    return NodeDef(node_type="Multiply", params={})


def LerpNode() -> NodeDef:
    return NodeDef(node_type="Lerp", params={})


def ClampNode(min_val: float = 0.0, max_val: float = 1.0) -> NodeDef:
    return NodeDef(node_type="Clamp", params={"min": min_val, "max": max_val})


def GravityWarpNode(strength: float = 2.0, radius: float = 0.3) -> NodeDef:
    return NodeDef(node_type="GravityWarp", params={"strength": strength, "radius": radius})


def SampleTextureNode() -> NodeDef:
    return NodeDef(node_type="SampleTexture", params={})


def FinalColorNode() -> NodeDef:
    return NodeDef(node_type="FinalColor", params={})


def DiscardNode() -> NodeDef:
    return NodeDef(node_type="Discard", params={})


# ---------------------------------------------------------------------------
# Sim-field / math / output nodes
# (see python/tests/test_node_material_lighting_obs.py and
# python/tests/test_nodegraph_compiler_e1.py for the canonical contract.)
# ---------------------------------------------------------------------------


def ReadFieldNode(field: str) -> NodeDef:
    return NodeDef(node_type="read_field", params={"field": field})


def WriteFieldNode(field: str) -> NodeDef:
    return NodeDef(node_type="write_field", params={"field": field})


def SampleSimFieldNode(field_ref: str = "", channel: str = "") -> NodeDef:
    return NodeDef(
        node_type="sample_sim_field",
        params={"field_ref": field_ref, "channel": channel},
    )


def SinNode() -> NodeDef:
    return NodeDef(node_type="sin", params={})


def CosNode() -> NodeDef:
    return NodeDef(node_type="cos", params={})


def PowNode(exponent: float = 2.0) -> NodeDef:
    return NodeDef(node_type="pow", params={"exponent": exponent})


def RemapNode(in_min: float = 0.0, in_max: float = 1.0,
              out_min: float = 0.0, out_max: float = 1.0) -> NodeDef:
    return NodeDef(
        node_type="remap",
        params={"in_min": in_min, "in_max": in_max,
                "out_min": out_min, "out_max": out_max},
    )


def LengthNode() -> NodeDef:
    return NodeDef(node_type="length", params={})


def NormalizeNode() -> NodeDef:
    return NodeDef(node_type="normalize", params={})


def DotNode() -> NodeDef:
    return NodeDef(node_type="dot", params={})


def NoiseNode(mode: str = "fbm", octaves: int = 4) -> NodeDef:
    return NodeDef(node_type="noise", params={"mode": mode, "octaves": octaves})


def WorldPosNode() -> NodeDef:
    return NodeDef(node_type="world_pos", params={})


def TimeNode() -> NodeDef:
    return NodeDef(node_type="time", params={})


def OffsetUVNode() -> NodeDef:
    return NodeDef(node_type="offset_uv", params={})


def ReflectUVNode() -> NodeDef:
    return NodeDef(node_type="reflect_uv", params={})


def AccumulateNode(decay: float = 0.9) -> NodeDef:
    return NodeDef(node_type="accumulate", params={"decay": decay})


def RayMarchNode(steps: int = 16, direction: tuple[float, float] = (0.0, 1.0)) -> NodeDef:
    return NodeDef(
        node_type="ray_march",
        params={"steps": steps, "direction": list(direction)},
    )


def ForceOutputNode() -> NodeDef:
    return NodeDef(node_type="force_output", params={})


def ReduceOutputNode(field: str = "", op: str = "sum") -> NodeDef:
    return NodeDef(node_type="reduce_output", params={"field": field, "op": op})


# Terminal node-type -> output_mode mapping. Order matters only for tie-breaking
# when a graph has multiple terminals (last terminal wins, matching the e1 test
# "test_output_mode_ignores_non_terminal_nodes" expectation).
_TERMINAL_MODES: dict[str, str] = {
    "FinalColor":    "render",
    "write_field":   "sim_write",
    "force_output":  "force",
    "reduce_output": "reduce",
}


class NodeMaterial:
    def __init__(self, name: str):
        self.name = name
        self._nodes: list[NodeDef] = []
        self._edges: list[dict] = []
        self._compiled_wgsl: str | None = None
        self.blend: str = "normal"

    def node(self, node_def: NodeDef) -> NodeDef:
        self._nodes.append(node_def)
        return node_def

    def connect(self, from_node: NodeDef, from_port: str,
                to_node: NodeDef, to_port: str) -> "NodeMaterial":
        self._edges.append({
            "from_node": from_node.id, "from_port": from_port,
            "to_node": to_node.id, "to_port": to_port,
        })
        return self

    def to_json(self) -> str:
        import json
        graph = {
            "nodes": [{"id": n.id, "type": n.node_type, "params": n.params} for n in self._nodes],
            "edges": self._edges,
        }
        return json.dumps(graph)

    @classmethod
    def from_json(cls, name: str, json_str: str) -> "NodeMaterial":
        import json
        graph = json.loads(json_str)
        mat = cls(name)
        for n in graph["nodes"]:
            nd = NodeDef(node_type=n["type"], params=n.get("params", {}), id=n["id"])
            mat._nodes.append(nd)
        mat._edges = graph.get("edges", [])
        return mat

    def compile(self) -> str:
        try:
            from slappyengine import _core
            self._compiled_wgsl = _core.compile_node_graph(self.to_json())
        except ImportError:
            raise RuntimeError("SlapPyEngine._core (Rust extension) required for node compilation")
        return self._compiled_wgsl

    @property
    def wgsl(self) -> str | None:
        return self._compiled_wgsl

    @property
    def output_mode(self) -> str:
        """Return the material's output mode based on terminal nodes.

        Determined by the last terminal node (FinalColor / write_field /
        force_output / reduce_output) in ``_nodes``. Defaults to ``"render"``
        for empty / intermediate-only graphs.
        """
        mode = "render"
        for nd in self._nodes:
            if nd.node_type in _TERMINAL_MODES:
                mode = _TERMINAL_MODES[nd.node_type]
        return mode
