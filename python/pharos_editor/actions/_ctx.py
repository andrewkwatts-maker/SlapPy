"""Shared context-dict validation for :mod:`pharos_editor.actions` helpers.

Silent-acceptance hardening (BB2) — every public ``_fb_*`` action helper
accepts a single ``ctx: dict`` argument. Prior to BB2 the helpers all did
``ctx.get("key")`` unconditionally; when a caller passed anything other
than a mapping the ``.get`` attribute lookup either raised
``AttributeError`` (list) or the ``.get`` call silently returned ``None``
for every lookup (custom mock objects). That left broken callsites
silently no-op'ing forever.

:func:`ensure_ctx` gives the actions a single canonical rejection point.
It refuses ``None`` and non-mapping inputs with a clear ``TypeError`` and
lets ``dict`` subclasses (including :class:`collections.ChainMap`) through
unmodified.
"""
from __future__ import annotations

from typing import Any, Mapping


def ensure_ctx(fn: str, ctx: Any) -> Mapping[str, Any]:
    """Return *ctx* iff it is a mapping; raise :class:`TypeError` otherwise.

    Parameters
    ----------
    fn:
        Fully-qualified name of the caller (e.g. ``"save_project"``) so
        the error message points straight at the broken callsite.
    ctx:
        The value the caller passed. Anything except ``None``, a
        :class:`Mapping`, or a plain :class:`dict` is rejected.

    Raises
    ------
    TypeError
        If *ctx* is ``None`` or not a mapping.
    """
    if ctx is None:
        raise TypeError(f"{fn}: ctx must not be None")
    if not isinstance(ctx, Mapping):
        raise TypeError(
            f"{fn}: ctx must be a mapping (dict-like); "
            f"got {type(ctx).__name__}"
        )
    return ctx


__all__ = ["ensure_ctx"]
