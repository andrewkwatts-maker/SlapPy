"""Game-runtime UI subpackage — immediate-mode widgets + HUD kit.

The :mod:`pharos_editor.ui.runtime` package provides a *lightweight*,
DPG-free UI stack usable from a game tick loop. The editor-side
:mod:`pharos_editor.ui.editor` package is a superset (dockable panels,
gizmos, etc.) intended for authoring; games ship the runtime layer only.

Design contract
---------------

* No Dear PyGui import at runtime — every module here works without DPG.
* Widgets emit :class:`DrawCommand` records instead of drawing directly,
  so the HH4 renderer (or any other back-end) can execute them.
* Theme colours come from :class:`RuntimeTheme`, which soft-imports the
  editor :class:`~pharos_editor.ui.theme.theme_spec.ThemeSpec` when
  available and falls back to a minimal built-in default otherwise.

Public surface
--------------

.. code-block:: python

    from pharos_editor.ui.runtime import (
        ImmediateUI,
        DrawCommand,
        RuntimeTheme,
        measure_text,
        wrap_text,
        HealthBar,
        StaminaBar,
        AmmoCounter,
        Minimap,
        Compass,
        Toast,
        stack_vertical,
        stack_horizontal,
        grid,
        anchor_topleft,
        anchor_center,
        anchor_bottomright,
    )
"""
from __future__ import annotations

from .draw_command import DrawCommand
from .hud_kit import (
    AmmoCounter,
    Compass,
    HealthBar,
    Minimap,
    StaminaBar,
    Toast,
)
from .immediate_ui import ImmediateUI
from .layout import (
    anchor_bottomright,
    anchor_center,
    anchor_topleft,
    grid,
    stack_horizontal,
    stack_vertical,
)
from .runtime_theme import RuntimeTheme
from .text_layout import measure_text, wrap_text

__all__ = [
    "AmmoCounter",
    "Compass",
    "DrawCommand",
    "HealthBar",
    "ImmediateUI",
    "Minimap",
    "RuntimeTheme",
    "StaminaBar",
    "Toast",
    "anchor_bottomright",
    "anchor_center",
    "anchor_topleft",
    "grid",
    "measure_text",
    "stack_horizontal",
    "stack_vertical",
    "wrap_text",
]
