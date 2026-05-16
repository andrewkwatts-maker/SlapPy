"""Editor subpackage — lazy-loaded (requires [editor] extra: dearpygui)."""
from __future__ import annotations

__all__ = [
    "EditorShell",
    "ViewportPanel",
    "LayerPanel",
    "PropertyInspector",
    "MaterialEditor",
    "NodeGraphPanel",
    "TagPainter",
    "AnimGraphPanel",
    "BehaviorPanel",
    "MeshInspector",
    "LayerLightingPanel",
]

_LAZY_MAP: dict[str, str] = {
    "EditorShell":        ".shell",
    "ViewportPanel":      ".viewport_panel",
    "LayerPanel":         ".layer_panel",
    "PropertyInspector":  ".property_inspector",
    "MaterialEditor":     ".material_editor",
    "NodeGraphPanel":     ".node_graph_panel",
    "TagPainter":         ".tag_painter",
    "AnimGraphPanel":     ".anim_graph_panel",
    "BehaviorPanel":      ".behavior_panel",
    "MeshInspector":      ".mesh_inspector",
    "LayerLightingPanel": ".layer_lighting_panel",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
