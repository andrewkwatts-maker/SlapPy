"""Notebook-themed window-title decorator.

The :class:`EditorShell` updates the OS viewport title via this single
formatter so the unsaved-flower / saved-heart sticker, the scene name
and the active theme name all surface in the OS task switcher.

Format
------
Saved:    ``"SlapPy Notebook -- <scene> heart  | <theme>"``
Unsaved:  ``"SlapPy Notebook -- <scene> flower  | <theme>"``

The sticker glyphs are ASCII-safe by default (``heart`` / ``flower``) so
the title renders on every OS shell font; a caller that wants the brief's
Unicode hearts (♡ / ✿) can pass ``use_unicode=True``.

This module is intentionally framework-free: no DPG, no theme registry,
no creature scheduler. Tests pin the format with plain string equality.
"""
from __future__ import annotations

from pharos_engine._validation import (
    validate_bool,
    validate_non_empty_str,
    validate_str,
)


# ASCII fallback glyphs (always renderable in OS shells).
_ASCII_SAVED_GLYPH: str = "heart"
_ASCII_UNSAVED_GLYPH: str = "flower"

# Unicode glyphs preferred by the brief.
_UNICODE_SAVED_GLYPH: str = "♡"     # WHITE HEART SUIT - small clean heart
_UNICODE_UNSAVED_GLYPH: str = "✿"   # BLACK FLORETTE - notebook flower

# Branding prefix — tests pin this so a future rename has to bump the
# constant + the assertion in lock-step.
_BRAND_PREFIX: str = "SlapPy Notebook"

# Em-dash separator + theme-segment separator.
_TITLE_SEPARATOR: str = " — "   # em dash
_THEME_SEPARATOR: str = "  |  "


def saved_glyph(use_unicode: bool = False) -> str:
    """Return the sticker glyph drawn next to a saved scene name."""
    return _UNICODE_SAVED_GLYPH if use_unicode else _ASCII_SAVED_GLYPH


def unsaved_glyph(use_unicode: bool = False) -> str:
    """Return the sticker glyph drawn next to an unsaved scene name."""
    return _UNICODE_UNSAVED_GLYPH if use_unicode else _ASCII_UNSAVED_GLYPH


#: Placeholder rendered when no project is loaded.
_NO_PROJECT_PLACEHOLDER: str = "(no project)"

#: Sentinel for the ``project_name`` kwarg so callers can pass an
#: explicit ``None`` (meaning "no project loaded → placeholder") and
#: still distinguish that from "not specified, behave like the legacy
#: API" (the value used by every test predating the M6 sprint).
_PROJECT_NAME_OMITTED = object()


def format_window_title(
    scene_name: str,
    saved: bool,
    theme_name: str,
    *,
    use_unicode: bool = False,
    project_name: "str | None | object" = _PROJECT_NAME_OMITTED,
) -> str:
    """Return e.g. ``'SlapPy Notebook -- my_scene heart  | teengirl_notebook'``.

    Three call shapes:

    1. **Legacy** — ``format_window_title(scene, saved, theme)`` (no
       ``project_name`` keyword) emits the pre-M6 format
       ``"SlapPy Notebook -- <scene> heart  | <theme>"``.
    2. **No project** — ``project_name=None`` collapses to
       ``"SlapPy Notebook -- (no project)"``.
    3. **Project loaded** — ``project_name="My Game"`` weaves the
       project name in:
       ``"SlapPy Notebook -- My Game -- <scene> heart  | <theme>"``.

    The legacy path stays untouched so every test predating this sprint
    keeps passing without modification.

    Parameters
    ----------
    scene_name:
        Non-empty scene identifier — usually the file name of the
        current scene without the ``.scene`` suffix. Ignored when
        *project_name* is ``None``.
    saved:
        ``True`` to display the saved sticker, ``False`` for the
        unsaved flower. Ignored when *project_name* is ``None``.
    theme_name:
        Non-empty active theme id (e.g. ``"teengirl_notebook"``). Surfaced
        in the OS title so the user can tell which mood the editor is in
        from the task switcher. Ignored when *project_name* is ``None``.
    use_unicode:
        When ``True`` the heart / flower glyphs are emitted as Unicode
        characters (``♡`` / ``✿``); when ``False`` (the
        default) the words ``"heart"`` / ``"flower"`` are used so the
        title renders on every OS shell font.
    project_name:
        Optional project display name (``Project.metadata.name``).
        Omit entirely for the legacy format; pass ``None`` to render
        the "no project" placeholder.

    Raises
    ------
    TypeError / ValueError
        Routed through the shared validators for ``scene_name`` /
        ``theme_name`` / ``saved`` / ``project_name``.
    """
    fn = "format_window_title"
    validate_bool("use_unicode", fn, use_unicode)

    if project_name is None:
        # Explicit "no project" — collapsed placeholder format.
        return f"{_BRAND_PREFIX}{_TITLE_SEPARATOR}{_NO_PROJECT_PLACEHOLDER}"

    validate_non_empty_str("scene_name", fn, scene_name)
    validate_bool("saved", fn, saved)
    validate_non_empty_str("theme_name", fn, theme_name)

    glyph = saved_glyph(use_unicode) if saved else unsaved_glyph(use_unicode)

    if project_name is _PROJECT_NAME_OMITTED:
        # Legacy three-arg call — keep the historic format.
        return (
            f"{_BRAND_PREFIX}{_TITLE_SEPARATOR}{scene_name} {glyph}"
            f"{_THEME_SEPARATOR}{theme_name}"
        )

    validate_non_empty_str("project_name", fn, project_name)
    return (
        f"{_BRAND_PREFIX}{_TITLE_SEPARATOR}{project_name}"
        f"{_TITLE_SEPARATOR}{scene_name} {glyph}"
        f"{_THEME_SEPARATOR}{theme_name}"
    )


def parse_window_title(title: str) -> dict[str, str | bool | None]:
    """Reverse :func:`format_window_title` (for tests + tooling diagnostics).

    Returns a dict with the keys ``scene_name`` / ``saved`` /
    ``theme_name`` / ``use_unicode`` / ``project_name``. The
    ``project_name`` key is ``None`` for no-project titles and a string
    otherwise. Raises ``ValueError`` if *title* doesn't look like a
    notebook editor title.
    """
    title = validate_str(
        "title", "parse_window_title", title, allow_empty=False,
    )
    if not title.startswith(_BRAND_PREFIX + _TITLE_SEPARATOR):
        raise ValueError(
            f"parse_window_title: title must start with "
            f"{(_BRAND_PREFIX + _TITLE_SEPARATOR)!r}; got {title!r}"
        )
    head = title[len(_BRAND_PREFIX) + len(_TITLE_SEPARATOR):]
    # ── No-project sentinel ──
    if head == _NO_PROJECT_PLACEHOLDER:
        return {
            "scene_name": "",
            "saved": True,
            "theme_name": "",
            "use_unicode": False,
            "project_name": None,
        }
    if _THEME_SEPARATOR not in head:
        raise ValueError(
            f"parse_window_title: missing theme separator in {title!r}"
        )
    scene_part, theme_name = head.rsplit(_THEME_SEPARATOR, 1)
    # The scene part is "<project> -- <scene_name> <glyph>" (when a
    # project is loaded) or "<scene_name> <glyph>" (legacy / no project).
    project_name: str | None = None
    if _TITLE_SEPARATOR in scene_part:
        project_name, scene_part = scene_part.split(_TITLE_SEPARATOR, 1)
    if " " not in scene_part:
        raise ValueError(
            f"parse_window_title: missing scene/glyph separator in {title!r}"
        )
    scene_name, glyph = scene_part.rsplit(" ", 1)
    use_unicode = glyph in (_UNICODE_SAVED_GLYPH, _UNICODE_UNSAVED_GLYPH)
    saved = glyph in (_ASCII_SAVED_GLYPH, _UNICODE_SAVED_GLYPH)
    return {
        "scene_name": scene_name,
        "saved": saved,
        "theme_name": theme_name,
        "use_unicode": use_unicode,
        "project_name": project_name,
    }


__all__ = [
    "format_window_title",
    "parse_window_title",
    "saved_glyph",
    "unsaved_glyph",
]
