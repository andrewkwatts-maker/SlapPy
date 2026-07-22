"""Theme registry for notebook-flavoured widget primitives.

This module owns the *interface* between generic widget primitives and a
swappable visual theme.  The widgets under this package (``StickerButton``,
``WashiPanel``, ``NotebookTab``, …) query the active theme at construction
time to fetch palette / nine-slice / sticker / icon assets.

The widgets themselves never bind to a specific theme — they only build the
structural Dear PyGui layout.  A concrete theme (e.g. the TeenGirl Notebook
theme that lands in the next sprint) plugs in by calling
:func:`set_active_theme` with a :class:`NotebookTheme` instance.

When no theme is registered, widgets fall back gracefully to plain DPG widgets
so the editor remains usable in vanilla mode.

This module deliberately imports nothing from ``dearpygui`` so it can be
imported in headless test contexts and on systems without the ``[editor]``
extra installed.  Each widget defers its DPG import to ``build()`` time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from pharos_engine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_str,
)


# ---------------------------------------------------------------------------
# NotebookTheme dataclass — the contract widgets see.
# ---------------------------------------------------------------------------


@dataclass
class NotebookTheme:
    """Palette / asset bundle queried by every notebook widget.

    Fields are intentionally generic — the next-sprint TeenGirl Notebook
    theme picks the concrete colour values, sticker PNG paths, washi-tape
    textures, etc.  Widgets in this package read these fields but never
    mutate them.

    Attributes
    ----------
    name:
        Human-readable theme identifier (``"teen_girl_notebook"``,
        ``"default"``, …).
    palette:
        Colour bag indexed by semantic name.  Each value is an ``(R, G, B, A)``
        tuple with components in ``0..255``.  Recognised keys:
        ``paper``, ``ink``, ``accent``, ``highlight``, ``washi``, ``heart``.
    nine_slice:
        Map of ``slot_name -> path``.  Recognised slots:
        ``sticker_button``, ``washi_panel``, ``notebook_tab``,
        ``highlighter_slider``, ``heart_checkbox``.  Empty string means no
        nine-slice texture for that slot — the widget falls back to a plain
        DPG primitive.
    stickers:
        Map of ``sticker_id -> path``.  Used by :func:`add_sticker_corner`
        and by :class:`StickerButton` when ``sticker_icon`` is a known id.
    icon_fallback:
        Map of ``sticker_id -> emoji``.  Surfaces as plain text when the
        sticker path cannot be resolved (no PIL, missing file, headless).
    sticker_rotation:
        Default sticker tilt in degrees applied by
        :class:`StickerButton`. The theme can override this; widgets clamp
        to ``[-15, 15]`` so the rotation reads as "stuck-on" rather than
        falling off.
    """

    name: str = "default"
    palette: dict[str, tuple[int, int, int, int]] = field(default_factory=dict)
    nine_slice: dict[str, str] = field(default_factory=dict)
    stickers: dict[str, str] = field(default_factory=dict)
    icon_fallback: dict[str, str] = field(default_factory=dict)
    sticker_rotation: float = 4.0

    # ------------------------------------------------------------------
    # Lookup helpers — every widget goes through these so a missing key
    # always returns a sensible default instead of crashing the layout.
    # ------------------------------------------------------------------

    def color(
        self,
        slot: str,
        default: tuple[int, int, int, int] = (200, 200, 200, 255),
    ) -> tuple[int, int, int, int]:
        """Return ``palette[slot]`` if present, else *default*."""
        validate_non_empty_str("slot", "NotebookTheme.color", slot)
        return self.palette.get(slot, default)

    def nine_slice_path(self, slot: str) -> str:
        """Return the nine-slice texture path for *slot* (empty if absent)."""
        validate_non_empty_str("slot", "NotebookTheme.nine_slice_path", slot)
        return self.nine_slice.get(slot, "")

    def sticker_path(self, sticker_id: str) -> str:
        """Return the sticker PNG path for *sticker_id* (empty if absent)."""
        validate_non_empty_str(
            "sticker_id", "NotebookTheme.sticker_path", sticker_id,
        )
        return self.stickers.get(sticker_id, "")

    def icon_for(self, sticker_id: str, default: str = "*") -> str:
        """Return the emoji / text fallback for *sticker_id*."""
        validate_non_empty_str("sticker_id", "NotebookTheme.icon_for", sticker_id)
        return self.icon_fallback.get(sticker_id, default)


# ---------------------------------------------------------------------------
# Process-global registry
# ---------------------------------------------------------------------------

_active_theme: NotebookTheme | None = None
_theme_listeners: list[Callable[[NotebookTheme | None], None]] = []


def set_active_theme(theme: NotebookTheme | None) -> None:
    """Register *theme* as the active notebook theme.

    Passing ``None`` clears the registration.  Every widget constructed
    after this call queries the new theme; widgets already built are
    notified via the listener hook so they can rebind their style.

    Parameters
    ----------
    theme:
        A :class:`NotebookTheme` instance or ``None``.
    """
    if theme is not None and not isinstance(theme, NotebookTheme):
        raise TypeError(
            "set_active_theme: theme must be NotebookTheme or None; "
            f"got {type(theme).__name__}"
        )
    global _active_theme
    _active_theme = theme
    for listener in list(_theme_listeners):
        try:
            listener(theme)
        except Exception:
            # Listeners that crash should not poison the registry.
            pass


def get_active_theme() -> NotebookTheme | None:
    """Return the currently registered :class:`NotebookTheme` (or ``None``)."""
    return _active_theme


def register_theme_listener(
    callback: Callable[[NotebookTheme | None], None],
) -> None:
    """Subscribe to active-theme changes.

    *callback* is invoked every time :func:`set_active_theme` is called.
    It receives the new theme (or ``None`` when the theme is cleared).
    """
    if not callable(callback):
        raise TypeError(
            "register_theme_listener: callback must be callable; "
            f"got {type(callback).__name__}"
        )
    if callback not in _theme_listeners:
        _theme_listeners.append(callback)


def unregister_theme_listener(
    callback: Callable[[NotebookTheme | None], None],
) -> None:
    """Remove a previously registered theme listener (no-op if absent)."""
    try:
        _theme_listeners.remove(callback)
    except ValueError:
        pass


# ---------------------------------------------------------------------------
# Shared helper used by every widget — returns a guaranteed-non-None theme
# so call sites never have to branch on ``is None``.
# ---------------------------------------------------------------------------


_FALLBACK_THEME = NotebookTheme(
    name="fallback",
    palette={
        "paper":     (250, 246, 235, 255),
        "ink":       (40, 40, 60, 255),
        "accent":    (220, 120, 160, 255),
        "highlight": (255, 240, 120, 200),
        "washi":     (180, 200, 230, 255),
        "heart":     (230, 80, 120, 255),
    },
    icon_fallback={
        "heart": "<3", "star": "*", "flower": "@",
        "sparkle": "+", "ribbon": "~", "default": "*",
    },
)


def resolve_theme() -> NotebookTheme:
    """Return the active theme, or a built-in fallback when none is set.

    Widgets call this at construction time so they can always read a
    palette / icon without checking for ``None``.
    """
    return _active_theme if _active_theme is not None else _FALLBACK_THEME


def clamp_rotation(degrees: Any) -> float:
    """Clamp *degrees* to ``[-15, 15]`` after validating it as a finite float.

    Sticker rotations outside this band look "fallen off" instead of
    "stuck on", so we hard-clamp to keep the visual contract.
    """
    deg = validate_finite_float("degrees", "clamp_rotation", degrees)
    if deg < -15.0:
        return -15.0
    if deg > 15.0:
        return 15.0
    return deg


def normalise_corner(corner: Any) -> str:
    """Validate *corner* against the ``{"TL","TR","BL","BR"}`` set."""
    s = validate_str("corner", "normalise_corner", corner, allow_empty=False)
    up = s.upper()
    if up not in ("TL", "TR", "BL", "BR"):
        raise ValueError(
            "normalise_corner: corner must be one of "
            f"'TL','TR','BL','BR'; got {s!r}"
        )
    return up


__all__ = [
    "NotebookTheme",
    "clamp_rotation",
    "get_active_theme",
    "normalise_corner",
    "register_theme_listener",
    "resolve_theme",
    "set_active_theme",
    "unregister_theme_listener",
]
