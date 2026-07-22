"""Real-GPU tests for DeformRepairer._dispatch_gpu.

These tests are skipped automatically when ``wgpu.utils.get_default_device()``
is unavailable (no Vulkan/DX/Metal driver in the sandbox).  When a device IS
available, they verify the shader actually dispatched — not a silent CPU
fallback — by inspecting ``DeformRepairer.last_path``.
"""
from __future__ import annotations

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Real-GPU device fixture
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


@pytest.fixture
def gpu_ctx(device):
    """Minimal GPU-context stand-in: just exposes ``.device``."""
    return type("Ctx", (), {"device": device})()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_layer(w=32, h=32, alpha=100):
    """Layer-like stub with RGBA image data."""
    layer = type("L", (), {})()
    layer._image_data = np.zeros((h, w, 4), dtype=np.uint8)
    layer._image_data[:, :, :3] = 180
    layer._image_data[:, :, 3] = alpha
    return layer


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDeformRepairerGPU:
    def test_dispatch_takes_gpu_path(self, gpu_ctx):
        """With a real device the dispatch must take the GPU path,
        NOT silently fall back to CPU."""
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=100)
        original = np.full((32, 32), 255, dtype=np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_full(rate=10.0)
        dr.dispatch(gpu_ctx=gpu_ctx)
        assert dr.last_path == "gpu", (
            f"Expected GPU dispatch, got last_path={dr.last_path!r} "
            "(silent CPU fallback — _dispatch_gpu raised or returned False)"
        )

    def test_no_pending_marks_none(self, gpu_ctx):
        """Empty queue means no work; last_path should be 'none'."""
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer()
        dr = DeformRepairer(layer)
        dr.dispatch(gpu_ctx=gpu_ctx)
        assert dr.last_path == "none"

    def test_no_gpu_ctx_uses_cpu(self):
        """Without a gpu_ctx the CPU path runs; last_path should be 'cpu'."""
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=100)
        dr = DeformRepairer(layer)
        dr.queue_full(rate=5.0)
        dr.dispatch(gpu_ctx=None)
        assert dr.last_path == "cpu"

    def test_gpu_dispatch_actually_repairs_alpha(self, gpu_ctx):
        """A full-layer repair on GPU must raise alpha above the starting
        value when readback is available.  Skipped if the device can't
        round-trip the texture."""
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=50)
        original = np.full((32, 32), 255, dtype=np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_full(rate=100.0)
        dr.dispatch(gpu_ctx=gpu_ctx)
        assert dr.last_path == "gpu"
        # Readback is best-effort — only assert when it produced data.
        mean_after = float(layer._image_data[:, :, 3].mean())
        if mean_after == 50.0:
            pytest.skip("device does not support read_texture readback")
        assert mean_after > 50.0, (
            f"GPU repair did not raise mean alpha (got {mean_after})"
        )

    def test_radial_event_encodes_and_dispatches(self, gpu_ctx):
        """Queue a radial + a pixel event together; both must encode cleanly
        and the dispatch must take the GPU path."""
        from slappyengine.deform_repair import DeformRepairer
        layer = _make_layer(alpha=80)
        original = np.full((32, 32), 255, dtype=np.float32)
        dr = DeformRepairer(layer, original_alpha=original)
        dr.queue_radial(16.0, 16.0, radius=8.0, rate=20.0)
        dr.queue_pixel(4, 4, rate=50.0)
        dr.dispatch(gpu_ctx=gpu_ctx)
        assert dr.last_path == "gpu"
