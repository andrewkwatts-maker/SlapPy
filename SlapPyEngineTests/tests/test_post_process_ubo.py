"""Regression tests for the shared post-process UBO packer.

Covers three contracts:

1. **Byte-for-byte parity** with the legacy inline ``struct.pack``
   layouts for every refactored pass (BloomPass, MotionBlurPass,
   DofPass).  The executor's runtime splice helper (Sprint 2D) relies
   on those offsets being stable — any drift would silently break
   width/height patching at dispatch time.
2. **std140-style alignment** of the offset computer, including the
   notorious ``vec3`` "size 12 / alignment 16" rule.
3. **Type-checking** of ``pack_struct``: wrong-dtype values are
   rejected with a clear ``TypeError`` / ``ValueError`` so the caller
   notices the bug *at the pack site* rather than as a corrupted
   uniform on the GPU.
"""
from __future__ import annotations

import struct

import pytest

from pharos_engine.post_process._ubo import (
    UboField,
    compute_offsets,
    pack_layout_str,
    pack_struct,
)


# ---------------------------------------------------------------------------
# 1. Std140 alignment rules
# ---------------------------------------------------------------------------


def test_compute_offsets_scalars_pack_tight() -> None:
    """Four f32s should pack into 16 bytes back-to-back."""
    fields = [
        UboField("a", "f32"),
        UboField("b", "f32"),
        UboField("c", "f32"),
        UboField("d", "f32"),
    ]
    total = compute_offsets(fields)
    assert [f.offset for f in fields] == [0, 4, 8, 12]
    assert total == 16


def test_compute_offsets_vec3_aligns_to_16() -> None:
    """A vec3f after one f32 must skip to offset 16 (vec3 has align=16)."""
    fields = [
        UboField("scalar", "f32"),
        UboField("v", "vec3f"),
    ]
    total = compute_offsets(fields)
    assert fields[0].offset == 0
    # vec3 alignment is 16 — the cursor jumps from 4 → 16.
    assert fields[1].offset == 16
    # vec3 is 12 bytes wide, so cursor ends at 28; std140 round-up → 32.
    assert total == 32


def test_compute_offsets_scalar_packs_into_vec3_tail() -> None:
    """A scalar after a vec3 packs into the vec3's trailing 4-byte pad slot.

    This is the WGSL trick the executor's contact-shadow layout relies
    on — ``vec3 light_dir`` at offset 0 (size 12) followed by ``u32
    samples`` at offset 12.  No explicit pad field needed.
    """
    fields = [
        UboField("v",       "vec3f"),
        UboField("samples", "u32"),
    ]
    total = compute_offsets(fields)
    assert fields[0].offset == 0
    assert fields[1].offset == 12   # packs into the vec3 tail
    assert total == 16


def test_compute_offsets_vec2_alignment() -> None:
    """A vec2f after a single f32 should skip to offset 8."""
    fields = [
        UboField("a",  "f32"),
        UboField("v2", "vec2f"),
    ]
    total = compute_offsets(fields)
    assert fields[0].offset == 0
    assert fields[1].offset == 8
    assert total == 16


def test_compute_offsets_vec4_alignment() -> None:
    """vec4f is 16-byte aligned and 16 bytes wide."""
    fields = [
        UboField("scalar", "u32"),
        UboField("v4",     "vec4f"),
    ]
    total = compute_offsets(fields)
    assert fields[0].offset == 0
    assert fields[1].offset == 16
    assert total == 32


def test_explicit_offsets_are_honoured() -> None:
    """A pinned offset overrides the auto-cursor."""
    fields = [
        UboField("a", "f32", offset=0),
        UboField("b", "f32", offset=12),     # leaves an 8-byte gap
        UboField("c", "u32", offset=20),
    ]
    total = compute_offsets(fields)
    assert [f.offset for f in fields] == [0, 12, 20]
    assert total == 32                       # 24 → round up to 32


def test_pack_layout_str_inserts_pad_bytes() -> None:
    """``pack_layout_str`` should match a hand-written struct format string."""
    fields = [
        UboField("a", "f32"),
        UboField("v", "vec3f"),
    ]
    fmt = pack_layout_str(fields)
    # f32 at 0..4, 12 bytes of pad, vec3 at 16..28, 4 bytes trailing pad → 32.
    assert fmt == "<f12xfff4x"


# ---------------------------------------------------------------------------
# 2. Type checking
# ---------------------------------------------------------------------------


def test_pack_struct_rejects_string_for_f32() -> None:
    fields = [UboField("threshold", "f32")]
    with pytest.raises(TypeError):
        pack_struct(fields, {"threshold": "not a float"})


def test_pack_struct_rejects_negative_u32() -> None:
    fields = [UboField("n", "u32")]
    with pytest.raises(ValueError):
        pack_struct(fields, {"n": -1})


def test_pack_struct_rejects_bool_for_f32() -> None:
    """``bool`` is an ``int`` subclass — make sure it doesn't sneak in as 0.0."""
    fields = [UboField("x", "f32")]
    with pytest.raises(TypeError):
        pack_struct(fields, {"x": True})


def test_pack_struct_accepts_bool_for_u32() -> None:
    """Bool encodes a flag bit and is valid for u32."""
    fields = [UboField("flag", "u32")]
    raw = pack_struct(fields, {"flag": True})
    assert raw == struct.pack("<I12x", 1)


def test_pack_struct_rejects_nan() -> None:
    fields = [UboField("x", "f32")]
    with pytest.raises(ValueError):
        pack_struct(fields, {"x": float("nan")})


def test_pack_struct_rejects_inf() -> None:
    fields = [UboField("x", "f32")]
    with pytest.raises(ValueError):
        pack_struct(fields, {"x": float("inf")})


def test_pack_struct_missing_value_raises() -> None:
    fields = [
        UboField("a", "f32"),
        UboField("b", "f32"),
    ]
    with pytest.raises(KeyError):
        pack_struct(fields, {"a": 1.0})


def test_pack_struct_vector_wrong_length() -> None:
    fields = [UboField("v", "vec3f")]
    with pytest.raises(ValueError):
        pack_struct(fields, {"v": (1.0, 2.0)})


def test_compute_offsets_unknown_dtype_raises() -> None:
    fields = [UboField("x", "u64")]
    with pytest.raises(KeyError):
        compute_offsets(fields)


# ---------------------------------------------------------------------------
# 3. Byte-for-byte parity with legacy inline struct.pack layouts
# ---------------------------------------------------------------------------


def test_bloom_pass_parity_with_legacy_layout() -> None:
    """BloomPass.params_to_bytes must match the pre-refactor ``"<ffff"`` blob."""
    from pharos_engine.post_process.bloom import BloomPass

    bp = BloomPass(threshold=0.7, knee=0.3, intensity=1.5)
    new_bytes = bp.params_to_bytes()
    legacy_bytes = struct.pack("<ffff", 0.7, 0.3, 1.5, 0.0)
    assert new_bytes == legacy_bytes
    assert len(new_bytes) == 16


def test_bloom_pass_make_pass_raw_bytes_unchanged() -> None:
    """End-to-end: the PostProcessPass record holds the legacy bytes."""
    from pharos_engine.post_process.bloom import BloomPass

    pp = BloomPass(threshold=1.0, knee=0.2, intensity=1.0).make_pass()
    assert pp.raw_params_bytes == struct.pack("<ffff", 1.0, 0.2, 1.0, 0.0)


def test_motion_blur_pass_parity_with_legacy_layout() -> None:
    """MotionBlurPass UBO bytes must match the pre-refactor ``"<IIIfIIII"``."""
    from pharos_engine.post_process.motion_blur import MotionBlurPass

    mb = MotionBlurPass(sample_count=12, strength=1.5)
    pp = mb.make_pass(scene_tex=None, velocity_tex=None)
    legacy_bytes = struct.pack(
        "<IIIfIIII",
        0, 0, 12, 1.5, 0, 0, 0, 0,
    )
    assert pp.raw_params_bytes == legacy_bytes
    assert len(pp.raw_params_bytes) == 32


def test_motion_blur_width_height_at_offsets_0_4() -> None:
    """The runtime-splice contract: width@0, height@4 are pre-zeroed."""
    from pharos_engine.post_process.motion_blur import MotionBlurPass

    pp = MotionBlurPass().make_pass(scene_tex=None, velocity_tex=None)
    assert pp.raw_params_bytes[0:8] == struct.pack("<II", 0, 0)


def test_dof_pass_parity_with_legacy_layout() -> None:
    """DofPass UBO bytes must match the pre-refactor ``"<IIfffIII"``."""
    from pharos_engine.post_process.dof import DofPass

    dp = DofPass(
        focal_distance=0.4,
        focal_range=0.25,
        max_coc_radius=8.0,
        bokeh_samples=12,
    )
    pp = dp.make_pass(scene_tex=None, depth_tex=None)
    legacy_bytes = struct.pack(
        "<IIfffIII",
        0, 0, 0.4, 0.25, 8.0, 12, 0, 0,
    )
    assert pp.raw_params_bytes == legacy_bytes
    assert len(pp.raw_params_bytes) == 32


def test_dof_width_height_at_offsets_0_4() -> None:
    """The runtime-splice contract: DoF also has width@0, height@4."""
    from pharos_engine.post_process.dof import DofPass

    pp = DofPass().make_pass(scene_tex=None, depth_tex=None)
    assert pp.raw_params_bytes[0:8] == struct.pack("<II", 0, 0)


# ---------------------------------------------------------------------------
# 4. End-to-end: pack_struct + struct.pack produce identical blobs
# ---------------------------------------------------------------------------


def test_pack_struct_round_trips_through_pack_layout_str() -> None:
    """The fmt-string emitted by ``pack_layout_str`` reproduces the bytes."""
    fields = [
        UboField("threshold", "f32"),
        UboField("knee",      "f32"),
        UboField("intensity", "f32"),
    ]
    values = {"threshold": 0.7, "knee": 0.3, "intensity": 1.5}
    new_bytes = pack_struct(fields, values)
    fmt = pack_layout_str(fields)
    legacy = struct.pack(fmt, 0.7, 0.3, 1.5)
    assert new_bytes == legacy
