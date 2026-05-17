"""Project Manager — HTML5 pywebview window with full JS<->Python bridge.

Provides: project creation, recent projects list, asset browser, drag-drop import.
"""
from __future__ import annotations
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.engine import Engine

_RECENT_FILE = Path.home() / ".SlapPyEngine" / "recent_projects.json"
_MAX_RECENT = 10
_PROJ_FILE = "project.slap_proj"


def _load_recent() -> list[dict]:
    try:
        return json.loads(_RECENT_FILE.read_text())
    except Exception:
        return []


def _save_recent(entries: list[dict]) -> None:
    _RECENT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _RECENT_FILE.write_text(json.dumps(entries[:_MAX_RECENT], indent=2))


def _add_recent(path: str, name: str) -> None:
    entries = [e for e in _load_recent() if e.get("path") != path]
    entries.insert(0, {
        "name": name,
        "path": path,
        "modified": datetime.now().isoformat()[:10],
    })
    _save_recent(entries)


class ProjectManagerAPI:
    """
    Python API class exposed to JavaScript via pywebview js_api.
    All public methods are callable from JS as: window.pywebview.api.method_name(arg)
    Return values are automatically serialized to JSON and returned as JS Promises.
    """

    def __init__(self, engine: "Engine", manager: "ProjectManager"):
        self._engine = engine
        self._manager = manager

    def list_recent(self) -> list[dict]:
        return _load_recent()

    def open_project(self, path: str) -> dict:
        """Read project.slap_proj and return project dict."""
        try:
            import yaml
            proj_file = Path(path) / _PROJ_FILE
            if not proj_file.exists():
                return {"error": f"No {_PROJ_FILE} found at {path}"}
            data = yaml.safe_load(proj_file.read_text())
            _add_recent(path, data.get("name", Path(path).name))

            # Restore editor mode state
            editor_data = data.get("editor", {})
            self._manager._editor_mode = editor_data.get("mode", "2D")
            layer_modes = editor_data.get("layer_modes", {})
            if self._manager._current_asset:
                for layer in self._manager._current_asset.layers:
                    if layer.name in layer_modes:
                        layer.mode = layer_modes[layer.name]

            return {"ok": True, "project": data, "path": path}
        except Exception as e:
            return {"error": str(e)}

    def save_project(self, path: str) -> dict:
        """Persist the current project state (including editor mode) to project.slap_proj."""
        try:
            import yaml
            proj_file = Path(path) / _PROJ_FILE
            if not proj_file.exists():
                return {"error": f"No {_PROJ_FILE} found at {path}"}
            data = yaml.safe_load(proj_file.read_text()) or {}

            # Serialize editor mode and per-layer modes
            data["editor"] = {
                "mode": self._manager._editor_mode
                if hasattr(self._manager, "_editor_mode")
                else "2D",
                "layer_modes": {
                    layer.name: getattr(layer, "mode", "2D")
                    for layer in (
                        self._manager._current_asset.layers
                        if self._manager._current_asset
                        else []
                    )
                },
            }

            proj_file.write_text(yaml.dump(data, default_flow_style=False))
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def create_project(self, path: str, name: str) -> dict:
        """Create a new project directory with project.slap_proj scaffold."""
        try:
            import yaml
            root = Path(path)
            root.mkdir(parents=True, exist_ok=True)
            for d in ["scenes", "assets/sprites", "assets/maps", "assets/audio", "config"]:
                (root / d).mkdir(parents=True, exist_ok=True)

            proj = {
                "name": name,
                "version": 1,
                "created": datetime.now().isoformat()[:10],
                "engine_config": "config/engine.yml",
                "entry_scene": "",
                "scenes": [],
                "assets_dir": "assets/",
            }
            (root / _PROJ_FILE).write_text(yaml.dump(proj, default_flow_style=False))
            _add_recent(path, name)
            return {"ok": True, "project": proj, "path": path}
        except Exception as e:
            return {"error": str(e)}

    def list_assets(self, project_path: str) -> list[dict]:
        """Walk the assets directory and return file info."""
        assets_dir = Path(project_path) / "assets"
        if not assets_dir.exists():
            return []
        result = []
        for p in sorted(assets_dir.rglob("*")):
            if p.is_file():
                result.append({
                    "name": p.name,
                    "rel_path": str(p.relative_to(assets_dir)),
                    "size": p.stat().st_size,
                    "ext": p.suffix.lower(),
                })
        return result

    def list_scenes(self, project_path: str) -> list[dict]:
        scenes_dir = Path(project_path) / "scenes"
        if not scenes_dir.exists():
            return []
        return [
            {"name": p.stem, "path": str(p)}
            for p in sorted(scenes_dir.glob("*.slap"))
        ]

    def import_asset(self, src: str, dest_dir: str) -> dict:
        """Copy a file into the project's asset directory."""
        try:
            src_path = Path(src)
            dest = Path(dest_dir) / src_path.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest)
            return {"ok": True, "dest": str(dest)}
        except Exception as e:
            return {"error": str(e)}

    def open_scene(self, scene_path: str) -> dict:
        """Load a scene into the engine (triggers scene switch)."""
        try:
            self._manager._selected_scene = scene_path
            return {"ok": True}
        except Exception as e:
            return {"error": str(e)}

    def select_project(self, path: str) -> dict:
        """Signal that the user chose this project — closes the window."""
        self._manager._selected_project = path
        if self._manager._window is not None:
            try:
                self._manager._window.destroy()
            except Exception:
                pass
        return {"ok": True}

    def get_engine_version(self) -> str:
        try:
            import importlib.metadata
            return importlib.metadata.version("slappyengine")
        except Exception:
            return "dev"

    def open_folder_dialog(self) -> str:
        """Open a native folder picker; returns selected path or empty string."""
        if self._manager._window is not None:
            try:
                result = self._manager._window.create_file_dialog(
                    dialog_type=10,  # FOLDER_DIALOG
                    allow_multiple=False,
                )
                if result:
                    return result[0]
            except Exception:
                pass
        return ""

    def get_wizard_mode(self) -> bool:
        """Called from JS to check if running in wizard mode."""
        return getattr(self, '_wizard_mode', False)


class ProjectManager:
    def __init__(self, engine: "Engine"):
        self._engine = engine
        self._selected_project: str = ""
        self._selected_scene: str = ""
        self._window = None
        self._api = ProjectManagerAPI(engine, self)
        # Editor mode state — persisted to / restored from project.slap_proj
        self._editor_mode: str = "2D"
        self._current_asset = None  # set by the editor when a scene asset is open

    def show(self) -> None:
        """Open the project manager window (blocks until user selects or closes)."""
        try:
            import webview
        except ImportError:
            raise ImportError(
                "pywebview is required for the Project Manager.\n"
                "Install it with: pip install SlapPyEngine[editor]"
            )

        html_path = Path(__file__).parent / "project_ui.html"
        if html_path.exists():
            html = html_path.read_text(encoding="utf-8")
        else:
            html = _FALLBACK_HTML

        self._window = webview.create_window(
            title="SlapPyEngine — Project Manager",
            html=html,
            js_api=self._api,
            width=1024,
            height=680,
            min_size=(800, 500),
            background_color="#0d0d14",
        )
        webview.start(debug=False)
        # Execution resumes here after window closes

    @property
    def selected_project(self) -> str:
        return self._selected_project


_FALLBACK_HTML = """<!DOCTYPE html>
<html><head><title>SlapPyEngine</title>
<style>body{background:#0d0d14;color:#ccc;font-family:monospace;display:flex;
align-items:center;justify-content:center;height:100vh;margin:0}
h1{color:#7af}</style></head>
<body><h1>SlapPyEngine Project Manager</h1><p>project_ui.html not found</p></body></html>"""
