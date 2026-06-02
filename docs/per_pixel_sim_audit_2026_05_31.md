# `per_pixel_sim.wgsl` branch-reachability audit — 2026-05-31

Audit triggered by `docs/phase_d_strip_plan_2026_05_31.md` §c. Goal:
prove which conditional branches in
`python/slappyengine/physics/shaders/per_pixel_sim.wgsl` (429 LOC) are
unreachable now that Phase D's `CellMaterial` strip is imminent, and
trim any whose gating field the uploader no longer populates.

## Verdict

**No branches are unreachable.** The Phase D Python-side cuts (steps
1-7 of the strip plan) have NOT landed — the last two repo commits
(`bc1976b`, `e62b930`) only add the plan doc and mark step 1 BLOCKED.
`physics/world.py::_pack_params` (lines 2743-2792) still threads every
`CellMaterial` field into `HullParams`, so every gating field in the
shader receives live per-material values exactly as before.

No trim is justified. The shader stays at 429 LOC. The `tests/test_gpu_headless.py` canary is green (4 passed) as a baseline.

## Uploader evidence

Source: `python/slappyengine/physics/world.py::_pack_params`, lines
2743-2792. Packs `<4I 36f` (4 u32 + 36 f32 = 160 B) per hull. Every
`HullParams` field in `per_pixel_sim.wgsl:28-88` has a corresponding
`float(mat.<field>)` or `float(cell.<field>)` write at the call site.

`CellMaterial` itself is alive at `python/slappyengine/deform_modes.py:284`
with defaults still set (`brittle_modulus: float = 999.0`,
`tear_strength: float = 999.0`, `Y: float`, `is_fluid: bool`, melt /
ductile / brittle rates, etc.). The MATERIAL presets (GLASS
`brittle_modulus=0.3`, RUBBER `tear_strength=0.3`, STEEL
`brittle_modulus=2.5`, LAVA `is_fluid=True`, ...) all still flow.

## Per-branch reachability table

| Branch | Lines | Gate | Uploader writes? | Reachable? |
|---|---|---|---|---|
| Fluid pressure-gradient force | 234-241 | `p.is_fluid == 1u` | `world.py:2754` writes `1 if mat.is_fluid else 0` from `CellMaterial.is_fluid`. WATER / LAVA / SMOKE / OIL presets set `is_fluid=True`. | YES — live. |
| Solid KE→heat injection | 279-281 | `p.is_fluid == 0u` | Same field, opposite side. Every solid preset (GLASS, STEEL, FLESH, BONE, etc.) sets `is_fluid=False`. | YES — live. |
| Melt anneal + viscous damping | 304-310 | `heat > p.melt_point` | `world.py:2778` writes `mat.melt_point`. Heat accumulates via solid KE→heat (279-281) and ductile strain-energy (363-367); both paths active. | YES — live. Reachability requires only `heat` to cross `melt_point` at runtime; nothing field-side disables it. |
| Brittle fracture core | 312-335 | `p.brittle_modulus < 800.0 && vm > brittle_eff && !is_melted` | `world.py:2759` writes `mat.brittle_modulus`. GLASS=0.3, STEEL=2.5, ICE=0.5, CERAMIC=12.0 — all <800. | YES — live. |
| Catastrophic brittle severance | 327-334 | Nested inside brittle, gated by `excess_b > cat_excess && dmg > brittle_catastrophic_damage_gate` | `world.py:2771-2773` writes the three `cell.brittle_catastrophic_*` config floats (default ratio=3.0, gate=0.4, floor=0.0). | YES — live. |
| Ductile plastic flow | 337-368 | `vm > Y_eff && !is_melted && !brittle` | `world.py:2758` writes `mat.Y`, `:2774-2776` write the three `ductile_*` rates. FLESH `Y=0.04`, MUD `Y=0.02`, etc. | YES — live. |
| LAVA-style ductile-runaway suppressor | 363-367 | Nested in ductile, gated `p.is_fluid == 0u` | Same `is_fluid` field. Inner branch suppresses strain-energy heat injection for fluids; reached every time the ductile branch fires on a solid. | YES — live. |
| Stretch-driven tearing | 377-382 | `p.tear_strength < 800.0 && stretch_now > p.tear_strength` | `world.py:2763` writes `mat.tear_strength`. RUBBER=0.3, FLESH=0.20, GLASS=0.03 — all <800. | YES — live. |
| Second fluid block (pressure update) | 389-398 | `p.is_fluid == 1u` | Same `is_fluid` field. | YES — live. |
| Silhouette mask | 405-409 | `s.density < p.silhouette_mask_threshold` | `world.py:2789` writes `cell.silhouette_mask_threshold`. | YES — live. |

## Why nothing was trimmed

The strip-plan note that motivated this audit said the brittle / ductile / melt branches
"require post-step-7 audit **once the uploader no longer threads `CellMaterial` fields**."
The uploader still threads them. Until Phase D step 5 (`deform_modes.py` cut) and step 9
(`world.py` cut) land, every gating field is populated with real values from the live
material presets — there is no field the shader reads that the uploader does not write.

Re-audit trigger: after Phase D step 5 lands and `world.py::_pack_params` is replaced
by the softbody/fluid uploader. At that point `brittle_modulus`, the three
`brittle_catastrophic_*` floats, the three `ductile_*` rates, `tear_strength`,
`tear_growth_rate`, `melt_point`, `melt_anneal_rate`, `melt_viscous_damping`,
`thermal_softening_coefficient`, `damage_weakening_coefficient`, and
`heat_strain_energy_factor` are the candidates — each can be confirmed dead only
when its uploader write site is gone, not before.

## Canary baseline

`PYTHONPATH=python python -m pytest tests/test_gpu_headless.py --no-header -q`
→ `4 passed in 1.25s`. Use this as the pre-trim snapshot when Phase D step 5+
lands and a real trim becomes possible.
