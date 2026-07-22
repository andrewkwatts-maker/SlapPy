"""imgui-style immediate-mode UI for the game tick loop.

The :class:`ImmediateUI` class holds per-frame input state (mouse
position, mouse button, keys down) and emits :class:`DrawCommand`
records as widgets are invoked. A game frame looks like::

    ui.begin_frame(dt, mouse_pos=(mx, my), keys_down=set(), mouse_down=clicked)
    if ui.button("quit", "Quit", (10, 10), (80, 24)):
        game.request_quit()
    ui.label("score", f"Score: {score}", (10, 40))
    ui.progress_bar("hp_bar", (10, 70), (200, 12), hp / max_hp)
    draw_cmds = ui.end_frame()
    renderer.execute(draw_cmds)

Widget invocations return the semantic value (True on click, the current
slider value, the current checkbox state). Persistent state (which
button is being pressed, panel drag offsets, checkbox values) lives on
the :class:`ImmediateUI` instance keyed by widget id, so a game can
skip the ceremony of building its own widget-state model.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator

from .draw_command import DrawCommand
from .runtime_theme import RuntimeTheme
from .text_layout import measure_text


# ---------------------------------------------------------------------------
# Draw layers (see DrawCommand.z_order docstring)
# ---------------------------------------------------------------------------

_Z_PANEL_BG: int = 10
_Z_PANEL_BORDER: int = 11
_Z_WIDGET_BG: int = 20
_Z_WIDGET_FG: int = 21
_Z_WIDGET_TEXT: int = 22
_Z_TOAST: int = 100


class ImmediateUI:
    """Immediate-mode UI context — one instance per game window.

    Parameters
    ----------
    theme:
        Optional :class:`RuntimeTheme`. Defaults to the built-in palette
        so games don't need to touch the theming layer at all.
    default_font_size:
        Font size used when a widget doesn't request one explicitly.
        Widgets that render text (label, button, checkbox, slider) use
        this to measure and position text.

    Notes
    -----
    The class is *not* thread-safe by design — immediate-mode UI is a
    per-tick construct and the tick loop is single-threaded.
    """

    def __init__(
        self,
        theme: RuntimeTheme | None = None,
        default_font_size: int = 14,
    ) -> None:
        self.theme: RuntimeTheme = theme if theme is not None else RuntimeTheme()
        self.default_font_size: int = int(default_font_size)
        if self.default_font_size <= 0:
            raise ValueError(
                "ImmediateUI: default_font_size must be > 0; "
                f"got {default_font_size!r}"
            )

        # ---- per-frame input state ------------------------------------
        self._mouse_pos: tuple[float, float] = (0.0, 0.0)
        self._mouse_down: bool = False
        self._prev_mouse_down: bool = False
        self._keys_down: set[str] = set()
        self._dt: float = 0.0
        self._in_frame: bool = False

        # ---- accumulated commands -------------------------------------
        self._commands: list[DrawCommand] = []

        # ---- persistent widget state ---------------------------------
        # id → arbitrary state bag (bool for checkboxes, float for
        # sliders, dict for panels, etc.)
        self._widget_state: dict[str, Any] = {}

        # id → (position, size) recorded on last frame — used by
        # button click detection when a widget is polled outside a panel.
        self._last_rect: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {}

        # active panel offset stack (context-manager based)
        self._panel_offset_stack: list[tuple[float, float]] = []
        self._panel_id_stack: list[str] = []

    # ------------------------------------------------------------------
    # Frame lifecycle
    # ------------------------------------------------------------------

    def begin_frame(
        self,
        dt: float,
        mouse_pos: tuple[float, float] = (0.0, 0.0),
        keys_down: set[str] | None = None,
        mouse_down: bool = False,
    ) -> None:
        """Start a new frame; must be called before any widget call.

        Parameters
        ----------
        dt:
            Seconds since the previous frame — used by toasts and any
            animated widgets.
        mouse_pos:
            Screen-space ``(x, y)`` of the mouse cursor.
        keys_down:
            Set of key names currently pressed (game-loop convention;
            widgets only consume specific keys they document).
        mouse_down:
            ``True`` while the primary mouse button is held. Click
            detection fires on the *release* edge of this signal.
        """
        if self._in_frame:
            raise RuntimeError(
                "ImmediateUI.begin_frame: called twice in a row without "
                "end_frame — check your tick loop"
            )
        self._prev_mouse_down = self._mouse_down
        self._mouse_pos = (float(mouse_pos[0]), float(mouse_pos[1]))
        self._mouse_down = bool(mouse_down)
        self._keys_down = set(keys_down) if keys_down else set()
        self._dt = float(dt)
        self._commands = []
        self._panel_offset_stack = []
        self._panel_id_stack = []
        self._in_frame = True

        # Full-frame background clear.
        self._commands.append(
            DrawCommand(
                kind="rect",
                position=(0.0, 0.0),
                size=(0.0, 0.0),  # renderer treats (0,0) as "full-screen"
                color=self.theme.bg_color,
                z_order=0,
            )
        )

    def end_frame(self) -> list[DrawCommand]:
        """Close the frame and return the accumulated draw list.

        The returned list is sorted by ``z_order`` (stable sort — ties
        preserve emission order), so renderers can walk it linearly.
        """
        if not self._in_frame:
            raise RuntimeError(
                "ImmediateUI.end_frame: no frame in progress — call "
                "begin_frame first"
            )
        if self._panel_offset_stack:
            raise RuntimeError(
                "ImmediateUI.end_frame: unclosed panel context "
                f"({self._panel_id_stack[-1]!r}) — did you forget to exit "
                "a `with ui.panel(...)` block?"
            )
        self._in_frame = False
        return sorted(self._commands, key=lambda c: c.z_order)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_frame(self, widget: str) -> None:
        if not self._in_frame:
            raise RuntimeError(
                f"ImmediateUI.{widget}: no frame in progress — call "
                "begin_frame first"
            )

    def _apply_panel_offset(
        self, position: tuple[float, float]
    ) -> tuple[float, float]:
        x, y = float(position[0]), float(position[1])
        for ox, oy in self._panel_offset_stack:
            x += ox
            y += oy
        return (x, y)

    def _mouse_over(
        self, position: tuple[float, float], size: tuple[float, float]
    ) -> bool:
        mx, my = self._mouse_pos
        px, py = position
        sw, sh = size
        return (px <= mx <= px + sw) and (py <= my <= py + sh)

    def _click_released_over(
        self, position: tuple[float, float], size: tuple[float, float]
    ) -> bool:
        """Return True on the frame the mouse button releases inside rect."""
        if not (self._prev_mouse_down and not self._mouse_down):
            return False
        return self._mouse_over(position, size)

    # ------------------------------------------------------------------
    # Widgets
    # ------------------------------------------------------------------

    def button(
        self,
        widget_id: str,
        label: str,
        position: tuple[float, float],
        size: tuple[float, float],
        hovered_callback: Callable[[], None] | None = None,
    ) -> bool:
        """Draw a labelled push-button; returns True on the click frame.

        Parameters
        ----------
        widget_id:
            Unique id for this button — used to key persistent state.
        label:
            Text drawn centred on the button. Rendered with
            ``theme.text_color`` at ``default_font_size``.
        position, size:
            Screen-space top-left and size.
        hovered_callback:
            Optional zero-arg callable invoked when the mouse is over
            the button. Handy for cursor-change / audio hooks.
        """
        self._require_frame("button")
        _validate_id(widget_id, "button")
        pos = self._apply_panel_offset(position)
        size_pair = (float(size[0]), float(size[1]))
        self._last_rect[widget_id] = (pos, size_pair)

        hovered = self._mouse_over(pos, size_pair)
        if hovered and hovered_callback is not None:
            try:
                hovered_callback()
            except Exception:  # pragma: no cover - defensive
                pass

        fill = self.theme.hover_color if hovered else self.theme.button_color
        self._commands.append(
            DrawCommand(
                kind="rect",
                position=pos,
                size=size_pair,
                color=fill,
                z_order=_Z_WIDGET_BG,
            )
        )
        # Centre the label.
        text_w, text_h = measure_text(label, self.default_font_size)
        tx = pos[0] + (size_pair[0] - text_w) * 0.5
        ty = pos[1] + (size_pair[1] - text_h) * 0.5
        self._commands.append(
            DrawCommand(
                kind="text",
                position=(tx, ty),
                size=(text_w, text_h),
                color=self.theme.text_color,
                text=label,
                z_order=_Z_WIDGET_TEXT,
            )
        )
        return self._click_released_over(pos, size_pair)

    def label(
        self,
        widget_id: str,
        text: str,
        position: tuple[float, float],
        color: tuple[float, float, float, float] | None = None,
    ) -> None:
        """Draw a plain text label at *position*."""
        self._require_frame("label")
        _validate_id(widget_id, "label")
        pos = self._apply_panel_offset(position)
        col = color if color is not None else self.theme.text_color
        text_w, text_h = measure_text(text, self.default_font_size)
        self._commands.append(
            DrawCommand(
                kind="text",
                position=pos,
                size=(text_w, text_h),
                color=(float(col[0]), float(col[1]), float(col[2]), float(col[3])),
                text=text,
                z_order=_Z_WIDGET_TEXT,
            )
        )

    def slider(
        self,
        widget_id: str,
        label: str,
        position: tuple[float, float],
        size: tuple[float, float],
        value: float,
        min_value: float,
        max_value: float,
    ) -> float:
        """Draw a horizontal slider; returns the (possibly-updated) value.

        The value is clamped into ``[min_value, max_value]`` before use.
        If the user is currently dragging the slider, the returned value
        follows the mouse; otherwise the input value is preserved.
        """
        self._require_frame("slider")
        _validate_id(widget_id, "slider")
        if max_value <= min_value:
            raise ValueError(
                "ImmediateUI.slider: max_value must be > min_value; "
                f"got min={min_value!r} max={max_value!r}"
            )
        pos = self._apply_panel_offset(position)
        w, h = float(size[0]), float(size[1])
        clamped = max(min_value, min(max_value, float(value)))
        hovered = self._mouse_over(pos, (w, h))
        # Drag detection: start on press-in-bounds, continue while held.
        state_key = f"{widget_id}::dragging"
        prev_drag = bool(self._widget_state.get(state_key, False))
        just_pressed = self._mouse_down and not self._prev_mouse_down
        if just_pressed and hovered:
            prev_drag = True
        if not self._mouse_down:
            prev_drag = False
        self._widget_state[state_key] = prev_drag

        if prev_drag and w > 0:
            t = (self._mouse_pos[0] - pos[0]) / w
            t = max(0.0, min(1.0, t))
            clamped = min_value + t * (max_value - min_value)
            clamped = max(min_value, min(max_value, float(clamped)))

        # Track: background rect.
        self._commands.append(
            DrawCommand(
                kind="rect",
                position=pos,
                size=(w, h),
                color=self.theme.button_color,
                z_order=_Z_WIDGET_BG,
            )
        )
        # Fill: [0, t*w].
        span = max_value - min_value
        t_draw = (clamped - min_value) / span if span > 0 else 0.0
        self._commands.append(
            DrawCommand(
                kind="rect",
                position=pos,
                size=(w * t_draw, h),
                color=self.theme.hover_color,
                z_order=_Z_WIDGET_FG,
            )
        )
        # Label + value text.
        display = f"{label}: {clamped:.2f}" if label else f"{clamped:.2f}"
        text_w, text_h = measure_text(display, self.default_font_size)
        tx = pos[0] + (w - text_w) * 0.5
        ty = pos[1] + (h - text_h) * 0.5
        self._commands.append(
            DrawCommand(
                kind="text",
                position=(tx, ty),
                size=(text_w, text_h),
                color=self.theme.text_color,
                text=display,
                z_order=_Z_WIDGET_TEXT,
            )
        )
        return clamped

    def checkbox(
        self,
        widget_id: str,
        label: str,
        position: tuple[float, float],
        value: bool,
    ) -> bool:
        """Draw a checkbox; returns the new value (toggled on click).

        Persistent state is keyed by *widget_id* so callers can just pass
        the current value each frame and let the checkbox handle its
        own toggle bookkeeping.
        """
        self._require_frame("checkbox")
        _validate_id(widget_id, "checkbox")
        pos = self._apply_panel_offset(position)
        box_size = float(self.default_font_size) + 4.0
        rect_size = (box_size, box_size)
        new_value = bool(value)
        if self._click_released_over(pos, rect_size):
            new_value = not new_value

        self._commands.append(
            DrawCommand(
                kind="rect",
                position=pos,
                size=rect_size,
                color=self.theme.button_color,
                z_order=_Z_WIDGET_BG,
            )
        )
        if new_value:
            inset = 3.0
            self._commands.append(
                DrawCommand(
                    kind="rect",
                    position=(pos[0] + inset, pos[1] + inset),
                    size=(box_size - 2 * inset, box_size - 2 * inset),
                    color=self.theme.hover_color,
                    z_order=_Z_WIDGET_FG,
                )
            )
        if label:
            text_w, text_h = measure_text(label, self.default_font_size)
            tx = pos[0] + box_size + 6.0
            ty = pos[1] + (box_size - text_h) * 0.5
            self._commands.append(
                DrawCommand(
                    kind="text",
                    position=(tx, ty),
                    size=(text_w, text_h),
                    color=self.theme.text_color,
                    text=label,
                    z_order=_Z_WIDGET_TEXT,
                )
            )
        return new_value

    def progress_bar(
        self,
        widget_id: str,
        position: tuple[float, float],
        size: tuple[float, float],
        value_0_1: float,
    ) -> None:
        """Draw a horizontal progress bar with fill ratio *value_0_1*."""
        self._require_frame("progress_bar")
        _validate_id(widget_id, "progress_bar")
        pos = self._apply_panel_offset(position)
        w, h = float(size[0]), float(size[1])
        ratio = max(0.0, min(1.0, float(value_0_1)))
        self._commands.append(
            DrawCommand(
                kind="rect",
                position=pos,
                size=(w, h),
                color=self.theme.button_color,
                z_order=_Z_WIDGET_BG,
            )
        )
        if ratio > 0:
            self._commands.append(
                DrawCommand(
                    kind="rect",
                    position=pos,
                    size=(w * ratio, h),
                    color=self.theme.hover_color,
                    z_order=_Z_WIDGET_FG,
                )
            )

    # ------------------------------------------------------------------
    # Panel (context manager)
    # ------------------------------------------------------------------

    @contextmanager
    def panel(
        self,
        widget_id: str,
        position: tuple[float, float],
        size: tuple[float, float],
        title: str | None = None,
        movable: bool = True,
    ) -> Iterator["ImmediateUI"]:
        """Context manager that groups nested widgets under a panel.

        Every widget invocation inside the ``with`` block is offset by
        the panel's top-left, so nested widget positions are *relative*
        to the panel origin. Panels are drag-movable when ``movable``
        is ``True`` — click on the title bar and drag to move.

        Yields the same :class:`ImmediateUI` for convenience so callers
        can chain::

            with ui.panel("hud", (20, 20), (200, 120), title="HUD") as p:
                p.label("hp_lbl", "HP", (10, 30))
                p.progress_bar("hp_bar", (10, 50), (180, 10), hp / 100)
        """
        self._require_frame("panel")
        _validate_id(widget_id, "panel")

        # Persistent state — remembers the drag offset.
        state_key = f"{widget_id}::panel"
        state = self._widget_state.setdefault(
            state_key,
            {"offset": (0.0, 0.0), "dragging": False, "drag_anchor": None},
        )

        base_pos = (float(position[0]) + state["offset"][0],
                    float(position[1]) + state["offset"][1])
        w, h = float(size[0]), float(size[1])
        title_h = 20.0 if title else 0.0

        # Handle drag on the title bar.
        if movable and title:
            title_rect_pos = base_pos
            title_rect_size = (w, title_h)
            hovered_title = self._mouse_over(title_rect_pos, title_rect_size)
            just_pressed = self._mouse_down and not self._prev_mouse_down
            if just_pressed and hovered_title:
                state["dragging"] = True
                state["drag_anchor"] = self._mouse_pos
            if not self._mouse_down:
                state["dragging"] = False
                state["drag_anchor"] = None
            if state["dragging"] and state["drag_anchor"] is not None:
                anchor = state["drag_anchor"]
                dx = self._mouse_pos[0] - anchor[0]
                dy = self._mouse_pos[1] - anchor[1]
                state["offset"] = (
                    state["offset"][0] + dx,
                    state["offset"][1] + dy,
                )
                state["drag_anchor"] = self._mouse_pos
                base_pos = (
                    float(position[0]) + state["offset"][0],
                    float(position[1]) + state["offset"][1],
                )

        # Panel background + border.
        self._commands.append(
            DrawCommand(
                kind="rect",
                position=base_pos,
                size=(w, h),
                color=self.theme.panel_bg_color,
                z_order=_Z_PANEL_BG,
            )
        )
        # Cheap "border" — four thin rects. The renderer is free to
        # composite these as a nine-slice, but the runtime stays honest.
        border_col = self.theme.panel_border_color
        border_px = 1.0
        for br_pos, br_size in (
            (base_pos, (w, border_px)),  # top
            ((base_pos[0], base_pos[1] + h - border_px), (w, border_px)),  # bottom
            (base_pos, (border_px, h)),  # left
            ((base_pos[0] + w - border_px, base_pos[1]), (border_px, h)),  # right
        ):
            self._commands.append(
                DrawCommand(
                    kind="rect",
                    position=br_pos,
                    size=br_size,
                    color=border_col,
                    z_order=_Z_PANEL_BORDER,
                )
            )
        if title:
            self._commands.append(
                DrawCommand(
                    kind="rect",
                    position=base_pos,
                    size=(w, title_h),
                    color=self.theme.button_color,
                    z_order=_Z_PANEL_BORDER,
                )
            )
            tw, th = measure_text(title, self.default_font_size)
            self._commands.append(
                DrawCommand(
                    kind="text",
                    position=(base_pos[0] + 6.0,
                              base_pos[1] + (title_h - th) * 0.5),
                    size=(tw, th),
                    color=self.theme.text_color,
                    text=title,
                    z_order=_Z_WIDGET_TEXT,
                )
            )

        # Push offset so nested widgets render relative to the panel.
        self._panel_offset_stack.append(
            (base_pos[0], base_pos[1] + title_h)
        )
        self._panel_id_stack.append(widget_id)
        try:
            yield self
        finally:
            self._panel_offset_stack.pop()
            self._panel_id_stack.pop()


def _validate_id(widget_id: str, widget: str) -> None:
    if not isinstance(widget_id, str) or not widget_id:
        raise ValueError(
            f"ImmediateUI.{widget}: widget_id must be a non-empty str; "
            f"got {widget_id!r}"
        )


__all__ = ["ImmediateUI"]
