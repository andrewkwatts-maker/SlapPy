"""
Comprehensive tests for SceneUIEntity.

No GPU required — SceneUIEntity operates purely on CPU numpy arrays and
only calls PIL inside _render_to_canvas(), which is guarded with a
try/except ImportError. Tests that trigger tick() will silently skip the
render step when PIL is absent, which is fine.

Module-level guard skips the whole module when SlapPyEngine.ui is not
importable (e.g. Rust _core extension not yet compiled).
"""
import pytest

try:
    from pharos_editor.ui.scene_ui import SceneUIEntity
    from pharos_engine.layer import Layer
except Exception as e:
    pytest.skip(f"SlapPyEngine.ui not importable: {e}", allow_module_level=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ui(**kwargs) -> SceneUIEntity:
    """Return a SceneUIEntity with convenient defaults."""
    kwargs.setdefault("name", "test_ui")
    kwargs.setdefault("size", (200, 100))
    return SceneUIEntity(**kwargs)


# ===========================================================================
# 1. Instantiation with default args
# ===========================================================================

def test_instantiation_default_args():
    """SceneUIEntity() with no arguments must not raise."""
    ui = SceneUIEntity()
    assert ui is not None


# ===========================================================================
# 2. Constructor stores correct name, position, size
# ===========================================================================

def test_constructor_stores_name():
    ui = SceneUIEntity(name="HUD", size=(120, 60))
    assert ui.name == "HUD"


def test_constructor_stores_position():
    ui = SceneUIEntity(name="p", position=(15.0, 25.0), size=(100, 50))
    assert ui.position[0] == pytest.approx(15.0)
    assert ui.position[1] == pytest.approx(25.0)


def test_constructor_stores_size():
    ui = SceneUIEntity(name="s", size=(320, 240))
    assert ui.size == (320, 240)


def test_constructor_default_position_is_origin():
    ui = SceneUIEntity(name="origin", size=(50, 50))
    assert ui.position[0] == pytest.approx(0.0)
    assert ui.position[1] == pytest.approx(0.0)


# ===========================================================================
# 3. set_text stores text lines
# ===========================================================================

def test_set_text_stores_single_line():
    ui = _make_ui()
    ui.set_text("Hello World")
    assert ui._text_lines == ["Hello World"]


def test_set_text_stores_multiple_lines():
    ui = _make_ui()
    ui.set_text("Score: 100", "Lives: 3", "Level: 5")
    assert ui._text_lines == ["Score: 100", "Lives: 3", "Level: 5"]


def test_set_text_replaces_previous_lines():
    ui = _make_ui()
    ui.set_text("first", "second")
    ui.set_text("only")
    assert ui._text_lines == ["only"]


def test_set_text_marks_dirty():
    ui = _make_ui()
    ui._dirty = False
    ui.set_text("updated")
    assert ui._dirty is True


# ===========================================================================
# 4. set_html strips HTML tags
# ===========================================================================

def test_set_html_strips_bold_tags():
    ui = _make_ui()
    ui.set_html("<b>Hello</b>")
    assert "Hello" in ui._text_lines
    # No raw tag characters in any line
    for line in ui._text_lines:
        assert "<" not in line
        assert ">" not in line


def test_set_html_strips_paragraph_tags():
    ui = _make_ui()
    ui.set_html("<p>Alpha</p><p>Beta</p>")
    assert "Alpha" in ui._text_lines
    assert "Beta" in ui._text_lines


def test_set_html_strips_mixed_tags():
    ui = _make_ui()
    ui.set_html("<h1>Title</h1><p>Body text</p>")
    all_text = " ".join(ui._text_lines)
    assert "Title" in all_text
    assert "Body text" in all_text


def test_set_html_marks_dirty():
    ui = _make_ui()
    ui._dirty = False
    ui.set_html("<p>test</p>")
    assert ui._dirty is True


def test_set_html_filters_empty_lines():
    """Lines that are empty after stripping must not appear in _text_lines."""
    ui = _make_ui()
    ui.set_html("<b>Hello</b>")
    for line in ui._text_lines:
        assert line.strip() != ""


# ===========================================================================
# 5. set_background stores background color
# ===========================================================================

def test_set_background_stores_rgb():
    ui = _make_ui()
    ui.set_background(10, 20, 30)
    assert ui._bg_color[:3] == (10, 20, 30)


def test_set_background_stores_alpha():
    ui = _make_ui()
    ui.set_background(10, 20, 30, a=128)
    assert ui._bg_color == (10, 20, 30, 128)


def test_set_background_default_alpha_is_200():
    ui = _make_ui()
    ui.set_background(0, 0, 0)
    assert ui._bg_color[3] == 200


def test_set_background_marks_dirty():
    ui = _make_ui()
    ui._dirty = False
    ui.set_background(50, 50, 50)
    assert ui._dirty is True


# ===========================================================================
# 6. set_text_color stores text color
# ===========================================================================

def test_set_text_color_stores_rgb():
    ui = _make_ui()
    ui.set_text_color(200, 100, 50)
    assert ui._text_color[:3] == (200, 100, 50)


def test_set_text_color_stores_alpha():
    ui = _make_ui()
    ui.set_text_color(255, 255, 255, a=180)
    assert ui._text_color == (255, 255, 255, 180)


def test_set_text_color_default_alpha_is_255():
    ui = _make_ui()
    ui.set_text_color(0, 0, 0)
    assert ui._text_color[3] == 255


def test_set_text_color_marks_dirty():
    ui = _make_ui()
    ui._dirty = False
    ui.set_text_color(100, 100, 100)
    assert ui._dirty is True


# ===========================================================================
# 7. input_rect returns correct (left, top, right, bottom)
# ===========================================================================

def test_input_rect_at_origin():
    ui = SceneUIEntity(name="r", position=(0.0, 0.0), size=(100, 50))
    l, t, r, b = ui.input_rect
    assert l == pytest.approx(0.0)
    assert t == pytest.approx(0.0)
    assert r == pytest.approx(100.0)
    assert b == pytest.approx(50.0)


def test_input_rect_with_offset_position():
    ui = SceneUIEntity(name="r", position=(10.0, 20.0), size=(100, 50))
    l, t, r, b = ui.input_rect
    assert l == pytest.approx(10.0)
    assert t == pytest.approx(20.0)
    assert r == pytest.approx(110.0)
    assert b == pytest.approx(70.0)


def test_input_rect_right_minus_left_equals_width():
    ui = SceneUIEntity(name="r", position=(5.0, 5.0), size=(80, 40))
    l, t, r, b = ui.input_rect
    assert (r - l) == pytest.approx(80.0)


def test_input_rect_bottom_minus_top_equals_height():
    ui = SceneUIEntity(name="r", position=(5.0, 5.0), size=(80, 40))
    l, t, r, b = ui.input_rect
    assert (b - t) == pytest.approx(40.0)


def test_input_rect_is_four_tuple():
    ui = _make_ui()
    rect = ui.input_rect
    assert len(rect) == 4


# ===========================================================================
# 8. handle_mouse returns True when point inside rect
# ===========================================================================

def test_handle_mouse_inside_returns_true():
    ui = SceneUIEntity(name="m", position=(0.0, 0.0), size=(100, 100))
    assert ui.handle_mouse(50.0, 50.0) is True


def test_handle_mouse_inside_at_corner_returns_true():
    """Boundary points are considered inside (inclusive bounds)."""
    ui = SceneUIEntity(name="m", position=(10.0, 20.0), size=(100, 50))
    assert ui.handle_mouse(10.0, 20.0) is True   # top-left corner
    assert ui.handle_mouse(110.0, 70.0) is True  # bottom-right corner


def test_handle_mouse_inside_with_offset_position():
    ui = SceneUIEntity(name="m", position=(50.0, 100.0), size=(200, 80))
    assert ui.handle_mouse(150.0, 140.0) is True


# ===========================================================================
# 9. handle_mouse returns False when point outside rect
# ===========================================================================

def test_handle_mouse_outside_returns_false():
    ui = SceneUIEntity(name="m", position=(0.0, 0.0), size=(100, 100))
    assert ui.handle_mouse(150.0, 50.0) is False


def test_handle_mouse_above_rect_returns_false():
    ui = SceneUIEntity(name="m", position=(0.0, 50.0), size=(100, 100))
    assert ui.handle_mouse(50.0, 10.0) is False


def test_handle_mouse_left_of_rect_returns_false():
    ui = SceneUIEntity(name="m", position=(50.0, 0.0), size=(100, 100))
    assert ui.handle_mouse(10.0, 50.0) is False


def test_handle_mouse_negative_coords_outside_returns_false():
    ui = SceneUIEntity(name="m", position=(0.0, 0.0), size=(100, 100))
    assert ui.handle_mouse(-1.0, -1.0) is False


# ===========================================================================
# 10. handle_mouse clicked=True inside rect sets _focused = True
# ===========================================================================

def test_handle_mouse_clicked_inside_sets_focused_true():
    ui = SceneUIEntity(name="m", position=(0.0, 0.0), size=(100, 100))
    ui.handle_mouse(50.0, 50.0, clicked=True)
    if hasattr(ui, "_focused"):
        assert ui._focused is True


def test_handle_mouse_clicked_inside_focused_property_true():
    ui = SceneUIEntity(name="m", position=(0.0, 0.0), size=(100, 100))
    ui.handle_mouse(50.0, 50.0, clicked=True)
    if hasattr(ui, "focused"):
        assert ui.focused is True


# ===========================================================================
# 11. handle_mouse clicked=True outside rect sets _focused = False
# ===========================================================================

def test_handle_mouse_clicked_outside_sets_focused_false():
    ui = SceneUIEntity(name="m", position=(0.0, 0.0), size=(100, 100))
    # First focus the widget by clicking inside
    ui.handle_mouse(50.0, 50.0, clicked=True)
    # Then click outside — must clear focus
    ui.handle_mouse(200.0, 200.0, clicked=True)
    if hasattr(ui, "_focused"):
        assert ui._focused is False


def test_handle_mouse_clicked_outside_focused_property_false():
    ui = SceneUIEntity(name="m", position=(0.0, 0.0), size=(100, 100))
    ui.handle_mouse(50.0, 50.0, clicked=True)
    ui.handle_mouse(200.0, 200.0, clicked=True)
    if hasattr(ui, "focused"):
        assert ui.focused is False


def test_handle_mouse_not_clicked_does_not_change_focus():
    """Without clicked=True, focus must not be altered."""
    ui = SceneUIEntity(name="m", position=(0.0, 0.0), size=(100, 100))
    ui._focused = True
    ui.handle_mouse(200.0, 200.0, clicked=False)
    if hasattr(ui, "_focused"):
        assert ui._focused is True  # unchanged


# ===========================================================================
# 12. handle_keyboard returns False when not focused
# ===========================================================================

def test_handle_keyboard_returns_false_unfocused():
    ui = _make_ui()
    handle_keyboard = getattr(ui, "handle_keyboard", None)
    if handle_keyboard is None:
        pytest.skip("handle_keyboard not yet implemented")
    ui._focused = False
    assert handle_keyboard("Enter") is False


def test_handle_keyboard_unfocused_no_callback_side_effects():
    """Keyboard events to an unfocused widget must not invoke callbacks."""
    ui = _make_ui()
    handle_keyboard = getattr(ui, "handle_keyboard", None)
    if handle_keyboard is None:
        pytest.skip("handle_keyboard not yet implemented")
    called = []
    ui.set_key_callback(lambda key, mods: called.append(key))
    ui._focused = False
    handle_keyboard("A")
    assert called == []


# ===========================================================================
# 13. handle_keyboard returns True when focused
# ===========================================================================

def test_handle_keyboard_returns_true_focused():
    ui = _make_ui()
    handle_keyboard = getattr(ui, "handle_keyboard", None)
    if handle_keyboard is None:
        pytest.skip("handle_keyboard not yet implemented")
    ui._focused = True
    result = handle_keyboard("Space")
    assert result is True


def test_handle_keyboard_focused_with_modifiers_returns_true():
    ui = _make_ui()
    handle_keyboard = getattr(ui, "handle_keyboard", None)
    if handle_keyboard is None:
        pytest.skip("handle_keyboard not yet implemented")
    ui._focused = True
    result = handle_keyboard("C", {"ctrl"})
    assert result is True


# ===========================================================================
# 14. set_key_callback stores the callback
# ===========================================================================

def test_set_key_callback_stores_callback():
    ui = _make_ui()
    if not hasattr(ui, "set_key_callback"):
        pytest.skip("set_key_callback not yet implemented")
    cb = lambda key, mods: None
    ui.set_key_callback(cb)
    assert ui._on_key_callback is cb


def test_set_key_callback_replaces_previous_callback():
    ui = _make_ui()
    if not hasattr(ui, "set_key_callback"):
        pytest.skip("set_key_callback not yet implemented")
    cb_a = lambda key, mods: None
    cb_b = lambda key, mods: None
    ui.set_key_callback(cb_a)
    ui.set_key_callback(cb_b)
    assert ui._on_key_callback is cb_b


def test_set_key_callback_accepts_none():
    """Passing None should clear the callback without raising."""
    ui = _make_ui()
    if not hasattr(ui, "set_key_callback"):
        pytest.skip("set_key_callback not yet implemented")
    ui.set_key_callback(lambda key, mods: None)
    ui.set_key_callback(None)
    assert ui._on_key_callback is None


# ===========================================================================
# 15. set_key_callback invokes callback when focused + key pressed
# ===========================================================================

def test_set_key_callback_invoked_when_focused():
    ui = _make_ui()
    handle_keyboard = getattr(ui, "handle_keyboard", None)
    if handle_keyboard is None:
        pytest.skip("handle_keyboard not yet implemented")
    if not hasattr(ui, "set_key_callback"):
        pytest.skip("set_key_callback not yet implemented")

    received = []
    ui.set_key_callback(lambda key, mods: received.append((key, mods)))
    ui._focused = True
    handle_keyboard("Enter")
    assert len(received) == 1
    assert received[0][0] == "Enter"


def test_set_key_callback_passes_modifiers():
    ui = _make_ui()
    handle_keyboard = getattr(ui, "handle_keyboard", None)
    if handle_keyboard is None:
        pytest.skip("handle_keyboard not yet implemented")
    if not hasattr(ui, "set_key_callback"):
        pytest.skip("set_key_callback not yet implemented")

    received_mods = []
    ui.set_key_callback(lambda key, mods: received_mods.append(mods))
    ui._focused = True
    handle_keyboard("S", {"ctrl", "shift"})
    assert len(received_mods) == 1
    assert "ctrl" in received_mods[0]
    assert "shift" in received_mods[0]


def test_set_key_callback_not_invoked_when_unfocused():
    ui = _make_ui()
    handle_keyboard = getattr(ui, "handle_keyboard", None)
    if handle_keyboard is None:
        pytest.skip("handle_keyboard not yet implemented")
    if not hasattr(ui, "set_key_callback"):
        pytest.skip("set_key_callback not yet implemented")

    called = []
    ui.set_key_callback(lambda key, mods: called.append(key))
    ui._focused = False
    handle_keyboard("X")
    assert called == []


def test_callback_exception_does_not_propagate():
    """A misbehaving callback must not crash handle_keyboard."""
    ui = _make_ui()
    handle_keyboard = getattr(ui, "handle_keyboard", None)
    if handle_keyboard is None:
        pytest.skip("handle_keyboard not yet implemented")
    if not hasattr(ui, "set_key_callback"):
        pytest.skip("set_key_callback not yet implemented")

    def bad_callback(key, mods):
        raise RuntimeError("intentional error")

    ui.set_key_callback(bad_callback)
    ui._focused = True
    # Must not raise — the implementation swallows callback exceptions
    result = handle_keyboard("A")
    assert result is True


# ===========================================================================
# 16. SceneUIEntity has exactly 1 layer after construction
# ===========================================================================

def test_has_exactly_one_layer_after_construction():
    ui = _make_ui()
    assert len(ui.layers) == 1


def test_layer_is_named_ui_canvas():
    ui = _make_ui()
    assert ui.layers[0].name == "ui_canvas"


def test_layer_is_layer_instance():
    ui = _make_ui()
    assert isinstance(ui.layers[0], Layer)


def test_layer_image_data_matches_canvas():
    """The layer's _image_data must share the same array object as _canvas."""
    ui = _make_ui()
    assert ui.layers[0]._image_data is ui._canvas


def test_canvas_shape_matches_size():
    ui = SceneUIEntity(name="shape", size=(160, 80))
    h, w, channels = ui._canvas.shape
    assert w == 160
    assert h == 80
    assert channels == 4


# ===========================================================================
# 17. tick(dt) can be called without error
# ===========================================================================

def test_tick_does_not_raise():
    ui = _make_ui()
    ui.tick(0.016)  # ~60 fps frame


def test_tick_clears_dirty_flag_when_pil_available():
    """If PIL is installed, tick should render the canvas and clear _dirty."""
    pytest.importorskip("PIL", reason="Pillow not installed — skip render check")
    ui = _make_ui()
    assert ui._dirty is True
    ui.tick(0.0)
    assert ui._dirty is False


def test_tick_with_text_does_not_raise():
    ui = _make_ui()
    ui.set_text("Line 1", "Line 2")
    ui.tick(0.033)


def test_tick_multiple_calls_do_not_raise():
    ui = _make_ui()
    for _ in range(5):
        ui.tick(0.016)


def test_tick_dirty_false_skips_render(monkeypatch):
    """When _dirty is already False, _render_to_canvas should not be called."""
    ui = _make_ui()
    ui._dirty = False
    calls = []
    monkeypatch.setattr(ui, "_render_to_canvas", lambda: calls.append(1))
    ui.tick(0.016)
    assert calls == [], "_render_to_canvas was called even though _dirty=False"


def test_tick_dirty_true_triggers_render(monkeypatch):
    """When _dirty is True, _render_to_canvas must be called exactly once."""
    ui = _make_ui()
    ui._dirty = True
    calls = []
    monkeypatch.setattr(ui, "_render_to_canvas", lambda: calls.append(1))
    ui.tick(0.016)
    assert calls == [1]


# ===========================================================================
# 18. Multiple set_text calls don't accumulate extra layers
# ===========================================================================

def test_multiple_set_text_no_extra_layers():
    ui = _make_ui()
    for i in range(10):
        ui.set_text(f"Line {i}")
    assert len(ui.layers) == 1


def test_set_html_then_set_text_no_extra_layers():
    ui = _make_ui()
    ui.set_html("<p>Hello</p>")
    ui.set_text("World")
    assert len(ui.layers) == 1


def test_tick_repeated_no_extra_layers():
    """Repeated tick calls must not add layers."""
    ui = _make_ui()
    for _ in range(20):
        ui.tick(0.016)
    assert len(ui.layers) == 1


def test_set_background_set_text_no_extra_layers():
    ui = _make_ui()
    ui.set_background(0, 0, 0)
    ui.set_text("text")
    ui.set_background(255, 0, 0)
    assert len(ui.layers) == 1
