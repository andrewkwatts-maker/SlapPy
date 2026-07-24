"""editor_v2 panel bodies — real implementations bridged to the engine.

Every panel takes an :class:`EditorState` at construction and reads
selection / command_stack / clipboard from there so cross-panel
interactions (select in Hierarchy -> inspect in Properties -> Ctrl+C
-> Ctrl+V spawns copy -> Ctrl+Z undoes) work without threading
state manually.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from imgui_bundle import imgui

from pharos_editor.ui.editor_v2.camera_controller import FlyCameraController
from pharos_editor.ui.editor_v2.commands import (
    DeleteEntityCommand,
    DuplicateEntityCommand,
    SpawnEntityCommand,
)
from pharos_editor.ui.editor_v2.editor_state import EditorState


# ---------------------------------------------------------------------------
# Hierarchy — scene tree with multi-select + right-click + commands
# ---------------------------------------------------------------------------

class HierarchyPanel:
    """Scene outliner. Ctrl/Shift-click multi-select; right-click context menu."""

    def __init__(self, state: EditorState) -> None:
        self._state = state
        self._filter: str = ""
        # For the right-click popup target (need to remember which id
        # the user clicked between right-click and menu-item click).
        self._context_target_id: str | None = None

    def _get_entities(self) -> list[Any]:
        try:
            scene = getattr(self._state.engine, "scene", None)
            if scene is None:
                return []
            return list(scene.entities)
        except Exception:
            return []

    def gui(self) -> None:
        entities = self._get_entities()

        changed, self._filter = imgui.input_text_with_hint(
            "##hier_filter", "Search entities…", self._filter
        )
        imgui.same_line()
        if imgui.button("+ Add"):
            self._spawn_default_entity()
        imgui.same_line()
        imgui.text_disabled(f"{len(entities)} entities")

        imgui.separator()

        if not entities:
            imgui.text_disabled("Scene is empty. Use + Add to create an entity.")
            self._render_scene_context_popup(entities)
            return

        needle = self._filter.strip().lower()
        selected_ids = set(self._state.selected_ids())
        siblings = [getattr(e, "id", "") for e in entities]

        for e in entities:
            name = getattr(e, "name", "") or "<unnamed>"
            eid = getattr(e, "id", "?")
            if needle and needle not in name.lower():
                continue

            flags = imgui.TreeNodeFlags_.leaf | imgui.TreeNodeFlags_.no_tree_push_on_open
            if eid in selected_ids:
                flags |= imgui.TreeNodeFlags_.selected

            imgui.tree_node_ex(f"{name}##{eid}", flags)

            # Selection on left-click (with modifier awareness).
            if imgui.is_item_clicked(0):
                self._on_click(eid, siblings)

            # Right-click: remember target + open popup below.
            if imgui.is_item_clicked(1):
                self._context_target_id = eid
                if eid not in selected_ids:
                    # Right-click on unselected entity selects it single.
                    if self._state.selection is not None:
                        self._state.selection.selection.set_single(eid)
                        self._state.notify_selection_changed()
                imgui.open_popup("##hier_entity_ctx")

        self._render_entity_context_popup()
        self._render_scene_context_popup(entities)

    # ── Interaction ────────────────────────────────────────────────────

    def _on_click(self, eid: str, siblings: list[str]) -> None:
        io = imgui.get_io()
        if self._state.selection is None:
            return
        self._state.selection.handle_click(
            eid, ctrl=io.key_ctrl, shift=io.key_shift, siblings=siblings
        )
        self._state.notify_selection_changed()

    def _render_entity_context_popup(self) -> None:
        if not imgui.begin_popup("##hier_entity_ctx"):
            return
        target_id = self._context_target_id
        multi = len(self._state.selected_ids()) > 1
        label_dup = "Duplicate Selection" if multi else "Duplicate"
        label_del = "Delete Selection" if multi else "Delete"
        if imgui.menu_item_simple(label_dup, "Ctrl+D"):
            self._duplicate_selection()
        if imgui.menu_item_simple("Copy", "Ctrl+C"):
            self._copy_selection()
        if imgui.menu_item_simple("Paste", "Ctrl+V"):
            self._paste_from_clipboard()
        imgui.separator()
        if imgui.menu_item_simple(label_del, "Del"):
            self._delete_selection()
        imgui.separator()
        if imgui.menu_item_simple("Frame in Viewport", "F"):
            self._frame_selection()
        imgui.end_popup()

    def _render_scene_context_popup(self, entities: list[Any]) -> None:
        # Empty-space right-click opens the "create" popup.
        # PopupFlags_.mouse_button_right is the standard "right-click
        # on the containing window's background" trigger.
        try:
            flags = imgui.PopupFlags_.mouse_button_right.value
        except Exception:
            flags = 0
        if imgui.begin_popup_context_window("##hier_scene_ctx", flags):
            if imgui.menu_item_simple("New Entity"):
                self._spawn_default_entity()
            if imgui.menu_item_simple("Paste", "Ctrl+V"):
                self._paste_from_clipboard()
            imgui.end_popup()

    # ── Command-stack-backed mutations ────────────────────────────────

    def _spawn_default_entity(self) -> None:
        try:
            from pharos_engine.entity import Entity

            scene = getattr(self._state.engine, "scene", None)
            if scene is None:
                return
            n = scene.entity_count() if hasattr(scene, "entity_count") else 0
            e = Entity(name=f"Entity_{n + 1}", position=(0.0, 0.0))
            cmd = SpawnEntityCommand(scene=scene, entity=e)
            self._push_command(cmd)
            if self._state.selection is not None:
                self._state.selection.selection.set_single(e.id)
                self._state.notify_selection_changed()
        except Exception:
            pass

    def _delete_selection(self) -> None:
        try:
            scene = getattr(self._state.engine, "scene", None)
            selected = self._state.selected_entities()
            if scene is None or not selected:
                return
            cmd = DeleteEntityCommand(scene=scene, entities=list(selected))
            self._push_command(cmd)
            if self._state.selection is not None:
                self._state.selection.selection.clear()
                self._state.notify_selection_changed()
        except Exception:
            pass

    def _duplicate_selection(self) -> None:
        try:
            scene = getattr(self._state.engine, "scene", None)
            selected = self._state.selected_entities()
            if scene is None or not selected:
                return
            cmd = DuplicateEntityCommand(scene=scene, originals=list(selected))
            self._push_command(cmd)
            # Select the newly-created copies after the command runs.
            if self._state.selection is not None and cmd.copies:
                self._state.selection.selection.clear()
                for c in cmd.copies:
                    self._state.selection.selection.add(c.id)
                self._state.notify_selection_changed()
        except Exception:
            pass

    def _copy_selection(self) -> None:
        try:
            from pharos_editor.clipboard import ClipboardPayload

            entities = self._state.selected_entities()
            if not entities or self._state.clipboard is None:
                return
            payload_data = [
                {
                    "name": getattr(e, "name", ""),
                    "position": list(getattr(e, "position", (0.0, 0.0))),
                    "rotation": float(getattr(e, "rotation", 0.0)),
                    "scale": float(getattr(e, "scale", 1.0)),
                    "tags": sorted(list(getattr(e, "tags", set()))),
                }
                for e in entities
            ]
            self._state.clipboard.copy(
                ClipboardPayload(kind="entity", schema_version=1, payload={"entities": payload_data})
            )
        except Exception:
            pass

    def _paste_from_clipboard(self) -> None:
        try:
            from pharos_engine.entity import Entity

            if self._state.clipboard is None:
                return
            payload = self._state.clipboard.paste()
            if payload is None or payload.kind != "entity":
                return
            scene = getattr(self._state.engine, "scene", None)
            if scene is None:
                return
            for row in payload.payload.get("entities", []):
                e = Entity(
                    name=f"{row.get('name', 'Entity')} (paste)",
                    position=tuple(row.get("position", (0.0, 0.0))),
                )
                e.rotation = float(row.get("rotation", 0.0))
                e.scale = float(row.get("scale", 1.0))
                e.tags = set(row.get("tags", []))
                cmd = SpawnEntityCommand(scene=scene, entity=e, label="Paste Entity")
                self._push_command(cmd)
        except Exception:
            pass

    def _frame_selection(self) -> None:
        # Emit a telemetry event; the ViewportPanel subscribes and centres
        # its camera target on the selection.
        try:
            from pharos_engine.telemetry import emit

            ids = self._state.selected_ids()
            if ids:
                emit("editor.v2.frame_selection", ids=ids, level="info")
        except Exception:
            pass

    def _push_command(self, cmd: Any) -> None:
        try:
            if self._state.command_stack is not None:
                self._state.command_stack.push_and_do(cmd)
            else:
                cmd.do()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Properties — inspector for the currently-selected entity
# ---------------------------------------------------------------------------

class PropertiesPanel:
    """Reads EditorState selection; renders transform + tags + components."""

    def __init__(self, state: EditorState) -> None:
        self._state = state

    def gui(self) -> None:
        entities = self._state.selected_entities()
        if not entities:
            imgui.text_disabled("No object selected.")
            imgui.text_disabled("Pick an entity in the Hierarchy panel to inspect it.")
            return
        # Multi-selection: show "Multi (N)" header + count.
        if len(entities) > 1:
            imgui.text_colored(imgui.ImVec4(0.31, 0.81, 0.69, 1.0), f"Multiple ({len(entities)}) selected")
            imgui.text_disabled("Inspecting first entity; batch-edit lands in a later sprint.")
            imgui.separator()

        entity = entities[0]
        name = getattr(entity, "name", "<unnamed>") or "<unnamed>"
        imgui.text_colored(imgui.ImVec4(0.31, 0.81, 0.69, 1.0), name)
        imgui.same_line()
        imgui.text_disabled(f"id={getattr(entity, 'id', '?')[:8]}")

        imgui.separator()

        if imgui.collapsing_header("Transform", imgui.TreeNodeFlags_.default_open):
            pos = list(getattr(entity, "position", (0.0, 0.0)))
            if len(pos) < 2:
                pos = [0.0, 0.0]
            changed, new_pos = imgui.drag_float2("Position", pos, 0.01)
            if changed:
                try:
                    entity.position = (float(new_pos[0]), float(new_pos[1]))
                except Exception:
                    pass

            rot = float(getattr(entity, "rotation", 0.0))
            changed, new_rot = imgui.drag_float("Rotation", rot, 0.5)
            if changed:
                try:
                    entity.rotation = float(new_rot)
                except Exception:
                    pass

            scl = float(getattr(entity, "scale", 1.0))
            changed, new_scl = imgui.drag_float("Scale", scl, 0.01, 0.01, 100.0)
            if changed:
                try:
                    entity.scale = float(new_scl)
                except Exception:
                    pass

        if imgui.collapsing_header("Tags"):
            tags = getattr(entity, "tags", set())
            if not tags:
                imgui.text_disabled("(no tags)")
            else:
                for t in sorted(tags):
                    imgui.bullet_text(str(t))

        if imgui.collapsing_header("Components"):
            comps = getattr(entity, "_components", {}) or {}
            if not comps:
                imgui.text_disabled("(none)")
            else:
                for cname, cobj in comps.items():
                    imgui.bullet_text(f"{cname}: {type(cobj).__name__}")


# ---------------------------------------------------------------------------
# Console — telemetry + logging bridge
# ---------------------------------------------------------------------------

class ConsolePanel:
    LEVELS = ("dbg", "info", "warn", "err")
    LEVEL_COLOURS = {
        "dbg":  imgui.ImVec4(0.60, 0.60, 0.65, 1.0),
        "info": imgui.ImVec4(0.31, 0.81, 0.69, 1.0),
        "warn": imgui.ImVec4(0.95, 0.75, 0.20, 1.0),
        "err":  imgui.ImVec4(0.95, 0.35, 0.30, 1.0),
    }

    def __init__(self, capacity: int = 2000) -> None:
        self._capacity = capacity
        self._entries: list[tuple[float, str, str, str]] = []
        self._enabled_levels: set[str] = set(self.LEVELS)
        self._follow_tail: bool = True
        self._filter: str = ""
        self._sub_handle: Any = None
        self._attach()

    def _attach(self) -> None:
        try:
            from pharos_engine.telemetry import subscribe

            def _handler(evt: Any) -> None:
                name = getattr(evt, "name", "?")
                payload = getattr(evt, "payload", {}) or {}
                level = str(payload.get("level", "info")).lower()
                if level not in self.LEVELS:
                    level = "info"
                if "message" in payload:
                    msg = str(payload["message"])
                elif payload:
                    msg = ", ".join(f"{k}={v!r}" for k, v in payload.items())
                else:
                    msg = ""
                self._append(level, name, msg)

            self._sub_handle = subscribe("*", _handler)
            self._append("info", "editor.v2.boot", "console attached to telemetry bus")
        except Exception:
            self._append("warn", "editor.v2.boot", "telemetry unavailable")

    def _append(self, level: str, topic: str, msg: str) -> None:
        self._entries.append((time.time(), level, topic, msg))
        if len(self._entries) > self._capacity:
            del self._entries[: len(self._entries) - self._capacity]

    def gui(self) -> None:
        if imgui.button("Clear"):
            self._entries.clear()
        imgui.same_line()
        _, self._follow_tail = imgui.checkbox("Follow", self._follow_tail)
        imgui.same_line()
        for lvl in self.LEVELS:
            on = lvl in self._enabled_levels
            changed, on = imgui.checkbox(lvl.upper(), on)
            if changed:
                (self._enabled_levels.add if on else self._enabled_levels.discard)(lvl)
            imgui.same_line()
        imgui.set_next_item_width(-1)
        _, self._filter = imgui.input_text_with_hint("##console_filter", "Filter…", self._filter)

        imgui.separator()
        imgui.begin_child("##console_body", imgui.ImVec2(0, 0), imgui.ChildFlags_.borders)
        needle = self._filter.strip().lower()
        for t, lvl, topic, msg in self._entries:
            if lvl not in self._enabled_levels:
                continue
            if needle and needle not in msg.lower() and needle not in topic.lower():
                continue
            colour = self.LEVEL_COLOURS.get(lvl, imgui.ImVec4(1, 1, 1, 1))
            imgui.text_colored(colour, f"[{lvl}]")
            imgui.same_line()
            imgui.text_disabled(topic)
            imgui.same_line()
            imgui.text(msg)
        if self._follow_tail and imgui.get_scroll_max_y() > 0:
            imgui.set_scroll_here_y(1.0)
        imgui.end_child()


# ---------------------------------------------------------------------------
# Content browser — folder tree + thumbnail grid
# ---------------------------------------------------------------------------

class ContentBrowserPanel:
    """Folder navigator with a thumbnail grid on the right."""

    THUMB_SIZE = 96
    THUMB_PADDING = 12

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            candidates = [
                Path.cwd() / "PharosEngineExamples",
                Path.cwd() / "examples",
                Path.cwd(),
            ]
            root = next((c for c in candidates if c.exists()), Path.cwd())
        try:
            from pharos_editor.breadcrumbs import BreadcrumbHistory

            self._history = BreadcrumbHistory(root=root)
        except Exception:
            self._history = None
        self._root = root.resolve()
        self._thumb_cache: dict[str, Any] = {}   # path -> ndarray or None

    def gui(self) -> None:
        # ── Breadcrumb toolbar ─────────────────────────────────────────
        cur = self._history.current() if self._history else self._root
        if imgui.button("<"):
            if self._history:
                self._history.go_back()
        imgui.same_line()
        if imgui.button(">"):
            if self._history:
                self._history.go_forward()
        imgui.same_line()
        if imgui.button("^"):
            if self._history:
                self._history.go_up()
        imgui.same_line()
        if imgui.button("Home"):
            if self._history:
                self._history.go_home()
        imgui.same_line()
        imgui.text_disabled(str(cur))

        imgui.separator()

        cur = self._history.current() if self._history else self._root
        try:
            items = sorted(cur.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception:
            imgui.text_disabled(f"(cannot read {cur})")
            return

        if not items:
            imgui.text_disabled("(folder is empty)")
            return

        # ── Thumbnail grid ─────────────────────────────────────────────
        avail = imgui.get_content_region_avail()
        cell = self.THUMB_SIZE + self.THUMB_PADDING
        cols = max(1, int(avail.x // cell))
        col = 0
        for p in items:
            self._draw_item(p)
            col += 1
            if col < cols:
                imgui.same_line()
            else:
                col = 0

    def _draw_item(self, path: Path) -> None:
        # Small vertical group so image + label align.
        imgui.begin_group()
        self._draw_thumbnail(path)
        # Truncate long names to keep the cell width predictable.
        label = path.name
        if len(label) > 14:
            label = label[:11] + "…"
        imgui.text_wrapped(label)
        imgui.end_group()
        if imgui.is_item_clicked(0):
            self._on_activate(path)

    def _draw_thumbnail(self, path: Path) -> None:
        # Try to load image files via PIL; folders + non-images get a
        # coloured placeholder.
        img = self._thumb_for(path)
        if img is not None:
            try:
                from imgui_bundle import immvision

                immvision.image_display(
                    f"##thumb_{path}", img,
                    image_display_size=(self.THUMB_SIZE, self.THUMB_SIZE),
                    refresh_image=False,
                )
                return
            except Exception:
                pass

        # Placeholder: coloured rect + icon glyph.
        pos_min = imgui.get_cursor_screen_pos()
        pos_max = imgui.ImVec2(pos_min.x + self.THUMB_SIZE, pos_min.y + self.THUMB_SIZE)
        dl = imgui.get_window_draw_list()
        if path.is_dir():
            fill = imgui.get_color_u32(imgui.ImVec4(0.28, 0.35, 0.55, 1.0))
            glyph = "[DIR]"
        else:
            fill = imgui.get_color_u32(imgui.ImVec4(0.32, 0.32, 0.36, 1.0))
            glyph = path.suffix.upper().lstrip(".") or "?"
        dl.add_rect_filled(pos_min, pos_max, fill, 6.0)
        text_col = imgui.get_color_u32(imgui.ImVec4(0.90, 0.90, 0.95, 1.0))
        text_size = imgui.calc_text_size(glyph)
        tx = pos_min.x + (self.THUMB_SIZE - text_size.x) * 0.5
        ty = pos_min.y + (self.THUMB_SIZE - text_size.y) * 0.5
        dl.add_text(imgui.ImVec2(tx, ty), text_col, glyph)
        imgui.dummy(imgui.ImVec2(self.THUMB_SIZE, self.THUMB_SIZE))

    def _thumb_for(self, path: Path) -> Any | None:
        key = str(path)
        if key in self._thumb_cache:
            return self._thumb_cache[key]
        if path.is_dir():
            self._thumb_cache[key] = None
            return None
        # Load only image-ish extensions to avoid PIL choking on random files.
        ext = path.suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tga", ".gif"}:
            self._thumb_cache[key] = None
            return None
        try:
            from PIL import Image
            import numpy as np

            img = Image.open(path)
            img.thumbnail((self.THUMB_SIZE, self.THUMB_SIZE))
            arr = np.array(img.convert("RGB"))
            # immvision expects contiguous HxWx3.
            arr = np.ascontiguousarray(arr)
            self._thumb_cache[key] = arr
            return arr
        except Exception:
            self._thumb_cache[key] = None
            return None

    def _on_activate(self, path: Path) -> None:
        if path.is_dir() and self._history:
            self._history.navigate(path)


# ---------------------------------------------------------------------------
# Viewport — Rust wgpu blit + fly camera + scene submission
# ---------------------------------------------------------------------------

class ViewportPanel:
    """3D viewport. Rust owns pixels; Python owns UI + input."""

    def __init__(self, state: EditorState) -> None:
        self._state = state
        self.mode: str = "Lit"
        self.grid: bool = True
        self.gizmo: bool = True
        self.bounds: bool = False
        self.lights: bool = True
        self.persp: bool = True
        self._renderer: Any = None
        self._render_scene: Any = None
        self._render_size: tuple[int, int] = (0, 0)
        self._render_err: str | None = None
        self._frame_np: Any = None
        self._last_render_t: float = 0.0
        self._render_period_s: float = 1.0 / 30.0
        self._camera = FlyCameraController()
        # Subscribe to "frame selection" broadcasts from Hierarchy.
        self._attach_frame_selection()

    def _attach_frame_selection(self) -> None:
        try:
            from pharos_engine.telemetry import subscribe

            def _on_frame(evt: Any) -> None:
                self._center_on_selection()

            subscribe("editor.v2.frame_selection", _on_frame)
        except Exception:
            pass

    def _center_on_selection(self) -> None:
        ents = self._state.selected_entities()
        if not ents:
            return
        # Average position across selection (2D -> lifted to Y=0 plane).
        xs = [float(getattr(e, "position", (0.0, 0.0))[0]) for e in ents]
        ys = [float(getattr(e, "position", (0.0, 0.0))[1]) for e in ents]
        cx = sum(xs) / len(xs)
        cz = sum(ys) / len(ys)  # entity.y -> world z (top-down)
        self._camera.target = [cx, 0.0, cz]

    def _ensure_renderer(self, w: int, h: int) -> bool:
        if self._render_err is not None:
            return False
        if self._renderer is None or self._render_size != (w, h):
            try:
                from pharos_engine._core import render as _r

                self._renderer = _r.Renderer(w, h, "wgpu")
                self._render_scene = _r.RenderScene()
                self._render_scene.set_clear_colour((0.09, 0.09, 0.11, 1.0))
                self._render_size = (w, h)
            except Exception as exc:
                self._render_err = str(exc)
                return False
        return True

    def _push_camera(self) -> None:
        if self._renderer is None:
            return
        try:
            px, py, pz = self._camera.position()
            tx, ty, tz = self._camera.target
            # PyRenderer wraps set_clear_colour but doesn't expose
            # camera setters yet — those come with a Sprint 4 render
            # scene surface. For now the clear + throttle path is the
            # observable signal that the camera state changed.
            # When Renderer.set_camera lands, this call site pushes
            # (px, py, pz) + (tx, ty, tz) straight through.
            self._renderer.set_clear_colour(0.09, 0.09, 0.11, 1.0)
            _ = (px, py, pz, tx, ty, tz)
        except Exception:
            pass

    def _blit_rust_frame(self, w: int, h: int) -> bool:
        if not self._ensure_renderer(w, h):
            return False
        try:
            now = time.perf_counter()
            if (now - self._last_render_t) >= self._render_period_s or self._frame_np is None:
                self._push_camera()
                pixels = self._renderer.render_to_rgba(self._render_scene)
                self._last_render_t = now
                import numpy as np

                arr = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)
                self._frame_np = np.ascontiguousarray(arr[:, :, :3])
        except Exception as exc:
            self._render_err = str(exc)
            return False

        try:
            from imgui_bundle import immvision

            immvision.image_display(
                "##viewport_rust_frame",
                self._frame_np,
                image_display_size=(w, h),
                refresh_image=True,
            )
            return True
        except Exception as exc:
            self._render_err = str(exc)
            return False

    def gui(self) -> None:
        # Toolbar
        clicked, self.grid = imgui.checkbox("Grid", self.grid)
        imgui.same_line()
        clicked, self.gizmo = imgui.checkbox("Gizmo", self.gizmo)
        imgui.same_line()
        clicked, self.bounds = imgui.checkbox("Bounds", self.bounds)
        imgui.same_line()
        clicked, self.lights = imgui.checkbox("Lights", self.lights)
        imgui.same_line()
        clicked, self.persp = imgui.checkbox("Persp", self.persp)
        imgui.same_line()
        if imgui.button("Reset View"):
            self._camera.reset()

        imgui.separator()

        avail = imgui.get_content_region_avail()
        w = max(64, int(avail.x))
        h = max(64, int(avail.y))

        # Sample camera input BEFORE the paint so this frame sees the
        # updated position.
        viewport_hovered = imgui.is_window_hovered()
        self._camera.tick(viewport_hovered)

        if self._blit_rust_frame(w, h):
            if self.gizmo:
                self._draw_gizmo_overlay(w, h)
            # Overlay HUD text: hovered / camera pos.
            self._draw_hud(w, h)
            return

        # ── Fallback path ──────────────────────────────────────────────
        dl = imgui.get_window_draw_list()
        ox, oy = imgui.get_cursor_screen_pos()
        bg = imgui.get_color_u32(imgui.ImVec4(0.09, 0.09, 0.11, 1.0))
        dl.add_rect_filled(imgui.ImVec2(ox, oy), imgui.ImVec2(ox + avail.x, oy + avail.y), bg)
        warn_col = imgui.get_color_u32(imgui.ImVec4(0.95, 0.35, 0.30, 1.0))
        dl.add_text(imgui.ImVec2(ox + 12, oy + 12), warn_col,
                    f"[wgpu unavailable: {self._render_err or 'unknown'}]")
        imgui.dummy(avail)

    def _draw_gizmo_overlay(self, w: int, h: int) -> None:
        dl = imgui.get_window_draw_list()
        ox, oy = imgui.get_cursor_screen_pos()
        cx = ox + w * 0.5
        cy = oy - h * 0.5
        axis_x = imgui.get_color_u32(imgui.ImVec4(0.90, 0.30, 0.30, 1.0))
        axis_z = imgui.get_color_u32(imgui.ImVec4(0.30, 0.50, 0.90, 1.0))
        dl.add_line(imgui.ImVec2(cx - 30, cy), imgui.ImVec2(cx + 30, cy), axis_x, 2.0)
        dl.add_line(imgui.ImVec2(cx, cy - 30), imgui.ImVec2(cx, cy + 30), axis_z, 2.0)

    def _draw_hud(self, w: int, h: int) -> None:
        dl = imgui.get_window_draw_list()
        ox, oy = imgui.get_cursor_screen_pos()
        col = imgui.get_color_u32(imgui.ImVec4(0.85, 0.85, 0.90, 0.85))
        px, py, pz = self._camera.position()
        line1 = f"cam ({px:+.2f}, {py:+.2f}, {pz:+.2f})   r={self._camera.radius:.2f}"
        line2 = "RMB drag: orbit   MMB drag: pan   scroll: dolly   RMB+WASD/QE: fly"
        dl.add_text(imgui.ImVec2(ox + 12, oy - h + 12), col, line1)
        dl.add_text(imgui.ImVec2(ox + 12, oy - h + 28), col, line2)
