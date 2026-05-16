"""
HTML5 overlay via pywebview — renders a transparent HTML/CSS/JS window above wgpu.

Optional extra: pip install playslap[editor]
pywebview creates a native transparent window layered above the wgpu output.

Limitations:
- Windows: requires EdgeHTML/WebView2 backend
- macOS: requires WebKit
- Linux: requires GTK+WebKit2
- Position/size must be set to match the wgpu canvas window exactly
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class HtmlOverlay:
    """
    Transparent HTML5 overlay above the wgpu canvas.

    Usage:
        overlay = HtmlOverlay(width=800, height=600)
        overlay.set_html('<div style="color:white">Health: 100</div>')
        overlay.show()
        # ... game loop runs ...
        overlay.hide()
        overlay.destroy()
    """

    def __init__(self, width: int = 800, height: int = 600, title: str = ""):
        try:
            import webview  # pywebview
            self._webview = webview
        except ImportError as exc:
            raise ImportError(
                "pywebview is required for the HTML overlay. "
                "Install it with: pip install playslap[editor]"
            ) from exc

        self._width = width
        self._height = height
        self._title = title
        self._window = None
        self._html = "<html><body></body></html>"
        self._running = False

    def set_html(self, html: str) -> None:
        """Set the full HTML content of the overlay."""
        self._html = html
        if self._window is not None:
            try:
                self._window.load_html(html)
            except Exception:
                pass

    def set_hud(self, items: dict[str, str]) -> None:
        """
        Convenience: render a HUD from a dict of {label: value} pairs.
        Items are rendered as a transparent overlay with white text.
        """
        rows = "".join(
            f'<div style="margin:4px 0">'
            f'<span style="opacity:0.7">{k}: </span>'
            f'<span style="font-weight:bold">{v}</span>'
            f'</div>'
            for k, v in items.items()
        )
        html = f"""
        <html>
        <head><style>
            body {{
                margin: 12px;
                font-family: monospace;
                font-size: 14px;
                color: white;
                background: transparent;
                pointer-events: none;
                user-select: none;
            }}
        </style></head>
        <body>{rows}</body>
        </html>
        """
        self.set_html(html)

    def show(self) -> None:
        """Create and show the overlay window (blocking — run in a thread)."""
        import threading

        def _run():
            self._window = self._webview.create_window(
                title=self._title,
                html=self._html,
                width=self._width,
                height=self._height,
                transparent=True,
                frameless=True,
                on_top=True,
                background_color="#00000000",
            )
            self._webview.start(debug=False)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()
        self._running = True

    def hide(self) -> None:
        """Hide the overlay window."""
        if self._window is not None:
            try:
                self._window.hide()
            except Exception:
                pass

    def destroy(self) -> None:
        """Destroy the overlay window and clean up."""
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
            self._window = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running
