"""Tests for :class:`NotebookAnimationPanel`.

Coverage:

* Construction
* Track add / remove / clear
* Keyframe add / remove / move
* Seek clamp + ruler glyphs
* Play / pause toggle / loop
* Tick drives the playhead and respects ``loop``
* Save round-trip writes ``<entity>.anim.yaml``
* curve_preview length
* Theme switch
* bind_entity
* Build under stub DPG
"""
from __future__ import annotations

import sys
import types

import pytest


# ---------------------------------------------------------------------------
# Stub DPG
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

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

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
        "group", "child_window", "window",
        "add_text", "add_button", "add_checkbox",
        "add_separator", "add_input_text",
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
    from pharos_engine.ui.widgets import notebook_theme
    from pharos_engine.ui.widgets.notebook_theme import set_active_theme

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_panel(**kwargs):
    from pharos_engine.ui.editor.notebook_animation_panel import (
        NotebookAnimationPanel,
    )
    return NotebookAnimationPanel(**kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_errors(self):
        panel = _make_panel()
        assert panel.tracks == []
        assert panel.playhead == 0.0
        assert panel.playing is False
        assert panel.loop is True

    def test_default_duration(self):
        panel = _make_panel()
        # No tracks → falls back to 4 seconds.
        assert panel.duration == 4.0


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------


class TestTracks:
    def test_add_track_appends(self):
        panel = _make_panel()
        t = panel.add_track("transform.position.x")
        assert panel.tracks == [t]
        assert t.property_name == "transform.position.x"

    def test_remove_track(self):
        panel = _make_panel()
        panel.add_track("a")
        panel.add_track("b")
        panel.remove_track(0)
        assert [t.property_name for t in panel.tracks] == ["b"]

    def test_remove_track_out_of_range(self):
        panel = _make_panel()
        with pytest.raises(IndexError):
            panel.remove_track(0)

    def test_clear_tracks(self):
        panel = _make_panel()
        panel.add_track("a")
        panel.add_track("b")
        panel.clear_tracks()
        assert panel.tracks == []


# ---------------------------------------------------------------------------
# Keyframes
# ---------------------------------------------------------------------------


class TestKeyframes:
    def test_add_keyframe(self):
        panel = _make_panel()
        panel.add_track("a")
        kf = panel.add_keyframe(0, 1.0, 5.0)
        assert kf.t == 1.0
        assert kf.value == 5.0
        assert len(panel.tracks[0].keyframes) == 1

    def test_remove_keyframe(self):
        panel = _make_panel()
        panel.add_track("a")
        panel.add_keyframe(0, 0.0, 0.0)
        panel.add_keyframe(0, 1.0, 1.0)
        panel.remove_keyframe(0, 0)
        kfs = panel.tracks[0].keyframes
        assert len(kfs) == 1
        assert kfs[0].t == 1.0

    def test_move_keyframe(self):
        panel = _make_panel()
        panel.add_track("a")
        panel.add_keyframe(0, 0.0, 0.0)
        kf = panel.move_keyframe(0, 0, t=2.0, value=9.0)
        assert kf.t == 2.0
        assert kf.value == 9.0


# ---------------------------------------------------------------------------
# Seek + ruler
# ---------------------------------------------------------------------------


class TestSeekRuler:
    def test_seek_clamps(self):
        panel = _make_panel()
        panel.seek(-1.0)
        assert panel.playhead == 0.0
        panel.seek(100.0)
        assert panel.playhead == panel.duration

    def test_ruler_marks_playhead(self):
        panel = _make_panel()
        panel.seek(panel.duration / 2)
        glyphs = panel._ruler_glyphs()
        # Should include the playhead glyph.
        assert "^" in glyphs


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------


class TestTransport:
    def test_toggle_play(self):
        panel = _make_panel()
        assert panel.toggle_play() is True
        assert panel.toggle_play() is False

    def test_loop_setter(self):
        panel = _make_panel()
        panel.set_loop(False)
        assert panel.loop is False

    def test_tick_advances_playhead_when_playing(self):
        panel = _make_panel()
        panel.play()
        panel.tick(0.5)
        assert panel.playhead == 0.5

    def test_tick_idle_when_paused(self):
        panel = _make_panel()
        panel.tick(0.5)
        assert panel.playhead == 0.0

    def test_tick_loops_at_duration(self):
        panel = _make_panel()
        panel.play()
        panel.set_loop(True)
        panel.seek(panel.duration - 0.1)
        panel.tick(0.2)
        # Looped around to a small positive value.
        assert 0.0 <= panel.playhead < 0.2


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_path_requires_binding(self):
        panel = _make_panel()
        assert panel.save_path() is None

    def test_save_writes_yaml(self, tmp_path):
        captured: list = []
        panel = _make_panel(on_save=captured.append)
        panel.bind_entity("hero", tmp_path)
        panel.add_track("position.x")
        panel.add_keyframe(0, 0.0, 0.0)
        panel.add_keyframe(0, 1.0, 2.0)
        path = panel.save()
        assert path is not None
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "entity: hero" in text
        assert "position.x" in text
        assert captured == [path]


# ---------------------------------------------------------------------------
# Curve preview
# ---------------------------------------------------------------------------


class TestCurvePreview:
    def test_preview_returns_samples_length(self):
        panel = _make_panel()
        panel.add_track("a")
        panel.add_keyframe(0, 0.0, 0.0)
        panel.add_keyframe(0, 1.0, 1.0)
        samples = panel.curve_preview(0, samples=32)
        assert len(samples) == 32
        assert abs(samples[0]) < 1e-6
        assert abs(samples[-1] - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Bind entity
# ---------------------------------------------------------------------------


class TestBindEntity:
    def test_bind_entity_sets_fields(self, tmp_path):
        panel = _make_panel()
        panel.bind_entity("hero", tmp_path)
        assert panel.selected_entity == "hero"
        assert panel.save_path() == tmp_path / "hero.anim.yaml"


# ---------------------------------------------------------------------------
# Theme integration
# ---------------------------------------------------------------------------


class TestThemeIntegration:
    def test_theme_switch_logs(self):
        from pharos_engine.ui.widgets.notebook_theme import (
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
        panel = _make_panel()
        panel.add_track("a")
        panel.build(parent_tag="root")
        assert "add_text" in stub_dpg.calls
        panel.destroy()
