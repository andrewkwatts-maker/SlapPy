"""ContentBrowser — bottom panel for browsing and importing assets.

Features
--------
- Left pane: folder tree (navigates filesystem starting from project root)
- Right pane: asset grid — files shown as coloured icon cards
- Right-click context menu: Import File, New Script, New Folder, Rename, Delete
- Double-click .py → calls on_open_script(path) callback → loads in Code Mode
- Double-click image → show basic info popup (TODO: full asset editor)
- Drag source on each card (future: drop into scene outliner)

Polish (BBB7, 2026-07-19)
- Wider tree column (200 px) + text truncation with hover tooltip on long
  folder names so ``temp_20260719_140xxx`` no longer clips off-panel.
- Empty-state message with paper-note graphic when the current folder is
  empty ("Drop assets here to begin").
- Alternating row shading in the asset grid for readability.

Protocol: build(parent_tag) -> None
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable


# Maximum characters shown in the tree label before we ellipsise and attach
# a tooltip with the full name. Tuned for the widened 200-px tree column.
_TREE_LABEL_MAX_CHARS: int = 22

# Alternating grid-row background tint (very subtle paper-shade variance).
_GRID_ROW_TINT_A: tuple[int, int, int, int] = (250, 246, 235, 0)   # transparent
_GRID_ROW_TINT_B: tuple[int, int, int, int] = (232, 226, 210, 40)  # +tint

# Empty-state copy shown when the current folder has no entries.
_EMPTY_STATE_STICKER: str = "[note]"
_EMPTY_STATE_HINT: str = "Drop assets here to begin"


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

    # Tree column width — widened from 150 to 200 so long timestamped
    # folder names (``temp_20260719_140xxx``) fit with ellipsis + tooltip.
    TREE_WIDTH: int = 200

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
                # Folder tree — 220 px wide so timestamped scratch dir
                # names ("temp_20260719_140...") don't clip at the
                # child-window border.  See BBB1.
                with dpg.child_window(
                    tag=self._tree_tag,
                    width=220,
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

    @staticmethod
    def _truncate_label(name: str, max_chars: int = _TREE_LABEL_MAX_CHARS) -> str:
        """Return *name* truncated with an ellipsis when longer than *max_chars*.

        The tree column is fixed-width; without truncation, long folder
        names such as ``temp_20260719_140xxx`` clip off-panel and become
        unreadable.  Callers pair this with :meth:`_attach_full_name_tooltip`
        so the full name is still discoverable on hover.
        """
        if len(name) <= max_chars:
            return name
        # Reserve one glyph for the ellipsis to avoid off-by-one clipping.
        return name[: max_chars - 1] + "…"

    def _attach_full_name_tooltip(self, item_tag: str, full_name: str) -> None:
        """Attach a hover tooltip showing *full_name* to *item_tag*.

        Best-effort: if DPG is stubbed or ``add_tooltip`` is unavailable
        we silently skip — the truncated label alone remains readable.
        """
        try:
            import dearpygui.dearpygui as dpg
            with dpg.tooltip(parent=item_tag):
                dpg.add_text(full_name)
        except Exception:
            pass

    def _add_folder_node(self, path: Path, parent: str, depth: int) -> None:
        import dearpygui.dearpygui as dpg

        full_label = path.name or str(path)
        label = self._truncate_label(full_label)
        needs_tooltip = label != full_label
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
                if needs_tooltip:
                    self._attach_full_name_tooltip(tag, full_label)
                # Selectable for navigating to this folder itself
                sel_tag = f"{tag}_sel"
                dpg.add_selectable(
                    label=f"  {label}",
                    tag=sel_tag,
                    callback=lambda s, d, fp=path: self._navigate(fp),
                )
                if needs_tooltip:
                    self._attach_full_name_tooltip(sel_tag, full_label)
                for sub in subdirs:
                    self._add_folder_node(sub, tag, depth + 1)
        else:
            sel_tag = f"{tag}_leaf_sel"
            dpg.add_selectable(
                label=f"  {label}",
                parent=parent,
                tag=sel_tag,
                callback=lambda s, d, fp=path: self._navigate(fp),
            )
            if needs_tooltip:
                self._attach_full_name_tooltip(sel_tag, full_label)

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

        # Empty folder — render a paper-note style hint instead of an empty
        # table.  Keeps the panel from looking broken on a fresh project.
        if not entries:
            self._render_empty_state(dpg)
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
            # Alternating row backgrounds for readability — DPG toggles
            # between ImGuiCol_TableRowBg and ImGuiCol_TableRowBgAlt.
            row_background=True,
        ):
            for _ in range(cols):
                dpg.add_table_column(width_fixed=True, init_width_or_weight=96)

            for row_idx, row_start in enumerate(
                range(0, max(1, len(entries)), cols)
            ):
                row_entries = entries[row_start:row_start + cols]
                with dpg.table_row():
                    for entry in row_entries:
                        with dpg.table_cell():
                            # Row parity is encoded in the card group's
                            # background tint so alternating stripes are
                            # visible even with DPG's row-bg disabled.
                            self._add_asset_card(entry, row_idx=row_idx)

    def _render_empty_state(self, dpg) -> None:
        """Render the paper-note "Drop assets here to begin" hint."""
        empty_tag = f"{self._grid_tag}_empty"
        try:
            with dpg.group(parent=self._grid_tag, tag=empty_tag):
                # Ink-colored notebook copy — matches the field-journal
                # theme used by NotebookInspector's empty state.
                dpg.add_text(_EMPTY_STATE_STICKER, color=(120, 80, 40, 255))
                dpg.add_text(
                    _EMPTY_STATE_HINT, color=(40, 40, 60, 255), wrap=280,
                )
                # Simple paper-note graphic — 96x64 washi-taped square.
                try:
                    with dpg.drawlist(width=96, height=64):
                        dpg.draw_rectangle(
                            (4, 4), (92, 60),
                            color=(200, 190, 160, 200),
                            fill=(248, 244, 230, 220),
                            rounding=4,
                        )
                        # Washi-tape strip across the top.
                        dpg.draw_rectangle(
                            (18, 0), (78, 8),
                            color=(220, 170, 140, 200),
                            fill=(230, 180, 150, 180),
                        )
                except Exception:
                    pass
        except Exception:
            # Stub-DPG flat path — at least emit the copy so tests
            # can assert the empty-state message appears.
            try:
                dpg.add_text(
                    f"{_EMPTY_STATE_STICKER} {_EMPTY_STATE_HINT}",
                    parent=self._grid_tag,
                    tag=empty_tag,
                )
            except Exception:
                pass

    def _add_asset_card(self, path: Path, *, row_idx: int = 0) -> None:
        """One card: coloured icon drawlist + filename label below it.

        Parameters
        ----------
        path:
            Filesystem entry the card represents.
        row_idx:
            Grid-row index used to alternate the card background tint —
            even rows get :data:`_GRID_ROW_TINT_A`, odd rows get
            :data:`_GRID_ROW_TINT_B`.  Subtle enough to remain paper-shade
            without competing with the icon colour.
        """
        import dearpygui.dearpygui as dpg

        ext = path.suffix.lower() if path.is_file() else "folder"
        color = self.ICON_COLORS.get(ext, self.ICON_COLORS["other"])
        full_name = path.name
        short_name = full_name[:12] + ("…" if len(full_name) > 12 else "")
        needs_tooltip = short_name != full_name

        # Use a stable tag derived from the absolute path hash
        card_tag = f"cb_card_{abs(hash(str(path)))}"
        row_tint = _GRID_ROW_TINT_B if (row_idx % 2) else _GRID_ROW_TINT_A

        with dpg.group(tag=card_tag):
            with dpg.drawlist(width=88, height=64):
                # Row-alternating background tint (very subtle — paper
                # shade variance rather than banded stripes).
                if row_tint[3] > 0:
                    dpg.draw_rectangle(
                        (0, 0), (88, 64),
                        color=row_tint,
                        fill=row_tint,
                    )
                dpg.draw_rectangle(
                    (2, 2), (70, 54),
                    color=color[:3] + (80,),
                    fill=color[:3] + (60,),
                    rounding=4,
                )
                ext_label = ext.lstrip(".").upper()[:4] if path.is_file() else "DIR"
                dpg.draw_text((10, 20), ext_label, color=(220, 220, 220), size=16)

            dpg.add_text(short_name, wrap=80)
            if needs_tooltip:
                self._attach_full_name_tooltip(card_tag, full_name)

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
