import pytest
import numpy as np
from PIL import Image

def test_theme_dark():
    from pharos_engine.ui.widgets import Theme
    t = Theme.dark()
    assert len(t.primary) == 4

def test_theme_light():
    from pharos_engine.ui.widgets import Theme
    t = Theme.light()
    assert t.surface[0] > 200  # light background

def test_label_bind():
    from pharos_engine.ui.widgets import Label
    class State:
        score = 42
    s = State()
    lbl = Label("test", x=0, y=0, w=100, h=30)
    lbl.bind(s, "score")
    s.score = 99
    lbl.update()
    assert lbl.dirty

def test_button_click():
    from pharos_engine.ui.widgets import Button
    clicked = []
    btn = Button("OK", x=0, y=0, w=80, h=30)
    btn.on_click(lambda w: clicked.append(True))
    btn.handle_event({"type": "mouse_down", "x": 10, "y": 10})
    assert len(clicked) == 1

def test_button_no_click_outside():
    from pharos_engine.ui.widgets import Button
    clicked = []
    btn = Button("OK", x=0, y=0, w=80, h=30)
    btn.on_click(lambda w: clicked.append(True))
    btn.handle_event({"type": "mouse_down", "x": 200, "y": 200})
    assert len(clicked) == 0

def test_progress_bar_clamp():
    from pharos_engine.ui.widgets import ProgressBar
    pb = ProgressBar(value=1.5)
    # draw should not crash
    img = Image.new("RGBA", (200, 40))
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    pb.draw(draw)

def test_slider_normalised():
    from pharos_engine.ui.widgets import Slider
    s = Slider(value=0.5, min_val=0.0, max_val=2.0, x=0, y=0, w=100, h=20)
    assert s.normalised == pytest.approx(0.25)

def test_checkbox_toggle():
    from pharos_engine.ui.widgets import Checkbox
    cb = Checkbox(checked=False, x=0, y=0, w=30, h=30)
    cb.handle_event({"type": "mouse_down", "x": 10, "y": 10})
    assert cb.checked is True
    cb.handle_event({"type": "mouse_down", "x": 10, "y": 10})
    assert cb.checked is False

def test_dropdown_select():
    from pharos_engine.ui.widgets import Dropdown
    dd = Dropdown(options=["A","B","C"], selected=0, x=0, y=0, w=100, h=30)
    # Open
    dd.handle_event({"type": "mouse_down", "x": 10, "y": 10})
    assert dd._open
    # Select second option
    dd.handle_event({"type": "mouse_down", "x": 10, "y": 45})
    assert dd.selected == 1
    assert dd.value == "B"

def test_layout_box_column():
    from pharos_engine.ui.widgets import LayoutBox, Button, Label
    box = LayoutBox(direction="column", gap=5, padding=10, x=0, y=0, w=200, h=300)
    box.add(Label("test", w=100, h=20))
    box.add(Button("OK", w=80, h=30))
    box.layout()
    children = [c for c in box._children]
    # First child should be at y=10 (padding)
    assert children[0].y == pytest.approx(10.0)
    # Second at y=10+20+5=35
    assert children[1].y == pytest.approx(35.0)

def test_layout_box_row():
    from pharos_engine.ui.widgets import LayoutBox, Button
    box = LayoutBox(direction="row", gap=5, padding=10, x=0, y=0, w=300, h=50)
    box.add(Button("A", w=60, h=30))
    box.add(Button("B", w=60, h=30))
    box.layout()
    children = list(box._children)
    assert children[0].x == pytest.approx(10.0)
    assert children[1].x == pytest.approx(75.0)  # 10+60+5

def test_render_to_layer():
    from pharos_engine.ui.widgets import LayoutBox, Label, Button
    box = LayoutBox(direction="column", x=0, y=0, w=200, h=100)
    box.add(Label("Hello", x=10, y=10, w=100, h=20))
    box.add(Button("Click", x=10, y=40, w=80, h=30))
    box.layout()
    layer = box.render_to_layer(size=(200, 100))
    assert layer is not None
    assert layer._image_data is not None
    assert layer._image_data.shape == (100, 200, 4)

def test_panel_children():
    from pharos_engine.ui.widgets import Panel, Label
    p = Panel(x=0, y=0, w=200, h=150)
    p.add(Label("child", x=10, y=10, w=80, h=20))
    assert len(p.children) == 1

def test_theme_apply_cascade():
    from pharos_engine.ui.widgets import Theme, Panel, Label, Button
    dark = Theme.dark()
    light = Theme.light()
    p = Panel(x=0, y=0, w=100, h=100)
    p.add(Label("test", w=80, h=20))
    p.apply_theme(light)
    for child in p.children:
        assert child._theme.surface == light.surface
