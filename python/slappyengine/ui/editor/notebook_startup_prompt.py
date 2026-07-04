"""``NotebookStartupPrompt`` — "Welcome back!" modal shown on editor boot.

If the user has one or more registered projects (per
:class:`slappyengine.project_registry.ProjectRegistry`), the editor
pops this modal on launch instead of dropping straight to an empty
scene. Layout:

* **Welcome back!** heading (diary-styled accent colour).
* A list of the top 5 recent projects — click a row to pick it.
* **New Project…** button — asks the caller to run its own scaffold flow.
* **Skip (empty editor)** button — dismiss without picking anything.

The prompt does *not* touch the filesystem itself — it just returns
the chosen path via :meth:`resolve` (or ``None`` if skipped). The
caller wires that path into the editor's scene loader.

Headless-safe — every DPG call is guarded so the prompt imports +
builds cleanly under a stub ``dearpygui`` in CI.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_positive_int,
)
from slappyengine.project_registry import (
    ProjectRegistry,
    RegisteredProject,
    get_default_registry,
)
from slappyengine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)


__all__ = [
    "NotebookStartupPrompt",
]


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]

        return dpg
    except Exception:
        return None


class NotebookStartupPrompt:
    """Modal shown on editor boot when the registry has recent projects.

    Parameters
    ----------
    on_project_chosen:
        Callback invoked with the chosen :class:`RegisteredProject`
        when the user clicks a recent row. Optional; defaults to a
        no-op so callers can drive the prompt purely via
        :meth:`chosen_path` after the fact.
    on_new_project:
        Zero-arg callback fired when the user clicks **New Project…**.
        The parent is expected to run its own scaffolding UI.
    on_skip:
        Zero-arg callback fired when the user clicks **Skip
        (empty editor)**. Parents wire this to "load blank scene".
    registry:
        Optional :class:`ProjectRegistry`. Defaults to
        :func:`get_default_registry`.
    limit:
        Maximum recent rows to show. Defaults to 5. Must be ≥ 1.
    """

    TITLE = "Welcome back!"
    WIDTH = 480
    HEIGHT = 380

    MIN_WIDTH: int = 420
    MIN_HEIGHT: int = 320

    def __init__(
        self,
        on_project_chosen: Callable[[RegisteredProject], None] | None = None,
        on_new_project: Callable[[], None] | None = None,
        on_skip: Callable[[], None] | None = None,
        registry: ProjectRegistry | None = None,
        limit: int = 5,
    ) -> None:
        self._on_project_chosen = validate_callable(
            "on_project_chosen",
            "NotebookStartupPrompt",
            on_project_chosen if on_project_chosen is not None else (lambda _p: None),
        )
        self._on_new_project = validate_callable(
            "on_new_project",
            "NotebookStartupPrompt",
            on_new_project if on_new_project is not None else (lambda: None),
        )
        self._on_skip = validate_callable(
            "on_skip",
            "NotebookStartupPrompt",
            on_skip if on_skip is not None else (lambda: None),
        )

        if registry is None:
            registry = get_default_registry()
        if not isinstance(registry, ProjectRegistry):
            raise TypeError(
                "NotebookStartupPrompt: registry must be a "
                f"ProjectRegistry; got {type(registry).__name__}"
            )
        self._registry = registry

        self._limit = validate_positive_int(
            "limit", "NotebookStartupPrompt", limit,
        )

        self._theme = resolve_theme()
        register_theme_listener(self._on_theme_changed)

        self._panel_tag = f"notebook_startup_prompt_{id(self)}"
        self._list_tag = f"{self._panel_tag}_list"
        self._new_btn_tag = f"{self._panel_tag}_new_btn"
        self._skip_btn_tag = f"{self._panel_tag}_skip_btn"

        self._built: bool = False
        self._open: bool = False
        self._parent_tag: str | int | None = None
        self._displayed: list[RegisteredProject] = []

        self._chosen_path: Optional[Path] = None
        self._chosen_project: Optional[RegisteredProject] = None
        self._skipped: bool = False
        self._chose_new: bool = False

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
    def new_btn_tag(self) -> str:
        return self._new_btn_tag

    @property
    def skip_btn_tag(self) -> str:
        return self._skip_btn_tag

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def displayed(self) -> list[RegisteredProject]:
        """Snapshot of the projects rendered at the last :meth:`refresh`."""
        return list(self._displayed)

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def is_built(self) -> bool:
        return self._built

    @property
    def chosen_path(self) -> Optional[Path]:
        """The path the user picked, or ``None`` if skipped / unresolved."""
        return self._chosen_path

    @property
    def chosen_project(self) -> Optional[RegisteredProject]:
        return self._chosen_project

    @property
    def skipped(self) -> bool:
        return self._skipped

    @property
    def chose_new(self) -> bool:
        return self._chose_new

    # ── Class helper ─────────────────────────────────────────────────

    @classmethod
    def should_show(cls, registry: ProjectRegistry | None = None) -> bool:
        """Return ``True`` when *registry* has at least one recent entry.

        Convenience for the editor's boot path — the shell wires this
        to decide whether to instantiate + open the prompt.
        """
        if registry is None:
            registry = get_default_registry()
        try:
            return bool(registry.list_recent(limit=1))
        except Exception:
            return False

    # ── Lifecycle ────────────────────────────────────────────────────

    def open(self) -> None:
        """Mark the prompt as visible. Idempotent."""
        self._open = True

    def close(self) -> None:
        """Hide the prompt and tear down its DPG subtree (if any)."""
        self._open = False
        if not self._built:
            return
        dpg = _safe_dpg()
        if dpg is not None:
            try:
                if dpg.does_item_exist(self._panel_tag):
                    dpg.delete_item(self._panel_tag)
            except Exception:
                pass
        self._built = False

    def destroy(self) -> None:
        """Drop the theme listener + close the modal."""
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self.close()

    # ── Build / refresh ──────────────────────────────────────────────

    def build(self, parent_tag: int | str) -> None:
        """Render the prompt under *parent_tag*. Headless-safe."""
        if isinstance(parent_tag, str):
            validate_non_empty_str(
                "parent_tag", "NotebookStartupPrompt.build", parent_tag,
            )
        self._parent_tag = parent_tag
        self._built = True
        self._open = True
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
                # Heading
                try:
                    dpg.add_text(
                        f"* {self.TITLE} *",
                        color=accent,
                        tag=f"{self._panel_tag}_title",
                    )
                except Exception:
                    pass
                try:
                    dpg.add_text(
                        "Pick up where you left off:",
                        color=ink,
                    )
                except Exception:
                    pass

                # Recent-projects list
                try:
                    with dpg.child_window(
                        tag=self._list_tag,
                        border=True,
                        height=200,
                    ):
                        self._build_rows(dpg, ink, accent)
                except Exception:
                    self._build_rows(dpg, ink, accent)

                # Doodle separator
                try:
                    dpg.add_text(
                        "~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~ ~",
                        color=washi,
                    )
                except Exception:
                    pass

                # Action buttons
                try:
                    with dpg.group(horizontal=True):
                        dpg.add_button(
                            label="<3 New Project...",
                            width=180,
                            height=32,
                            callback=self._on_new_clicked,
                            tag=self._new_btn_tag,
                        )
                        dpg.add_button(
                            label="Skip (empty editor)",
                            width=180,
                            height=32,
                            callback=self._on_skip_clicked,
                            tag=self._skip_btn_tag,
                        )
                except Exception:
                    # Fall back to flat buttons if ``group`` unsupported.
                    try:
                        dpg.add_button(
                            label="<3 New Project...",
                            width=180,
                            height=32,
                            callback=self._on_new_clicked,
                            tag=self._new_btn_tag,
                        )
                    except Exception:
                        pass
                    try:
                        dpg.add_button(
                            label="Skip (empty editor)",
                            width=180,
                            height=32,
                            callback=self._on_skip_clicked,
                            tag=self._skip_btn_tag,
                        )
                    except Exception:
                        pass
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
        if not self._displayed:
            try:
                dpg.add_text(
                    "No recent projects — start a new one!",
                    color=ink,
                    tag=f"{self._panel_tag}_empty",
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
        btn_tag = self._row_tag(project.name)
        label = f"* {project.name}  ({project.path})"
        try:
            dpg.add_button(
                label=label,
                width=-1,
                height=28,
                callback=(
                    lambda *_a, name=project.name: self._on_row_clicked(name)
                ),
                tag=btn_tag,
            )
        except Exception:
            pass

    def refresh(self) -> None:
        """Rebuild the recent-projects list. Headless-safe."""
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
        self._build_rows(dpg, ink, accent)

    def _refresh_snapshot(self) -> None:
        try:
            self._displayed = list(
                self._registry.list_recent(limit=self._limit)
            )
        except Exception:
            self._displayed = []

    # ── Callback shims ───────────────────────────────────────────────

    def _on_row_clicked(self, name: str) -> None:
        self.pick(name)

    def _on_new_clicked(self, *_: Any) -> None:
        self.trigger_new()

    def _on_skip_clicked(self, *_: Any) -> None:
        self.skip()

    # ── Test-facing action surface ───────────────────────────────────

    def pick(self, name: str) -> Optional[Path]:
        """Resolve the prompt to the project named *name*.

        Returns the chosen :class:`Path`, or ``None`` when the entry
        is no longer in the registry (dropped between refreshes).
        """
        validate_non_empty_str("name", "NotebookStartupPrompt.pick", name)
        project = self._registry.get(name)
        if project is None:
            return None
        self._chosen_project = project
        self._chosen_path = project.path
        try:
            self._on_project_chosen(project)
        except Exception:
            pass
        self.close()
        return project.path

    def skip(self) -> None:
        """Mark the prompt as skipped + fire the caller's ``on_skip``."""
        self._skipped = True
        self._chosen_path = None
        self._chosen_project = None
        try:
            self._on_skip()
        except Exception:
            pass
        self.close()

    def trigger_new(self) -> None:
        """Fire the caller's ``on_new_project`` + close the prompt."""
        self._chose_new = True
        try:
            self._on_new_project()
        except Exception:
            pass
        self.close()

    def resolve(self) -> Optional[Path]:
        """Return the chosen path, or ``None`` when skipped / unresolved."""
        return self._chosen_path

    def _row_tag(self, name: str) -> str:
        scrub = (
            name.replace(" ", "_")
            .replace("\\", "_")
            .replace("/", "_")
            .replace(":", "_")
        )
        return f"{self._panel_tag}_row_{scrub}"
