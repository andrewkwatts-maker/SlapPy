"""Optional Dear PyGui bridge — lets the editor host an :class:`ImmediateUI`.

The runtime UI is designed to be renderer-agnostic (the HH4 renderer
draws :class:`~.draw_command.DrawCommand` records directly). Inside the
editor, though, it's nice to preview a game HUD without spinning up a
game window — that's what this bridge is for.

The bridge is a *soft* integration point: importing this module does not
import Dear PyGui. Calling :func:`run_immediate_in_dpg` does, and raises
a clear ``ImportError`` if DPG isn't installed. The rest of the runtime
subpackage keeps working with zero DPG contact.
"""
from __future__ import annotations

from typing import Any


def _import_dpg() -> Any:
    """Import Dear PyGui or raise a friendly ImportError."""
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - defensive
        raise ImportError(
            "run_immediate_in_dpg requires Dear PyGui: "
            "pip install SlapPyEngine[editor]"
        ) from exc
    return dpg


def run_immediate_in_dpg(ui: Any, parent_tag: str) -> None:
    """Replay ``ui.end_frame()`` draws into a DPG draw layer.

    Parameters
    ----------
    ui:
        A frame-closed :class:`~.immediate_ui.ImmediateUI` — call
        :meth:`ImmediateUI.end_frame` before passing it here (or pass
        the pre-computed command list yourself; this helper accepts
        either).
    parent_tag:
        DPG tag of a ``draw_layer`` or ``drawlist`` under which the
        commands are appended. The tag must exist before the call.

    Raises
    ------
    ImportError
        If Dear PyGui is not installed.
    ValueError
        If *parent_tag* doesn't correspond to a live DPG item.
    """
    dpg = _import_dpg()
    if not isinstance(parent_tag, str) or not parent_tag:
        raise ValueError(
            "run_immediate_in_dpg: parent_tag must be a non-empty str"
        )
    if not dpg.does_item_exist(parent_tag):
        raise ValueError(
            f"run_immediate_in_dpg: parent_tag {parent_tag!r} does not "
            "exist in the DPG context"
        )
    # Accept either an ImmediateUI (still in-frame → close it) or a list.
    if hasattr(ui, "end_frame") and hasattr(ui, "_in_frame"):
        if ui._in_frame:
            commands = ui.end_frame()
        else:
            # Assume the caller cached the last draw list on the UI.
            commands = getattr(ui, "_last_commands", [])
    else:
        commands = list(ui)

    for cmd in commands:
        _emit_dpg(dpg, cmd, parent_tag)


def _to_rgba_255(color) -> tuple[int, int, int, int]:
    r = int(round(float(color[0]) * 255))
    g = int(round(float(color[1]) * 255))
    b = int(round(float(color[2]) * 255))
    a = int(round(float(color[3]) * 255))
    return (max(0, min(255, r)), max(0, min(255, g)),
            max(0, min(255, b)), max(0, min(255, a)))


def _emit_dpg(dpg: Any, cmd: Any, parent_tag: str) -> None:
    """Convert one :class:`DrawCommand` into a DPG draw call."""
    color = _to_rgba_255(cmd.color)
    px, py = cmd.position
    sw, sh = cmd.size
    if cmd.kind == "rect":
        if sw <= 0 or sh <= 0:
            return
        dpg.draw_rectangle(
            (px, py), (px + sw, py + sh),
            color=color, fill=color, parent=parent_tag,
        )
    elif cmd.kind == "text":
        if cmd.text:
            dpg.draw_text(
                (px, py), cmd.text, color=color, size=14, parent=parent_tag,
            )
    elif cmd.kind == "line":
        dpg.draw_line(
            (px, py), (px + sw, py + sh),
            color=color, thickness=1, parent=parent_tag,
        )
    elif cmd.kind == "circle":
        radius = 0.5 * max(sw, sh)
        centre = (px + sw * 0.5, py + sh * 0.5)
        dpg.draw_circle(
            centre, radius, color=color, fill=color, parent=parent_tag,
        )
    elif cmd.kind == "textured_quad" and cmd.texture_id is not None:
        # Best-effort — DPG's image handles are opaque so we just draw a
        # rectangle in the tint colour when the texture bind fails.
        try:
            dpg.draw_image(
                cmd.texture_id, (px, py), (px + sw, py + sh),
                parent=parent_tag,
            )
        except Exception:  # pragma: no cover - defensive
            dpg.draw_rectangle(
                (px, py), (px + sw, py + sh),
                color=color, fill=color, parent=parent_tag,
            )


__all__ = ["run_immediate_in_dpg"]
