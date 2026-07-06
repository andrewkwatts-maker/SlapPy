"""Renderer feature-toggle actions — SSAO + CSM shadow map on/off.

Backs the ``render.enable_ssao`` / ``render.enable_shadows``
:class:`~slappyengine.tool_router.ToolAction` rows added by the MM6
STUB-triage sprint tick (round 14 after JJ6 + KK7 + LL landings).

These delegate to the Nova3D-parity renderer surface added by JJ7 (CSM
shadow map pass) and KK3 (SSAO / HBAO pass). The pass objects themselves
carry no ``enabled`` flag — the renderer / shell owns the toggle so a
missed frame doesn't leak state into the AO / shadow textures. This
helper is *headless-safe*: when no renderer is reachable it still writes
the intended state onto the shell so tests can assert on the toggle
semantics without a real GPU.

Resolution order
----------------

For each toggle the helper looks for a target in this order:

1. ``ctx["renderer"]`` — explicit override (tests + editor's viewport
   panel).
2. ``ctx["shell"]._renderer`` / ``ctx["shell"]._viewport_panel._renderer``
   — the running editor.
3. ``ctx["shell"]`` alone — headless fallback where the flag is stored
   on the shell object directly so a follow-up ``render.enable_ssao`` /
   ``render.enable_shadows`` still round-trips.

Write path (each attempted in order until one succeeds):

* ``renderer.enable_ssao(bool)`` / ``renderer.enable_shadows(bool)``
  method call — the canonical Nova3D API.
* ``renderer.ssao_enabled`` / ``renderer.shadows_enabled`` attribute
  write — matches the passes that expose a public flag.
* ``renderer._ssao_enabled`` / ``renderer._shadows_enabled`` underscored
  fallback used by the log-only stub renderer.
* Shell attribute write (``_ssao_enabled`` / ``_shadows_enabled``) as
  the last-ditch headless fallback.

Return contract
---------------

* ``{"status": "toggled", "target": "ssao"|"shadows",
   "enabled": bool, "previous": bool, "path": "renderer"|"shell"}`` —
  the flag was flipped. ``enabled`` is the new value; ``path`` names
  where the write landed so the shell status bar can hint at whether the
  pipeline actually saw the change.
* ``{"status": "no_target"}`` — no renderer + no shell in ``ctx``, so
  the toggle has nowhere to land. Distinct from ``"unchanged"`` so
  callers can render a "no viewport bound" toast.
* ``{"status": "unchanged", "target": ..., "enabled": bool}`` — the
  requested ``ctx["enabled"]`` matched the current state.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


_SSAO_METHOD = "enable_ssao"
_SHADOWS_METHOD = "enable_shadows"
_SSAO_ATTR = "ssao_enabled"
_SHADOWS_ATTR = "shadows_enabled"
_SSAO_UNDER = "_ssao_enabled"
_SHADOWS_UNDER = "_shadows_enabled"


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def _get_renderer(ctx: dict[str, Any]) -> Any:
    """Return the first renderer-like handle reachable from *ctx*."""
    override = ctx.get("renderer")
    if override is not None:
        return override
    shell = _get_shell(ctx)
    if shell is None:
        return None
    # Direct slot on the shell — Nova3D convention.
    r = getattr(shell, "_renderer", None)
    if r is not None:
        return r
    # Viewport panel wrapper — Nova3D editor layout.
    panel = getattr(shell, "_viewport_panel", None)
    if panel is None:
        return None
    return getattr(panel, "_renderer", None) or getattr(panel, "renderer", None)


def _read_flag(target: Any, attr_public: str, attr_under: str, default: bool) -> bool:
    """Return the current on/off state stored on *target*."""
    if target is None:
        return default
    if hasattr(target, attr_public):
        try:
            return bool(getattr(target, attr_public))
        except Exception:  # noqa: BLE001
            return default
    if hasattr(target, attr_under):
        try:
            return bool(getattr(target, attr_under))
        except Exception:  # noqa: BLE001
            return default
    return default


def _write_flag(
    renderer: Any,
    shell: Any,
    method_name: str,
    attr_public: str,
    attr_under: str,
    value: bool,
) -> tuple[bool, str]:
    """Try renderer method → renderer attr → shell attr in order.

    Returns ``(effective_value, path)`` — ``path`` is one of
    ``"renderer"`` / ``"shell"`` / ``"fallback"``.
    """
    # 1. Renderer method call (canonical Nova3D API).
    if renderer is not None:
        method = getattr(renderer, method_name, None)
        if callable(method):
            try:
                method(value)
                # Mirror onto the flag attribute so subsequent reads see
                # the same state without re-dispatching the method.
                try:
                    setattr(renderer, attr_public, value)
                except Exception:  # noqa: BLE001
                    pass
                return value, "renderer"
            except Exception:  # noqa: BLE001
                pass
        # 2. Renderer attribute write.
        for attr in (attr_public, attr_under):
            if hasattr(renderer, attr) or True:
                try:
                    setattr(renderer, attr, value)
                    return value, "renderer"
                except Exception:  # noqa: BLE001
                    continue
    # 3. Shell attribute write — headless fallback.
    if shell is not None:
        try:
            setattr(shell, attr_under, value)
            return value, "shell"
        except Exception:  # noqa: BLE001
            pass
    return value, "fallback"


def _resolve_enabled(ctx: dict[str, Any], current: bool) -> bool:
    """Pick the requested new state from ``ctx["enabled"]`` (default: toggle)."""
    if "enabled" in ctx:
        want = ctx.get("enabled")
        if isinstance(want, bool):
            return want
        try:
            return bool(want)
        except Exception:  # noqa: BLE001
            return not current
    return not current


def enable_ssao(ctx: dict[str, Any]) -> dict[str, Any]:
    """Toggle the SSAO (KK3) pass on the current renderer.

    Parameters
    ----------
    ctx:
        Router context. Consumed keys:

        * ``renderer`` (optional) — explicit override. Any object with
          ``enable_ssao(bool)`` / ``ssao_enabled`` / ``_ssao_enabled``.
        * ``shell`` (optional) — resolved as documented in the module
          docstring.
        * ``enabled`` (optional bool) — force the new state. When omitted
          the flag is flipped.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("enable_ssao", ctx)
    shell = _get_shell(ctx)
    renderer = _get_renderer(ctx)
    if renderer is None and shell is None:
        return {"status": "no_target"}
    current = _read_flag(renderer, _SSAO_ATTR, _SSAO_UNDER, default=False)
    if renderer is None:
        current = _read_flag(shell, _SSAO_ATTR, _SSAO_UNDER, default=current)
    want = _resolve_enabled(ctx, current)
    if want == current:
        return {
            "status": "unchanged",
            "target": "ssao",
            "enabled": bool(current),
        }
    effective, path = _write_flag(
        renderer, shell, _SSAO_METHOD, _SSAO_ATTR, _SSAO_UNDER, want,
    )
    return {
        "status": "toggled",
        "target": "ssao",
        "enabled": bool(effective),
        "previous": bool(current),
        "path": path,
    }


def enable_shadows(ctx: dict[str, Any]) -> dict[str, Any]:
    """Toggle the CSM shadow-map (JJ7) pass on the current renderer.

    Same resolution rules as :func:`enable_ssao`. See the module
    docstring for the resolution / write order.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping.
    """
    ensure_ctx("enable_shadows", ctx)
    shell = _get_shell(ctx)
    renderer = _get_renderer(ctx)
    if renderer is None and shell is None:
        return {"status": "no_target"}
    current = _read_flag(renderer, _SHADOWS_ATTR, _SHADOWS_UNDER, default=False)
    if renderer is None:
        current = _read_flag(shell, _SHADOWS_ATTR, _SHADOWS_UNDER, default=current)
    want = _resolve_enabled(ctx, current)
    if want == current:
        return {
            "status": "unchanged",
            "target": "shadows",
            "enabled": bool(current),
        }
    effective, path = _write_flag(
        renderer, shell, _SHADOWS_METHOD, _SHADOWS_ATTR, _SHADOWS_UNDER, want,
    )
    return {
        "status": "toggled",
        "target": "shadows",
        "enabled": bool(effective),
        "previous": bool(current),
        "path": path,
    }


__all__ = [
    "enable_ssao",
    "enable_shadows",
]
