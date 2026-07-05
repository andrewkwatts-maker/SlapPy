"""
Tests for `slappyengine.audio_3d` — 3D positional audio, doppler,
and equal-power stereo panning.

These tests exercise the pure-DSP helpers (`attenuation`,
`doppler_shift`, `stereo_pan`), the dataclass surface (`AudioListener`,
`Audio3DSource`), the `SoundBank` registry, and the `Audio3DEngine`
lifecycle (play → update → stop) using a stubbed backend so no actual
audio is emitted.
"""
from __future__ import annotations

import math

import pytest

from slappyengine.audio_3d import (
    ATTENUATION_CURVES,
    SPEED_OF_SOUND,
    Audio3DEngine,
    Audio3DSource,
    AudioListener,
    SoundBank,
    attenuation,
    doppler_shift,
    stereo_pan,
)


# ---------------------------------------------------------------------------
# Dataclass defaults
# ---------------------------------------------------------------------------

def test_audio_listener_defaults():
    L = AudioListener()
    assert L.position == (0.0, 0.0, 0.0)
    assert L.forward == (0.0, 0.0, 1.0)
    assert L.up == (0.0, 1.0, 0.0)
    assert L.velocity == (0.0, 0.0, 0.0)


def test_audio_listener_custom_construction():
    L = AudioListener(
        position=(1.0, 2.0, 3.0),
        forward=(0.0, 0.0, -1.0),
        up=(0.0, 1.0, 0.0),
        velocity=(0.0, 0.0, 5.0),
    )
    assert L.position == (1.0, 2.0, 3.0)
    assert L.forward == (0.0, 0.0, -1.0)
    assert L.velocity == (0.0, 0.0, 5.0)


def test_audio_3d_source_defaults():
    S = Audio3DSource(sound_id="shoot")
    assert S.sound_id == "shoot"
    assert S.position == (0.0, 0.0, 0.0)
    assert S.velocity == (0.0, 0.0, 0.0)
    assert S.volume == pytest.approx(1.0)
    assert S.pitch == pytest.approx(1.0)
    assert S.min_distance == pytest.approx(1.0)
    assert S.max_distance == pytest.approx(20.0)
    assert S.attenuation_curve == "inverse"
    assert S.is_looping is False


def test_audio_3d_source_curve_choices_constant():
    # Ensures the module-level constant covers all three canonical curves,
    # so downstream code can rely on `in ATTENUATION_CURVES` for validation.
    assert set(ATTENUATION_CURVES) == {"linear", "inverse", "exponential"}


# ---------------------------------------------------------------------------
# attenuation()
# ---------------------------------------------------------------------------

def test_attenuation_at_zero_distance_is_full():
    for curve in ATTENUATION_CURVES:
        assert attenuation(0.0, 1.0, 20.0, curve) == pytest.approx(1.0), curve


def test_attenuation_inside_min_distance_is_full():
    # Inside the min_distance plateau, all curves clamp to 1.0.
    for curve in ATTENUATION_CURVES:
        assert attenuation(0.5, 1.0, 20.0, curve) == pytest.approx(1.0), curve


def test_attenuation_at_max_distance_is_zero():
    for curve in ATTENUATION_CURVES:
        assert attenuation(20.0, 1.0, 20.0, curve) == pytest.approx(0.0), curve


def test_attenuation_beyond_max_distance_is_zero():
    for curve in ATTENUATION_CURVES:
        assert attenuation(1000.0, 1.0, 20.0, curve) == pytest.approx(0.0), curve


def test_attenuation_linear_at_half_distance():
    # Half of the (min→max) span => exactly 0.5 for linear.
    # min=1, max=21 → distance=11 sits at midpoint.
    val = attenuation(11.0, 1.0, 21.0, "linear")
    assert val == pytest.approx(0.5, abs=1e-6)


def test_attenuation_inverse_and_linear_differ_at_half_distance():
    d, dmin, dmax = 11.0, 1.0, 21.0
    lin = attenuation(d, dmin, dmax, "linear")
    inv = attenuation(d, dmin, dmax, "inverse")
    # Inverse falloff drops off *much* faster than linear at midrange.
    assert not math.isclose(lin, inv, rel_tol=0.05), (
        f"inverse and linear should differ meaningfully at half-distance "
        f"(lin={lin}, inv={inv})"
    )
    assert inv < lin, "inverse curve should be quieter than linear at midrange"


def test_attenuation_exponential_falls_off_fastest():
    d, dmin, dmax = 5.0, 1.0, 20.0
    lin = attenuation(d, dmin, dmax, "linear")
    inv = attenuation(d, dmin, dmax, "inverse")
    exp = attenuation(d, dmin, dmax, "exponential")
    assert exp < inv < lin, f"expected exp < inv < lin (got {exp=} {inv=} {lin=})"


def test_attenuation_monotonic_decreasing():
    prev = attenuation(1.0, 1.0, 20.0, "linear")
    for d in (2.0, 5.0, 10.0, 15.0, 19.9):
        cur = attenuation(d, 1.0, 20.0, "linear")
        assert cur <= prev + 1e-9, f"linear should be monotonic (d={d})"
        prev = cur


def test_attenuation_invalid_curve_raises():
    with pytest.raises(ValueError, match="curve must be one of"):
        attenuation(5.0, 1.0, 20.0, "bogus")


def test_attenuation_invalid_min_max_raises():
    with pytest.raises(ValueError, match="max_dist must be > min_dist"):
        attenuation(5.0, 10.0, 5.0, "linear")


def test_attenuation_negative_distance_raises():
    with pytest.raises(ValueError, match="distance must be >= 0"):
        attenuation(-1.0, 1.0, 20.0, "linear")


# ---------------------------------------------------------------------------
# doppler_shift()
# ---------------------------------------------------------------------------

def test_doppler_no_motion_returns_unity():
    p = doppler_shift(
        source_vel=(0, 0, 0),
        listener_vel=(0, 0, 0),
        source_to_listener=(0, 0, 10),
    )
    assert p == pytest.approx(1.0)


def test_doppler_source_approaching_listener_raises_pitch():
    # Source at origin, listener 10m forward on +z.
    # Source moving +z at 30 m/s → moving *toward* the listener.
    s_to_l = (0.0, 0.0, 10.0)
    p = doppler_shift(
        source_vel=(0.0, 0.0, 30.0),
        listener_vel=(0.0, 0.0, 0.0),
        source_to_listener=s_to_l,
    )
    assert p > 1.0, f"approaching source should raise pitch, got {p}"


def test_doppler_source_receding_lowers_pitch():
    s_to_l = (0.0, 0.0, 10.0)
    # Source moving -z (away from listener at +z).
    p = doppler_shift(
        source_vel=(0.0, 0.0, -30.0),
        listener_vel=(0.0, 0.0, 0.0),
        source_to_listener=s_to_l,
    )
    assert p < 1.0, f"receding source should lower pitch, got {p}"


def test_doppler_listener_approaching_source_raises_pitch():
    # Listener moves *toward* source (source_to_listener points +z,
    # so "toward source" means listener velocity in -z direction).
    s_to_l = (0.0, 0.0, 10.0)
    p = doppler_shift(
        source_vel=(0.0, 0.0, 0.0),
        listener_vel=(0.0, 0.0, -30.0),
        source_to_listener=s_to_l,
    )
    assert p > 1.0, f"listener approaching source should raise pitch, got {p}"


def test_doppler_matches_classical_ratio():
    # Classical: source approaching at v, listener still →
    # f' / f = c / (c - v)
    v = 30.0
    c = SPEED_OF_SOUND
    expected = c / (c - v)
    got = doppler_shift(
        source_vel=(0.0, 0.0, v),
        listener_vel=(0.0, 0.0, 0.0),
        source_to_listener=(0.0, 0.0, 10.0),
    )
    assert got == pytest.approx(expected, rel=1e-6)


def test_doppler_perpendicular_motion_no_shift():
    # Source moving purely orthogonal to source_to_listener axis → no shift.
    p = doppler_shift(
        source_vel=(50.0, 0.0, 0.0),
        listener_vel=(0.0, 0.0, 0.0),
        source_to_listener=(0.0, 0.0, 10.0),
    )
    assert p == pytest.approx(1.0, abs=1e-6)


def test_doppler_zero_separation_returns_unity():
    # Coincident source & listener → no meaningful direction, no shift.
    p = doppler_shift(
        source_vel=(10.0, 0.0, 0.0),
        listener_vel=(0.0, 0.0, 0.0),
        source_to_listener=(0.0, 0.0, 0.0),
    )
    assert p == pytest.approx(1.0)


def test_doppler_custom_sound_speed_underwater():
    # Underwater sound speed ~1480 m/s → same velocities give a smaller shift.
    air = doppler_shift(
        source_vel=(0.0, 0.0, 30.0),
        listener_vel=(0, 0, 0),
        source_to_listener=(0, 0, 10),
        sound_speed=343.0,
    )
    water = doppler_shift(
        source_vel=(0.0, 0.0, 30.0),
        listener_vel=(0, 0, 0),
        source_to_listener=(0, 0, 10),
        sound_speed=1480.0,
    )
    assert water < air, (
        f"faster sound_speed should reduce doppler magnitude "
        f"(air={air}, water={water})"
    )
    assert water > 1.0


def test_doppler_invalid_sound_speed_raises():
    with pytest.raises(ValueError, match="sound_speed must be > 0"):
        doppler_shift((0, 0, 0), (0, 0, 0), (0, 0, 1), sound_speed=0.0)


# ---------------------------------------------------------------------------
# stereo_pan()
# ---------------------------------------------------------------------------

def test_stereo_pan_front_is_equal_gains():
    L = AudioListener(forward=(0, 0, 1), up=(0, 1, 0))
    lg, rg = stereo_pan(L, source_dir=(0, 0, 1))
    assert lg == pytest.approx(rg), f"front-of-listener should be equal (got {lg}, {rg})"


def test_stereo_pan_directly_right_is_zero_one():
    # forward=+z, up=+y → right = forward × up = (0,0,1)×(0,1,0) = (-1, 0, 0)?
    # Actually (0,0,1)×(0,1,0) = (0*0-1*1, 1*0-0*0, 0*1-0*0) = (-1, 0, 0).
    # So "directly to right" is source in -x direction.
    L = AudioListener(forward=(0, 0, 1), up=(0, 1, 0))
    lg, rg = stereo_pan(L, source_dir=(-1, 0, 0))
    assert lg == pytest.approx(0.0, abs=1e-6), f"left gain should be 0 (got {lg})"
    assert rg == pytest.approx(1.0, abs=1e-6), f"right gain should be 1 (got {rg})"


def test_stereo_pan_directly_left_is_one_zero():
    L = AudioListener(forward=(0, 0, 1), up=(0, 1, 0))
    # +x is opposite of the derived "right" vector → full left.
    lg, rg = stereo_pan(L, source_dir=(1, 0, 0))
    assert lg == pytest.approx(1.0, abs=1e-6), f"left gain should be 1 (got {lg})"
    assert rg == pytest.approx(0.0, abs=1e-6), f"right gain should be 0 (got {rg})"


def test_stereo_pan_equal_power_law():
    L = AudioListener(forward=(0, 0, 1), up=(0, 1, 0))
    # Sweep across arbitrary angles — sum of squares should stay ~= 1.
    for src in [(0, 0, 1), (1, 0, 1), (-1, 0, 1), (1, 0, 0), (-1, 0, 0), (0.5, 0, 0.5)]:
        lg, rg = stereo_pan(L, source_dir=src)
        total = lg * lg + rg * rg
        assert total == pytest.approx(1.0, abs=1e-6), (
            f"equal-power law violated for src={src}: L²+R²={total}"
        )


def test_stereo_pan_behind_listener_still_valid():
    # Behind the listener the pan magnitude collapses to center — this is
    # a known limitation of dot(right, dir) panning; make sure it doesn't
    # crash and gains sum to a valid equal-power total.
    L = AudioListener(forward=(0, 0, 1), up=(0, 1, 0))
    lg, rg = stereo_pan(L, source_dir=(0, 0, -1))
    assert 0.0 <= lg <= 1.0 and 0.0 <= rg <= 1.0
    assert (lg * lg + rg * rg) == pytest.approx(1.0, abs=1e-6)


def test_stereo_pan_zero_direction_returns_center():
    L = AudioListener()
    lg, rg = stereo_pan(L, source_dir=(0, 0, 0))
    assert lg == pytest.approx(rg)


# ---------------------------------------------------------------------------
# SoundBank
# ---------------------------------------------------------------------------

def test_soundbank_load_and_get_placeholder():
    # No real .wav on disk → placeholder handle, but registry still works.
    bank = SoundBank()
    handle = bank.load("shoot", "not_a_real_file.wav")
    assert handle is not None
    assert bank.get("shoot") is handle
    assert "shoot" in bank
    assert len(bank) == 1


def test_soundbank_list_all_sorted():
    bank = SoundBank()
    bank.register("zeta", object())
    bank.register("alpha", object())
    bank.register("mu", object())
    assert bank.list_all() == ["alpha", "mu", "zeta"]


def test_soundbank_get_missing_returns_none():
    bank = SoundBank()
    assert bank.get("nonexistent") is None


def test_soundbank_invalid_name_raises():
    bank = SoundBank()
    with pytest.raises(ValueError, match="non-empty string"):
        bank.load("", "foo.wav")
    with pytest.raises(ValueError, match="non-empty string"):
        bank.load("ok", "")


def test_soundbank_register_direct():
    bank = SoundBank()
    handle = {"stub": True}
    bank.register("boom", handle)
    assert bank.get("boom") is handle


# ---------------------------------------------------------------------------
# Audio3DEngine
# ---------------------------------------------------------------------------

def _make_engine() -> Audio3DEngine:
    listener = AudioListener()
    bank = SoundBank()
    bank.register("beep", {"stub": True})
    return Audio3DEngine(listener, bank)


def test_engine_play_returns_voice_id():
    engine = _make_engine()
    vid = engine.play(Audio3DSource(sound_id="beep", position=(5, 0, 0)))
    assert isinstance(vid, int) and vid > 0
    assert vid in engine.active_voices()


def test_engine_play_unique_voice_ids():
    engine = _make_engine()
    vids = [
        engine.play(Audio3DSource(sound_id="beep")) for _ in range(5)
    ]
    assert len(set(vids)) == 5


def test_engine_play_unknown_sound_raises():
    engine = _make_engine()
    with pytest.raises(KeyError, match="not in bank"):
        engine.play(Audio3DSource(sound_id="ghost"))


def test_engine_stop_removes_voice():
    engine = _make_engine()
    vid = engine.play(Audio3DSource(sound_id="beep"))
    engine.stop(vid)
    assert vid not in engine.active_voices()


def test_engine_stop_unknown_is_noop():
    engine = _make_engine()
    engine.stop(9999)  # must not raise


def test_engine_update_advances_voice_age():
    engine = _make_engine()
    vid = engine.play(Audio3DSource(sound_id="beep", is_looping=True))
    engine.update(0.5)
    state = engine.voice_state(vid)
    assert state is not None
    assert state["age"] == pytest.approx(0.5)


def test_engine_update_applies_attenuation_state():
    engine = _make_engine()
    # Source 100 units away with max_distance=20 → should be silenced.
    vid = engine.play(Audio3DSource(
        sound_id="beep",
        position=(100.0, 0.0, 0.0),
        min_distance=1.0,
        max_distance=20.0,
        is_looping=True,
    ))
    engine.update(0.016)
    state = engine.voice_state(vid)
    assert state["gain"] == pytest.approx(0.0)


def test_engine_update_applies_doppler_state():
    engine = _make_engine()
    vid = engine.play(Audio3DSource(
        sound_id="beep",
        position=(0.0, 0.0, -10.0),
        velocity=(0.0, 0.0, 30.0),  # toward listener at origin
        is_looping=True,
    ))
    engine.update(0.016)
    state = engine.voice_state(vid)
    assert state["pitch"] > 1.0


def test_engine_update_rejects_negative_dt():
    engine = _make_engine()
    with pytest.raises(ValueError, match="non-negative"):
        engine.update(-0.1)


def test_engine_update_rejects_nan_dt():
    engine = _make_engine()
    with pytest.raises(ValueError, match="non-negative"):
        engine.update(float("nan"))


def test_engine_set_listener_updates_pose():
    engine = _make_engine()
    new_L = AudioListener(position=(10, 0, 0))
    engine.set_listener(new_L)
    assert engine.listener.position == (10, 0, 0)


def test_engine_set_listener_type_check():
    engine = _make_engine()
    with pytest.raises(TypeError):
        engine.set_listener("not-a-listener")  # type: ignore[arg-type]


def test_engine_stop_all_clears_voices():
    engine = _make_engine()
    for _ in range(3):
        engine.play(Audio3DSource(sound_id="beep"))
    assert len(engine.active_voices()) == 3
    engine.stop_all()
    assert engine.active_voices() == []


def test_engine_non_looping_voice_expires():
    engine = _make_engine()
    vid = engine.play(Audio3DSource(sound_id="beep", is_looping=False))
    engine.update(120.0)  # well past the 60s safety cap
    assert vid not in engine.active_voices()


def test_engine_looping_voice_persists():
    engine = _make_engine()
    vid = engine.play(Audio3DSource(sound_id="beep", is_looping=True))
    engine.update(120.0)
    assert vid in engine.active_voices()


def test_engine_sound_speed_default_and_setter():
    engine = _make_engine()
    assert engine.sound_speed == pytest.approx(SPEED_OF_SOUND)
    engine.sound_speed = 1480.0
    assert engine.sound_speed == pytest.approx(1480.0)


def test_engine_sound_speed_invalid_raises():
    engine = _make_engine()
    with pytest.raises(ValueError):
        engine.sound_speed = 0.0


def test_engine_sample_rate_stored():
    listener = AudioListener()
    bank = SoundBank()
    bank.register("beep", {"stub": True})
    engine = Audio3DEngine(listener, bank, sample_rate=48000)
    assert engine.sample_rate == 48000


def test_engine_invalid_sample_rate_raises():
    listener = AudioListener()
    bank = SoundBank()
    with pytest.raises(ValueError):
        Audio3DEngine(listener, bank, sample_rate=0)


def test_engine_pan_state_reflects_side_source():
    engine = _make_engine()
    # Listener default forward=(0,0,1), so right vector = (-1, 0, 0).
    # Source in -x should hit the right ear.
    vid = engine.play(Audio3DSource(
        sound_id="beep",
        position=(-5.0, 0.0, 0.0),
        min_distance=1.0,
        max_distance=100.0,
        is_looping=True,
    ))
    engine.update(0.016)
    lg, rg = engine.voice_state(vid)["pan"]
    assert rg > lg, f"right ear should dominate for source at -x (lg={lg}, rg={rg})"
