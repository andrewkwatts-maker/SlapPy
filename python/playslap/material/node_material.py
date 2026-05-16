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
            from playslap import _core
            self._compiled_wgsl = _core.compile_node_graph(self.to_json())
        except ImportError:
            raise RuntimeError("playslap._core (Rust extension) required for node compilation")
        return self._compiled_wgsl

    @property
    def wgsl(self) -> str | None:
        return self._compiled_wgsl
