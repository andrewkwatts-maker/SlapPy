"""Tests for the Rust ``_core.deferred_cluster`` kernel (DDD4).

* Clusters 100 lights into a 16×9×24 grid; asserts every light lands
  in at least one cluster.
* Timing sanity: 100 lights + 3,456 clusters < 10 ms on any dev box.

Skips cleanly when ``pharos_engine._core`` (or the ``deferred_cluster``
submodule) isn't built.
"""

from __future__ import annotations

import random
import time
import types

import pytest


_core = pytest.importorskip("pharos_engine._core")
if not hasattr(_core, "deferred_cluster"):
    pytest.skip(
        "_core.deferred_cluster not built (rebuild _core with the 3d feature)",
        allow_module_level=True,
    )

dc = _core.deferred_cluster


def _make_camera() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        eye=(0.0, 0.0, 0.0),
        fov_y_deg=60.0,
        aspect=16.0 / 9.0,
        near=0.1,
        far=200.0,
    )


def test_100_lights_hit_at_least_one_cluster_each():
    rng = random.Random(0xDDD4)
    lights = []
    for _ in range(100):
        # Sprinkle inside a rough frustum ahead of the camera.
        x = rng.uniform(-30.0, 30.0)
        y = rng.uniform(-15.0, 15.0)
        z = rng.uniform(-100.0, -1.0)
        rng_rad = rng.uniform(2.0, 20.0)
        lights.append(dc.Light(
            x, y, z, 0,
            1.0, 1.0, 1.0, 1.0,
            rng_rad, 1.0, 1.0, -1.0,
            0.0, -1.0, 0.0,
        ))
    table = dc.cluster_lights(lights, _make_camera(), (1920, 1080), (16, 9, 24))
    assert table.dims == (16, 9, 24)
    assert table.total_clusters == 3456
    for i, count in enumerate(table.light_cluster_count):
        assert count >= 1, f"light {i} landed in zero clusters"


def test_timing_100_lights_under_10ms():
    rng = random.Random(0x1234)
    lights = [
        dc.Light(
            rng.uniform(-30.0, 30.0),
            rng.uniform(-15.0, 15.0),
            rng.uniform(-100.0, -1.0),
            0,
            1.0, 1.0, 1.0, 1.0,
            rng.uniform(2.0, 20.0),
            1.0, 1.0, -1.0,
            0.0, -1.0, 0.0,
        )
        for _ in range(100)
    ]
    camera = _make_camera()
    # Warm up once so the timing sample isn't fighting import overhead.
    dc.cluster_lights(lights, camera, (1920, 1080), (16, 9, 24))
    start = time.perf_counter()
    dc.cluster_lights(lights, camera, (1920, 1080), (16, 9, 24))
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < 10.0, f"cluster_lights too slow: {elapsed_ms:.2f} ms"


def test_default_dims_constant_matches_16_9_24():
    assert dc.DEFAULT_DIMS == (16, 9, 24)
    assert dc.default_cluster_count() == 16 * 9 * 24 == 3456


def test_directional_light_touches_every_cluster():
    lights = [
        dc.Light(
            0.0, -1.0, 0.0, 1,
            1.0, 1.0, 1.0, 1.0,
            0.0, 1.0, 1.0, -1.0,
            0.0, -1.0, 0.0,
        ),
    ]
    table = dc.cluster_lights(lights, _make_camera(), (1920, 1080), (16, 9, 24))
    assert table.light_cluster_count[0] == 3456
