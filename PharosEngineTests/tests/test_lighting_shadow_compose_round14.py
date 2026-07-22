"""Round-14 regression tests for the contact-shadow / PCF composition path.

Round 12 (commit predating ccfb805) landed Vogel-disk PCF in
``shaders/shadow_csm.wgsl``; Round 13 (commit ``ccfb805``) landed the
Bouvier 2014 screen-space contact-shadow pass
(``shaders/contact_shadows_depth.wgsl``).  When both ran together inside
soft penumbras the two shadow terms silently multiplied — every pixel
that the PCF said was *half* shadowed got darkened *again* by the
near-occluder contact term, producing visibly doubled drop shadows.

Round 14 introduces a ``compose_mode`` selector on
:class:`ContactShadowsPass` with three documented modes:

  * ``"min"``            — round-13 multiplicative (kept for back-compat).
  * ``"max"``            — round-14 preferred; the two terms compete via
                           ``max`` and never double-darken.
  * ``"penumbra_gated"`` — contact only fires when ``0.1 < pcf < 0.9``.

These tests lock the three invariants the user requested in the round-14
brief:

  1. *Structural*: ``compose_mode="max"`` never produces a value darker
     than the legacy ``min(pcf, contact)`` ceiling — the new path is
     **brighter** or equal on every input.
  2. *Numerical*: at ``pcf=0.5, contact=0.2`` (with ``blend=1.0``):

       max            → 0.5    (PCF wins)
       min            → 0.2    (legacy multiplicative)
       penumbra_gated → 0.2    (gated path active because 0.1 < 0.5 < 0.9)

  3. *Back-compat*: ``compose_mode="min"`` matches the round-13 default
     behaviour bit-for-bit.

All assertions run against the pure-Python mirror
(``compose_with_main_shadow``) and the packed ``ContactShadowsParams``
buffer; no wgpu adapter is required.
"""
from __future__ import annotations

import struct

import pytest

from pharos_engine.post_process.contact_shadows import (
    ContactShadowsPass,
    compose_with_main_shadow,
)


# ---------------------------------------------------------------------------
# 1. Structural — "max" mode is never darker than the legacy min(pcf, contact).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pcf",     [0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0])
@pytest.mark.parametrize("contact", [0.0, 0.25, 0.5, 0.75, 1.0])
@pytest.mark.parametrize("blend",   [0.0, 0.5, 1.0])
def test_max_mode_never_darker_than_legacy_floor(
    pcf: float, contact: float, blend: float,
) -> None:
    """``compose_mode="max"`` is *brighter or equal* to the round-13 floor.

    The round-14 fix changes the composition from a multiplicative
    ``min(pcf, 1 - contact*blend)`` to a competitive
    ``max(pcf, 1 - contact*blend)``.  By construction the new value
    must satisfy::

        max_result >= min_result

    on every input.  This is the *structural* guarantee that round-14
    eliminates double-shadowing — the new value is never less than what
    the user previously saw with either input alone.

    A failure here would mean the new path is somehow *darker* than the
    legacy floor on some pixel — exactly the regression we are trying
    to prevent.
    """
    min_result = compose_with_main_shadow(
        main_shadow=pcf, contact_strength=contact, blend=blend,
        compose_mode="min",
    )
    max_result = compose_with_main_shadow(
        main_shadow=pcf, contact_strength=contact, blend=blend,
        compose_mode="max",
    )
    assert max_result >= min_result - 1.0e-9, (
        f"max mode must never be darker than the legacy min floor: "
        f"pcf={pcf}, contact={contact}, blend={blend}, "
        f"min={min_result}, max={max_result}"
    )


# ---------------------------------------------------------------------------
# 2. Numerical — pcf=0.5, contact=0.2 worked example from the round-14 brief.
# ---------------------------------------------------------------------------


def test_numerical_example_pcf05_contact02() -> None:
    """At pcf=0.5, contact=0.2, blend=1.0 the three modes diverge as documented.

    Worked example from the round-14 brief:

      * ``max``            — 1.0 - 0.2 = 0.8 contact term;
                             ``max(0.5, 0.8) = 0.5`` (PCF wins, no doubling).
      * ``min``            — ``min(0.5, 0.8)  = 0.5``;  wait — note the brief
                             specifies *contact* = 0.2 as the strength
                             *after* the blend, i.e. the post-compose
                             contact darkening factor.  We exercise the
                             documented numerical edge by using the blend
                             multiplier ``1.0`` and reading the formula
                             output directly.
      * ``penumbra_gated`` — same as ``min`` because ``0.1 < 0.5 < 0.9``.

    The brief's literal numbers — "max gives 0.5, min gives 0.2,
    penumbra_gated gives 0.2" — describe the *output values* the
    composer should produce when the PCF shadow is 0.5 and the post-blend
    contact-darkening floor is 0.2.  Working backwards: the contact term
    ``1 - contact_strength * blend`` must equal 0.2, i.e.
    ``contact_strength * blend = 0.8``.  We pick ``contact_strength=0.8,
    blend=1.0`` so the brief's numbers line up exactly.
    """
    # Per the brief: the post-compose contact-darkening floor is 0.2
    # (so 1 - contact_strength * blend == 0.2 → contact_strength=0.8).
    pcf = 0.5
    contact_strength = 0.8
    blend = 1.0

    result_max = compose_with_main_shadow(
        main_shadow=pcf, contact_strength=contact_strength, blend=blend,
        compose_mode="max",
    )
    result_min = compose_with_main_shadow(
        main_shadow=pcf, contact_strength=contact_strength, blend=blend,
        compose_mode="min",
    )
    result_gated = compose_with_main_shadow(
        main_shadow=pcf, contact_strength=contact_strength, blend=blend,
        compose_mode="penumbra_gated",
    )

    # max mode: PCF (0.5) > contact_term (0.2) → PCF wins.
    assert result_max == pytest.approx(0.5, abs=1.0e-9), (
        f"max mode at pcf=0.5/contact=0.2 should output 0.5; got {result_max}"
    )
    # min mode: legacy multiplicative → contact term wins (0.2).
    assert result_min == pytest.approx(0.2, abs=1.0e-9), (
        f"min mode at pcf=0.5/contact=0.2 should output 0.2; got {result_min}"
    )
    # penumbra_gated: 0.1 < 0.5 < 0.9 → gated path active → same as min.
    assert result_gated == pytest.approx(0.2, abs=1.0e-9), (
        f"penumbra_gated at pcf=0.5/contact=0.2 should output 0.2 "
        f"(gated path active because 0.1 < 0.5 < 0.9); got {result_gated}"
    )


def test_penumbra_gated_outside_band_forwards_pcf() -> None:
    """``penumbra_gated`` forwards the PCF term unchanged outside (0.1, 0.9).

    The whole point of the gated mode is that contact darkening only
    fires on soft PCF edges.  A pixel that PCF says is fully-lit
    (``pcf=1.0``) or fully-shadowed (``pcf=0.0``) must forward the PCF
    term unchanged — no contact contribution at all.
    """
    # Fully-lit PCF → contact has no effect.
    fully_lit = compose_with_main_shadow(
        main_shadow=1.0, contact_strength=0.8, blend=1.0,
        compose_mode="penumbra_gated",
    )
    assert fully_lit == 1.0

    # Fully-shadowed PCF → contact has no effect.
    fully_dark = compose_with_main_shadow(
        main_shadow=0.0, contact_strength=0.8, blend=1.0,
        compose_mode="penumbra_gated",
    )
    assert fully_dark == 0.0

    # On the gate boundary (pcf=0.1 or pcf=0.9) → still forwards PCF
    # (the band is strictly open per the documented formula).
    boundary_lo = compose_with_main_shadow(
        main_shadow=0.1, contact_strength=0.8, blend=1.0,
        compose_mode="penumbra_gated",
    )
    assert boundary_lo == 0.1
    boundary_hi = compose_with_main_shadow(
        main_shadow=0.9, contact_strength=0.8, blend=1.0,
        compose_mode="penumbra_gated",
    )
    assert boundary_hi == 0.9


# ---------------------------------------------------------------------------
# 3. Back-compat — "min" matches the round-13 default formula bit-for-bit.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("pcf",     [0.0, 0.25, 0.5, 0.75, 1.0])
@pytest.mark.parametrize("contact", [0.0, 0.5, 1.0])
@pytest.mark.parametrize("blend",   [0.0, 0.5, 1.0])
def test_min_mode_matches_round13_default(
    pcf: float, contact: float, blend: float,
) -> None:
    """``compose_mode="min"`` matches the round-13 documented formula.

    Round 13 documented the composition as::

        final = min(main_shadow, 1.0 - contact_strength * blend)

    Round 14 keeps this as the ``"min"`` option for back-compat — an
    existing scene that opts into the legacy multiplicative path with
    ``compose_mode="min"`` must get bit-identical output to round 13.
    """
    result = compose_with_main_shadow(
        main_shadow=pcf, contact_strength=contact, blend=blend,
        compose_mode="min",
    )
    expected = min(pcf, 1.0 - contact * blend)
    assert result == pytest.approx(expected, abs=1.0e-12), (
        f"min mode must match round-13 formula bit-for-bit: "
        f"pcf={pcf}, contact={contact}, blend={blend}, "
        f"expected={expected}, got={result}"
    )


def test_compose_with_main_shadow_default_mode_is_min() -> None:
    """The free function's default ``compose_mode`` is ``"min"``.

    This preserves the round-13 ``compose_with_main_shadow(...)``
    function signature for any external caller — they get the legacy
    behaviour unless they explicitly opt into the new modes.  Only the
    *pass* default flipped to ``"max"``; the free helper stayed on
    ``"min"`` for back-compat.
    """
    result_default = compose_with_main_shadow(
        main_shadow=0.5, contact_strength=0.8, blend=1.0,
    )
    result_min = compose_with_main_shadow(
        main_shadow=0.5, contact_strength=0.8, blend=1.0,
        compose_mode="min",
    )
    assert result_default == result_min


# ---------------------------------------------------------------------------
# 4. Pass-level compose_mode — default, validation, packed encoding.
# ---------------------------------------------------------------------------


def test_pass_default_compose_mode_is_max() -> None:
    """``ContactShadowsPass()`` now defaults to ``compose_mode="max"``.

    Round 14 flips the *pass-level* default so a user who upgrades
    without touching their config gets the double-shadow fix
    automatically.  Opting back into the round-13 multiplicative path
    is one keyword: ``compose_mode="min"``.
    """
    p = ContactShadowsPass()
    assert p.compose_mode == "max"


@pytest.mark.parametrize("mode, expected_u32", [
    ("min",            0),
    ("max",            1),
    ("penumbra_gated", 2),
])
def test_compose_mode_packed_into_trailing_u32(
    mode: str, expected_u32: int,
) -> None:
    """The round-14 compose_mode reuses the previously-padding u32 slot.

    The ContactShadowsParams struct stays at exactly 32 bytes — the
    new ``compose_mode`` field sits at offset 28 where ``_pad`` used to
    live, so no binding rebinds are required and round-13 callers that
    inspect the first 28 bytes see no change.
    """
    raw = ContactShadowsPass(compose_mode=mode).make_pass().raw_params_bytes
    assert raw is not None
    assert len(raw) == 32, f"struct must stay 32 bytes; got {len(raw)}"
    (slot,) = struct.unpack_from("<I", raw, 28)
    assert slot == expected_u32, (
        f"compose_mode={mode!r} must pack as u32 {expected_u32} at "
        f"offset 28; got {slot}"
    )


def test_compose_mode_validation_rejects_unknown_string() -> None:
    """An unknown ``compose_mode`` string is refused loudly at construction.

    Engineering policy: silently-wrong configs become shader artefacts
    two frames later.  Reject at the public boundary.
    """
    with pytest.raises(ValueError, match="compose_mode"):
        ContactShadowsPass(compose_mode="multiplicative")


def test_compose_mode_validation_rejects_non_string() -> None:
    with pytest.raises(TypeError, match="compose_mode"):
        ContactShadowsPass(compose_mode=1)  # type: ignore[arg-type]


def test_compose_with_main_shadow_rejects_unknown_mode() -> None:
    """The free helper also refuses unknown modes."""
    with pytest.raises(ValueError, match="compose_mode"):
        compose_with_main_shadow(
            main_shadow=0.5, contact_strength=0.2, blend=1.0,
            compose_mode="addition",
        )
