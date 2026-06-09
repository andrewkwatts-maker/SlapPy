"""Inline SVG portraits for :class:`NotebookSpawnMenu` trading cards.

Split out of ``notebook_spawn_menu.py`` (2026-06-07 consolidation sweep)
so the menu module stays focused on dispatch + lifecycle and the
portraits live next to their byte-budget guard.

Each portrait ≤ 500 bytes. Glyphs use literal colour values so they read
at thumbnail scale; an active theme can re-tint via ``currentColor`` if
authors swap the literals later. The byte-budget guard at the bottom of
this module fires at import time, so a future copy edit can't quietly
bust the budget.
"""
from __future__ import annotations


_SVG_ROPE_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="8" cy="20" r="4" fill="#a07050"/>'
    '<circle cx="56" cy="44" r="4" fill="#a07050"/>'
    '<path d="M8 20 L20 38 L32 22 L44 40 L56 24" '
    'fill="none" stroke="#a07050" stroke-width="3"/>'
    '</svg>'
)

_SVG_RAGDOLL_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="12" r="6" fill="none" stroke="#604030"/>'
    '<path d="M32 18 L32 40 M14 26 L50 26 '
    'M32 40 L20 58 M32 40 L44 58" stroke="#604030" fill="none"/>'
    '<circle cx="14" cy="26" r="2" fill="#a07050"/>'
    '<circle cx="50" cy="26" r="2" fill="#a07050"/>'
    '</svg>'
)

_SVG_HUMANOID_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="14" r="8" fill="#e0b080"/>'
    '<rect x="22" y="22" width="20" height="22" rx="6" fill="#d0a070"/>'
    '<rect x="22" y="44" width="8" height="16" rx="3" fill="#a07050"/>'
    '<rect x="34" y="44" width="8" height="16" rx="3" fill="#a07050"/>'
    '</svg>'
)

_SVG_IK_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="8" cy="48" r="3" fill="#7090c0"/>'
    '<circle cx="28" cy="28" r="3" fill="#7090c0"/>'
    '<circle cx="48" cy="16" r="3" fill="#7090c0"/>'
    '<line x1="8" y1="48" x2="28" y2="28" stroke="#7090c0" stroke-width="2"/>'
    '<line x1="28" y1="28" x2="48" y2="16" stroke="#7090c0" stroke-width="2"/>'
    '<polygon points="56,12 60,16 56,20" fill="#d87aa0"/>'
    '</svg>'
)

_SVG_ZONE_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<rect x="8" y="12" width="48" height="40" fill="none" '
    'stroke="#8090a0" stroke-width="2" stroke-dasharray="4,3"/>'
    '</svg>'
)

_SVG_THRESHOLD_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="0">'
    '<stop offset="0" stop-color="#7090c0"/>'
    '<stop offset="1" stop-color="#f0c050"/></linearGradient></defs>'
    '<rect x="6" y="24" width="52" height="16" fill="url(#g)"/>'
    '<line x1="36" y1="18" x2="36" y2="46" stroke="#d87aa0" stroke-width="2"/>'
    '</svg>'
)

_SVG_LIGHT_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="32" r="10" fill="#f0c050"/>'
    '<path d="M32 6 L32 14 M32 50 L32 58 M6 32 L14 32 M50 32 L58 32 '
    'M14 14 L20 20 M44 44 L50 50" stroke="#f0c050" fill="none"/>'
    '</svg>'
)

_SVG_SUN_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<circle cx="32" cy="32" r="14" fill="#f0c050"/>'
    '<circle cx="27" cy="29" r="1.5" fill="#604030"/>'
    '<circle cx="37" cy="29" r="1.5" fill="#604030"/>'
    '<path d="M27 36 Q32 40 37 36 M32 4 L32 12 M32 52 L32 60 '
    'M4 32 L12 32 M52 32 L60 32" stroke="#604030" fill="none"/>'
    '</svg>'
)

_SVG_PALETTE_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M32 8 C16 8 8 22 8 34 C8 44 16 48 22 44 C26 41 32 44 32 50 '
    'C32 56 40 58 48 52 C58 44 58 26 48 16 C44 12 38 8 32 8 Z" '
    'fill="#e0c890" stroke="#604030" stroke-width="1.5"/>'
    '<circle cx="20" cy="22" r="3" fill="#e07a90"/>'
    '<circle cx="32" cy="18" r="3" fill="#e0c850"/>'
    '<circle cx="44" cy="24" r="3" fill="#70a0c0"/>'
    '<circle cx="42" cy="38" r="3" fill="#6ea060"/>'
    '</svg>'
)

_SVG_EMITTER_PORTRAIT = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg">'
    '<polygon points="32,4 36,28 60,32 36,36 32,60 28,36 4,32 28,28" '
    'fill="#f0c050"/>'
    '<circle cx="32" cy="32" r="4" fill="#d87aa0"/>'
    '<circle cx="14" cy="14" r="2" fill="#f0c050"/>'
    '<circle cx="50" cy="14" r="2" fill="#f0c050"/>'
    '<circle cx="14" cy="50" r="2" fill="#f0c050"/>'
    '<circle cx="50" cy="50" r="2" fill="#f0c050"/>'
    '</svg>'
)


# Byte-budget guard — every portrait must fit in 500 bytes.
for _name, _svg in (
    ("rope",       _SVG_ROPE_PORTRAIT),
    ("ragdoll",    _SVG_RAGDOLL_PORTRAIT),
    ("humanoid",   _SVG_HUMANOID_PORTRAIT),
    ("ik_chain",   _SVG_IK_PORTRAIT),
    ("zone_rect",  _SVG_ZONE_PORTRAIT),
    ("zone_thresh", _SVG_THRESHOLD_PORTRAIT),
    ("light",      _SVG_LIGHT_PORTRAIT),
    ("sun",        _SVG_SUN_PORTRAIT),
    ("material",   _SVG_PALETTE_PORTRAIT),
    ("emitter",    _SVG_EMITTER_PORTRAIT),
):
    if len(_svg.encode("utf-8")) > 500:  # pragma: no cover - constant data
        raise AssertionError(
            f"NotebookSpawnMenu: SVG portrait {_name!r} exceeds 500 bytes "
            f"({len(_svg.encode('utf-8'))} bytes)"
        )


__all__ = [
    "_SVG_ROPE_PORTRAIT",
    "_SVG_RAGDOLL_PORTRAIT",
    "_SVG_HUMANOID_PORTRAIT",
    "_SVG_IK_PORTRAIT",
    "_SVG_ZONE_PORTRAIT",
    "_SVG_THRESHOLD_PORTRAIT",
    "_SVG_LIGHT_PORTRAIT",
    "_SVG_SUN_PORTRAIT",
    "_SVG_PALETTE_PORTRAIT",
    "_SVG_EMITTER_PORTRAIT",
]
