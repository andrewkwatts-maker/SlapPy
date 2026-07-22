# Lighting Presets

Sprint-3 ships three ready-to-use post-process chain presets that compose the
existing lighting-polish helpers (round-3 bloom, round-4 vignette, round-5
outline, round-6 chromatic-aberration falloff, round-7 auto-EV, round-8
render-channel topological order, round-9 DoF focus transition) into the three
flagship game looks supported by Pharos Engine.

Import path:

```python
from pharos_engine.post_process import (
    cinematic_chain,
    arcade_chain,
    iso_strategy_chain,
)
```

Each factory returns a fully-populated `PostProcessChain` whose passes
appear in the order the executor should run them.  All presets are
backward-compatible — they only call existing chain helpers, never mutate
global state, and never introduce new shader variants.

---

## `cinematic_chain()` — the "movie look"

Use for cutscenes, showcase demos, photo modes, and any sequence where
gameplay readability is **not** the constraint.

| # | Pass | Round | Purpose |
|---|------|------:|---------|
| 1 | `dof`                  | 9 | Soft focal edge (`focus_transition=1.5` -> smoothstep ramp). |
| 2 | `bloom`                | 3 | Mild Lottes smooth-knee glow that survives auto-EV. |
| 3 | `tonemap`              | 7 | ACES mode 0; drive `exposure_ev` with an `AutoExposurePass` per frame. |
| 4 | `chromatic_aberration` | 6 | Polynomial radial falloff (`falloff_power=2, falloff_amount=0.6`). |
| 5 | `vignette`             | 4 | Opt-in smoothstep shoulder (`feather=0.45`). |
| 6 | `outline`              | 5 | Soft Sobel detector — runs last so the DoF blur doesn't mush it. |

### Expected screenshot

- A clear focal plane mid-frame with soft, bokeh-like blur in the background.
- A warm vignette on the corners (smooth shoulder, not the hard pre-round-4 pow).
- Visible but subtle red/blue lens fringing near the corners.
- Silhouettes stay distinct thanks to the Sobel outline running after DoF.

---

## `arcade_chain()` — twitch gameplay, top-down

Use for Ochema Circuit, Bullet Strata, and any game where the player must read
the play-field every frame.

| # | Pass | Round | Purpose |
|---|------|------:|---------|
| 1 | `bloom`    | 3 | Punchier intensity (1.4 vs cinematic 0.8) so neon accents pop. |
| 2 | `tonemap`  | 7 | Contrast 1.2 / saturation 1.15 — arcade pop. |
| 3 | `outline`  | 5 | Legacy binary 4-cardinal path so enemies don't smear under motion. |
| 4 | `vignette` | 4 | `feather=0` — the legacy curve, bit-for-bit. |

### Why no DoF / CA

Depth-of-field and chromatic aberration both blur the play-field, which
is sub-optimal for top-down twitch gameplay.  Players need every pixel
sharp; the arcade preset explicitly omits these passes.

### Expected screenshot

- Bright, saturated colours; punchy contrast.
- Hard binary outlines around every sprite (no temporal pop, no anti-alias).
- Mild round vignette on the periphery — same curve the engine shipped with.

---

## `iso_strategy_chain()` — tower-defence / fixed-depth iso camera

Use for Stone Keep and any title whose camera holds a fixed depth (so DoF
makes no sense) but still wants emissive flourishes.

| # | Pass | Round | Purpose |
|---|------|------:|---------|
| 1 | `bloom`    | 3 | Moderate glow for emissive units (muzzle flashes, status auras). |
| 2 | `tonemap`  | 7 | Declares `depends_on=["bloom"]` so the round-8 topo sort guarantees order. |
| 3 | `vignette` | 4 | Declares `depends_on=["tonemap"]` so the shoulder is post-tonemap. |

### Round-8 dependency hookup

Sprint-3 mirrors the round-8 `RenderPass.depends_on` field onto
`PostProcessPass`.  The iso-strategy preset uses it to make the **intended**
order explicit: even if a caller swaps the chain at runtime, the topological
sort produced by the executor will always run `bloom` -> `tonemap` -> `vignette`.

If you build a custom chain that mixes user-added passes with preset passes,
the `depends_on` declarations propagate — your additions slot in without
breaking the preset's invariants.

### Expected screenshot

- Crisp, fixed-focus iso scene.
- Emissive units (turrets, runes, projectiles) carry a moderate halo.
- Vignette frames the play-field but doesn't darken unit silhouettes.

---

## Backward compatibility

- All preset helpers only call existing `add_*` chain helpers.
- `PostProcessPass.depends_on` defaults to `[]`, so legacy chains see no
  behavioural change.
- The new `chain.add_dof(...)` and `chain.add_bloom(...)` helpers are
  thin wrappers around the existing `DofPass.make_pass()` and
  `BloomPass.make_pass()` paths — no new shader variants, no new uniforms.

## Tests

Regression coverage lives at `PharosEngineTests/tests/test_post_process_preset_chains.py`
and runs CPU-only (no GPU required):

1. `test_cinematic_has_dof_and_bloom`
2. `test_arcade_has_no_dof`
3. `test_iso_strategy_has_topo_dependencies_set`
4. `test_each_preset_builds_without_error` (parametrised across all 3 presets)
5. `test_each_preset_can_serialize_to_dict_of_pass_names` (parametrised)

Run them with:

```bash
PYTHONPATH=python python -m pytest tests/test_post_process_preset_chains.py tests/test_lighting_*.py -v
```
