"""Regression tests for :class:`PostProcessPassBase`.

Covers:

* Subclass declared without ``SHADER`` / ``label`` raises ``TypeError``
  at class-creation time (early failure beats a downstream ``NoneType``
  bug at ``make_pass()`` time).
* The base-class ``from_config`` template walks ``CONFIG_KEY``,
  graceful-falls-back to defaults on missing sections, and copies
  recognised attribute names through to the constructor.
* The base-class ``params_to_bytes`` template (driven by
  ``PARAMS_LAYOUT``) packs the per-pass UBO byte-for-byte equal to the
  pre-refactor hand-rolled ``struct.pack`` call.  This is the **Sprint
  2D layout-stability contract** — the executor's runtime splice helper
  patches dispatch-time fields by absolute offset, so any drift in the
  UBO byte layout would silently corrupt every TAA/GTAO frame.
* Subclasses that inherit ``make_pass`` from the base class produce
  the same :class:`PostProcessPass` record (label, shader path, entry
  point, params dict, raw bytes) as the legacy implementation.
"""
from __future__ import annotations

import struct
from types import SimpleNamespace

import pytest

from pharos_engine.post_process._pass_base import PostProcessPassBase
from pharos_engine.post_process.bloom import BloomPass
from pharos_engine.post_process.outline import OutlinePass
from pharos_engine.post_process.tonemap import TonemapPass


# ---------------------------------------------------------------------------
# Subclass declaration enforcement
# ---------------------------------------------------------------------------

def test_subclass_missing_shader_raises_at_class_creation() -> None:
    """A subclass that forgets ``SHADER`` cannot even be declared."""
    with pytest.raises(TypeError, match=r"SHADER"):
        class _BrokenPass(PostProcessPassBase):
            label = "broken"
            # SHADER deliberately omitted.


def test_subclass_missing_label_raises_at_class_creation() -> None:
    """A subclass that forgets ``label`` cannot even be declared."""
    with pytest.raises(TypeError, match=r"label"):
        class _BrokenPass(PostProcessPassBase):
            SHADER = "noop.wgsl"
            # label deliberately omitted (inherits the empty default).


def test_abstract_marker_skips_enforcement() -> None:
    """Intermediate abstract subclasses opt out with ``_abstract = True``."""

    class IntermediatePass(PostProcessPassBase):
        _abstract = True
        # No SHADER, no label — but ``_abstract`` exempts us.

    # The concrete subclass below must still declare both:
    class ConcretePass(IntermediatePass):
        label = "concrete"
        SHADER = "noop.wgsl"

    assert ConcretePass.SHADER == "noop.wgsl"


# ---------------------------------------------------------------------------
# ``from_config`` template
# ---------------------------------------------------------------------------

def test_from_config_walks_dotted_key_and_copies_fields() -> None:
    """Bloom's ``CONFIG_KEY = "rendering.bloom"`` should reach the section."""
    cfg = SimpleNamespace(
        rendering=SimpleNamespace(
            bloom=SimpleNamespace(threshold=2.5, knee=0.4, intensity=1.5),
        ),
    )
    bp = BloomPass.from_config(cfg)
    assert bp.threshold == pytest.approx(2.5)
    assert bp.knee == pytest.approx(0.4)
    assert bp.intensity == pytest.approx(1.5)
    # upsample_mode is non-PARAMS_LAYOUT — falls back to the constructor default.
    assert bp.upsample_mode == "tent9"


def test_from_config_missing_section_returns_defaults() -> None:
    """Missing ``cfg.rendering.bloom`` section short-circuits to ``cls()``."""
    cfg = SimpleNamespace(rendering=SimpleNamespace())
    bp = BloomPass.from_config(cfg)
    assert bp.threshold == 1.0
    assert bp.knee == pytest.approx(0.2)
    assert bp.intensity == 1.0


def test_from_config_missing_root_returns_defaults() -> None:
    """Even ``cfg`` without a ``rendering`` attribute should not crash."""
    cfg = SimpleNamespace()
    bp = BloomPass.from_config(cfg)
    assert bp.threshold == 1.0


def test_base_from_config_without_config_key_raises_not_implemented() -> None:
    """Subclasses that don't declare CONFIG_KEY can't use the template."""

    class NoConfigPass(PostProcessPassBase):
        label = "noconf"
        SHADER = "noop.wgsl"
        # CONFIG_KEY left as ``None`` (the default).

    with pytest.raises(NotImplementedError, match=r"CONFIG_KEY"):
        NoConfigPass.from_config(SimpleNamespace())


# ---------------------------------------------------------------------------
# ``params_to_bytes`` template byte-for-byte parity
# ---------------------------------------------------------------------------

def test_bloom_params_to_bytes_matches_legacy_struct_pack() -> None:
    """The base-class layout walker must pack the same bytes the legacy
    hand-rolled ``struct.pack("<ffff", t, k, i, 0.0)`` produced.

    This is the **load-bearing assertion** for the refactor: the
    executor's splice helper patches dispatch-time fields by absolute
    offset, so byte drift would silently corrupt UBO contents.
    """
    bp = BloomPass(threshold=1.5, knee=0.25, intensity=2.0)
    got = bp.params_to_bytes()
    legacy = struct.pack("<ffff", 1.5, 0.25, 2.0, 0.0)
    assert got == legacy, (
        f"BloomPass UBO drift: got {got.hex()} vs legacy {legacy.hex()}"
    )


def test_bloom_make_pass_emits_correct_record() -> None:
    """Smoke-test the inherited ``make_pass`` produces the legacy record."""
    bp = BloomPass(threshold=3.0, knee=0.0, intensity=0.5)
    rec = bp.make_pass()
    assert rec.label == "bloom"
    assert rec.shader_path == "bloom_threshold.wgsl"
    assert rec.entry_point == "main"
    # raw_params_bytes path — bytes equal the legacy layout exactly.
    assert rec.raw_params_bytes == struct.pack("<ffff", 3.0, 0.0, 0.5, 0.0)
    # params dict carries the same fields for executor sideband + diagnostics.
    assert rec.params == {"threshold": 3.0, "knee": 0.0, "intensity": 0.5}


def test_outline_make_pass_emits_correct_record() -> None:
    """OutlinePass uses the params-dict route — no raw_params_bytes."""
    op = OutlinePass(
        color=(0.5, 0.5, 0.5, 0.8),
        threshold=0.2,
        softness=0.05,
        use_sobel=True,
    )
    rec = op.make_pass()
    assert rec.label == "outline"
    assert rec.shader_path == "outline.wgsl"
    assert rec.entry_point == "main"
    assert rec.raw_params_bytes is None
    assert rec.params == {
        "outline_r": 0.5,
        "outline_g": 0.5,
        "outline_b": 0.5,
        "outline_a": 0.8,
        "threshold": 0.2,
        "softness": 0.05,
        "use_sobel": 1,
    }


def test_tonemap_make_pass_emits_correct_record() -> None:
    """TonemapPass uses the params-dict route — base-class make_pass works."""
    t = TonemapPass(
        exposure_ev=1.5,
        mode=1,
        saturation=0.8,
        contrast=1.2,
        lift=(0.1, 0.0, -0.05),
        gain=(1.0, 1.1, 1.0),
        gamma=1.0,
    )
    rec = t.make_pass()
    assert rec.label == "tonemap"
    assert rec.shader_path == "tonemap.wgsl"
    assert rec.entry_point == "tonemap_main"
    assert rec.raw_params_bytes is None
    # Every field of the original 11-key params dict, in the same order.
    assert rec.params == {
        "exposure_ev": 1.5,
        "mode": 1,
        "saturation": 0.8,
        "contrast": 1.2,
        "lift_r": 0.1,
        "lift_g": 0.0,
        "lift_b": -0.05,
        "gain_r": 1.0,
        "gain_g": 1.1,
        "gain_b": 1.0,
        "gamma": 1.0,
    }


# ---------------------------------------------------------------------------
# Default round-trip parity (defaults should match the pre-refactor record)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pass_cls,expected_shader,expected_entry,has_raw_bytes",
    [
        (BloomPass,   "bloom_threshold.wgsl", "main",          True),
        (OutlinePass, "outline.wgsl",         "main",          False),
        (TonemapPass, "tonemap.wgsl",         "tonemap_main",  False),
    ],
)
def test_default_construction_emits_expected_metadata(
    pass_cls,
    expected_shader: str,
    expected_entry: str,
    has_raw_bytes: bool,
) -> None:
    """Default-constructed passes carry the documented metadata."""
    rec = pass_cls().make_pass()
    assert rec.shader_path == expected_shader
    assert rec.entry_point == expected_entry
    assert (rec.raw_params_bytes is not None) == has_raw_bytes
