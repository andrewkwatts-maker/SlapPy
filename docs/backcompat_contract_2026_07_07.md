# Public downstream backcompat contract — 2026-07-07 (YY6)

Owner: agent YY6 (parallel-sprint), 2026-07-07.

Sibling to [`docs/api_stability_2026_07_07.md`](api_stability_2026_07_07.md)
(UU7 backcompat harness — name-deletion + subclass-abuse tripwires) and
[`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md) (TT1 → WW3
game-compat re-runs). Where UU7 pins the *set of names* the engine
publishes, this contract pins the *shape* of what those names return and
the *iteration semantics* of the collections they expose.

---

## 1. Motivation

The UU7 harness closed the largest class of silent breakage TT1
uncovered — the "symbol quietly disappeared" class. But two more classes
still leak past every engine-side test:

1. **Return-shape drift.** The name is still there but the object it
   returns changed shape. Downstream `payload.publisher` starts raising
   `AttributeError: 'dict' object has no attribute 'publisher'`.
   (WW3 caught 84 Ochema sites of this pattern.)
2. **Iteration / assignment drift.** `for x in obj.layers` starts
   raising because `layers` was refactored to a lazy generator; or
   `entity.tags = ["a", "b"]` starts raising because the setter now
   rejects lists.

YY6's tripwire pair covers both classes.

---

## 2. The tripwire

Two paired test files ship with this contract:

* [`SlapPyEngineTests/tests/test_backcompat_downstream_shape.py`](../SlapPyEngineTests/tests/test_backcompat_downstream_shape.py)
  — pins the *return shape* of five load-bearing public APIs.
* [`SlapPyEngineTests/tests/test_backcompat_iteration_patterns.py`](../SlapPyEngineTests/tests/test_backcompat_iteration_patterns.py)
  — pins the *iteration / assignment semantics* of three engine-managed
  collections (`entity.layers`, `bus._listeners`, `entity.tags`).

Each check uses `pytest.importorskip` and `hasattr` guards so a fix that
hasn't landed yet (e.g. YY1's EventPayload return-shape wrapper) yields
an `xfail`, not a hard failure. Once the fix lands the check flips to
`xpass`; the harness surfaces both.

---

## 3. Pinned downstream contracts

The following shapes MUST remain stable from v0.4.0 onward.

### 3.1 `EventBus.publish(...)` return

`EventBus.publish("topic", **payload)` returns an object exposing:

* Attribute access — `.publisher`, `.label`, `.data`, `.timestamp`.
* Dict-style access — `result["publisher"]`.

Timestamps are unix-epoch floats. `.data` is a `dict` mirroring the
kwargs. `.publisher` and `.label` come out of the kwargs when supplied
and default to sensible sentinels otherwise.

Owner of the underlying fix: sibling agent YY1 (in-flight this sprint).
Until YY1 lands, the shape checks `xfail` cleanly on plain-`None`
return.

### 3.2 `AudioManager.play_loop(handle, volume, pitch)` handle

Returns an object exposing:

* `.stop()` — stop this loop.
* `.set_volume(vol: float)` — clamp-and-set per-loop volume.
* `.set_pitch(pitch: float)` — clamp-and-set per-loop pitch.

Ochema Circuit's Sprint P3 audio system currently drives the tracked-
loop registry via the integer-id API (`stop_loop(id)`,
`set_loop_volume(id, v)`, `set_loop_pitch(id, p)`); the object-handle
contract is the aspirational shape and `xfail`s until backfilled.

### 3.3 `LightingSystem.load_profile(name)` return

Returns an object (or dict) exposing at minimum:

* `.ambient` / `["ambient"]` — RGB tuple.
* `.ambient_intensity` / `["ambient_intensity"]` — float.

Currently applies in-place and returns `None`; the returned-config shape
is the aspirational contract. Until backfilled, the check verifies
in-place state mutation still occurs and `xfail`s on the return value.

### 3.4 `RenderTarget.add_layer(spec)` dict-shape polymorphism

`add_layer` accepts EITHER:

* A `Layer` instance (current baseline), or
* A dict-shaped layer spec like `{"name": "foo", "mode": "2D"}` that
  the engine wraps into a `Layer` internally.

Dict-shaped support is aspirational and `xfail`s on the current
Layer-only contract; the check does NOT block master.

### 3.5 `Observable` cooperative init chain

`type("X", (Observable, Asset), {})` dynamic subclasses construct with a
single `X()` call that walks the cooperative `super().__init__()`
chain end-to-end. Both `Observable._bus` / `_observable_topic` AND
`Asset.layers` (via `RenderTarget → Entity → object`) must be present on
the resulting instance.

Owner of the underlying fix: sibling agent UU1 (already landed
2026-07-07); this test locks the behaviour so a future MRO refactor
can't silently regress it.

### 3.6 `CacheMode` variant values are `str`

Every variant of `slappyengine.residency.manager.CacheMode` MUST have a
`str`-typed `.value`.  Bullet Strata's residency-tier YAML compares
`.value` against string literals; a variant flipping from `str` → `int`
takes out ~26 game-compat sites (VV1 fix, 2026-07-07).

### 3.7 Iteration / assignment contracts

* `for layer in entity.layers` — `entity.layers` MUST be re-iterable
  (not a consumed generator) and index-accessible.
* `for topic, listeners in bus._listeners.items()` — `bus._listeners`
  MUST expose the `dict` interface (`.items()`, `.keys()`, `.values()`,
  plain-iter).
* `entity.tags = ["foo", "bar"]` — the `tags` attribute MUST accept a
  plain list assignment; iteration and membership queries MUST work
  afterwards regardless of whether the engine coerces to a set.

---

## 4. Version compat promise

| Aspect | Guarantee |
|---|---|
| Baseline | v0.4.0 release (2026-07 target). |
| Stability window | STABLE through v1.x — no shape changes without a deprecation cycle. |
| Additive changes | New attrs on payloads / new methods on handles — permitted freely, no deprecation. |
| Removal / rename | Requires a full deprecation cycle (see § 5). |
| Cross-minor promotion | Aspirational contracts (`xfail`ing today) may be promoted to `must-pass` at any minor bump; downgrade from `must-pass` back to `xfail` is NOT permitted. |

The v0.4.0 baseline is the *first* baseline this contract covers.
Every shape / iteration semantic listed in § 3 becomes locked at
v0.4.0's tag commit, snapshotted transitively by the two YY6 test files
plus the pre-existing UU7 name-surface snapshot at
[`SlapPyEngineTests/tests/data/api_surface_snapshot.json`](../SlapPyEngineTests/tests/data/api_surface_snapshot.json).

---

## 5. Deprecation policy

Any breaking change to a § 3 contract requires all three steps in
order:

1. **N**  → mark deprecated. Emit `DeprecationWarning` from the
   affected code path; add a CHANGELOG entry under the current
   `[Unreleased]` block referencing the deprecation. Update the check
   in the YY6 tripwire file to `xfail(strict=False, reason=...)` so
   downstream can still rely on the old shape.
2. **N+1** (one minor version cycle) → keep both shapes working; the
   `DeprecationWarning` remains. Downstream games have one full minor
   version to migrate.
3. **N+2** → remove the deprecated shape. Bump the YY6 tripwire's
   `xfail` to a hard assertion of the *new* shape only. Add a
   CHANGELOG entry under the removal-minor's `[Removed]` block cross-
   referencing the N-cycle deprecation.

The one-minor-cycle window mirrors the UU7 name-deletion policy — see
[`docs/api_stability_2026_07_07.md`](api_stability_2026_07_07.md) § 3
for the equivalent name-surface deprecation cycle.

**Explicit anti-pattern:** silently changing a return shape and only
noticing when a game-compat run lights up. TT1 → WW3 spent five
sprints doing exactly this. The YY6 harness makes it structurally
impossible for a future contributor to repeat the mistake without
tripping a red test in engine CI *before* the change lands.

---

## 6. Adding a new pinned contract

When a downstream project discovers a load-bearing shape not yet
covered by this doc:

1. Add a matching check to
   [`test_backcompat_downstream_shape.py`](../SlapPyEngineTests/tests/test_backcompat_downstream_shape.py)
   or
   [`test_backcompat_iteration_patterns.py`](../SlapPyEngineTests/tests/test_backcompat_iteration_patterns.py)
   as appropriate.
2. If the shape isn't yet supported by the engine, gate with
   `pytest.xfail(...)` per the pattern already used for
   `EventBus.publish` / `AudioManager.play_loop` / `LightingSystem`.
3. Add a § 3.x entry to this doc describing the contract.
4. Include a source citation (which downstream project + which file
   depends on the shape) so future refactor PRs can reason about the
   blast radius.

Do NOT loosen an existing check to "unstick" a refactor. Either land
the shape-preserving refactor or ship the deprecation cycle from § 5.

---

## 7. Cross-links

* [`docs/api_stability_2026_07_07.md`](api_stability_2026_07_07.md) —
  UU7 name-surface + subclass-pattern tripwires.
* [`docs/game_compat_2026_07_07.md`](game_compat_2026_07_07.md) —
  TT1 → WW3 live game-compat re-runs; every shape pinned in § 3 above
  traces back to a specific site count in that doc.
* [`docs/v0_4_ship_decision_2026_07_07.md`](v0_4_ship_decision_2026_07_07.md)
  — VV7 ship-decision doc; § 3.6 (`CacheMode`) was VV1's fix.
* [`SlapPyEngineTests/tests/data/api_surface_snapshot.json`](../SlapPyEngineTests/tests/data/api_surface_snapshot.json)
  — the paired UU7 name lockfile.
