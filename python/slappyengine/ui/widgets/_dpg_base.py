"""Shared scaffolding for notebook-themed Dear PyGui widgets.

Every notebook widget follows the same protocol:

* Construct with the user-supplied label / value / callback.
* Snapshot the active :class:`NotebookTheme` once at construction time.
* Optionally call :meth:`build` to materialise the DPG tree under a parent
  tag.  ``build`` is the only method that imports ``dearpygui``.
* Optionally re-bind the snapshot via :meth:`refresh_theme` when
  ``set_active_theme`` is called after construction.

The class is intentionally tiny — it only owns the theme snapshot, a
build flag, and a parent-tag stash.  Concrete widgets layer on top.
"""
from __future__ import annotations

from typing import Any

from slappyengine.ui.widgets.notebook_theme import (
    NotebookTheme,
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)


class _NotebookWidget:
    """Base for every notebook-flavoured widget primitive."""

    def __init__(self) -> None:
        self._theme: NotebookTheme = resolve_theme()
        self._built: bool = False
        self._parent_tag: str | int | None = None
        self._root_tag: str | None = None
        # Auto-track theme changes so widgets restyle without manual rebind.
        register_theme_listener(self._on_theme_changed)

    # ------------------------------------------------------------------
    # Theme handling
    # ------------------------------------------------------------------

    def _on_theme_changed(self, theme: NotebookTheme | None) -> None:
        """Listener fired when ``set_active_theme`` is called.

        Widgets always re-bind their cached palette / nine-slice slots so
        properties like ``accent_color`` track the active theme even before
        :meth:`build` has been called.  Subclasses that need to push the
        new palette into DPG should override :meth:`refresh_theme` and
        check ``self._built`` before issuing DPG calls.
        """
        self._theme = resolve_theme()
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-apply the active theme.  Subclasses override when needed."""
        self._theme = resolve_theme()

    @property
    def theme(self) -> NotebookTheme:
        """Return the theme snapshot the widget was last bound against."""
        return self._theme

    @property
    def root_tag(self) -> str | None:
        """Return the root DPG tag used by :meth:`build` (or ``None``)."""
        return self._root_tag

    # ------------------------------------------------------------------
    # Build / teardown
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Materialise the widget tree under *parent_tag*.

        Subclasses override and call ``self._mark_built(parent_tag, root)``
        once the root group has been created.
        """
        raise NotImplementedError

    def _mark_built(self, parent_tag: str | int, root_tag: str | None) -> None:
        self._parent_tag = parent_tag
        self._root_tag = root_tag
        self._built = True

    def destroy(self) -> None:
        """Tear down the widget — delete its DPG subtree and drop listeners."""
        unregister_theme_listener(self._on_theme_changed)
        if self._built and self._root_tag is not None:
            try:
                import dearpygui.dearpygui as dpg

                if dpg.does_item_exist(self._root_tag):
                    dpg.delete_item(self._root_tag)
            except Exception:
                # Headless / missing dearpygui — nothing to delete.
                pass
        self._built = False
        self._root_tag = None
        self._parent_tag = None

    # ------------------------------------------------------------------
    # Helpers shared by every widget
    # ------------------------------------------------------------------

    def _safe_dpg(self) -> Any | None:
        """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
        try:
            import dearpygui.dearpygui as dpg

            return dpg
        except Exception:
            return None
