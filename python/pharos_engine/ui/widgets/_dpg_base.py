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

from pharos_engine.ui.widgets.notebook_theme import (
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
        self._enabled: bool = True
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
        # Follow the global registry unless the widget has been pinned to
        # a specific theme via ``set_theme``.
        self._theme = resolve_theme()
        self.refresh_theme()

    def refresh_theme(self) -> None:
        """Re-apply the currently bound theme.

        Subclasses override to re-cache palette slots.  This method must
        *not* re-resolve the theme — callers (either the global listener
        or :meth:`set_theme`) update ``self._theme`` before invoking us.
        """
        pass

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

    def mount(self, parent_tag: str | int) -> None:
        """Alias for :meth:`build` — the newer notebook widgets prefer this name."""
        self.build(parent_tag)

    # ------------------------------------------------------------------
    # Enabled state
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        """Return whether the widget is currently interactable."""
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Toggle the widget's interactable state.

        The base implementation caches the flag and, when built, tries to
        push it into DPG via ``dpg.configure_item(root, enabled=...)`` /
        ``dpg.disable_item`` / ``dpg.enable_item``.  Subclasses override
        when they need to disable multiple sub-items.
        """
        self._enabled = bool(enabled)
        if not self._built or self._root_tag is None:
            return
        dpg = self._safe_dpg()
        if dpg is None:
            return
        try:
            if self._enabled:
                enable = getattr(dpg, "enable_item", None)
                if callable(enable):
                    enable(self._root_tag)
                else:
                    dpg.configure_item(self._root_tag, enabled=True)
            else:
                disable = getattr(dpg, "disable_item", None)
                if callable(disable):
                    disable(self._root_tag)
                else:
                    dpg.configure_item(self._root_tag, enabled=False)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Theme override
    # ------------------------------------------------------------------

    def set_theme(self, theme: NotebookTheme | None) -> None:
        """Rebind this widget against *theme* (or the fallback when ``None``).

        Unlike :func:`set_active_theme`, this only re-styles *this* widget
        instance — the global registry is untouched.  Widgets whose cached
        palette entries derive from the fallback / active theme are
        refreshed via :meth:`refresh_theme`.
        """
        from pharos_engine.ui.widgets.notebook_theme import (
            NotebookTheme as _NT,
            resolve_theme as _resolve,
        )

        if theme is None:
            self._theme = _resolve()
        elif isinstance(theme, _NT):
            self._theme = theme
        else:
            raise TypeError(
                "set_theme: theme must be NotebookTheme or None; "
                f"got {type(theme).__name__}"
            )
        self.refresh_theme()

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
