"""``NotebookProjectPicker`` — diary-themed project chooser modal.

The picker is the editor's first-run + ``File → Switch Project`` modal.
It lists the recently opened projects from a :class:`ProjectRegistry`,
plus two action stickers:

* **New notebook…**  — opens a sub-modal for name / location / theme,
  then calls ``registry.new(root, name)`` and forwards the resulting
  :class:`Project` to the caller.
* **Open from disk** — pops a native folder picker (soft-imported
  tkinter), walks upward looking for ``project.slap_proj``, then calls
  ``registry.open(path)``.

Both paths converge on the same ``on_project_chosen(project)`` callback
the caller wires to load the project into the editor. Cancel fires
``on_cancel()`` so the parent can dismiss its first-run blocker.

Each recent row is a clickable button with a right-click context menu
offering "Remove from recents" (drops the entry from the registry and
refreshes the list).

Headless-safe — every DPG and tkinter call is guarded so the module
imports and builds cleanly under a stub ``dearpygui`` in CI.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_path_like,
)
from slappyengine.projects import (
    Project,
    ProjectFormatError,
    ProjectRegistry,
    find_project_root,
    get_default_registry,
)
from slappyengine.projects.registry import RegistryEntry
from slappyengine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)


__all__ = [
    "NotebookProjectPicker",
    "THEME_OPTIONS",
    "humanise_age",
]


# ---------------------------------------------------------------------------
# Theme dropdown — six default options matching ``notebook_welcome``.
# ---------------------------------------------------------------------------

THEME_OPTIONS: tuple[str, ...] = (
    "teengirl_notebook",
    "cozy_diary",
    "bullet_journal",
    "scrapbook_summer",
    "cottagecore_garden",
    "kawaii_planner",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


def _parse_iso(stamp: str) -> datetime | None:
    """Parse an ISO 8601 string into a ``datetime``.

    Tolerates the trailing ``Z`` used by the registry. Returns ``None``
    on parse failure so the caller can fall back to ``"unknown"``.
    """
    if not isinstance(stamp, str) or not stamp:
        return None
    s = stamp.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def humanise_age(stamp: str, *, now: datetime | None = None) -> str:
    """Convert an ISO 8601 timestamp to a friendly relative age.

    Buckets:

    * < 60 s ............. ``"just now"``
    * < 60 min ........... ``"{n}m ago"``
    * same calendar day .. ``"Today"``
    * < 24 h ............. ``"{n}h ago"``
    * < 7 days ........... ``"{n}d ago"``
    * < 5 weeks .......... ``"{n}w ago"``
    * < 12 months ........ ``"{n}mo ago"``
    * else ............... ``"{n}y ago"``

    Returns ``"unknown"`` when *stamp* can't be parsed.
    """
    parsed = _parse_iso(stamp)
    if parsed is None:
        return "unknown"
    if now is None:
        now = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    delta = now - parsed
    secs = int(delta.total_seconds())
    if secs < 60:
        return "just now"
    mins = secs // 60
    if mins < 60:
        return f"{mins}m ago"
    hrs = mins // 60
    if hrs < 24:
        if parsed.date() == now.date():
            return "Today"
        return f"{hrs}h ago"
    days = hrs // 24
    if days < 7:
        return f"{days}d ago"
    weeks = days // 7
    if weeks < 5:
        return f"{weeks}w ago"
    months = days // 30
    if months < 12:
        return f"{months}mo ago"
    years = days // 365
    return f"{years}y ago"


# ---------------------------------------------------------------------------
# NotebookProjectPicker
# ---------------------------------------------------------------------------


class NotebookProjectPicker:
    """Project picker — pick from recents or create / open browse.

    Modal that blocks the editor until the user resolves a project to
    load. Used on first run (no project in cwd / parents) and via the
    ``File → Switch Project`` menu.

    Parameters
    ----------
    on_project_chosen:
        Invoked with the resolved :class:`Project` when the user picks
        a recent row, creates a new project, or opens one from disk.
        Required.
    on_cancel:
        Zero-arg callback fired when the user dismisses the picker
        without resolving a project. Parents typically use this to
        exit the editor cleanly on first run. Required.
    registry:
        Optional :class:`ProjectRegistry`. Defaults to
        :func:`get_default_registry` so the singleton recents list is
        shared with the rest of the editor.
    """

    TITLE = "Pick a notebook"
    WIDTH = 520
    HEIGHT = 460
    EMPTY_STATE_MESSAGE = "No recent notebooks yet — start a new one!"

    def __init__(
        self,
        on_project_chosen: Callable[[Project], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        registry: ProjectRegistry | None = None,
        *,
        # Backwards-compat aliases for the older keyword-only API.
        on_chosen: Callable[[Project], None] | None = None,
        on_cancelled: Callable[[], None] | None = None,
    ) -> None:
        # Reconcile new + legacy keyword names — the spec uses
        # ``on_project_chosen`` / ``on_cancel``; older shell callers used
        # ``on_chosen`` / ``on_cancelled`` keyword-only. Either is accepted
        # and validated through the same code path.
        if on_project_chosen is None:
            on_project_chosen = on_chosen
        if on_cancel is None:
            on_cancel = on_cancelled

        # The chosen callback is required so the picker never silently
        # eats a successful pick. The cancel callback is optional — when
        # absent we still wire a no-op so test code can hit
        # ``self._on_cancel`` without a None guard.
        self._on_project_chosen = validate_callable(
            "on_project_chosen",
            "NotebookProjectPicker",
            on_project_chosen if on_project_chosen is not None else (lambda _p: None),
        )
        self._on_cancel = validate_callable(
            "on_cancel",
            "NotebookProjectPicker",
            on_cancel if on_cancel is not None else (lambda: None),
        )

        if registry is None:
            registry = get_default_registry()
        if not isinstance(registry, ProjectRegistry):
            raise TypeError(
                "NotebookProjectPicker: registry must be a ProjectRegistry; "
                f"got {type(registry).__name__}"
            )
        self._registry = registry

        # Theme snapshot — refreshed when the user picks a swatch.
        self._theme = resolve_theme()
        register_theme_listener(self._on_theme_changed)

        # DPG tag namespace
        self._panel_tag = f"notebook_project_picker_{id(self)}"
        self._list_tag = f"{self._panel_tag}_recents"
        self._sub_modal_tag = f"{self._panel_tag}_new_sub"
        self._built: bool = False
        self._open: bool = False
        self._parent_tag: str | int | None = None

        # Cached snapshot of the recents list rendered at last refresh.
        self._displayed_entries: list[RegistryEntry] = []

        # Test-visible counters / handles
        self._chosen_count: int = 0
        self._cancel_count: int = 0
        self._last_chosen: Project | None = None

    # ------------------------------------------------------------------
    # Theme wiring
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def registry(self) -> ProjectRegistry:
        return self._registry

    @property
    def panel_tag(self) -> str:
        return self._panel_tag

    @property
    def displayed_entries(self) -> list[RegistryEntry]:
        """Return the recents shown at the most recent :meth:`refresh`."""
        return list(self._displayed_entries)

    @property
    def chosen_count(self) -> int:
        return self._chosen_count

    @property
    def cancel_count(self) -> int:
        return self._cancel_count

    @property
    def last_chosen(self) -> Project | None:
        return self._last_chosen

    @property
    def is_open(self) -> bool:
        return self._open

    # Backwards-compat shim — older code path used ``picker.visible``.
    @property
    def visible(self) -> bool:
        return self._open

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Mark the picker as visible. Idempotent."""
        self._open = True

    def show(self) -> None:
        """Backwards-compat alias for :meth:`open`."""
        self.open()

    def hide(self) -> None:
        """Mark the picker as hidden without firing any callbacks."""
        self._open = False

    def close(self) -> None:
        """Hide the picker and tear down its DPG subtree (if any).

        Only touches DPG when :meth:`build` has run — calling
        ``does_item_exist`` before a DPG context exists segfaults on
        Windows, which surfaces during headless lifecycle tests.
        """
        self._open = False
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is not None:
            for tag in (self._panel_tag, self._sub_modal_tag):
                try:
                    if dpg.does_item_exist(tag):
                        dpg.delete_item(tag)
                except Exception:
                    pass
        self._built = False

    def destroy(self) -> None:
        """Tear down the panel — drop theme listener + subtree."""
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self.close()

    # ------------------------------------------------------------------
    # Build / refresh
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Render the picker modal under *parent_tag*.

        Headless-safe — every DPG call is guarded so the panel still
        registers its callbacks under a stub ``dearpygui`` in CI.
        """
        if isinstance(parent_tag, str):
            validate_non_empty_str(
                "parent_tag", "NotebookProjectPicker.build", parent_tag,
            )
        self._parent_tag = parent_tag
        self._built = True
        self._open = True

        # Always refresh the snapshot first so ``displayed_entries`` is
        # accurate even in headless contexts.
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
                # Title bar
                try:
                    dpg.add_text(
                        f"* {self.TITLE} *",
                        color=accent,
                        tag=f"{self._panel_tag}_title",
                    )
                except Exception:
                    pass

                # Recents header
                try:
                    dpg.add_text("Recent notebooks:", color=ink)
                except Exception:
                    pass

                # Recent rows container
                try:
                    with dpg.child_window(
                        tag=self._list_tag,
                        border=True,
                        height=200,
                    ):
                        self._build_recent_rows(dpg, ink, accent)
                except Exception:
                    self._build_recent_rows(dpg, ink, accent)

                # Doodle separator
                try:
                    dpg.add_text(
                        "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
                        color=washi,
                    )
                except Exception:
                    pass

                # Action row
                try:
                    with dpg.group(horizontal=True):
                        self._build_action_buttons(dpg)
                except Exception:
                    self._build_action_buttons(dpg)

                # Cancel button
                try:
                    dpg.add_button(
                        label="Cancel",
                        width=120,
                        height=28,
                        callback=self._on_cancel_clicked,
                        tag=f"{self._panel_tag}_cancel_btn",
                    )
                except Exception:
                    pass
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    def _build_recent_rows(
        self,
        dpg: Any,
        ink: list[int],
        accent: list[int],
    ) -> None:
        """Render one button per recent project (or an empty-state message)."""
        if not self._displayed_entries:
            try:
                dpg.add_text(
                    self.EMPTY_STATE_MESSAGE,
                    color=ink,
                    tag=f"{self._panel_tag}_empty",
                )
            except Exception:
                pass
            return

        for entry in self._displayed_entries:
            self._build_recent_row(dpg, entry, ink, accent)

    def _build_recent_row(
        self,
        dpg: Any,
        entry: RegistryEntry,
        ink: list[int],
        accent: list[int],
    ) -> None:
        """Render one row — name + age + a click button + context menu."""
        row_tag = self._row_tag(entry.path)
        btn_tag = f"{row_tag}_btn"
        age = humanise_age(entry.last_opened_at)
        display_name = entry.name or Path(entry.path).name or "Untitled"
        label = f"* {display_name}   ({age})"
        try:
            dpg.add_button(
                label=label,
                width=-1,
                height=28,
                callback=(
                    lambda *_a, p=entry.path: self._on_recent_clicked(p)
                ),
                tag=btn_tag,
            )
        except Exception:
            pass
        # Right-click context menu — "Remove from recents".
        try:
            with dpg.popup(parent=btn_tag, mousebutton=1):
                dpg.add_menu_item(
                    label="Remove from recents",
                    callback=(
                        lambda *_a, p=entry.path: self._on_remove_recent(p)
                    ),
                    tag=f"{row_tag}_remove",
                )
        except Exception:
            # Stub DPG without ``popup`` — register the remove handler
            # under a flat tag so tests can still trigger the path via
            # :meth:`remove_recent`.
            try:
                dpg.add_menu_item(
                    label="Remove from recents",
                    callback=(
                        lambda *_a, p=entry.path: self._on_remove_recent(p)
                    ),
                    tag=f"{row_tag}_remove",
                )
            except Exception:
                pass

    def _build_action_buttons(self, dpg: Any) -> None:
        try:
            dpg.add_button(
                label="<3 New notebook...",
                width=180,
                height=32,
                callback=self._on_new_clicked,
                tag=f"{self._panel_tag}_new_btn",
            )
        except Exception:
            pass
        try:
            dpg.add_button(
                label="[F] Open from disk",
                width=180,
                height=32,
                callback=self._on_open_disk_clicked,
                tag=f"{self._panel_tag}_open_btn",
            )
        except Exception:
            pass

    def refresh(self) -> None:
        """Rebuild the recents list under the existing panel.

        Safe to call repeatedly — re-runs the recents render path so the
        modal stays in sync with the registry. Headless-safe.
        """
        self._refresh_snapshot()
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
        self._build_recent_rows(dpg, ink, accent)

    def _refresh_snapshot(self) -> None:
        try:
            self._displayed_entries = list(
                self._registry.list_recent(limit=10)
            )
        except Exception:
            self._displayed_entries = []

    def _row_tag(self, path: str) -> str:
        """Stable DPG tag for the row owning *path*."""
        scrub = (
            path.replace("\\", "_")
            .replace("/", "_")
            .replace(":", "_")
            .replace(" ", "_")
        )
        return f"{self._panel_tag}_row_{scrub}"

    # ------------------------------------------------------------------
    # Public action surface — exposed so tests can drive the picker
    # without going through DPG.
    # ------------------------------------------------------------------

    def list_recent(self, limit: int = 10) -> list[RegistryEntry]:
        """Convenience pass-through to :meth:`ProjectRegistry.list_recent`."""
        return self._registry.list_recent(limit=limit)

    def pick_recent(self, index_or_path) -> Optional[Project]:
        """Open a recent project.

        Accepts either:

        * an ``int`` index into the recents list (legacy API), or
        * a ``str`` / ``Path`` referring to the project root directly.

        Returns the opened :class:`Project`, or ``None`` if the entry
        could not be loaded (the row is dropped from recents in that
        case so the bad entry disappears on the next refresh).

        Raises
        ------
        IndexError
            If ``index_or_path`` is an int outside the recents range.
        """
        if isinstance(index_or_path, bool):
            raise TypeError(
                "NotebookProjectPicker.pick_recent: index must be int / "
                "str / Path"
            )
        if isinstance(index_or_path, int):
            recents = self._registry.list_recent(
                limit=max(1, index_or_path + 1),
            )
            if index_or_path < 0 or index_or_path >= len(recents):
                raise IndexError(
                    f"pick_recent: index {index_or_path} out of range "
                    f"(have {len(recents)} entries)"
                )
            path: str | Path = recents[index_or_path].path
        else:
            path = index_or_path
        try:
            project = self._registry.open(path)
        except (FileNotFoundError, ProjectFormatError):
            try:
                self._registry.unregister(path)
            except Exception:
                pass
            self.refresh()
            return None
        self._resolve(project)
        return project

    def pick_path(self, path: Path | str) -> Project:
        """Open the project rooted at *path*. Raises on missing manifest."""
        validate_path_like("path", "NotebookProjectPicker.pick_path", path)
        project = self._registry.open(path)
        self._resolve(project)
        return project

    def remove_recent(self, path: str | Path) -> bool:
        """Drop *path* from the registry and refresh the panel."""
        removed = self._registry.unregister(path)
        if removed:
            self.refresh()
        return removed

    def create(
        self,
        path: Path | str,
        name: str,
        *,
        description: str = "",
        scaffold: bool = True,
        default_theme: str | None = None,
    ) -> Project:
        """Backwards-compat constructor used by the older shell wiring.

        Scaffolds a fresh project at *path* with manifest *name* and
        fires ``on_project_chosen``.
        """
        validate_path_like("path", "NotebookProjectPicker.create", path)
        validate_non_empty_str("name", "NotebookProjectPicker.create", name)
        project = self._registry.new(
            path, name, description=description, scaffold=scaffold,
        )
        if default_theme is not None:
            if default_theme not in THEME_OPTIONS:
                raise ValueError(
                    "NotebookProjectPicker.create: default_theme must be "
                    f"one of {THEME_OPTIONS}; got {default_theme!r}"
                )
            project.metadata.default_theme = default_theme
            try:
                project.save()
            except Exception:
                pass
        self._resolve(project)
        return project

    def create_new(
        self,
        root: str | Path,
        name: str,
        *,
        default_theme: str = "teengirl_notebook",
        description: str = "",
    ) -> Project:
        """Create a project at *root* with *name*, fire ``on_project_chosen``.

        ``default_theme`` is validated against :data:`THEME_OPTIONS` and
        persisted onto the project's metadata after creation.
        """
        if default_theme not in THEME_OPTIONS:
            raise ValueError(
                f"NotebookProjectPicker.create_new: default_theme must be one "
                f"of {THEME_OPTIONS}; got {default_theme!r}"
            )
        return self.create(
            root,
            name,
            description=description,
            default_theme=default_theme,
        )

    def open_from_disk(self, path: str | Path) -> Project | None:
        """Open the project rooted at (or above) *path*.

        Walks upward via :func:`find_project_root` so the caller may
        pass any directory inside the project tree. Returns ``None`` if
        no manifest was located so the caller can surface a friendly
        "not a project directory" message.
        """
        try:
            target = validate_path_like(
                "path", "NotebookProjectPicker.open_from_disk", path,
            )
        except (TypeError, ValueError):
            return None
        root = find_project_root(target)
        if root is None:
            return None
        try:
            project = self._registry.open(root)
        except (FileNotFoundError, ProjectFormatError):
            return None
        self._resolve(project)
        return project

    def cancel(self) -> None:
        """Public cancel hook — equivalent to clicking the Cancel button."""
        self._on_cancel_clicked()

    # ------------------------------------------------------------------
    # Internal callback shims (DPG-bound)
    # ------------------------------------------------------------------

    def _on_recent_clicked(self, path: str) -> None:
        self.pick_recent(path)

    def _on_remove_recent(self, path: str) -> None:
        self.remove_recent(path)

    def _on_new_clicked(self, *_: Any) -> None:
        """Open the new-project sub-modal."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._sub_modal_tag):
                dpg.delete_item(self._sub_modal_tag)
        except Exception:
            pass
        name_tag = f"{self._sub_modal_tag}_name"
        loc_tag = f"{self._sub_modal_tag}_location"
        theme_tag = f"{self._sub_modal_tag}_theme"
        try:
            with dpg.window(
                label="New notebook",
                tag=self._sub_modal_tag,
                modal=True,
                width=360,
                height=220,
            ):
                try:
                    dpg.add_input_text(
                        label="Name",
                        default_value="My Notebook",
                        tag=name_tag,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_input_text(
                        label="Location",
                        default_value=str(Path.home()),
                        tag=loc_tag,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_combo(
                        items=list(THEME_OPTIONS),
                        label="Theme",
                        default_value=THEME_OPTIONS[0],
                        tag=theme_tag,
                    )
                except Exception:
                    pass
                try:
                    dpg.add_button(
                        label="Create",
                        callback=(
                            lambda *_a: self._create_from_sub_modal(
                                dpg, name_tag, loc_tag, theme_tag,
                            )
                        ),
                        tag=f"{self._sub_modal_tag}_create_btn",
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def _create_from_sub_modal(
        self,
        dpg: Any,
        name_tag: str,
        loc_tag: str,
        theme_tag: str,
    ) -> None:
        try:
            name = dpg.get_value(name_tag) or ""
        except Exception:
            name = ""
        try:
            location = dpg.get_value(loc_tag) or ""
        except Exception:
            location = ""
        try:
            theme = dpg.get_value(theme_tag) or THEME_OPTIONS[0]
        except Exception:
            theme = THEME_OPTIONS[0]
        if not name or not location:
            # Leave the sub-modal open — validation feedback would live
            # alongside the input widgets. In CI / stub-DPG we silently
            # no-op so the picker stays usable.
            return
        root = Path(location).expanduser() / name
        try:
            self.create_new(root, name, default_theme=theme)
        except Exception:
            return
        try:
            if dpg.does_item_exist(self._sub_modal_tag):
                dpg.delete_item(self._sub_modal_tag)
        except Exception:
            pass

    def _on_open_disk_clicked(self, *_: Any) -> None:
        """Pop a folder picker (tkinter) and forward to :meth:`open_from_disk`."""
        path = self.open_folder_dialog()
        if path is None:
            return
        self.open_from_disk(path)

    def open_folder_dialog(
        self, *, title: str | None = None
    ) -> Optional[Path]:
        """Soft-import :mod:`tkinter` and surface a native folder picker.

        Returns the chosen :class:`Path`, or ``None`` if the user
        cancelled or tkinter is unavailable. Headless tests bypass this
        and call :meth:`pick_path` / :meth:`open_from_disk` directly.
        """
        try:
            import tkinter as tk  # noqa: F401
            from tkinter import filedialog
        except Exception:
            return None
        try:
            chosen = filedialog.askdirectory(
                title=title or self.TITLE,
                mustexist=True,
            )
        except Exception:
            return None
        if not chosen:
            return None
        return Path(chosen)

    def _on_cancel_clicked(self, *_: Any) -> None:
        self._cancel_count += 1
        try:
            self._on_cancel()
        except Exception:
            pass
        self.close()

    def _resolve(self, project: Project) -> None:
        """Fire ``on_project_chosen`` + tear the panel down."""
        if not isinstance(project, Project):
            return
        self._chosen_count += 1
        self._last_chosen = project
        try:
            self._on_project_chosen(project)
        except Exception:
            pass
        self.close()

    # ------------------------------------------------------------------
    # Backwards-compat setters used by the older shell wiring.
    # ------------------------------------------------------------------

    def set_on_chosen(self, cb: Callable[[Project], None]) -> None:
        """Re-bind the chosen callback after construction."""
        self._on_project_chosen = validate_callable(
            "on_chosen", "NotebookProjectPicker.set_on_chosen", cb,
        )

    def set_on_cancelled(self, cb: Callable[[], None]) -> None:
        """Re-bind the cancel callback after construction."""
        self._on_cancel = validate_callable(
            "on_cancelled", "NotebookProjectPicker.set_on_cancelled", cb,
        )
