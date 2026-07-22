# Idle Animation System — Woodland Creatures Subsystem

**Status:** Design spec (2026-06-03). Pure design; no source yet.
**Sibling docs:**
- [`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md) — the cast (14 creatures, render strategies, per-entry detail).
- [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md) — the parent theme that registers the cast.
- [`ui_concept_art_2026_06_03.md`](ui_concept_art_2026_06_03.md) — concept-art source material.
- [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) — current UI pattern audit.

This document specifies the **subsystem** that drives the woodland
creature animations: module surface, event bindings, performance
contract, theme integration, accessibility settings, and the test
plan that locks the contract.

## 1. Module surface — `pharos_editor.ui.theme.creatures`

The subsystem lives at `pharos_editor.ui.theme.creatures` (sibling to
the existing `theme_spec` module).

### 1.1 Public dataclasses

```python
class Creature:
    """Declarative creature record.

    Pure data — no rendering state. Behaviour is the job of
    CreatureScheduler. Lookups are by ``id``.
    """
    id: str
    render_fn: Callable[[DrawList, float, float, float], None]
        # signature: (draw_list, x, y, anim_t) -> None
        # anim_t is the normalised animation time in [0.0, 1.0]
        # (idle uses a slow phase walk; one-shot uses 0 -> 1 over its duration)
    idle_animations: dict[str, AnimationCurve]
        # name -> keyframe curve (e.g. "blink", "ear_twitch")
    trigger_animations: dict[str, AnimationCurve]
        # name -> keyframe curve (e.g. "flutter", "hoot")
    metadata: dict[str, str] = field(default_factory=dict)
        # season variant tag, atlas key, accessibility class, etc.


class AnimationCurve:
    """Keyframe curve for a single animation state.

    Reuses the existing AnimationCurve concept from
    ``pharos_engine.animation`` (linear / ease-in / ease-out
    interpolation between keyframes; loop / clamp modes).
    """
    duration: float            # seconds
    keyframes: list[Keyframe]  # [(t, value), ...]
    loop: bool = False
    ease: str = "linear"       # "linear" | "ease_in" | "ease_out" | "ease_in_out"


class SlotPolicy:
    """Where a creature lives and how often it may animate."""
    region: Rect               # screen-space bbox (px) the creature occupies
    idle_cooldown: tuple[float, float]
                              # (min_s, max_s) seconds between idle anims
    max_concurrent: int = 1   # how many trigger anims may overlap in this slot
    sub_slots: int = 1        # >1 lets a slot host multiple creatures
                              # (e.g. sidebar = 2 sub-slots)
```

### 1.2 Public scheduler

```python
class CreatureScheduler:
    """Owns the active set of creatures and their per-slot cooldowns.

    Stateless w.r.t. rendering — emits draw commands by calling
    ``creature.render_fn(draw_list, x, y, anim_t)`` each tick.
    """

    def register(self, creature: Creature, slot: SlotPolicy) -> None: ...
        # registers a creature into a slot; raises if the slot is full
        # (existing registrations + this one > slot.sub_slots).

    def unregister(self, creature_id: str) -> None: ...

    def tick(self, dt: float) -> None: ...
        # advances cooldowns, fires idle anims when their cooldown elapses,
        # advances active anim curves, retires curves that finished.

    def trigger(self, creature_id: str, anim_name: str) -> None: ...
        # queues a trigger animation. If max_concurrent is exceeded
        # the new trigger is dropped (with a debug-level log).

    def render(self, draw_list: DrawList) -> None: ...
        # iterates active creatures and calls their render_fn.

    def set_enabled(self, enabled: bool) -> None: ...
        # global on/off — preserves slot/creature registrations.

    def set_reduced_motion(self, on: bool) -> None: ...
        # filters out non-blink animations; see §5.
```

### 1.3 Helpers — event-binding wiring

A separate `pharos_editor.ui.theme.creature_bindings` module wires the
default event-to-creature mapping. The bindings module is the **only**
place that knows about engine event types — `Creature` itself is
event-agnostic.

```python
def install_default_bindings(
    scheduler: CreatureScheduler,
    bus: EventBus,
) -> list[Subscription]:
    """Subscribe ``scheduler.trigger`` to the engine event bus per §2.

    Returns the subscriptions so callers can ``.unsubscribe()`` cleanly
    in tests / teardown.
    """
```

## 2. Event bindings

The default `install_default_bindings()` wires:

| Engine event | Creature | Anim name | Notes |
|---|---|---|---|
| `engine.save` | `butterfly_01` | `flutter` | 1.5 s flight across status bar |
| `engine.build_success` | `bee_01` | `dive` | bee buzzes from toolbar to output panel |
| `engine.build_success` | `acorn_01` | `drop` | 8-12 acorn confetti, gravity fall |
| `engine.build_failure` | `owl_01` | `hoot` | head tilt + chest puff |
| `engine.error` | `owl_01` | `hoot` | same anim, generalised |
| `engine.scene_loaded` | `deer_01` | `peek_in` | sidebar peek |
| `engine.scene_closed` | `deer_01` | `peek_out` | sidebar slide-out |
| `engine.test_pass` | `acorn_01` | `drop` | success confetti |
| `engine.idle_60s` | `fox_01` | `stretch` | rare idle stretch |
| `engine.idle_120s` | `frog_01` | `hop` | very rare cross-toolbar hop |
| `engine.first_run` | `rabbit_01` | `run` | parade spawn |
| `engine.first_run` | `butterfly_01` | `flutter` | parade spawn |
| `progress.start` | `rabbit_01` | `run` | progress bar overlay |
| `progress.end` | `rabbit_01` | `sit` | progress complete |
| `loading.start` | `snail_01` | `crawl` | long-load overlay |
| `loading.cancel` | `snail_01` | `hide` | retract into shell |
| `scene_outliner.select_root` | `flower_01` | `bloom` | "you are here" |
| `code_mode.bookmark_add` | `pinecone_01` | `drop` | bookmark bounce |
| `engine.click_on_mushroom` | `mushroom_01` | `spore_puff` | Easter egg |

Notes:

1. `engine.idle_60s` / `engine.idle_120s` are virtual events — produced
   by the scheduler itself, not by an external publisher. The scheduler
   tracks the last user-action timestamp via `engine.user_action`
   pings (any input event resets the timer).
2. `engine.first_run` is published once by the editor on the first ever
   launch (persistence flag in `~/.pharos_engine/state.json`).

## 3. Performance contract

The contract is asserted by `test_creature_scheduler.py` (§6).

1. **Idle CPU budget.** With ≤ 5 active idle creatures, `scheduler.tick(dt)`
   median wall-time at 60 Hz must be ≤ 1.0 ms (target: 0.3 ms typical).
2. **Trigger CPU budget.** A single trigger animation must complete its
   per-frame work in ≤ 5.0 ms (peak).
3. **Concurrency.** At most 1 trigger animation visible at a time across
   the whole editor unless the slot's `max_concurrent > 1`. Excess
   triggers are dropped (NOT queued, to avoid backlog drift on long
   user sessions). The drop is logged at `DEBUG`.
4. **Cooldown sleep.** Idle creatures whose cooldown is not yet elapsed
   contribute exactly one branch + one float compare to `tick()` — no
   per-frame allocation, no shader uniform update, no draw-list entry.
5. **No per-frame texture upload.** All rendering uses one of:
   - DPG drawlist primitives (line / triangle / circle), or
   - a numpy-baked sprite atlas built at theme-apply time, or
   - a shader-baked texture rendered into a cached GPU texture at
     theme-apply time.

   Per-frame texture uploads are **forbidden** — the test plan asserts
   the atlas/texture-upload counters are unchanged across 60 frames.

## 4. Theme integration

`ThemeSpec` gains an optional creature-binding field:

```python
@dataclass
class ThemeSpec:
    name: str
    palette: dict[str, Color] = field(default_factory=dict)
    # ... existing fields ...
    creatures: dict[str, "CreatureBinding"] = field(default_factory=dict)
        # creature_id -> binding (slot policy + season variant override)
```

A `CreatureBinding` references a `Creature` by ID and assigns it a
`SlotPolicy` and an optional `season` override. Themes that omit
`creatures` get **no creatures** — the subsystem is opt-in per theme.

The TeenGirl Notebook theme declares all 14 creatures from the catalog
with their default slot policies and `season="summer"`. A winter sub-
theme `TeenGirlNotebookWinter` overrides only `season="winter"` and
reuses every other field — so winter fox wears a scarf without any
behaviour code change.

Theme switches drive a single `scheduler.reload(theme)` call that:

1. Unregisters every creature.
2. Re-registers from the new theme's `creatures` dict.
3. Rebuilds any cached shader textures (fern, mushroom) using the new
   palette.

`reload()` is allowed to spend up to 50 ms — it's a one-shot cost paid
once on theme apply, not on every frame.

## 5. Disable + accessibility

Three control surfaces, in priority order:

1. **`settings.ui.creature_animations: bool`** (default: `True`)

   Master switch. `False` calls `scheduler.set_enabled(False)`, which:

   - Skips all `tick()` work after one cheap branch.
   - Drops every incoming `trigger()` call silently.
   - Renders **nothing** — even static decorative creatures are hidden.
     (Themes that depend on creatures for visual hierarchy must provide
     a fallback border via `nine_slices`.)

2. **`settings.ui.reduced_motion: bool`** (default: follows OS
   "Reduce motion" hint where available; `False` otherwise)

   Calls `scheduler.set_reduced_motion(True)`. Behaviour:

   - Idle: only `blink` animations fire. All ear-twitches, sways,
     stretches, hops, head-turns are suppressed.
   - Trigger: animations play but with NO movement — the creature
     appears at its destination instantly and shows only opacity-fade
     in / out. Flutter, dive, hop, peek_in all collapse to a static
     reveal.
   - Confetti: `acorn_01` drop is suppressed entirely (replaced with a
     single static checkmark glyph rendered by the theme).

3. **`settings.ui.easter_eggs: bool`** (default: `True`)

   When `False`, suppresses `mushroom_01` spore puffs and the
   `engine.click_on_mushroom` event handler. The mushroom remains
   visible as static decoration.

## 6. State machine — per-creature lifecycle

```
                +-------------+
                |  DORMANT    |   cooldown not elapsed
                +-------------+
                       | cooldown_elapsed && idle_pick()
                       v
                +-------------+
                |  IDLE_PLAY  |   curve in progress
                +-------------+
                       | curve_finished
                       v
                +-------------+
                |   DORMANT   |   reset cooldown to uniform(min, max)
                +-------------+

      external -> trigger(id, name)
                       |
                       v
                +-------------+
                | TRIGGER_PLAY|   one-shot curve in progress
                +-------------+
                       | curve_finished
                       v
                +-------------+
                | DORMANT (or RESIDENT if persistent)
                +-------------+
```

Persistent creatures (e.g. `fern_01`, `mushroom_01`, `pinecone_01`
bookmarks) live in a separate **RESIDENT** state that never goes
dormant — they render every frame but tick a near-zero-cost branch
(cached texture, no anim curve).

## 7. Test plan

`SlapPyEngineTests/tests/test_creature_scheduler.py`:

1. **Registration / unregistration**
   - `register()` adds the creature; `unregister()` removes it.
   - `register()` raises when slot sub_slots is exceeded.
2. **Slot policy respected**
   - With `max_concurrent=1`, a second `trigger()` while one is active
     is dropped (assert via a counter).
   - With `sub_slots=2`, two creatures can co-register in the same
     `SlotPolicy.region`.
3. **Cooldowns honoured**
   - With `idle_cooldown=(1.0, 2.0)`, ticking 60 Hz for 5 s fires
     between 2 and 5 idle anims (probabilistic; assert via range).
4. **Performance budget**
   - With 5 dummy creatures (each render_fn = no-op), median of
     1000 calls to `tick(1/60)` must be ≤ 1.0 ms on the CI box
     (skip if `os.environ.get("CI_PERF_SKIP")` is set).
5. **No per-frame texture upload**
   - Mock the texture-upload counter; assert it stays constant
     across 60 frames of tick() + render().
6. **Reduced motion**
   - With `set_reduced_motion(True)`, non-blink idle animations are
     not fired even when their cooldown elapses.
7. **Disable**
   - With `set_enabled(False)`, `tick()` returns in < 1 µs and
     `trigger()` is a no-op.
8. **Event-binding integration**
   - Publish `engine.save` on a fresh bus → `butterfly_01.flutter`
     is queued (assert via scheduler internal state).

Performance assertions use `pytest.mark.perf` and are skipped under
the same `CI_PERF_SKIP` flag as the existing dynamics perf tripwire.

## 8. Open questions

1. **Sprite atlas lifecycle.** `frog_01` and `acorn_01` are the only
   sprite-using creatures. Should the atlas be built at install time
   (via `scripts/bake_creature_atlas.py`) or at theme-apply time? Build-
   time keeps theme-apply fast; install-time bloats the wheel by
   ~30 KB.
2. **Engine event prefixes.** Today the engine publishes `save_event`,
   `build_complete`, `error_event` — we'd canonicalise these to the
   `engine.*` namespace as part of this work. Tracked at
   [`telemetry_design.md`](telemetry_design.md) §5.
3. **Easter egg routing.** The mushroom click handler needs a global
   per-creature click router. Defer to a follow-up sprint; ship the
   creature as static-only at first.
4. **First-run parade choreography.** Two creatures spawn on
   `engine.first_run` — should they enter simultaneously or stagger?
   Defer; pick one in the implementation sprint.

## 9. Cross-links

- [`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md) — sibling doc, the cast.
- [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md) — parallel sprint, parent theme.
- [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) — parallel sprint, current-UI audit.
- [`ui_concept_art_2026_06_03.md`](ui_concept_art_2026_06_03.md) — parallel sprint, concept-art inventory.
- [`api/animation.md`](api/animation.md) — existing AnimationCurve / keyframe semantics reused here.
- [`telemetry_design.md`](telemetry_design.md) — event-bus conventions, `engine.*` namespace canonicalisation.
