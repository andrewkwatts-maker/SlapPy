"""Tests for :mod:`pharos_engine.ui.theme.creatures`.

Coverage:

* :class:`AnimationCurve` — sample / is_done semantics, sort stability,
  validation.
* :class:`SlotPolicy` / :class:`SlotRegion` — rect + cooldown validation.
* :class:`CreatureScheduler` — register / unregister, cooldown advance,
  trigger drop-on-full, master switch + reduced motion, performance
  contract.
* Built-in fox / butterfly / sparkle — registration + render contract
  on a mock drawlist.
* Module-level singleton wrappers — register_creature / trigger / tick.

The tests are headless: a :class:`MockDrawList` records ``record(kind,
**kwargs)`` calls without any DPG dependency.
"""
from __future__ import annotations

import time

import pytest

try:
    from pharos_engine.ui.theme.creatures import (
        AnimationCurve,
        Creature,
        CreatureScheduler,
        Keyframe,
        SlotPolicy,
        SlotRegion,
        _reset_default_scheduler_for_tests,
        register_creature,
        set_enabled,
        set_reduced_motion,
        tick,
        trigger,
    )
    from pharos_engine.ui.theme.creatures.builtin import (
        butterfly_01,
        butterfly_01_slot,
        fox_01,
        fox_01_slot,
        register_builtins,
        sparkle,
        sparkle_slot,
    )
    from pharos_engine.ui.theme import Color
except Exception as e:  # pragma: no cover — defensive import skip
    pytest.skip(
        f"pharos_engine.ui.theme.creatures not importable: {e}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


class MockDrawList:
    """Recording draw-list — every ``record`` call is appended to a list."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def record(self, kind: str, **kwargs) -> None:
        self.calls.append((kind, kwargs))

    @property
    def kinds(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def _isolate_singleton():
    """Each test sees a fresh module-level singleton."""
    _reset_default_scheduler_for_tests()
    yield
    _reset_default_scheduler_for_tests()


def _noop_render(draw_list, x, y, anim_t):
    return None


def _simple_creature(cid: str = "test_01") -> Creature:
    return Creature(
        id=cid,
        render_fn=_noop_render,
        idle_animations={
            "blink": AnimationCurve(
                keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 1.0)],
                duration_s=0.2,
            ),
            "stretch": AnimationCurve(
                keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 1.0)],
                duration_s=1.0,
            ),
        },
        trigger_animations={
            "wake_up": AnimationCurve(
                keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 1.0)],
                duration_s=0.5,
            ),
        },
        personality_color=Color(255, 128, 64, 1.0),
    )


def _slot(min_s: float = 0.1, max_s: float = 0.2, max_concurrent: int = 1) -> SlotPolicy:
    return SlotPolicy(
        region=SlotRegion(x=0, y=0, w=64, h=64, parent_panel="toolbar"),
        idle_cooldown_s=(min_s, max_s),
        max_concurrent=max_concurrent,
    )


# ===========================================================================
# 1-3. AnimationCurve.sample at t=0 / 0.5 / 1
# ===========================================================================


def test_animation_curve_sample_at_zero_returns_first_value():
    curve = AnimationCurve(
        keyframes=[Keyframe(0.0, 5.0), Keyframe(1.0, 25.0)], duration_s=2.0
    )
    assert curve.sample(0.0) == pytest.approx(5.0)


def test_animation_curve_sample_at_midpoint_linear_interp():
    curve = AnimationCurve(
        keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 10.0)], duration_s=2.0
    )
    # Halfway through the 2s duration -> norm 0.5 -> value 5.0.
    assert curve.sample(1.0) == pytest.approx(5.0)


def test_animation_curve_sample_at_end_returns_last_value():
    curve = AnimationCurve(
        keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 10.0)], duration_s=2.0
    )
    assert curve.sample(2.0) == pytest.approx(10.0)


# ===========================================================================
# 4. is_done after duration
# ===========================================================================


def test_animation_curve_is_done_only_after_duration():
    curve = AnimationCurve(
        keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 1.0)], duration_s=0.5
    )
    assert curve.is_done(0.4) is False
    assert curve.is_done(0.5) is True
    assert curve.is_done(1.0) is True


def test_animation_curve_loop_never_done_and_wraps():
    curve = AnimationCurve(
        keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 1.0)],
        duration_s=1.0,
        loop=True,
    )
    assert curve.is_done(100.0) is False
    # Wraps modulo duration — t=2.5 ≡ t=0.5 ≡ value 0.5.
    assert curve.sample(2.5) == pytest.approx(0.5)


def test_animation_curve_sorts_unordered_keyframes():
    curve = AnimationCurve(
        keyframes=[Keyframe(1.0, 10.0), Keyframe(0.0, 0.0), Keyframe(0.5, 5.0)],
        duration_s=1.0,
    )
    # Should still interpolate correctly despite input being out of order.
    assert curve.sample(0.5) == pytest.approx(5.0)


def test_animation_curve_rejects_empty_keyframes():
    with pytest.raises(ValueError, match="keyframes must be non-empty"):
        AnimationCurve(keyframes=[], duration_s=1.0)


def test_animation_curve_rejects_zero_duration():
    with pytest.raises(ValueError):
        AnimationCurve(keyframes=[Keyframe(0.0, 0.0)], duration_s=0.0)


# ===========================================================================
# 5. SlotPolicy validates rect + cooldown ranges
# ===========================================================================


def test_slot_region_rejects_zero_width():
    with pytest.raises(ValueError):
        SlotRegion(x=0, y=0, w=0, h=10)


def test_slot_region_rejects_negative_coords():
    with pytest.raises(ValueError):
        SlotRegion(x=-1, y=0, w=10, h=10)


def test_slot_policy_rejects_inverted_cooldown():
    with pytest.raises(ValueError, match="must be >="):
        SlotPolicy(
            region=SlotRegion(x=0, y=0, w=10, h=10),
            idle_cooldown_s=(5.0, 1.0),
        )


def test_slot_policy_accepts_equal_cooldown_bounds():
    p = SlotPolicy(
        region=SlotRegion(x=0, y=0, w=10, h=10),
        idle_cooldown_s=(2.0, 2.0),
    )
    assert p.idle_cooldown_s == (2.0, 2.0)


def test_slot_policy_round_trip_preserves_fields():
    region = SlotRegion(x=10, y=20, w=64, h=32, parent_panel="status_bar")
    p = SlotPolicy(
        region=region,
        idle_cooldown_s=(1.5, 3.0),
        max_concurrent=2,
        reduced_motion_idle_ok=False,
    )
    assert p.region.x == 10 and p.region.w == 64
    assert p.idle_cooldown_s == (1.5, 3.0)
    assert p.max_concurrent == 2
    assert p.reduced_motion_idle_ok is False


# ===========================================================================
# 6. CreatureScheduler.register accepts a Creature + Slot
# ===========================================================================


def test_scheduler_register_and_unregister():
    s = CreatureScheduler()
    c = _simple_creature()
    s.register(c, _slot())
    assert "test_01" in s.registered_ids
    s.unregister("test_01")
    assert "test_01" not in s.registered_ids


def test_scheduler_register_rejects_duplicate_id():
    s = CreatureScheduler()
    c = _simple_creature()
    s.register(c, _slot())
    with pytest.raises(ValueError, match="already registered"):
        s.register(c, _slot())


def test_scheduler_register_rejects_wrong_types():
    s = CreatureScheduler()
    with pytest.raises(TypeError):
        s.register("not a creature", _slot())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        s.register(_simple_creature(), "not a slot")  # type: ignore[arg-type]


# ===========================================================================
# 7. tick advances idle animations based on cooldown
# ===========================================================================


def test_scheduler_tick_fires_idle_after_cooldown():
    s = CreatureScheduler(rng_seed=42)
    s.register(_simple_creature(), _slot(min_s=0.1, max_s=0.1))
    # Initial cooldown picked at register time; tick past it.
    s.tick(0.2)
    # An idle animation should now be active.
    assert s.active_count == 1


def test_scheduler_tick_dt_zero_is_noop():
    s = CreatureScheduler()
    s.register(_simple_creature(), _slot())
    s.tick(0.0)
    assert s.active_count == 0


def test_scheduler_tick_rejects_negative_dt():
    s = CreatureScheduler()
    with pytest.raises(ValueError, match="dt must be >= 0"):
        s.tick(-0.1)


# ===========================================================================
# 8. trigger fires once even if called twice rapidly
# ===========================================================================


def test_scheduler_trigger_drops_when_concurrency_full():
    s = CreatureScheduler()
    s.register(_simple_creature(), _slot(max_concurrent=1))
    assert s.trigger("test_01", "wake_up") is True
    # Slot is now full — second trigger drops.
    assert s.trigger("test_01", "wake_up") is False
    assert s.dropped_trigger_count == 1


def test_scheduler_trigger_unknown_creature_raises():
    s = CreatureScheduler()
    with pytest.raises(LookupError):
        s.trigger("not_registered", "wake_up")


def test_scheduler_trigger_unknown_animation_raises():
    s = CreatureScheduler()
    s.register(_simple_creature(), _slot())
    with pytest.raises(LookupError, match="not declared"):
        s.trigger("test_01", "no_such_anim")


def test_scheduler_trigger_max_concurrent_two_allows_two():
    s = CreatureScheduler()
    s.register(_simple_creature(), _slot(max_concurrent=2))
    assert s.trigger("test_01", "wake_up") is True
    assert s.trigger("test_01", "wake_up") is True
    # Third drops.
    assert s.trigger("test_01", "wake_up") is False


# ===========================================================================
# 9. set_enabled(False) silences all animation
# ===========================================================================


def test_scheduler_set_enabled_false_silences_tick_and_trigger():
    s = CreatureScheduler()
    s.register(_simple_creature(), _slot(min_s=0.01, max_s=0.01))
    s.set_enabled(False)
    s.tick(1.0)
    assert s.active_count == 0  # tick was a no-op
    assert s.trigger("test_01", "wake_up") is False


def test_scheduler_set_enabled_back_to_true_resumes():
    s = CreatureScheduler()
    s.register(_simple_creature(), _slot())
    s.set_enabled(False)
    s.set_enabled(True)
    assert s.is_enabled is True


def test_scheduler_set_enabled_rejects_non_bool():
    s = CreatureScheduler()
    with pytest.raises(TypeError):
        s.set_enabled("on")  # type: ignore[arg-type]


# ===========================================================================
# 10. set_reduced_motion(True) limits to blinks only
# ===========================================================================


def test_scheduler_reduced_motion_only_fires_blink():
    # Use a creature whose ONLY non-blink idle is "stretch" so we can
    # detect that the scheduler refused to pick it.
    s = CreatureScheduler(rng_seed=0)
    c = Creature(
        id="rm_test",
        render_fn=_noop_render,
        idle_animations={
            "stretch": AnimationCurve(
                keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 1.0)],
                duration_s=0.5,
            ),
        },
        trigger_animations={},
    )
    s.register(c, _slot(min_s=0.01, max_s=0.01))
    s.set_reduced_motion(True)
    # Pump 30 frames — cooldown is 0.01 s so this would normally fire
    # many times, but the only available idle is "stretch" which is
    # filtered out in reduced-motion mode.
    for _ in range(30):
        s.tick(0.05)
    assert s.active_count == 0


def test_scheduler_reduced_motion_still_allows_blink():
    s = CreatureScheduler(rng_seed=0)
    c = Creature(
        id="rm_blink",
        render_fn=_noop_render,
        idle_animations={
            "blink": AnimationCurve(
                keyframes=[Keyframe(0.0, 0.0), Keyframe(1.0, 1.0)],
                duration_s=0.2,
            ),
        },
        trigger_animations={},
    )
    s.register(c, _slot(min_s=0.01, max_s=0.01))
    s.set_reduced_motion(True)
    s.tick(0.1)
    assert s.active_count == 1


# ===========================================================================
# 11. Performance: 5 creatures + 100 ticks completes in <= 5 ms
# ===========================================================================


def test_scheduler_performance_budget():
    s = CreatureScheduler()
    for i in range(5):
        s.register(_simple_creature(f"perf_{i}"), _slot())
    t0 = time.perf_counter()
    for _ in range(100):
        s.tick(1 / 60)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    # 5 ms total wall-clock for 100 ticks * 5 creatures = headroom.
    assert elapsed_ms <= 5.0, f"tick budget blown: {elapsed_ms:.3f} ms"


# ===========================================================================
# 12. fox_01 / butterfly_01 / sparkle registration + render
# ===========================================================================


def test_register_builtins_populates_scheduler():
    s = CreatureScheduler()
    register_builtins(s)
    ids = s.registered_ids
    assert "fox_01" in ids
    assert "butterfly_01" in ids
    assert "sparkle" in ids


def test_fox_render_contract_emits_draw_calls():
    s = CreatureScheduler(rng_seed=1)
    s.register(fox_01(), fox_01_slot())
    dl = MockDrawList()
    s.render(dl)
    # Even dormant the fox renders at phase 0 — body + head appear.
    assert any(kind == "ellipse" for kind, _ in dl.calls)


def test_butterfly_render_contract_emits_svg_call():
    s = CreatureScheduler(rng_seed=1)
    s.register(butterfly_01(), butterfly_01_slot())
    dl = MockDrawList()
    s.render(dl)
    assert any(kind == "svg" for kind, _ in dl.calls)


def test_sparkle_render_contract_emits_svg_and_shader():
    s = CreatureScheduler(rng_seed=1)
    s.register(sparkle(), sparkle_slot())
    dl = MockDrawList()
    s.render(dl)
    kinds = [k for k, _ in dl.calls]
    assert "svg" in kinds
    assert "shader_swatch" in kinds


def test_builtins_personality_colors_match_spec():
    # fox = warm orange #E5853B; butterfly = pink #FF6FB5.
    f = fox_01()
    assert f.personality_color.r == 0xE5
    assert f.personality_color.g == 0x85
    assert f.personality_color.b == 0x3B
    b = butterfly_01()
    assert b.personality_color.r == 0xFF
    assert b.personality_color.g == 0x6F
    assert b.personality_color.b == 0xB5


def test_sparkle_has_no_trigger_animations():
    sp = sparkle()
    assert sp.trigger_animations == {}


# ===========================================================================
# 13. Module-level singleton wrappers
# ===========================================================================


def test_module_level_register_and_tick():
    register_creature(_simple_creature(), _slot(min_s=0.01, max_s=0.01))
    tick(0.1)
    # Just confirm tick + trigger don't blow up via the singleton path.
    set_reduced_motion(False)
    set_enabled(True)


def test_module_level_trigger_returns_bool():
    register_creature(_simple_creature(), _slot())
    assert trigger("test_01", "wake_up") is True


# ===========================================================================
# 14. total_budget_ms aggregation
# ===========================================================================


def test_scheduler_total_budget_aggregates_registered_creatures():
    s = CreatureScheduler()
    register_builtins(s)
    # fox=0.3 + butterfly=0.5 + sparkle=0.1 + cat=0.3 + golden=0.4
    # + red_panda=0.4 + raccoon=0.35 + panda=0.3 + porcupine=0.3
    # + hedgehog=0.3 + butterfly_02=0.5 -> 3.75 ms
    assert s.total_budget_ms == pytest.approx(3.75)


# ===========================================================================
# 15. Render-fn signature compliance for all builtins
# ===========================================================================


@pytest.mark.parametrize(
    "factory,slot_factory",
    [
        (fox_01, fox_01_slot),
        (butterfly_01, butterfly_01_slot),
        (sparkle, sparkle_slot),
    ],
)
def test_builtin_render_fn_accepts_phase_range(factory, slot_factory):
    """Every built-in render fn must tolerate anim_t in [0, 1]."""
    c = factory()
    dl = MockDrawList()
    for phase in (0.0, 0.25, 0.5, 0.75, 1.0):
        c.render_fn(dl, 0, 0, phase)
    # At least one draw call per phase * 5 phases.
    assert len(dl.calls) >= 5


# ===========================================================================
# 16. Cooldown bounds — repeated picks stay within range
# ===========================================================================


def test_scheduler_cooldown_picks_stay_within_bounds():
    s = CreatureScheduler(rng_seed=123)
    s.register(_simple_creature(), _slot(min_s=2.0, max_s=4.0))
    # Internal record — we can poke for white-box check.
    rec = s._slots["test_01"]
    assert 2.0 <= rec.cooldown_remaining <= 4.0
    # Pump many cooldown resets.
    for _ in range(50):
        cd = s._pick_cooldown(rec.policy)
        assert 2.0 <= cd <= 4.0
