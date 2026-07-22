"""Byte-for-byte parity tests for the R-B / R-F migration of complex passes.

Covers TAAPass, GTAOPass, ContactShadowsPass, ShadowCSM, VolumetricFog,
and SSRPass (UBO packing moved into ``_SSRApply.apply``).  Each pass
must produce the same UBO bytes the pre-migration ``struct.pack`` call
produced — the Sprint 2D / Sprint 7B executor splice helper patches
dispatch-time fields by absolute byte offset, so any drift would
silently corrupt frames.

Also exercises the new :class:`PostProcessPassBase` features the
migration depends on:

* ``EXTRA_BINDINGS`` merging into the params dict
* ``DEPENDS_ON`` propagating to :class:`PostProcessPass.depends_on`
* ``BLOB_SIZE`` truncating the std140 round-up for non-16-multiple
  layouts (VolumetricFog's 132-byte struct).
"""
from __future__ import annotations

import math
import struct

import pytest

from pharos_engine.post_process.contact_shadows import ContactShadowsPass
from pharos_engine.post_process.executor import _splice_runtime_params
from pharos_engine.post_process.gtao import GTAOPass
from pharos_engine.post_process.shadow_csm import ShadowCSM, _IDENTITY_MAT4
from pharos_engine.post_process.ssr import SSRPass, _SSR_UBO_FIELDS
from pharos_engine.post_process.taa import TAAPass
from pharos_engine.post_process.volumetric_fog import VolumetricFog
from pharos_engine.post_process._ubo import pack_struct


# ---------------------------------------------------------------------------
# Legacy reference packers — frozen copies of the pre-migration
# ``struct.pack`` calls captured from ``git show <pre-commit>:taa.py`` etc.
# Any change here is a deliberate UBO layout change and MUST be paired
# with a shader-side schema bump.
# ---------------------------------------------------------------------------


def _legacy_taa_bytes(p: TAAPass) -> bytes:
    return struct.pack(
        "<ffIIIIfIfIfI",
        p.alpha,
        p.sharpening,
        0,                       # width  — executor splices these in
        0,                       # height
        1 if p.karis_weight else 0,
        1 if p.tight_variance_clip else 0,
        p.variance_clip_gamma,
        1 if p.reject_on_depth_disocclusion else 0,
        p.depth_disocclusion_threshold,
        1 if p.reject_on_normal_disocclusion else 0,
        p.normal_disocclusion_threshold,
        0,                       # _pad
    )


def _legacy_gtao_bytes(p: GTAOPass) -> bytes:
    return struct.pack(
        "<16fffIIffIIffII",
        *p.inv_proj,
        p.radius,
        p.max_pixel_radius,
        p.num_directions,
        p.num_steps,
        p.power,
        p.bias,
        0,  # width
        0,  # height
        p.depth_falloff,
        p.min_radius_scale,
        1 if p.multibounce else 0,
        0,  # _pad0
    )


_COMPOSE = {"min": 0, "max": 1, "penumbra_gated": 2}


def _legacy_contact_bytes(p: ContactShadowsPass) -> bytes:
    return struct.pack(
        "<3fIfffI",
        p.light_dir[0],
        p.light_dir[1],
        p.light_dir[2],
        int(p.samples),
        float(p.max_distance),
        float(p.thickness_threshold),
        float(p.blend),
        _COMPOSE[p.compose_mode],
    )


def _legacy_csm_bytes(p: ShadowCSM) -> bytes:
    vps = list(p.cascade_vps)
    while len(vps) < 64:
        vps.extend(_IDENTITY_MAT4)
    vps = vps[:64]
    sd = list(p.split_dists)
    while len(sd) < 4:
        sd.append(0.0)
    sd = sd[:4]
    ld = list(p.light_dir)
    while len(ld) < 3:
        ld.append(0.0)
    ld = ld[:3]
    return struct.pack(
        "<64f4f3fIffIIIffI",
        *vps,
        *sd,
        *ld,
        p.num_cascades,
        p.depth_bias,
        p.pcf_radius,
        0,
        0,
        int(p.pcss_enabled),
        p.light_size,
        p.near,
        int(p.pcf_samples),
    )


def _legacy_vfog_bytes(p: VolumetricFog) -> bytes:
    fc = list(p.fog_color)[:3]
    sd = list(p.sun_dir)[:3]
    return struct.pack(
        "<16f3ffffff3ffIIIff",
        *p.inv_proj,
        *fc,
        p.density,
        p.phase_g,
        p.fog_start,
        p.max_dist,
        p.sun_intensity,
        *sd,
        p.ambient,
        p.num_steps,
        0,
        0,
        p.time,
        0.0,
    )


def _legacy_ssr_bytes(p: SSRPass, width: int, height: int) -> bytes:
    return struct.pack(
        "<IIIffffI",
        width,
        height,
        p.max_steps,
        p.stride,
        p.thickness,
        p.strength,
        p.roughness_cutoff,
        0,
    )


# ---------------------------------------------------------------------------
# TAA — 48 bytes, runtime-splice load-bearing test
# ---------------------------------------------------------------------------


def test_taa_default_bytes_match_legacy() -> None:
    p = TAAPass()
    got = p.params_to_bytes()
    assert len(got) == 48
    assert got == _legacy_taa_bytes(p)


def test_taa_all_flags_bytes_match_legacy() -> None:
    p = TAAPass(
        alpha=0.25,
        variance_clip_gamma=1.5,
        karis_weight=True,
        tight_variance_clip=False,
        sharpening=0.7,
        reject_on_depth_disocclusion=False,
        depth_disocclusion_threshold=0.03,
        reject_on_normal_disocclusion=True,
        normal_disocclusion_threshold=0.75,
    )
    got = p.params_to_bytes()
    assert got == _legacy_taa_bytes(p)


def test_taa_splice_helper_still_patches_width_height_offsets() -> None:
    """Round 5 contract: the executor's runtime splice helper patches
    ``TaaParams.width`` and ``.height`` at offsets 8/12 of the UBO blob.

    This is the load-bearing invariant of the migration — Sprint 2D's
    splice helper relies on these byte offsets staying stable across
    the refactor.
    """
    p = TAAPass(alpha=0.1, karis_weight=True, sharpening=0.25)
    pp = p.make_pass(frame_tex="frame", history_tex="history", motion_tex="motion")

    # Width/height start at zero in the pre-packed blob.
    w0, h0 = struct.unpack_from("<II", pp.raw_params_bytes, 8)
    assert w0 == 0 and h0 == 0

    spliced = _splice_runtime_params(
        pp.shader_path, pp.raw_params_bytes, 320, 180,
    )
    assert len(spliced) == 48
    w, h = struct.unpack_from("<II", spliced, 8)
    assert w == 320 and h == 180
    # Every other slot is byte-identical to the pre-splice blob.
    assert spliced[:8] == pp.raw_params_bytes[:8]
    assert spliced[16:] == pp.raw_params_bytes[16:]


def test_taa_extra_bindings_merged_into_params() -> None:
    p = TAAPass()
    pp = p.make_pass(frame_tex="ft", history_tex="ht", motion_tex="mt")
    assert pp.params["frame_tex"] == "ft"
    assert pp.params["history_tex"] == "ht"
    assert pp.params["motion_tex"] == "mt"


# ---------------------------------------------------------------------------
# GTAO — 112 bytes, mat4 + G-buffer bindings
# ---------------------------------------------------------------------------


def test_gtao_default_bytes_match_legacy() -> None:
    p = GTAOPass()
    pp = p.make_pass(depth_tex=object(), normal_tex=object())
    assert len(pp.raw_params_bytes) == 112
    assert pp.raw_params_bytes == _legacy_gtao_bytes(p)


def test_gtao_all_knobs_bytes_match_legacy() -> None:
    p = GTAOPass(
        num_directions=12,
        num_steps=6,
        radius=3.5,
        intensity=2.0,
        bias=0.1,
        max_pixel_radius=128.0,
        depth_falloff=0.2,
        min_radius_scale=0.3,
        multibounce=False,
    )
    pp = p.make_pass(depth_tex=object(), normal_tex=object())
    assert pp.raw_params_bytes == _legacy_gtao_bytes(p)


def test_gtao_extra_bindings_include_optional_albedo() -> None:
    """``albedo_tex`` defaults to None when omitted (executor falls back
    to a neutral albedo) — but the binding slot must still be present."""
    p = GTAOPass()
    pp = p.make_pass(depth_tex="d", normal_tex="n")
    assert pp.params["depth_tex"] == "d"
    assert pp.params["normal_tex"] == "n"
    assert "albedo_tex" in pp.params
    assert pp.params["albedo_tex"] is None


def test_gtao_unknown_binding_kwarg_rejected() -> None:
    """Typos in the binding kwarg name fail at call time.

    GTAO's ``make_pass`` overrides the base class to keep the explicit
    ``depth_tex / normal_tex / albedo_tex`` signature, so Python itself
    catches the bad kwarg before the base-class allow-list ever runs.
    The contract is "loud failure at the boundary" either way.
    """
    p = GTAOPass()
    with pytest.raises(TypeError, match=r"albedo_text|unknown binding"):
        p.make_pass(depth_tex="d", normal_tex="n", albedo_text="typo")


# ---------------------------------------------------------------------------
# ContactShadows — 32 bytes, DEPENDS_ON("shadow_csm")
# ---------------------------------------------------------------------------


def test_contact_default_bytes_match_legacy() -> None:
    p = ContactShadowsPass()
    pp = p.make_pass()
    assert len(pp.raw_params_bytes) == 32
    assert pp.raw_params_bytes == _legacy_contact_bytes(p)


def test_contact_all_compose_modes_bytes_match_legacy() -> None:
    for mode in ("min", "max", "penumbra_gated"):
        p = ContactShadowsPass(
            samples=4,
            max_distance=2.0,
            thickness_threshold=0.05,
            blend=0.5,
            light_dir=(0.3, -0.8, 0.5),
            compose_mode=mode,
        )
        pp = p.make_pass()
        assert pp.raw_params_bytes == _legacy_contact_bytes(p), (
            f"compose_mode={mode!r} drifted"
        )


def test_contact_depends_on_shadow_csm() -> None:
    """ContactShadows must declare ``depends_on=['shadow_csm']`` so the
    executor schedules it after the main CSM shadow pass."""
    pp = ContactShadowsPass().make_pass()
    assert pp.depends_on == ["shadow_csm"]


# ---------------------------------------------------------------------------
# ShadowCSM — 320 bytes
# ---------------------------------------------------------------------------


def test_csm_default_bytes_match_legacy() -> None:
    p = ShadowCSM()
    pp = p.make_pass()
    assert len(pp.raw_params_bytes) == 320
    assert pp.raw_params_bytes == _legacy_csm_bytes(p)


def test_csm_custom_cascades_bytes_match_legacy() -> None:
    custom_vps = tuple(float(i) * 0.01 for i in range(64))
    p = ShadowCSM(
        num_cascades=3,
        pcss_enabled=False,
        light_size=0.1,
        near=0.05,
        depth_bias=0.001,
        pcf_radius=2.0,
        pcf_samples=32,
        split_dists=(5.0, 20.0, 60.0, 200.0),
        light_dir=(0.0, -0.866, -0.5),
        cascade_vps=custom_vps,
    )
    pp = p.make_pass()
    assert pp.raw_params_bytes == _legacy_csm_bytes(p)


# ---------------------------------------------------------------------------
# VolumetricFog — 132 bytes (NOT a multiple of 16; BLOB_SIZE truncates)
# ---------------------------------------------------------------------------


def test_vfog_default_bytes_match_legacy() -> None:
    p = VolumetricFog()
    pp = p.make_pass()
    # 132 bytes, *not* the std140 round-up to 144 — BLOB_SIZE truncates.
    assert len(pp.raw_params_bytes) == 132
    assert pp.raw_params_bytes == _legacy_vfog_bytes(p)


def test_vfog_custom_params_bytes_match_legacy() -> None:
    p = VolumetricFog(
        density=0.05,
        scatter=0.7,
        absorption=0.02,
        phase_g=0.5,
        num_steps=128,
        max_dist=1000.0,
        fog_start=2.0,
        fog_color=(0.5, 0.6, 0.7),
        sun_dir=(0.1, -0.9, 0.1),
        sun_intensity=2.5,
        ambient=0.2,
        time=12.34,
    )
    pp = p.make_pass()
    assert len(pp.raw_params_bytes) == 132
    assert pp.raw_params_bytes == _legacy_vfog_bytes(p)


# ---------------------------------------------------------------------------
# SSR — 32 bytes, packed at apply() time via the shared _ubo helper
# ---------------------------------------------------------------------------


def test_ssr_pack_bytes_match_legacy() -> None:
    """SSR doesn't expose ``make_pass``-style raw bytes (the UBO is packed
    inside ``_SSRApply.apply``); we exercise the shared layout directly.
    """
    p = SSRPass(
        max_steps=24,
        stride=2.0,
        thickness=0.4,
        strength=0.9,
        roughness_cutoff=0.5,
    )
    got = pack_struct(
        _SSR_UBO_FIELDS,
        {
            "width":            1920,
            "height":           1080,
            "max_steps":        p.max_steps,
            "stride":           p.stride,
            "thickness":        p.thickness,
            "strength":         p.strength,
            "roughness_cutoff": p.roughness_cutoff,
            "_pad":             0,
        },
    )
    assert len(got) == 32
    assert got == _legacy_ssr_bytes(p, 1920, 1080)


# ---------------------------------------------------------------------------
# Cross-cutting: the base class plumbing the migration depends on
# ---------------------------------------------------------------------------


def test_blob_size_truncates_std140_round_up_for_vfog() -> None:
    """VolumetricFog's std140-natural size is 144 (cursor=132 → 144);
    the BLOB_SIZE=132 override trims the trailing 12 pad bytes so the
    bytes are byte-identical to the legacy 132-byte payload."""
    p = VolumetricFog()
    assert p.BLOB_SIZE == 132
    raw = p.params_to_bytes()
    assert len(raw) == 132


def test_taa_blob_size_pinned_to_48() -> None:
    """TAA's BLOB_SIZE = 48 matches the round-5 UBO size exactly — any
    drift would silently break the executor's splice helper."""
    assert TAAPass.BLOB_SIZE == 48
    assert len(TAAPass().params_to_bytes()) == 48


def test_gtao_blob_size_pinned_to_112() -> None:
    assert GTAOPass.BLOB_SIZE == 112
    assert len(GTAOPass().params_to_bytes()) == 112


def test_contact_blob_size_pinned_to_32() -> None:
    assert ContactShadowsPass.BLOB_SIZE == 32
    assert len(ContactShadowsPass().params_to_bytes()) == 32


def test_csm_blob_size_pinned_to_320() -> None:
    assert ShadowCSM.BLOB_SIZE == 320
    assert len(ShadowCSM().params_to_bytes()) == 320
