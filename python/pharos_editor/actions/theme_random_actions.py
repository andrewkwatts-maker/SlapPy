"""Random-theme action — pick a random registered theme.

Backs the ``theme.random`` :class:`~pharos_editor.tool_router.ToolAction`
row added by the EE1 STUB-triage sprint tick (round 8 after
X3 / Y1 / Z7 / AA1 / BB1 / CC1 / DD1).

Sibling to :func:`pharos_editor.actions.theme_actions.cycle_theme` and
:func:`pharos_editor.actions.theme_cycle_reverse_actions.cycle_theme_reverse`.
Prefers a shell hook when present (``shell.set_theme(name)`` /
``shell.apply_theme(name)``), otherwise walks
:func:`pharos_editor.ui.theme.list_registered_themes` and picks a random
entry via :func:`random.choice`. To make the pick deterministic in
tests, ``ctx["rng"]`` accepts a :class:`random.Random` instance and
``ctx["exclude_current"]`` (default ``True``) skips the currently
active theme so a click never no-ops.

Return contract
---------------

* ``{"status": "randomised", "theme": "<name>", "path": "shell"}`` when
  a shell hook was invoked.
* ``{"status": "randomised", "theme": "<name>", "path": "fallback"}``
  when the headless registry lookup landed a theme.
* ``{"status": "no_themes"}`` when the registry is empty.
* ``{"status": "single_theme", "theme": "<name>"}`` when there's exactly
  one registered theme and ``exclude_current`` is truthy — the caller
  can then toast "no other themes available" without special-casing.
"""
from __future__ import annotations

import random
from typing import Any

from . import theme_actions as _theme_actions
from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _rng(ctx: dict[str, Any]) -> random.Random:
    """Return the RNG to sample from — accepts ``ctx["rng"]`` for tests."""
    override = ctx.get("rng")
    if isinstance(override, random.Random):
        return override
    return random.Random()


def _current_theme(shell: Any) -> str | None:
    """Best-effort read of the shell's current theme id."""
    if shell is None:
        return _theme_actions._THEME_CURSOR
    settings = getattr(shell, "_ui_settings", None)
    if settings is not None:
        theme = getattr(settings, "default_theme", None)
        if isinstance(theme, str) and theme:
            return theme
    theme = getattr(shell, "_current_theme", None)
    if isinstance(theme, str) and theme:
        return theme
    return _theme_actions._THEME_CURSOR


def _apply_via_shell(shell: Any, name: str) -> bool:
    """Best-effort apply of *name* via a shell hook. Returns True on success."""
    for hook in ("set_theme", "apply_theme"):
        method = getattr(shell, hook, None)
        if callable(method):
            try:
                method(name)
                return True
            except Exception:  # noqa: BLE001
                return False
    return False


def random_theme(ctx: dict[str, Any]) -> dict[str, Any]:
    """Pick a random registered theme and apply it.

    Consumed ctx keys:

    * ``shell`` (optional): editor shell — receives the ``set_theme`` /
      ``apply_theme`` call when present.
    * ``rng`` (optional :class:`random.Random`): deterministic sampler
      for tests.
    * ``exclude_current`` (optional bool, default ``True``): skip the
      currently active theme so a click never no-ops.
    * ``themes`` (optional list[str]): override the registry — tests use
      this to constrain the sampling pool.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("random_theme", ctx)

    override = ctx.get("themes")
    if isinstance(override, (list, tuple)) and override:
        themes = [t for t in override if isinstance(t, str)]
    else:
        try:
            from pharos_editor.ui.theme import list_registered_themes
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}
        themes = list(list_registered_themes())

    if not themes:
        return {"status": "no_themes"}

    shell = _get_shell(ctx)
    exclude = ctx.get("exclude_current", True)
    current = _current_theme(shell)

    candidates = list(themes)
    if exclude and current in candidates:
        candidates = [t for t in candidates if t != current]
        if not candidates:
            # Only one registered theme — surface a distinct status so
            # the caller can render a "no other themes available" toast.
            return {"status": "single_theme", "theme": current}

    picked = _rng(ctx).choice(candidates)
    _theme_actions._THEME_CURSOR = picked

    if shell is not None and _apply_via_shell(shell, picked):
        return {"status": "randomised", "theme": picked, "path": "shell"}

    # Headless fallback — call ``apply_theme`` on the registry.
    try:
        from pharos_editor.ui.theme import apply_theme
    except Exception:  # noqa: BLE001
        apply_theme = None  # type: ignore[assignment]
    if apply_theme is not None:
        try:
            apply_theme(picked)
        except Exception:  # noqa: BLE001
            pass
    return {"status": "randomised", "theme": picked, "path": "fallback"}


__all__ = ["random_theme"]
