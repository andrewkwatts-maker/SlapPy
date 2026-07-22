"""Tests for :mod:`pharos_engine.render.deferred` — Nova3D pillar 2 (DDD4).

Covers four seams:

1. ``GBuffer`` allocates four textures (or falls back cleanly when
   wgpu isn't installed) with the correct format table.
2. ``DeferredRenderer.render(scene, target)`` runs 60 frames without
   crashing, whether or not wgpu is available.
3. Every WGSL source file parses to a non-empty string containing the
   expected entry points.
4. When ``_core.deferred_cluster`` is importable,
   ``cluster_lights(...)`` returns a table with the expected shape.
"""

from __future__ import annotations

import os
import types
from typing import Any

import pytest


# The deferred module is import-safe even without wgpu — the soft-import
# lands ``_wgpu = None`` and every entrypoint short-circuits.
from pharos_engine.render import deferred as dfr


# ---------------------------------------------------------------------------
# 1. G-buffer format table (driver-independent)
# ---------------------------------------------------------------------------

def test_gbuffer_format_table_shape():
    gb = dfr.GBuffer(width=320, height=180, device=None)
    table = gb.format_table()
    assert table == (
        ("albedo",            "rgba8unorm"),
        ("normal_roughness",  "rgba16float"),
        ("position_metallic", "rgba16float"),
        ("depth",             "depth24plus"),
    )
    # Field-tuple mirror.
    assert gb.formats == tuple(fmt for _, fmt in table)


def test_gbuffer_views_are_none_without_device():
    gb = dfr.GBuffer(width=64, height=64, device=None)
    assert gb.views() == (None, None, None, None)
    assert gb.albedo is None
    assert gb.normal_roughness is None
    assert gb.position_metallic is None
    assert gb.depth is None


def test_gbuffer_with_wgpu_creates_four_textures():
    wgpu = pytest.importorskip("wgpu")
    try:
        import wgpu.utils as wgpu_utils  # type: ignore[import-not-found]
        device = wgpu_utils.get_default_device()
    except Exception as e:  # pragma: no cover — GPU-dependent
        pytest.skip(f"wgpu device unavailable: {e!r}")

    gb = dfr.GBuffer(width=128, height=72, device=device)
    assert gb.albedo is not None
    assert gb.normal_roughness is not None
    assert gb.position_metallic is not None
    assert gb.depth is not None
    # Views should build without raising.
    a, n, p, d = gb.views()
    assert a is not None and n is not None and p is not None and d is not None


# ---------------------------------------------------------------------------
# 2. DeferredRenderer.render — 60 frames, no crashes
# ---------------------------------------------------------------------------

class _StubScene:
    """Duck-typed scene: exposes .meshes / .lights / .camera."""

    def __init__(self) -> None:
        self.meshes: list[Any] = []
        self.lights: list[Any] = []
        self.camera = types.SimpleNamespace(
            eye=(0.0, 0.0, 0.0),
            fov_y_deg=60.0,
            aspect=16.0 / 9.0,
            near=0.1,
            far=200.0,
        )


def test_deferred_renderer_render_60_frames_headless():
    r = dfr.DeferredRenderer(device=None, queue=None, resolution=(320, 180))
    scene = _StubScene()
    for _ in range(60):
        r.render(scene, target_view=None)
    assert r.frames_rendered == 60


def test_deferred_renderer_render_60_frames_with_wgpu():
    pytest.importorskip("wgpu")
    try:
        import wgpu.utils as wgpu_utils  # type: ignore[import-not-found]
        device = wgpu_utils.get_default_device()
    except Exception as e:  # pragma: no cover — GPU-dependent
        pytest.skip(f"wgpu device unavailable: {e!r}")

    r = dfr.DeferredRenderer(
        device=device,
        queue=device.queue,
        resolution=(256, 144),
    )
    scene = _StubScene()
    # Small target texture for the tonemap pass.
    target = device.create_texture(
        size=(256, 144, 1),
        format=dfr._resolve_format("rgba8unorm"),
        usage=dfr._color_target_usage(),
    ).create_view()
    for _ in range(60):
        r.render(scene, target_view=target)
    assert r.frames_rendered == 60


# ---------------------------------------------------------------------------
# 3. WGSL shader sources parse
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "name,expect_entry",
    [
        ("gbuffer_write", "fs_main"),
        ("lighting_pass", "fs_main"),
        ("tonemap",        "fs_main"),
    ],
)
def test_shader_source_loads(name: str, expect_entry: str):
    src = dfr.load_shader_source(name)
    assert isinstance(src, str)
    assert len(src) > 0
    assert "@fragment" in src
    assert expect_entry in src
    assert "vs_main" in src


def test_shader_paths_exist_on_disk():
    for path in (
        dfr.GBUFFER_WRITE_WGSL_PATH,
        dfr.LIGHTING_PASS_WGSL_PATH,
        dfr.TONEMAP_WGSL_PATH,
    ):
        assert os.path.exists(path), f"missing WGSL: {path}"


def test_unknown_shader_name_raises():
    with pytest.raises(ValueError):
        dfr.load_shader_source("does_not_exist")


# ---------------------------------------------------------------------------
# 4. Rust cluster kernel (soft-import)
# ---------------------------------------------------------------------------

def test_cluster_lights_via_core_stub_shape():
    core = pytest.importorskip("pharos_engine._core")
    if not hasattr(core, "deferred_cluster"):
        pytest.skip("_core.deferred_cluster not built (rebuild _core with 3d feature)")

    dc = core.deferred_cluster
    lights = [dc.Light(0.0, 0.0, -5.0, 0, 1.0, 1.0, 1.0, 1.0, 10.0, 1.0, 1.0, -1.0, 0.0, -1.0, 0.0)]
    camera = types.SimpleNamespace(
        eye=(0.0, 0.0, 0.0),
        fov_y_deg=60.0,
        aspect=16.0 / 9.0,
        near=0.1,
        far=200.0,
    )
    table = dc.cluster_lights(lights, camera, (1920, 1080), (16, 9, 24))
    assert table.dims == (16, 9, 24)
    assert table.total_clusters == 16 * 9 * 24 == 3456
    assert len(table.assignments) == 3456
    assert table.light_cluster_count[0] >= 1


def test_deferred_renderer_cluster_lights_fallback():
    r = dfr.DeferredRenderer(device=None, queue=None, resolution=(320, 180))
    # cluster_lights must always return *something* with a well-defined
    # cluster count so downstream consumers never need to guard for
    # None. When _core is available we get a LightClusterTable; when
    # it's missing we get a plain Python list-of-lists.
    table = r.cluster_lights([], camera=None)
    if hasattr(table, "total_clusters"):
        assert table.total_clusters == 16 * 9 * 24
    else:
        assert len(table) == 16 * 9 * 24


def test_deferred_renderer_exports_constants():
    for name in (
        "ALBEDO_FORMAT",
        "NORMAL_ROUGHNESS_FORMAT",
        "POSITION_METALLIC_FORMAT",
        "DEPTH_FORMAT",
        "HDR_FORMAT",
    ):
        assert hasattr(dfr, name)
