"""Runtime-side theme palette — soft-imports :class:`ThemeSpec` when present.

The editor-side :mod:`slappyengine.ui.theme` package ships full palettes,
nine-slice borders, page linings, and WGSL background shaders. Games
that want the whole stack can import it and hand the resulting theme id
to :meth:`RuntimeTheme.from_diary_theme` — the runtime layer then reads
the six colour tokens it needs from :class:`SemanticTokens`.

Games that don't want the editor dep can just construct
:class:`RuntimeTheme` directly; the built-in defaults are a neutral dark
grey / blue-accent scheme that looks clean without any theming layer at
all.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


RGBA = tuple[float, float, float, float]


def _clone_rgba(value) -> RGBA:
    if not hasattr(value, "__len__") or len(value) != 4:
        raise TypeError(
            f"RuntimeTheme: colour must be a 4-sequence; got {value!r}"
        )
    return (float(value[0]), float(value[1]), float(value[2]), float(value[3]))


# ---------------------------------------------------------------------------
# Default palette — used when no ThemeSpec is loaded.
# ---------------------------------------------------------------------------

_DEFAULT_TEXT: RGBA = (0.92, 0.94, 0.98, 1.0)
_DEFAULT_BUTTON: RGBA = (0.24, 0.32, 0.48, 1.0)
_DEFAULT_HOVER: RGBA = (0.34, 0.44, 0.62, 1.0)
_DEFAULT_BG: RGBA = (0.08, 0.09, 0.12, 1.0)
_DEFAULT_PANEL_BG: RGBA = (0.14, 0.16, 0.20, 0.92)
_DEFAULT_PANEL_BORDER: RGBA = (0.30, 0.34, 0.42, 1.0)


@dataclass
class RuntimeTheme:
    """Runtime-side palette — six colour tokens the widget layer reads.

    Attributes
    ----------
    text_color:
        Ink colour for labels and text-only draws.
    button_color:
        Idle button fill.
    hover_color:
        Button fill under mouse hover.
    bg_color:
        Full-frame background clear colour.
    panel_bg_color:
        Panel body fill (typically semi-transparent).
    panel_border_color:
        1 px panel border stroke.
    """

    text_color: RGBA = field(default_factory=lambda: _DEFAULT_TEXT)
    button_color: RGBA = field(default_factory=lambda: _DEFAULT_BUTTON)
    hover_color: RGBA = field(default_factory=lambda: _DEFAULT_HOVER)
    bg_color: RGBA = field(default_factory=lambda: _DEFAULT_BG)
    panel_bg_color: RGBA = field(default_factory=lambda: _DEFAULT_PANEL_BG)
    panel_border_color: RGBA = field(default_factory=lambda: _DEFAULT_PANEL_BORDER)

    def __post_init__(self) -> None:
        for name in (
            "text_color",
            "button_color",
            "hover_color",
            "bg_color",
            "panel_bg_color",
            "panel_border_color",
        ):
            setattr(self, name, _clone_rgba(getattr(self, name)))

    # ------------------------------------------------------------------
    # ThemeSpec bridge — soft-imported so games can skip the editor dep.
    # ------------------------------------------------------------------

    @classmethod
    def from_diary_theme(cls, theme_id: str) -> "RuntimeTheme":
        """Build a :class:`RuntimeTheme` from a registered :class:`ThemeSpec`.

        Attempts (in order):

        1. Look up ``theme_id`` in the ``slappyengine.ui.theme`` registry.
        2. If not registered, call ``register_all_themes()`` and retry.
        3. If neither succeeds, fall back to the built-in defaults so the
           game keeps running.

        The lookup is soft — if the whole ``slappyengine.ui.theme``
        subpackage is unavailable (bare wheel, missing PIL, etc.), a
        default :class:`RuntimeTheme` is returned instead of raising.
        """
        if not isinstance(theme_id, str) or not theme_id:
            raise TypeError(
                "RuntimeTheme.from_diary_theme: theme_id must be a "
                f"non-empty string; got {theme_id!r}"
            )
        spec = _try_lookup_theme(theme_id)
        if spec is None:
            return cls()
        return cls._from_theme_spec(spec)

    @classmethod
    def _from_theme_spec(cls, spec: Any) -> "RuntimeTheme":
        """Read the six runtime tokens from a :class:`ThemeSpec` instance."""
        semantic = getattr(spec, "semantic", None)
        if semantic is None:
            return cls()

        def _pull(name: str, default: RGBA) -> RGBA:
            col = getattr(semantic, name, None)
            if col is None:
                return default
            as_float = getattr(col, "as_float_tuple", None)
            if callable(as_float):
                r, g, b, a = as_float()
                return (float(r), float(g), float(b), float(a))
            return default

        return cls(
            text_color=_pull("text_primary", _DEFAULT_TEXT),
            button_color=_pull("primary", _DEFAULT_BUTTON),
            hover_color=_pull("surface_hover", _DEFAULT_HOVER),
            bg_color=_pull("background", _DEFAULT_BG),
            panel_bg_color=_pull("surface", _DEFAULT_PANEL_BG),
            panel_border_color=_pull("border", _DEFAULT_PANEL_BORDER),
        )


def _try_lookup_theme(theme_id: str) -> Any | None:
    """Look up ``theme_id`` in the editor theme registry; returns None on miss."""
    try:
        from slappyengine.ui import theme as _theme_pkg  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - defensive soft-import
        return None
    try:
        registered = _theme_pkg.list_registered_themes()
    except Exception:  # pragma: no cover - defensive
        registered = []
    if theme_id not in registered:
        # One-shot lazy bake — the starter theme family lives under
        # slappyengine.ui.theme.themes and self-registers on import.
        try:
            from slappyengine.ui.theme import themes as _themes_pkg  # type: ignore
            _themes_pkg.register_all_themes()
        except Exception:  # pragma: no cover - defensive
            return None
        try:
            registered = _theme_pkg.list_registered_themes()
        except Exception:  # pragma: no cover - defensive
            registered = []
        if theme_id not in registered:
            return None
    try:
        # Registry lookup — use the private map because the public API
        # only exposes get_active_theme() which requires apply_theme().
        return _theme_pkg._REGISTRY.get(theme_id)  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - defensive
        return None


__all__ = ["RuntimeTheme"]
