"""Regression tests for YY2's backwards-compat shim stack.

Follows up on WW3's fresh residuals in
`docs/game_compat_2026_07_07.md` § 11.4 after WW1/WW2 landed. YY2
closes five more items with UU/VV/WW-style targeted shims. YY1 owns
the top-ranked dict-vs-object return-shape residual in parallel;
event_bus.py is off-limits for YY2.

1. ``collision_pixel.PixelContactResult.depth`` — read-only property
   aliasing ``contact_pixels``. Ochema's
   ``tests/test_sprint5_collision.py`` (10 sites) asserts
   ``result.depth == result.contact_pixels``.
2. ``asset.Asset.cache_mode`` — default attribute set to
   ``CacheMode.OFFSCREEN_SERIALIZE`` on ``Asset.__init__``. Ochema's
   ``tests/test_asset_caching.py`` and ``scenes/race.py:111`` reach for
   this attribute directly.
3. ``components.DeformableLayerComponent.integrity_from_strain`` +
   ``_compute_integrity_from_ss`` — mean-strain → integrity mapping.
   Ochema's ``TestIntegrityFromStrain`` (6 sites) exercises the shape.
4. ``components.DeformableLayerComponent._gpu_dispatch_enabled`` +
   ``_apply_impact_cpu`` — GPU compute dispatch flag with graceful CPU
   fallback via the extracted ``_apply_impact_cpu`` helper. Ochema's
   ``TestGpuDispatchFallback`` (4 sites) drives the fallback.
5. ``components.DeformableLayerComponent.repair`` +
   ``residency.manager.ResidencyManager.update`` cache-mode honouring
   (``ALWAYS_CACHED`` pins to GPU, ``USER_DRIVEN`` skips auto-tier,
   ``OFFSCREEN_SERIALIZE`` bakes to ``{id}_damage.slap`` on eviction).
   Ochema's ``PitsSystem`` (2 repair sites) and asset-caching residency
   tests (5 sites) rely on these shims.

Bonus fix: plastic strain (channel 1 of ``_stress_strain_buf``) no
longer decays under ``spring_decay`` — only stress (channel 0) does.
Ochema's ``test_plastic_strain_persists_after_many_frames`` enforces
this invariant.

If any of these regress, downstream games break. Do NOT remove without
a v1.0 deprecation cycle. (YY2)
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Item 1 — PixelContactResult.depth aliases contact_pixels
# ---------------------------------------------------------------------------

def test_pixel_contact_result_depth_matches_contact_pixels():
    from slappyengine.collision_pixel import PixelContactResult
    r = PixelContactResult(hit=True, contact_pixels=42, normal=(1.0, 0.0))
    assert r.depth == 42
    assert r.depth == r.contact_pixels


def test_pixel_contact_result_depth_zero_on_no_contact():
    from slappyengine.collision_pixel import PixelContactResult
    r = PixelContactResult(hit=False, contact_pixels=0, normal=(0.0, 0.0))
    assert r.depth == 0


# ---------------------------------------------------------------------------
# Item 2 — Asset.cache_mode default + assignment
# ---------------------------------------------------------------------------

def test_asset_cache_mode_defaults_to_offscreen_serialize():
    from slappyengine.asset import Asset
    from slappyengine.residency.manager import CacheMode
    a = Asset(name="cache_default_test")
    assert a.cache_mode == CacheMode.OFFSCREEN_SERIALIZE


def test_asset_cache_mode_assignable():
    from slappyengine.asset import Asset
    from slappyengine.residency.manager import CacheMode
    a = Asset(name="cache_assign_test")
    a.cache_mode = CacheMode.ALWAYS_CACHED
    assert a.cache_mode == CacheMode.ALWAYS_CACHED
    a.cache_mode = CacheMode.USER_DRIVEN
    assert a.cache_mode == CacheMode.USER_DRIVEN


# ---------------------------------------------------------------------------
# Item 3 — DeformableLayerComponent.integrity_from_strain()
# ---------------------------------------------------------------------------

class _FakeLayer:
    def __init__(self, w: int = 32, h: int = 32):
        self._image_data = np.full((h, w, 4), 255, dtype=np.uint8)


def _make_deform(spring_decay: float = 0.94):
    from slappyengine.components import DeformableLayerComponent
    return DeformableLayerComponent(_FakeLayer(), spring_decay=spring_decay)


def test_integrity_from_strain_returns_one_on_undamaged_component():
    comp = _make_deform()
    comp.update(1 / 60)
    assert comp.integrity_from_strain() == pytest.approx(1.0)


def test_integrity_from_strain_scales_inversely_with_mean_strain():
    comp = _make_deform()
    comp.update(1 / 60)
    comp._stress_strain_buf[:, :, 1] = 0.4  # mean strain = 0.4
    assert comp.integrity_from_strain() == pytest.approx(0.6, abs=1e-5)


def test_integrity_from_strain_clamps_to_zero_and_one():
    comp = _make_deform()
    comp.update(1 / 60)
    comp._stress_strain_buf[:, :, 1] = 2.0
    assert comp.integrity_from_strain() == pytest.approx(0.0)
    comp._stress_strain_buf[:, :, 1] = 0.0
    assert comp.integrity_from_strain() == pytest.approx(1.0)


def test_compute_integrity_from_ss_matches_integrity_from_strain():
    comp = _make_deform()
    comp.update(1 / 60)
    comp._stress_strain_buf[:, :, 1] = 0.25
    assert comp._compute_integrity_from_ss() == pytest.approx(
        comp.integrity_from_strain(), abs=1e-7,
    )


def test_integrity_from_strain_falls_back_when_buffer_none():
    comp = _make_deform()
    # No update() → buffer stays None; method returns _integrity.
    comp._integrity = 0.77
    assert comp.integrity_from_strain() == pytest.approx(0.77)


# ---------------------------------------------------------------------------
# Item 4 — GPU dispatch flag + CPU fallback
# ---------------------------------------------------------------------------

def test_gpu_dispatch_disabled_by_default():
    comp = _make_deform()
    assert comp._gpu_dispatch_enabled is False


def test_cpu_path_populates_stress_strain_buf():
    comp = _make_deform()
    comp.apply_impact((16.0, 16.0), force=200.0, radius=8.0, mode="plastic")
    comp.update(1 / 60)
    assert comp._stress_strain_buf is not None
    assert comp._stress_strain_buf[16, 16, 1] > 0.0


def test_gpu_dispatch_falls_back_when_engine_missing():
    comp = _make_deform()
    comp._gpu_dispatch_enabled = True
    mock_entity = MagicMock()
    mock_entity.engine = None
    comp.entity = mock_entity
    comp.apply_impact((16.0, 16.0), force=200.0, radius=8.0, mode="plastic")
    comp.update(1 / 60)
    # CPU fallback ran → strain is populated
    assert comp._stress_strain_buf[16, 16, 1] > 0.0


def test_gpu_dispatch_calls_compute_when_available():
    comp = _make_deform()
    comp._gpu_dispatch_enabled = True
    mock_compute = MagicMock()
    mock_engine = MagicMock()
    mock_engine.compute = mock_compute
    mock_entity = MagicMock()
    mock_entity.engine = mock_engine
    comp.entity = mock_entity
    comp.apply_impact((16.0, 16.0), force=200.0, radius=8.0, mode="plastic")
    comp.update(1 / 60)
    mock_compute.dispatch.assert_called_once()
    call = mock_compute.dispatch.call_args
    assert call.kwargs.get("shader") == "deform_impact.wgsl"


def test_gpu_dispatch_falls_back_on_runtime_error():
    comp = _make_deform()
    comp._gpu_dispatch_enabled = True
    mock_compute = MagicMock()
    mock_compute.dispatch.side_effect = RuntimeError("simulated GPU failure")
    mock_engine = MagicMock()
    mock_engine.compute = mock_compute
    mock_entity = MagicMock()
    mock_entity.engine = mock_engine
    comp.entity = mock_entity
    comp.apply_impact((16.0, 16.0), force=200.0, radius=8.0, mode="plastic")
    comp.update(1 / 60)
    # CPU fallback ran and mirrored the impact into the strain channel
    assert comp._stress_strain_buf[16, 16, 1] > 0.0


def test_apply_impact_cpu_direct_call_writes_strain():
    comp = _make_deform()
    comp.update(1 / 60)
    impact = {"pos": (16.0, 16.0), "force": 200.0, "radius": 8.0, "mode": "plastic"}
    comp._apply_impact_cpu(impact)
    assert comp._stress_strain_buf[16, 16, 1] > 0.0


# ---------------------------------------------------------------------------
# Item 5 — repair() + ResidencyManager cache-mode honouring
# ---------------------------------------------------------------------------

def test_repair_restores_alpha_and_relieves_strain():
    comp = _make_deform()
    comp.apply_impact((16.0, 16.0), force=300.0, radius=8.0, mode="plastic")
    comp.update(1 / 60)
    damaged_integrity = comp._integrity
    strain_before = float(comp._stress_strain_buf[16, 16, 1])
    assert damaged_integrity < 1.0
    assert strain_before > 0.0
    comp.repair(rate=200.0)
    comp.update(1 / 60)
    assert comp._integrity > damaged_integrity
    strain_after = float(comp._stress_strain_buf[16, 16, 1])
    assert strain_after < strain_before


def test_plastic_strain_does_not_decay_under_spring_decay():
    """Bonus fix: only stress (channel 0) is subject to spring_decay."""
    comp = _make_deform(spring_decay=0.5)
    comp.apply_impact((16.0, 16.0), force=200.0, radius=8.0, mode="plastic")
    comp.update(1 / 60)
    strain_after_impact = float(comp._stress_strain_buf[16, 16, 1])
    assert strain_after_impact > 0.0
    for _ in range(50):
        comp.update(1 / 60)
    strain_after_decay = float(comp._stress_strain_buf[16, 16, 1])
    assert strain_after_decay == pytest.approx(strain_after_impact, abs=1e-6)


class _FakeCacheAssetLayer:
    def __init__(self):
        self.size = (4, 4)
        self.name = "layer"
        self.opacity = 1.0
        self.visible = True
        self.channel_map = {}
        self._gpu_texture = None
        self._ram_pixel_data = None
        self._image_data = None
        self._pixel_data = None
        self._data_array = None


class _FakeCacheAsset:
    """Minimal Asset-like stub for ResidencyManager tests."""

    _n = 0

    def __init__(self, cache_mode, x=0.0, y=0.0):
        _FakeCacheAsset._n += 1
        self.id = f"fake_asset_{_FakeCacheAsset._n}"
        self.name = self.id
        self.position = (x, y)
        self.size = (4, 4)
        self.z_order = 0
        self.layers = [_FakeCacheAssetLayer()]
        self.cache_mode = cache_mode
        self.bake_paths: list[str] = []

    def bake_data_layer(self, output_path=None):
        self.bake_paths.append(str(output_path) if output_path else "")


def _cache_test(monkeypatch, cache_mode, camera_pos):
    from slappyengine.residency.manager import ResidencyManager
    import slappyengine.asset as _asset_mod
    with tempfile.TemporaryDirectory() as td:
        mgr = ResidencyManager(save_dir=td)
        asset = _FakeCacheAsset(cache_mode, x=0.0, y=0.0)
        monkeypatch.setattr(_asset_mod, "Asset", _FakeCacheAsset)
        mgr._tiers[asset.id] = ResidencyManager.TIER_GPU
        mgr.update(camera_pos, [asset])
        return mgr, asset


def test_residency_always_cached_pins_to_gpu(monkeypatch):
    from slappyengine.residency.manager import CacheMode, ResidencyManager
    mgr, asset = _cache_test(monkeypatch, CacheMode.ALWAYS_CACHED, (99999.0, 99999.0))
    assert mgr.tier(asset) == ResidencyManager.TIER_GPU
    assert asset.bake_paths == []


def test_residency_user_driven_skips_auto_tier(monkeypatch):
    from slappyengine.residency.manager import CacheMode, ResidencyManager
    mgr, asset = _cache_test(monkeypatch, CacheMode.USER_DRIVEN, (99999.0, 99999.0))
    # USER_DRIVEN never demotes automatically — starts at GPU, stays at GPU.
    assert mgr.tier(asset) == ResidencyManager.TIER_GPU
    assert asset.bake_paths == []


def test_residency_offscreen_serialize_bakes_on_eviction(monkeypatch):
    from slappyengine.residency.manager import CacheMode, ResidencyManager
    mgr, asset = _cache_test(monkeypatch, CacheMode.OFFSCREEN_SERIALIZE, (99999.0, 99999.0))
    assert mgr.tier(asset) == ResidencyManager.TIER_DISK
    assert any("_damage.slap" in p for p in asset.bake_paths)
