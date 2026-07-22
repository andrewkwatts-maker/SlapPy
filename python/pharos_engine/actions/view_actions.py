"""View-lifecycle actions — layout reset.

Backs the ``view.reset_layout`` :class:`~pharos_engine.tool_router.ToolAction`
row. Restores the DEFAULT preset via
:func:`~pharos_engine.ui.editor.layout_presets.apply_preset` when a shell
handle is present; falls back to a headless "state-dict-only" reset
otherwise so tests can drive the callback without a live editor.
"""
from __future__ import annotations

from typing import Any

from ._ctx import ensure_ctx


def _get_shell(ctx: dict[str, Any]) -> Any:
    return ctx.get("shell")


def reset_layout(ctx: dict[str, Any]) -> dict[str, Any]:
    """Reset the editor layout to the DEFAULT preset.

    * When ``ctx["shell"]`` exposes ``apply_layout_preset(name)``, that
      method is called directly (matches the F1-hotkey path used by the
      Ctrl+0 menu binding).
    * Otherwise :func:`pharos_engine.ui.editor.layout_presets.apply_preset`
      is invoked with the (possibly headless) shell — this rebuilds the
      shell's ``_panel_layout_state`` dict even without DPG.

    Returns a small dict describing what happened so tests can assert on
    it: ``{"status": "reset", "preset": "default"}`` on success,
    ``{"status": "no_shell"}`` when the ctx has no shell handle at all.

    Raises
    ------
    TypeError
        If *ctx* is not a mapping, or ``ctx["preset"]`` is present but
        not a str.
    """
    ensure_ctx("reset_layout", ctx)
    preset_override = ctx.get("preset")
    if preset_override is not None and not isinstance(preset_override, str):
        raise TypeError(
            f"reset_layout: ctx['preset'] must be a str; "
            f"got {type(preset_override).__name__}"
        )
    shell = _get_shell(ctx)
    preset_name = ctx.get("preset", "default") or "default"
    if shell is None:
        return {"status": "no_shell", "preset": preset_name}

    # Preferred path — shell owns the "apply the named preset" contract.
    apply = getattr(shell, "apply_layout_preset", None)
    if callable(apply):
        try:
            apply(preset_name)
            return {"status": "reset", "preset": preset_name, "path": "shell"}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": str(exc)}

    # Headless fallback — call apply_preset directly so at least
    # ``_panel_layout_state`` is populated.
    try:
        from pharos_engine.ui.editor.layout_presets import apply_preset
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    try:
        preset = apply_preset(shell, preset_name)
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "message": str(exc)}
    return {
        "status": "reset",
        "preset": preset_name,
        "path": "apply_preset",
        "panel_count": len(preset.panels),
    }


__all__ = ["reset_layout"]
