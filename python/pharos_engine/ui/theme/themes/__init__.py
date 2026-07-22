"""Starter theme content for the SlapPyEngine diary family.

Six :class:`ThemeSpec` constants ship here — the concrete UI themes
built on the ``pharos_engine.ui.theme`` primitive infrastructure
(``NineSlice``, ``SVGIcon``, ``ShaderEffect``). They are the user-facing
demonstration of the diary-family contract documented in
``docs/theme_diary_family_2026_06_03.md`` and the base TeenGirl Notebook
design at ``docs/theme_teengirl_notebook_2026_06_03.md``.

Public surface::

    from pharos_engine.ui.theme.themes import (
        TEENGIRL_NOTEBOOK, COZY_DIARY, BULLET_JOURNAL,
        SCRAPBOOK_SUMMER, COTTAGECORE_GARDEN, KAWAII_PLANNER,
        register_starter_themes, register_all_themes,
    )

Calling :func:`register_all_themes` registers all six constants through
``pharos_engine.ui.theme.register_theme`` in one shot — handy for demos
and headless tests that want every variant available without listing
them by hand. :func:`register_starter_themes` is the original three-way
helper kept for backwards compatibility; it now delegates to
:func:`register_all_themes` so existing callers pick up the full family.

The constants themselves carry no rendering state: each is a pure
:class:`ThemeSpec` whose palette + fonts + nine-slices + icons +
background_shader fields describe the look. Renderer integration lives
in the editor shell.
"""
from __future__ import annotations

from .. import register_theme
from ..theme_spec import ThemeSpec
from .bullet_journal import BULLET_JOURNAL
from .cottagecore_garden import COTTAGECORE_GARDEN
from .cozy_diary import COZY_DIARY
from .kawaii_planner import KAWAII_PLANNER
from .scrapbook_summer import SCRAPBOOK_SUMMER
from .teengirl_notebook import TEENGIRL_NOTEBOOK


# Insertion order is the family rollout order: the three original
# starters first, then the three v0.4 Phase C additions.
_ALL_THEMES: tuple[ThemeSpec, ...] = (
    TEENGIRL_NOTEBOOK,
    COZY_DIARY,
    BULLET_JOURNAL,
    SCRAPBOOK_SUMMER,
    COTTAGECORE_GARDEN,
    KAWAII_PLANNER,
)


def register_all_themes() -> list[str]:
    """Register every :class:`ThemeSpec` constant in this subpackage.

    Returns the list of theme names registered (in insertion order) so
    callers can chain a follow-up ``apply_theme(name)`` without having
    to re-import each constant. Idempotent — calling it twice simply
    overwrites the registry entries with the same constants.
    """
    names: list[str] = []
    for theme in _ALL_THEMES:
        if not isinstance(theme, ThemeSpec):  # pragma: no cover - defensive
            raise TypeError(
                "register_all_themes: each constant must be a "
                f"ThemeSpec; got {type(theme).__name__}"
            )
        register_theme(theme)
        names.append(theme.name)
    return names


def register_starter_themes() -> list[str]:
    """Register every starter :class:`ThemeSpec` constant.

    Backwards-compatible alias for :func:`register_all_themes` — the
    original helper registered only the first three variants; it now
    registers the full six-theme diary family so existing callers
    automatically pick up the v0.4 Phase C additions.
    """
    return register_all_themes()


__all__ = [
    "BULLET_JOURNAL",
    "COTTAGECORE_GARDEN",
    "COZY_DIARY",
    "KAWAII_PLANNER",
    "SCRAPBOOK_SUMMER",
    "TEENGIRL_NOTEBOOK",
    "register_all_themes",
    "register_starter_themes",
]
