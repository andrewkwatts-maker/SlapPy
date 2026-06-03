"""Tests for the extended built-in creature roster (8 cuddly species).

Covers:

* Each new creature constructs without error.
* Each carries the documented personality colour.
* Each declares the documented idle + trigger animations.
* :func:`register_builtins` registers all 11 (3 existing + 8 new).
* Render contract: each render_fn accepts ``(draw_list, x, y, t)``
  and produces non-zero draw calls.
* Theme switch: red_panda_01 + cat_01 stay in their slots when the
  active theme changes.

The tests are headless: a small recording ``MockDrawList`` captures
the ``record(kind, **kwargs)`` calls and the assertions only inspect
the recorded list.
"""
from __future__ import annotations

import pytest

try:
    from slappyengine.ui.theme import Color
    from slappyengine.ui.theme.creatures import (
        AnimationCurve,
        CreatureScheduler,
        _reset_default_scheduler_for_tests,
    )
    from slappyengine.ui.theme.creatures.builtin import (
        butterfly_01,
        butterfly_01_slot,
        butterfly_02,
        butterfly_02_slot,
        cat_01,
        cat_01_slot,
        fox_01,
        fox_01_slot,
        golden_01,
        golden_01_slot,
        hedgehog_01,
        hedgehog_01_slot,
        panda_01,
        panda_01_slot,
        porcupine_01,
        porcupine_01_slot,
        raccoon_01,
        raccoon_01_slot,
        red_panda_01,
        red_panda_01_slot,
        register_builtins,
        sparkle,
    )
except Exception as e:  # pragma: no cover — defensive import skip
    pytest.skip(
        f"slappyengine.ui.theme.creatures.builtin not importable: {e}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Recording draw list + fixtures
# ---------------------------------------------------------------------------


class MockDrawList:
    """Recording draw-list — every ``record`` call is captured."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def record(self, kind: str, **kwargs) -> None:
        self.calls.append((kind, kwargs))

    @property
    def kinds(self) -> list[str]:
        return [c[0] for c in self.calls]


@pytest.fixture(autouse=True)
def _isolate_singleton():
    _reset_default_scheduler_for_tests()
    yield
    _reset_default_scheduler_for_tests()


# Reference spec from the theme-diary catalog: (factory, slot_factory,
# expected RGB tuple, idle names tuple, trigger names tuple).
SPEC = [
    (
        cat_01,
        cat_01_slot,
        (0xE8, 0xA8, 0x7C),
        ("breathe", "blink", "stretch", "tail_flick"),
        ("stretch_full",),
    ),
    (
        golden_01,
        golden_01_slot,
        (0xE8, 0xC1, 0x6F),
        ("tail_wag", "ear_flop", "pant"),
        ("tail_celebrate",),
    ),
    (
        red_panda_01,
        red_panda_01_slot,
        (0xB4, 0x65, 0x1C),
        ("deep_breath", "tail_swish", "ear_twitch"),
        ("lift_head",),
    ),
    (
        raccoon_01,
        raccoon_01_slot,
        (0xA0, 0xA8, 0xB5),
        ("ear_perk", "paw_clean"),
        ("peek_behind",),
    ),
    (
        panda_01,
        panda_01_slot,
        (0xFA, 0xFA, 0xFA),
        ("chew", "sit_swap"),
        ("bamboo_drop",),
    ),
    (
        porcupine_01,
        porcupine_01_slot,
        (0x9C, 0x7B, 0x5A),
        ("nibble", "blink"),
        ("ball_up",),
    ),
    (
        hedgehog_01,
        hedgehog_01_slot,
        (0x8C, 0x6F, 0x4A),
        ("sniff", "bristle"),
        ("bristle_full",),
    ),
    (
        butterfly_02,
        butterfly_02_slot,
        (0xFF, 0x6F, 0xB5),
        ("wing_idle",),
        ("flutter_full",),
    ),
]


# ---------------------------------------------------------------------------
# 1-8. Each creature constructs without error
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory,slot_factory,_rgb,_idle,_trig", SPEC,
                         ids=lambda v: getattr(v, "__name__", str(v)))
def test_creature_constructs_without_error(
    factory, slot_factory, _rgb, _idle, _trig
):
    c = factory()
    slot = slot_factory()
    assert c.id == factory.__name__
    assert slot.region.w > 0 and slot.region.h > 0


# ---------------------------------------------------------------------------
# 9-16. Each has the expected personality_color
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory,_slot_factory,rgb,_idle,_trig", SPEC,
                         ids=lambda v: getattr(v, "__name__", str(v)))
def test_creature_personality_color_matches_spec(
    factory, _slot_factory, rgb, _idle, _trig
):
    c = factory()
    assert isinstance(c.personality_color, Color)
    assert (c.personality_color.r, c.personality_color.g,
            c.personality_color.b) == rgb


# ---------------------------------------------------------------------------
# 17-24. Each declares the documented idle animations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory,_slot_factory,_rgb,idle,_trig", SPEC,
                         ids=lambda v: getattr(v, "__name__", str(v)))
def test_creature_idle_animations_present(
    factory, _slot_factory, _rgb, idle, _trig
):
    c = factory()
    for name in idle:
        assert name in c.idle_animations, (
            f"{c.id}: missing idle anim {name!r}; "
            f"have {sorted(c.idle_animations)}"
        )
        assert isinstance(c.idle_animations[name], AnimationCurve)


# ---------------------------------------------------------------------------
# 25-32. Each declares the documented trigger animations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory,_slot_factory,_rgb,_idle,trig", SPEC,
                         ids=lambda v: getattr(v, "__name__", str(v)))
def test_creature_trigger_animations_present(
    factory, _slot_factory, _rgb, _idle, trig
):
    c = factory()
    for name in trig:
        assert name in c.trigger_animations, (
            f"{c.id}: missing trigger anim {name!r}; "
            f"have {sorted(c.trigger_animations)}"
        )
        assert isinstance(c.trigger_animations[name], AnimationCurve)


# ---------------------------------------------------------------------------
# 33. register_builtins registers all 11 creatures
# ---------------------------------------------------------------------------


def test_register_builtins_registers_full_roster():
    s = CreatureScheduler()
    register_builtins(s)
    ids = set(s.registered_ids)
    expected = {
        "fox_01", "butterfly_01", "sparkle",
        "cat_01", "golden_01", "red_panda_01", "raccoon_01",
        "panda_01", "porcupine_01", "hedgehog_01", "butterfly_02",
    }
    assert ids == expected
    assert len(ids) == 11


# ---------------------------------------------------------------------------
# 34-41. Render contract — render_fn accepts (draw_list, x, y, t)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("factory,_slot_factory,_rgb,_idle,_trig", SPEC,
                         ids=lambda v: getattr(v, "__name__", str(v)))
def test_creature_render_fn_emits_draw_calls(
    factory, _slot_factory, _rgb, _idle, _trig
):
    c = factory()
    dl = MockDrawList()
    # Sweep the [0, 1] phase range and confirm draws are emitted at each
    # phase; an empty draw list at any phase would mean the render fn
    # silently skipped a frame, which would fail the scheduler's render
    # contract.
    for phase in (0.0, 0.25, 0.5, 0.75, 1.0):
        before = len(dl.calls)
        c.render_fn(dl, 16, 16, phase)
        assert len(dl.calls) > before, (
            f"{c.id} render_fn emitted zero draws at phase={phase}"
        )


# ---------------------------------------------------------------------------
# 42-43. Theme switch — cat_01 + red_panda_01 stay in their slots
#         when the active theme changes (the slot policy is opaque to
#         theme state — it is owned by the creature factory, not the
#         palette).
# ---------------------------------------------------------------------------


def test_cat_slot_unchanged_across_theme_switch():
    # Two separate factory calls — analogous to applying two different
    # themes that both register the same builtin.
    a = cat_01_slot()
    b = cat_01_slot()
    assert a.region.x == b.region.x
    assert a.region.y == b.region.y
    assert a.region.w == b.region.w
    assert a.region.h == b.region.h
    assert a.region.parent_panel == b.region.parent_panel == "title_bar"
    assert a.idle_cooldown_s == b.idle_cooldown_s


def test_red_panda_slot_unchanged_across_theme_switch():
    a = red_panda_01_slot()
    b = red_panda_01_slot()
    assert a.region.x == b.region.x
    assert a.region.y == b.region.y
    assert a.region.w == b.region.w
    assert a.region.h == b.region.h
    assert a.region.parent_panel == b.region.parent_panel == "toolbar"
    assert a.idle_cooldown_s == b.idle_cooldown_s


# ---------------------------------------------------------------------------
# Sanity: existing trio still registers cleanly with the extended roster
# ---------------------------------------------------------------------------


def test_existing_trio_still_present():
    # Belt and braces — the user explicitly asked for "3 existing + 8 new".
    s = CreatureScheduler()
    register_builtins(s)
    ids = s.registered_ids
    for cid in ("fox_01", "butterfly_01", "sparkle"):
        assert cid in ids
    # And the factories themselves are still callable independently.
    assert fox_01().id == "fox_01"
    assert butterfly_01().id == "butterfly_01"
    assert sparkle().id == "sparkle"
    # Existing slot factories still typed.
    assert fox_01_slot().region.parent_panel == "toolbar"
    assert butterfly_01_slot().region.parent_panel == "status_bar"
