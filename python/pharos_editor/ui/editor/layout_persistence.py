"""Layout persistence — save/restore editor panel positions per project.

A small YAML-backed snapshot of every notebook panel's position / size /
visibility / docking / z-order. Stored at
``<project_root>/.pharos/layout.yaml`` so users get the same layout next
time they re-open a project, and so it can be ``.gitignore``-d at the
``.pharos/`` level without losing the rest of the project tree.

When no project is loaded (e.g. the very first launch before the project
picker runs), the persistence layer falls back to
``~/.pharos_engine/default_layout.yaml`` so the user's preferred chrome
still carries between sessions.

Schema
------

The YAML payload looks like::

    schema_version: 1
    theme: teengirl_notebook
    viewport_size: [1280, 800]
    panels:
      notebook_outliner:
        position: [0, 80]
        size: [260, 480]
        visible: true
        z_order: 0
        docked_to: left
      ...

Schema mismatches cause :meth:`LayoutPersistence.load` to return
``None``; the editor then falls back to whichever default layout it
was constructed with.

Headless safety
---------------

The whole module is Dear PyGui-free. ``snapshot_from_shell`` and
``apply_to_shell`` use ``getattr`` probes rather than DPG widget
queries, so tests can drive them against a bare ``EditorShell`` (no
viewport, no context).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from pharos_engine._validation import (
    validate_bool,
    validate_int,
    validate_non_empty_str,
    validate_non_negative_int,
    validate_positive_size_2tuple,
    validate_str,
)

if TYPE_CHECKING:
    from pharos_editor.ui.editor.shell import EditorShell


__all__ = [
    "PanelLayoutState",
    "EditorLayout",
    "LayoutPersistence",
    "SCHEMA_VERSION",
    "VALID_DOCK_SIDES",
]


#: Current on-disk schema version. Bump when the layout YAML shape
#: changes incompatibly; older files load as "missing" and fall back to
#: the default layout.
SCHEMA_VERSION: int = 1

#: Allowed values for :attr:`PanelLayoutState.docked_to`. The empty
#: string means "no docking opinion" — used by panels that float by
#: default but which we don't want to forbid restoring.
VALID_DOCK_SIDES: tuple[str, ...] = (
    "",
    "left",
    "right",
    "top",
    "bottom",
    "floating",
)


# ---------------------------------------------------------------------------
# PanelLayoutState
# ---------------------------------------------------------------------------


@dataclass
class PanelLayoutState:
    """Persisted state for a single editor panel.

    Parameters
    ----------
    panel_id:
        Stable identifier for the panel — matches the DPG tag used by
        the panel's ``build()`` (e.g. ``"notebook_outliner"``).
    position:
        ``(x, y)`` window-relative pixel position of the panel's top-left
        corner.
    size:
        ``(width, height)`` in pixels. Must be positive.
    visible:
        ``True`` iff the panel should be shown on layout apply.
    z_order:
        Stacking order — higher values draw on top. Non-negative ints.
    docked_to:
        Docking edge name. One of :data:`VALID_DOCK_SIDES`.
    """

    panel_id: str
    position: tuple[int, int]
    size: tuple[int, int]
    visible: bool = True
    z_order: int = 0
    docked_to: str = ""

    def __post_init__(self) -> None:
        """Validate every field at construction.

        Raises ``TypeError`` / ``ValueError`` on garbage input so callers
        can never round-trip a malformed layout to disk.
        """
        fn = "PanelLayoutState"
        self.panel_id = validate_non_empty_str("panel_id", fn, self.panel_id)
        # Position is "any two finite ints" — including negatives so an
        # off-screen floating panel still validates.
        if (
            not hasattr(self.position, "__len__")
            or len(self.position) != 2
            or isinstance(self.position, (str, bytes))
        ):
            raise ValueError(
                f"{fn}: position must be a 2-tuple of ints; got {self.position!r}"
            )
        px = validate_int("position[0]", fn, self.position[0])
        py = validate_int("position[1]", fn, self.position[1])
        self.position = (px, py)

        # Size must be positive — a zero-area panel is never sensible.
        self.size = validate_positive_size_2tuple("size", fn, self.size)

        self.visible = validate_bool("visible", fn, self.visible)
        self.z_order = validate_non_negative_int("z_order", fn, self.z_order)
        # ``docked_to`` accepts the empty string (canonical "no opinion").
        self.docked_to = validate_str("docked_to", fn, self.docked_to)
        if self.docked_to not in VALID_DOCK_SIDES:
            raise ValueError(
                f"{fn}: docked_to must be one of {VALID_DOCK_SIDES}; "
                f"got {self.docked_to!r}"
            )

    # ------------------------------------------------------------------
    # Dict <-> YAML conversion (no custom representers — primitives only)
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a YAML-safe dict snapshot.

        Tuples are unrolled to lists so ``yaml.safe_dump`` doesn't choke
        on the ``tuple`` type. The ``panel_id`` lives as the *key* of the
        outer ``panels`` mapping, so it's omitted from the per-panel body
        here.
        """
        return {
            "position": [int(self.position[0]), int(self.position[1])],
            "size": [int(self.size[0]), int(self.size[1])],
            "visible": bool(self.visible),
            "z_order": int(self.z_order),
            "docked_to": str(self.docked_to),
        }

    @classmethod
    def from_dict(cls, panel_id: str, data: dict) -> "PanelLayoutState":
        """Build a :class:`PanelLayoutState` from a YAML mapping.

        Unknown keys are ignored (forwards-compat). Missing optional
        keys fall back to dataclass defaults; ``position`` and ``size``
        are required.
        """
        if not isinstance(data, dict):
            raise TypeError(
                "PanelLayoutState.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        pos = data.get("position")
        sz = data.get("size")
        if pos is None or sz is None:
            raise KeyError(
                "PanelLayoutState.from_dict: 'position' and 'size' are required"
            )
        return cls(
            panel_id=panel_id,
            position=(int(pos[0]), int(pos[1])),
            size=(int(sz[0]), int(sz[1])),
            visible=bool(data.get("visible", True)),
            z_order=int(data.get("z_order", 0)),
            docked_to=str(data.get("docked_to", "")),
        )


# ---------------------------------------------------------------------------
# EditorLayout
# ---------------------------------------------------------------------------


@dataclass
class EditorLayout:
    """Complete editor layout snapshot.

    Parameters
    ----------
    schema_version:
        On-disk schema version. Defaults to :data:`SCHEMA_VERSION`.
    theme:
        Notebook-theme registry id used when the layout was captured.
        Restored on apply so colour palettes survive a project reload.
    viewport_size:
        Top-level window size at snapshot time. Used to normalise panel
        positions when restoring on a differently-sized display.
    panels:
        ``panel_id`` → :class:`PanelLayoutState` map.
    """

    schema_version: int = SCHEMA_VERSION
    theme: str = "teengirl_notebook"
    viewport_size: tuple[int, int] = (1280, 800)
    panels: dict[str, PanelLayoutState] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "EditorLayout"
        self.schema_version = validate_non_negative_int(
            "schema_version", fn, self.schema_version,
        )
        self.theme = validate_str("theme", fn, self.theme)
        self.viewport_size = validate_positive_size_2tuple(
            "viewport_size", fn, self.viewport_size,
        )
        if not isinstance(self.panels, dict):
            raise TypeError(
                f"{fn}: panels must be a dict; got {type(self.panels).__name__}"
            )
        # Permit the panels dict to hold either ``PanelLayoutState`` or
        # nested dict (for the dataclass-default convenience case where a
        # caller hands us a plain mapping). We coerce to ``PanelLayoutState``
        # so every member of ``self.panels`` is a validated dataclass.
        coerced: dict[str, PanelLayoutState] = {}
        for pid, state in self.panels.items():
            if isinstance(state, PanelLayoutState):
                if state.panel_id != pid:
                    # Keep the key authoritative.
                    state = PanelLayoutState(
                        panel_id=pid,
                        position=state.position,
                        size=state.size,
                        visible=state.visible,
                        z_order=state.z_order,
                        docked_to=state.docked_to,
                    )
                coerced[pid] = state
            elif isinstance(state, dict):
                coerced[pid] = PanelLayoutState.from_dict(pid, state)
            else:
                raise TypeError(
                    f"{fn}: panels[{pid!r}] must be PanelLayoutState or dict; "
                    f"got {type(state).__name__}"
                )
        self.panels = coerced

    # ------------------------------------------------------------------
    # Dict <-> YAML conversion
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a YAML-safe dict snapshot of the full layout."""
        return {
            "schema_version": int(self.schema_version),
            "theme": str(self.theme),
            "viewport_size": [
                int(self.viewport_size[0]),
                int(self.viewport_size[1]),
            ],
            "panels": {
                pid: state.to_dict() for pid, state in self.panels.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EditorLayout":
        """Build an :class:`EditorLayout` from a YAML mapping."""
        if not isinstance(data, dict):
            raise TypeError(
                "EditorLayout.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        vp = data.get("viewport_size", [1280, 800])
        panels_raw = data.get("panels", {}) or {}
        if not isinstance(panels_raw, dict):
            raise TypeError(
                "EditorLayout.from_dict: panels must be a mapping; "
                f"got {type(panels_raw).__name__}"
            )
        panels = {
            pid: PanelLayoutState.from_dict(pid, body)
            for pid, body in panels_raw.items()
        }
        return cls(
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
            theme=str(data.get("theme", "teengirl_notebook")),
            viewport_size=(int(vp[0]), int(vp[1])),
            panels=panels,
        )


# ---------------------------------------------------------------------------
# LayoutPersistence
# ---------------------------------------------------------------------------


class LayoutPersistence:
    """Saves and restores editor layout state per project.

    Parameters
    ----------
    project_root:
        Path to the active project's root directory. When ``None``, the
        persistence layer falls back to the user-wide
        ``~/.pharos_engine/default_layout.yaml`` file so the editor still
        remembers the user's preferred chrome between sessions before a
        project has been picked.

    The on-disk shape is documented at module level. The shell hooks
    ``snapshot_from_shell`` / ``apply_to_shell`` are the only methods
    that touch live panel objects; everything else is a pure file
    operation.
    """

    #: Hidden directory inside the project root that holds layout state.
    LAYOUT_DIR: str = ".pharos"

    #: Filename of the YAML snapshot.
    LAYOUT_FILE: str = "layout.yaml"

    #: Filename used when no project is loaded.
    FALLBACK_FILE: str = "default_layout.yaml"

    def __init__(self, project_root: Path | str | None = None) -> None:
        if project_root is None:
            self._project_root: Path | None = None
        else:
            self._project_root = Path(project_root)

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def get_file_path(self) -> Path:
        """Return the absolute path to the layout file.

        When a project root was supplied, returns
        ``<project>/.pharos/layout.yaml``. Otherwise falls back to
        ``~/.pharos_engine/default_layout.yaml``.
        """
        if self._project_root is not None:
            return (
                self._project_root / self.LAYOUT_DIR / self.LAYOUT_FILE
            )
        return Path.home() / ".pharos_engine" / self.FALLBACK_FILE

    # ------------------------------------------------------------------
    # File I/O
    # ------------------------------------------------------------------

    def save(self, layout: EditorLayout) -> None:
        """Persist *layout* to :meth:`get_file_path`.

        Creates the ``.pharos/`` (or ``~/.pharos_engine/``) directory if
        it doesn't yet exist. Writes through a ``.tmp`` file + atomic
        rename so a crash mid-write never leaves a partial YAML on disk.
        """
        if not isinstance(layout, EditorLayout):
            raise TypeError(
                "LayoutPersistence.save: layout must be an EditorLayout; "
                f"got {type(layout).__name__}"
            )
        path = self.get_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(
            layout.to_dict(),
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)

    def load(self) -> EditorLayout | None:
        """Load the layout snapshot from disk.

        Returns
        -------
        EditorLayout | None
            The restored layout, or ``None`` when the file is missing,
            unreadable, malformed, or carries a schema version this
            engine doesn't understand. ``None`` is the universal "fall
            back to defaults" sentinel.
        """
        path = self.get_file_path()
        if not path.is_file():
            return None
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return None
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError:
            return None
        if not isinstance(data, dict):
            return None
        # Schema gate — older / newer layouts fall back to defaults rather
        # than corrupting the editor.
        if int(data.get("schema_version", 0)) != SCHEMA_VERSION:
            return None
        try:
            return EditorLayout.from_dict(data)
        except (TypeError, ValueError, KeyError):
            return None

    def reset(self) -> None:
        """Delete the on-disk layout file (no-op when missing)."""
        path = self.get_file_path()
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            return

    # ------------------------------------------------------------------
    # Shell integration
    # ------------------------------------------------------------------

    def snapshot_from_shell(self, shell: "EditorShell") -> EditorLayout:
        """Capture *shell*'s current panel state as an :class:`EditorLayout`.

        Uses ``getattr`` probes rather than Dear PyGui queries so this is
        headless-safe. Each known panel handle on the shell contributes
        one :class:`PanelLayoutState` keyed by its canonical panel id.

        Panels that don't expose a position / size (because they haven't
        been built yet) fall back to the default layout's coordinates so
        the snapshot always covers the full panel family.
        """
        from .default_layouts import DEFAULT_LAYOUT

        viewport = (
            int(getattr(shell, "_width", 1280) or 1280),
            int(getattr(shell, "_height", 800) or 800),
        )
        theme_name = "teengirl_notebook"
        ui_settings = getattr(shell, "_ui_settings", None)
        if ui_settings is not None:
            theme_name = str(
                getattr(ui_settings, "default_theme", theme_name) or theme_name
            )

        # Map canonical panel ids to the shell attribute that holds them.
        panel_attrs: dict[str, str] = {
            "notebook_toolbar":         "_toolbar",
            "notebook_outliner":        "_scene_outliner",
            "notebook_inspector":       "_inspector",
            "notebook_content_browser": "_content_browser",
            "notebook_code_panel":      "_code_mode_panel",
            "theme_switcher_panel":     "_theme_switcher_panel",
        }

        panels: dict[str, PanelLayoutState] = {}
        for pid, attr in panel_attrs.items():
            default_state = DEFAULT_LAYOUT.panels.get(pid)
            handle = getattr(shell, attr, None)
            # Probe optional positioning hooks; fall back to default.
            position = _probe_position(handle, default_state)
            size = _probe_size(handle, default_state)
            visible = _probe_visible(handle, default_state)
            z_order = _probe_z_order(handle, default_state)
            docked_to = (
                default_state.docked_to if default_state is not None else ""
            )
            panels[pid] = PanelLayoutState(
                panel_id=pid,
                position=position,
                size=size,
                visible=visible,
                z_order=z_order,
                docked_to=docked_to,
            )
        return EditorLayout(
            schema_version=SCHEMA_VERSION,
            theme=theme_name,
            viewport_size=viewport,
            panels=panels,
        )

    def apply_to_shell(
        self, shell: "EditorShell", layout: EditorLayout
    ) -> None:
        """Apply *layout* to *shell*.

        For each known panel id, looks up the matching shell attribute
        and forwards the persisted position / size / visibility through
        whichever optional setter the panel exposes
        (``set_position`` / ``set_size`` / ``set_visible`` / ``set_z_order``).
        Panels without those setters silently no-op — the layout file is
        still useful as a forward-compatible cache.
        """
        if not isinstance(layout, EditorLayout):
            raise TypeError(
                "LayoutPersistence.apply_to_shell: layout must be EditorLayout; "
                f"got {type(layout).__name__}"
            )

        panel_attrs: dict[str, str] = {
            "notebook_toolbar":         "_toolbar",
            "notebook_outliner":        "_scene_outliner",
            "notebook_inspector":       "_inspector",
            "notebook_content_browser": "_content_browser",
            "notebook_code_panel":      "_code_mode_panel",
            "theme_switcher_panel":     "_theme_switcher_panel",
        }

        # Cache the last-applied layout on the shell so tests can verify
        # what the persistence layer actually pushed (and so the shell
        # can re-snapshot from defaults later).
        try:
            shell._layout_state = layout  # type: ignore[attr-defined]
        except Exception:
            pass

        # Drop the theme name back onto the UI settings so the next theme
        # switch lookup picks up the persisted choice.
        ui_settings = getattr(shell, "_ui_settings", None)
        if ui_settings is not None:
            try:
                ui_settings.default_theme = layout.theme
            except Exception:
                pass

        for pid, attr in panel_attrs.items():
            state = layout.panels.get(pid)
            if state is None:
                continue
            handle = getattr(shell, attr, None)
            if handle is None:
                continue
            _push_position(handle, state.position)
            _push_size(handle, state.size)
            _push_visible(handle, state.visible)
            _push_z_order(handle, state.z_order)

    # ------------------------------------------------------------------
    # Baked-preset shortcut (sprint CC4)
    # ------------------------------------------------------------------

    @classmethod
    def load_baked_preset(cls, name: str) -> EditorLayout:
        """Return the shipping :class:`EditorLayout` for baked preset *name*.

        Thin delegation to :class:`pharos_editor.ui.editor.layout_baker.LayoutBaker`
        so callers can reach the six shipping presets (``default``,
        ``triple_pane``, ``wide_code``, ``focus_mode``, ``debugging``,
        ``presentation``) without importing the baker module directly.

        The user-side file wins when it exists — matching the same
        precedence as every other baker (``ChainBaker``,
        ``PrefabLibrary``, ``UserThemeStore``) so hand-edits made in
        ``~/.pharos_engine/layouts/`` survive across engine upgrades.

        Raises
        ------
        LayoutBakerError
            When no baked or user preset matches *name*, or when the
            on-disk YAML is malformed. Imported lazily so the base
            persistence surface remains free of extra top-level
            dependencies.
        """
        # Lazy import — avoids a module-level cycle between
        # ``layout_persistence`` and ``layout_baker`` (the latter
        # imports :class:`EditorLayout` from here).
        from .layout_baker import LayoutBaker
        return LayoutBaker().load(name)


# ---------------------------------------------------------------------------
# Internal probe / push helpers — keep ``snapshot_from_shell`` /
# ``apply_to_shell`` readable while still being defensive against panels
# that don't implement every optional setter.
# ---------------------------------------------------------------------------


def _probe_position(
    handle: Any, default: PanelLayoutState | None,
) -> tuple[int, int]:
    """Return ``(x, y)`` from *handle* with a sane fallback."""
    if handle is not None:
        # Prefer an explicit ``get_position`` method.
        getter = getattr(handle, "get_position", None)
        if callable(getter):
            try:
                pos = getter()
                if pos is not None and len(pos) == 2:
                    return (int(pos[0]), int(pos[1]))
            except Exception:
                pass
        # Else honour a ``position`` attribute if one is present.
        pos_attr = getattr(handle, "position", None)
        if pos_attr is not None and hasattr(pos_attr, "__len__"):
            try:
                if len(pos_attr) == 2:
                    return (int(pos_attr[0]), int(pos_attr[1]))
            except Exception:
                pass
    if default is not None:
        return default.position
    return (0, 0)


def _probe_size(
    handle: Any, default: PanelLayoutState | None,
) -> tuple[int, int]:
    if handle is not None:
        getter = getattr(handle, "get_size", None)
        if callable(getter):
            try:
                sz = getter()
                if sz is not None and len(sz) == 2:
                    w = max(1, int(sz[0]))
                    h = max(1, int(sz[1]))
                    return (w, h)
            except Exception:
                pass
        sz_attr = getattr(handle, "size", None)
        if sz_attr is not None and hasattr(sz_attr, "__len__"):
            try:
                if len(sz_attr) == 2:
                    w = max(1, int(sz_attr[0]))
                    h = max(1, int(sz_attr[1]))
                    return (w, h)
            except Exception:
                pass
    if default is not None:
        return default.size
    return (200, 200)


def _probe_visible(handle: Any, default: PanelLayoutState | None) -> bool:
    if handle is not None:
        v = getattr(handle, "visible", None)
        if isinstance(v, bool):
            return v
        getter = getattr(handle, "is_visible", None)
        if callable(getter):
            try:
                return bool(getter())
            except Exception:
                pass
    if default is not None:
        return default.visible
    return True


def _probe_z_order(handle: Any, default: PanelLayoutState | None) -> int:
    if handle is not None:
        z = getattr(handle, "z_order", None)
        if isinstance(z, int) and not isinstance(z, bool) and z >= 0:
            return z
    if default is not None:
        return default.z_order
    return 0


def _push_position(handle: Any, position: tuple[int, int]) -> None:
    setter = getattr(handle, "set_position", None)
    if callable(setter):
        try:
            setter(position)
            return
        except Exception:
            pass
    try:
        handle.position = position
    except Exception:
        pass


def _push_size(handle: Any, size: tuple[int, int]) -> None:
    setter = getattr(handle, "set_size", None)
    if callable(setter):
        try:
            setter(size)
            return
        except Exception:
            pass
    try:
        handle.size = size
    except Exception:
        pass


def _push_visible(handle: Any, visible: bool) -> None:
    setter = getattr(handle, "set_visible", None)
    if callable(setter):
        try:
            setter(visible)
            return
        except Exception:
            pass
    try:
        handle.visible = visible
    except Exception:
        pass


def _push_z_order(handle: Any, z_order: int) -> None:
    setter = getattr(handle, "set_z_order", None)
    if callable(setter):
        try:
            setter(z_order)
            return
        except Exception:
            pass
    try:
        handle.z_order = z_order
    except Exception:
        pass
