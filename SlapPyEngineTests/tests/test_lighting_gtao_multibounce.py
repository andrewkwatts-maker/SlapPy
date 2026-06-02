"""Regression tests for the GTAO multibounce resolve (Jiménez 2016 §2.3).

The shader-side change (``shaders/ao_gtao.wgsl``) is mirrored by the
Python helper :func:`slappyengine.post_process.gtao.multibounce_visibility`
so the polynomial can be exercised headlessly without a wgpu adapter.

These tests lock the three invariants the spec calls out:

  1. *Structural* — multibounce visibility is never **darker** than the
     single-bounce input.  The polynomial fit could in principle overshoot
     below ``v`` on some albedo×visibility combinations, so the resolve
     wraps the result in ``max(v, …)``.  The check sweeps a dense grid
     of (visibility, albedo) pairs to detect any regression that drops
     the clamp.
  2. *Numerical at albedo = 0* — the lerp collapses to a no-op, so
     ``multibounce(v, 0) == v`` byte-for-byte.  This is the "off" identity
     and the foundation for the ``multibounce: bool`` toggle: disabling the
     feature must produce the same numerics as setting albedo to zero.
  3. *Numerical at albedo = 1, visibility = 0.5* — the Jiménez fit must
     actually **brighten** crevices on a perfect white surface; if the
     coefficients drift the brightening could collapse to zero (white
     wall stays grey).  Locking ``> 0.5`` at the canonical test point
     catches both sign flips and coefficient swaps.

A fourth test guards the ``GTAOPass.multibounce`` API surface (uniform
packing, default value, validation) so the WGSL toggle stays in sync.
"""
from __future__ import annotations

import struct

import numpy as np
import pytest

from slappyengine.post_process.gtao import (
    GTAOPass,
    multibounce_visibility,
)


# ---------------------------------------------------------------------------
# 1. Structural — multibounce ≥ single-bounce across the (v, albedo) plane.
# ---------------------------------------------------------------------------

def test_multibounce_never_darker_than_single_bounce():
    """Spec invariant: ``multibounce(v, a) >= v`` for all v, a in [0, 1].

    The polynomial fit can dip below v at low albedos / mid visibilities;
    the implementation must therefore clamp with ``max(v, ...)``.  Sweep a
    32×32 grid so a regression that drops the clamp shows up immediately
    rather than as a subtle visual artefact two bounces later.
    """
    vs = np.linspace(0.0, 1.0, 32)
    albedos = np.linspace(0.0, 1.0, 32)
    for v in vs:
        for a in albedos:
            mb = multibounce_visibility(float(v), float(a))
            assert mb >= float(v) - 1e-9, (
                f"multibounce darkened visibility at v={v:.3f}, "
                f"albedo={a:.3f}: got {mb:.6f} < v={v:.6f}"
            )
            # Polynomial may overshoot 1.0 by a fraction of a percent at the
            # high-v / high-albedo corner; the shader clamps with
            # ``clamp(..., 0.0, 1.0)`` in the resolve step.  Allow a 1%
            # headroom in the helper so the math stays faithful to the
            # paper while still flagging gross divergence.
            assert -1e-9 <= mb <= 1.01, (
                f"multibounce out of unit range at v={v}, a={a}: {mb}"
            )


# ---------------------------------------------------------------------------
# 2. Numerical — at albedo = 0 the multibounce term is a no-op.
# ---------------------------------------------------------------------------

def test_multibounce_albedo_zero_is_identity():
    """At albedo = 0 the lerp collapses to ``v`` exactly at every visibility.

    This is the foundation of the ``multibounce: bool`` toggle semantics:
    a black surface receives no indirect bounce light, so the resolve must
    match single-bounce numerics byte-for-byte.
    """
    for v in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        out = multibounce_visibility(v, 0.0)
        assert out == pytest.approx(v, abs=1e-12), (
            f"multibounce(v={v}, a=0) must equal v; got {out}"
        )


# ---------------------------------------------------------------------------
# 3. Numerical — at albedo = 1, v = 0.5 the polynomial brightens crevices.
# ---------------------------------------------------------------------------

def test_multibounce_white_albedo_brightens_mid_visibility():
    """At albedo = 1, visibility = 0.5 the result must exceed 0.5.

    Single-bounce GTAO would leave a white plaster wall sitting at 0.5
    crevice visibility; the Jiménez fit redistributes the energy from
    direct reflection back into the crease and brightens it.  Locking
    ``> 0.5`` here catches both coefficient drift and accidental sign
    flips that would collapse the multibounce term to zero.
    """
    out = multibounce_visibility(0.5, 1.0)
    assert out > 0.5, (
        f"multibounce(0.5, 1.0) must brighten above 0.5; got {out:.6f}"
    )
    # Sanity: the brightening saturates well below 1.0 — the polynomial
    # should never overshoot the unit interval.
    assert out <= 1.0 + 1e-9


# ---------------------------------------------------------------------------
# 4. GTAOPass API — multibounce default, validation, uniform packing.
# ---------------------------------------------------------------------------

def test_gtao_pass_multibounce_defaults_to_true():
    """Spec: ``multibounce: bool`` field defaults to True on GTAOPass."""
    p = GTAOPass()
    assert p.multibounce is True


def test_gtao_pass_multibounce_can_be_disabled():
    """Toggle off so existing single-bounce callers can opt out."""
    p = GTAOPass(multibounce=False)
    assert p.multibounce is False


def test_gtao_pass_rejects_non_bool_multibounce():
    """validate_bool refuses truthy non-bools at the boundary."""
    with pytest.raises(TypeError, match="multibounce"):
        GTAOPass(multibounce=1)  # type: ignore[arg-type]


def test_gtao_pass_packs_multibounce_flag_at_offset_104():
    """Uniform layout still 112 bytes; multibounce u32 at offset 104."""
    p_on  = GTAOPass(multibounce=True)
    p_off = GTAOPass(multibounce=False)
    raw_on  = p_on.make_pass(depth_tex=object(), normal_tex=object()).raw_params_bytes
    raw_off = p_off.make_pass(depth_tex=object(), normal_tex=object()).raw_params_bytes
    assert len(raw_on)  == 112
    assert len(raw_off) == 112
    flag_on  = struct.unpack_from("<I", raw_on,  104)[0]
    flag_off = struct.unpack_from("<I", raw_off, 104)[0]
    assert flag_on  == 1, f"multibounce=True must pack 1 at offset 104; got {flag_on}"
    assert flag_off == 0, f"multibounce=False must pack 0 at offset 104; got {flag_off}"


def test_gtao_pass_make_pass_accepts_albedo_tex():
    """make_pass threads the G-buffer albedo through to the resolve params."""
    p = GTAOPass()
    albedo = object()
    pp = p.make_pass(depth_tex=object(), normal_tex=object(), albedo_tex=albedo)
    assert pp.params["albedo_tex"] is albedo


def test_gtao_pass_make_pass_albedo_tex_defaults_to_none():
    """Callers without a G-buffer may omit albedo_tex (executor falls back)."""
    p = GTAOPass()
    pp = p.make_pass(depth_tex=object(), normal_tex=object())
    assert "albedo_tex" in pp.params
    assert pp.params["albedo_tex"] is None
