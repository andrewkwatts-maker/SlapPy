"""editor_v2 panel bodies — real implementations bridged to the engine.

Each panel is a small class that owns its state (selection, filter,
scroll position) and exposes a ``gui()`` method Hello ImGui calls
every frame. The classes are constructed once at shell boot and their
``gui`` method is registered as the ``DockableWindow.gui_function``.

Design principles:
- No hidden mutation. Panels hold *references* to shared editor state
  (Engine, Scene, MultiSelectModel, CommandStack, telemetry
  subscription handle) — they never own the singletons.
- Every render is stateless w.r.t. imgui: no push/pop pairs left
  dangling across frames.
- Graceful degradation: when the engine / scene / model isn't
  attached, the panel renders an empty-state hint instead of raising.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from imgui_bundle import imgui


# ---------------------------------------------------------------------------
# Hierarchy — scene entity tree with selection + right-click actions
# ---------------------------------------------------------------------------

class HierarchyPanel:
    """Scene outliner. Displays every entity in the active scene."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._selected: str | None = None       # entity id
        self._filter: str = ""

    def _get_entities(self) -> list[Any]:
        try:
            scene = getattr(self._engine, "scene", None)
            if scene is None:
                return []
            return list(scene.entities)
        except Exception:
            return []

    def selected_entity(self) -> Any | None:
        for e in self._get_entities():
            if getattr(e, "id", None) == self._selected:
                return e
        return None

    def gui(self) -> None:
        entities = self._get_entities()

        # Filter box.
        changed, self._filter = imgui.input_text_with_hint(
            "##hier_filter", "Search entities…", self._filter
        )

        imgui.same_line()
        if imgui.button("+ Add"):
            # Spawn a plain Entity as a smoke test until a proper spawn
            # menu lands in a later sprint.
            self._spawn_default_entity()

        imgui.separator()

        if not entities:
            imgui.text_disabled("Scene is empty. Use + Add to create an entity.")
            return

        needle = self._filter.strip().lower()
        for e in entities:
            name = getattr(e, "name", "") or "<unnamed>"
            eid = getattr(e, "id", "?")
            if needle and needle not in name.lower():
                continue

            flags = imgui.TreeNodeFlags_.leaf | imgui.TreeNodeFlags_.no_tree_push_on_open
            if eid == self._selected:
                flags |= imgui.TreeNodeFlags_.selected

            imgui.tree_node_ex(f"{name}##{eid}", flags)
            if imgui.is_item_clicked():
                self._selected = eid

    def _spawn_default_entity(self) -> None:
        try:
            scene = getattr(self._engine, "scene", None)
            if scene is None:
                return
            from pharos_engine.entity import Entity  # local import — engine dep

            n = scene.entity_count() if hasattr(scene, "entity_count") else 0
            e = Entity(name=f"Entity_{n + 1}", position=(0.0, 0.0))
            scene.add_entity(e)
            self._selected = e.id
        except Exception:
            # Best-effort — no toast infrastructure in v2 yet.
            pass


# ---------------------------------------------------------------------------
# Properties — inspector for the currently-selected entity
# ---------------------------------------------------------------------------

class PropertiesPanel:
    """Reads the active hierarchy selection; renders transform + tags."""

    def __init__(self, hierarchy: HierarchyPanel) -> None:
        self._hierarchy = hierarchy

    def gui(self) -> None:
        entity = self._hierarchy.selected_entity()
        if entity is None:
            imgui.text_disabled("No object selected.")
            imgui.text_disabled("Pick an entity in the Hierarchy panel to inspect it.")
            return

        # Header
        name = getattr(entity, "name", "<unnamed>") or "<unnamed>"
        imgui.text_colored(imgui.ImVec4(0.31, 0.81, 0.69, 1.0), name)
        imgui.same_line()
        imgui.text_disabled(f"id={getattr(entity, 'id', '?')[:8]}")

        imgui.separator()

        # Transform
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

        # Tags
        if imgui.collapsing_header("Tags"):
            tags = getattr(entity, "tags", set())
            if not tags:
                imgui.text_disabled("(no tags)")
            else:
                for t in sorted(tags):
                    imgui.bullet_text(str(t))

        # Components
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
    """Subscribes to `pharos_engine.telemetry`; renders a ring-buffered log."""

    LEVELS = ("dbg", "info", "warn", "err")
    LEVEL_COLOURS = {
        "dbg":  imgui.ImVec4(0.60, 0.60, 0.65, 1.0),
        "info": imgui.ImVec4(0.31, 0.81, 0.69, 1.0),
        "warn": imgui.ImVec4(0.95, 0.75, 0.20, 1.0),
        "err":  imgui.ImVec4(0.95, 0.35, 0.30, 1.0),
    }

    def __init__(self, capacity: int = 2000) -> None:
        self._capacity = capacity
        self._entries: list[tuple[float, str, str, str]] = []  # (t, level, topic, msg)
        self._enabled_levels: set[str] = set(self.LEVELS)
        self._follow_tail: bool = True
        self._filter: str = ""
        self._sub_handle: Any = None
        self._attach()

    def _attach(self) -> None:
        try:
            from pharos_engine.telemetry import subscribe

            def _handler(evt: Any) -> None:
                # TelemetryEvent has .name (topic) + .payload (dict).
                name = getattr(evt, "name", "?")
                payload = getattr(evt, "payload", {}) or {}
                # Infer severity from payload["level"] if present, else "info".
                level = str(payload.get("level", "info")).lower()
                if level not in self.LEVELS:
                    level = "info"
                # Message: prefer payload["message"], else stringify payload.
                if "message" in payload:
                    msg = str(payload["message"])
                elif payload:
                    msg = ", ".join(f"{k}={v!r}" for k, v in payload.items())
                else:
                    msg = ""
                self._append(level, name, msg)

            self._sub_handle = subscribe("*", _handler)
            # Seed with a boot message so the panel isn't empty on first paint.
            self._append("info", "editor.v2.boot", "console attached to telemetry bus")
        except Exception:
            self._append("warn", "editor.v2.boot", "telemetry unavailable; console will only show local logs")

    def _append(self, level: str, topic: str, msg: str) -> None:
        self._entries.append((time.time(), level, topic, msg))
        if len(self._entries) > self._capacity:
            del self._entries[: len(self._entries) - self._capacity]

    def gui(self) -> None:
        # Toolbar.
        if imgui.button("Clear"):
            self._entries.clear()
        imgui.same_line()
        _, self._follow_tail = imgui.checkbox("Follow", self._follow_tail)
        imgui.same_line()
        for lvl in self.LEVELS:
            on = lvl in self._enabled_levels
            changed, on = imgui.checkbox(lvl.upper(), on)
            if changed:
                if on:
                    self._enabled_levels.add(lvl)
                else:
                    self._enabled_levels.discard(lvl)
            imgui.same_line()
        imgui.set_next_item_width(-1)
        _, self._filter = imgui.input_text_with_hint("##console_filter", "Filter…", self._filter)

        imgui.separator()

        # Scrolling body.
        imgui.begin_child(
            "##console_body", imgui.ImVec2(0, 0),
            imgui.ChildFlags_.borders,
        )
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
# Content browser — folder tree + file grid, backed by BreadcrumbHistory
# ---------------------------------------------------------------------------

class ContentBrowserPanel:
    """Simple folder navigator. Uses BreadcrumbHistory from Sprint 9."""

    def __init__(self, root: Path | None = None) -> None:
        if root is None:
            # Prefer a Pharos project dir if one exists, else current cwd.
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
        self._current = self._root

    def gui(self) -> None:
        # Breadcrumb row
        cur = self._history.current() if self._history else self._current
        if imgui.button("<") and self._history:
            self._current = self._history.go_back()
        imgui.same_line()
        if imgui.button(">") and self._history:
            self._current = self._history.go_forward()
        imgui.same_line()
        if imgui.button("^") and self._history:
            self._current = self._history.go_up()
        imgui.same_line()
        if imgui.button("Home") and self._history:
            self._current = self._history.go_home()
        imgui.same_line()
        imgui.text_disabled(str(cur))

        imgui.separator()

        # Item grid — one entry per row for now (grid layout comes with
        # thumbnail rendering in a follow-up sprint).
        try:
            items = sorted(cur.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except Exception:
            imgui.text_disabled(f"(cannot read {cur})")
            return

        if not items:
            imgui.text_disabled("(folder is empty)")
            return

        for p in items:
            label = f"[DIR] {p.name}" if p.is_dir() else p.name
            if imgui.selectable(label, False)[0]:
                if p.is_dir() and self._history:
                    self._current = self._history.navigate(p)


# ---------------------------------------------------------------------------
# Viewport — placeholder grid + camera state (Sprint 3 wires wgpu blit)
# ---------------------------------------------------------------------------

class ViewportPanel:
    """3D viewport. Blits Rust-rendered wgpu frames into imgui.

    Architecture contract: Python-side owns the panel state + input,
    Rust (``pharos_engine._core.render.Renderer``) owns wgpu + the
    frame pixels. Python never touches wgpu directly — every viewport
    tick calls Rust for a fresh RGBA buffer and hands it to
    ``immvision.image_display`` which manages the GL texture upload.
    """

    def __init__(self) -> None:
        self.mode: str = "Lit"
        self.grid: bool = True
        self.gizmo: bool = True
        self.bounds: bool = False
        self.lights: bool = True
        self.persp: bool = True
        # Rust renderer + last-known texture size. Constructed lazily
        # on first gui() call so the wgpu init cost doesn't fire until
        # the panel is actually visible.
        self._renderer: Any = None
        self._render_scene: Any = None
        self._render_size: tuple[int, int] = (0, 0)
        self._render_err: str | None = None
        self._frame_np: Any = None
        # Frame throttle: cap render to 30 fps for the viewport panel
        # so idle UI doesn't burn GPU on unchanging scenes. UI reacts
        # to every input event regardless — this only affects the
        # per-frame wgpu blit rate.
        self._last_render_t: float = 0.0
        self._render_period_s: float = 1.0 / 30.0

    def _ensure_renderer(self, w: int, h: int) -> bool:
        """Lazy-construct + resize the Rust wgpu renderer.

        Returns True on success, False when the backend can't init
        (headless CI without an adapter, driver issue) — the panel
        then falls back to the imgui-drawlist placeholder.
        """
        if self._render_err is not None:
            return False
        if self._renderer is None or self._render_size != (w, h):
            try:
                from pharos_engine._core import render as _r

                self._renderer = _r.Renderer(w, h, "wgpu")
                self._render_scene = _r.RenderScene()
                # Match the theme's panel_bg-ish grey for the empty scene.
                self._render_scene.set_clear_colour((0.09, 0.09, 0.11, 1.0))
                self._render_size = (w, h)
            except Exception as exc:
                self._render_err = str(exc)
                return False
        return True

    def _blit_rust_frame(self, w: int, h: int) -> bool:
        """Ask Rust for pixels, upload via immvision. Returns True on paint."""
        if not self._ensure_renderer(w, h):
            return False
        try:
            import time

            now = time.perf_counter()
            if (now - self._last_render_t) >= self._render_period_s or self._frame_np is None:
                pixels = self._renderer.render_to_rgba(self._render_scene)
                self._last_render_t = now
                import numpy as np

                arr = np.frombuffer(pixels, dtype=np.uint8).reshape(h, w, 4)
                # immvision wants RGB or BGR; drop alpha for the display path.
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
        # Toolbar row
        _, self.mode = imgui.combo(
            "##vp_mode", 0 if self.mode == "Lit" else 1,
            ["Lit", "Wireframe", "Unlit"],
        )[0] and (True, self.mode) or (False, self.mode)  # noqa: keep placeholder
        # Simpler: individual checkboxes for now
        clicked, self.grid = imgui.checkbox("Grid", self.grid); _ = clicked
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
            pass

        imgui.separator()

        avail = imgui.get_content_region_avail()
        w = max(64, int(avail.x))
        h = max(64, int(avail.y))

        # Preferred path: Rust wgpu -> RGBA bytes -> immvision blit.
        if self._blit_rust_frame(w, h):
            # Draw the axis crosshair overlay on top when gizmo is on —
            # cheap enough to do in imgui rather than round-trip Rust.
            if self.gizmo:
                dl = imgui.get_window_draw_list()
                ox, oy = imgui.get_cursor_screen_pos()
                # imgui.image_display advances the cursor by (w, h) —
                # walk back to the centre of the just-painted image.
                cx = ox + w * 0.5
                cy = oy - h * 0.5
                axis_x = imgui.get_color_u32(imgui.ImVec4(0.90, 0.30, 0.30, 1.0))
                axis_z = imgui.get_color_u32(imgui.ImVec4(0.30, 0.50, 0.90, 1.0))
                dl.add_line(imgui.ImVec2(cx - 30, cy), imgui.ImVec2(cx + 30, cy), axis_x, 2.0)
                dl.add_line(imgui.ImVec2(cx, cy - 30), imgui.ImVec2(cx, cy + 30), axis_z, 2.0)
            return

        # Fallback path: pure-imgui placeholder when Rust backend can't
        # init (headless CI, unsupported driver). Small "NO RENDER"
        # banner so the failure mode is visible.
        dl = imgui.get_window_draw_list()
        ox, oy = imgui.get_cursor_screen_pos()
        bg = imgui.get_color_u32(imgui.ImVec4(0.09, 0.09, 0.11, 1.0))
        dl.add_rect_filled(
            imgui.ImVec2(ox, oy),
            imgui.ImVec2(ox + avail.x, oy + avail.y),
            bg,
        )
        if self.grid:
            step = 32.0
            grid_col = imgui.get_color_u32(imgui.ImVec4(0.20, 0.22, 0.28, 1.0))
            x = 0.0
            while x < avail.x:
                dl.add_line(imgui.ImVec2(ox + x, oy), imgui.ImVec2(ox + x, oy + avail.y), grid_col)
                x += step
            y = 0.0
            while y < avail.y:
                dl.add_line(imgui.ImVec2(ox, oy + y), imgui.ImVec2(ox + avail.x, oy + y), grid_col)
                y += step
        # Warning banner.
        warn_col = imgui.get_color_u32(imgui.ImVec4(0.95, 0.35, 0.30, 1.0))
        dl.add_text(
            imgui.ImVec2(ox + 12, oy + 12),
            warn_col,
            f"[wgpu unavailable: {self._render_err or 'unknown'}]",
        )
        imgui.dummy(avail)
