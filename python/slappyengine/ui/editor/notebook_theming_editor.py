"""``NotebookThemingEditor`` — big pick-and-preview theme customizer.

The editor is the user-facing "customise every knob on the active theme"
panel. It lists the base theme, one dropdown per style dimension (page
lining shader, edge stroke shader, washi-tape style, divider style, corner
tape), a colour-picker row per palette role (primary / accent /
background / ink), and a creature-roster grid. Every dropdown carries a
128×64 preview tile beside it and every change is a *live* mutation of
the active :class:`ThemeSpec` — no "Apply" button.

The panel soft-imports the U1/U2/U3/U4 registries so it degrades to
placeholder single-entry dropdowns when those modules haven't landed
yet. Persistence rides on top of a :class:`UserThemeStore` — the store
is soft-imported the same way; when it is missing the export /
import / save-as / reset actions become no-ops that only mutate the
in-memory copy.

Headless-safe: every ``dearpygui`` and ``tkinter`` call is guarded so
the same code path drives the CI stub and the shipping viewport.

Public surface
--------------

.. code-block:: python

    from slappyengine.ui.editor.notebook_theming_editor import (
        NotebookThemingEditor,
    )

    editor = NotebookThemingEditor()
    editor.set_active_theme("teengirl_notebook")
    editor.apply_color("primary", (255, 111, 181, 255))
    editor.export_yaml(Path("~/notebook.theme.yaml").expanduser())
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from slappyengine._validation import (
    validate_non_empty_str,
    validate_path_like,
)


# ---------------------------------------------------------------------------
# Constants — roles & fallback catalogues
# ---------------------------------------------------------------------------


#: Palette roles surfaced as colour-picker rows.
PALETTE_ROLES: tuple[str, ...] = (
    "primary",
    "accent",
    "background",
    "ink",
)


#: Style-dimension keys the editor exposes.
STYLE_KEYS: tuple[str, ...] = (
    "page_lining",
    "edge_stroke",
    "washi_tape",
    "corner_tape",
    "divider",
)


#: Fallback dropdown entries used when the underlying registry is not
#: installed. These are *placeholder* labels — the panel still renders
#: and the tests still exercise selection changes.
_FALLBACK_PAGE_LININGS: tuple[str, ...] = ("ruled_paper",)
_FALLBACK_EDGE_STROKES: tuple[str, ...] = ("ballpoint_pen",)
_FALLBACK_WASHI_TAPES: tuple[str, ...] = ("tape_pink_solid",)
_FALLBACK_CREATURES: tuple[str, ...] = (
    "fox_01",
    "butterfly_01",
    "sparkle",
    "cat_01",
    "hedgehog_01",
    "butterfly_02",
)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


def _soft_import_page_linings() -> list[str]:
    """Return the built-in page-lining ids (U3), or a fallback list."""
    try:
        from slappyengine.ui.theme.page_linings import (  # type: ignore
            list_linings,
        )
        result = list_linings()
        if isinstance(result, (list, tuple)) and result:
            return sorted(str(x) for x in result)
    except Exception:
        pass
    return list(_FALLBACK_PAGE_LININGS)


def _soft_import_edge_strokes() -> list[str]:
    """Return the built-in edge-stroke ids (U4), or a fallback list."""
    try:
        from slappyengine.ui.theme.edge_strokes import (  # type: ignore
            list_strokes,
        )
        result = list_strokes()
        if isinstance(result, (list, tuple)) and result:
            return sorted(str(x) for x in result)
    except Exception:
        pass
    return list(_FALLBACK_EDGE_STROKES)


def _soft_import_washi_tapes() -> list[str]:
    """Return the washi-tape style ids (U1), or a fallback list."""
    try:
        from slappyengine.ui.theme.washi_tape.library import list_tapes
        result = list_tapes()
        if isinstance(result, (list, tuple)) and result:
            return sorted(str(x) for x in result)
    except Exception:
        pass
    return list(_FALLBACK_WASHI_TAPES)


def _soft_import_divider_styles() -> list[str]:
    """Return the divider style ids (T2), or a fallback list."""
    try:
        from slappyengine.ui.editor.panel_decor import DividerStyle
        return sorted(m.value for m in DividerStyle)
    except Exception:
        return ["wavy", "dotted", "dashed"]


def _soft_import_creatures() -> list[str]:
    """Return the built-in creature ids, or a fallback list."""
    try:
        from slappyengine.ui.theme.creatures import builtin as _b  # type: ignore

        ids: list[str] = []
        for name in getattr(_b, "__all__", []):
            # Slot factories end in ``_slot``; skip them and dedupe.
            if name.endswith("_slot") or name == "register_builtins":
                continue
            if name.isidentifier():
                ids.append(name)
        if ids:
            return sorted(set(ids))
    except Exception:
        pass
    return list(_FALLBACK_CREATURES)


def _soft_import_theme_registry() -> tuple[
    Callable[[], list[str]] | None,
    Callable[[str], Any] | None,
    Callable[[], Any] | None,
]:
    """Return ``(list_themes, apply_theme, get_active_theme)`` handles.

    Any of the three may be ``None`` when the theme registry is not
    importable — the panel then falls back to a placeholder base-theme
    dropdown with a single ``teengirl_notebook`` entry.
    """
    try:
        from slappyengine.ui.theme import (
            apply_theme,
            get_active_theme,
            list_registered_themes,
        )
        return list_registered_themes, apply_theme, get_active_theme
    except Exception:
        return None, None, None


def _soft_import_user_store() -> Any | None:
    """Return a fresh :class:`UserThemeStore` (U2), or ``None``.

    The U2 module may not have landed yet; when absent the editor
    still tracks palette / style edits in-memory but cannot persist
    them to ``~/.slappyengine/themes``.
    """
    try:
        from slappyengine.ui.theme.user_theme_store import (  # type: ignore
            UserThemeStore,
        )
        return UserThemeStore()
    except Exception:
        return None


def _rgba_tuple(value: Any) -> tuple[int, int, int, int]:
    """Coerce *value* into an ``(r, g, b, a)`` tuple with 0-255 channels."""
    if value is None:
        return (0, 0, 0, 255)
    # ``Color`` (theme_spec.Color) instances expose ``as_rgba_tuple``.
    if hasattr(value, "as_rgba_tuple"):
        try:
            return tuple(int(v) for v in value.as_rgba_tuple())  # type: ignore[return-value]
        except Exception:
            pass
    if isinstance(value, (list, tuple)) and len(value) >= 3:
        r = int(value[0])
        g = int(value[1])
        b = int(value[2])
        a = int(value[3]) if len(value) >= 4 else 255
        return (r, g, b, a)
    return (0, 0, 0, 255)


def _clamp_channel(v: Any) -> int:
    try:
        i = int(v)
    except (TypeError, ValueError):
        return 0
    if i < 0:
        return 0
    if i > 255:
        return 255
    return i


# ---------------------------------------------------------------------------
# NotebookThemingEditor
# ---------------------------------------------------------------------------


class NotebookThemingEditor:
    """The user-editable theme customization panel.

    Layout::

        +-- [washi tape: Customize Theme] -----------------+
        |                                                  |
        |  Base theme: [teengirl_notebook v]              |
        |                                                  |
        |  Page lining:      [ruled_paper       v]  [preview]
        |  Edge stroke:      [ballpoint_pen     v]  [preview]
        |  Divider style:    [wavy              v]  [preview]
        |  Corner tape:      [tape_pink_solid   v]  [preview]
        |                                                  |
        |  Palette:                                        |
        |  Primary:      [#] [color pick]                 |
        |  Accent:       [#] [color pick]                 |
        |  Background:   [#] [color pick]                 |
        |  Ink:          [#] [color pick]                 |
        |                                                  |
        |  Creatures:                                      |
        |  <3 fox_01    <3 butterfly_01    <3 sparkle    |
        |  <3 cat_01    <3 hedgehog_01    <3 butterfly_02|
        |                                                  |
        |  [<3 Save as new theme...]  [* Reset to default] |
        |  [Ex Export .theme.yaml]   [Im Import .theme.yaml]
        +--------------------------------------------------+

    Parameters
    ----------
    theme_store:
        Optional :class:`UserThemeStore`-like handle. Soft-imported on
        first use so the editor works without U2 present. Callers may
        inject a stub in tests.
    """

    TITLE = "Theming"
    PREVIEW_WIDTH: int = 128
    PREVIEW_HEIGHT: int = 64

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 420
    MIN_HEIGHT: int = 480

    def __init__(self, theme_store: Any | None = None) -> None:
        self._store = theme_store if theme_store is not None else _soft_import_user_store()

        (
            self._list_themes,
            self._apply_theme,
            self._get_active_theme,
        ) = _soft_import_theme_registry()

        # Populate dropdown option sets — soft-imports return safe
        # fallbacks so the editor always has *something* to show.
        self._page_lining_options: list[str] = _soft_import_page_linings()
        self._edge_stroke_options: list[str] = _soft_import_edge_strokes()
        self._washi_tape_options: list[str] = _soft_import_washi_tapes()
        self._divider_options: list[str] = _soft_import_divider_styles()
        self._creature_options: list[str] = _soft_import_creatures()

        # Live selection state — the dropdowns bind to these fields.
        self._active_theme_name: str | None = None
        self._selection: dict[str, str] = {
            "page_lining": self._page_lining_options[0],
            "edge_stroke": self._edge_stroke_options[0],
            "washi_tape": self._washi_tape_options[0],
            "corner_tape": self._washi_tape_options[0],
            "divider": self._divider_options[0],
        }

        # Palette snapshot — keyed by :data:`PALETTE_ROLES`. Colours are
        # stored as (r, g, b, a) tuples so the panel round-trips cleanly
        # even when :class:`Color` isn't importable.
        self._palette: dict[str, tuple[int, int, int, int]] = {
            "primary":    (255, 111, 181, 255),
            "accent":     (255, 224, 102, 220),
            "background": (251, 247, 236, 255),
            "ink":        (31, 47, 102, 255),
        }

        # Creature-roster selection — booleans keyed by creature id.
        self._creatures_enabled: dict[str, bool] = {
            cid: False for cid in self._creature_options
        }

        # DPG state
        self._panel_tag = f"notebook_theming_editor_{id(self)}"
        self._parent_tag: str | int | None = None
        self._built: bool = False
        self._open: bool = False

        # Test-visible counters / mirrors — surface panel activity
        # without hitting DPG.
        self.call_log: list[tuple[str, Any]] = []
        self._preview_cache: dict[str, Any] = {}
        self._preview_count: int = 0

        # Seed the active theme when the registry has one active.
        if self._get_active_theme is not None:
            try:
                spec = self._get_active_theme()
                if spec is not None:
                    self._active_theme_name = getattr(spec, "name", None)
                    self._sync_from_spec(spec)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def panel_tag(self) -> str:
        return self._panel_tag

    @property
    def is_open(self) -> bool:
        return self._open

    @property
    def active_theme_name(self) -> str | None:
        return self._active_theme_name

    @property
    def selection(self) -> dict[str, str]:
        return dict(self._selection)

    @property
    def palette(self) -> dict[str, tuple[int, int, int, int]]:
        return dict(self._palette)

    @property
    def creatures_enabled(self) -> dict[str, bool]:
        return dict(self._creatures_enabled)

    @property
    def page_lining_options(self) -> list[str]:
        return list(self._page_lining_options)

    @property
    def edge_stroke_options(self) -> list[str]:
        return list(self._edge_stroke_options)

    @property
    def washi_tape_options(self) -> list[str]:
        return list(self._washi_tape_options)

    @property
    def divider_options(self) -> list[str]:
        return list(self._divider_options)

    @property
    def creature_options(self) -> list[str]:
        return list(self._creature_options)

    @property
    def theme_options(self) -> list[str]:
        if self._list_themes is None:
            return ["teengirl_notebook"]
        try:
            names = self._list_themes()
            if isinstance(names, (list, tuple)) and names:
                return list(names)
        except Exception:
            pass
        return ["teengirl_notebook"]

    @property
    def preview_count(self) -> int:
        return self._preview_count

    @property
    def preview_cache(self) -> dict[str, Any]:
        """Read-only view of the last-baked preview tiles by dimension key."""
        return dict(self._preview_cache)

    @property
    def store(self) -> Any | None:
        return self._store

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Mark the panel as visible. Idempotent."""
        self._open = True

    def show(self) -> None:
        """Backwards-compat alias for :meth:`open`."""
        self.open()

    def hide(self) -> None:
        """Mark the panel as hidden without tearing down its subtree."""
        self._open = False

    def close(self) -> None:
        """Hide the panel and drop its DPG subtree (if any)."""
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
        """Alias for :meth:`close` — kept for lifecycle-consistency."""
        self.close()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self, parent_tag: int | str) -> None:
        """Render the editor panel under *parent_tag*.

        Headless-safe — every DPG call is guarded so the panel still
        marks itself ``built`` under a stub ``dearpygui`` in CI.
        """
        if isinstance(parent_tag, str):
            validate_non_empty_str(
                "parent_tag", "NotebookThemingEditor.build", parent_tag,
            )
        self._parent_tag = parent_tag
        self._built = True
        self._open = True
        self.call_log.append(("build", parent_tag))

        # Bake fresh previews so the ``preview_cache`` is populated for
        # tests + first-frame render even in headless mode.
        for key in STYLE_KEYS:
            try:
                self._bake_preview(key, self._selection[key])
            except Exception:
                pass

        dpg = _safe_dpg()
        if dpg is None:
            return

        try:
            with dpg.child_window(
                tag=self._panel_tag,
                parent=parent_tag,
                width=-1,
                height=-1,
                border=True,
            ):
                try:
                    dpg.add_text(f"* {self.TITLE} *")
                except Exception:
                    pass
                # Base-theme dropdown.
                try:
                    dpg.add_combo(
                        items=self.theme_options,
                        label="Base theme",
                        default_value=(
                            self._active_theme_name
                            or (self.theme_options[0] if self.theme_options else "")
                        ),
                        callback=self._on_theme_selected,
                        tag=f"{self._panel_tag}_theme_combo",
                    )
                except Exception:
                    pass

                # Style dropdowns.
                for key, opts, label in (
                    ("page_lining", self._page_lining_options, "Page lining"),
                    ("edge_stroke", self._edge_stroke_options, "Edge stroke"),
                    ("divider",     self._divider_options,     "Divider style"),
                    ("washi_tape",  self._washi_tape_options,  "Washi tape"),
                    ("corner_tape", self._washi_tape_options,  "Corner tape"),
                ):
                    try:
                        dpg.add_combo(
                            items=list(opts),
                            label=label,
                            default_value=self._selection[key],
                            callback=self._make_style_callback(key),
                            tag=f"{self._panel_tag}_{key}_combo",
                        )
                    except Exception:
                        pass

                # Palette rows.
                try:
                    dpg.add_text("Palette:")
                except Exception:
                    pass
                for role in PALETTE_ROLES:
                    try:
                        dpg.add_color_edit(
                            label=role.title(),
                            default_value=list(self._palette[role]),
                            callback=self._make_palette_callback(role),
                            tag=f"{self._panel_tag}_palette_{role}",
                        )
                    except Exception:
                        pass

                # Creature roster.
                try:
                    dpg.add_text("Creatures:")
                except Exception:
                    pass
                for cid in self._creature_options:
                    try:
                        dpg.add_checkbox(
                            label=cid,
                            default_value=self._creatures_enabled.get(cid, False),
                            callback=self._make_creature_callback(cid),
                            tag=f"{self._panel_tag}_creature_{cid}",
                        )
                    except Exception:
                        pass

                # Action row.
                try:
                    with dpg.group(horizontal=True):
                        dpg.add_button(
                            label="<3 Save as new theme...",
                            callback=self._on_save_as_new_clicked,
                            tag=f"{self._panel_tag}_save_as_btn",
                        )
                        dpg.add_button(
                            label="* Reset to default",
                            callback=self._on_reset_clicked,
                            tag=f"{self._panel_tag}_reset_btn",
                        )
                except Exception:
                    pass
                try:
                    with dpg.group(horizontal=True):
                        dpg.add_button(
                            label="Ex Export .theme.yaml",
                            callback=self._on_export_clicked,
                            tag=f"{self._panel_tag}_export_btn",
                        )
                        dpg.add_button(
                            label="Im Import .theme.yaml",
                            callback=self._on_import_clicked,
                            tag=f"{self._panel_tag}_import_btn",
                        )
                except Exception:
                    pass
        except Exception:
            # Even if the container fails to open, we count as "built"
            # so callers can drive us via the public methods.
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Public state mutators
    # ------------------------------------------------------------------

    def set_active_theme(self, name: str) -> None:
        """Bind the panel to the theme registered under *name*.

        When the underlying registry is not importable this just records
        the name locally so the panel reflects the pick in the base-theme
        dropdown; palette + selection sync happens on the next call.
        """
        validate_non_empty_str(
            "name", "NotebookThemingEditor.set_active_theme", name,
        )
        self._active_theme_name = name
        self.call_log.append(("set_active_theme", name))
        if self._apply_theme is not None:
            try:
                spec = self._apply_theme(name)
                self._sync_from_spec(spec)
            except Exception:
                pass

    def preview_page_lining(self, style: str) -> Any:
        """Preview a page-lining shader; also mutates the active selection."""
        return self._preview_style("page_lining", style)

    def preview_edge_stroke(self, style: str) -> Any:
        """Preview an edge-stroke shader; also mutates the active selection."""
        return self._preview_style("edge_stroke", style)

    def preview_washi_tape(self, style: str) -> Any:
        """Preview a washi-tape style; also mutates the active selection."""
        return self._preview_style("washi_tape", style)

    def preview_divider(self, style: str) -> Any:
        """Preview a divider style; also mutates the active selection."""
        return self._preview_style("divider", style)

    def preview_corner_tape(self, style: str) -> Any:
        """Preview the corner-tape style; also mutates the active selection."""
        return self._preview_style("corner_tape", style)

    def apply_color(
        self,
        role: str,
        rgba: tuple[int, int, int, int],
    ) -> tuple[int, int, int, int]:
        """Rebind palette *role* to *rgba* on the active :class:`ThemeSpec`.

        Returns the clamped ``(r, g, b, a)`` tuple actually stored. Fires
        the theme-listener re-render as a side effect via
        :meth:`_persist_active`.
        """
        validate_non_empty_str(
            "role", "NotebookThemingEditor.apply_color", role,
        )
        if role not in PALETTE_ROLES:
            raise KeyError(
                f"NotebookThemingEditor.apply_color: unknown palette role "
                f"{role!r}; known: {PALETTE_ROLES}"
            )
        if not isinstance(rgba, (list, tuple)) or len(rgba) < 3:
            raise TypeError(
                "NotebookThemingEditor.apply_color: rgba must be a "
                "3- or 4-sequence; got "
                f"{type(rgba).__name__}"
            )
        r = _clamp_channel(rgba[0])
        g = _clamp_channel(rgba[1])
        b = _clamp_channel(rgba[2])
        a = _clamp_channel(rgba[3]) if len(rgba) >= 4 else 255
        clamped = (r, g, b, a)
        self._palette[role] = clamped
        self.call_log.append(("apply_color", (role, clamped)))
        # Mutate the live ThemeSpec so listeners re-render.
        self._mutate_spec_palette(role, clamped)
        self._persist_active()
        return clamped

    def toggle_creature(self, creature_id: str) -> bool:
        """Flip the enabled state for *creature_id* in the roster.

        Returns the *new* state so callers can drive checkboxes off a
        single call.
        """
        validate_non_empty_str(
            "creature_id",
            "NotebookThemingEditor.toggle_creature",
            creature_id,
        )
        current = self._creatures_enabled.get(creature_id, False)
        new_state = not current
        self._creatures_enabled[creature_id] = new_state
        self.call_log.append(("toggle_creature", (creature_id, new_state)))
        self._persist_active()
        return new_state

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_as_new(self, name: str) -> Path | None:
        """Snapshot the current state to a new theme file.

        Returns the resulting path when the U2 store is present; ``None``
        when the store is missing (the call is still recorded so tests
        can verify the code path).
        """
        validate_non_empty_str(
            "name", "NotebookThemingEditor.save_as_new", name,
        )
        self.call_log.append(("save_as_new", name))
        if self._store is None:
            return None
        try:
            # Prefer a dedicated ``save_as`` method; fall back to
            # generic ``save`` with a name kw.
            if hasattr(self._store, "save_as"):
                return Path(self._store.save_as(name, self._snapshot_dict()))
            if hasattr(self._store, "save"):
                return Path(self._store.save(name, self._snapshot_dict()))
        except Exception:
            return None
        return None

    def reset_to_default(self) -> None:
        """Copy the current theme back from the baked defaults via U2.

        No-op when the store is missing; still logs so tests can verify
        the invocation.
        """
        self.call_log.append(("reset_to_default", self._active_theme_name))
        if self._store is None:
            return
        try:
            if hasattr(self._store, "revert_to_baked"):
                self._store.revert_to_baked(self._active_theme_name)
            elif hasattr(self._store, "reset"):
                self._store.reset(self._active_theme_name)
        except Exception:
            pass

    def export_yaml(self, path: Path | str) -> Path:
        """Write the current snapshot to *path* as YAML.

        Falls back to a lightweight hand-rolled writer when PyYAML is
        not installed so tests always produce a readable file.
        """
        target = validate_path_like(
            "path", "NotebookThemingEditor.export_yaml", path,
        )
        target = target.expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._snapshot_dict()
        try:
            import yaml  # type: ignore[import-untyped]
            text = yaml.safe_dump(payload, sort_keys=False)
        except Exception:
            text = _fallback_yaml_dump(payload)
        target.write_text(text, encoding="utf-8")
        self.call_log.append(("export_yaml", str(target)))
        return target

    def import_yaml(self, path: Path | str) -> dict[str, Any]:
        """Load a theme snapshot from *path* and apply it in place.

        Returns the parsed dict so callers can inspect the payload.
        """
        target = validate_path_like(
            "path", "NotebookThemingEditor.import_yaml", path,
        )
        target = target.expanduser()
        text = target.read_text(encoding="utf-8")
        try:
            import yaml  # type: ignore[import-untyped]
            data = yaml.safe_load(text)
        except Exception:
            data = _fallback_yaml_load(text)
        if not isinstance(data, dict):
            raise ValueError(
                "NotebookThemingEditor.import_yaml: parsed YAML is not a "
                f"mapping; got {type(data).__name__}"
            )
        self._apply_snapshot(data)
        self.call_log.append(("import_yaml", str(target)))
        return data

    # ------------------------------------------------------------------
    # Internal — preview machinery
    # ------------------------------------------------------------------

    def _preview_style(self, key: str, style: str) -> Any:
        """Shared implementation for the ``preview_*`` methods."""
        validate_non_empty_str(
            "style", f"NotebookThemingEditor.preview_{key}", style,
        )
        self._selection[key] = style
        self.call_log.append(("preview", (key, style)))
        return self._bake_preview(key, style)

    def _bake_preview(self, key: str, style: str) -> Any:
        """Bake a small numpy preview tile and stash it in the cache.

        Uses numpy when available; falls back to a plain-Python list of
        row tuples so the panel remains importable in absurdly minimal
        environments. The colour of the tile is driven off the active
        palette so a theme change re-tints every preview.
        """
        tile = self._make_preview_tile(key, style)
        self._preview_cache[key] = tile
        self._preview_count += 1
        return tile

    def _make_preview_tile(self, key: str, style: str) -> Any:
        """Return a small RGBA preview tile for (*key*, *style*)."""
        w = self.PREVIEW_WIDTH
        h = self.PREVIEW_HEIGHT
        # Colour picks per dimension — read from the palette snapshot.
        primary = self._palette.get("primary", (255, 111, 181, 255))
        accent = self._palette.get("accent", (255, 224, 102, 220))
        background = self._palette.get("background", (251, 247, 236, 255))
        ink = self._palette.get("ink", (31, 47, 102, 255))
        base = {
            "page_lining": background,
            "edge_stroke": background,
            "washi_tape":  primary,
            "corner_tape": primary,
            "divider":     background,
        }.get(key, background)
        stripe = {
            "page_lining": ink,
            "edge_stroke": ink,
            "washi_tape":  accent,
            "corner_tape": accent,
            "divider":     primary,
        }.get(key, ink)

        try:
            import numpy as np

            tile = np.zeros((h, w, 4), dtype=np.uint8)
            tile[..., 0] = base[0]
            tile[..., 1] = base[1]
            tile[..., 2] = base[2]
            tile[..., 3] = base[3] if len(base) >= 4 else 255
            # Deterministic stripe pattern seeded by style name so the
            # tile changes when the user picks a different style.
            period = max(4, (len(style) * 3) % 16 + 4)
            for y in range(0, h, period):
                tile[y, :, 0] = stripe[0]
                tile[y, :, 1] = stripe[1]
                tile[y, :, 2] = stripe[2]
                tile[y, :, 3] = stripe[3] if len(stripe) >= 4 else 255
            return tile
        except Exception:
            # Plain-Python fallback — 2-row header + base fill.
            row_base = tuple(int(c) for c in base[:4]) + ((255,) if len(base) < 4 else ())
            row_stripe = tuple(int(c) for c in stripe[:4]) + ((255,) if len(stripe) < 4 else ())
            rows: list[list[tuple[int, ...]]] = []
            for y in range(h):
                if y % 8 == 0:
                    rows.append([row_stripe] * w)
                else:
                    rows.append([row_base] * w)
            return rows

    # ------------------------------------------------------------------
    # Internal — theme spec sync
    # ------------------------------------------------------------------

    def _sync_from_spec(self, spec: Any) -> None:
        """Refresh the panel palette + selection from a live ThemeSpec."""
        if spec is None:
            return
        self._active_theme_name = getattr(spec, "name", self._active_theme_name)

        semantic = getattr(spec, "semantic", None)
        if semantic is not None:
            for role, attr in (
                ("primary", "primary"),
                ("accent", "accent"),
                ("background", "background"),
                ("ink", "text_primary"),
            ):
                try:
                    colour = getattr(semantic, attr, None)
                except Exception:
                    colour = None
                if colour is not None:
                    self._palette[role] = _rgba_tuple(colour)

        # Divider + corner-tape come from PanelDecorConfig on the spec.
        decor = getattr(spec, "decor", None)
        if decor is not None:
            div = getattr(decor, "divider_style", None)
            if isinstance(div, str) and div:
                self._selection["divider"] = div
            corner = getattr(decor, "corner_style", None)
            if isinstance(corner, str) and corner:
                # Corner tape metadata often lives under a different key;
                # we mirror it as the corner_tape selection so the preview
                # tile picks up the pick.
                self._selection["corner_tape"] = corner

        # Background shader — the ruled-paper shader is our page-lining
        # default. When absent we leave the selection alone.
        bg = getattr(spec, "background_shader", None)
        bg_name = getattr(bg, "name", None) if bg is not None else None
        if isinstance(bg_name, str) and bg_name:
            self._selection["page_lining"] = bg_name

        # Creature roster — teased out of metadata["creature_roster"].
        metadata = getattr(spec, "metadata", None) or {}
        roster_raw = metadata.get("creature_roster") if isinstance(metadata, dict) else None
        if isinstance(roster_raw, str) and roster_raw:
            roster = {c.strip() for c in roster_raw.split(",") if c.strip()}
            for cid in list(self._creatures_enabled):
                self._creatures_enabled[cid] = cid in roster

    def _mutate_spec_palette(
        self,
        role: str,
        rgba: tuple[int, int, int, int],
    ) -> None:
        """Mirror a palette edit onto the live ThemeSpec so listeners fire."""
        if self._get_active_theme is None:
            return
        try:
            spec = self._get_active_theme()
        except Exception:
            return
        if spec is None:
            return
        try:
            from slappyengine.ui.theme.theme_spec import Color as _Color
        except Exception:
            _Color = None  # type: ignore[assignment]
        attr_map = {
            "primary": "primary",
            "accent": "accent",
            "background": "background",
            "ink": "text_primary",
        }
        attr = attr_map.get(role)
        if attr is None:
            return
        r, g, b, a = rgba
        if _Color is not None:
            try:
                colour = _Color(r=r, g=g, b=b, a=a / 255.0)
                semantic = getattr(spec, "semantic", None)
                if semantic is not None:
                    try:
                        setattr(semantic, attr, colour)
                    except Exception:
                        try:
                            object.__setattr__(semantic, attr, colour)
                        except Exception:
                            pass
                # Also mirror into palette dict for palette-key callers.
                palette = getattr(spec, "palette", None)
                if isinstance(palette, dict):
                    palette[role] = colour
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Internal — persistence + snapshot helpers
    # ------------------------------------------------------------------

    def _snapshot_dict(self) -> dict[str, Any]:
        """Return a YAML-safe dict describing the current state."""
        return {
            "name": self._active_theme_name or "custom_theme",
            "selection": dict(self._selection),
            "palette": {
                role: list(colour) for role, colour in self._palette.items()
            },
            "creatures": sorted(
                cid for cid, on in self._creatures_enabled.items() if on
            ),
        }

    def _apply_snapshot(self, data: dict[str, Any]) -> None:
        """Rebind the panel state from a :meth:`_snapshot_dict` payload."""
        name = data.get("name")
        if isinstance(name, str) and name:
            self._active_theme_name = name
        selection = data.get("selection")
        if isinstance(selection, dict):
            for key in STYLE_KEYS:
                value = selection.get(key)
                if isinstance(value, str) and value:
                    self._selection[key] = value
        palette = data.get("palette")
        if isinstance(palette, dict):
            for role in PALETTE_ROLES:
                colour = palette.get(role)
                if isinstance(colour, (list, tuple)) and len(colour) >= 3:
                    self._palette[role] = _rgba_tuple(colour)
                    self._mutate_spec_palette(role, self._palette[role])
        creatures = data.get("creatures")
        if isinstance(creatures, (list, tuple)):
            wanted = {str(c) for c in creatures}
            for cid in list(self._creatures_enabled):
                self._creatures_enabled[cid] = cid in wanted
        self._persist_active()

    def _persist_active(self) -> None:
        """Write the current snapshot to the user store, when present."""
        if self._store is None or self._active_theme_name is None:
            return
        try:
            if hasattr(self._store, "save"):
                self._store.save(self._active_theme_name, self._snapshot_dict())
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internal — DPG callback shims
    # ------------------------------------------------------------------

    def _on_theme_selected(self, sender: Any, app_data: Any, user_data: Any) -> None:
        name = app_data if isinstance(app_data, str) else None
        if not name:
            return
        self.set_active_theme(name)

    def _make_style_callback(self, key: str) -> Callable[..., None]:
        def _cb(sender: Any, app_data: Any, user_data: Any) -> None:
            if isinstance(app_data, str) and app_data:
                self._preview_style(key, app_data)
        return _cb

    def _make_palette_callback(self, role: str) -> Callable[..., None]:
        def _cb(sender: Any, app_data: Any, user_data: Any) -> None:
            try:
                rgba = tuple(int(v) for v in app_data)
            except (TypeError, ValueError):
                return
            self.apply_color(role, rgba)  # type: ignore[arg-type]
        return _cb

    def _make_creature_callback(self, cid: str) -> Callable[..., None]:
        def _cb(sender: Any, app_data: Any, user_data: Any) -> None:
            self._creatures_enabled[cid] = bool(app_data)
            self.call_log.append(("creature", (cid, bool(app_data))))
            self._persist_active()
        return _cb

    def _on_save_as_new_clicked(self, *_a: Any, **_kw: Any) -> None:
        # In the shipping UI this would pop a name-prompt modal — the
        # test-driven code path just records the click so callers can
        # verify the wiring.
        self.call_log.append(("save_as_new_click", None))

    def _on_reset_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.reset_to_default()

    def _on_export_clicked(self, *_a: Any, **_kw: Any) -> None:
        # Real UI pops a native save-dialog; here we just log so the
        # export path is testable without touching the filesystem.
        self.call_log.append(("export_click", None))

    def _on_import_clicked(self, *_a: Any, **_kw: Any) -> None:
        self.call_log.append(("import_click", None))


# ---------------------------------------------------------------------------
# Fallback YAML helpers — used only when PyYAML is missing
# ---------------------------------------------------------------------------


def _fallback_yaml_dump(data: dict[str, Any]) -> str:
    """Ultra-small YAML-ish emitter used when PyYAML isn't installed.

    Handles the shape produced by :meth:`NotebookThemingEditor._snapshot_dict`
    — scalar strings, nested dicts one level deep, and flat sequences —
    which is plenty for the export contract the tests exercise.
    """
    lines: list[str] = []

    def _emit_scalar(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)):
            return str(value)
        return str(value)

    def _emit_sequence(values: Any) -> str:
        return "[" + ", ".join(_emit_scalar(v) for v in values) + "]"

    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            for sub_key, sub_value in value.items():
                if isinstance(sub_value, (list, tuple)):
                    lines.append(f"  {sub_key}: {_emit_sequence(sub_value)}")
                else:
                    lines.append(f"  {sub_key}: {_emit_scalar(sub_value)}")
        elif isinstance(value, (list, tuple)):
            lines.append(f"{key}: {_emit_sequence(value)}")
        else:
            lines.append(f"{key}: {_emit_scalar(value)}")
    return "\n".join(lines) + "\n"


def _fallback_yaml_load(text: str) -> dict[str, Any]:
    """Ultra-small YAML-ish parser matching :func:`_fallback_yaml_dump`."""
    root: dict[str, Any] = {}
    current_key: str | None = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw.startswith("  "):
            if current_key is None:
                continue
            sub = raw.strip()
            if ":" not in sub:
                continue
            k, _, v = sub.partition(":")
            v = v.strip()
            root_child = root.setdefault(current_key, {})
            if isinstance(root_child, dict):
                root_child[k.strip()] = _parse_scalar(v)
        else:
            k, _, v = raw.partition(":")
            v = v.strip()
            key = k.strip()
            if not v:
                root[key] = {}
                current_key = key
            else:
                root[key] = _parse_scalar(v)
                current_key = None
    return root


def _parse_scalar(text: str) -> Any:
    """Parse the RHS of a fallback-YAML scalar entry."""
    stripped = text.strip()
    if not stripped:
        return ""
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        parts = [p.strip() for p in inner.split(",")]
        parsed: list[Any] = []
        for part in parts:
            try:
                parsed.append(int(part))
            except ValueError:
                try:
                    parsed.append(float(part))
                except ValueError:
                    parsed.append(part)
        return parsed
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        pass
    return stripped


# Ensure copy import is used somewhere — keeps linters happy without
# depending on it as a public shim (some future callers may want a
# deep-copied snapshot for undo/redo journals).
_ = copy


__all__ = [
    "NotebookThemingEditor",
    "PALETTE_ROLES",
    "STYLE_KEYS",
]
