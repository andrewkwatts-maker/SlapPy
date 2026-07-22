"""Procedural washi-tape shader library.

Two things live here:

* :mod:`.library` — a registry (:data:`WASHI_TAPES`) of 15
  :class:`WashiTapeStyle` records, each bundling a WGSL fragment shader
  with a display name, default swatch size, animation flag, and
  description.
* :mod:`.renderer` — :func:`render_tape` / :func:`bake_tape_texture`,
  which bake a style at a chosen size and pair of theme colours.

Callers (notably the panel-decor system in
:mod:`pharos_engine.ui.editor.panel_decor`) look tapes up by
:attr:`WashiTapeStyle.id` and blit the returned RGBA into the
appropriate window corner.

Public surface::

    from pharos_engine.ui.theme.washi_tape import (
        WashiTapeStyle, WASHI_TAPES, get_tape, list_tapes,
        render_tape, bake_tape_texture,
    )
"""
from __future__ import annotations

from .library import WashiTapeStyle, WASHI_TAPES, get_tape, list_tapes
from .renderer import render_tape, bake_tape_texture, has_wgpu
from .presets import (
    WASHI_TAPE_PRESETS,
    WashiTapePreset,
    render_washi_tape,
    rotate_washi_tape,
)


__all__ = [
    "WASHI_TAPES",
    "WASHI_TAPE_PRESETS",
    "WashiTapePreset",
    "WashiTapeStyle",
    "bake_tape_texture",
    "get_tape",
    "has_wgpu",
    "list_tapes",
    "render_tape",
    "render_washi_tape",
    "rotate_washi_tape",
]
