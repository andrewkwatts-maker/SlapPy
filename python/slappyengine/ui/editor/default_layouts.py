"""Canonical preset editor layouts.

These :class:`EditorLayout` snapshots ship with the engine and are used
whenever the per-project ``layout.yaml`` is missing, malformed, or has
a schema version this build can't understand.

Three presets are exposed:

* :data:`DEFAULT_LAYOUT` — the standard four-pane notebook layout
  (toolbar / outliner / inspector / content browser) with the code panel
  and theme switcher hidden by default. This is the layout
  ``View → Reset Layout`` restores.
* :data:`WIDE_CODE_LAYOUT` — outliner + inspector compressed to leave
  room for the code panel docked centre-right; suits scripting-heavy
  sessions.
* :data:`TRIPLE_PANE_LAYOUT` — three equal columns
  (scene / viewport / inspector) with the content browser collapsed —
  inspired by the Unreal-style "Inspector | Viewport | Inspector"
  workflow some power users prefer.

The presets are pure data and are validated at module import time by
the :class:`PanelLayoutState` / :class:`EditorLayout` dataclass
``__post_init__`` hooks. A bad preset trips an ``ImportError`` rather
than blowing up later when the user clicks Reset.
"""
from __future__ import annotations

from .layout_persistence import EditorLayout, PanelLayoutState


__all__ = [
    "DEFAULT_LAYOUT",
    "WIDE_CODE_LAYOUT",
    "TRIPLE_PANE_LAYOUT",
    "PRESET_LAYOUTS",
]


# ---------------------------------------------------------------------------
# DEFAULT_LAYOUT — the standard notebook chrome
# ---------------------------------------------------------------------------

DEFAULT_LAYOUT = EditorLayout(
    theme="teengirl_notebook",
    viewport_size=(1280, 800),
    panels={
        "notebook_toolbar": PanelLayoutState(
            panel_id="notebook_toolbar",
            position=(0, 24),
            size=(1280, 56),
            docked_to="top",
        ),
        "notebook_outliner": PanelLayoutState(
            panel_id="notebook_outliner",
            position=(0, 80),
            size=(260, 480),
            docked_to="left",
        ),
        "notebook_inspector": PanelLayoutState(
            panel_id="notebook_inspector",
            position=(1020, 80),
            size=(260, 480),
            docked_to="right",
        ),
        "notebook_content_browser": PanelLayoutState(
            panel_id="notebook_content_browser",
            position=(0, 560),
            size=(1280, 200),
            docked_to="bottom",
        ),
        "notebook_code_panel": PanelLayoutState(
            panel_id="notebook_code_panel",
            position=(300, 100),
            size=(640, 400),
            visible=False,
            docked_to="floating",
        ),
        "theme_switcher_panel": PanelLayoutState(
            panel_id="theme_switcher_panel",
            position=(280, 200),
            size=(280, 360),
            visible=False,
            docked_to="floating",
        ),
    },
)


# ---------------------------------------------------------------------------
# WIDE_CODE_LAYOUT — outliner + inspector squeezed, big code pane
# ---------------------------------------------------------------------------

WIDE_CODE_LAYOUT = EditorLayout(
    theme="teengirl_notebook",
    viewport_size=(1280, 800),
    panels={
        "notebook_toolbar": PanelLayoutState(
            panel_id="notebook_toolbar",
            position=(0, 24),
            size=(1280, 56),
            docked_to="top",
        ),
        "notebook_outliner": PanelLayoutState(
            panel_id="notebook_outliner",
            position=(0, 80),
            size=(180, 680),
            docked_to="left",
        ),
        "notebook_inspector": PanelLayoutState(
            panel_id="notebook_inspector",
            position=(1100, 80),
            size=(180, 680),
            docked_to="right",
        ),
        "notebook_content_browser": PanelLayoutState(
            panel_id="notebook_content_browser",
            position=(180, 700),
            size=(920, 100),
            docked_to="bottom",
        ),
        "notebook_code_panel": PanelLayoutState(
            panel_id="notebook_code_panel",
            position=(180, 80),
            size=(920, 620),
            visible=True,
            docked_to="floating",
            z_order=1,
        ),
        "theme_switcher_panel": PanelLayoutState(
            panel_id="theme_switcher_panel",
            position=(280, 200),
            size=(280, 360),
            visible=False,
            docked_to="floating",
        ),
    },
)


# ---------------------------------------------------------------------------
# TRIPLE_PANE_LAYOUT — three equal columns, content browser collapsed
# ---------------------------------------------------------------------------

TRIPLE_PANE_LAYOUT = EditorLayout(
    theme="teengirl_notebook",
    viewport_size=(1280, 800),
    panels={
        "notebook_toolbar": PanelLayoutState(
            panel_id="notebook_toolbar",
            position=(0, 24),
            size=(1280, 56),
            docked_to="top",
        ),
        "notebook_outliner": PanelLayoutState(
            panel_id="notebook_outliner",
            position=(0, 80),
            size=(420, 720),
            docked_to="left",
        ),
        "notebook_inspector": PanelLayoutState(
            panel_id="notebook_inspector",
            position=(860, 80),
            size=(420, 720),
            docked_to="right",
        ),
        "notebook_content_browser": PanelLayoutState(
            panel_id="notebook_content_browser",
            position=(0, 780),
            size=(1280, 20),
            visible=False,
            docked_to="bottom",
        ),
        "notebook_code_panel": PanelLayoutState(
            panel_id="notebook_code_panel",
            position=(300, 100),
            size=(640, 400),
            visible=False,
            docked_to="floating",
        ),
        "theme_switcher_panel": PanelLayoutState(
            panel_id="theme_switcher_panel",
            position=(280, 200),
            size=(280, 360),
            visible=False,
            docked_to="floating",
        ),
    },
)


#: Registry of every preset by canonical id. The ``View → Reset Layout``
#: submenu walks this map to surface a switcher; tests iterate it to
#: confirm every preset validates without raising.
PRESET_LAYOUTS: dict[str, EditorLayout] = {
    "default":     DEFAULT_LAYOUT,
    "wide_code":   WIDE_CODE_LAYOUT,
    "triple_pane": TRIPLE_PANE_LAYOUT,
}
