"""Debug overlay for SlapPyEngine — toggled at runtime with F2 / F3 / F4.

Three independent panels, each independently togglable:

F2 — **Event stream**: scrolling list of the last 20 events received on
     the global bus (event name, publisher type, timestamp delta).
     Subscribes while visible; unsubscribes when hidden (no overhead).

F3 — **RunRule status**: placeholder table showing which ComputePass
     instances are skipping due to zero subscribers.  Populated by
     passes that call ``DebugOverlay.report_pass(name, skipping)``.

F4 — **Observable heatmap**: counts how many events each class attribute
     fired this frame.  Resets each frame.  Populated by Observable
     ``__setattr__`` when ``_debug_overlay`` is set.

All panels render as plain text into a PIL Image that the caller composites
over the scene.  Import is lazy so PIL absence only matters if the overlay
is actually shown.
"""
from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


class DebugOverlay:
    """Headless-safe runtime debug overlay.

    Usage::

        overlay = DebugOverlay()

        # In input handler:
        if key == F2: overlay.toggle_events()
        if key == F3: overlay.toggle_passes()
        if key == F4: overlay.toggle_heatmap()

        # Each frame:
        overlay.begin_frame()
        img = overlay.render(width=400)   # PIL Image or None if all hidden
    """

    MAX_EVENTS = 20
    FONT_SIZE  = 12
    LINE_H     = 14
    PAD        = 6
    BG_COLOR   = (10, 10, 20, 200)
    TEXT_COLOR = (220, 220, 220, 255)
    DIM_COLOR  = (130, 130, 130, 255)
    WARN_COLOR = (255, 180, 60, 255)

    def __init__(self) -> None:
        self._show_events  = False
        self._show_passes  = False
        self._show_heatmap = False

        # F2 — event stream
        self._event_log: deque[tuple[float, str, str]] = deque(maxlen=self.MAX_EVENTS)
        self._event_sub_handle: int | None = None

        # F3 — pass status: {name: skipping}
        self._pass_status: dict[str, bool] = {}

        # F4 — heatmap: {attr_key: count_this_frame}
        self._heatmap: dict[str, int] = {}

        self._frame_t = time.perf_counter()

    # ------------------------------------------------------------------
    # Toggle helpers
    # ------------------------------------------------------------------

    def toggle_events(self) -> bool:
        self._show_events = not self._show_events
        self._sync_event_sub()
        return self._show_events

    def toggle_passes(self) -> bool:
        self._show_passes = not self._show_passes
        return self._show_passes

    def toggle_heatmap(self) -> bool:
        self._show_heatmap = not self._show_heatmap
        return self._show_heatmap

    @property
    def visible(self) -> bool:
        return self._show_events or self._show_passes or self._show_heatmap

    # ------------------------------------------------------------------
    # Event subscription management
    # ------------------------------------------------------------------

    def _sync_event_sub(self) -> None:
        try:
            from slappyengine.event_bus import subscribe, unsubscribe
        except ImportError:
            return

        if self._show_events and self._event_sub_handle is None:
            # Catch-all: subscribe to top-level tokens that fan up
            # We subscribe to a synthetic wildcard via a low-level hook.
            # Since EventBus doesn't support wildcards, subscribe to common
            # root-level event categories plus a universal interceptor.
            def _catch(evt: Any) -> None:
                name = getattr(evt, "name", str(evt))
                pub  = type(getattr(evt, "publisher", None)).__name__
                self._event_log.append((time.perf_counter(), name, pub))

            # Subscribe to a few major namespaces as a practical interceptor
            from slappyengine.event_bus import global_bus

            def _raw_all(payload: dict) -> None:
                evt = payload.get("_event")
                if evt is not None:
                    _catch(evt)

            # Hook into EventBus at a low level: wrap publish to intercept
            if not hasattr(global_bus, "_debug_overlay_orig_pub"):
                orig = global_bus.publish

                def _patched(event_type: str, **kw: Any) -> None:
                    orig(event_type, **kw)
                    evt = kw.get("_event")
                    if evt is not None:
                        self._event_log.append((
                            time.perf_counter(),
                            getattr(evt, "name", event_type),
                            type(getattr(evt, "publisher", None)).__name__,
                        ))

                global_bus._debug_overlay_orig_pub = orig
                global_bus.publish = _patched  # type: ignore[method-assign]

            self._event_sub_handle = -1  # sentinel: patched

        elif not self._show_events and self._event_sub_handle is not None:
            # Restore original publish
            from slappyengine.event_bus import global_bus
            orig = getattr(global_bus, "_debug_overlay_orig_pub", None)
            if orig is not None:
                global_bus.publish = orig  # type: ignore[method-assign]
                del global_bus._debug_overlay_orig_pub
            self._event_sub_handle = None

    # ------------------------------------------------------------------
    # External reporters
    # ------------------------------------------------------------------

    def report_pass(self, name: str, skipping: bool) -> None:
        """Called by ComputePass each frame to report its run/skip state."""
        self._pass_status[name] = skipping

    def record_attr_publish(self, class_attr: str) -> None:
        """Called by Observable.__setattr__ when _debug_overlay is wired."""
        if self._show_heatmap:
            self._heatmap[class_attr] = self._heatmap.get(class_attr, 0) + 1

    def begin_frame(self) -> None:
        """Reset per-frame heatmap counters.  Call at the start of each tick."""
        self._frame_t = time.perf_counter()
        if self._show_heatmap:
            self._heatmap.clear()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, width: int = 400) -> "Any | None":
        """Return a PIL RGBA Image of the overlay, or None if nothing is visible."""
        if not self.visible:
            return None

        try:
            from PIL import Image, ImageDraw, ImageFont
            _pil_ok = True
        except ImportError:
            _pil_ok = False

        if not _pil_ok:
            return None

        sections: list[list[tuple[str, tuple[int, int, int, int]]]] = []

        if self._show_events:
            sections.append(self._build_event_lines())
        if self._show_passes:
            sections.append(self._build_pass_lines())
        if self._show_heatmap:
            sections.append(self._build_heatmap_lines())

        all_lines: list[tuple[str, tuple[int, int, int, int]]] = []
        for sec in sections:
            all_lines.extend(sec)
            all_lines.append(("", self.DIM_COLOR))

        height = self.PAD * 2 + len(all_lines) * self.LINE_H
        img = Image.new("RGBA", (width, max(height, 10)), self.BG_COLOR)
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("consola.ttf", self.FONT_SIZE)
        except Exception:
            font = ImageFont.load_default()

        y = self.PAD
        for text, color in all_lines:
            if text:
                draw.text((self.PAD, y), text, fill=color, font=font)
            y += self.LINE_H

        return img

    def _build_event_lines(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        lines: list[tuple[str, tuple[int, int, int, int]]] = [
            ("── F2: Event Stream ─────────────────────────", self.WARN_COLOR),
        ]
        now = time.perf_counter()
        events = list(self._event_log)[-self.MAX_EVENTS:]
        for t, name, pub in events:
            age = now - t
            color = self.TEXT_COLOR if age < 0.5 else self.DIM_COLOR
            truncated = name[:34] if len(name) > 34 else name
            lines.append((f"  {truncated:<34} [{pub}]", color))
        return lines

    def _build_pass_lines(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        lines: list[tuple[str, tuple[int, int, int, int]]] = [
            ("── F3: ComputePass Status ───────────────────", self.WARN_COLOR),
        ]
        for name, skipping in sorted(self._pass_status.items()):
            status = "SKIP" if skipping else " RUN"
            color = self.DIM_COLOR if skipping else self.TEXT_COLOR
            lines.append((f"  {status}  {name}", color))
        if not self._pass_status:
            lines.append(("  (no passes registered)", self.DIM_COLOR))
        return lines

    def _build_heatmap_lines(self) -> list[tuple[str, tuple[int, int, int, int]]]:
        lines: list[tuple[str, tuple[int, int, int, int]]] = [
            ("── F4: Observable Heatmap (this frame) ─────", self.WARN_COLOR),
        ]
        ranked = sorted(self._heatmap.items(), key=lambda x: -x[1])[:15]
        for attr, count in ranked:
            bar = "█" * min(count, 20)
            lines.append((f"  {count:4d}  {attr[:28]:<28} {bar}", self.TEXT_COLOR))
        if not ranked:
            lines.append(("  (no Observable events this frame)", self.DIM_COLOR))
        return lines

    # ------------------------------------------------------------------
    # Text-only fallback (headless / no PIL)
    # ------------------------------------------------------------------

    def render_text(self) -> str:
        """Return a plain-text representation of the overlay state."""
        out: list[str] = []
        if self._show_events:
            out.append("=== Event Stream ===")
            for t, name, pub in list(self._event_log)[-self.MAX_EVENTS:]:
                out.append(f"  {name} [{pub}]")
        if self._show_passes:
            out.append("=== ComputePass Status ===")
            for name, skip in sorted(self._pass_status.items()):
                out.append(f"  {'SKIP' if skip else 'RUN '} {name}")
        if self._show_heatmap:
            out.append("=== Observable Heatmap ===")
            for attr, count in sorted(self._heatmap.items(), key=lambda x: -x[1])[:15]:
                out.append(f"  {count:4d}  {attr}")
        return "\n".join(out)
