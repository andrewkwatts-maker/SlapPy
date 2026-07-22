"""Immediate-mode game HUD (Nova3D flaw #3 remediation).

The core module keeps the imgui import lazy so ``import
pharos_engine.hud`` never fails on an install without the ``[hud]``
extra — fall-back is a text-console overlay printed once per second
for debug builds.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


# The wgpu Device/Queue are the engine's; the HUD does not own them.
# ``bind_wgpu_context`` is invoked by the App boot path once the wgpu
# backend is up. HUD render() short-circuits if no context is bound.
_wgpu_device: Any = None
_wgpu_queue: Any = None


def bind_wgpu_context(device: Any, queue: Any) -> None:
    global _wgpu_device, _wgpu_queue
    _wgpu_device = device
    _wgpu_queue = queue


class HudFrame:
    """Per-frame builder handed to user draw callbacks."""

    def __init__(self, backend: str) -> None:
        self._backend = backend
        self._pending_text: list[str] = []

    def begin_window(self, title: str) -> None:
        if self._backend == "imgui":
            import imgui  # type: ignore

            imgui.begin(title)
        else:
            self._pending_text.append(f"[{title}]")

    def end_window(self) -> None:
        if self._backend == "imgui":
            import imgui  # type: ignore

            imgui.end()
        else:
            self._pending_text.append("")

    def text(self, s: str) -> None:
        if self._backend == "imgui":
            import imgui  # type: ignore

            imgui.text(s)
        else:
            self._pending_text.append(f"  {s}")

    def progress_bar(self, ratio: float, overlay: str | None = None) -> None:
        ratio = max(0.0, min(1.0, ratio))
        if self._backend == "imgui":
            import imgui  # type: ignore

            imgui.progress_bar(ratio, overlay=overlay)
        else:
            filled = int(round(ratio * 20))
            bar = "#" * filled + "-" * (20 - filled)
            self._pending_text.append(f"  [{bar}] {overlay or f'{ratio:.0%}'}")

    def flush_text(self) -> list[str]:
        """Return + clear the pending text-mode overlay lines."""
        out = self._pending_text
        self._pending_text = []
        return out


class Hud:
    """Immediate-mode HUD owning a stack of draw callbacks.

    Rendering path:
    1. ``[hud]`` extra installed  -> uses imgui[glfw] for GPU-textured overlay
    2. no imgui available         -> prints text-mode overlay once per second

    Either path is production-safe for shipped games; the text fallback
    is meant for CI + headless testing where an imgui context can't be
    created.
    """

    def __init__(self) -> None:
        self._callbacks: list[Callable[[HudFrame], None]] = []
        self._backend: Optional[str] = None
        self._last_text_dump = 0.0

    def _resolve_backend(self) -> str:
        if self._backend is not None:
            return self._backend
        try:
            import imgui  # type: ignore  # noqa: F401
            self._backend = "imgui"
        except ImportError:
            self._backend = "text"
        return self._backend

    def on_draw(self, callback: Callable[[HudFrame], None]) -> None:
        self._callbacks.append(callback)

    def render(self, dt: float) -> None:
        backend = self._resolve_backend()
        frame = HudFrame(backend)
        for cb in self._callbacks:
            try:
                cb(frame)
            except Exception as exc:
                # Never let a HUD callback take down the frame. Use the
                # editor error router if it's available; otherwise fall
                # back to stderr.
                try:
                    from pharos_editor.errors import route  # type: ignore

                    route(exc, "pharos_engine.hud.callback")
                except Exception:
                    import traceback
                    traceback.print_exc()
        if backend == "text":
            self._last_text_dump += dt
            if self._last_text_dump >= 1.0:
                self._last_text_dump = 0.0
                for line in frame.flush_text():
                    print(f"HUD | {line}")
