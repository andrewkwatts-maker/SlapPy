"""E2-G — ShaderCache compile-cache tests."""
from __future__ import annotations

import pytest

from pharos_engine.compute.shader_cache import ShaderCache


# ---------------------------------------------------------------------------
# Real-GPU fixture (skipped when wgpu device unavailable)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def device():
    try:
        import wgpu.utils
        dev = wgpu.utils.get_default_device()
    except Exception as exc:
        pytest.skip(f"wgpu device unavailable: {exc}")
    if dev is None:
        pytest.skip("wgpu.utils.get_default_device() returned None")
    return dev


# Minimal compute shaders used across tests.
SRC_A = """
@group(0) @binding(0) var<storage, read_write> buf: array<u32>;
@compute @workgroup_size(1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    buf[gid.x] = buf[gid.x] + 1u;
}
"""

SRC_B = """
@group(0) @binding(0) var<storage, read_write> buf: array<u32>;
@compute @workgroup_size(1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    buf[gid.x] = buf[gid.x] * 2u;
}
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_same_source_returns_same_module(device):
    """Identical source must return the exact same GPUShaderModule instance."""
    cache = ShaderCache()
    mod1, key1 = cache.get_or_create_module(device, SRC_A)
    mod2, key2 = cache.get_or_create_module(device, SRC_A)
    assert key1 == key2
    assert id(mod1) == id(mod2)
    assert cache.stats()["modules"] == 1


def test_different_sources_return_different_modules(device):
    """Distinct sources must produce distinct modules and distinct hash keys."""
    cache = ShaderCache()
    mod_a, key_a = cache.get_or_create_module(device, SRC_A)
    mod_b, key_b = cache.get_or_create_module(device, SRC_B)
    assert key_a != key_b
    assert id(mod_a) != id(mod_b)
    assert cache.stats()["modules"] == 2


def test_compute_pipeline_is_cached(device):
    """Second call with same (src, entry_point) returns the same pipeline."""
    cache = ShaderCache()
    p1 = cache.get_or_create_compute(device, SRC_A, entry_point="main")
    p2 = cache.get_or_create_compute(device, SRC_A, entry_point="main")
    assert id(p1) == id(p2)
    assert cache.stats() == {"modules": 1, "pipelines": 1}


def test_stats_and_clear(device):
    """stats() reflects state; clear() empties both caches."""
    cache = ShaderCache()
    assert cache.stats() == {"modules": 0, "pipelines": 0}

    cache.get_or_create_compute(device, SRC_A)
    cache.get_or_create_compute(device, SRC_B)
    s = cache.stats()
    assert s["modules"] == 2
    assert s["pipelines"] == 2

    cache.clear()
    assert cache.stats() == {"modules": 0, "pipelines": 0}
