## Material Catalog

Reference for every material shipped in `config/softbody.yml` and
`config/fluid.yml`. Values mirror the YAML — to add or tune a material,
edit the YAML and these tables become stale; the engine reads the YAML at
runtime.

### Softbody materials (`config/softbody.yml`)

Loaded by `slappyengine.softbody.MATERIALS`. Each name resolves through
`load_catalog()` into a `Material` dataclass.

| Material | Density (kg/m²) | Stiffness (Pa) | Break strain | Yield strain | Plasticity rate (1/s) | Use case |
|---|---|---|---|---|---|---|
| `steel` | 7800 | 2.0e9 | 0.080 | 0.010 | 2000 | Vehicle chassis; ductile, absorbs impacts past yield |
| `stone` | 2700 | 5.0e8 | 0.003 | 0.003 | 0 | Brittle / "glass" — yield == break, clean fracture |
| `wood` | 600 | 1.0e8 | 0.010 | 0.003 | 20 | Light, slow plastic creep — floats in water |
| `rubber` | 1100 | 5.0e5 | 0.300 | 0.150 | 1000 | Hyperelastic — springy, rarely yields |
| `bone` | 1800 | 4.0e8 | 0.008 | 0.005 | 3 | Humanoid skeleton bones; brittle past yield |
| `muscle` | 1050 | 1.0e6 | 0.150 | 0.080 | 30 | Soft humanoid flesh layer (inner ring) |
| `skin` | 1100 | 3.0e5 | 0.250 | 0.150 | 20 | Soft humanoid flesh layer (outer ring); tears easily |
| `tire_rubber` | 1500 | 8.0e6 | 2.000 | 0.350 | 0.2 | Reinforced wheel tread; very large elastic range |
| `suspension` | 2500 | 6.0e7 | 1.500 | 0.001 | 0.05 | Spring beams — purely elastic in normal use |

Tuning notes:
- `plasticity_rate = 0` paired with `yield_strain == break_strain` gives
  brittle behaviour (clean snap, no rest-length migration).
- High `plasticity_rate` with low `yield_strain` gives ductile behaviour
  (absorbs sustained load without breaking; impacts crumple instead).
- `damping` (0..1 per substep) is not shown above; defaults range from
  0.05 (steel/stone/bone) to 0.65 (suspension).

### Fluid materials (`config/fluid.yml`)

Loaded by `slappyengine.fluid.MATERIALS`. Each name resolves into a
`FluidMaterial` dataclass.

| Material | Rest density (kg/m³) | Kernel radius (m) | Viscosity | Granular | Friction coef. | Phase change | Use case |
|---|---|---|---|---|---|---|---|
| `water` | 1000 | 0.15 | 0.01 | no | 0.0 | freezes → `ice` at 0 °C | Pools, rivers, buoyancy demos |
| `lava` | 2800 | 0.18 | 0.20 | no | 0.0 | freezes → `stone` at 600 °C | Hot dense liquid; HDR orange render |
| `ice` | 920 | 0.14 | 0.0 | yes | 0.4 | melts → `water` above 0 °C | Solid-ish particle pile, slippery |
| `stone` (fluid) | 2700 | 0.16 | 0.0 | yes | 0.9 | melts → `lava` above 1200 °C | Cold solidified lava; high friction |
| `sand` | 1600 | 0.12 | 0.0 | yes | 0.6 | — | Granular pile; angle of repose tan⁻¹(0.6) |
| `gravel` | 2100 | 0.14 | 0.0 | yes | 0.8 | — | Coarser, higher friction than sand |
| `dust` | 900 | 0.11 | 0.0 | yes | 0.35 | — | Light powder; falls in clouds |

Tuning notes:
- `is_granular: true` enables the Coulomb friction pass after density
  projection. `tan(repose_angle) ≈ friction_coef`.
- Phase change is per-particle: when `temperature` crosses the
  `freeze_temperature` or `melt_temperature` threshold from either
  direction, `material_id` is rewritten in place and the particle adopts
  the target material's `rest_density`, `kernel_radius`, etc.
- Two distinct `stone` materials exist — one in `softbody.yml` (brittle
  lattice), one in `fluid.yml` (granular pile). The fluid one is what
  cooled lava becomes.

### Cross-references

- Buoyancy uses `world.water_density` (default 1000 kg/m³, from `fluid.yml`'s
  `world.water_density`) — see `slappyengine.fluid.apply_fluid_buoyancy`.
- Plasticity / yield mechanics are documented in `softbody_design.md`.
- PBF kernel math is documented in `fluid_design.md`.
