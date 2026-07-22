"""Tests for :class:`NotebookPPPreviewPanel` — sprint EE6.

Coverage:

* Construction / defaults / property surface.
* Test image generation determinism + shape + fixed shape locations.
* Placeholder mode when no baker is bound.
* Preset dropdown loads baked chains from :class:`ChainBaker`.
* :meth:`refresh` re-runs :func:`apply_manifest` + updates processed
  image.
* Split-ratio slider clamped to ``[0, 100]``.
* Add / remove pass mutates the manifest.
* Enable / disable toggle flips :attr:`PassSpec.enabled`.
* Screenshot saves a PNG (or ``.npy`` fallback when Pillow is missing).
* ``tick`` respects the auto-refresh throttle (4 Hz).
* Build under stub DPG calls the expected widget factories.
* Registration in editor ``__all__`` + ``_LAZY_MAP``.
* MovablePanelWindow wrap helper.
"""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Very small DPG stub — mirrors the pattern used by sibling tests."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self._values: dict = {}
        self._next_id = 100

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # Containers
    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def texture_registry(self, *a, **kw):
        self._track("texture_registry", a, kw)
        return _StubCM()

    # Leaves
    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_combo(self, *a, **kw):
        self._track("add_combo", a, kw)
        tag = kw.get("tag")
        default = kw.get("default_value")
        if isinstance(tag, str) and default is not None:
            self._values[tag] = default

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_slider_int(self, *a, **kw):
        self._track("add_slider_int", a, kw)
        tag = kw.get("tag")
        default = kw.get("default_value")
        if isinstance(tag, str) and default is not None:
            self._values[tag] = default

    def add_dynamic_texture(self, *a, **kw):
        self._track("add_dynamic_texture", a, kw)

    def add_image(self, *a, **kw):
        self._track("add_image", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []

    def configure_item(self, tag, *a, **kw):
        self._track("configure_item", (tag,) + a, kw)

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)
        if isinstance(tag, str):
            self._values[tag] = value

    def get_value(self, tag, *a, **kw):
        return self._values.get(tag)


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window", "texture_registry",
        "add_text", "add_button", "add_combo", "add_checkbox",
        "add_slider_int", "add_dynamic_texture", "add_image",
        "add_separator",
        "does_item_exist", "delete_item", "get_item_children",
        "configure_item", "set_value", "get_value",
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
def clear_theme_state():
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


@pytest.fixture
def baker(tmp_path):
    """Return a :class:`ChainBaker` whose user dir is isolated per test."""
    from pharos_engine.post_process.chain_baker import ChainBaker

    b = ChainBaker(user_dir=tmp_path / "chains")
    b.bake_defaults()
    ChainBaker.register_stub_handlers()
    return b


def _make_panel(**kwargs):
    from pharos_engine.ui.editor.notebook_pp_preview import (
        NotebookPPPreviewPanel,
    )
    return NotebookPPPreviewPanel(**kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_builds_without_dpg_errors(self):
        p = _make_panel()
        assert p.TITLE == "Post-Process Preview"

    def test_defaults_expose_constants(self):
        from pharos_engine.ui.editor.notebook_pp_preview import (
            PLACEHOLDER_PRESET_NAME,
            REFRESH_INTERVAL_MS,
            SPLIT_DEFAULT,
            SPLIT_MAX,
            SPLIT_MIN,
            TEST_IMAGE_SIZE,
        )
        assert TEST_IMAGE_SIZE == 128
        assert REFRESH_INTERVAL_MS == 250
        assert SPLIT_MIN == 0
        assert SPLIT_MAX == 100
        assert SPLIT_DEFAULT == 50
        assert PLACEHOLDER_PRESET_NAME == "<no baker>"

    def test_rejects_bad_refresh_interval(self):
        with pytest.raises((TypeError, ValueError)):
            _make_panel(refresh_interval_ms=-5)

    def test_default_manifest_has_four_passes(self):
        p = _make_panel()
        names = [x.name for x in p.manifest.passes]
        assert names == ["bloom", "taa", "tonemap", "dither"]

    def test_test_image_defaults(self):
        p = _make_panel()
        img = p.get_test_image()
        assert img.shape == (128, 128, 3)
        assert img.dtype == np.float32
        assert 0.0 <= img.min() <= img.max() <= 1.0

    def test_processed_image_populated_on_init(self):
        p = _make_panel()
        proc = p.get_processed_image()
        assert proc.shape == (128, 128, 3)


# ---------------------------------------------------------------------------
# Test image
# ---------------------------------------------------------------------------


class TestTestImage:
    def test_build_test_image_deterministic(self):
        from pharos_engine.ui.editor.notebook_pp_preview import build_test_image
        a = build_test_image()
        b = build_test_image()
        assert np.allclose(a, b)

    def test_build_test_image_rejects_bad_size(self):
        from pharos_engine.ui.editor.notebook_pp_preview import build_test_image
        with pytest.raises(ValueError):
            build_test_image(0)
        with pytest.raises(ValueError):
            build_test_image(-1)

    def test_test_image_contains_red_square(self):
        from pharos_engine.ui.editor.notebook_pp_preview import build_test_image
        img = build_test_image()
        # Top-left quadrant should contain saturated red pixels.
        tl = img[:64, :64]
        red_mask = (tl[..., 0] > 0.95) & (tl[..., 1] < 0.2) & (tl[..., 2] < 0.2)
        assert red_mask.any()

    def test_test_image_contains_green_circle(self):
        from pharos_engine.ui.editor.notebook_pp_preview import build_test_image
        img = build_test_image()
        tr = img[:64, 64:]
        green_mask = (tr[..., 1] > 0.9) & (tr[..., 0] < 0.2)
        assert green_mask.any()

    def test_test_image_contains_blue_triangle(self):
        from pharos_engine.ui.editor.notebook_pp_preview import build_test_image
        img = build_test_image()
        bl = img[64:, :64]
        blue_mask = (bl[..., 2] > 0.9) & (bl[..., 0] < 0.2) & (bl[..., 1] < 0.2)
        assert blue_mask.any()


# ---------------------------------------------------------------------------
# Placeholder mode
# ---------------------------------------------------------------------------


class TestPlaceholderMode:
    def test_no_baker_marks_placeholder(self):
        p = _make_panel()
        assert p.is_placeholder_mode() is True
        assert p.presets == ["<no baker>"]

    def test_load_preset_without_baker_raises(self):
        p = _make_panel()
        with pytest.raises(RuntimeError):
            p.load_preset("default")

    def test_set_chain_baker_populates_presets(self, baker):
        p = _make_panel()
        p.set_chain_baker(baker)
        assert p.is_placeholder_mode() is False
        assert "default" in p.presets
        assert "crisp" in p.presets

    def test_set_chain_baker_none_reverts_to_placeholder(self, baker):
        p = _make_panel(baker=baker)
        assert p.is_placeholder_mode() is False
        p.set_chain_baker(None)
        assert p.is_placeholder_mode() is True


# ---------------------------------------------------------------------------
# Preset loading
# ---------------------------------------------------------------------------


class TestPresetLoading:
    def test_load_preset_returns_manifest(self, baker):
        p = _make_panel(baker=baker)
        m = p.load_preset("default")
        assert [x.name for x in m.passes] == ["bloom", "taa", "tonemap", "dither"]

    def test_load_preset_updates_active(self, baker):
        p = _make_panel(baker=baker)
        p.load_preset("crisp")
        assert p.active_preset == "crisp"

    def test_load_preset_rejects_empty(self, baker):
        p = _make_panel(baker=baker)
        with pytest.raises((ValueError, TypeError)):
            p.load_preset("")

    def test_all_baked_presets_load(self, baker):
        p = _make_panel(baker=baker)
        for name in baker.list_baked():
            m = p.load_preset(name)
            assert len(m.passes) > 0


# ---------------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_refresh_updates_processed_image(self, baker):
        p = _make_panel(baker=baker)
        p.load_preset("default")
        proc = p.refresh()
        assert proc.shape == (128, 128, 3)
        # Default chain (bloom + tonemap + taa + dither) should differ from raw.
        assert not np.allclose(proc, p.get_test_image())

    def test_refresh_clears_dirty_flag(self, baker):
        p = _make_panel(baker=baker)
        assert p.dirty is True
        p.refresh()
        assert p.dirty is False

    def test_set_test_image_marks_dirty(self):
        p = _make_panel()
        p.refresh()
        assert p.dirty is False
        new_img = np.random.default_rng(0).random((128, 128, 3), dtype=np.float32)
        p.set_test_image(new_img)
        assert p.dirty is True

    def test_set_test_image_rejects_bad_shape(self):
        p = _make_panel()
        with pytest.raises(ValueError):
            p.set_test_image(np.zeros((10, 10), dtype=np.float32))

    def test_set_test_image_rejects_non_ndarray(self):
        p = _make_panel()
        with pytest.raises(TypeError):
            p.set_test_image([1, 2, 3])

    def test_set_test_image_accepts_rgba(self):
        p = _make_panel()
        rgba = np.ones((32, 32, 4), dtype=np.float32)
        p.set_test_image(rgba)
        assert p.get_test_image().shape[-1] == 3


# ---------------------------------------------------------------------------
# Split ratio
# ---------------------------------------------------------------------------


class TestSplitRatio:
    def test_default_split_is_middle(self):
        p = _make_panel()
        assert p.split_ratio == 50

    def test_set_split_clamps_low(self):
        p = _make_panel()
        assert p.set_split_ratio(-42) == 0
        assert p.split_ratio == 0

    def test_set_split_clamps_high(self):
        p = _make_panel()
        assert p.set_split_ratio(999) == 100
        assert p.split_ratio == 100

    def test_set_split_valid_stored(self):
        p = _make_panel()
        p.set_split_ratio(37)
        assert p.split_ratio == 37

    def test_set_split_rejects_non_numeric(self):
        p = _make_panel()
        with pytest.raises(TypeError):
            p.set_split_ratio("half")


# ---------------------------------------------------------------------------
# Manifest mutation
# ---------------------------------------------------------------------------


class TestManifestMutation:
    def test_add_pass_appends(self):
        p = _make_panel()
        before = len(p.manifest.passes)
        spec = p.add_pass("tonemap")
        assert len(p.manifest.passes) == before + 1
        assert p.manifest.passes[-1] is spec

    def test_add_pass_auto_names_duplicates(self):
        p = _make_panel()
        first = p.add_pass("tonemap")
        second = p.add_pass("tonemap")
        assert first.name != second.name

    def test_add_pass_rejects_unknown_kind(self):
        p = _make_panel()
        from pharos_engine.post_process.chain_manifest import ChainManifestError
        with pytest.raises(ChainManifestError):
            p.add_pass("mystery_shader")

    def test_add_pass_rejects_empty_kind(self):
        p = _make_panel()
        with pytest.raises((ValueError, TypeError)):
            p.add_pass("")

    def test_remove_pass_by_name(self):
        p = _make_panel()
        removed = p.remove_pass("bloom")
        assert removed is True
        names = [x.name for x in p.manifest.passes]
        assert "bloom" not in names

    def test_remove_pass_missing_returns_false(self):
        p = _make_panel()
        assert p.remove_pass("does_not_exist") is False

    def test_remove_pass_strips_dependencies(self):
        p = _make_panel()
        # ``taa`` depends on ``bloom`` in DEFAULT_CHAIN.
        p.remove_pass("bloom")
        # After removal, ``taa.depends_on`` should no longer reference bloom.
        taa = next(x for x in p.manifest.passes if x.name == "taa")
        assert "bloom" not in taa.depends_on
        # Manifest must still validate.
        p.manifest.validate()

    def test_add_and_apply_manifest_still_works(self):
        p = _make_panel()
        p.add_pass("tonemap")
        result = p.refresh()
        assert result.shape == (128, 128, 3)


# ---------------------------------------------------------------------------
# Enable / disable
# ---------------------------------------------------------------------------


class TestEnableDisable:
    def test_set_pass_enabled_toggles(self):
        p = _make_panel()
        assert p.set_pass_enabled("bloom", False) is True
        bloom = next(x for x in p.manifest.passes if x.name == "bloom")
        assert bloom.enabled is False

    def test_set_pass_enabled_re_enables(self):
        p = _make_panel()
        p.set_pass_enabled("bloom", False)
        p.set_pass_enabled("bloom", True)
        bloom = next(x for x in p.manifest.passes if x.name == "bloom")
        assert bloom.enabled is True

    def test_set_pass_enabled_missing_returns_false(self):
        p = _make_panel()
        assert p.set_pass_enabled("mystery", False) is False

    def test_set_pass_enabled_rejects_non_bool(self):
        p = _make_panel()
        with pytest.raises(TypeError):
            p.set_pass_enabled("bloom", 1)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------


class TestScreenshot:
    def test_save_screenshot_writes_png(self, tmp_path):
        p = _make_panel()
        p.refresh()
        target = tmp_path / "shot.png"
        written = p.save_screenshot(target)
        assert written.exists()
        assert written.stat().st_size > 0

    def test_save_screenshot_creates_parent(self, tmp_path):
        p = _make_panel()
        target = tmp_path / "sub" / "deep" / "shot.png"
        written = p.save_screenshot(target)
        assert written.exists()

    def test_save_screenshot_returns_path(self, tmp_path):
        p = _make_panel()
        target = tmp_path / "shot.png"
        result = p.save_screenshot(target)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# Tick / throttling
# ---------------------------------------------------------------------------


class TestTick:
    def test_tick_below_interval_no_refresh(self):
        p = _make_panel(refresh_interval_ms=1000)
        p.refresh()  # clear dirty
        p.set_test_image(np.ones((32, 32, 3), dtype=np.float32))
        result = p.tick(0.1)  # 100 ms < 1000
        assert result is False

    def test_tick_above_interval_refreshes_when_dirty(self):
        p = _make_panel(refresh_interval_ms=100)
        p.refresh()
        p.set_test_image(np.ones((32, 32, 3), dtype=np.float32))
        assert p.tick(0.2) is True

    def test_tick_when_clean_returns_false(self):
        p = _make_panel(refresh_interval_ms=100)
        p.refresh()
        # No mutation -> dirty stays False.
        assert p.tick(1.0) is False

    def test_tick_rejects_bad_dt(self):
        p = _make_panel()
        with pytest.raises(TypeError):
            p.tick("many")
        with pytest.raises(ValueError):
            p.tick(-0.5)


# ---------------------------------------------------------------------------
# Build under stub DPG
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_registers_root_group(self, stub_dpg):
        p = _make_panel()
        p.build(parent_tag="root")
        assert "group" in stub_dpg.calls
        assert p._built is True

    def test_build_adds_preset_combo(self, stub_dpg, baker):
        p = _make_panel(baker=baker)
        p.build(parent_tag="root")
        combos = stub_dpg.calls.get("add_combo", [])
        # At least: preset combo + add-kind combo.
        assert len(combos) >= 2

    def test_build_adds_split_slider(self, stub_dpg):
        p = _make_panel()
        p.build(parent_tag="root")
        assert "add_slider_int" in stub_dpg.calls

    def test_build_registers_textures(self, stub_dpg):
        p = _make_panel()
        p.build(parent_tag="root")
        assert "add_dynamic_texture" in stub_dpg.calls
        # Two textures — raw + processed.
        assert len(stub_dpg.calls["add_dynamic_texture"]) >= 2

    def test_build_adds_image_widgets(self, stub_dpg):
        p = _make_panel()
        p.build(parent_tag="root")
        assert "add_image" in stub_dpg.calls
        assert len(stub_dpg.calls["add_image"]) >= 2


# ---------------------------------------------------------------------------
# MovablePanelWindow wrap
# ---------------------------------------------------------------------------


class TestWrap:
    def test_wrap_in_window_returns_wrapper(self):
        p = _make_panel()
        w = p.wrap_in_window()
        # MovablePanelWindow always has a title attr.
        assert getattr(w, "title", None) == "Post-Process Preview"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_all_lists_class(self):
        from pharos_engine.ui.editor import __all__ as editor_all
        assert "NotebookPPPreviewPanel" in editor_all

    def test_lazy_map_registers_module(self):
        from pharos_engine.ui.editor import _LAZY_MAP
        assert _LAZY_MAP["NotebookPPPreviewPanel"] == ".notebook_pp_preview"

    def test_lazy_import(self):
        import pharos_engine.ui.editor as editor_pkg
        cls = editor_pkg.NotebookPPPreviewPanel
        # Direct import path should agree.
        from pharos_engine.ui.editor.notebook_pp_preview import (
            NotebookPPPreviewPanel,
        )
        assert cls is NotebookPPPreviewPanel


# ---------------------------------------------------------------------------
# Theme integration
# ---------------------------------------------------------------------------


class TestTheme:
    def test_theme_change_appends_call_log(self):
        p = _make_panel()
        p._on_theme_changed(None)
        assert any(e[0] == "theme_changed" for e in p.call_log)

    def test_destroy_unregisters_listener(self):
        p = _make_panel()
        p.destroy()
        assert p._built is False
