"""Material subpackage — lazy-loaded."""
from __future__ import annotations

__all__ = [
    "AddNode",
    "ClampNode",
    "ColorRange",
    "DiscardNode",
    "FinalColorNode",
    "GravityWarpNode",
    "KNOWN_NODE_TYPES",
    "KNOWN_PORT_TYPES",
    "LerpNode",
    "MaterialDef",
    "MaterialMap",
    "MultiplyNode",
    "NodeDef",
    "NodeMaterial",
    "PixelChannelNode",
    "PixelColorNode",
    "SampleTextureNode",
    "UVNode",
    "validate_node_graph",
]

_LAZY_MAP: dict[str, str] = {
    "AddNode":           ".node_material",
    "ClampNode":         ".node_material",
    "ColorRange":        ".map",
    "DiscardNode":       ".node_material",
    "FinalColorNode":    ".node_material",
    "GravityWarpNode":   ".node_material",
    "KNOWN_NODE_TYPES":  ".graph_schema",
    "KNOWN_PORT_TYPES":  ".graph_schema",
    "LerpNode":          ".node_material",
    "MaterialDef":       ".map",
    "MaterialMap":       ".map",
    "MultiplyNode":      ".node_material",
    "NodeDef":           ".node_material",
    "NodeMaterial":      ".node_material",
    "PixelChannelNode":  ".node_material",
    "PixelColorNode":    ".node_material",
    "SampleTextureNode": ".node_material",
    "UVNode":            ".node_material",
    "validate_node_graph": ".graph_schema",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
