"""Editor-only settings — the ``settings.ui`` section.

Keeps the editor's user-facing preferences off the engine ``Config`` so
shipping games don't pull in a UISettings dependency. Validation routes
through ``pharos_engine._validation`` to match every other public
boundary in the codebase.

Currently exposes a single :class:`UISettings` block read by
:meth:`pharos_editor.ui.editor.shell.EditorShell.setup` when wiring the
theme + creature subsystems. Future editor preferences (panel layout,
recent-files list, …) layer additional dataclasses on the same module.
"""
from __future__ import annotations

from dataclasses import dataclass

from pharos_engine._validation import validate_bool, validate_non_empty_str, validate_str


@dataclass
class UISettings:
    """User-facing editor UI preferences.

    Parameters
    ----------
    default_theme:
        Name of the theme that :meth:`EditorShell.setup` applies as
        soon as :func:`register_starter_themes` has run. Must be a
        registered theme; the shell falls back to the first available
        when the name does not resolve so a typo never blocks boot.
    creature_animations:
        Master switch for the woodland-creature subsystem. ``False``
        keeps the scheduler registered (so the panel still lists the
        roster) but skips :meth:`CreatureScheduler.tick` / ``render``.
    reduced_motion:
        Forward to :meth:`CreatureScheduler.set_reduced_motion`.
    easter_eggs:
        Forward to :meth:`CreatureScheduler.set_easter_eggs` (if the
        scheduler implements it). Persisted in :class:`ThemeSwitcherPanel`
        regardless so the toggle state survives a refresh.
    welcome_shown:
        Tracks whether the first-run :class:`NotebookWelcome` splash
        has already been dismissed. The shell consults this flag during
        :meth:`EditorShell.setup` to decide whether to surface the
        welcome modal on launch.
    last_opened_demo:
        Last demo id the user opened from the welcome panel — surfaced
        as a tiny "Resume…" hint when the welcome modal reappears via
        the Help menu. Empty when no demo has been opened yet.
    """

    default_theme: str = "teengirl_notebook"
    creature_animations: bool = True
    reduced_motion: bool = False
    easter_eggs: bool = True
    welcome_shown: bool = False
    last_opened_demo: str = ""

    def __post_init__(self) -> None:
        fn = "UISettings"
        validate_non_empty_str("default_theme", fn, self.default_theme)
        validate_bool("creature_animations", fn, self.creature_animations)
        validate_bool("reduced_motion", fn, self.reduced_motion)
        validate_bool("easter_eggs", fn, self.easter_eggs)
        validate_bool("welcome_shown", fn, self.welcome_shown)
        validate_str("last_opened_demo", fn, self.last_opened_demo, allow_empty=True)


__all__ = ["UISettings"]
