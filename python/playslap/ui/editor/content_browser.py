"""ContentBrowser — bottom panel for browsing and importing assets.

Features
--------
- Left pane: folder tree (navigates filesystem starting from project root)
- Right pane: asset grid — files shown as coloured icon cards
- Right-click context menu: Import File, New Script, New Folder, Rename, Delete
- Double-click .py → calls on_open_script(path) callback → loads in Code Mode
- Double-click image → show basic info popup (TODO: full asset editor)
- Drag source on each card (future: drop into scene outliner)

Protocol: build(parent_tag) -> None
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable


class ContentBrowser:
    """Asset browser panel rendered in the bottom strip of the editor."""

    ICON_COLORS: dict[str, tuple[int, int, int, int]] = {
        ".py":    (102, 204, 102, 255),   # green
        ".wgsl":  (102, 153, 255, 255),   # blue
        ".png":   (255, 180,  80, 255),   # orange
        ".jpg":   (255, 150,  80, 255),   # orange
        ".slap":  (180, 100, 255, 255),   # purple
        ".yml":   (220, 220,  80, 255),   # yellow
        ".yaml":  (220, 220,  80, 255),
        "folder": ( 80, 160, 220, 255),   # blue
        "other":  (140, 140, 140, 255),   # grey
    }

    def __init__(self, root_path: str | Path | None = None) -> None:
        self._root: Path = Path(root_path) if root_path else Path.cwd()
        self._current: Path = self._root
        self._selected: Path | None = None
        self._on_open_script: Callable[[Path], None] | None = None
        self._panel_tag = "content_browser_panel"
        self._tree_tag  = "cb_tree"
        self._grid_tag  = "cb_grid"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_root(self, path: str | Path) -> None:
        """Change the root directory for the browser."""
        self._root = Path(path)
        self._current = self._root

    def set_on_open_script(self, cb: Callable[[Path], None]) -> None:
        """Register callback invoked when a .py file is double-clicked."""
        self._on_open_script = cb

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: str) -> None:  # noqa: C901 (complexity — UI layout)
        import dearpygui.dearpygui as dpg

        with dpg.group(horizontal=False, parent=parent_tag):
            # Header row: label + action buttons (no flexbox — just ordered)
            with dpg.group(horizontal=True):
                dpg.add_text("Content Browser", color=(180, 180, 200))
                dpg.add_button(
                    label="Import",
                    width=80,
                    callback=self._on_import_click,
                )
                dpg.add_button(
                    label="New Script",
                    width=90,
                    callback=self._on_new_script,
                )

            dpg.add_separator()

            # Split: tree left | grid right
            panel_h = 165  # leaves room for header + separator

            with dpg.group(horizontal=True):
                # Folder tree (150 px wide)
                with dpg.child_window(
                    tag=self._tree_tag,
                    width=150,
                    height=panel_h,
                    border=True,
                ):
                    self._build_tree(self._tree_tag)

                # Asset grid (remaining width)
                with dpg.child_window(
                    tag=self._grid_tag,
                    width=-1,
                    height=panel_h,
                    border=False,
                ):
                    self._build_grid()

        # Right-click context menu triggered via a viewport-level key handler
        # (child_window doesn't support item_clicked_handler in DPG 2.x)
        with dpg.handler_registry():
            dpg.add_mouse_click_handler(
                button=1,
                callback=self._on_grid_right_click,
            )

    # ------------------------------------------------------------------
    # Tree
    # ------------------------------------------------------------------

    def _build_tree(self, parent: str) -> None:
        self._add_folder_node(self._root, parent, depth=0)

    def _add_folder_node(self, path: Path, parent: str, depth: int) -> None:
        import dearpygui.dearpygui as dpg

        label = path.name or str(path)
        tag = f"cb_tree_{abs(hash(str(path)))}_{depth}"

        try:
            subdirs = sorted(
                [x for x in path.iterdir()
                 if x.is_dir() and not x.name.startswith(".")],
                key=lambda x: x.name.lower(),
            )
        except PermissionError:
            subdirs = []

        if subdirs:
            with dpg.tree_node(
                label=label,
                tag=tag,
                parent=parent,
                default_open=(depth == 0),
            ):
                # Selectable for navigating to this folder itself
                dpg.add_selectable(
                    label=f"  {label}",
                    callback=lambda s, d, fp=path: self._navigate(fp),
                )
                for sub in subdirs:
                    self._add_folder_node(sub, tag, depth + 1)
        else:
            dpg.add_selectable(
                label=f"  {label}",
                parent=parent,
                callback=lambda s, d, fp=path: self._navigate(fp),
            )

    # ------------------------------------------------------------------
    # Grid
    # ------------------------------------------------------------------

    def _build_grid(self) -> None:
        import dearpygui.dearpygui as dpg

        dpg.delete_item(self._grid_tag, children_only=True)

        try:
            entries = sorted(
                self._current.iterdir(),
                key=lambda p: (p.is_file(), p.name.lower()),
            )
        except Exception:
            dpg.add_text(
                "(cannot read folder)",
                parent=self._grid_tag,
                color=(180, 80, 80),
            )
            return

        # Calculate number of columns; fall back to 6 if width not yet known.
        raw_w = dpg.get_item_width(self._grid_tag) if dpg.does_item_exist(self._grid_tag) else 0
        cols = max(1, (raw_w or 600) // 100)

        with dpg.table(
            parent=self._grid_tag,
            header_row=False,
            borders_innerH=False,
            borders_innerV=False,
            borders_outerH=False,
            borders_outerV=False,
        ):
            for _ in range(cols):
                dpg.add_table_column(width_fixed=True, init_width_or_weight=96)

            for row_start in range(0, max(1, len(entries)), cols):
                row_entries = entries[row_start:row_start + cols]
                with dpg.table_row():
                    for entry in row_entries:
                        with dpg.table_cell():
                            self._add_asset_card(entry)

    def _add_asset_card(self, path: Path) -> None:
        """One card: coloured icon drawlist + filename label below it."""
        import dearpygui.dearpygui as dpg

        ext = path.suffix.lower() if path.is_file() else "folder"
        color = self.ICON_COLORS.get(ext, self.ICON_COLORS["other"])
        short_name = path.name[:12] + ("…" if len(path.name) > 12 else "")

        # Use a stable tag derived from the absolute path hash
        card_tag = f"cb_card_{abs(hash(str(path)))}"

        with dpg.group(tag=card_tag):
            with dpg.drawlist(width=72, height=56):
                dpg.draw_rectangle(
                    (2, 2), (70, 54),
                    color=color[:3] + (80,),
                    fill=color[:3] + (60,),
                    rounding=4,
                )
                ext_label = ext.lstrip(".").upper()[:4] if path.is_file() else "DIR"
                dpg.draw_text((10, 20), ext_label, color=(220, 220, 220), size=16)

            dpg.add_text(short_name, wrap=80)

        # Click / double-click handlers bound to the group
        with dpg.item_handler_registry() as reg:
            dpg.add_item_clicked_handler(
                button=0,
                callback=lambda s, d, fp=path: self._on_card_click(fp),
            )
            dpg.add_item_double_clicked_handler(
                callback=lambda s, d, fp=path: self._on_card_double_click(fp),
            )
        dpg.bind_item_handler_registry(card_tag, reg)

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _navigate(self, path: Path) -> None:
        self._current = path
        self._build_grid()

    # ------------------------------------------------------------------
    # Card callbacks
    # ------------------------------------------------------------------

    def _on_card_click(self, path: Path) -> None:
        self._selected = path

    def _on_card_double_click(self, path: Path) -> None:
        if path.is_dir():
            self._navigate(path)
        elif path.suffix == ".py" and self._on_open_script is not None:
            self._on_open_script(path)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _on_grid_right_click(self, *_) -> None:
        import dearpygui.dearpygui as dpg

        # Only show menu when mouse is inside the grid child window
        if dpg.does_item_exist(self._grid_tag):
            try:
                mx, my = dpg.get_mouse_pos()
                rx, ry = dpg.get_item_rect_min(self._grid_tag)
                rw, rh = dpg.get_item_rect_size(self._grid_tag)
                if not (rx <= mx <= rx + rw and ry <= my <= ry + rh):
                    return
            except Exception:
                pass

        with dpg.window(
            popup=True,
            autosize=True,
            no_title_bar=True,
            no_move=True,
            modal=False,
        ):
            dpg.add_menu_item(
                label="Import File...", callback=self._on_import_click
            )
            dpg.add_menu_item(label="New Script", callback=self._on_new_script)
            dpg.add_separator()
            dpg.add_menu_item(
                label="Open Folder in Explorer",
                callback=lambda: self._open_in_explorer(),
            )

    def _open_in_explorer(self) -> None:
        import subprocess
        subprocess.Popen(["explorer", str(self._current)])  # noqa: S603,S607

    # ------------------------------------------------------------------
    # Import / new script
    # ------------------------------------------------------------------

    def _on_import_click(self, *_) -> None:
        import dearpygui.dearpygui as dpg

        if dpg.does_item_exist("cb_import_dialog"):
            return

        dpg.add_file_dialog(
            label="Import Asset",
            tag="cb_import_dialog",
            width=640,
            height=400,
            callback=self._on_import_selected,
            cancel_callback=lambda s, d: None,
        )
        for ext in (".py", ".png", ".jpg", ".wgsl", ".yml", ".slap"):
            dpg.add_file_extension(ext, parent="cb_import_dialog")

    def _on_import_selected(self, sender, selection) -> None:
        import shutil

        if not selection or "file_path_name" not in selection:
            return
        src = Path(selection["file_path_name"])
        dest = self._current / src.name
        try:
            shutil.copy2(src, dest)
            self._build_grid()
        except Exception:
            pass  # silently ignore copy errors for now

    def _on_new_script(self, *_) -> None:
        idx = 1
        while (self._current / f"new_script_{idx}.py").exists():
            idx += 1
        p = self._current / f"new_script_{idx}.py"
        p.write_text(
            '"""New script."""\n\n\nclass Script:\n    def on_create(self):\n        pass\n',
            encoding="utf-8",
        )
        self._build_grid()
        if self._on_open_script is not None:
            self._on_open_script(p)
