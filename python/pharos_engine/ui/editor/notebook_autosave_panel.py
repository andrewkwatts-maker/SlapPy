"""``NotebookAutosavePanel`` — diary-themed snapshot list + restore controls.

Visual counterpart to the Y6 :class:`~pharos_engine.autosave.AutosaveManager`
+ Z6 :class:`~pharos_engine.ui.editor.editor_autosave.EditorAutosaveIntegration`
pipeline. Where those modules own the on-disk ring buffer, this panel
surfaces it to the user: a scrolling list of ``.snap.yaml`` snapshots
with per-row **Restore** / **Delete** / **Preview** buttons plus a
header that shows the current project name and the "Autosaved 12 s ago"
status hint.

Design provenance: sprint BB3 (visual counterpart to Y6/Z6 autosave).

Wiring
------
The panel is *observer-only*: it never mutates the manager's ring
buffer directly. Restore + Delete clicks fan out through subscriber
callbacks registered via :meth:`set_on_restore` and :meth:`set_on_delete`
so the editor shell can decide policy (should a restore replace the
current session? should a delete confirm?). The panel does the file I/O
for the Preview modal itself — it's read-only and needs no callback.

Empty state
-----------
When the ring buffer is empty the body shows:

    No snapshots yet — an autosave will fire in a few seconds…

with a small sparkle marquee (three characters cycled at each
``refresh`` so a headless test can observe the animation frame).

Diary theming
-------------
* Ruled-paper background under the snapshot list (mirrors the message
  log's ``child_window`` + separator rows pattern).
* Hand-drawn dividers between rows every entry.
* Level chips are unused here — snapshot rows are homogeneous.

Every :mod:`dearpygui` call is funnelled through ``_safe_dpg`` so the
panel is exercisable in headless CI without a real GUI context.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from pharos_engine._validation import validate_callable


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _is_real_dpg(dpg: Any) -> bool:
    """Return ``True`` when *dpg* is the real ``dearpygui.dearpygui`` module."""
    import types
    inner = getattr(dpg, "internal_dpg", None)
    if not isinstance(inner, types.ModuleType):
        return False
    return getattr(inner, "__name__", "").startswith("dearpygui")


def _headless_env_active() -> bool:
    """Return ``True`` when ``SLAPPY_HEADLESS`` is set to a truthy value."""
    val = os.environ.get("SLAPPY_HEADLESS", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if importable + usable, else ``None``.

    Mirrors the guard used across every notebook panel: real DPG in a
    headless env would blow up before ``create_context`` so we degrade
    silently to "no widgets rendered".
    """
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception:
        return None
    if _is_real_dpg(dpg) and _headless_env_active():
        return None
    return dpg


def _format_timestamp(ts: float) -> str:
    """Format *ts* as ``YYYY-MM-DD HH:MM:SS`` local time."""
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except Exception:
        return "????-??-?? ??:??:??"


def _format_age_seconds(seconds: float | None) -> str:
    """Format a "N sec/min/hour ago" hint. ``None`` → ``"never"``."""
    if seconds is None:
        return "never"
    try:
        s = float(seconds)
    except (TypeError, ValueError):
        return "never"
    if s < 0.0:
        s = 0.0
    if s < 1.0:
        return "just now"
    if s < 60.0:
        n = int(s)
        return f"{n} sec ago"
    if s < 3600.0:
        n = int(s // 60.0)
        return f"{n} min ago"
    if s < 86400.0:
        n = int(s // 3600.0)
        return f"{n} hour{'s' if n != 1 else ''} ago"
    n = int(s // 86400.0)
    return f"{n} day{'s' if n != 1 else ''} ago"


def _snapshot_mtime(path: Path) -> float:
    """Return *path*'s mtime, falling back to 0.0 on any OSError."""
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


# Sparkle characters cycled by the empty-state marquee — each refresh
# advances the animation frame by one.
_SPARKLE_FRAMES: tuple[str, ...] = (". ", ".*", "*.", "..", "*.", ".*")


# ---------------------------------------------------------------------------
# Snapshot row
# ---------------------------------------------------------------------------


@dataclass
class SnapshotRow:
    """One rendered snapshot row.

    Attributes
    ----------
    path:
        Absolute path to the ``.snap.yaml`` file.
    mtime:
        POSIX timestamp of the file's mtime.
    filename:
        Bare filename (no directory) for compact display.
    """

    path: Path
    mtime: float
    filename: str

    def age_seconds(self, now: float | None = None) -> float:
        """Return seconds between *now* (or wall-clock) and :attr:`mtime`."""
        ref = float(now) if now is not None else time.time()
        return max(0.0, ref - float(self.mtime))


# ---------------------------------------------------------------------------
# The panel
# ---------------------------------------------------------------------------


class NotebookAutosavePanel:
    """Diary-themed panel listing every autosave snapshot for the project.

    The panel is *observer-only* against the
    :class:`~pharos_engine.autosave.AutosaveManager` ring buffer: it never
    prunes, restores, or force-saves on its own. Every mutating action
    fans out through subscriber callbacks registered via
    :meth:`set_on_restore` and :meth:`set_on_delete`; the panel itself
    only reads the manager for :meth:`~pharos_engine.autosave.AutosaveManager.list_snapshots`
    and pokes it via :meth:`~pharos_engine.autosave.AutosaveManager.force_save`
    when the user hits the header's Force-save-now button.

    Parameters
    ----------
    manager:
        Optional :class:`AutosaveManager`. May be ``None`` — the panel
        renders its empty state until :meth:`set_manager` swaps a real
        one in.
    integration:
        Optional
        :class:`~pharos_engine.ui.editor.editor_autosave.EditorAutosaveIntegration`.
        Used to source the "Autosaved 12 s ago" hint via
        :meth:`EditorAutosaveIntegration.last_saved_ago_seconds`. May be
        ``None``; the hint then reports ``"never"`` until the panel has
        an integration.
    project_name:
        Optional friendly name shown in the header. Falls back to the
        manager's underlying project when omitted.
    """

    TITLE = "Autosaves"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 480
    MIN_HEIGHT: int = 320

    # Cap how many rows we render at once so DPG doesn't choke on
    # multi-thousand-entry ring buffers. Manager caps at 20 by default
    # so the cap here is only a defensive guard.
    _MAX_RENDERED_ROWS: int = 200

    _ROOT_TAG = "notebook_autosave_panel_root"
    _HEADER_TAG = "notebook_autosave_panel_header"
    _STATUS_TAG = "notebook_autosave_panel_status"
    _PROJECT_TAG = "notebook_autosave_panel_project"
    _RULED_TAG = "notebook_autosave_panel_ruled"
    _LIST_TAG = "notebook_autosave_panel_list"
    _EMPTY_TAG = "notebook_autosave_panel_empty"

    def __init__(
        self,
        manager: Any = None,
        integration: Any = None,
        project_name: str | None = None,
    ) -> None:
        self._manager: Any = manager
        self._integration: Any = integration
        self._explicit_project_name: str | None = (
            project_name if isinstance(project_name, str) and project_name else None
        )

        self._rows: list[SnapshotRow] = []
        self._selected_index: int | None = None
        self._sparkle_frame: int = 0

        # Callback slots.
        self._on_restore: Callable[[Path], None] | None = None
        self._on_delete: Callable[[Path], None] | None = None

        # Preview modal state (populated by :meth:`preview`).
        self._preview_modal: dict[str, Any] | None = None

        # Context menu state (opened via :meth:`open_context_menu`).
        self._context_menu: dict[str, Any] | None = None

        # Build state.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Test-observability — every user-facing mutation is logged as a
        # ``(event, data)`` tuple so headless tests can assert intent
        # without walking DPG's item tree.
        self.call_log: list[tuple[str, Any]] = []

        # Populate the initial row cache from the manager, if any.
        try:
            self.refresh()
        except Exception:
            # A broken manager must never derail construction — the
            # panel still renders its empty state.
            pass

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def manager(self) -> Any:
        """The current :class:`AutosaveManager` (or ``None``)."""
        return self._manager

    @property
    def integration(self) -> Any:
        """The current :class:`EditorAutosaveIntegration` (or ``None``)."""
        return self._integration

    @property
    def rows(self) -> list[SnapshotRow]:
        """Return a shallow copy of the cached snapshot rows (newest first)."""
        return list(self._rows)

    @property
    def row_count(self) -> int:
        """Number of cached snapshot rows."""
        return len(self._rows)

    @property
    def selected_index(self) -> int | None:
        return self._selected_index

    @property
    def sparkle_frame(self) -> int:
        """Current sparkle animation frame index (empty-state marquee)."""
        return self._sparkle_frame

    @property
    def is_empty(self) -> bool:
        """``True`` iff there are no snapshot rows to render."""
        return not self._rows

    @property
    def preview_modal(self) -> dict[str, Any] | None:
        """The currently open preview modal state (``None`` when closed)."""
        return self._preview_modal

    @property
    def context_menu(self) -> dict[str, Any] | None:
        """The currently open right-click context menu state."""
        return self._context_menu

    def project_name(self) -> str:
        """Return the friendly project name shown in the header.

        Prefers the explicit override passed to ``__init__`` (or the
        setter), then the manager's project ``.name``, then a placeholder.
        """
        if self._explicit_project_name is not None:
            return self._explicit_project_name
        mgr = self._manager
        if mgr is not None:
            project = getattr(mgr, "_project", None)
            name = getattr(project, "name", None)
            if isinstance(name, str) and name:
                return name
        return "unnamed"

    def status_text(self) -> str:
        """Return the header status hint (``"Autosaved N sec ago"``)."""
        ago = self._last_saved_ago_seconds()
        if ago is None:
            return "Autosaved: never"
        return f"Autosaved {_format_age_seconds(ago)}"

    def sparkle_text(self) -> str:
        """Return the current sparkle frame string (empty-state marquee)."""
        idx = self._sparkle_frame % len(_SPARKLE_FRAMES)
        return _SPARKLE_FRAMES[idx]

    def empty_state_text(self) -> str:
        """Return the empty-state message + sparkle animation frame."""
        return (
            "No snapshots yet — an autosave will fire in a few seconds… "
            + self.sparkle_text()
        )

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def set_manager(self, manager: Any) -> None:
        """Swap the source :class:`AutosaveManager`. Re-fetches immediately."""
        self._manager = manager
        self.call_log.append(("set_manager", type(manager).__name__ if manager is not None else None))
        self.refresh()

    def set_integration(self, integration: Any) -> None:
        """Swap the source :class:`EditorAutosaveIntegration`."""
        self._integration = integration
        self.call_log.append(("set_integration", type(integration).__name__ if integration is not None else None))
        if self._built:
            self._update_status_widget()

    def set_project_name(self, project_name: str | None) -> None:
        """Override the header project label (``None`` clears the override)."""
        if project_name is not None and not isinstance(project_name, str):
            raise TypeError(
                "NotebookAutosavePanel.set_project_name: project_name must be "
                f"str or None; got {type(project_name).__name__}"
            )
        self._explicit_project_name = (
            project_name if isinstance(project_name, str) and project_name else None
        )
        self.call_log.append(("set_project_name", self._explicit_project_name))
        if self._built:
            self._update_project_widget()

    def set_on_restore(self, callback: Callable[[Path], None] | None) -> None:
        """Register (or clear with ``None``) the restore subscriber."""
        if callback is not None:
            validate_callable(
                "callback", "NotebookAutosavePanel.set_on_restore", callback,
            )
        self._on_restore = callback
        self.call_log.append(("set_on_restore", callback is not None))

    def set_on_delete(self, callback: Callable[[Path], None] | None) -> None:
        """Register (or clear with ``None``) the delete subscriber."""
        if callback is not None:
            validate_callable(
                "callback", "NotebookAutosavePanel.set_on_delete", callback,
            )
        self._on_delete = callback
        self.call_log.append(("set_on_delete", callback is not None))

    # ------------------------------------------------------------------
    # Row cache
    # ------------------------------------------------------------------

    def refresh(self) -> list[SnapshotRow]:
        """Re-fetch the snapshot list from the manager.

        Returns the newly-cached list (newest first). A missing manager
        yields an empty list and the panel renders its empty state.
        Any exception thrown by the manager is swallowed — this method
        is safe to call from the UI thread as often as needed.
        """
        rows: list[SnapshotRow] = []
        mgr = self._manager
        if mgr is not None:
            try:
                paths = mgr.list_snapshots()
            except Exception:
                paths = []
            for p in paths or []:
                try:
                    path = Path(p)
                except Exception:
                    continue
                rows.append(
                    SnapshotRow(
                        path=path,
                        mtime=_snapshot_mtime(path),
                        filename=path.name,
                    )
                )
            # Manager already returns newest-first but re-sort defensively
            # so mocked managers don't break the invariant.
            rows.sort(key=lambda r: r.mtime, reverse=True)
        self._rows = rows
        # Clamp any lingering selection.
        if self._selected_index is not None and (
            self._selected_index < 0 or self._selected_index >= len(rows)
        ):
            self._selected_index = None
        # Advance the empty-state sparkle so the marquee ticks on every
        # refresh even when nothing changes.
        self._sparkle_frame = (self._sparkle_frame + 1) % len(_SPARKLE_FRAMES)
        self.call_log.append(("refresh", len(rows)))
        if self._built:
            try:
                self._rebuild_list_widget()
            except Exception:
                pass
            try:
                self._update_status_widget()
            except Exception:
                pass
        return list(rows)

    def select(self, index: int | None) -> None:
        """Select the row at *index* (``None`` clears)."""
        if index is None:
            self._selected_index = None
        else:
            if not isinstance(index, int) or isinstance(index, bool):
                raise TypeError(
                    "NotebookAutosavePanel.select: index must be int or None"
                )
            if index < 0 or index >= len(self._rows):
                raise IndexError(
                    f"NotebookAutosavePanel.select: index {index} out of range "
                    f"[0, {len(self._rows)})"
                )
            self._selected_index = index
        self.call_log.append(("select", self._selected_index))
        if self._built:
            try:
                self._rebuild_list_widget()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Row actions
    # ------------------------------------------------------------------

    def _resolve_row(self, target: int | Path | str) -> SnapshotRow:
        """Return the :class:`SnapshotRow` for *target* (index or path)."""
        if isinstance(target, int) and not isinstance(target, bool):
            if target < 0 or target >= len(self._rows):
                raise IndexError(
                    f"NotebookAutosavePanel: row index {target} out of range "
                    f"[0, {len(self._rows)})"
                )
            return self._rows[target]
        if isinstance(target, (str, Path)):
            path = Path(target)
            for row in self._rows:
                if row.path == path:
                    return row
            raise KeyError(
                f"NotebookAutosavePanel: no cached row for path {path}"
            )
        raise TypeError(
            "NotebookAutosavePanel: target must be int index or path-like; "
            f"got {type(target).__name__}"
        )

    def restore(self, target: int | Path | str) -> Path:
        """Fire the restore callback for the snapshot at *target*.

        Returns the resolved snapshot path (also passed to the callback).
        Silently no-ops (returns the path) when no callback is registered
        so tests + code exercising the row layer can call this without
        wiring a full editor shell.
        """
        row = self._resolve_row(target)
        self.call_log.append(("restore", str(row.path)))
        cb = self._on_restore
        if cb is not None:
            try:
                cb(row.path)
            except Exception:
                # Subscriber errors must never crash the panel — the
                # shell owns error reporting.
                pass
        return row.path

    def delete(self, target: int | Path | str) -> Path:
        """Fire the delete callback for the snapshot at *target*.

        Returns the resolved snapshot path (also passed to the callback).
        The panel does not remove the file itself — the subscriber is
        expected to prune via the manager (or confirm with the user).
        The row cache is *not* mutated eagerly; call :meth:`refresh` to
        pick up the deletion afterwards.
        """
        row = self._resolve_row(target)
        self.call_log.append(("delete", str(row.path)))
        cb = self._on_delete
        if cb is not None:
            try:
                cb(row.path)
            except Exception:
                pass
        return row.path

    def preview(self, target: int | Path | str) -> str:
        """Open a modal showing the raw YAML of the snapshot at *target*.

        Returns the raw file text (for headless-test assertions). A read
        failure falls back to a stub message so the modal always renders
        *something* even when the file has been externally deleted.
        """
        row = self._resolve_row(target)
        try:
            text = row.path.read_text(encoding="utf-8")
        except OSError as exc:
            text = f"# (unable to read {row.path.name}: {exc})\n"
        modal_tag = f"notebook_autosave_preview_modal_{id(self)}"
        self._preview_modal = {
            "path": row.path,
            "filename": row.filename,
            "yaml": text,
            "modal_tag": modal_tag,
        }
        self.call_log.append(("preview", str(row.path)))
        dpg = _safe_dpg()
        if dpg is not None:
            try:
                if dpg.does_item_exist(modal_tag):
                    dpg.delete_item(modal_tag)
            except Exception:
                pass
            try:
                with dpg.window(
                    label=f"Preview: {row.filename}",
                    modal=True,
                    tag=modal_tag,
                    width=540,
                    height=440,
                ):
                    try:
                        dpg.add_text(text)
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="Close",
                            callback=lambda *_a, **_kw: self.close_preview(),
                        )
                    except Exception:
                        pass
            except Exception:
                pass
        return text

    def close_preview(self) -> bool:
        """Tear down any open preview modal. Returns ``True`` iff one was open."""
        if self._preview_modal is None:
            return False
        tag = self._preview_modal.get("modal_tag")
        dpg = _safe_dpg()
        if dpg is not None and isinstance(tag, str):
            try:
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            except Exception:
                pass
        self._preview_modal = None
        self.call_log.append(("close_preview", None))
        return True

    def copy_path(self, target: int | Path | str) -> str:
        """Copy the resolved snapshot path to the OS clipboard (best-effort).

        Returns the path string that was staged for the clipboard so
        tests can assert intent even when the DPG clipboard isn't
        available.
        """
        row = self._resolve_row(target)
        path_str = str(row.path)
        self.call_log.append(("copy_path", path_str))
        dpg = _safe_dpg()
        if dpg is not None:
            try:
                # ``set_clipboard_text`` needs a live viewport; guard it.
                dpg.set_clipboard_text(path_str)
            except Exception:
                pass
        return path_str

    # ------------------------------------------------------------------
    # Header actions
    # ------------------------------------------------------------------

    def force_save_now(self) -> Path | None:
        """Trigger an immediate autosave via the manager.

        Returns the path written (or ``None`` when the manager is missing
        or the force-save raised). Every subsequent refresh will pick up
        the new snapshot.
        """
        mgr = self._manager
        if mgr is None:
            self.call_log.append(("force_save_now", None))
            return None
        try:
            path = mgr.force_save()
        except Exception:
            self.call_log.append(("force_save_now_failed", None))
            return None
        self.call_log.append(("force_save_now", str(path)))
        try:
            self.refresh()
        except Exception:
            pass
        return Path(path) if path is not None else None

    # ------------------------------------------------------------------
    # Right-click context menu
    # ------------------------------------------------------------------

    def open_context_menu(self, target: int | Path | str) -> dict[str, Any]:
        """Open the right-click context menu anchored to *target*.

        The menu exposes the four canonical actions: Restore, Delete,
        Preview, Copy Path. Returns the menu descriptor so headless
        tests can invoke each action via the returned callables.
        """
        row = self._resolve_row(target)
        menu = {
            "row": row,
            "actions": {
                "restore": lambda: self.restore(row.path),
                "delete":  lambda: self.delete(row.path),
                "preview": lambda: self.preview(row.path),
                "copy_path": lambda: self.copy_path(row.path),
            },
        }
        self._context_menu = menu
        self.call_log.append(("open_context_menu", str(row.path)))
        return menu

    def close_context_menu(self) -> bool:
        """Drop the context menu descriptor. Returns ``True`` if one was open."""
        if self._context_menu is None:
            return False
        self._context_menu = None
        self.call_log.append(("close_context_menu", None))
        return True

    # ------------------------------------------------------------------
    # Build / rebuild
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Construct the widget tree under *parent_tag*. Headless-safe."""
        self._parent_tag = parent_tag
        self._built = True
        dpg = _safe_dpg()
        if dpg is None:
            return

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                self._build_header(dpg)
                try:
                    dpg.add_separator()
                except Exception:
                    pass
                # Ruled-paper background around the row list.
                try:
                    with dpg.child_window(
                        tag=self._RULED_TAG, border=True, height=-30,
                    ):
                        with dpg.group(tag=self._LIST_TAG):
                            self._build_rows(dpg)
                except Exception:
                    try:
                        dpg.add_group(tag=self._LIST_TAG)
                    except Exception:
                        pass
                    self._build_rows(dpg)
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    def _build_header(self, dpg: Any) -> None:
        """Header row: project name, status, Refresh, Force-save-now."""
        try:
            with dpg.group(tag=self._HEADER_TAG, horizontal=True):
                try:
                    dpg.add_text(self.project_name(), tag=self._PROJECT_TAG)
                except Exception:
                    pass
                try:
                    dpg.add_text(self.status_text(), tag=self._STATUS_TAG)
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Refresh",
                        callback=self._on_refresh_clicked,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Force save now",
                        callback=self._on_force_save_clicked,
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _build_rows(self, dpg: Any) -> None:
        """Render the snapshot rows (or the empty state)."""
        if not self._rows:
            try:
                dpg.add_text(self.empty_state_text(), tag=self._EMPTY_TAG)
            except Exception:
                pass
            return

        display = self._rows[: self._MAX_RENDERED_ROWS]
        now = time.time()
        for i, row in enumerate(display):
            self._build_single_row(dpg, i, row, now)
            # Hand-drawn divider between rows.
            if i + 1 < len(display):
                try:
                    dpg.add_text("~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~")
                except Exception:
                    pass

    def _build_single_row(
        self, dpg: Any, index: int, row: SnapshotRow, now: float,
    ) -> None:
        """Build the widgets for one snapshot row."""
        stamp = _format_timestamp(row.mtime)
        age = _format_age_seconds(row.age_seconds(now))
        try:
            with dpg.group(horizontal=True):
                try:
                    dpg.add_text(stamp)
                except Exception:
                    pass
                try:
                    dpg.add_text(age)
                except Exception:
                    pass
                try:
                    dpg.add_text(row.filename)
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Restore",
                        callback=self._make_row_cb("restore", row.path),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Delete",
                        callback=self._make_row_cb("delete", row.path),
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Preview",
                        callback=self._make_row_cb("preview", row.path),
                    )
                except Exception:
                    pass
        except Exception:
            try:
                dpg.add_text(f"{stamp} {age} {row.filename}")
            except Exception:
                pass

    def _rebuild_list_widget(self) -> None:
        """Wipe + re-render the list container. Called from :meth:`refresh`."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if not dpg.does_item_exist(self._LIST_TAG):
                return
        except Exception:
            return
        try:
            for child in list(dpg.get_item_children(self._LIST_TAG, slot=1) or []):
                try:
                    dpg.delete_item(child)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            with dpg.group(parent=self._LIST_TAG):
                self._build_rows(dpg)
        except Exception:
            try:
                self._build_rows(dpg)
            except Exception:
                pass

    def _update_status_widget(self) -> None:
        """Refresh the header status text under its cached tag."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._STATUS_TAG):
                dpg.set_value(self._STATUS_TAG, self.status_text())
        except Exception:
            pass

    def _update_project_widget(self) -> None:
        """Refresh the header project-name text under its cached tag."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._PROJECT_TAG):
                dpg.set_value(self._PROJECT_TAG, self.project_name())
        except Exception:
            pass

    def destroy(self) -> None:
        """Tear down external state so the panel can be garbage-collected."""
        self.close_preview()
        self.close_context_menu()
        self._built = False

    # ------------------------------------------------------------------
    # DPG callback builders
    # ------------------------------------------------------------------

    def _make_row_cb(self, action: str, path: Path) -> Callable[..., None]:
        """Return a DPG-compatible callback that fires *action* on *path*."""
        if action == "restore":
            def _cb(*_a: Any, **_kw: Any) -> None:
                self.restore(path)
            return _cb
        if action == "delete":
            def _cb(*_a: Any, **_kw: Any) -> None:
                self.delete(path)
            return _cb
        if action == "preview":
            def _cb(*_a: Any, **_kw: Any) -> None:
                self.preview(path)
            return _cb
        if action == "copy_path":
            def _cb(*_a: Any, **_kw: Any) -> None:
                self.copy_path(path)
            return _cb
        # Unknown action — fall back to a no-op logger.
        def _cb(*_a: Any, **_kw: Any) -> None:
            self.call_log.append(("row_cb_unknown", (action, str(path))))
        return _cb

    def _on_refresh_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.refresh()

    def _on_force_save_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.force_save_now()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _last_saved_ago_seconds(self) -> Optional[float]:
        """Resolve the "N sec ago" hint via integration or manager state."""
        integ = self._integration
        if integ is not None:
            try:
                v = integ.last_saved_ago_seconds()
                if v is not None:
                    return float(v)
            except Exception:
                pass
        mgr = self._manager
        if mgr is not None:
            state = getattr(mgr, "state", None)
            last = getattr(state, "last_saved_at", None) if state is not None else None
            if isinstance(last, (int, float)) and not isinstance(last, bool):
                return max(0.0, time.time() - float(last))
        return None


__all__ = [
    "NotebookAutosavePanel",
    "SnapshotRow",
]
