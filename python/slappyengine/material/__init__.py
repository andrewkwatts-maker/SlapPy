"""Material subpackage — lazy-loaded."""
from __future__ import annotations

__all__ = [
    "NodeDef",
    "NodeMaterial",
    "UVNode",
    "PixelColorNode",
    "PixelChannelNode",
    "AddNode",
    "MultiplyNode",
    "LerpNode",
    "ClampNode",
    "GravityWarpNode",
    "SampleTextureNode",
    "FinalColorNode",
    "DiscardNode",
    "validate_node_graph",
    "KNOWN_NODE_TYPES",
    "KNOWN_PORT_TYPES",
    "ColorRange",
    "MaterialDef",
    "MaterialMap",
]

_LAZY_MAP: dict[str, str] = {
    "NodeDef":           ".node_material",
    "NodeMaterial":      ".node_material",
    "UVNode":            ".node_material",
    "PixelColorNode":    ".node_material",
    "PixelChannelNode":  ".node_material",
    "AddNode":           ".node_material",
    "MultiplyNode":      ".node_material",
    "LerpNode":          ".node_material",
    "ClampNode":         ".node_material",
    "GravityWarpNode":   ".node_material",
    "SampleTextureNode": ".node_material",
    "FinalColorNode":    ".node_material",
    "DiscardNode":       ".node_material",
    "validate_node_graph": ".graph_schema",
    "KNOWN_NODE_TYPES":  ".graph_schema",
    "KNOWN_PORT_TYPES":  ".graph_schema",
    "ColorRange":        ".map",
    "MaterialDef":       ".map",
    "MaterialMap":       ".map",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
