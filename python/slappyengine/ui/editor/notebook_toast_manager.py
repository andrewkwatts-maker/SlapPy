"""``NotebookToastManager`` — diary-themed transient toast notifications.

The toast manager lets editor operations pop small floating status
messages at the bottom-right of the viewport. Toasts stack vertically
with the oldest at the bottom and the newest sliding in from the right
above them.

Levels
------

* ``INFO`` — muted blue border (informational).
* ``SUCCESS`` — pen-green border.
* ``WARN`` — highlighter-amber border.
* ``ERROR`` — red-ink border.

Each toast has a slide-in animation (300 ms) followed by a static
lifetime and a fade-out animation (500 ms). Progress values are returned
from :meth:`tick` so callers (or tests) can inspect the current
animation phase for every visible toast.

Auto-integration
----------------

:meth:`subscribe_to_logging` installs a :class:`logging.Handler` on a
target logger (root by default) so any record at or above a chosen
level (default ``logging.WARNING``) is surfaced as a toast. This gives
editor operations an "opt-in and forget" path: any warning-level log
emitted anywhere in the engine automatically becomes a toast.

Diary theming
-------------

Each toast is rendered as a small child window with four "washi-tape"
corner glyphs (small coloured chip texts placed at the four corners)
and a border colour keyed off the level. An optional *sticker glyph*
(e.g. a small doodle-style character) can be attached — a curated set of
diary-page-friendly options lives in :data:`STICKER_OPTIONS`.

Every :mod:`dearpygui` call is funnelled through ``_safe_dpg`` so the
manager is headless-safe and testable under a stub DPG.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from slappyengine._validation import (
    validate_non_empty_str,
    validate_positive_int,
    validate_str,
)


# ---------------------------------------------------------------------------
# DPG bootstrap helpers (mirrors the pattern used in notebook_message_log).
# ---------------------------------------------------------------------------


def _is_real_dpg(dpg: Any) -> bool:
    """Return ``True`` when *dpg* is the real ``dearpygui.dearpygui`` module."""
    import types
    inner = getattr(dpg, "internal_dpg", None)
    if not isinstance(inner, types.ModuleType):
        return False
    return getattr(inner, "__name__", "").startswith("dearpygui")


def _headless_env_active() -> bool:
    """Return ``True`` when ``SLAPPY_HEADLESS=1`` (or truthy) is set."""
    val = os.environ.get("SLAPPY_HEADLESS", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` if usable, else ``None``."""
    try:
        import dearpygui.dearpygui as dpg  # type: ignore[import-not-found]
    except Exception:
        return None
    if _is_real_dpg(dpg) and _headless_env_active():
        return None
    return dpg


# ---------------------------------------------------------------------------
# Toast levels + colour mapping
# ---------------------------------------------------------------------------


class ToastLevel(Enum):
    """Canonical toast severity levels."""

    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARN = "WARN"
    ERROR = "ERROR"


# Border colours per level (RGBA 0..255). Diary-page palette:
# * INFO    — muted ink-blue
# * SUCCESS — pen-green
# * WARN    — highlighter-amber
# * ERROR   — red-ink
LEVEL_BORDER_COLORS: dict[ToastLevel, tuple[int, int, int, int]] = {
    ToastLevel.INFO:    ( 90, 140, 220, 255),
    ToastLevel.SUCCESS: ( 70, 170,  90, 255),
    ToastLevel.WARN:    (230, 170,  60, 255),
    ToastLevel.ERROR:   (220,  80,  80, 255),
}

# Curated diary-friendly sticker glyphs. Callers may pass an arbitrary
# string as ``sticker`` — this set is exposed purely as a hint.
STICKER_OPTIONS: tuple[str, ...] = (
    "*",     # doodle-star
    "!",     # exclamation
    "?",     # thought
    "+",     # plus
    "x",     # cross
    "~",     # squiggle
    "@",     # spiral
    "#",     # grid
    "%",     # split
    "&",     # loop
    "^",     # up-tick
    "v",     # down-tick
    "o",     # circle
    "=",     # equals
    "$",     # coin
    ">",     # arrow-right
    "<",     # arrow-left
    ".",     # dot
    ":",     # colon
    "|",     # bar
)


# Map stdlib logging level ints -> ToastLevel.
_STDLIB_LEVEL_MAP: tuple[tuple[int, ToastLevel], ...] = (
    (logging.ERROR,    ToastLevel.ERROR),
    (logging.WARNING,  ToastLevel.WARN),
    (logging.INFO,     ToastLevel.INFO),
    (logging.DEBUG,    ToastLevel.INFO),
)


def normalise_toast_level(level: Any) -> ToastLevel:
    """Coerce *level* into a :class:`ToastLevel`.

    Accepts stdlib ``int`` levels, canonical string names,
    ``ToastLevel`` instances, and common aliases (``WARNING`` → ``WARN``,
    ``CRITICAL`` → ``ERROR``, ``OK`` → ``SUCCESS``). Bool is refused.
    """
    if isinstance(level, ToastLevel):
        return level
    if isinstance(level, bool):
        raise TypeError(
            "normalise_toast_level: level must be str, int, or ToastLevel; "
            "not bool"
        )
    if isinstance(level, int):
        for threshold, tl in _STDLIB_LEVEL_MAP:
            if level >= threshold:
                return tl
        return ToastLevel.INFO
    if not isinstance(level, str):
        raise TypeError(
            f"normalise_toast_level: level must be str, int, or ToastLevel; "
            f"got {type(level).__name__}"
        )
    up = level.strip().upper()
    if up in ToastLevel.__members__:
        return ToastLevel[up]
    aliases = {
        "WARNING": ToastLevel.WARN,
        "CRIT": ToastLevel.ERROR,
        "CRITICAL": ToastLevel.ERROR,
        "FATAL": ToastLevel.ERROR,
        "ERR": ToastLevel.ERROR,
        "OK": ToastLevel.SUCCESS,
        "DONE": ToastLevel.SUCCESS,
        "GOOD": ToastLevel.SUCCESS,
        "NOTICE": ToastLevel.INFO,
        "DEBUG": ToastLevel.INFO,
    }
    if up in aliases:
        return aliases[up]
    return ToastLevel.INFO


# ---------------------------------------------------------------------------
# Toast dataclass
# ---------------------------------------------------------------------------


def _new_toast_id() -> str:
    """Return a fresh short UUID-based toast id."""
    return f"toast-{uuid.uuid4().hex[:12]}"


@dataclass
class Toast:
    """A single toast notification.

    Attributes
    ----------
    message:
        Body text shown on the toast.
    level:
        Severity level (drives the border colour).
    duration_ms:
        Total lifetime in ms **excluding** the fade-out tail. Defaults
        to 3000 ms.
    sticker_glyph:
        Optional short glyph rendered on the left edge of the toast
        (see :data:`STICKER_OPTIONS` for the curated set).
    id:
        Stable identifier (auto-generated).
    created_ms:
        ``tick`` timestamp of the moment the toast was shown. Populated
        by :meth:`NotebookToastManager.show`.
    """

    message: str
    level: ToastLevel = ToastLevel.INFO
    duration_ms: int = 3000
    sticker_glyph: str | None = None
    id: str = field(default_factory=_new_toast_id)
    created_ms: float = 0.0

    # Timing constants — exposed as class attributes so tests can inspect.
    SLIDE_IN_MS: int = 300
    FADE_OUT_MS: int = 500

    def total_lifetime_ms(self) -> int:
        """Return the total lifetime including the fade-out tail."""
        return int(self.duration_ms) + int(self.FADE_OUT_MS)

    def progress(self, now_ms: float) -> dict[str, float]:
        """Return ``{phase, slide_in, alpha, elapsed}`` for *now_ms*.

        * ``slide_in`` — 0.0..1.0 slide-in progress.
        * ``alpha`` — 0.0..1.0 alpha (1.0 during the static hold).
        * ``phase`` — ``"slide"`` / ``"hold"`` / ``"fade"`` / ``"expired"``.
        * ``elapsed`` — ms since :attr:`created_ms`.
        """
        elapsed = float(now_ms) - float(self.created_ms)
        if elapsed < 0:
            elapsed = 0.0
        slide = 1.0 if elapsed >= self.SLIDE_IN_MS else max(
            0.0, elapsed / max(1.0, float(self.SLIDE_IN_MS))
        )
        if elapsed < self.SLIDE_IN_MS:
            phase = "slide"
            alpha = slide
        elif elapsed < self.duration_ms:
            phase = "hold"
            alpha = 1.0
        elif elapsed < self.total_lifetime_ms():
            phase = "fade"
            fade_elapsed = elapsed - self.duration_ms
            alpha = max(
                0.0, 1.0 - fade_elapsed / max(1.0, float(self.FADE_OUT_MS))
            )
        else:
            phase = "expired"
            alpha = 0.0
        return {
            "phase": phase,
            "slide_in": float(slide),
            "alpha": float(alpha),
            "elapsed": float(elapsed),
        }


# ---------------------------------------------------------------------------
# Log handler
# ---------------------------------------------------------------------------


class _ToastLogHandler(logging.Handler):
    """A :class:`logging.Handler` that forwards records to a manager."""

    def __init__(
        self,
        manager: "NotebookToastManager | None",
        threshold: int = logging.WARNING,
    ) -> None:
        super().__init__(level=threshold)
        self._manager: NotebookToastManager | None = manager

    def emit(self, record: logging.LogRecord) -> None:
        mgr = self._manager
        if mgr is None:
            return
        try:
            level = normalise_toast_level(record.levelno)
            message = record.getMessage()
            mgr.show(message, level=level)
        except Exception:  # noqa: BLE001
            self.handleError(record)

    def close(self) -> None:
        self._manager = None
        super().close()


# ---------------------------------------------------------------------------
# NotebookToastManager
# ---------------------------------------------------------------------------


class NotebookToastManager:
    """Diary-themed transient toast notification manager.

    The manager keeps an ordered list of currently-visible toasts. New
    toasts are appended to the top of the stack; the oldest live at the
    bottom. When more than :attr:`max_visible` toasts are alive, the
    oldest ones are treated as *off-screen* (still in
    :meth:`active_toasts` but marked as such by
    :meth:`visible_toasts`).

    Parameters
    ----------
    max_visible:
        Maximum number of toasts to draw at once. Defaults to 5.
    default_duration_ms:
        Default lifetime for :meth:`show` calls that don't specify one.
        Defaults to 3000 ms.
    """

    TITLE = "Toasts"

    DEFAULT_MAX_VISIBLE: int = 5
    DEFAULT_DURATION_MS: int = 3000

    _ROOT_TAG = "notebook_toast_manager_root"

    def __init__(
        self,
        *,
        max_visible: int = DEFAULT_MAX_VISIBLE,
        default_duration_ms: int = DEFAULT_DURATION_MS,
    ) -> None:
        validate_positive_int(
            "max_visible", "NotebookToastManager", max_visible
        )
        validate_positive_int(
            "default_duration_ms", "NotebookToastManager", default_duration_ms
        )
        self._max_visible: int = int(max_visible)
        self._default_duration_ms: int = int(default_duration_ms)

        # Newest-first list. Toasts are inserted at index 0 and appended
        # visually at the top of the stack.
        self._toasts: list[Toast] = []
        # Monotonic-ish clock — set on each ``tick`` and by ``show`` when
        # no external clock has ticked yet.
        self._now_ms: float = 0.0

        # Subscribers.
        self._shown_subscribers: list[Callable[[Toast], None]] = []
        self._dismissed_subscribers: list[Callable[[Toast], None]] = []

        # Log-handler bookkeeping.
        self._log_handler: _ToastLogHandler | None = None
        self._log_target_logger: logging.Logger | None = None

        # Build state.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Test-observability.
        self.call_log: list[tuple[str, Any]] = []

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def max_visible(self) -> int:
        return self._max_visible

    @property
    def default_duration_ms(self) -> int:
        return self._default_duration_ms

    def active_toasts(self) -> list[Toast]:
        """Return the full list of live toasts (newest first)."""
        return list(self._toasts)

    def visible_toasts(self) -> list[Toast]:
        """Return only the toasts within the ``max_visible`` window."""
        return self._toasts[: self._max_visible]

    def offscreen_toasts(self) -> list[Toast]:
        """Return the live toasts that are shoved off-screen by the cap."""
        return self._toasts[self._max_visible:]

    # ------------------------------------------------------------------
    # Show / dismiss
    # ------------------------------------------------------------------

    def show(
        self,
        message: Any,
        level: Any = ToastLevel.INFO,
        duration_ms: int | None = None,
        sticker: str | None = None,
    ) -> str:
        """Push a new toast onto the stack. Returns the toast id.

        Parameters
        ----------
        message:
            Human-readable toast body.
        level:
            :class:`ToastLevel` or coercible value (see
            :func:`normalise_toast_level`).
        duration_ms:
            Optional override for the default lifetime.
        sticker:
            Optional sticker glyph — any short string.
        """
        validate_str(
            "message", "NotebookToastManager.show", message,
            allow_empty=True,
        )
        norm_level = normalise_toast_level(level)
        if duration_ms is None:
            dur = self._default_duration_ms
        else:
            dur = validate_positive_int(
                "duration_ms", "NotebookToastManager.show", duration_ms
            )
        if sticker is not None:
            validate_str(
                "sticker", "NotebookToastManager.show", sticker,
                allow_empty=True,
            )
            sticker_val: str | None = str(sticker) if sticker else None
        else:
            sticker_val = None

        toast = Toast(
            message=str(message),
            level=norm_level,
            duration_ms=int(dur),
            sticker_glyph=sticker_val,
        )
        toast.created_ms = float(self._now_ms)

        # Newest goes at the front so ``visible_toasts()[0]`` is the
        # most-recent-and-topmost entry.
        self._toasts.insert(0, toast)
        self.call_log.append(("show", toast.id))

        for cb in list(self._shown_subscribers):
            try:
                cb(toast)
            except Exception:  # noqa: BLE001
                pass

        if self._built:
            try:
                self.refresh()
            except Exception:
                pass
        return toast.id

    def dismiss(self, toast_id: str) -> bool:
        """Force-close the toast with *toast_id*.

        Returns ``True`` if a matching toast was found and removed.
        """
        validate_non_empty_str(
            "toast_id", "NotebookToastManager.dismiss", toast_id
        )
        for i, t in enumerate(self._toasts):
            if t.id == toast_id:
                del self._toasts[i]
                self.call_log.append(("dismiss", toast_id))
                for cb in list(self._dismissed_subscribers):
                    try:
                        cb(t)
                    except Exception:  # noqa: BLE001
                        pass
                if self._built:
                    try:
                        self.refresh()
                    except Exception:
                        pass
                return True
        return False

    def dismiss_all(self) -> int:
        """Force-close every toast. Returns the number dropped."""
        dropped = list(self._toasts)
        self._toasts.clear()
        self.call_log.append(("dismiss_all", len(dropped)))
        for t in dropped:
            for cb in list(self._dismissed_subscribers):
                try:
                    cb(t)
                except Exception:  # noqa: BLE001
                    pass
        if self._built:
            try:
                self.refresh()
            except Exception:
                pass
        return len(dropped)

    # ------------------------------------------------------------------
    # Tick / animation
    # ------------------------------------------------------------------

    def tick(self, now_ms: float) -> list[dict[str, Any]]:
        """Advance the clock to *now_ms* and expire finished toasts.

        Returns a list of ``{id, phase, slide_in, alpha, elapsed}``
        dicts (one per currently-alive toast). Toasts whose
        :meth:`Toast.progress` phase becomes ``"expired"`` are removed
        and their dismissed-subscribers fire.
        """
        if isinstance(now_ms, bool) or not isinstance(now_ms, (int, float)):
            raise TypeError(
                "NotebookToastManager.tick: now_ms must be a real number; "
                f"got {type(now_ms).__name__}"
            )
        self._now_ms = float(now_ms)

        progress: list[dict[str, Any]] = []
        expired: list[Toast] = []
        for t in self._toasts:
            p = t.progress(self._now_ms)
            if p["phase"] == "expired":
                expired.append(t)
            else:
                progress.append({"id": t.id, **p})
        if expired:
            for t in expired:
                try:
                    self._toasts.remove(t)
                except ValueError:
                    pass
                for cb in list(self._dismissed_subscribers):
                    try:
                        cb(t)
                    except Exception:  # noqa: BLE001
                        pass
            self.call_log.append(("expired", [t.id for t in expired]))
            if self._built:
                try:
                    self.refresh()
                except Exception:
                    pass
        return progress

    # ------------------------------------------------------------------
    # Subscriber registration
    # ------------------------------------------------------------------

    def on_toast_shown(
        self, callback: Callable[[Toast], None]
    ) -> Callable[[Toast], None]:
        """Register *callback* to fire whenever a toast is shown.

        Returns the callback for chaining / removal.
        """
        if not callable(callback):
            raise TypeError(
                "NotebookToastManager.on_toast_shown: callback must be callable"
            )
        self._shown_subscribers.append(callback)
        return callback

    def on_toast_dismissed(
        self, callback: Callable[[Toast], None]
    ) -> Callable[[Toast], None]:
        """Register *callback* to fire whenever a toast is dismissed."""
        if not callable(callback):
            raise TypeError(
                "NotebookToastManager.on_toast_dismissed: "
                "callback must be callable"
            )
        self._dismissed_subscribers.append(callback)
        return callback

    def remove_shown_subscriber(
        self, callback: Callable[[Toast], None]
    ) -> bool:
        """Remove a previously-registered shown-subscriber."""
        try:
            self._shown_subscribers.remove(callback)
            return True
        except ValueError:
            return False

    def remove_dismissed_subscriber(
        self, callback: Callable[[Toast], None]
    ) -> bool:
        """Remove a previously-registered dismissed-subscriber."""
        try:
            self._dismissed_subscribers.remove(callback)
            return True
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Logging integration
    # ------------------------------------------------------------------

    def subscribe_to_logging(
        self,
        threshold: int = logging.WARNING,
        logger: logging.Logger | None = None,
    ) -> _ToastLogHandler:
        """Install a log handler so records at *threshold* become toasts.

        Idempotent — a second call replaces the previous handler with a
        fresh one at the new threshold (this makes threshold updates
        trivial).
        """
        if isinstance(threshold, bool) or not isinstance(threshold, int):
            raise TypeError(
                "NotebookToastManager.subscribe_to_logging: "
                "threshold must be an int"
            )
        # If a previous handler exists, detach it first so we don't
        # double-emit toasts when the threshold changes.
        if self._log_handler is not None:
            self.unsubscribe_from_logging()
        target = logger if logger is not None else logging.getLogger()
        handler = _ToastLogHandler(self, threshold=int(threshold))
        target.addHandler(handler)
        self._log_handler = handler
        self._log_target_logger = target
        self.call_log.append(("subscribe_logging", (target.name, int(threshold))))
        return handler

    def unsubscribe_from_logging(self) -> None:
        """Remove the log handler and detach the panel reference. Idempotent."""
        handler = self._log_handler
        if handler is None:
            return
        try:
            target = self._log_target_logger or logging.getLogger()
            target.removeHandler(handler)
        except Exception:
            pass
        try:
            handler.close()
        except Exception:
            pass
        self._log_handler = None
        self._log_target_logger = None
        self.call_log.append(("unsubscribe_logging", None))

    # ------------------------------------------------------------------
    # Build / refresh / destroy (headless-safe)
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Construct the overlay under *parent_tag* (headless-safe)."""
        self._parent_tag = parent_tag
        self._built = True
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                self._build_toasts(dpg)
        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

    def _build_toasts(self, dpg: Any) -> None:
        """Render the visible toasts (headless-safe)."""
        visible = self.visible_toasts()
        if not visible:
            try:
                dpg.add_text("(no toasts)")
            except Exception:
                pass
            return
        for t in visible:
            border = list(LEVEL_BORDER_COLORS.get(
                t.level, (200, 200, 200, 255)
            ))
            try:
                # Small floating "washi-tape-cornered" child window.
                with dpg.child_window(
                    tag=f"{self._ROOT_TAG}__{t.id}",
                    border=True, width=280, height=64,
                ):
                    # Washi-tape corners (four coloured chips).
                    try:
                        with dpg.group(horizontal=True):
                            dpg.add_text("+", color=border)
                            dpg.add_text("...")
                            dpg.add_text("+", color=border)
                    except Exception:
                        pass
                    try:
                        with dpg.group(horizontal=True):
                            if t.sticker_glyph:
                                dpg.add_text(
                                    f"[{t.sticker_glyph}]", color=border
                                )
                            dpg.add_text(
                                f"{t.level.value}: {t.message}",
                                color=border,
                            )
                    except Exception:
                        try:
                            dpg.add_text(
                                f"{t.level.value}: {t.message}"
                            )
                        except Exception:
                            pass
                    try:
                        with dpg.group(horizontal=True):
                            dpg.add_text("+", color=border)
                            dpg.add_text("...")
                            dpg.add_text("+", color=border)
                    except Exception:
                        pass
            except Exception:
                try:
                    dpg.add_text(f"{t.level.value}: {t.message}")
                except Exception:
                    pass

    def refresh(self) -> None:
        """Rebuild the toast children under the existing root tag."""
        dpg = _safe_dpg()
        if dpg is None:
            return
        try:
            if dpg.does_item_exist(self._ROOT_TAG):
                for child in list(
                    dpg.get_item_children(self._ROOT_TAG, slot=1) or []
                ):
                    try:
                        dpg.delete_item(child)
                    except Exception:
                        pass
                with dpg.group(parent=self._ROOT_TAG):
                    self._build_toasts(dpg)
        except Exception:
            try:
                self._build_toasts(dpg)
            except Exception:
                pass

    def destroy(self) -> None:
        """Tear down subscribers and drop all live toasts."""
        self.unsubscribe_from_logging()
        self._shown_subscribers.clear()
        self._dismissed_subscribers.clear()
        self._toasts.clear()
        self._built = False


__all__ = [
    "LEVEL_BORDER_COLORS",
    "NotebookToastManager",
    "STICKER_OPTIONS",
    "Toast",
    "ToastLevel",
    "_ToastLogHandler",
    "normalise_toast_level",
]
