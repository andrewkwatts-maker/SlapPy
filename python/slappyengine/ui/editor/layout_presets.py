"""Layout presets for the notebook editor shell.

Five named layouts ship with the editor — "Default", "Wide Code",
"Focus", "Triple Pane", and "Compact". Each preset records the desired
position, size, and visibility of every well-known panel window in the
shell. Applying a preset reshapes the layout in one call so users can
hop between an outliner-heavy edit setup and an immersive coding view
without dragging splitters.

The preset payloads reuse the canonical
:class:`slappyengine.ui.editor.layout_persistence.PanelLayoutState`
dataclass so that an applied preset can later be snapshotted + persisted
through the existing :class:`LayoutPersistence` pipeline without an
adapter layer.

Headless-safe
-------------
The module imports no Dear PyGui at module load. :func:`apply_preset`
reaches through the shell's panel registry and either calls the shell's
own ``configure_panel`` hook (when available) or attempts a best-effort
DPG reconfigure — but only when ``shell._running`` is set so the headless
test path never trips DPG's no-context segfault.

Design provenance
-----------------
``docs/ui_layout_presets_2026_06_04.md`` § Window Mgmt and the shell at
:mod:`slappyengine.ui.editor.shell` (rows 1-3 of the ``editor_root``
window).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from slappyengine._validation import validate_non_empty_str, validate_str
from slappyengine.ui.editor.layout_persistence import PanelLayoutState

if TYPE_CHECKING:
    from slappyengine.ui.editor.shell import EditorShell


# ---------------------------------------------------------------------------
# LayoutPreset — a named collection of PanelLayoutState entries.
# ---------------------------------------------------------------------------


@dataclass
class LayoutPreset:
    """A named layout configuration covering every editor panel.

    Parameters
    ----------
    name:
        Human-readable name surfaced in the View → Layout Presets menu.
    description:
        One-line summary used as the menu tooltip + status-bar toast.
    panels:
        Mapping of panel id → :class:`PanelLayoutState`. The shell uses
        this to repaint the layout when the preset is applied.
    shortcut:
        Canonical hotkey string (e.g. ``"ctrl+1"``). Empty when the
        preset has no shortcut binding.
    icon_id:
        Optional sticker icon id rendered in the menu / welcome-screen
        chooser.
    """

    name: str
    description: str
    panels: dict[str, PanelLayoutState] = field(default_factory=dict)
    shortcut: str = ""
    icon_id: str = ""

    def __post_init__(self) -> None:
        validate_non_empty_str("name", "LayoutPreset", self.name)
        validate_str("description", "LayoutPreset", self.description)
        validate_str("shortcut", "LayoutPreset", self.shortcut)
        validate_str("icon_id", "LayoutPreset", self.icon_id)
        if not isinstance(self.panels, dict):
            raise TypeError(
                "LayoutPreset: panels must be a dict[str, PanelLayoutState]"
            )


# ---------------------------------------------------------------------------
# The five built-in presets.
# ---------------------------------------------------------------------------


# Canonical panel ids known to the shell. Tests pin this set.
PANEL_IDS: tuple[str, ...] = (
    "toolbar",
    "outliner",
    "viewport",
    "inspector",
    "content_browser",
    "code",
    "status_bar",
)


def _pls(panel_id, position, size, visible=True, z_order=0, docked_to=""):
    """Shorthand for :class:`PanelLayoutState` construction."""
    return PanelLayoutState(
        panel_id=panel_id,
        position=position,
        size=size,
        visible=visible,
        z_order=z_order,
        docked_to=docked_to,
    )


def _default_panels() -> dict[str, PanelLayoutState]:
    """Outliner + Viewport + Inspector + Content Browser (the shipping layout)."""
    return {
        "toolbar":         _pls("toolbar",         (0,    0),   (1400, 36),  docked_to="top"),
        "outliner":        _pls("outliner",        (0,    36),  (200,  444), docked_to="left"),
        "viewport":        _pls("viewport",        (200,  36),  (900,  444)),
        "inspector":       _pls("inspector",       (1100, 36),  (300,  444), docked_to="right"),
        "content_browser": _pls("content_browser", (0,    480), (1400, 220), docked_to="bottom"),
        "code":            _pls("code",            (200,  36),  (900,  444), visible=False),
        "status_bar":      _pls("status_bar",      (0,    700), (1400, 20),  docked_to="bottom"),
    }


def _wide_code_panels() -> dict[str, PanelLayoutState]:
    """Code panel dominates; outliner + inspector compressed to thin strips."""
    return {
        "toolbar":         _pls("toolbar",         (0,    0),   (1400, 36),  docked_to="top"),
        "outliner":        _pls("outliner",        (0,    36),  (150,  644), docked_to="left"),
        "viewport":        _pls("viewport",        (150,  36),  (350,  644)),
        "inspector":       _pls("inspector",       (500,  36),  (200,  644), docked_to="right"),
        "code":            _pls("code",            (700,  36),  (700,  644), visible=True),
        "content_browser": _pls("content_browser", (0,    680), (1400, 40),  visible=False),
        "status_bar":      _pls("status_bar",      (0,    700), (1400, 20),  docked_to="bottom"),
    }


def _focus_panels() -> dict[str, PanelLayoutState]:
    """Single viewport — every panel except toolbar + status bar hidden."""
    return {
        "toolbar":         _pls("toolbar",         (0,    0),   (1400, 36),  docked_to="top"),
        "outliner":        _pls("outliner",        (0,    36),  (200,  644), visible=False),
        "viewport":        _pls("viewport",        (0,    36),  (1400, 644)),
        "inspector":       _pls("inspector",       (1100, 36),  (300,  644), visible=False),
        "content_browser": _pls("content_browser", (0,    680), (1400, 40),  visible=False),
        "code":            _pls("code",            (200,  36),  (900,  644), visible=False),
        "status_bar":      _pls("status_bar",      (0,    700), (1400, 20),  docked_to="bottom"),
    }


def _triple_pane_panels() -> dict[str, PanelLayoutState]:
    """Outliner | Viewport | Inspector — three equal vertical columns."""
    return {
        "toolbar":         _pls("toolbar",         (0,    0),   (1400, 36),  docked_to="top"),
        "outliner":        _pls("outliner",        (0,    36),  (467,  644), docked_to="left"),
        "viewport":        _pls("viewport",        (467,  36),  (466,  644)),
        "inspector":       _pls("inspector",       (933,  36),  (467,  644), docked_to="right"),
        "content_browser": _pls("content_browser", (0,    680), (1400, 40),  visible=False),
        "code":            _pls("code",            (467,  36),  (466,  644), visible=False),
        "status_bar":      _pls("status_bar",      (0,    700), (1400, 20),  docked_to="bottom"),
    }


def _compact_panels() -> dict[str, PanelLayoutState]:
    """Tight layout for smaller screens — compressed sidebars + low rows."""
    return {
        "toolbar":         _pls("toolbar",         (0,    0),   (1120, 28),  docked_to="top"),
        "outliner":        _pls("outliner",        (0,    28),  (160,  372), docked_to="left"),
        "viewport":        _pls("viewport",        (160,  28),  (720,  372)),
        "inspector":       _pls("inspector",       (880,  28),  (240,  372), docked_to="right"),
        "content_browser": _pls("content_browser", (0,    400), (1120, 140), docked_to="bottom"),
        "code":            _pls("code",            (160,  28),  (720,  372), visible=False),
        "status_bar":      _pls("status_bar",      (0,    540), (1120, 16),  docked_to="bottom"),
    }


PRESETS: dict[str, LayoutPreset] = {
    "default": LayoutPreset(
        name="Default",
        description="Outliner + Viewport + Inspector + Content Browser",
        shortcut="ctrl+1",
        icon_id="notebook",
        panels=_default_panels(),
    ),
    "wide_code": LayoutPreset(
        name="Wide Code",
        description="Code panel takes 50% of viewport; sidebars compressed.",
        shortcut="ctrl+2",
        icon_id="pencil",
        panels=_wide_code_panels(),
    ),
    "focus": LayoutPreset(
        name="Focus",
        description="Single viewport, all panels hidden.",
        shortcut="ctrl+3",
        icon_id="eye",
        panels=_focus_panels(),
    ),
    "triple_pane": LayoutPreset(
        name="Triple Pane",
        description="Outliner | Viewport | Inspector — equal thirds.",
        shortcut="ctrl+4",
        icon_id="three_dots",
        panels=_triple_pane_panels(),
    ),
    "compact": LayoutPreset(
        name="Compact",
        description="Tight layout for smaller screens.",
        shortcut="ctrl+5",
        icon_id="compress",
        panels=_compact_panels(),
    ),
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def list_presets() -> list[LayoutPreset]:
    """Return the built-in presets in canonical (insertion) order."""
    return list(PRESETS.values())


def list_preset_names() -> list[str]:
    """Return the canonical preset id list (insertion order)."""
    return list(PRESETS.keys())


def get_preset(name: str) -> LayoutPreset:
    """Look a preset up by canonical id.

    Raises
    ------
    KeyError
        If *name* is not a known preset id.
    """
    validate_non_empty_str("name", "get_preset", name)
    if name not in PRESETS:
        raise KeyError(
            f"get_preset: unknown preset {name!r}; known: "
            f"{sorted(PRESETS.keys())}"
        )
    return PRESETS[name]


def _maybe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when missing."""
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]

        return dpg
    except Exception:
        return None


def apply_preset(shell: "EditorShell", preset_name: str) -> LayoutPreset:
    """Apply *preset_name* to *shell*.

    Mutates the shell's ``_panel_layout_state`` dict and best-effort
    reconfigures any DPG windows whose tags map to the preset's panel
    ids. Returns the resolved :class:`LayoutPreset`.

    The shell may also expose ``configure_panel(panel_id, state)`` which
    takes precedence over the direct DPG path so hosts can route through
    a custom dock manager.
    """
    preset = get_preset(preset_name)
    # Record the resolved state on the shell so subsequent queries see it.
    setattr(shell, "_active_layout_preset", preset_name)
    state_dict = getattr(shell, "_panel_layout_state", None)
    if not isinstance(state_dict, dict):
        state_dict = {}
        setattr(shell, "_panel_layout_state", state_dict)
    state_dict.clear()
    for pid, st in preset.panels.items():
        state_dict[pid] = st

    # Route through the shell's configure_panel hook if provided.
    configure = getattr(shell, "configure_panel", None)
    if callable(configure):
        for pid, st in preset.panels.items():
            try:
                configure(pid, st)
            except Exception:
                pass
        return preset

    # Direct DPG best-effort reconfigure. Gate on shell._running because
    # ``dpg.does_item_exist`` segfaults hard on Windows when no DPG
    # context has been created — the shell's own status helpers use the
    # same gate.
    if not getattr(shell, "_running", False):
        return preset
    dpg = _maybe_dpg()
    if dpg is None:
        return preset
    tag_map = {
        "toolbar":         "toolbar_row",
        "outliner":        "scene_tab_body",
        "viewport":        "viewport_area",
        "inspector":       "details_tab_body",
        "content_browser": "bottom_panel",
        "code":            "code_mode_area",
        "status_bar":      "status_bar",
    }
    for pid, st in preset.panels.items():
        tag = tag_map.get(pid)
        if tag is None:
            continue
        try:
            if dpg.does_item_exist(tag):
                dpg.configure_item(
                    tag,
                    width=st.size[0],
                    height=st.size[1],
                    show=st.visible,
                )
        except Exception:
            pass
    return preset


__all__ = [
    "LayoutPreset",
    "PANEL_IDS",
    "PRESETS",
    "PanelLayoutState",
    "apply_preset",
    "get_preset",
    "list_preset_names",
    "list_presets",
]
