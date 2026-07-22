"""Runtime game HUD (Nova3D flaw #3 remediation).

Nova3D shipped an editor UI (DearPyGui, retained-mode) but no game
runtime HUD. Games either had to embed a separate UI library or hack
DearPyGui into their shipped title (both expensive + heavy).

Pharos ships an immediate-mode HUD in the engine wheel. Independent
of the editor. Zero DearPyGui / pywebview cost — talks straight to the
existing wgpu context. Uses PyImGui when the ``[hud]`` extra is
installed; falls back to a text-only overlay otherwise.

Public API
----------
:class:`Hud`               entrypoint owning the frame lifecycle
:class:`HudFrame`          per-frame builder handed to user code
:func:`bind_wgpu_context`  register the engine's wgpu Device + Queue

Example::

    from pharos_engine.hud import Hud

    hud = Hud()
    def draw_hud(frame):
        frame.begin_window("Player")
        frame.text(f"HP: {player.hp}/{player.max_hp}")
        frame.progress_bar(player.hp / player.max_hp)
        frame.end_window()

    hud.on_draw(draw_hud)
    hud.render(dt)
"""
from __future__ import annotations

from .core import Hud, HudFrame, bind_wgpu_context

__all__ = ["Hud", "HudFrame", "bind_wgpu_context"]
