"""Tests for :class:`pharos_engine.ui.editor.viewport_3d_panel.Viewport3DPanel`.

The panel is the first end-to-end wgpu render surface hosted inside the
Notebook editor (CCC1). These tests exercise three seams:

1. The panel imports cleanly with no side effects.
2. ``build(mock_parent)`` under a Dear PyGui mock does not raise, and
   the panel exposes a non-empty ``last_frame`` ndarray once it returns.
3. ``render()`` produces a real (H, W, 4) uint8 image whose contents are
   not just the clear colour — the cube must actually rasterise.

Environments without wgpu skip cleanly via ``pytest.importorskip``.
"""

from __future__ import annotations

import types
from typing import Any

import numpy as np
import pytest

# Skip the module entirely when wgpu isn't installed. This is the
# canonical CI-friendly guard — every wgpu-touching test in the tree
# should follow the same pattern.
wgpu = pytest.importorskip("wgpu")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _DPGMock:
    """Minimal Dear PyGui stand-in used by ``build`` under headless test.

    Records every call so tests can introspect widget creation without a
    live DPG context. Only the methods the panel actually touches need
    to exist; every attribute falls through to a no-op stub.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._existing: set[str] = set()

    def _record(self, name: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((name, args, kwargs))
        # Track tags so does_item_exist can behave sensibly across a
        # texture-registry rebind cycle.
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self._existing.add(tag)
        return None

    def does_item_exist(self, tag: str) -> bool:
        return tag in self._existing

    def delete_item(self, tag: str) -> None:
        self._existing.discard(tag)
        self.calls.append(("delete_item", (tag,), {}))

    def add_dynamic_texture(self, w: int, h: int, data: Any, **kw: Any) -> Any:
        return self._record("add_dynamic_texture", w, h, data, **kw)

    def add_static_texture(self, w: int, h: int, data: Any, **kw: Any) -> Any:
        return self._record("add_static_texture", w, h, data, **kw)

    def add_image(self, tex: Any, **kw: Any) -> Any:
        return self._record("add_image", tex, **kw)

    def set_value(self, tag: str, value: Any) -> None:
        self.calls.append(("set_value", (tag, value), {}))

    def texture_registry(self, **kw: Any) -> "_TextureRegistryCtx":
        return _TextureRegistryCtx(self)


class _TextureRegistryCtx:
    """Context-manager stand-in for ``dpg.texture_registry(show=False)``."""

    def __init__(self, mock: _DPGMock) -> None:
        self.mock = mock

    def __enter__(self) -> "_DPGMock":
        self.mock.calls.append(("texture_registry.__enter__", (), {}))
        return self.mock

    def __exit__(self, *_: Any) -> None:
        self.mock.calls.append(("texture_registry.__exit__", (), {}))


@pytest.fixture
def dpg_mock(monkeypatch: pytest.MonkeyPatch) -> _DPGMock:
    """Install a Dear PyGui mock into ``sys.modules`` for the duration."""
    import sys

    mock = _DPGMock()
    module = types.ModuleType("dearpygui")
    submodule = types.ModuleType("dearpygui.dearpygui")
    for attr in (
        "does_item_exist",
        "delete_item",
        "add_dynamic_texture",
        "add_static_texture",
        "add_image",
        "set_value",
        "texture_registry",
    ):
        setattr(submodule, attr, getattr(mock, attr))
    module.dearpygui = submodule
    monkeypatch.setitem(sys.modules, "dearpygui", module)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", submodule)
    return mock


# ---------------------------------------------------------------------------
# Import + basic construction
# ---------------------------------------------------------------------------

def test_module_imports_cleanly() -> None:
    """The panel module must import with no side effects."""
    from pharos_engine.ui.editor import viewport_3d_panel as mod
    assert hasattr(mod, "Viewport3DPanel")
    assert callable(mod.Viewport3DPanel)


def test_default_construction_populates_frame() -> None:
    """Constructing the panel initialises a zero-filled ``last_frame``."""
    from pharos_engine.ui.editor.viewport_3d_panel import Viewport3DPanel

    p = Viewport3DPanel(width=128, height=96)
    assert p.width == 128
    assert p.height == 96
    assert isinstance(p.last_frame, np.ndarray)
    assert p.last_frame.shape == (96, 128, 4)
    assert p.last_frame.dtype == np.uint8


# ---------------------------------------------------------------------------
# build() under DPG mock
# ---------------------------------------------------------------------------

def test_build_under_dpg_mock_does_not_raise(dpg_mock: _DPGMock) -> None:
    """``build(parent_tag)`` must not raise when Dear PyGui is mocked out."""
    from pharos_engine.ui.editor.viewport_3d_panel import Viewport3DPanel

    p = Viewport3DPanel(width=192, height=128)
    p.build("mock_parent_window")

    # The panel should have attempted to register a dynamic texture.
    texture_calls = [c for c in dpg_mock.calls if c[0] == "add_dynamic_texture"]
    image_calls = [c for c in dpg_mock.calls if c[0] == "add_image"]
    assert len(texture_calls) == 1, dpg_mock.calls
    assert len(image_calls) == 1, dpg_mock.calls

    # Image parent must be the tag we passed in.
    _, _, kwargs = image_calls[0]
    assert kwargs.get("parent") == "mock_parent_window"


def test_build_populates_last_frame(dpg_mock: _DPGMock) -> None:
    """After ``build`` returns, ``last_frame`` must hold a real image."""
    from pharos_engine.ui.editor.viewport_3d_panel import Viewport3DPanel

    p = Viewport3DPanel(width=160, height=120)
    p.build("mock_parent_window")

    assert isinstance(p.last_frame, np.ndarray)
    assert p.last_frame.shape == (120, 160, 4)
    assert p.last_frame.dtype == np.uint8
    # Non-empty — either the rendered cube or the placeholder covers > 0 %.
    non_black = (p.last_frame[:, :, :3].sum(axis=2) > 0).mean()
    assert non_black > 0.0


# ---------------------------------------------------------------------------
# Render loop — the cube must show up
# ---------------------------------------------------------------------------

def test_render_returns_non_empty_image() -> None:
    """A single ``render()`` call must return a non-empty ndarray."""
    from pharos_engine.ui.editor.viewport_3d_panel import Viewport3DPanel

    p = Viewport3DPanel(width=192, height=128)
    p._init_gpu()
    frame = p.render()

    assert isinstance(frame, np.ndarray)
    assert frame.shape == (128, 192, 4)
    assert frame.dtype == np.uint8


def test_render_produces_cube_pixels() -> None:
    """When wgpu is up, the shaded cube must occupy some centre pixels.

    Skips when the panel fell into placeholder mode (headless CI without
    a GPU adapter). Otherwise asserts that pixels near the frame centre
    contain the orange cube base colour, i.e. the R channel materially
    exceeds the clear-colour red (~23).
    """
    from pharos_engine.ui.editor.viewport_3d_panel import Viewport3DPanel

    p = Viewport3DPanel(width=256, height=192)
    p._init_gpu()
    if p.backend == "placeholder":
        pytest.skip("wgpu adapter unavailable in this environment")

    frame = p.render()
    # The cube should occupy the middle third of the frame.
    h, w, _ = frame.shape
    centre = frame[h // 3: 2 * h // 3, w // 3: 2 * w // 3]
    max_r = int(centre[:, :, 0].max())
    # Clear colour is ~(23, 25, 33); cube tops render around R = 130+.
    assert max_r > 60, f"expected cube pixels in centre, got max R={max_r}"


def test_tick_advances_rotation_and_updates_frame(dpg_mock: _DPGMock) -> None:
    """``tick`` must advance the cube rotation and push a new frame to DPG."""
    from pharos_engine.ui.editor.viewport_3d_panel import Viewport3DPanel

    p = Viewport3DPanel(width=192, height=128)
    p.build("mock_parent_window")
    start_angle = p._angle

    # Reset the call log so we only count what tick() emits.
    dpg_mock.calls.clear()
    p.tick(dt=0.033)  # ~30 fps
    assert p._angle > start_angle

    # tick() should have called set_value to push the new frame.
    set_value_calls = [c for c in dpg_mock.calls if c[0] == "set_value"]
    # When wgpu is up we expect at least one set_value; when placeholder,
    # tick() short-circuits (no re-render) which is documented behaviour.
    if p.backend != "placeholder":
        assert len(set_value_calls) >= 1


# ---------------------------------------------------------------------------
# Placeholder fallback — always available
# ---------------------------------------------------------------------------

def test_placeholder_fallback_when_wgpu_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the wgpu soft-import fails, the placeholder image must fill.

    We patch ``_wgpu`` to ``None`` on the module so the ``_init_gpu`` fast
    path takes the placeholder branch even on a machine with a real GPU.
    """
    from pharos_engine.ui.editor import viewport_3d_panel as mod

    monkeypatch.setattr(mod, "_wgpu", None)
    monkeypatch.setattr(mod, "_wgpu_utils", None)

    p = mod.Viewport3DPanel(width=160, height=100)
    p._init_gpu()
    assert p.backend == "placeholder"
    assert p.last_frame.shape == (100, 160, 4)
    # Placeholder is not all-zero — it draws stripes + a marker.
    assert (p.last_frame[:, :, :3].sum(axis=2) > 0).mean() > 0.9
