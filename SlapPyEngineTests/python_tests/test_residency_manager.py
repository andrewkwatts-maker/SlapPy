"""Engine tests for residency/manager.py — headless (no GPU required)."""
from __future__ import annotations
import pytest
import numpy as np
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_layer(w=16, h=16):
    from pharos_engine.layer import Layer2D
    return Layer2D.blank(w, h, name="test_layer")


def _make_asset(name="TestAsset"):
    """Minimal in-memory asset with one layer, no GPU context needed."""
    from pharos_engine.asset import Asset
    a = Asset(name=name, position=(100.0, 200.0), size=(32, 32))
    a.add_layer(_make_layer())
    return a


def _manager(tmp_path):
    from pharos_engine.residency.manager import ResidencyManager
    return ResidencyManager(ctx=None, buf_mgr=None, tex_mgr=None, save_dir=tmp_path)


# ---------------------------------------------------------------------------
# CacheMode
# ---------------------------------------------------------------------------

class TestCacheMode:
    def test_import(self):
        from pharos_engine.residency.manager import CacheMode
        assert CacheMode is not None

    def test_always_cached_value(self):
        from pharos_engine.residency.manager import CacheMode
        assert CacheMode.ALWAYS_CACHED.value == "always_cached"

    def test_offscreen_serialize_value(self):
        from pharos_engine.residency.manager import CacheMode
        assert CacheMode.OFFSCREEN_SERIALIZE.value == "offscreen_serialize"

    def test_user_driven_value(self):
        from pharos_engine.residency.manager import CacheMode
        assert CacheMode.USER_DRIVEN.value == "user_driven"

    def test_three_modes_defined(self):
        from pharos_engine.residency.manager import CacheMode
        modes = list(CacheMode)
        assert len(modes) == 3


# ---------------------------------------------------------------------------
# ResidencyManager — init
# ---------------------------------------------------------------------------

class TestResidencyManagerInit:
    def test_instantiates(self, tmp_path):
        mgr = _manager(tmp_path)
        assert mgr is not None

    def test_save_dir_created(self, tmp_path):
        save = tmp_path / "residency"
        from pharos_engine.residency.manager import ResidencyManager
        ResidencyManager(save_dir=save)
        assert save.is_dir()

    def test_default_tier_is_gpu(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset()
        assert mgr.tier(asset) == "gpu"

    def test_streaming_radii_from_config(self, tmp_path):
        mgr = _manager(tmp_path)
        assert mgr.streaming_radius_gpu > 0
        assert mgr.streaming_radius_ram > mgr.streaming_radius_gpu

    def test_vram_budget_positive(self, tmp_path):
        mgr = _manager(tmp_path)
        assert mgr.vram_budget_mb > 0

    def test_tiers_dict_initially_empty(self, tmp_path):
        mgr = _manager(tmp_path)
        assert mgr._tiers == {}


# ---------------------------------------------------------------------------
# ResidencyManager — tier transitions
# ---------------------------------------------------------------------------

class TestResidencyManagerTier:
    def test_always_cached_stays_gpu(self, tmp_path):
        from pharos_engine.residency.manager import CacheMode
        mgr = _manager(tmp_path)
        asset = _make_asset()
        asset.cache_mode = CacheMode.ALWAYS_CACHED
        # Place far away from camera
        asset.position = (99999.0, 99999.0)
        mgr.update((0.0, 0.0), [asset])
        assert mgr.tier(asset) == "gpu"

    def test_user_driven_not_auto_evicted(self, tmp_path):
        from pharos_engine.residency.manager import CacheMode
        mgr = _manager(tmp_path)
        asset = _make_asset()
        asset.cache_mode = CacheMode.USER_DRIVEN
        asset.position = (99999.0, 99999.0)
        initial_tier = mgr.tier(asset)
        mgr.update((0.0, 0.0), [asset])
        # USER_DRIVEN: no automatic change
        assert mgr.tier(asset) == initial_tier

    def test_close_entity_stays_gpu(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset()
        asset.position = (10.0, 10.0)
        mgr.update((0.0, 0.0), [asset])
        assert mgr.tier(asset) == "gpu"

    def test_mid_range_entity_becomes_ram(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset()
        # Place at distance between gpu and ram radius
        mid = (mgr.streaming_radius_gpu + mgr.streaming_radius_ram) / 2.0
        asset.position = (mid, 0.0)
        mgr.update((0.0, 0.0), [asset])
        assert mgr.tier(asset) == "ram"

    def test_far_entity_becomes_disk(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset()
        far = mgr.streaming_radius_ram + 100.0
        asset.position = (far, 0.0)
        mgr.update((0.0, 0.0), [asset])
        assert mgr.tier(asset) == "disk"

    def test_disk_entity_promoted_when_close(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset()
        # First evict to disk
        far = mgr.streaming_radius_ram + 100.0
        asset.position = (far, 0.0)
        mgr.update((0.0, 0.0), [asset])
        assert mgr.tier(asset) == "disk"
        # Now move close
        asset.position = (10.0, 0.0)
        mgr.update((0.0, 0.0), [asset])
        assert mgr.tier(asset) == "gpu"

    def test_empty_entity_list_no_crash(self, tmp_path):
        mgr = _manager(tmp_path)
        mgr.update((0.0, 0.0), [])  # should not raise


# ---------------------------------------------------------------------------
# ResidencyManager — explicit evict / prefetch
# ---------------------------------------------------------------------------

class TestResidencyManagerEvict:
    def test_evict_to_ram_sets_tier(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset()
        mgr.evict_to_ram(asset)
        assert mgr.tier(asset) == "ram"

    def test_evict_to_disk_sets_tier(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset()
        mgr.evict_to_disk(asset)
        assert mgr.tier(asset) == "disk"

    def test_evict_to_disk_writes_slap_file(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset("DiskAsset")
        mgr.evict_to_disk(asset)
        slap_files = list(tmp_path.glob("*.slap"))
        assert len(slap_files) > 0

    def test_prefetch_sets_gpu_tier(self, tmp_path):
        mgr = _manager(tmp_path)
        asset = _make_asset()
        mgr.evict_to_disk(asset)
        mgr.prefetch(asset)
        assert mgr.tier(asset) == "gpu"

    def test_tier_constants(self, tmp_path):
        from pharos_engine.residency.manager import ResidencyManager
        assert ResidencyManager.TIER_GPU == "gpu"
        assert ResidencyManager.TIER_RAM == "ram"
        assert ResidencyManager.TIER_DISK == "disk"
