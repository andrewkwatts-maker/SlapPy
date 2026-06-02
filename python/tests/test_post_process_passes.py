"""Tests for named PostProcessPass subclasses (ChromaticAberrationPass, etc.)."""
from __future__ import annotations
import sys
from pathlib import Path

_ENGINE = Path(__file__).parent.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import pytest
from slappyengine.post_process.chain import (
    PostProcessPass,
    PostProcessChain,
    ChromaticAberrationPass,
    VignettePass,
    FilmGrainPass,
    BloomPass,
)


class TestChromaticAberrationPass:
    def test_import(self):
        assert ChromaticAberrationPass is not None

    def test_is_post_process_pass(self):
        ca = ChromaticAberrationPass()
        assert isinstance(ca, PostProcessPass)

    def test_default_strength(self):
        ca = ChromaticAberrationPass()
        assert ca.strength == pytest.approx(0.005)

    def test_custom_strength(self):
        ca = ChromaticAberrationPass(strength=0.012)
        assert ca.strength == pytest.approx(0.012)

    def test_strength_setter_syncs_params(self):
        ca = ChromaticAberrationPass()
        ca.strength = 0.009
        assert ca.params["strength"] == pytest.approx(0.009)
        assert ca.strength == pytest.approx(0.009)

    def test_params_dict_has_center(self):
        ca = ChromaticAberrationPass(center=(0.4, 0.6))
        assert ca.params["center_x"] == pytest.approx(0.4)
        assert ca.params["center_y"] == pytest.approx(0.6)

    def test_label(self):
        ca = ChromaticAberrationPass()
        assert ca.label == "chromatic_aberration"

    def test_add_to_chain(self):
        chain = PostProcessChain()
        ca = ChromaticAberrationPass(strength=0.003)
        chain.add(ca)
        assert ca in chain.passes

    def test_animate_strength(self):
        ca = ChromaticAberrationPass(strength=0.003)
        for speed in range(0, 201, 50):
            ca.strength = 0.003 + (speed / 200) * 0.006
        assert ca.strength == pytest.approx(0.009)


class TestVignettePass:
    def test_import(self):
        assert VignettePass is not None

    def test_is_post_process_pass(self):
        v = VignettePass()
        assert isinstance(v, PostProcessPass)

    def test_default_strength(self):
        v = VignettePass()
        assert v.strength == pytest.approx(0.4)

    def test_custom_strength(self):
        v = VignettePass(strength=0.8)
        assert v.strength == pytest.approx(0.8)

    def test_strength_setter_syncs_params(self):
        v = VignettePass()
        v.strength = 0.65
        assert v.params["strength"] == pytest.approx(0.65)
        assert v.strength == pytest.approx(0.65)

    def test_label(self):
        v = VignettePass()
        assert v.label == "vignette"

    def test_add_to_chain(self):
        chain = PostProcessChain()
        v = VignettePass(strength=0.5)
        chain.add(v)
        assert v in chain.passes

    def test_ramp_from_low_to_high(self):
        v = VignettePass(strength=0.4)
        # Simulate ramp over 2 seconds at 60fps
        for _ in range(120):
            v.strength = min(0.8, v.strength + 0.4 / 120)
        assert v.strength == pytest.approx(0.8, abs=0.01)


class TestFilmGrainPass:
    def test_import(self):
        assert FilmGrainPass is not None

    def test_is_post_process_pass(self):
        fg = FilmGrainPass()
        assert isinstance(fg, PostProcessPass)

    def test_default_strength(self):
        fg = FilmGrainPass()
        assert fg.strength == pytest.approx(0.025)

    def test_custom_strength(self):
        fg = FilmGrainPass(strength=0.08)
        assert fg.strength == pytest.approx(0.08)

    def test_strength_setter_syncs_params(self):
        fg = FilmGrainPass()
        fg.strength = 0.05
        assert fg.params["strength"] == pytest.approx(0.05)

    def test_label(self):
        fg = FilmGrainPass()
        assert fg.label == "film_grain"

    def test_add_to_chain(self):
        chain = PostProcessChain()
        fg = FilmGrainPass()
        chain.add(fg)
        assert fg in chain.passes


class TestBloomPass:
    def test_import(self):
        assert BloomPass is not None

    def test_is_post_process_pass(self):
        b = BloomPass()
        assert isinstance(b, PostProcessPass)

    def test_default_intensity(self):
        b = BloomPass()
        assert b.intensity == pytest.approx(1.0)

    def test_custom_intensity(self):
        b = BloomPass(intensity=2.5)
        assert b.intensity == pytest.approx(2.5)

    def test_intensity_setter_syncs_params(self):
        b = BloomPass()
        b.intensity = 1.8
        assert b.params["intensity"] == pytest.approx(1.8)
        assert b.intensity == pytest.approx(1.8)

    def test_default_threshold(self):
        b = BloomPass()
        assert b.params["threshold"] == pytest.approx(0.7)

    def test_custom_threshold(self):
        b = BloomPass(threshold=0.5)
        assert b.params["threshold"] == pytest.approx(0.5)

    def test_label(self):
        b = BloomPass()
        assert b.label == "bloom"

    def test_add_to_chain(self):
        chain = PostProcessChain()
        b = BloomPass(intensity=1.5)
        chain.add(b)
        assert b in chain.passes


class TestPostProcessChainIntegration:
    def test_mixed_passes_in_chain(self):
        chain = PostProcessChain()
        ca = ChromaticAberrationPass(strength=0.003)
        vp = VignettePass(strength=0.4)
        fg = FilmGrainPass(strength=0.025)
        bp = BloomPass(intensity=1.2)
        for p in (ca, vp, fg, bp):
            chain.add(p)
        assert len(chain.passes) == 4

    def test_named_passes_have_distinct_labels(self):
        labels = {
            ChromaticAberrationPass().label,
            VignettePass().label,
            FilmGrainPass().label,
            BloomPass().label,
        }
        assert len(labels) == 4

    def test_strength_change_visible_in_chain(self):
        chain = PostProcessChain()
        ca = ChromaticAberrationPass(strength=0.003)
        chain.add(ca)
        ca.strength = 0.007
        found = next(p for p in chain.passes if p.label == "chromatic_aberration")
        assert found.params["strength"] == pytest.approx(0.007)

    def test_remove_named_pass_by_label(self):
        chain = PostProcessChain()
        chain.add(ChromaticAberrationPass())
        chain.add(VignettePass())
        chain.remove("chromatic_aberration")
        labels = [p.label for p in chain.passes]
        assert "chromatic_aberration" not in labels
        assert "vignette" in labels

    def test_disabled_pass_excluded_from_chain_passes(self):
        chain = PostProcessChain()
        ca = ChromaticAberrationPass()
        ca.enabled = False
        chain.add(ca)
        assert ca not in chain.passes
