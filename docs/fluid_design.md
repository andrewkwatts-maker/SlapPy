# Position-Based Fluids (PBF) — 2D Particle Simulator

This module is the flow / pool / merge half of the engine's physics
foundation. The break / crumple half is the soft-body XPBD module in
`softbody/`. PBF reuses the same XPBD-style position-projection
iteration; the only difference is the constraint we project against —
here it is a density constraint instead of a distance constraint.

Coordinates are 2D, units SI (m, s, kg), positive `y` is downward to
match the soft-body convention.

## Substep loop (one PBF substep)

For each substep of duration `Δt_sub = Δt / substeps`:

1. **Predict.** `v ← v + g · Δt_sub`; `x ← x + v · Δt_sub`; project
   boundaries (floor / walls / ceiling) as half-planes.
2. **Build neighbour table.** Uniform-grid spatial hash with cell size
   `h` (the kernel radius). The 9-cell join is fully vectorised: for
   every particle we evaluate `(ix + dx, iy + dy)` for the 9 offsets,
   pack each to an `int64` key via `key = ix·P1 ⊕ iy·P2`, then
   `np.searchsorted` against the sorted own-key list to find candidate
   ranges. Self-pairs are filtered with `i != j`. Pairs whose squared
   distance exceeds `h²` are dropped.
3. **Iterate `iters` times:**
   1. **Density.** `ρ_i = m_i · W_self + Σ_j m_j · W_poly6(|x_i - x_j|, h)`.
      `W_self` is the kernel self-term `4 h⁶ / (π h⁸) = 4 / (π h²)`.
   2. **Constraint.** `C_i = max(ρ_i/ρ_0 − 1, c_floor)` with
      `c_floor = 0` by default (only repulsive — the constraint is
      one-sided so a half-filled fluid does not implode).
   3. **Lagrange multiplier.**
      `λ_i = −C_i / (|Σ_k ∇_k C_i|² + Σ_k |∇_k C_i|² + ε_relax)` where
      `∇_k C_i = (1/ρ_0) · ∇W_spiky(x_i − x_k, h)` for `k = j ≠ i` and
      the diagonal entry sums those gradients with opposite sign.
   4. **Surface-tension cohesion.**
      `s_corr_ij = −k_corr · (W_poly6(|x_i−x_j|, h) / W_poly6(Δq, h))^n_corr`
      with `Δq = scale · h` (the Akinci-style anti-clustering term).
   5. **Position correction.**
      `Δp_i = (1/ρ_0) · Σ_j (λ_i + λ_j + s_corr_ij) · ∇W_spiky(x_i − x_j, h)`
      and `x_i ← x_i + Δp_i`; re-project boundaries.
4. **Re-derive velocity.** `v ← (x − x_prev) / Δt_sub`, clamped to
   `max_velocity` per particle (cap removes the worst pathological
   outliers — not a physical effect, just a numerical safety).
5. **XSPH viscosity.**
   `v_i ← v_i + c_visc · Σ_j (m_j / ρ_0) · (v_j − v_i) · W_poly6(|x_i−x_j|, h)`.
   The `m_j / ρ_0` weighting is the volume-per-neighbour factor that
   keeps the summed kernel value bounded regardless of neighbour
   count.

## 2D kernel normalisation

Macklin's paper uses 3D kernels. The 2D forms used here are

```
W_poly6(r, h)   = 4 / (π h⁸) · (h² − r²)³      for 0 ≤ r ≤ h, else 0
∇W_spiky(r⃗, h) = −30 / (π h⁵) · (h − |r⃗|)² · r⃗/|r⃗|   for 0 < |r⃗| < h
```

**Derivation (1 line each).**

* Poly6: require `∫₀ʰ 2πr · α (h² − r²)³ dr = 1`; sub `u = h² − r²` →
  `α · π · h⁸ / 4 = 1` → `α = 4 / (π h⁸)`.
* Spiky base: require `∫₀ʰ 2πr · β (h − r)³ dr = 1`; expand and
  integrate → `β · π · h⁵ / 10 = 1` → `β = 10 / (π h⁵)`; differentiate
  `β (h − r)³` w.r.t. `r` and multiply by the radial unit vector to
  obtain the gradient coefficient `−30 / (π h⁵)`.

(In 3D the corresponding constants are `315/(64πh⁹)` and `−45/(πh⁶)`.
The 2D analogues used here are smaller because a 2D ball encloses less
than a 3D ball.)

## "Actually flows / pools / merges" — what the tests assert

The old per-pixel solver had visual sloshing but no physically
meaningful invariants. The smoke tests here assert:

1. **Pool flattens.** After `test_water_drops_into_basin_and_pools`,
   the standard deviation of the top-row particle `y` is below a
   tolerance — the fluid surface is approximately flat.
2. **Pool grows.** `test_water_pours_continuously_and_fills_higher`
   emits two successive blobs; the second blob measurably raises the
   final surface height above the first blob alone.
3. **Streams merge.** `test_two_water_streams_merge` collides two
   horizontal streams; after settle, the merged column straddles the
   centre — no air gap, no symmetric escape, just one pool.
4. **Splash returns.** `test_water_splashes_when_object_drops_in`
   drops a steel softbody block onto a settled pool. Particles are
   displaced (variance in `y` grows) and a fraction return below the
   block — they are not all blown clear of the floor.

All four tests also assert mass conservation (count_before ==
count_after), absence of NaN/RuntimeWarning, and KE_after < 10% of
initial gravitational PE.

## Particle ↔ softbody contact

`fluid/contact.py` performs an XPBD-style projection between fluid
particles and the live (non-broken) softbody beams. The beam cells are
keyed with the same `(ix·P1 ⊕ iy·P2)` packing the soft-body uses, and
the per-particle 1-cell `searchsorted` join produces all candidate
(particle, beam) pairs in one vectorised pass. Each pair is projected
with the same form as the soft-body's node-vs-beam contact:

```
t       = clamp(dot(N − a, b − a) / ‖b − a‖², 0, 1)
delta   = N − (a + t·(b − a))
C       = thickness − ‖delta‖              if ‖delta‖ < thickness
n̂       = delta / ‖delta‖
w_a     = w_a_node · (1 − t)
w_b     = w_b_node · t
α       = 1 / (k · Δt_sub²)
Δλ      = C / (w_p + w_a + w_b + α)
N      +=  +n̂ · w_p · Δλ
a      +=  −n̂ · w_a · Δλ
b      +=  −n̂ · w_b · Δλ
```

This is **option A** from the brief: reuse the same XPBD form, sibling
file (`fluid/contact.py`). I chose this over reusing the soft-body's
spatial hash directly because the soft-body hash is keyed by beam
endpoints (cell size = `max(beam.rest_length) · factor`) which is the
wrong cell size for a fluid that has its own `kernel_radius`. A
sibling pass keeps both modules' cell sizes appropriate to their own
characteristic length and avoids hidden coupling in the soft-body
hash's filter rules (which currently strip same-body pairs — fluid
particles are not a body, so they would all leak through).

## Materials — water only this tick

```python
WATER = FluidMaterial(
    name="water", rest_density=1000.0, kernel_radius=0.15,
    relaxation_eps=600.0, viscosity=0.01,
    surface_tension=0.0001, surface_tension_n=4.0,
    particle_mass=1.0,
)
```

`particle_mass` is auto-overridden by `FluidWorld.add_block_of_particles`
so that the rest density is hit *at the chosen spacing*: we compute the
neighbour-sum of `W_poly6` for a uniform lattice at that spacing and
solve `m = ρ_0 / W_sum`. Without this, a user dialling the spacing up
or down would silently get the wrong rest density and watch the
constraint over- or under-correct.

## Numerical knobs that matter

* **`relaxation_eps = 600`.** Higher → softer corrections, mushier
  fluid, fewer divergences when the lattice is degenerate. Lower →
  crisper but jitter when sub-step count is low.
* **`substeps = 4`, `iters = 4`.** The stability baseline. Tests run
  at these defaults.
* **`max_velocity = 40 m/s`.** A safety cap on the re-derived velocity
  (a particle starting at rest reaches this cap after ~4 s of free
  fall — well above anything physical the smoke tests trigger). Acts
  as a structural guard against runaway only; not a physical effect.
* **`density_floor_factor = 0`.** PBF's density constraint is
  one-sided (clamp `C` to `max(0, ρ/ρ_0 − 1)`); negative values let
  particles pull together (effectively adds a cohesive tension term)
  but make low-density regions unstable.

## Granular materials (sand, gravel, dust)

A granular pile is fluid with **Coulomb friction at particle contacts**
in place of viscosity and surface tension. Same kernel, same density
projection, same neighbour table. Only difference is one extra pass and
material-flag gating.

### Friction pass

After the density-projection iterations (still inside the substep), for
every neighbour pair where both particles have `is_granular = True`:

1. Compute current separation `r = |x_i - x_j|`. Skip if `r >=
   contact_radius` (default `0.55 · h`).
2. Estimate relative tangential motion since the start of the substep
   from the predicted displacement:
   `Δx_t = ((x_i - x_i_prev) - (x_j - x_j_prev))` projected onto the
   plane normal to the contact normal `n = (x_i - x_j) / r`.
3. Apply Coulomb cap: `s = min(|Δx_t|, μ · pen)` where `pen =
   contact_radius - r` and `μ` is the mean of the two particles'
   `friction_coef`. The cap is the position-based analogue of the
   normal-force Coulomb limit (`|f_t| ≤ μ · |f_n|`); over a constraint
   step the normal "force" magnitude is proxied by the penetration.
4. Scatter equal-and-opposite tangential position corrections,
   mass-weighted: `Δp_i = -s · ŝ · (w_i / (w_i + w_j))` and the negative
   on `j`, where `ŝ` is the unit tangent direction.

The Coulomb form makes a stationary heap of sand stable at an angle
`θ ≈ arctan(μ)`. With `μ = 0.6` (`SAND`), the expected angle of repose
is ~31° in the continuum limit; the PBD form spreads this somewhat
(the test window is `25° < θ < 50°`). `μ = 0.8` (`GRAVEL`) sits steeper;
`μ = 0.35` (`DUST`) spreads flatter.

### Material settings

Granular materials also set `viscosity = 0` and `surface_tension = 0`
in the catalog — sand grains do not smooth their velocity field like a
viscous fluid and do not exhibit droplet-style cohesion. `relaxation_eps`
is bumped (`2000` for sand, `2400` for gravel) so the density constraint
stays stiff enough not to deform into a fluid puddle under the friction
load.

### Test contracts

* `test_sand_settles_and_loses_energy` — column of sand falls, settles
  on the floor, KE drops below 10% of initial PE (friction is doing
  real work).
* `test_sand_does_not_blend_like_water` — two horizontal streams
  collide; the population's x-position variance stays above a threshold
  (water would collapse to a single mass at the centre).
* `test_sand_drains_through_funnel` — sand column drops + spreads
  laterally (does not deadlock).
* `test_block_buries_in_sand` — steel softbody dropped on a sand pile
  partially sinks; sand displaces laterally instead of blasting away.

### Known formulation gap — angle of repose

In continuum mechanics, a stable granular heap with friction `μ`
takes an angle `θ ≈ arctan(μ)` (so `μ = 0.6` → `θ ≈ 31°`). The
position-based friction form above caps tangential corrections by
`(pen + normal_proxy_floor) · μ`, which is sufficient to differentiate
sand from water (no blending, mass piles instead of pooling) but not
to hold a steep slope — in tests, settled heaps come out closer to
flat than the continuum prediction.

The proper fix is **Macklin position-based friction** (Macklin
et al. 2014, "Unified Particle Physics"), where the normal force proxy
is the magnitude of the density-constraint Lagrange multiplier `λ_n`
rather than penetration depth. Wiring `λ` through from the projection
to the friction pass is a focused follow-up — until then, treat the
`friction_coef` parameter on `FluidMaterial` as a feel knob, not a
calibrated Coulomb coefficient.

## What is intentionally not here yet

* **Confinement vorticity.** Stubbed (`vorticity_eps = 0`), can be
  added without changing the substep skeleton.
* **Surface reconstruction for rendering.** Particles render as
  filled disc + halo. A proper screen-space surface (Müller's
  paraboloid splatting or marching-squares isosurface) is a later
  rendering tick.
* **Heat / temperature field.** Stubbed in the material struct but
  not solved.
* **GPU port.** CPU NumPy only.
* **Body-particle two-way coupling beyond contact.** The contact pass
  pushes both sides apart but the fluid does not exert a sustained
  buoyancy load on the soft-body via a separate body-force term.

## Burn-down for the old per-pixel fluid

The old `physics2/` and `physics/` fluid scaffolds are intentionally
not touched here. PBF lives in its own module so it can be wired up
in demos without disturbing the legacy tests. The next tick is to
swap the demo-facing fluid call-sites over to `slappyengine.fluid`
and then delete the per-pixel fluid scaffolding once nothing imports
it.

## See also

- The fluid subpackage does not ship a dedicated `docs/api/` ref — its
  public surface is documented inline in the source module's docstring
  (`python/slappyengine/fluid/__init__.py`) and via the auto-generated
  entries in [`engine_surface_v030.md`](engine_surface_v030.md).
- [`softbody_design.md`](softbody_design.md) — the sibling XPBD
  subpackage; PBF + softbody compose via `apply_fluid_buoyancy`.
- [`studio_design.md`](studio_design.md) — `fluid_stage()` and
  `fluid_with_softbody_stage()` wrap this module for demos.
- [`numerics_design.md`](numerics_design.md) — the multigrid Poisson
  solver this module's pressure projection could migrate onto in a
  future tick.
