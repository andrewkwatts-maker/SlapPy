from __future__ import annotations
import re
import numpy as np
from pharos_engine.render_target import RenderTarget
from pharos_engine.layer import Layer


class SceneUIEntity(RenderTarget):

    def __init__(self, name: str = "UI", position=(0.0, 0.0), size=(200, 100)):
        super().__init__(name=name, position=position, size=size)
        self._html_content: str = ""
        self._text_lines: list[str] = []
        self._bg_color: tuple[int, int, int, int] = (30, 30, 30, 200)
        self._text_color: tuple[int, int, int, int] = (255, 255, 255, 255)
        self._dirty = True
        self._focused: bool = False
        self._on_key_callback: callable | None = None

        w, h = size
        self._canvas = np.zeros((h, w, 4), dtype=np.uint8)
        from PIL import Image as _PILImage
        self._image: "_PILImage.Image" = _PILImage.new("RGBA", (w, h), self._bg_color)
        layer = Layer.blank(w, h, name="ui_canvas")
        layer._image_data = self._canvas
        self.add_layer(layer)

    def set_html(self, html: str) -> None:
        self._html_content = html
        self._text_lines = re.sub(r'<[^>]+>', '\n', html).strip().split('\n')
        self._text_lines = [t.strip() for t in self._text_lines if t.strip()]
        self._dirty = True

    def set_text(self, *lines: str) -> None:
        self._text_lines = list(lines)
        self._dirty = True

    def set_background(self, r: int, g: int, b: int, a: int = 200) -> None:
        self._bg_color = (r, g, b, a)
        self._dirty = True

    def set_text_color(self, r: int, g: int, b: int, a: int = 255) -> None:
        self._text_color = (r, g, b, a)
        self._dirty = True

    def _render_to_canvas(self) -> None:
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return

        w, h = self.size
        img = Image.new("RGBA", (w, h), self._bg_color)
        draw = ImageDraw.Draw(img)

        y_offset = 8
        for line in self._text_lines:
            draw.text((8, y_offset), line, fill=self._text_color)
            y_offset += 18
            if y_offset > h - 8:
                break

        arr = np.asarray(img, dtype=np.uint8)
        self._canvas[:] = arr
        if self.layers:
            self.layers[0]._image_data = self._canvas
        self._image = img
        self._dirty = False

    def _render_text(self, text: str, font_size: int = 20,
                     color: tuple = (255, 255, 255)) -> None:
        from PIL import Image, ImageDraw
        fill = color + (255,) if len(color) == 3 else color
        self._image = Image.new("RGBA", self.size, self._bg_color)
        draw = ImageDraw.Draw(self._image)
        draw.text((8, 8), text, fill=fill)
        self._upload_texture()

    def _upload_texture(self) -> None:
        import numpy as np
        arr = np.asarray(self._image, dtype=np.uint8)
        if arr.shape[:2] == self._canvas.shape[:2]:
            self._canvas[:] = arr
        if self.layers:
            self.layers[0]._image_data = self._canvas
        self._dirty = False

    def tick(self, dt: float) -> None:
        super().tick(dt)
        if self._dirty:
            self._render_to_canvas()

    @property
    def input_rect(self) -> tuple[float, float, float, float]:
        x, y = self.position
        w, h = self.size
        return (x, y, x + w, y + h)

    def handle_mouse(self, screen_x: float, screen_y: float,
                     button: int = 0, pressed: bool = True,
                     clicked: bool = False) -> bool:
        l, t, r, b = self.input_rect
        inside = l <= screen_x <= r and t <= screen_y <= b
        if clicked:
            self._focused = inside
        return inside

    @property
    def focused(self) -> bool:
        return self._focused

    def set_key_callback(self, callback) -> None:
        """Set callback(key: str, modifiers: set[str]) called when focused and key pressed."""
        self._on_key_callback = callback

    def handle_keyboard(self, key: str, modifiers: set[str] | None = None) -> bool:
        if not self._focused:
            return False
        if self._on_key_callback is not None:
            try:
                self._on_key_callback(key, modifiers or set())
            except Exception:
                pass
        return True
