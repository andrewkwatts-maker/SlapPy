"""
Engine Widget toolkit — retained-mode UI that renders to Layer2D.
Default: plain overlay. Opt-in: physics, lighting, post-process (via Layer2D ops).
"""
from __future__ import annotations
import math
import time as _time
from typing import Callable, Any
from dataclasses import dataclass, field


@dataclass
class Theme:
    """Visual style for all widgets. Cascades down widget trees."""
    primary:    tuple[int,int,int,int] = (60, 120, 220, 255)   # button bg, active
    surface:    tuple[int,int,int,int] = (30, 30, 40, 220)     # panel bg
    on_primary: tuple[int,int,int,int] = (255, 255, 255, 255)  # text on primary
    on_surface: tuple[int,int,int,int] = (220, 220, 220, 255)  # text on surface
    accent:     tuple[int,int,int,int] = (0, 200, 120, 255)    # highlight
    error:      tuple[int,int,int,int] = (220, 50, 50, 255)
    font_size_body:    int = 14
    font_size_title:   int = 20
    font_size_caption: int = 10
    corner_radius:     float = 4.0

    @classmethod
    def dark(cls) -> "Theme":
        return cls()  # defaults are dark

    @classmethod
    def light(cls) -> "Theme":
        return cls(
            primary=(40, 100, 200, 255),
            surface=(240, 240, 245, 220),
            on_primary=(255, 255, 255, 255),
            on_surface=(20, 20, 30, 255),
            accent=(0, 160, 90, 255),
        )

    @classmethod
    def from_dict(cls, d: dict) -> "Theme":
        valid = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**valid)


class Widget:
    """Base class for all UI widgets."""

    def __init__(self, x: float = 0, y: float = 0,
                 w: float = 100, h: float = 30,
                 tag: str = ""):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.tag = tag
        self.visible: bool = True
        self.dirty: bool = True
        self._theme: Theme = Theme()
        self._bindings: list[tuple] = []   # (obj, attr, formatter) — legacy polling
        self._event_handles: list[int] = []  # global-bus subscription handles
        self._event_value: Any = None        # last value received from an event
        self._on_click: Callable | None = None
        self._on_change: Callable | None = None
        self._on_hover: Callable | None = None
        self._hovered: bool = False
        self._focused: bool = False

    def bind_event(self, event_name: str,
                   transform: Callable | None = None) -> "Widget":
        """Subscribe to *event_name* on the global bus.

        When an event arrives the widget is marked dirty and its
        ``_event_value`` is updated (after applying *transform* if given).
        ``update()`` no longer polls; it simply returns the dirty flag.

        Parameters
        ----------
        event_name:
            Dot-path event, e.g. ``"VehicleEntity.speed"``.
        transform:
            Optional ``(EventDetails) → display_value`` function.

        Returns self for chaining.
        """
        from slappyengine.event_bus import subscribe

        def _handler(evt) -> None:
            val = transform(evt) if transform is not None else getattr(evt, "value", None)
            self._event_value = val
            self.dirty = True
            self._on_value_updated(val)

        h = subscribe(event_name, _handler)
        self._event_handles.append(h)
        return self

    def unbind_all(self) -> None:
        """Unsubscribe all event-bus handles and clear legacy bindings."""
        from slappyengine.event_bus import unsubscribe
        for h in self._event_handles:
            unsubscribe(h)
        self._event_handles.clear()
        self._bindings.clear()

    def bind(self, obj: Any, attr: str,
              formatter: Callable | None = None) -> "Widget":
        """Legacy poll-based binding. Prefer bind_event() for new code."""
        self._bindings.append((obj, attr, formatter))
        self.dirty = True
        return self

    def on_click(self, callback: Callable) -> "Widget":
        self._on_click = callback
        return self

    def on_change(self, callback: Callable) -> "Widget":
        self._on_change = callback
        return self

    def on_hover(self, callback: Callable) -> "Widget":
        self._on_hover = callback
        return self

    def _get_bound_value(self) -> Any:
        """Read the first bound attribute value (or None)."""
        for obj, attr, _ in self._bindings:
            try:
                return getattr(obj, attr)
            except AttributeError:
                pass
        return None

    def handle_event(self, event: dict) -> bool:
        """Handle input event. Returns True if consumed."""
        kind = event.get("type", "")
        mx, my = event.get("x", -1), event.get("y", -1)
        inside = (self.x <= mx < self.x + self.w and
                  self.y <= my < self.y + self.h)
        if kind == "mouse_move":
            was = self._hovered
            self._hovered = inside
            if self._hovered != was:
                self.dirty = True
                if self._hovered and self._on_hover:
                    self._on_hover(self)
        elif kind == "mouse_down" and inside:
            if self._on_click:
                self._on_click(self)
            return True
        return False

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        self.dirty = True

    def _on_value_updated(self, value: Any) -> None:
        """Hook called when a bound event value arrives. Subclasses override."""
        pass

    def draw(self, draw, offset_x: float = 0, offset_y: float = 0) -> None:
        """Draw to a PIL ImageDraw. Subclasses override."""
        pass

    def update(self) -> bool:
        """Check if the widget needs a redraw.

        Event-bound widgets (bind_event) are already marked dirty by the
        event handler — no polling occurs here.  Legacy poll-bound widgets
        (bind()) still read their source object.

        Returns True if the dirty flag is set (i.e. a redraw is needed).
        """
        for obj, attr, _ in self._bindings:
            try:
                val = getattr(obj, attr)
                if val != getattr(self, "_last_bound_val", object()):
                    self._last_bound_val = val
                    self._event_value = val
                    self.dirty = True
            except AttributeError:
                pass
        return self.dirty


class Label(Widget):
    def __init__(self, text: str = "", **kwargs):
        super().__init__(**kwargs)
        self.text = text
        self._format_str: str | None = None
        self._pulse_end: float = 0.0   # time.perf_counter() when pulse ends

    def bind_format(self, event_name: str, format_str: str) -> "Label":
        """Subscribe to *event_name* and format the received value with *format_str*.

        Example::

            label.bind_format("VehicleEntity.speed", "{value:.0f} km/h")
        """
        self._format_str = format_str

        def _transform(evt) -> str:
            val = getattr(evt, "value", evt)
            try:
                return format_str.format(value=val)
            except Exception:
                return str(val)

        self.bind_event(event_name, transform=_transform)
        return self

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        # Pulse: briefly brighten on value change
        now = _time.perf_counter()
        pulse = now < self._pulse_end
        color = (255, 255, 200, 255) if pulse else self._theme.on_surface

        # Event value takes priority over legacy poll value then static text
        val = self._event_value
        if val is None:
            val = self._get_bound_value()
        text = str(val) if val is not None else self.text
        try:
            draw.text((self.x + ox + 4, self.y + oy + 4), text, fill=color)
        except Exception:
            pass

    def _on_value_updated(self, value: Any) -> None:
        self._pulse_end = _time.perf_counter() + 0.1  # 100ms pulse


class Button(Widget):
    def __init__(self, label: str = "Button", **kwargs):
        super().__init__(**kwargs)
        self.label = label
        self._pressed: bool = False

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        bg = self._theme.accent if self._hovered else self._theme.primary
        tx = int(self.x + ox)
        ty = int(self.y + oy)
        try:
            draw.rectangle([tx, ty, tx + int(self.w), ty + int(self.h)],
                           fill=bg, outline=self._theme.on_primary)
            draw.text((tx + 6, ty + 6), self.label, fill=self._theme.on_primary)
        except Exception:
            pass

    def handle_event(self, event: dict) -> bool:
        consumed = super().handle_event(event)
        if event.get("type") == "mouse_down":
            mx, my = event.get("x", -1), event.get("y", -1)
            if self.x <= mx < self.x + self.w and self.y <= my < self.y + self.h:
                self._pressed = True
                self.dirty = True
        elif event.get("type") == "mouse_up":
            self._pressed = False
            self.dirty = True
        return consumed


class ProgressBar(Widget):
    """Horizontal fill bar. Bind to a float 0..1."""
    def __init__(self, value: float = 0.5,
                 transition_ms: float = 80.0,
                 color_gradient: list | None = None,
                 **kwargs):
        super().__init__(**kwargs)
        self.value = value          # target (set by event or code)
        self._displayed = value     # animated display value
        self.transition_ms = transition_ms
        self._last_tick = _time.perf_counter()
        # color_gradient: [(t, color)] — t=0..1, interpolated
        self._gradient = color_gradient or [
            (0.0, (220, 50, 50, 255)),
            (0.5, (220, 200, 0, 255)),
            (1.0, (50, 200, 50, 255)),
        ]

    def _lerp_color(self, v: float) -> tuple:
        g = self._gradient
        if v <= g[0][0]:
            return g[0][1]
        if v >= g[-1][0]:
            return g[-1][1]
        for i in range(len(g) - 1):
            t0, c0 = g[i]
            t1, c1 = g[i + 1]
            if t0 <= v <= t1:
                t = (v - t0) / (t1 - t0) if t1 > t0 else 0.0
                return tuple(int(c0[j] + (c1[j] - c0[j]) * t) for j in range(4))
        return g[-1][1]

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        # Advance animated display value
        now = _time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now

        # Apply event/legacy value to target
        ev = self._event_value
        if ev is None:
            ev = self._get_bound_value()
        if ev is not None:
            self.value = float(ev)

        target = max(0.0, min(1.0, self.value))
        if self.transition_ms > 0:
            rate = dt / (self.transition_ms / 1000.0)
            self._displayed += (target - self._displayed) * min(1.0, rate)
        else:
            self._displayed = target

        v = max(0.0, min(1.0, self._displayed))
        tx, ty = int(self.x + ox), int(self.y + oy)
        draw.rectangle([tx, ty, tx + int(self.w), ty + int(self.h)],
                       fill=self._theme.surface, outline=self._theme.on_surface)
        fill_w = int(self.w * v)
        if fill_w > 0:
            fill_color = self._lerp_color(v)
            draw.rectangle([tx, ty, tx + fill_w, ty + int(self.h)],
                           fill=fill_color)


class StatBar(ProgressBar):
    """ProgressBar with label."""
    def __init__(self, label: str = "", **kwargs):
        super().__init__(**kwargs)
        self.label = label

    def draw(self, draw, ox=0, oy=0):
        super().draw(draw, ox, oy)
        if self.label:
            try:
                draw.text((int(self.x+ox+4), int(self.y+oy+2)),
                           self.label, fill=self._theme.on_surface)
            except Exception:
                pass


class Slider(Widget):
    """Horizontal slider. Bind to a float."""
    def __init__(self, value: float = 0.5,
                 min_val: float = 0.0, max_val: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self.min_val = min_val
        self.max_val = max_val
        self._dragging = False

    @property
    def normalised(self) -> float:
        rng = self.max_val - self.min_val
        return (self.value - self.min_val) / rng if rng else 0.0

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        val = self._get_bound_value()
        if val is not None:
            self.value = float(val)
        tx, ty = int(self.x+ox), int(self.y+oy)
        mid_y = ty + int(self.h // 2)
        draw.line([(tx, mid_y), (tx + int(self.w), mid_y)],
                  fill=self._theme.on_surface, width=2)
        knob_x = tx + int(self.normalised * self.w)
        r = int(self.h // 2)
        draw.ellipse([knob_x - r, ty, knob_x + r, ty + int(self.h)],
                     fill=self._theme.primary)


class Dial(Widget):
    """Circular gauge (e.g. speedometer). Bind to a float 0..1."""
    def __init__(self, value: float = 0.0, transition_ms: float = 80.0, **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self._displayed = value
        self.transition_ms = transition_ms
        self._last_tick = _time.perf_counter()

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        now = _time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now

        ev = self._event_value
        if ev is None:
            ev = self._get_bound_value()
        if ev is not None:
            self.value = float(ev)

        target = max(0.0, min(1.0, self.value))
        if self.transition_ms > 0:
            rate = dt / (self.transition_ms / 1000.0)
            self._displayed += (target - self._displayed) * min(1.0, rate)
        else:
            self._displayed = target

        v = max(0.0, min(1.0, self._displayed))
        cx = int(self.x + ox + self.w / 2)
        cy = int(self.y + oy + self.h / 2)
        r = int(min(self.w, self.h) / 2 - 4)
        try:
            draw.ellipse([cx-r, cy-r, cx+r, cy+r],
                         outline=self._theme.on_surface, width=2)
            start_angle = -225.0
            needle_angle = math.radians(start_angle + v * 270.0)
            nx = cx + int(r * 0.8 * math.cos(needle_angle))
            ny = cy + int(r * 0.8 * math.sin(needle_angle))
            draw.line([(cx, cy), (nx, ny)],
                      fill=self._theme.accent, width=3)
        except Exception:
            pass


class Panel(Widget):
    """Container that draws a background and clips children."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.children: list[Widget] = []

    def add(self, widget: "Widget") -> "Panel":
        self.children.append(widget)
        return self

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        tx, ty = int(self.x+ox), int(self.y+oy)
        draw.rectangle([tx, ty, tx + int(self.w), ty + int(self.h)],
                       fill=self._theme.surface)
        for child in self.children:
            child.draw(draw, ox + self.x, oy + self.y)

    def handle_event(self, event: dict) -> bool:
        for child in reversed(self.children):
            if child.visible and child.handle_event(event):
                return True
        return super().handle_event(event)

    def apply_theme(self, theme: Theme) -> None:
        super().apply_theme(theme)
        for child in self.children:
            child.apply_theme(theme)


class ImageWidget(Widget):
    """Displays a PIL Image, Layer2D, or file path.

    Fit modes: ``"contain"`` (default), ``"cover"``, ``"stretch"``, ``"none"``.
    Use ``bind_event`` to swap the image reactively.
    """
    def __init__(self, image=None, fit: str = "contain", **kwargs):
        super().__init__(**kwargs)
        self._image = image   # PIL Image, Layer2D, file path str, or None
        self.fit = fit
        self._cached_pil = None   # resolved PIL Image cache

    def set_image(self, image) -> None:
        """Replace the displayed image. Accepts PIL Image, Layer2D, or path."""
        self._image = image
        self._cached_pil = None
        self.dirty = True

    def _resolve_pil(self):
        """Return a PIL Image regardless of source type."""
        src = self._event_value if self._event_value is not None else self._image
        if src is None:
            return None
        if self._cached_pil is not None and src is self._image:
            return self._cached_pil
        try:
            from PIL import Image as _PILImage
            if isinstance(src, str):
                img = _PILImage.open(src).convert("RGBA")
            elif hasattr(src, "_image_data"):
                # Layer2D
                import numpy as np
                data = np.asarray(src._image_data, dtype=np.uint8)
                img = _PILImage.fromarray(data, mode="RGBA")
            elif hasattr(src, "save"):
                img = src  # already a PIL Image
            else:
                return None
            self._cached_pil = img
            self._image = src
            return img
        except Exception:
            return None

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        img = self._resolve_pil()
        if img is None:
            return
        try:
            from PIL import Image as _PILImage
            tx, ty = int(self.x + ox), int(self.y + oy)
            tw, th = int(self.w), int(self.h)

            if self.fit == "stretch":
                resized = img.resize((tw, th), _PILImage.LANCZOS)
                paste_x, paste_y = tx, ty
            elif self.fit == "none":
                resized = img
                paste_x, paste_y = tx, ty
            else:  # "contain" or "cover"
                iw, ih = img.size
                scale_w = tw / iw
                scale_h = th / ih
                if self.fit == "contain":
                    scale = min(scale_w, scale_h)
                else:  # "cover"
                    scale = max(scale_w, scale_h)
                nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
                resized = img.resize((nw, nh), _PILImage.LANCZOS)
                paste_x = tx + (tw - nw) // 2
                paste_y = ty + (th - nh) // 2

            # draw.bitmap doesn't exist on ImageDraw; paste requires the canvas Image
            # Store for LayoutBox.render_to_layer to composite
            if not hasattr(draw, "_widget_pastes"):
                draw._widget_pastes = []
            draw._widget_pastes.append((resized, paste_x, paste_y))
        except Exception:
            pass


class Checkbox(Widget):
    def __init__(self, checked: bool = False, label: str = "", **kwargs):
        super().__init__(**kwargs)
        self.checked = checked
        self.label = label

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        tx, ty = int(self.x+ox), int(self.y+oy)
        s = int(min(self.w, self.h))
        box = [tx, ty, tx+s, ty+s]
        draw.rectangle(box, outline=self._theme.on_surface, fill=self._theme.surface)
        if self.checked:
            draw.line([(tx+2,ty+s//2),(tx+s//2,ty+s-2),(tx+s-2,ty+2)],
                      fill=self._theme.accent, width=2)
        if self.label:
            draw.text((tx+s+4, ty+2), self.label, fill=self._theme.on_surface)

    def handle_event(self, event: dict) -> bool:
        if event.get("type") == "mouse_down":
            mx, my = event.get("x",-1), event.get("y",-1)
            if self.x <= mx < self.x+self.w and self.y <= my < self.y+self.h:
                self.checked = not self.checked
                self.dirty = True
                if self._on_change:
                    self._on_change(self.checked)
                return True
        return False


class Dropdown(Widget):
    def __init__(self, options: list[str] | None = None,
                 selected: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.options = options or []
        self.selected = selected
        self._open = False

    @property
    def value(self) -> str:
        return self.options[self.selected] if self.options else ""

    def _unselected_options(self) -> list[tuple[int, str]]:
        """Return (original_index, label) for all options except the selected one."""
        return [(i, opt) for i, opt in enumerate(self.options) if i != self.selected]

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        tx, ty = int(self.x+ox), int(self.y+oy)
        draw.rectangle([tx, ty, tx+int(self.w), ty+int(self.h)],
                       fill=self._theme.surface, outline=self._theme.on_surface)
        label = self.value + " ▾"
        draw.text((tx+4, ty+4), label, fill=self._theme.on_surface)
        if self._open:
            for row, (_, opt) in enumerate(self._unselected_options()):
                oy2 = ty + int(self.h) * (row + 1)
                draw.rectangle([tx, oy2, tx+int(self.w), oy2+int(self.h)],
                               fill=self._theme.surface, outline=self._theme.on_surface)
                draw.text((tx+4, oy2+4), opt, fill=self._theme.on_surface)

    def handle_event(self, event: dict) -> bool:
        if event.get("type") == "mouse_down":
            mx, my = event.get("x",-1), event.get("y",-1)
            if self.x <= mx < self.x+self.w and self.y <= my < self.y+self.h:
                self._open = not self._open
                self.dirty = True
                return True
            if self._open:
                for row, (orig_idx, _) in enumerate(self._unselected_options()):
                    item_y = self.y + self.h * (row + 1)
                    if self.x <= mx < self.x+self.w and item_y <= my < item_y+self.h:
                        self.selected = orig_idx
                        self._open = False
                        self.dirty = True
                        if self._on_change:
                            self._on_change(self.value)
                        return True
                self._open = False
        return False


class ScrollView(Panel):
    """Scrollable container. Children overflow below; a scroll offset clips the view.

    Use ``scroll_by(dy)`` or set ``scroll_offset`` directly.  The view clips
    child drawing to its own bounds so content outside is not visible.

    Parameters
    ----------
    scroll_speed:
        Pixels to scroll per mouse-wheel notch.
    """

    def __init__(self, scroll_speed: float = 20.0, **kwargs):
        super().__init__(**kwargs)
        self.scroll_offset: float = 0.0
        self.scroll_speed = scroll_speed
        self._content_height: float = 0.0

    def add(self, widget: "Widget") -> "ScrollView":
        super().add(widget)
        self._recompute_content_height()
        return self

    def _recompute_content_height(self) -> None:
        bottom = 0.0
        for child in self.children:
            bottom = max(bottom, child.y + child.h)
        self._content_height = bottom

    def scroll_by(self, dy: float) -> None:
        """Scroll by *dy* pixels (positive = down, negative = up)."""
        self.scroll_offset = max(
            0.0,
            min(self.scroll_offset + dy,
                max(0.0, self._content_height - self.h))
        )
        self.dirty = True

    def scroll_to(self, offset: float) -> None:
        """Scroll to an absolute *offset*."""
        self.scroll_offset = max(
            0.0,
            min(offset, max(0.0, self._content_height - self.h))
        )
        self.dirty = True

    @property
    def at_bottom(self) -> bool:
        return self._content_height <= self.h or \
               self.scroll_offset >= self._content_height - self.h

    def draw(self, draw, ox=0, oy=0):
        if not self.visible:
            return
        tx, ty = int(self.x + ox), int(self.y + oy)
        # Background
        try:
            draw.rectangle([tx, ty, tx + int(self.w), ty + int(self.h)],
                           fill=self._theme.surface)
        except Exception:
            pass
        # Compute content height from children
        bottom = 0.0
        for child in self.children:
            bottom = max(bottom, child.y + child.h)
        self._content_height = bottom

        # Draw each visible child (shifted by scroll offset)
        scroll_y = int(self.scroll_offset)
        for child in self.children:
            # Only draw if at least partially inside the clip region
            child_top = child.y - scroll_y
            child_bot = child.y - scroll_y + child.h
            if child_bot < 0 or child_top > self.h:
                continue
            child.draw(draw, ox + self.x, oy + self.y - scroll_y)

        # Scrollbar track + thumb
        if self._content_height > self.h:
            track_x = tx + int(self.w) - 5
            try:
                draw.rectangle([track_x, ty, track_x + 4,
                                ty + int(self.h)],
                               fill=self._theme.surface)
                thumb_ratio = self.h / self._content_height
                thumb_h = max(16, int(self.h * thumb_ratio))
                thumb_y = ty + int(
                    (self.scroll_offset / self._content_height) *
                    (self.h - thumb_h)
                )
                draw.rectangle([track_x, thumb_y,
                                track_x + 4, thumb_y + thumb_h],
                               fill=self._theme.on_surface)
            except Exception:
                pass

    def handle_event(self, event: dict) -> bool:
        kind = event.get("type", "")
        mx, my = event.get("x", -1), event.get("y", -1)
        inside = (self.x <= mx < self.x + self.w and
                  self.y <= my < self.y + self.h)
        if kind == "scroll" and inside:
            self.scroll_by(-event.get("dy", 0) * self.scroll_speed)
            return True
        # Forward to children with corrected y for scroll offset
        if inside:
            adj_event = dict(event)
            adj_event["y"] = my + self.scroll_offset
            for child in reversed(self.children):
                if child.visible and child.handle_event(adj_event):
                    return True
        return False


class LayoutBox:
    """Flexbox-inspired layout container."""
    def __init__(self, direction: str = "column",
                 align: str = "start",
                 gap: float = 4.0,
                 padding: float = 8.0,
                 x: float = 0, y: float = 0,
                 w: float = 200, h: float = 400):
        self.direction = direction   # "row" | "column"
        self.align = align           # "start" | "center" | "end" | "stretch"
        self.gap = gap
        self.padding = padding
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self._children: list[Widget | "LayoutBox"] = []
        self._theme = Theme()

    def add(self, child) -> "LayoutBox":
        self._children.append(child)
        return self

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        for c in self._children:
            c.apply_theme(theme)

    def layout(self, bounds: tuple[float,float,float,float] | None = None) -> None:
        """Compute child positions from layout rules."""
        if bounds:
            self.x, self.y, self.w, self.h = bounds
        p = self.padding
        cursor = p
        for child in self._children:
            if self.direction == "column":
                child.x = self.x + p
                child.y = self.y + cursor
                if self.align == "stretch":
                    child.w = self.w - 2 * p
                cursor += child.h + self.gap
            else:  # row
                child.x = self.x + cursor
                child.y = self.y + p
                if self.align == "stretch":
                    child.h = self.h - 2 * p
                cursor += child.w + self.gap
            if isinstance(child, LayoutBox):
                child.layout()

    def handle_event(self, event: dict) -> bool:
        for c in reversed(self._children):
            if hasattr(c, "handle_event") and c.handle_event(event):
                return True
        return False

    def render_to_layer(self, size: tuple[int,int] | None = None):
        """
        Render all widgets to a Layer2D (PIL ImageDraw backend).
        The returned Layer2D is a plain overlay by default.
        Attach NodeGraph passes, post-process, lighting, collision as needed.
        """
        try:
            from PIL import Image, ImageDraw
            from slappyengine.layer import Layer2D
        except ImportError:
            return None

        w = size[0] if size else int(self.w + self.x)
        h = size[1] if size else int(self.h + self.y)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        self._draw_children(draw, self._children)

        # Composite any ImageWidget pastes (PIL paste can't happen through Draw)
        for pasted_img, px, py in getattr(draw, "_widget_pastes", []):
            try:
                img.paste(pasted_img, (px, py),
                          pasted_img if pasted_img.mode == "RGBA" else None)
            except Exception:
                pass

        layer = Layer2D.blank(w, h, name="ui_layout")
        import numpy as np
        layer._image_data[:] = np.asarray(img, dtype=np.uint8)
        return layer

    # ------------------------------------------------------------------
    # YAML layout loading
    # ------------------------------------------------------------------

    @classmethod
    def load_yml(cls, path: str) -> "LayoutBox":
        """Load a LayoutBox tree from a YAML file.

        Falls back to an empty LayoutBox on ImportError or parse failure so
        callers never have to guard against exceptions.

        Parameters
        ----------
        path:
            Filesystem path to the ``.yml`` / ``.yaml`` file.
        """
        try:
            import yaml  # lazy — optional dependency
        except ImportError:
            return cls()

        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, dict):
                return cls()
        except Exception:
            return cls()

        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "LayoutBox":
        """Recursively build a LayoutBox (and its children) from a plain dict."""
        _WIDGET_MAP: dict[str, type] = {
            "Label":       Label,
            "Button":      Button,
            "ProgressBar": ProgressBar,
            "StatBar":     StatBar,
            "Slider":      Slider,
            "Dial":        Dial,
            "Panel":       Panel,
            "ScrollView":  ScrollView,
            "ImageWidget": ImageWidget,
            "Checkbox":    Checkbox,
            "Dropdown":    Dropdown,
        }

        # Build the LayoutBox itself
        box_kwargs: dict = {}
        for key in ("direction", "align", "gap", "padding", "x", "y", "w", "h"):
            if key in data:
                box_kwargs[key] = data[key]
        box = cls(**box_kwargs)

        # Build children
        for child_data in data.get("children") or []:
            if not isinstance(child_data, dict):
                continue
            widget_type = child_data.get("type", "")

            if widget_type == "LayoutBox":
                box.add(cls._from_dict(child_data))
                continue

            widget_cls = _WIDGET_MAP.get(widget_type)
            if widget_cls is None:
                continue

            # Collect constructor kwargs — pass through common scalar keys
            _SKIP = {"type", "bind", "children"}
            wkwargs: dict = {
                k: v for k, v in child_data.items()
                if k not in _SKIP and not isinstance(v, (dict, list))
            }
            try:
                widget = widget_cls(**wkwargs)
            except Exception:
                continue

            # bind_event wiring
            bind = child_data.get("bind")
            if isinstance(bind, dict) and "event" in bind:
                event_name: str = bind["event"]
                transform = None
                bind_transform = bind.get("transform", "")
                if isinstance(bind_transform, str) and \
                        bind_transform.strip().startswith("lambda"):
                    try:
                        transform = eval(bind_transform)  # noqa: S307 — lambda-only guard above
                    except Exception:
                        transform = None
                try:
                    widget.bind_event(event_name, transform)
                except Exception:
                    pass

            box.add(widget)

        return box

    def _subscribe_hotreload(self, path: str) -> int:
        """Subscribe to ``Config.Changed|<path>`` and reload this box in-place.

        The layout tree (children, direction, gap, padding) is replaced with
        the freshly parsed file each time the event fires.

        Parameters
        ----------
        path:
            The same path you passed to ``load_yml``.  The event key is
            ``"Config.Changed|{path}"``.

        Returns
        -------
        int
            The subscription handle — pass it to ``event_bus.unsubscribe``
            when you want to stop hot-reloading.
        """
        from slappyengine.event_bus import subscribe

        def _handler(evt) -> None:
            try:
                fresh = LayoutBox.load_yml(path)
                self._children = fresh._children
                self.direction = fresh.direction
                self.gap = fresh.gap
                self.padding = fresh.padding
            except Exception:
                pass

        h = subscribe(f"Config.Changed|{path}", _handler)
        return h

    def _draw_children(self, draw, children):
        for c in children:
            if isinstance(c, LayoutBox):
                self._draw_children(draw, c._children)
            elif isinstance(c, Widget) and c.visible:
                c.draw(draw)


# ---------------------------------------------------------------------------
# Notebook-themed widget primitives (Dear PyGui layer).
#
# These widgets live in sibling modules; the heavy DPG imports are deferred
# to ``build()`` time so importing this package on a headless / no-extras
# install still succeeds.  Themes are registered via
# ``slappyengine.ui.widgets.notebook_theme.set_active_theme``.
# ---------------------------------------------------------------------------
from slappyengine.ui.widgets.doodle_separator import DoodleSeparator
from slappyengine.ui.widgets.glitter_progress_bar import GlitterProgressBar
from slappyengine.ui.widgets.heart_checkbox import HeartCheckbox
from slappyengine.ui.widgets.highlighter_slider import HighlighterSlider
from slappyengine.ui.widgets.ink_stamp_badge import InkStampBadge
from slappyengine.ui.widgets.notebook_tab import NotebookTab
from slappyengine.ui.widgets.notebook_theme import (
    NotebookTheme,
    get_active_theme,
    register_theme_listener,
    resolve_theme,
    set_active_theme,
    unregister_theme_listener,
)
from slappyengine.ui.widgets.paper_clip_attachment import PaperClipAttachment
from slappyengine.ui.widgets.ribbon_tab import RibbonTab
from slappyengine.ui.widgets.sketch_button import SketchButton
from slappyengine.ui.widgets.sticker_button import StickerButton
from slappyengine.ui.widgets.sticker_corner import (
    add_sticker_corner,
    list_sticker_corners,
    remove_sticker_corner,
)
from slappyengine.ui.widgets.washi_panel import WashiPanel
from slappyengine.ui.widgets.washi_tape_divider import WashiTapeDivider


__all__ = [
    "Button",
    "Checkbox",
    "Dial",
    "DoodleSeparator",
    "Dropdown",
    "GlitterProgressBar",
    "HeartCheckbox",
    "HighlighterSlider",
    "ImageWidget",
    "InkStampBadge",
    "Label",
    "LayoutBox",
    "NotebookTab",
    "NotebookTheme",
    "Panel",
    "PaperClipAttachment",
    "ProgressBar",
    "RibbonTab",
    "ScrollView",
    "SketchButton",
    "Slider",
    "StatBar",
    "StickerButton",
    "Theme",
    "WashiPanel",
    "WashiTapeDivider",
    "Widget",
    "add_sticker_corner",
    "get_active_theme",
    "list_sticker_corners",
    "register_theme_listener",
    "remove_sticker_corner",
    "resolve_theme",
    "set_active_theme",
    "unregister_theme_listener",
]
