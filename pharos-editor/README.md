# PharosEditor

Notebook-style editor UI for PharosEngine.

`pip install pharos-editor` transitively installs `pharos-engine` and adds:

- DearPyGui-based panels, gizmos, spawn menu, scene outliner
- Diary/notebook themes with hot-reload
- Layout persistence (YAML)
- Nova3D-inspired panel patterns (adopted verbatim per audit)
- Ollama manager for local LLM authoring

Run the editor:

```
pharos-edit path/to/project
```

Or from Python:

```python
import pharos_editor
pharos_editor.launch()
```

The engine works standalone via `pip install pharos-engine` (no UI deps).
