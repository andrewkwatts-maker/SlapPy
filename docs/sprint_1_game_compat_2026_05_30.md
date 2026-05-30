# Sprint 1 — Game integration verification

**Branch:** `sprint-1-game-compat-verify`
**Date:** 2026-05-30
**Scope:** Verify the engine surface contract for Ochema Circuit, Bullet
Strata, and Stone Keep is honoured on master HEAD after the Phase C closure
(commit `a1732e1`).

---

## Headline

- Stone Keep surface (iso.combat + iso primitives + zones): **fully working**
  end-to-end, 100-frame WaveSchedule sim completes with zero NaNs.
- Bullet Strata surface: **half-closed.** The Phase C closure landed the
  `_LAZY_MAP` entries on master, but the underlying modules for ~13 of those
  entries were never committed (`slappyengine.trigger`,
  `slappyengine.deform_zones`, `slappyengine.deform_modes`,
  `slappyengine.deform_controller`, `slappyengine.pixel_material`).
- Ochema Circuit surface: **half-closed.** Same root cause — Phase C added
  the lazy map entries for `softbody.vehicle`, `spline`, `track`,
  `input_provider`, `collision_pixel`, `post_process.motion_blur`,
  `deform_controller`, but none of those modules ship on master HEAD today.
- Net: the tripwire is **34 pass / 20 fail / 0 xfail** (NOT the
  "54 pass + 0 xfail" the sprint plan expected).
- New smoke-instantiation test file
  `tests/test_game_smoke_instantiation.py` lands **13 hard-pass +
  18 xfail** behavioural checks — one xfail per residual-gap symbol so each
  gap auto-flips to xpass the moment the underlying module is committed.

---

## Test results

### `tests/test_game_compat_tripwire.py`

```
34 passed, 20 failed, 0 xfailed
```

Passing surfaces (34):

- Stone Keep: every name (17/17) — iso.combat, iso primitives, zones,
  EventBus, DataComponent.
- Bullet Strata: `DataComponent`, `EventBus`, `GpuParticleSystem`,
  `ParticleEmitter`, `CacheMode`, `Observable`, `Script`, `audio_runtime`,
  `StrataWorld`, `StrataLayer` (10/17).
- Ochema Circuit: `CacheMode`, `DofPass`, `GTAOPass`, `RenderPass`,
  `NightVisionPass`, `RadianceCascadeConfig`, `LightingContext` (7/20).

Failing surfaces (20) — all from missing underlying modules:

| Game | Symbol | Lazy-map target | Status |
|------|--------|-----------------|--------|
| ochema_circuit | `build_vehicle` | `slappyengine.softbody.vehicle` | module not on master |
| ochema_circuit | `VehicleSpec` | `slappyengine.softbody.vehicle` | module not on master |
| ochema_circuit | `WheelSpec` | `slappyengine.softbody.vehicle` | module not on master |
| ochema_circuit | `apply_drivetrain_torque` | `slappyengine.softbody.vehicle` | module not on master |
| ochema_circuit | `CatmullRomSpline` | `slappyengine.spline` | module not on master |
| ochema_circuit | `SplineTrack` | `slappyengine.track` | module not on master |
| ochema_circuit | `PlayerInputProvider` | `slappyengine.input_provider` | module not on master |
| ochema_circuit | `PixelCollisionPass` | `slappyengine.collision_pixel` | module not on master |
| ochema_circuit | `MotionBlurPass` | `slappyengine.post_process.motion_blur` | module not on master |
| ochema_circuit | `SimFrequencyBudget` | `slappyengine.deform_controller` | module not on master |
| ochema_circuit | `SimState` | `slappyengine.deform_controller` | module not on master |
| ochema_circuit | `DeformController` | `slappyengine.deform_controller` | module not on master |
| bullet_strata | `TriggerSystem` | `slappyengine.trigger` | module not on master |
| bullet_strata | `TriggerVolume` | `slappyengine.trigger` | module not on master |
| bullet_strata | `DeformController` | `slappyengine.deform_controller` | module not on master |
| bullet_strata | `MaterialPreset` | `slappyengine.deform_modes` | module not on master |
| bullet_strata | `ZoneMap` | `slappyengine.deform_zones` | module not on master |
| bullet_strata | `SimFrequencyBudget` | `slappyengine.deform_controller` | module not on master |
| bullet_strata | `CrackMode` | `slappyengine.deform_modes` | module not on master |
| bullet_strata | `PixelMaterialMap` | `slappyengine.pixel_material` | module not on master |

Distinct missing modules (5 net): `slappyengine.trigger`,
`slappyengine.deform_zones`, `slappyengine.deform_modes`,
`slappyengine.deform_controller`, `slappyengine.pixel_material`,
`slappyengine.softbody`, `slappyengine.spline`, `slappyengine.track`,
`slappyengine.input_provider`, `slappyengine.collision_pixel`,
`slappyengine.post_process.motion_blur` — i.e. 11 module paths covering
20 lazy-map entries.

### `tests/test_game_smoke_instantiation.py` (NEW)

```
13 passed, 18 xfailed, 0 failed
```

Behavioural pins (one tick of behaviour each, beyond mere importability):

1. `EventBus()` + class-level publish/subscribe kwargs round-trip.
2. Module-level `event_bus.publish`/`subscribe` round-trip.
3. `DataComponent()` + kwarg-set + `.watch` attribute exists.
4. `Observable(bus=..., topic=...)` + `notify(**payload)` routes to
   the bound bus.
5. `CacheMode` Enum has GPU/RAM/DISK members.
6. `StrataWorld(layers=[StrataLayer(...)])` builds a 3-layer world.
7. `ParticleEmitter()` default ctor + emit + tick → 64x64x4 uint8 texture.
8. `GpuParticleSystem(ctx, max_particles)` with a mocked wgpu device.
9. `audio_runtime.get_backend()` returns a backend with `stop_all`/`play`.
10. `Script()` default ctor.
11. `zones.RectZone` + `ZoneManager` enter callback round-trip.
12. `zones.ThresholdZone` fires at threshold + re-arms on hysteresis.
13. Stone Keep: 100-frame WaveSchedule + 2-wave spec, 5 spawns, schedule
    completes, every Defender has finite hp/pos, `resolve_attack` kills all
    in-range defenders within 3 swings (NaN tripwire).

xfail entries (1 per residual gap, auto-flip to xpass when module lands):
`TriggerSystem`, `TriggerVolume`, `ZoneMap`, `CrackMode`, `MaterialPreset`,
`PixelMaterialMap`, `SimFrequencyBudget`, `SimState`, `DeformController`,
`build_vehicle`, `VehicleSpec`, `WheelSpec`, `apply_drivetrain_torque`,
`CatmullRomSpline`, `SplineTrack`, `PlayerInputProvider`,
`PixelCollisionPass`, `MotionBlurPass`.

---

## Classes that import but crash on construction

**None.** Every game-required symbol that *does* resolve also constructs
cleanly under default / mocked args. The only failure mode on the engine
surface today is the 20 missing-module entries above — those don't import
at all (`ModuleNotFoundError`), so they don't reach the "import succeeds
but ctor blows up" pathology this test file was written to catch.

---

## Recommended follow-up (out of Sprint 1 scope)

1. **Re-land the residual Phase C modules** so the tripwire reaches the
   expected 54 pass / 0 xfail state:
   - `python/slappyengine/trigger.py`
     (`TriggerSystem`, `TriggerVolume`)
   - `python/slappyengine/deform_zones.py` (`ZoneMap`)
   - `python/slappyengine/deform_modes.py`
     (`CrackMode`, `MaterialPreset`)
   - `python/slappyengine/deform_controller.py`
     (`DeformController`, `SimState`, `SimFrequencyBudget`)
   - `python/slappyengine/pixel_material.py` (`PixelMaterialMap`)
   - `python/slappyengine/softbody/vehicle.py`
     (`build_vehicle`, `VehicleSpec`, `WheelSpec`,
     `apply_drivetrain_torque`)
   - `python/slappyengine/spline.py` (`CatmullRomSpline`)
   - `python/slappyengine/track.py` (`SplineTrack`)
   - `python/slappyengine/input_provider.py` (`PlayerInputProvider`)
   - `python/slappyengine/collision_pixel.py` (`PixelCollisionPass`)
   - `python/slappyengine/post_process/motion_blur.py` (`MotionBlurPass`)
2. **As each module lands**, the corresponding `test_missing_module_residual_gap`
   xfail in `tests/test_game_smoke_instantiation.py` will xpass — and the
   sibling tripwire failure will flip to pass — without any test edit.

---

## Sprint 1 deliverables

- Branch: `sprint-1-game-compat-verify`
- Files touched:
  - `tests/test_game_smoke_instantiation.py` (NEW — 31 tests, 13 pass + 18 xfail)
  - `docs/sprint_1_game_compat_2026_05_30.md` (this file)
- Files explicitly NOT touched:
  - `python/slappyengine/__init__.py` (per sprint rules)
  - `python/slappyengine/softbody/`, `fluid/`, `sim_field.py`
  - `tests/test_game_compat_tripwire.py` (the failing test is reporting a
    real, accurate gap — converting failures to xfail here would mask the
    residual Phase C work)
