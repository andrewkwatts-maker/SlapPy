"""Starter theme content for the SlapPyEngine diary family.

Three :class:`ThemeSpec` constants ship here — the first concrete UI
themes built on the ``slappyengine.ui.theme`` primitive infrastructure
(``NineSlice``, ``SVGIcon``, ``ShaderEffect``). They are the user-facing
demonstration of the diary-family contract documented in
``docs/theme_diary_family_2026_06_03.md`` and the base TeenGirl Notebook
design at ``docs/theme_teengirl_notebook_2026_06_03.md``.

Public surface::

    from slappyengine.ui.theme.themes import (
        TEENGIRL_NOTEBOOK, COZY_DIARY, BULLET_JOURNAL,
        register_starter_themes,
    )

Calling :func:`register_starter_themes` registers all three constants
through ``slappyengine.ui.theme.register_theme`` in one shot — handy for
demos and headless tests that want every starter available without
listing them by hand.

The constants themselves carry no rendering state: each is a pure
:class:`ThemeSpec` whose palette + fonts + nine-slices + icons +
background_shader fields describe the look. Renderer integration lives
in the editor shell.
"""
from __future__ import annotations

from .. import register_theme
from ..theme_spec import ThemeSpec
from .bullet_journal import BULLET_JOURNAL
from .cozy_diary import COZY_DIARY
from .teengirl_notebook import TEENGIRL_NOTEBOOK


def register_starter_themes() -> list[str]:
    """Register all three starter :class:`ThemeSpec` constants.

    Returns the list of theme names registered (in insertion order) so
    callers can chain a follow-up ``apply_theme(name)`` without having
    to re-import each constant.
    """
    names: list[str] = []
    for theme in (TEENGIRL_NOTEBOOK, COZY_DIARY, BULLET_JOURNAL):
        if not isinstance(theme, ThemeSpec):  # pragma: no cover - defensive
            raise TypeError(
                "register_starter_themes: each constant must be a "
                f"ThemeSpec; got {type(theme).__name__}"
            )
        register_theme(theme)
        names.append(theme.name)
    return names


__all__ = [
    "BULLET_JOURNAL",
    "COZY_DIARY",
    "TEENGIRL_NOTEBOOK",
    "register_starter_themes",
]
