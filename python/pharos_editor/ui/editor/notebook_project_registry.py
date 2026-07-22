"""``NotebookProjectRegistryPanel`` — diary-themed project registry manager.

The registry panel is a side-panel that shows every project registered
with :class:`pharos_engine.project_registry.ProjectRegistry`. It lets
the user:

* browse the full list (name / path / last opened),
* click **Open** on any row to invoke a caller-supplied handler,
* click **Remove** on any row to drop it from the registry,
* click **+ Add Project** in the header to pick a folder via
  ``dpg.add_file_dialog`` and register a fresh entry.

The panel is themed via the notebook :class:`NotebookTheme` (via
:func:`resolve_theme`) so it colour-matches the rest of the diary
editor. Every DPG call is guarded so the panel imports and builds
cleanly under a stub ``dearpygui`` in CI.

Wrap in :class:`MovablePanelWindow` from
:mod:`pharos_editor.ui.editor.movable_panel` to get chrome + drag +
resize; the panel itself just implements ``build(parent_tag)``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from pharos_engine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_positive_int,
)
from pharos_engine.project_registry import (
    ProjectRegistry,
    RegisteredProject,
    get_default_registry,
    iso_utc_now,
)
from pharos_editor.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)


__all__ = [
    "NotebookProjectRegistryPanel",
]


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]

        return dpg
    except Exception:
        return None


class NotebookProjectRegistryPanel:
    """Side panel that manages the persistent project registry.

    Parameters
    ----------
    on_open:
        Optional callback fired when the user clicks **Open** on a row.
        Receives the :class:`RegisteredProject`. Defaults to a no-op so
        headless tests can smoke-instantiate the panel.
    registry:
        Optional :class:`ProjectRegistry`. Defaults to
        :func:`get_default_registry`.
    """

    TITLE = "Project registry"
    WIDTH = 560
    HEIGHT = 480

    # Movable-window minimums picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 480
    MIN_HEIGHT: int = 320

    EMPTY_STATE_MESSAGE = "No projects yet — click '+ Add Project' to register one."

    def __init__(
        self,
        on_open: Callable[[RegisteredProject], None] | None = None,
        registry: ProjectRegistry | None = None,
    ) -> None:
        self._on_open = validate_callable(
            "on_open",
            "NotebookProjectRegistryPanel",
            on_open if on_open is not None else (lambda _p: None),
        )
        if registry is None:
            registry = get_default_registry()
        if not isinstance(registry, ProjectRegistry):
            raise TypeError(
                "NotebookProjectRegistryPanel: registry must be a "
                f"ProjectRegistry; got {type(registry).__name__}"
            )
        self._registry = registry

        self._theme = resolve_theme()
        register_theme_listener(self._on_theme_changed)

        self._panel_tag = f"notebook_project_registry_{id(self)}"
        self._header_tag = f"{self._panel_tag}_header"
        self._list_tag = f"{self._panel_tag}_list"
        self._empty_tag = f"{self._panel_tag}_empty"
        self._add_btn_tag = f"{self._panel_tag}_add_btn"
        self._file_dialog_tag = f"{self._panel_tag}_file_dialog"

        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._displayed: list[RegisteredProject] = []

        # Test-visible counters
        self._open_count: int = 0
        self._remove_count: int = 0
        self._add_count: int = 0
        self._last_opened: RegisteredProject | None = None

    # ── Theme wiring ─────────────────────────────────────────────────

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()

    # ── Public properties ────────────────────────────────────────────

    @property
    def registry(self) -> ProjectRegistry:
        return self._registry

    @property
    def panel_tag(self) -> str:
        return self._panel_tag

    @property
    def list_tag(self) -> str:
        return self._list_tag

    @property
    def add_btn_tag(self) -> str:
        return self._add_btn_tag

    @property
    def displayed(self) -> list[RegisteredProject]:
        """Snapshot of the projects rendered at the last :meth:`refresh`."""
        return list(self._displayed)

    @property
    def open_count(self) -> int:
        return self._open_count

    @property
    def remove_count(self) -> int:
        return self._remove_count

    @property
    def add_count(self) -> int:
        return self._add_count

    @property
    def is_built(self) -> bool:
        return self._built

    # ── Lifecycle ────────────────────────────────────────────────────

    def destroy(self) -> None:
        """Drop the theme listener and tear down the DPG subtree (if any)."""
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is not None:
            for tag in (self._panel_tag, self._file_dialog_tag):
                try:
                    if dpg.does_item_exist(tag):
                        dpg.delete_item(tag)
                except Exception:
                    pass
        self._built = False

    # ── Build ────────────────────────────────────────────────────────

    def build(self, parent_tag: int | str) -> None:
        """Render the panel under *parent_tag*. Headless-safe."""
        if isinstance(parent_tag, str):
            validate_non_empty_str(
                "parent_tag", "NotebookProjectRegistryPanel.build", parent_tag,
            )
        self._parent_tag = parent_tag
        self._built = True
        self._refresh_snapshot()

        dpg = _safe_dpg()
        if dpg is None:
            return

        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        washi = list(self._theme.color("washi", (180, 200, 230, 255)))

        try:
            with dpg.child_window(
                tag=self._panel_tag,
                parent=parent_tag,
                width=self.WIDTH,
                height=self.HEIGHT,
                border=True,
            ):
                # Title
                try:
                    dpg.add_text(
                        f"* {self.TITLE} *",
                        color=accent,
                        tag=f"{self._panel_tag}_title",
                    )
                except Exception:
                    pass

                # Header row — "+ Add Project" button
                try:
                    with dpg.group(horizontal=True, tag=self._header_tag):
                        dpg.add_button(
                            label="+ Add Project",
                            width=180,
                            height=28,
                            callback=self._on_add_clicked,
                            tag=self._add_btn_tag,
                        )
                except Exception:
                    try:
                        dpg.add_button(
                            label="+ Add Project",
                            width=180,
                            height=28,
                            callback=self._on_add_clicked,
                            tag=self._add_btn_tag,
                        )
                    except Exception:
                        pass

                # Doodle separator
                try:
                    dpg.add_text(
                        "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
                        color=washi,
                    )
                except Exception:
                    pass

                # Column headers
                try:
                    with dpg.group(horizontal=True):
                        dpg.add_text("Name", color=ink)
                        dpg.add_text(" | ", color=washi)
                        dpg.add_text("Path", color=ink)
                        dpg.add_text(" | ", color=washi)
                        dpg.add_text("Last opened", color=ink)
                except Exception:
                    pass

                # List container
                try:
                    with dpg.child_window(
                        tag=self._list_tag,
                        border=True,
                        height=-1,
                    ):
                        self._build_rows(dpg, ink, accent)
                except Exception:
                    self._build_rows(dpg, ink, accent)
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    def _build_rows(
        self,
        dpg: Any,
        ink: list[int],
        accent: list[int],
    ) -> None:
        """Render one row per registered project (or an empty-state message)."""
        if not self._displayed:
            try:
                dpg.add_text(
                    self.EMPTY_STATE_MESSAGE,
                    color=ink,
                    tag=self._empty_tag,
                )
            except Exception:
                pass
            return

        for project in self._displayed:
            self._build_row(dpg, project, ink, accent)

    def _build_row(
        self,
        dpg: Any,
        project: RegisteredProject,
        ink: list[int],
        accent: list[int],
    ) -> None:
        row_tag = self._row_tag(project.name)
        try:
            with dpg.group(horizontal=True, tag=row_tag):
                # Name + path label
                label = f"* {project.name}  ({project.path})  ~ {project.last_opened}"
                try:
                    dpg.add_text(label, color=ink, tag=f"{row_tag}_label")
                except Exception:
                    pass
                # Open button
                try:
                    dpg.add_button(
                        label="Open",
                        width=64,
                        height=22,
                        callback=(
                            lambda *_a, name=project.name: self._on_open_clicked(name)
                        ),
                        tag=f"{row_tag}_open",
                    )
                except Exception:
                    pass
                # Remove button
                try:
                    dpg.add_button(
                        label="Remove",
                        width=72,
                        height=22,
                        callback=(
                            lambda *_a, name=project.name: self._on_remove_clicked(name)
                        ),
                        tag=f"{row_tag}_remove",
                    )
                except Exception:
                    pass
        except Exception:
            # Some stub DPGs don't support ``with`` on ``add_group`` —
            # fall back to a flat button pair so the callback wiring
            # still exists for tests.
            try:
                dpg.add_button(
                    label=f"Open {project.name}",
                    callback=(
                        lambda *_a, name=project.name: self._on_open_clicked(name)
                    ),
                    tag=f"{row_tag}_open",
                )
            except Exception:
                pass
            try:
                dpg.add_button(
                    label=f"Remove {project.name}",
                    callback=(
                        lambda *_a, name=project.name: self._on_remove_clicked(name)
                    ),
                    tag=f"{row_tag}_remove",
                )
            except Exception:
                pass

    # ── Refresh ──────────────────────────────────────────────────────

    def refresh(self, limit: int | None = None) -> None:
        """Rebuild the visible list from the registry. Headless-safe.

        Parameters
        ----------
        limit:
            When set, render only the top *limit* entries (newest first).
            Defaults to *None* = show everything.
        """
        if limit is not None:
            limit = validate_positive_int(
                "limit", "NotebookProjectRegistryPanel.refresh", limit,
            )
        self._refresh_snapshot(limit=limit)
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._list_tag):
                try:
                    dpg.delete_item(self._list_tag, children_only=True)
                except TypeError:
                    dpg.delete_item(self._list_tag)
        except Exception:
            pass
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))
        self._build_rows(dpg, ink, accent)

    def _refresh_snapshot(self, limit: int | None = None) -> None:
        try:
            if limit is None:
                self._displayed = list(self._registry.list_all())
            else:
                self._displayed = list(self._registry.list_recent(limit=limit))
        except Exception:
            self._displayed = []

    # ── Callback shims ───────────────────────────────────────────────

    def _on_open_clicked(self, name: str) -> None:
        self.open_project(name)

    def _on_remove_clicked(self, name: str) -> None:
        self.remove_project(name)

    def _on_add_clicked(self, *_: Any) -> None:
        """Pop a folder picker via ``dpg.add_file_dialog``.

        The dialog wires ``callback=self._on_folder_chosen`` — that
        callback registers the picked folder as a new project.
        """
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._file_dialog_tag):
                dpg.delete_item(self._file_dialog_tag)
        except Exception:
            pass
        try:
            dpg.add_file_dialog(
                directory_selector=True,
                show=True,
                callback=self._on_folder_chosen,
                tag=self._file_dialog_tag,
                width=520,
                height=380,
            )
        except Exception:
            pass

    def _on_folder_chosen(
        self, _sender: Any = None, app_data: Any = None, *_: Any,
    ) -> None:
        """DPG file-dialog callback — resolve the picked path + register."""
        path_str: str | None = None
        if isinstance(app_data, dict):
            path_str = app_data.get("file_path_name") or app_data.get("current_path")
        elif isinstance(app_data, str):
            path_str = app_data
        if not path_str:
            return
        try:
            path = Path(path_str)
        except Exception:
            return
        name = path.name or path_str
        self.add_project(name, path)

    # ── Public action surface (test-visible) ─────────────────────────

    def add_project(
        self,
        name: str,
        path: Path | str,
        *,
        notes: Optional[str] = None,
    ) -> RegisteredProject:
        """Register a project + refresh the panel.

        Returns the stored :class:`RegisteredProject` — mostly useful
        for tests that want to assert on the round-trip.
        """
        validate_non_empty_str(
            "name", "NotebookProjectRegistryPanel.add_project", name,
        )
        project = RegisteredProject(
            name=name,
            path=Path(path),
            last_opened=iso_utc_now(),
            notes=notes,
        )
        stored = self._registry.add(project)
        self._add_count += 1
        self.refresh()
        return stored

    def open_project(self, name: str) -> Optional[RegisteredProject]:
        """Bump ``last_opened`` + fire the caller's ``on_open``.

        Returns the opened :class:`RegisteredProject`, or ``None`` if
        the entry no longer exists (dropped between refreshes).
        """
        validate_non_empty_str(
            "name", "NotebookProjectRegistryPanel.open_project", name,
        )
        project = self._registry.get(name)
        if project is None:
            return None
        self._registry.touch(name)
        # Re-read so ``last_opened`` reflects the touch().
        project = self._registry.get(name) or project
        self._open_count += 1
        self._last_opened = project
        try:
            self._on_open(project)
        except Exception:
            pass
        self.refresh()
        return project

    def remove_project(self, name: str) -> bool:
        """Drop the project named *name* from the registry + refresh."""
        validate_non_empty_str(
            "name", "NotebookProjectRegistryPanel.remove_project", name,
        )
        removed = self._registry.remove(name)
        if removed:
            self._remove_count += 1
            self.refresh()
        return removed

    def _row_tag(self, name: str) -> str:
        """Stable DPG tag for the row owning *name*."""
        scrub = (
            name.replace(" ", "_")
            .replace("\\", "_")
            .replace("/", "_")
            .replace(":", "_")
        )
        return f"{self._panel_tag}_row_{scrub}"
