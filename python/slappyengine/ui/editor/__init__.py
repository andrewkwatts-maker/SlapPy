"""Editor subpackage — lazy-loaded (requires [editor] extra: dearpygui)."""
from __future__ import annotations

__all__ = [
    "AnimGraphPanel",
    "BehaviorPanel",
    "EditorShell",
    "LayerLightingPanel",
    "LayerPanel",
    "MaterialEditor",
    "MeshInspector",
    "NodeGraphPanel",
    "NotebookInspector",
    "NotebookMaterialEditor",
    "NotebookWelcome",
    "PropertyInspector",
    "TagPainter",
    "ViewportPanel",
]

_LAZY_MAP: dict[str, str] = {
    "AnimGraphPanel":         ".anim_graph_panel",
    "BehaviorPanel":          ".behavior_panel",
    "EditorShell":            ".shell",
    "LayerLightingPanel":     ".layer_lighting_panel",
    "LayerPanel":             ".layer_panel",
    "MaterialEditor":         ".material_editor",
    "MeshInspector":          ".mesh_inspector",
    "NodeGraphPanel":         ".node_graph_panel",
    "NotebookInspector":      ".notebook_inspector",
    "NotebookMaterialEditor": ".notebook_material_editor",
    "NotebookWelcome":        ".notebook_welcome",
    "PropertyInspector":      ".property_inspector",
    "TagPainter":             ".tag_painter",
    "ViewportPanel":          ".viewport_panel",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
