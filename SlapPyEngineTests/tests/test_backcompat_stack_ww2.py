"""Regression tests for WW2's backwards-compat shim stack.

Follows up on VV2's residuals in
`docs/game_compat_2026_07_07.md` § 10.3. WW2 landed the next five
targeted shims after VV1/VV2/VV3:

1. ``components.DeformableLayerComponent._stress_strain_buf`` — lazy
   ``(H, W, 2)`` float32 buffer; ``None`` before first ``update()``,
   allocated on first ``update()`` call. Ochema's ``test_gpu_deform``
   inspects both channels post-impact.
2. ``lighting.ConeLight(volumetric=True)`` — dataclass now accepts the
   legacy ``volumetric`` kwarg so Ochema's vehicle-headlight system
   builds without raising ``TypeError``.
3. ``collision.PixelCollisionPass`` — re-export of the class living in
   ``slappyengine.collision_pixel`` so downstream
   ``from slappyengine.collision import PixelCollisionPass`` resolves.
4. ``audio.AudioManager.play_loop`` / ``stop_loop`` / ``set_loop_volume``
   / ``set_loop_pitch`` — id-tracked loop registry. Returns int; stores
   in ``_loops`` dict; per-loop volume + pitch clamped.
5. ``lighting.LightingSystem.load_profile`` — named-preset ambient
   colour + intensity apply. Built-in presets ``night_rally`` /
   ``day_rally`` / ``garage``; custom ``profiles`` dict supported;
   unknown names silently no-op.
6. ``collision.CollisionManager.on_overlap(predicate, callback)`` —
   two-arg overlap filter with reversed-order fallback so Ochema's
   combat system doesn't have to worry about broad-phase pair ordering.

If any of these regress, downstream games break. Do NOT remove without
a v1.0 deprecation cycle. (WW2)
"""
from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Item 1 — DeformableLayerComponent._stress_strain_buf lazy init
# ---------------------------------------------------------------------------

class _FakeLayer:
    def __init__(self, w: int = 16, h: int = 16):
        self._image_data = np.full((h, w, 4), 255, dtype=np.uint8)


def test_stress_strain_buf_none_before_first_update():
    from slappyengine.components import DeformableLayerComponent
    comp = DeformableLayerComponent(_FakeLayer())
    assert comp._stress_strain_buf is None


def test_stress_strain_buf_allocated_on_first_update():
    from slappyengine.components import DeformableLayerComponent
    comp = DeformableLayerComponent(_FakeLayer(w=16, h=8))
    comp.update(dt=1 / 60)
    assert comp._stress_strain_buf is not None
    assert comp._stress_strain_buf.shape == (8, 16, 2)
    assert comp._stress_strain_buf.dtype == np.float32


def test_stress_strain_buf_writes_on_plastic_impact():
    from slappyengine.components import DeformableLayerComponent
    comp = DeformableLayerComponent(_FakeLayer(w=32, h=32))
    comp.update(dt=1 / 60)  # lazy-init the buffer
    comp.apply_impact((16.0, 16.0), force=200.0, radius=8.0, mode="plastic")
    comp.update(dt=1 / 60)
    # Channel 1 = strain (permanent)
    assert comp._stress_strain_buf[16, 16, 1] > 0.0


# ---------------------------------------------------------------------------
# Item 2 — ConeLight(volumetric=...) kwarg accepted
# ---------------------------------------------------------------------------

def test_cone_light_accepts_volumetric_kwarg():
    from slappyengine.lighting import ConeLight
    cl = ConeLight(volumetric=True)
    assert cl.volumetric is True


def test_cone_light_volumetric_defaults_false():
    from slappyengine.lighting import ConeLight
    cl = ConeLight()
    assert cl.volumetric is False


# ---------------------------------------------------------------------------
# Item 3 — PixelCollisionPass re-exported from slappyengine.collision
# ---------------------------------------------------------------------------

def test_pixel_collision_pass_importable_from_collision_module():
    """Legacy path: `from slappyengine.collision import PixelCollisionPass`."""
    from slappyengine.collision import PixelCollisionPass
    from slappyengine.collision_pixel import (
        PixelCollisionPass as _Canonical,
    )
    assert PixelCollisionPass is _Canonical


# ---------------------------------------------------------------------------
# Item 4 — AudioManager.play_loop / stop_loop / set_loop_volume / pitch
# ---------------------------------------------------------------------------

def _make_headless_audio_manager():
    import slappyengine.audio as audio_mod
    am = audio_mod.AudioManager.__new__(audio_mod.AudioManager)
    am._sf = MagicMock()
    am._available = False  # skip the background thread — deterministic tests
    am._cache = {}
    am._master_volume = 1.0
    am._loops = {}
    am._loop_id_counter = 0
    import threading
    am._loop_lock = threading.Lock()
    return am


def _make_sound_handle():
    from slappyengine.audio import SoundHandle
    return SoundHandle(
        path="test.wav",
        data=np.zeros((4410, 2), dtype=np.float32),
        samplerate=44100,
    )


def test_play_loop_returns_int_id():
    am = _make_headless_audio_manager()
    loop_id = am.play_loop(_make_sound_handle(), volume=0.5)
    assert isinstance(loop_id, int)
    assert loop_id in am._loops
    assert am._loops[loop_id].volume == pytest.approx(0.5)


def test_stop_loop_drops_from_registry():
    am = _make_headless_audio_manager()
    loop_id = am.play_loop(_make_sound_handle())
    am.stop_loop(loop_id)
    assert loop_id not in am._loops


def test_set_loop_volume_clamps_to_unit_interval():
    am = _make_headless_audio_manager()
    lid = am.play_loop(_make_sound_handle())
    am.set_loop_volume(lid, 2.5)
    assert am._loops[lid].volume == pytest.approx(1.0)
    am.set_loop_volume(lid, -0.3)
    assert am._loops[lid].volume == pytest.approx(0.0)


def test_set_loop_pitch_clamps_to_valid_range():
    am = _make_headless_audio_manager()
    lid = am.play_loop(_make_sound_handle())
    am.set_loop_pitch(lid, 0.01)   # below min
    assert am._loops[lid].pitch >= 0.1
    am.set_loop_pitch(lid, 99.0)   # above max
    assert am._loops[lid].pitch <= 4.0


def test_play_loop_none_handle_still_returns_id():
    am = _make_headless_audio_manager()
    lid = am.play_loop(None, volume=1.0)
    assert isinstance(lid, int)


# ---------------------------------------------------------------------------
# Item 5 — LightingSystem.load_profile
# ---------------------------------------------------------------------------

def _make_lighting_system():
    from slappyengine.lighting import LightingSystem
    gpu = MagicMock()
    gpu.device = MagicMock()
    return LightingSystem(gpu, width=64, height=64)


def test_load_profile_night_rally_dims_ambient():
    ls = _make_lighting_system()
    ls.load_profile("night_rally")
    assert ls._ambient_intensity < 0.15


def test_load_profile_day_rally_brightens_ambient():
    ls = _make_lighting_system()
    ls.load_profile("day_rally")
    assert ls._ambient_intensity > 0.15


def test_load_profile_garage_moderate_ambient():
    ls = _make_lighting_system()
    ls.load_profile("garage")
    assert ls._ambient_intensity > 0.2


def test_load_profile_unknown_name_is_noop():
    ls = _make_lighting_system()
    before_i = ls._ambient_intensity
    ls.load_profile("nonexistent_profile_key")
    assert ls._ambient_intensity == before_i


def test_load_profile_custom_registry_overrides_builtins():
    ls = _make_lighting_system()
    custom = {"weird": {"ambient": (0.9, 0.1, 0.1), "ambient_intensity": 0.77}}
    ls.load_profile("weird", profiles=custom)
    assert ls._ambient_intensity == pytest.approx(0.77)


# ---------------------------------------------------------------------------
# Item 6 — CollisionManager.on_overlap(predicate, callback)
# ---------------------------------------------------------------------------

def test_on_overlap_fires_when_predicate_true():
    from slappyengine.collision import CollisionManager, AABBShape

    class _E:
        position = (0.0, 0.0)
        collision_shape = AABBShape(100, 100)
        tag = ""
        _scripts: list = []

    a = _E(); a.tag = "proj"
    b = _E(); b.tag = "vehicle"
    cm = CollisionManager()
    cm.register(a)
    cm.register(b)

    fired: list = []
    cm.on_overlap(
        lambda x, y: x.tag == "proj" and y.tag == "vehicle",
        lambda x, y: fired.append((x.tag, y.tag)),
    )
    cm.step()
    assert len(fired) == 1
    assert fired[0] == ("proj", "vehicle")


def test_on_overlap_predicate_false_no_fire():
    from slappyengine.collision import CollisionManager, AABBShape

    class _E:
        position = (0.0, 0.0)
        collision_shape = AABBShape(100, 100)
        tag = "X"
        _scripts: list = []

    a, b = _E(), _E()
    cm = CollisionManager()
    cm.register(a)
    cm.register(b)

    fired: list = []
    cm.on_overlap(
        lambda x, y: x.tag == "proj",  # never true
        lambda x, y: fired.append(True),
    )
    cm.step()
    assert fired == []
