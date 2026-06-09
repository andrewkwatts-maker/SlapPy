"""Tests for :class:`NotebookPostProcessPanel`.

Coverage:

* Construction — empty default chain + custom chain.
* Toggle pass — flips ``enabled``, raises on unknown label.
* Reorder — up / down + clamped at the boundaries.
* Remove — drops the matching pass, raises on unknown.
* Add — appends from the factory map; rejects unknown names.
* Preset — replaces the chain with cinematic / arcade / iso_strategy.
* Param set — mutates the inline tweak.
* Status counts.
* Theme switch — listener fires.
* Build under stub DPG.
"""
from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub (shared shape with the welcome / outliner tests)
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_slider_float(self, *a, **kw):
        self._track("add_slider_float", a, kw)

    def add_slider_int(self, *a, **kw):
        self._track("add_slider_int", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "window", "child_window",
        "add_text", "add_button", "add_input_text",
        "add_checkbox", "add_separator",
        "add_slider_float", "add_slider_int",
        "does_item_exist", "delete_item", "get_item_children",
        "set_value",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
        return _noop
    mod.__getattr__ = _fallback

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_state():
    from slappyengine.ui.widgets import notebook_theme
    from slappyengine.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_panel(**kwargs):
    from slappyengine.ui.editor.notebook_post_process_panel import (
        NotebookPostProcessPanel,
    )
    return NotebookPostProcessPanel(**kwargs)


def _make_chain_with_bloom():
    from slappyengine.post_process.chain import PostProcessChain
    chain = PostProcessChain()
    chain.add_bloom(intensity=1.0)
    chain.add_vignette(strength=0.5)
    return chain


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_empty_chain(self):
        panel = _make_panel()
        assert panel.passes == []

    def test_constructs_with_chain(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        labels = [p.label for p in panel.passes]
        assert labels == ["bloom", "vignette"]

    def test_rejects_non_callable_callback(self):
        from slappyengine.ui.editor.notebook_post_process_panel import (
            NotebookPostProcessPanel,
        )
        with pytest.raises(TypeError):
            NotebookPostProcessPanel(on_chain_changed=42)


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------


class TestToggle:
    def test_toggle_flips_enabled(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        state = panel.toggle_pass("bloom")
        assert state is False
        assert chain._passes[0].enabled is False
        state = panel.toggle_pass("bloom")
        assert state is True

    def test_toggle_unknown_raises(self):
        panel = _make_panel(chain=_make_chain_with_bloom())
        with pytest.raises(KeyError):
            panel.toggle_pass("does_not_exist")


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------


class TestReorder:
    def test_move_down(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        panel.move_pass("bloom", +1)
        labels = [p.label for p in panel.passes]
        assert labels == ["vignette", "bloom"]

    def test_move_up(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        panel.move_pass("vignette", -1)
        labels = [p.label for p in panel.passes]
        assert labels == ["vignette", "bloom"]

    def test_move_at_top_is_noop(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        panel.move_pass("bloom", -1)
        labels = [p.label for p in panel.passes]
        assert labels == ["bloom", "vignette"]

    def test_move_at_bottom_is_noop(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        panel.move_pass("vignette", +1)
        labels = [p.label for p in panel.passes]
        assert labels == ["bloom", "vignette"]

    def test_move_unknown_raises(self):
        panel = _make_panel(chain=_make_chain_with_bloom())
        with pytest.raises(KeyError):
            panel.move_pass("ghost", +1)


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


class TestRemove:
    def test_remove_existing(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        panel.remove_pass("bloom")
        labels = [p.label for p in panel.passes]
        assert labels == ["vignette"]

    def test_remove_unknown_raises(self):
        panel = _make_panel(chain=_make_chain_with_bloom())
        with pytest.raises(KeyError):
            panel.remove_pass("ghost")


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------


class TestAdd:
    def test_add_bloom(self):
        panel = _make_panel()
        panel.add_pass("bloom")
        labels = [p.label for p in panel.passes]
        assert labels == ["bloom"]

    def test_add_unknown_raises(self):
        panel = _make_panel()
        with pytest.raises(KeyError):
            panel.add_pass("not_a_real_pass")


# ---------------------------------------------------------------------------
# Preset
# ---------------------------------------------------------------------------


class TestPreset:
    def test_cinematic_preset_replaces_chain(self):
        panel = _make_panel()
        chain = panel.apply_preset("cinematic")
        assert panel.chain is chain
        labels = [p.label for p in panel.passes]
        assert "bloom" in labels
        assert "tonemap" in labels

    def test_arcade_preset(self):
        panel = _make_panel()
        panel.apply_preset("arcade")
        labels = [p.label for p in panel.passes]
        assert labels[0] == "bloom"

    def test_iso_preset(self):
        panel = _make_panel()
        panel.apply_preset("iso_strategy")
        labels = [p.label for p in panel.passes]
        assert "bloom" in labels

    def test_unknown_preset_raises(self):
        panel = _make_panel()
        with pytest.raises(KeyError):
            panel.apply_preset("unknown_preset")


# ---------------------------------------------------------------------------
# Param set
# ---------------------------------------------------------------------------


class TestSetParam:
    def test_set_param_mutates_pass(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        panel.set_param("bloom", "intensity", 2.0)
        assert chain._passes[0].params["intensity"] == 2.0

    def test_set_param_unknown_label_raises(self):
        panel = _make_panel(chain=_make_chain_with_bloom())
        with pytest.raises(KeyError):
            panel.set_param("ghost", "intensity", 1.0)


# ---------------------------------------------------------------------------
# Status / callback
# ---------------------------------------------------------------------------


class TestStatusCallback:
    def test_on_chain_changed_fires(self):
        chain = _make_chain_with_bloom()
        seen: list[object] = []
        panel = _make_panel(chain=chain, on_chain_changed=seen.append)
        panel.toggle_pass("bloom")
        assert seen and seen[-1] is chain

    def test_status_counts(self):
        chain = _make_chain_with_bloom()
        panel = _make_panel(chain=chain)
        msg = panel._format_status()
        assert "passes: 2" in msg
        assert "enabled: 2" in msg


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------


class TestThemeIntegration:
    def test_theme_switch_logs(self):
        from slappyengine.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        panel = _make_panel()
        theme = NotebookTheme(name="alt")
        set_active_theme(theme)
        assert any(call[0] == "theme_changed" for call in panel.call_log)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_does_not_raise(self, stub_dpg):
        panel = _make_panel(chain=_make_chain_with_bloom())
        panel.build(parent_tag="root")
        assert "add_text" in stub_dpg.calls
        panel.destroy()
