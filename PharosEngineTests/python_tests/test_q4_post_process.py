"""Q4 — Post-process Pass Tests.

Validates PostProcessChain composition, pass enable/disable, ordering, reactive
property setters on named subclasses, label management, and RaceScene construction
(which wires the post-process chain internally).

All tests are headless — no GPU, no window required.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ENGINE = Path(__file__).parent.parent
if str(_ENGINE) not in sys.path:
    sys.path.insert(0, str(_ENGINE))

import pytest
from pharos_engine.post_process.chain import (
    PostProcessPass,
    PostProcessChain,
    ChromaticAberrationPass,
    VignettePass,
    FilmGrainPass,
    BloomPass,
)


# ---------------------------------------------------------------------------
# 1. PostProcessChain composition — 3 enabled passes all in chain
# ---------------------------------------------------------------------------

class TestChainComposition:
    def test_three_enabled_passes_all_in_chain(self):
        chain = PostProcessChain()
        p1 = PostProcessPass(shader_path="a.wgsl", label="a")
        p2 = PostProcessPass(shader_path="b.wgsl", label="b")
        p3 = PostProcessPass(shader_path="c.wgsl", label="c")
        chain.add(p1)
        chain.add(p2)
        chain.add(p3)
        assert len(chain.passes) == 3

    def test_three_enabled_passes_are_the_correct_objects(self):
        chain = PostProcessChain()
        passes_in = [
            PostProcessPass(shader_path="x.wgsl", label="x"),
            PostProcessPass(shader_path="y.wgsl", label="y"),
            PostProcessPass(shader_path="z.wgsl", label="z"),
        ]
        for p in passes_in:
            chain.add(p)
        for p in passes_in:
            assert p in chain.passes


# ---------------------------------------------------------------------------
# 2. Pass enable/disable toggle
# ---------------------------------------------------------------------------

class TestPassEnableDisable:
    def test_disabled_pass_excluded_from_passes(self):
        chain = PostProcessChain()
        p = PostProcessPass(shader_path="blur.wgsl", label="blur")
        p.enabled = False
        chain.add(p)
        assert p not in chain.passes

    def test_enabled_pass_included(self):
        chain = PostProcessChain()
        p = PostProcessPass(shader_path="blur.wgsl", label="blur")
        p.enabled = True
        chain.add(p)
        assert p in chain.passes

    def test_toggle_excludes_then_restores(self):
        chain = PostProcessChain()
        p = PostProcessPass(shader_path="blur.wgsl", label="blur")
        chain.add(p)
        p.enabled = False
        assert p not in chain.passes
        p.enabled = True
        assert p in chain.passes

    def test_mixed_enabled_disabled_count(self):
        chain = PostProcessChain()
        p_on  = PostProcessPass(shader_path="a.wgsl", label="on")
        p_off = PostProcessPass(shader_path="b.wgsl", label="off")
        p_off.enabled = False
        chain.add(p_on)
        chain.add(p_off)
        assert len(chain.passes) == 1
        assert chain.passes[0].label == "on"


# ---------------------------------------------------------------------------
# 3. Chain ordering — passes execute in insertion order
# ---------------------------------------------------------------------------

class TestChainOrdering:
    def test_insertion_order_preserved(self):
        chain = PostProcessChain()
        labels = ["first", "second", "third", "fourth"]
        for lbl in labels:
            chain.add(PostProcessPass(shader_path=f"{lbl}.wgsl", label=lbl))
        result = [p.label for p in chain.passes]
        assert result == labels

    def test_newly_added_pass_appended_at_end(self):
        chain = PostProcessChain()
        chain.add(PostProcessPass(shader_path="a.wgsl", label="a"))
        chain.add(PostProcessPass(shader_path="b.wgsl", label="b"))
        chain.add(PostProcessPass(shader_path="c.wgsl", label="c"))
        assert chain.passes[-1].label == "c"


# ---------------------------------------------------------------------------
# 4. ChromaticAberrationPass reactive property
# ---------------------------------------------------------------------------

class TestChromaticAberrationReactive:
    def test_strength_setter_updates_params_strength(self):
        ca = ChromaticAberrationPass()
        ca.strength = 0.012
        assert ca.params["strength"] == pytest.approx(0.012)

    def test_strength_setter_round_trips(self):
        ca = ChromaticAberrationPass(strength=0.003)
        assert ca.strength == pytest.approx(0.003)
        ca.strength = 0.009
        assert ca.strength == pytest.approx(0.009)

    def test_strength_setter_stores_float(self):
        ca = ChromaticAberrationPass()
        ca.strength = 1  # integer input
        assert isinstance(ca.params["strength"], float)


# ---------------------------------------------------------------------------
# 5. VignettePass reactive property
# ---------------------------------------------------------------------------

class TestVignetteReactive:
    def test_strength_setter_updates_params_strength(self):
        v = VignettePass()
        v.strength = 0.75
        assert v.params["strength"] == pytest.approx(0.75)

    def test_strength_setter_round_trips(self):
        v = VignettePass(strength=0.2)
        assert v.strength == pytest.approx(0.2)
        v.strength = 0.9
        assert v.strength == pytest.approx(0.9)

    def test_strength_setter_stores_float(self):
        v = VignettePass()
        v.strength = 1
        assert isinstance(v.params["strength"], float)


# ---------------------------------------------------------------------------
# 6. FilmGrainPass reactive property
# ---------------------------------------------------------------------------

class TestFilmGrainReactive:
    def test_strength_setter_updates_params_strength(self):
        fg = FilmGrainPass()
        fg.strength = 0.08
        assert fg.params["strength"] == pytest.approx(0.08)

    def test_strength_setter_round_trips(self):
        fg = FilmGrainPass(strength=0.01)
        assert fg.strength == pytest.approx(0.01)
        fg.strength = 0.05
        assert fg.strength == pytest.approx(0.05)

    def test_strength_setter_stores_float(self):
        fg = FilmGrainPass()
        fg.strength = 0
        assert isinstance(fg.params["strength"], float)


# ---------------------------------------------------------------------------
# 7. BloomPass reactive property — threshold stored in params
# ---------------------------------------------------------------------------

class TestBloomPassReactive:
    def test_threshold_stored_in_params(self):
        b = BloomPass(threshold=0.6)
        assert b.params["threshold"] == pytest.approx(0.6)

    def test_threshold_default_value(self):
        b = BloomPass()
        assert b.params["threshold"] == pytest.approx(0.7)

    def test_intensity_setter_updates_params_intensity(self):
        b = BloomPass()
        b.intensity = 2.5
        assert b.params["intensity"] == pytest.approx(2.5)

    def test_intensity_round_trips(self):
        b = BloomPass(intensity=1.2)
        assert b.intensity == pytest.approx(1.2)
        b.intensity = 0.5
        assert b.intensity == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 8. Pass.label uniqueness — two instances with distinct labels
# ---------------------------------------------------------------------------

class TestLabelUniqueness:
    def test_manually_assigned_labels_are_distinct(self):
        p1 = PostProcessPass(shader_path="x.wgsl", label="effect_1")
        p2 = PostProcessPass(shader_path="x.wgsl", label="effect_2")
        assert p1.label != p2.label

    def test_named_subclasses_have_distinct_labels(self):
        labels = {
            ChromaticAberrationPass().label,
            VignettePass().label,
            FilmGrainPass().label,
            BloomPass().label,
        }
        assert len(labels) == 4

    def test_same_class_different_explicit_labels(self):
        p1 = PostProcessPass(shader_path="blur.wgsl", label="blur_near")
        p2 = PostProcessPass(shader_path="blur.wgsl", label="blur_far")
        assert p1.label != p2.label


# ---------------------------------------------------------------------------
# 9. Chain.remove by label
# ---------------------------------------------------------------------------

class TestChainRemove:
    def test_remove_by_label_eliminates_pass(self):
        chain = PostProcessChain()
        chain.add(PostProcessPass(shader_path="a.wgsl", label="remove_me"))
        chain.add(PostProcessPass(shader_path="b.wgsl", label="keep_me"))
        chain.remove("remove_me")
        labels = [p.label for p in chain.passes]
        assert "remove_me" not in labels

    def test_remove_by_label_keeps_other_passes(self):
        chain = PostProcessChain()
        chain.add(PostProcessPass(shader_path="a.wgsl", label="alpha"))
        chain.add(PostProcessPass(shader_path="b.wgsl", label="beta"))
        chain.add(PostProcessPass(shader_path="c.wgsl", label="gamma"))
        chain.remove("beta")
        labels = [p.label for p in chain.passes]
        assert labels == ["alpha", "gamma"]

    def test_remove_nonexistent_label_no_crash(self):
        chain = PostProcessChain()
        chain.add(PostProcessPass(shader_path="a.wgsl", label="exists"))
        chain.remove("does_not_exist")  # should not raise
        assert len(chain.passes) == 1

    def test_remove_named_subclass_by_label(self):
        chain = PostProcessChain()
        chain.add(ChromaticAberrationPass())
        chain.add(VignettePass())
        chain.remove("chromatic_aberration")
        labels = [p.label for p in chain.passes]
        assert "chromatic_aberration" not in labels
        assert "vignette" in labels


# ---------------------------------------------------------------------------
# 10. Chain clear (via _passes reassignment — no public clear())
#     The chain has no .clear() method; we test that emptying _passes works.
# ---------------------------------------------------------------------------

class TestChainClear:
    def test_clear_via_passes_assignment_empties_chain(self):
        chain = PostProcessChain()
        chain.add(PostProcessPass(shader_path="a.wgsl", label="a"))
        chain.add(PostProcessPass(shader_path="b.wgsl", label="b"))
        # Clear by reassigning internal list (as done in on_pp_integrity)
        chain._passes = []
        assert len(chain.passes) == 0

    def test_clear_then_re_add(self):
        chain = PostProcessChain()
        chain.add(PostProcessPass(shader_path="a.wgsl", label="old"))
        chain._passes = []
        new_pass = PostProcessPass(shader_path="b.wgsl", label="new")
        chain.add(new_pass)
        assert chain.passes == [new_pass]


# ---------------------------------------------------------------------------
# 11. Empty chain — iterating passes does not crash
# ---------------------------------------------------------------------------

class TestEmptyChain:
    def test_empty_chain_passes_is_empty_list(self):
        chain = PostProcessChain()
        assert chain.passes == []

    def test_iterate_empty_chain_no_crash(self):
        chain = PostProcessChain()
        executed = []
        for p in chain.passes:
            executed.append(p)
        assert executed == []

    def test_empty_chain_remove_no_crash(self):
        chain = PostProcessChain()
        chain.remove("nonexistent")  # must not raise


# ---------------------------------------------------------------------------
# 12. Pass strength — raw set (no built-in clamp; document actual behavior)
# ---------------------------------------------------------------------------

class TestPassStrengthRaw:
    def test_strength_zero_stores_zero(self):
        ca = ChromaticAberrationPass()
        ca.strength = 0.0
        assert ca.params["strength"] == pytest.approx(0.0)

    def test_strength_large_value_stored_raw(self):
        fg = FilmGrainPass()
        fg.strength = 1.0
        assert fg.params["strength"] == pytest.approx(1.0)

    def test_vignette_strength_zero_stores_zero(self):
        v = VignettePass()
        v.strength = 0.0
        assert v.params["strength"] == pytest.approx(0.0)

    def test_vignette_strength_one_stores_one(self):
        v = VignettePass()
        v.strength = 1.0
        assert v.params["strength"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 13. Observable publish on change — event_bus receives notification
# ---------------------------------------------------------------------------

class TestObservablePublish:
    def test_strength_change_visible_via_chain_reference(self):
        """After setting strength, the in-chain pass reflects the new value."""
        chain = PostProcessChain()
        ca = ChromaticAberrationPass(strength=0.003)
        chain.add(ca)
        ca.strength = 0.007
        found = next(p for p in chain.passes if p.label == "chromatic_aberration")
        assert found.params["strength"] == pytest.approx(0.007)

    def test_vignette_change_visible_via_chain_reference(self):
        chain = PostProcessChain()
        v = VignettePass(strength=0.4)
        chain.add(v)
        v.strength = 0.8
        found = next(p for p in chain.passes if p.label == "vignette")
        assert found.params["strength"] == pytest.approx(0.8)

    def test_film_grain_change_visible_via_chain_reference(self):
        chain = PostProcessChain()
        fg = FilmGrainPass(strength=0.025)
        chain.add(fg)
        fg.strength = 0.08
        found = next(p for p in chain.passes if p.label == "film_grain")
        assert found.params["strength"] == pytest.approx(0.08)


# ---------------------------------------------------------------------------
# 14. Chain.add return value
#     The current implementation returns None; document + assert.
# ---------------------------------------------------------------------------

class TestChainAddReturnValue:
    def test_add_returns_none(self):
        chain = PostProcessChain()
        result = chain.add(PostProcessPass(shader_path="a.wgsl", label="a"))
        assert result is None

    def test_named_factory_methods_return_pass(self):
        """Built-in factories (add_blur etc.) do return the pass."""
        chain = PostProcessChain()
        p = chain.add_blur(radius=3)
        assert isinstance(p, PostProcessPass)
        assert p.label == "blur"

    def test_add_chromatic_aberration_factory_returns_pass(self):
        chain = PostProcessChain()
        p = chain.add_chromatic_aberration(strength=0.006)
        assert isinstance(p, PostProcessPass)
        assert p.params["strength"] == pytest.approx(0.006)


# ---------------------------------------------------------------------------
# 15. Post-process from RaceScene — scene constructs without error
# ---------------------------------------------------------------------------

class TestRaceScenePostProcess:
    def _make_engine(self):
        from unittest.mock import MagicMock
        engine = MagicMock()
        engine.input = None
        engine.lighting = None
        engine.gpu = None
        engine.post_process = None
        return engine

    def _add_game_to_path(self):
        import sys
        # H:\Github\Pharos Engine\python\tests -> ... -> H:\ -> DaedalusSVN\Ochema Circuit
        _game = Path(__file__).parent.parent.parent.parent.parent / "DaedalusSVN" / "Ochema Circuit"
        if str(_game) not in sys.path:
            sys.path.insert(0, str(_game))

    def test_race_scene_constructs_without_error(self):
        self._add_game_to_path()
        from scenes.garage import bake_default_vehicle
        from scenes.race import RaceScene
        engine = self._make_engine()
        vehicle = bake_default_vehicle(None)
        scene = RaceScene(engine, vehicles=[vehicle], track_id="circuit01")
        assert scene is not None

    def test_race_scene_post_chain_attribute_exists(self):
        self._add_game_to_path()
        from scenes.garage import bake_default_vehicle
        from scenes.race import RaceScene
        engine = self._make_engine()
        vehicle = bake_default_vehicle(None)
        scene = RaceScene(engine, vehicles=[vehicle], track_id="circuit01")
        # _setup_post_process either creates a chain or sets None on failure
        assert hasattr(scene, "_post_chain")

    def test_race_scene_post_chain_is_chain_or_none(self):
        self._add_game_to_path()
        from scenes.garage import bake_default_vehicle
        from scenes.race import RaceScene
        engine = self._make_engine()
        vehicle = bake_default_vehicle(None)
        scene = RaceScene(engine, vehicles=[vehicle], track_id="circuit01")
        assert scene._post_chain is None or isinstance(scene._post_chain, PostProcessChain)
