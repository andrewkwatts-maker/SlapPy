"""ScriptBindingPanel — editor panel for attaching scripts to entities via YAML manifests.

Features
--------
- Dropdown lists every ``*.py`` script found in the project's script directories.
- "Auto-create" generates a scaffold ``.py`` with stub ``on_launch / on_tick / on_end``
  functions named after the current entity/asset.
- Bound-script list shows which lifecycle hooks each script implements (✓ / –).
- Changes write back to the entity's YAML manifest immediately.
- Multiple entities can share the same script file — the panel makes this explicit.
- pub/sub bindings: shows ``global_bus.subscribe`` call sites detected in each script
  so the user can see what events the script reacts to.

DPG panel protocol: ``build(parent_tag)`` creates the widget tree;
``set_entity(entity, manifest_path=None)`` updates state.
"""
from __future__ import annotations

import ast
import re
import textwrap
from pathlib import Path
from typing import Any

_HOOK_NAMES = ("on_launch", "on_tick", "on_end")

_SCRIPT_STUB = '''\
"""Behavior script for {asset_name}.

Attach via the asset manifest:
  scripts:
    - {script_path}

Functions defined here are called automatically:
  on_launch(entity)        — once, after entity is added to scene
  on_tick(entity, dt)      — every frame; dt is seconds since last frame
  on_end(entity)           — once, when entity is removed from scene

Multiple assets can share this script. Add / remove functions freely.
The editor will detect which hooks are implemented and show them as checkmarks.
"""

def on_launch(entity):
    pass  # initialise entity state here


def on_tick(entity, dt):
    pass  # per-frame logic here


def on_end(entity):
    pass  # cleanup here
'''


# ---------------------------------------------------------------------------
# Helper: inspect a .py file for implemented hooks + pub/sub
# ---------------------------------------------------------------------------

def _inspect_script(path: Path) -> dict:
    """Return {hooks: set[str], subscribes: list[str]} for a script file."""
    result = {"hooks": set(), "subscribes": []}
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in _HOOK_NAMES:
                    result["hooks"].add(node.name)
            # Detect: global_bus.subscribe("event_name", ...)
            if isinstance(node, ast.Call):
                try:
                    fn = node.func
                    if (
                        isinstance(fn, ast.Attribute)
                        and fn.attr == "subscribe"
                        and isinstance(fn.value, ast.Name)
                        and fn.value.id in ("global_bus", "bus")
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                    ):
                        result["subscribes"].append(str(node.args[0].value))
                except Exception:
                    pass
    except Exception:
        pass
    return result


def _scan_scripts(search_dirs: list[Path]) -> list[Path]:
    """Return sorted list of .py files found in *search_dirs*."""
    found = []
    for d in search_dirs:
        if d.is_dir():
            found.extend(sorted(d.rglob("*.py")))
    return found


# ---------------------------------------------------------------------------
# ScriptBindingPanel
# ---------------------------------------------------------------------------

class ScriptBindingPanel:
    """Editor panel: attach / detach scripts to an entity's YAML manifest.

    Integrates with :class:`~slappyengine.asset_manifest.AssetManifest` and
    :class:`~slappyengine.asset_manifest.ScriptBinding`.
    """

    def __init__(self, search_dirs: list[str | Path] | None = None) -> None:
        self._entity: Any = None
        self._manifest_path: Path | None = None
        self._manifest = None      # AssetManifest | None
        self._search_dirs: list[Path] = [
            Path(d) for d in (search_dirs or ["scripts", "systems", "entities"])
        ]
        self._all_scripts: list[Path] = []
        self._selected_script: str = ""
        self._status: str = "No entity selected"
        self._panel_tag = "script_binding_panel"
        self._built: bool = False  # True only after build() creates DPG widgets

    # ------------------------------------------------------------------
    # Public: set entity
    # ------------------------------------------------------------------

    def set_entity(self, entity, manifest_path: str | Path | None = None) -> None:
        """Point the panel at *entity*, optionally with a known manifest path."""
        self._entity = entity
        self._manifest = None

        if manifest_path is not None:
            self._manifest_path = Path(manifest_path)
        else:
            # Try to find <entity_name>.yml in assets/
            name = getattr(entity, "name", None) or type(entity).__name__
            for candidate_dir in [Path("assets"), Path.cwd() / "assets"]:
                p = candidate_dir / f"{name.lower()}.yml"
                if p.exists():
                    self._manifest_path = p
                    break
            else:
                self._manifest_path = None

        if self._manifest_path and self._manifest_path.exists():
            try:
                from slappyengine.asset_manifest import AssetManifest
                self._manifest = AssetManifest.load(self._manifest_path)
            except Exception as e:
                self._set_status(f"Manifest load error: {e}", error=True)

        self._refresh_scripts()
        self._rebuild_ui()

    # ------------------------------------------------------------------
    # Build DPG widgets
    # ------------------------------------------------------------------

    def build(self, parent_tag) -> None:
        """Create the full widget tree inside *parent_tag*."""
        try:
            import dearpygui.dearpygui as dpg
        except ImportError:
            return

        dpg.add_text("Script Bindings", color=(180, 220, 255), parent=parent_tag)
        dpg.add_separator(parent=parent_tag)

        # ---- Bound scripts list -------------------------------------------
        dpg.add_text("Attached scripts:", parent=parent_tag, tag="sb_bound_label")
        with dpg.group(parent=parent_tag, tag="sb_bound_group"):
            dpg.add_text("(none)", tag="sb_bound_placeholder", color=(120, 120, 120))

        dpg.add_separator(parent=parent_tag)

        # ---- Add script from dropdown -------------------------------------
        dpg.add_text("Add script:", parent=parent_tag)
        dpg.add_combo(
            items=[],
            tag="sb_script_combo",
            width=290,
            callback=self._on_combo_change,
            parent=parent_tag,
        )
        with dpg.group(horizontal=True, parent=parent_tag):
            dpg.add_button(
                label="Attach",
                tag="sb_attach_btn",
                callback=self._on_attach,
            )
            dpg.add_button(
                label="Auto-create script",
                tag="sb_create_btn",
                callback=self._on_create,
            )

        dpg.add_separator(parent=parent_tag)
        dpg.add_text(
            self._status,
            tag="sb_status",
            color=(150, 200, 150),
            parent=parent_tag,
        )

        self._built = True
        self._refresh_scripts()
        self._rebuild_ui()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_combo_change(self, sender, app_data, user_data):
        self._selected_script = app_data

    def _on_attach(self, sender=None, app_data=None, user_data=None):
        if not self._selected_script:
            self._set_status("Select a script from the dropdown first", error=True)
            return
        if self._manifest is None:
            self._set_status("No manifest — select an entity with a YAML manifest", error=True)
            return
        rel = self._selected_script
        if rel not in self._manifest.scripts:
            self._manifest.scripts.append(rel)
            self._save_manifest()
            self._set_status(f"Attached: {rel}")
        else:
            self._set_status("Already attached", error=False)
        self._rebuild_ui()

    def _on_remove(self, sender, app_data, user_data):
        """Remove the script stored in *user_data* from the manifest."""
        script_path = user_data
        if self._manifest is None:
            return
        if script_path in self._manifest.scripts:
            self._manifest.scripts.remove(script_path)
            self._save_manifest()
            self._set_status(f"Removed: {script_path}")
        self._rebuild_ui()

    def _on_create(self, sender=None, app_data=None, user_data=None):
        """Auto-generate a scaffold .py for the current entity."""
        entity = self._entity
        if entity is None:
            self._set_status("No entity selected", error=True)
            return

        name = getattr(entity, "name", None) or type(entity).__name__
        safe_name = re.sub(r"[^a-z0-9_]", "_", name.lower())

        # Pick the first writable scripts dir
        for d in self._search_dirs:
            scripts_dir = d if d.is_absolute() else Path.cwd() / d
            if scripts_dir.is_dir() or not scripts_dir.exists():
                scripts_dir.mkdir(parents=True, exist_ok=True)
                out_path = scripts_dir / f"{safe_name}.py"
                break
        else:
            self._set_status("No scripts directory found", error=True)
            return

        if out_path.exists():
            self._set_status(f"Already exists: {out_path.name}", error=False)
        else:
            rel_str = str(out_path.relative_to(Path.cwd())).replace("\\", "/")
            content = _SCRIPT_STUB.format(
                asset_name=name, script_path=rel_str
            )
            out_path.write_text(content, encoding="utf-8")
            self._set_status(f"Created: {out_path.name}")

        # Auto-attach
        rel_str = str(out_path.relative_to(Path.cwd())).replace("\\", "/")
        if self._manifest is not None and rel_str not in self._manifest.scripts:
            self._manifest.scripts.append(rel_str)
            self._save_manifest()

        self._refresh_scripts()
        self._rebuild_ui()

    # ------------------------------------------------------------------
    # UI rebuild
    # ------------------------------------------------------------------

    def _rebuild_ui(self) -> None:
        if not self._built:
            return
        try:
            import dearpygui.dearpygui as dpg
        except ImportError:
            return

        if not dpg.does_item_exist("sb_bound_group"):
            return

        # Clear existing bound-script rows
        for child in dpg.get_item_children("sb_bound_group", slot=1) or []:
            dpg.delete_item(child)

        if self._manifest is None or not self._manifest.scripts:
            dpg.add_text(
                "(none)",
                parent="sb_bound_group",
                tag="sb_bound_placeholder",
                color=(120, 120, 120),
            )
        else:
            for script_path in self._manifest.scripts:
                info = _inspect_script(self._resolve_script(script_path))
                hooks_str = "  ".join(
                    f"{'✓' if h in info['hooks'] else '–'} {h}" for h in _HOOK_NAMES
                )
                subs = info["subscribes"]
                subs_str = f"  events: {', '.join(subs)}" if subs else ""

                with dpg.group(
                    horizontal=False, parent="sb_bound_group", indent=8
                ):
                    with dpg.group(horizontal=True):
                        dpg.add_text(
                            Path(script_path).name,
                            color=(200, 220, 255),
                        )
                        dpg.add_button(
                            label="✕",
                            small=True,
                            user_data=script_path,
                            callback=self._on_remove,
                        )
                    dpg.add_text(hooks_str, color=(160, 200, 160), indent=12)
                    if subs_str:
                        dpg.add_text(subs_str, color=(160, 160, 220), indent=12)
                dpg.add_spacer(height=2, parent="sb_bound_group")

        # Refresh dropdown
        items = [str(p.relative_to(Path.cwd())).replace("\\", "/")
                 for p in self._all_scripts]
        if dpg.does_item_exist("sb_script_combo"):
            dpg.configure_item("sb_script_combo", items=items)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_scripts(self) -> None:
        self._all_scripts = _scan_scripts(
            [d if d.is_absolute() else Path.cwd() / d for d in self._search_dirs]
        )

    def _resolve_script(self, script_path: str) -> Path:
        p = Path(script_path)
        if p.is_absolute():
            return p
        cwd = Path.cwd()
        candidate = cwd / p
        if candidate.exists():
            return candidate
        return p  # fallback — may not exist yet

    def _save_manifest(self) -> None:
        if self._manifest is None or self._manifest_path is None:
            return
        try:
            self._manifest.save(self._manifest_path)
        except Exception as e:
            self._set_status(f"Save error: {e}", error=True)

    def _set_status(self, msg: str, error: bool = False) -> None:
        self._status = msg
        if not self._built:
            return
        color = (220, 80, 80) if error else (150, 200, 150)
        try:
            import dearpygui.dearpygui as dpg
            if dpg.does_item_exist("sb_status"):
                dpg.configure_item("sb_status", default_value=msg, color=color)
        except Exception:
            pass
