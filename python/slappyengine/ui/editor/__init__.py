"""Editor subpackage — lazy-loaded (requires [editor] extra: dearpygui)."""
from __future__ import annotations

__all__ = [
    "AnimGraphPanel",
    "BehaviorPanel",
    "DEFAULT_LAYOUT",
    "DEFAULT_PAGES",
    "DiaryPage",
    "DiaryShell",
    "EditorLayout",
    "EditorShell",
    "EntityClipboard",
    "LayerLightingPanel",
    "LayerPanel",
    "LayoutPersistence",
    "MaterialEditor",
    "MeshInspector",
    "NodeGraphPanel",
    "NotebookDiaryPage",
    "NotebookInspector",
    "NotebookMaterialEditor",
    "NotebookWelcome",
    "PRESET_LAYOUTS",
    "PanelLayoutState",
    "PropertyInspector",
    "SaveOnQuitPrompt",
    "SavePromptChoice",
    "TRIPLE_PANE_LAYOUT",
    "TagPainter",
    "TooltipEntry",
    "TooltipRegistry",
    "UndoEntry",
    "UndoStack",
    "ViewportPanel",
    "WIDE_CODE_LAYOUT",
    "build_default_tooltip_registry",
    "get_active_clipboard",
    "reset_active_clipboard",
    "resolve_undo_stack",
]

_LAZY_MAP: dict[str, str] = {
    "AnimGraphPanel":         ".anim_graph_panel",
    "BehaviorPanel":          ".behavior_panel",
    "DEFAULT_LAYOUT":         ".default_layouts",
    "DEFAULT_PAGES":          ".diary_shell",
    "DiaryPage":              ".diary_shell",
    "DiaryShell":             ".diary_shell",
    "EditorLayout":           ".layout_persistence",
    "EditorShell":            ".shell",
    "LayerLightingPanel":     ".layer_lighting_panel",
    "LayerPanel":             ".layer_panel",
    "LayoutPersistence":      ".layout_persistence",
    "MaterialEditor":         ".material_editor",
    "MeshInspector":          ".mesh_inspector",
    "NodeGraphPanel":         ".node_graph_panel",
    "NotebookDiaryPage":      ".notebook_diary_page",
    "NotebookInspector":      ".notebook_inspector",
    "NotebookMaterialEditor": ".notebook_material_editor",
    "NotebookWelcome":        ".notebook_welcome",
    "PanelLayoutState":       ".layout_persistence",
    "PRESET_LAYOUTS":         ".default_layouts",
    "PropertyInspector":      ".property_inspector",
    "TRIPLE_PANE_LAYOUT":     ".default_layouts",
    "TagPainter":             ".tag_painter",
    "ViewportPanel":          ".viewport_panel",
    "WIDE_CODE_LAYOUT":       ".default_layouts",
    # Usability polish landings — 2026-07-04 sprint
    "EntityClipboard":                ".entity_clipboard",
    "SaveOnQuitPrompt":               ".save_on_quit",
    "SavePromptChoice":               ".save_on_quit",
    "TooltipEntry":                   ".tooltip_registry",
    "TooltipRegistry":                ".tooltip_registry",
    "UndoEntry":                      ".editor_undo",
    "UndoStack":                      ".editor_undo",
    "build_default_tooltip_registry": ".tooltip_registry",
    "get_active_clipboard":           ".entity_clipboard",
    "reset_active_clipboard":         ".entity_clipboard",
    "resolve_undo_stack":             ".editor_undo",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        val = getattr(mod, name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
