"""Headless tests for miscellaneous editor panel classes.

Covers (pure Python / DPG-safe paths):
- pharos_engine.ui.editor.theme          (_rgba, color constants)
- pharos_engine.ui.editor.toolbar        (EditorToolbar pure API)
- pharos_engine.ui.editor.behavior_panel (BehaviorPanel init + _on_apply + _set_status)
- pharos_engine.ui.editor.content_browser (ContentBrowser init + set_root + ICON_COLORS)
- pharos_engine.ui.editor.layer_panel    (LayerPanel init + set_on_layer_mode_change)
- pharos_engine.ui.editor.tag_painter    (TagPainter init + mode constants)
- pharos_engine.ui.editor.ollama_setup_modal (AiOptInDialog + module constants)

DPG guard
---------
dearpygui.dearpygui crashes (segfault) when called without a viewport context.
We force a safe MagicMock into sys.modules at import time so that any deferred
``import dearpygui.dearpygui as dpg`` inside panel methods gets the mock.
``does_item_exist`` is set to return False so _refresh guard clauses return
early without executing any widget code.
"""
from __future__ import annotations
import sys
import unittest.mock
import pytest
from pathlib import Path

# ---------------------------------------------------------------------------
# DPG mock — installed once, before any panel module is imported or called.
# ---------------------------------------------------------------------------
_DPG_MOCK = unittest.mock.MagicMock()
_DPG_MOCK.does_item_exist.return_value = False   # all _refresh guards exit early
sys.modules['dearpygui'] = unittest.mock.MagicMock()
sys.modules['dearpygui.dearpygui'] = _DPG_MOCK


# ---------------------------------------------------------------------------
# theme.py — _rgba helper and color constants
# ---------------------------------------------------------------------------

class TestRgbaHelper:
    def _fn(self, *args, **kwargs):
        from pharos_engine.ui.editor.theme import _rgba
        return _rgba(*args, **kwargs)

    def test_returns_list(self):
        result = self._fn((10, 20, 30))
        assert isinstance(result, list)

    def test_length_four(self):
        result = self._fn((10, 20, 30))
        assert len(result) == 4

    def test_rgb_channels(self):
        result = self._fn((10, 20, 30))
        assert result[0] == 10
        assert result[1] == 20
        assert result[2] == 30

    def test_default_alpha_255(self):
        result = self._fn((10, 20, 30))
        assert result[3] == 255

    def test_custom_alpha(self):
        result = self._fn((10, 20, 30), a=128)
        assert result[3] == 128

    def test_zero_alpha(self):
        result = self._fn((0, 0, 0), a=0)
        assert result == [0, 0, 0, 0]

    def test_full_white(self):
        result = self._fn((255, 255, 255))
        assert result == [255, 255, 255, 255]


class TestThemeColorConstants:
    def test_glass_bg_is_tuple(self):
        from pharos_engine.ui.editor.theme import _GLASS_BG
        assert isinstance(_GLASS_BG, tuple)
        assert len(_GLASS_BG) == 3

    def test_glass_accent_has_three_channels(self):
        from pharos_engine.ui.editor.theme import _GLASS_ACCENT
        assert len(_GLASS_ACCENT) == 3

    def test_glass_text_has_three_channels(self):
        from pharos_engine.ui.editor.theme import _GLASS_TEXT
        assert len(_GLASS_TEXT) == 3

    def test_success_is_green_ish(self):
        from pharos_engine.ui.editor.theme import _SUCCESS
        r, g, b = _SUCCESS
        assert g > r and g > b  # green channel dominates

    def test_error_is_red_ish(self):
        from pharos_engine.ui.editor.theme import _ERROR
        r, g, b = _ERROR
        assert r > g and r > b  # red channel dominates

    def test_warning_is_yellow_ish(self):
        from pharos_engine.ui.editor.theme import _WARNING
        r, g, b = _WARNING
        assert r > 150 and g > 150 and b < 100  # high R+G, low B = yellow

    def test_viewport_bg_is_tuple(self):
        from pharos_engine.ui.editor.theme import _VIEWPORT_BG
        assert isinstance(_VIEWPORT_BG, tuple)


# ---------------------------------------------------------------------------
# toolbar.py — EditorToolbar pure Python API
# ---------------------------------------------------------------------------

class TestEditorToolbarInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t is not None

    def test_active_tool_is_select(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t.active_tool == EditorToolbar.TOOL_SELECT

    def test_snap_disabled(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t.snap_enabled is False

    def test_mode_2d(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t.mode == "2D"

    def test_on_tool_change_none(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t._on_tool_change is None

    def test_on_mode_change_none(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t._on_mode_change is None

    def test_btn_tags_empty(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t._btn_tags == {}


class TestEditorToolbarConstants:
    def test_tool_select_constant(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        assert EditorToolbar.TOOL_SELECT == "select"

    def test_tool_translate_constant(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        assert EditorToolbar.TOOL_TRANSLATE == "translate"

    def test_tool_rotate_constant(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        assert EditorToolbar.TOOL_ROTATE == "rotate"

    def test_tool_scale_constant(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        assert EditorToolbar.TOOL_SCALE == "scale"

    def test_tools_list_has_four(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        assert len(EditorToolbar._TOOLS) == 4


class TestEditorToolbarPublicAPI:
    def test_set_on_tool_change_stores_callback(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        cb = lambda tool: None
        t.set_on_tool_change(cb)
        assert t._on_tool_change is cb

    def test_set_on_mode_change_stores_callback(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        cb = lambda mode: None
        t.set_on_mode_change(cb)
        assert t._on_mode_change is cb

    def test_get_active_tool_returns_string(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert isinstance(t.get_active_tool(), str)

    def test_get_active_tool_returns_current(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t.get_active_tool() == EditorToolbar.TOOL_SELECT

    def test_mode_property_returns_2d(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        assert t.mode == "2D"


class TestEditorToolbarSelectTool:
    """_select_tool is safe headlessly: _update_button_highlights returns
    early when themes are None (i.e., before build() is called)."""

    def test_select_tool_updates_active(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        t._select_tool(EditorToolbar.TOOL_ROTATE)
        assert t.active_tool == EditorToolbar.TOOL_ROTATE

    def test_select_tool_fires_callback(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        fired = []
        t.set_on_tool_change(lambda tool: fired.append(tool))
        t._select_tool(EditorToolbar.TOOL_TRANSLATE)
        assert fired == [EditorToolbar.TOOL_TRANSLATE]

    def test_select_tool_no_callback_no_crash(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        t._select_tool(EditorToolbar.TOOL_SCALE)  # no callback set

    def test_select_tool_multiple_times(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        fired = []
        t.set_on_tool_change(lambda tool: fired.append(tool))
        t._select_tool(EditorToolbar.TOOL_ROTATE)
        t._select_tool(EditorToolbar.TOOL_SELECT)
        assert fired == [EditorToolbar.TOOL_ROTATE, EditorToolbar.TOOL_SELECT]


class TestEditorToolbarSetMode:
    """_set_mode is safe headlessly: _update_mode_highlights returns
    early when themes are None."""

    def test_set_mode_2d_to_3d(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        t._set_mode("3D")
        assert t.mode == "3D"

    def test_set_mode_fires_callback(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        fired = []
        t.set_on_mode_change(lambda m: fired.append(m))
        t._set_mode("3D")
        assert fired == ["3D"]

    def test_set_mode_no_callback_no_crash(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        t._set_mode("3D")  # no callback set

    def test_set_mode_back_to_2d(self):
        from pharos_engine.ui.editor.toolbar import EditorToolbar
        t = EditorToolbar()
        t._set_mode("3D")
        t._set_mode("2D")
        assert t.mode == "2D"


# ---------------------------------------------------------------------------
# behavior_panel.py — BehaviorPanel
# ---------------------------------------------------------------------------

class _FakeEntity:
    def __init__(self):
        self._scripts = []

    def attach_script(self, s):
        self._scripts.append(s)


class TestBehaviorPanelInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        assert p is not None

    def test_entity_none_initially(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        assert p._entity is None

    def test_prompt_text_empty(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        assert p._prompt_text == ""

    def test_python_text_empty(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        assert p._python_text == ""

    def test_mode_is_prompt(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        assert p._mode == "prompt"

    def test_generating_false(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        assert p._generating is False

    def test_status_is_ready(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        assert p._status == "Ready"

    def test_set_entity_stores_entity(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        e = _FakeEntity()
        p.set_entity(e)
        assert p._entity is e


class TestBehaviorPanelSetStatus:
    """_set_status stores to self._status; DPG call is try/except so it's safe."""

    def test_sets_status_message(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        p._set_status("hello")
        assert p._status == "hello"

    def test_overrides_previous_status(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        p._set_status("first")
        p._set_status("second")
        assert p._status == "second"

    def test_no_crash_without_dpg(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        p._set_status("test", color=(200, 100, 100))


class TestBehaviorPanelOnApply:
    """_on_apply uses exec() — no DPG needed."""

    def _bp_with_entity(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        p._entity = _FakeEntity()
        return p

    def test_noop_when_python_text_empty(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        p._entity = _FakeEntity()
        p._on_apply()
        assert "No entity" in p._status or "no script" in p._status.lower()

    def test_noop_when_entity_none(self):
        from pharos_engine.ui.editor.behavior_panel import BehaviorPanel
        p = BehaviorPanel()
        p._python_text = "class EntityScript: pass"
        p._on_apply()
        # entity is None — should mention "No entity"
        assert "No entity" in p._status or "no" in p._status.lower()

    def test_apply_valid_script(self):
        p = self._bp_with_entity()
        p._python_text = "class EntityScript:\n    pass\n"
        p._on_apply()
        assert p._status == "Script applied!"
        assert len(p._entity._scripts) == 1

    def test_apply_attaches_instance(self):
        p = self._bp_with_entity()
        p._python_text = "class EntityScript:\n    def __init__(self): self.x=42\n"
        p._on_apply()
        assert p._entity._scripts[0].x == 42

    def test_apply_bad_script_sets_compile_error(self):
        p = self._bp_with_entity()
        p._python_text = "def not_a_class(): pass"  # no EntityScript class
        p._on_apply()
        assert "must define class EntityScript" in p._status

    def test_apply_syntax_error_reports_error(self):
        p = self._bp_with_entity()
        p._python_text = "class EntityScript: @@@invalid syntax"
        p._on_apply()
        assert "error" in p._status.lower() or "Compile error" in p._status

    def test_apply_removes_old_script_of_same_class(self):
        p = self._bp_with_entity()
        # First apply
        p._python_text = "class EntityScript:\n    version = 1\n"
        p._on_apply()
        # Second apply should replace
        p._python_text = "class EntityScript:\n    version = 2\n"
        p._on_apply()
        assert len(p._entity._scripts) == 1
        assert p._entity._scripts[0].version == 2


# ---------------------------------------------------------------------------
# content_browser.py — ContentBrowser
# ---------------------------------------------------------------------------

class TestContentBrowserInit:
    def test_instantiates_no_args(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser()
        assert cb is not None

    def test_root_defaults_to_cwd(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        import os
        cb = ContentBrowser()
        assert cb._root == Path(os.getcwd())

    def test_init_with_path_str(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser(root_path="H:/tmp")
        assert cb._root == Path("H:/tmp")

    def test_init_with_path_obj(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        p = Path("H:/tmp")
        cb = ContentBrowser(root_path=p)
        assert cb._root == p

    def test_selected_none_initially(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser()
        assert cb._selected is None

    def test_on_open_script_none_initially(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser()
        assert cb._on_open_script is None

    def test_panel_tag(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser()
        assert cb._panel_tag == "content_browser_panel"


class TestContentBrowserSetRoot:
    def test_set_root_str(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser()
        cb.set_root("H:/projects")
        assert cb._root == Path("H:/projects")

    def test_set_root_path(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser()
        p = Path("H:/projects")
        cb.set_root(p)
        assert cb._root == p

    def test_set_root_updates_current(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser()
        cb.set_root("H:/new_root")
        assert cb._current == Path("H:/new_root")

    def test_set_on_open_script_stores_callback(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        cb = ContentBrowser()
        func = lambda p: None
        cb.set_on_open_script(func)
        assert cb._on_open_script is func


class TestContentBrowserIconColors:
    def test_icon_colors_is_dict(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        assert isinstance(ContentBrowser.ICON_COLORS, dict)

    def test_py_color_present(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        assert ".py" in ContentBrowser.ICON_COLORS

    def test_png_color_present(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        assert ".png" in ContentBrowser.ICON_COLORS

    def test_folder_color_present(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        assert "folder" in ContentBrowser.ICON_COLORS

    def test_other_color_present(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        assert "other" in ContentBrowser.ICON_COLORS

    def test_colors_are_four_tuples(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        for key, color in ContentBrowser.ICON_COLORS.items():
            assert len(color) == 4, f"{key} color should have 4 channels"

    def test_slap_color_is_purpleish(self):
        from pharos_engine.ui.editor.content_browser import ContentBrowser
        r, g, b, a = ContentBrowser.ICON_COLORS[".slap"]
        assert b > r  # blue-ish purple


# ---------------------------------------------------------------------------
# layer_panel.py — LayerPanel
# ---------------------------------------------------------------------------

class TestLayerPanelInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.layer_panel import LayerPanel
        p = LayerPanel()
        assert p is not None

    def test_asset_none_initially(self):
        from pharos_engine.ui.editor.layer_panel import LayerPanel
        p = LayerPanel()
        assert p._asset is None

    def test_panel_tag(self):
        from pharos_engine.ui.editor.layer_panel import LayerPanel
        p = LayerPanel()
        assert p._panel_tag == "layer_panel"

    def test_on_mode_change_none(self):
        from pharos_engine.ui.editor.layer_panel import LayerPanel
        p = LayerPanel()
        assert p._on_mode_change is None

    def test_set_on_layer_mode_change_stores_callback(self):
        from pharos_engine.ui.editor.layer_panel import LayerPanel
        p = LayerPanel()
        cb = lambda layer, mode: None
        p.set_on_layer_mode_change(cb)
        assert p._on_mode_change is cb

    def test_set_on_layer_mode_change_replaces(self):
        from pharos_engine.ui.editor.layer_panel import LayerPanel
        p = LayerPanel()
        cb1 = lambda layer, mode: None
        cb2 = lambda layer, mode: None
        p.set_on_layer_mode_change(cb1)
        p.set_on_layer_mode_change(cb2)
        assert p._on_mode_change is cb2


# ---------------------------------------------------------------------------
# tag_painter.py — TagPainter
# ---------------------------------------------------------------------------

class TestTagPainterInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p is not None

    def test_asset_none_initially(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._asset is None

    def test_tag_registry_none_initially(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._tag_registry is None

    def test_selected_tag_none(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._selected_tag is None

    def test_paint_mode_color_range(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._paint_mode == "Color Range"

    def test_brush_radius_default(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._brush_radius == pytest.approx(0.05)

    def test_cr_r_full_range(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._cr_r == [0, 255]

    def test_cr_g_full_range(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._cr_g == [0, 255]

    def test_cr_b_full_range(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._cr_b == [0, 255]

    def test_mask_path_empty(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        p = TagPainter()
        assert p._mask_path == ""

    def test_paint_modes_list(self):
        from pharos_engine.ui.editor.tag_painter import TagPainter
        assert "Color Range" in TagPainter._PAINT_MODES
        assert "Brush" in TagPainter._PAINT_MODES
        assert "Mask Import" in TagPainter._PAINT_MODES
        assert len(TagPainter._PAINT_MODES) == 3


# ---------------------------------------------------------------------------
# ollama_setup_modal.py — AiOptInDialog + module constants
# ---------------------------------------------------------------------------

class TestAiOptInDialogInit:
    def test_instantiates(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AiOptInDialog
        d = AiOptInDialog()
        assert d is not None

    def test_choice_pending(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AiOptInDialog
        d = AiOptInDialog()
        assert d._choice is ...  # Ellipsis = pending

    def test_selected_label_is_recommended(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AiOptInDialog, AVAILABLE_MODELS
        d = AiOptInDialog()
        assert d._selected_label == AVAILABLE_MODELS[1]

    def test_custom_text_empty(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AiOptInDialog
        d = AiOptInDialog()
        assert d._custom_text == ""


class TestOllamaModuleConstants:
    def test_available_models_is_list(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AVAILABLE_MODELS
        assert isinstance(AVAILABLE_MODELS, list)

    def test_available_models_has_entries(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AVAILABLE_MODELS
        assert len(AVAILABLE_MODELS) >= 4

    def test_none_option_present(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AVAILABLE_MODELS
        assert any("None" in m for m in AVAILABLE_MODELS)

    def test_other_option_present(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AVAILABLE_MODELS
        assert any("Other" in m for m in AVAILABLE_MODELS)

    def test_model_tags_is_dict(self):
        from pharos_engine.ui.editor.ollama_setup_modal import _MODEL_TAGS
        assert isinstance(_MODEL_TAGS, dict)

    def test_none_option_maps_to_none(self):
        from pharos_engine.ui.editor.ollama_setup_modal import _MODEL_TAGS
        # The "None (disable AI sync)" key should map to None
        none_keys = [k for k in _MODEL_TAGS if "None" in k and "disable" in k]
        assert len(none_keys) >= 1
        assert _MODEL_TAGS[none_keys[0]] is None

    def test_model_tags_keys_match_available(self):
        from pharos_engine.ui.editor.ollama_setup_modal import AVAILABLE_MODELS, _MODEL_TAGS
        for model in AVAILABLE_MODELS:
            assert model in _MODEL_TAGS, f"model '{model}' missing from _MODEL_TAGS"

    def test_pull_modal_tag_constant(self):
        from pharos_engine.ui.editor.ollama_setup_modal import _PULL_MODAL
        assert isinstance(_PULL_MODAL, str)
        assert len(_PULL_MODAL) > 0

    def test_opt_modal_tag_constant(self):
        from pharos_engine.ui.editor.ollama_setup_modal import _OPT_MODAL
        assert isinstance(_OPT_MODAL, str)
