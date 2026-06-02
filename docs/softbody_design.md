# Soft-Body Lattice Physics (XPBD)

This module is the new BeamNG-style node + beam simulator that replaces the
per-pixel hierarchical hull solver for vehicles, creatures, and other
deformable bodies. Coordinates are 2D (the engine is 2D). Units are SI
(metres, seconds, kilograms) with positive `y` pointing *downward*.

## Primitives

- **Node** — a point mass at `pos` with `mass`, `inv_mass`, `vel`, and a
  `layer` tag (0 = bone, 1 = muscle, 2 = skin for creatures; 3 = chassis
  for vehicles). Anchors set `fixed = True` which forces `inv_mass = 0`.
- **Beam** — a distance constraint between two nodes, parameterised by
  `rest_length`, `stiffness` (Pa), `damping` (per-substep velocity
  attenuation, 0..1), `break_strain` (the value of `|Δl / l₀|` above
  which the beam is removed permanently — now measured against the
  *current* rest length, not the initial one), `yield_strain` (the
  fraction of strain below which the beam responds purely elastically),
  and `plasticity_rate` (how aggressively `rest_length` migrates toward
  the deformed length once the yield strain is exceeded).

All arrays live in NumPy SoA blocks (`NodeSoA`, `BeamSoA`) — no per-beam
Python loops in the hot path.

## Solver — XPBD with Jacobi-style scatter

For each render frame we run `substeps` XPBD substeps. Within a substep:

1. **Predict.** `prev_pos := pos`, `pos += vel · Δt + ½ g · Δt²` (only on
   non-fixed nodes).
2. **Project.** Repeat `iters` times: for every live beam compute the
   distance constraint `C = ‖p_b − p_a‖ − l₀`, the compliance
   `α = 1 / (k · Δt²)`, the impulse `Δλ = −C / (w_a + w_b + α)`, and
   scatter the corrections `Δp_a = −w_a · Δλ · n̂`, `Δp_b = +w_b · Δλ · n̂`
   into the position buffer. Each scatter is additionally scaled by a
   per-node *relaxation* factor `1 / deg(node)` (the inverse number of
   beams touching the node) — this is what keeps Jacobi-style aggregation
   stable when many beams correct the same node in parallel. After every
   constraint pass we re-project the floor (`pos.y = min(pos.y, floor_y)`).
3. **Plastic flow.** After the constraint iterations (or inside the
   iteration loop if `plasticity_subcycle` is enabled — smoother crumple
   at ~25% slower), compute `strain = (length − rest_length) / rest_length`
   and `over = |strain| − yield_strain`. For every beam where `over > 0`
   we blend `rest_length` toward the value that would restore the strain
   to exactly `yield_strain`:

   ```
   target_rest = length / (1 + sign(strain) · yield_strain)
   blend       = 1 − exp(−plasticity_rate · Δt_sub)
   rest_length := (1 − blend) · rest_length + blend · target_rest
   ```

   The blend uses the exponential-decay form (Norton–Hoff with an
   implicit Backward-Euler step), which gives `plasticity_rate` proper
   1/s units and makes the result **substep-independent**: doubling
   `substeps` halves `Δt_sub` but the cumulative blend after one frame
   stays the same to second order. In the limit
   `plasticity_rate · Δt_sub → ∞` the beam fully yields in a single
   substep; for small products it reduces to the explicit
   `rest += rate · Δt · sign(strain) · over · rest` update. Catalog
   defaults were retuned (e.g. steel `plasticity_rate` 500 → 10000)
   when the form changed so the smoke tests still report stable ductile
   crumple at `substeps=8`.
4. **Break.** After plasticity, mark every beam whose
   `|length − rest_length| / rest_length` (i.e. the post-yield
   deviation, *not* the raw strain) exceeds `break_strain` as `broken`.
   Broken beams contribute zero `C` from then on (so the body genuinely
   splits). Because plasticity continuously moves `rest_length` to track
   `length`, a ductile beam can stretch by 30% without ever exceeding a
   `break_strain = 0.005` threshold — that is what makes steel crumple
   instead of shatter.
5. **Derive velocity.** `vel := (pos − prev_pos) / Δt`, multiplied by
   `(1 − damping · Δt)` per node. Contact-row nodes get tangential
   velocity scaled by `(1 − floor_friction)` and have downward
   `vel.y` zeroed.

This is the classic Macklin–Müller–Chentanez–Kim 2016 XPBD formulation
(*XPBD: Position-Based Simulation of Compliant Constrained Dynamics*),
with the standard fix for scatter aliasing under NumPy's
`np.add.at` (the `1 / deg(node)` per-node relaxation factor).

The two factors that matter for tuning are:

- **Number of beams per node** — corner nodes of a lattice have 3, edge
  nodes 5, interior 8. The per-node relaxation handles the variance.
- **Stiffness × Δt²** — XPBD is unconditionally stable but stiff beams
  with too few iterations exhibit visible "wobble". `substeps = 8`,
  `iters = 4` is the working baseline.

## Material catalog

The seven materials below live in `material.py` and can be overridden
from `config/softbody.yml` under the `materials:` key.

| name   | density (kg/m²) | stiffness (Pa) | damping | yield_strain | plasticity_rate (1/s) | break_strain | notes                                |
| ------ | --------------- | -------------- | ------- | ------------ | --------------------- | ------------ | ------------------------------------ |
| steel  | 7800            | 2.0e9          | 0.04    | 0.002        | 10000.0               | 0.005        | ductile — crumples plastically       |
| stone  | 2700            | 5.0e8          | 0.05    | 0.001        | 2.0                   | 0.003        | very brittle, near-zero plasticity   |
| wood   | 600             | 1.0e8          | 0.10    | 0.003        | 20.0                  | 0.010        | yields then snaps                    |
| rubber | 1100            | 5.0e5          | 0.30    | 0.150        | 0.5                   | 0.300        | mostly elastic, slow plastic creep   |
| bone   | 1800            | 4.0e8          | 0.05    | 0.005        | 3.0                   | 0.008        | stiff with small ductile region      |
| muscle | 1050            | 1.0e6          | 0.25    | 0.080        | 30.0                  | 0.150        | stretchy, takes plastic deformation  |
| skin   | 1100            | 3.0e5          | 0.20    | 0.150        | 20.0                  | 0.250        | stretches a lot before tearing       |

Stiffness values are *scaled down* from SI moduli (real steel ≈ 2e11 Pa)
so that the chosen substep/iters baseline stays well-behaved. The
relative ordering is what matters for gameplay: steel > stone > bone >
wood > muscle > skin > rubber.

## Topology builders

- `make_lattice_body(world, material, width_cells, height_cells, cell_size, position)`
  — produces a regular grid of nodes with horizontal, vertical, and both
  diagonal beams. Diagonals are slightly softer (`diagonal_stiffness_scale = 0.7`)
  because they otherwise dominate the corner of the alpha matrix.
- `make_layered_creature(world, materials_per_layer, ring_counts, radii, position)`
  — concentric rings of nodes. Inner ring is layer 0 (bone), outer is
  layer N-1 (skin). Each ring is closed into a polygon by tangential
  beams; rings are stitched together by radial beams matched on nearest
  angle. Radial beams are weakened by `cross_layer_stiffness_scale = 0.6`.

## Floor

A single horizontal floor at `floor_y` is enforced as a hard inequality
constraint inside the iteration loop:

```
if pos.y > floor_y: pos.y = floor_y
```

After the substep we also zero the downward component of `vel.y` and
scale tangential velocity by `(1 − floor_friction)` for nodes still in
contact. The floor remains a special-cased clamp; body–body contact
runs as its own XPBD pass (next section).

## Contact constraints

Body–body collision is handled by node-vs-beam capsule contacts and a
node-vs-node fallback, both projected inside the same iteration loop as
the beam constraints (XPBD's iteration is the stability mechanism, so a
separate post-pass would not converge correctly).

### Node-vs-beam capsule

For each node `N ∈ body B` and intact beam `(a, b) ∈ body A` with
`A ≠ B`:

```
t       = clamp(dot(N − a, b − a) / ‖b − a‖², 0, 1)
closest = a + t · (b − a)
delta   = N − closest
dist    = ‖delta‖
```

If `dist < contact_thickness` the contact is violated and we project a
position correction with the standard XPBD form (note the `+` sign —
contacts push apart):

```
C       = contact_thickness − dist
n̂       = delta / dist
w_N = w_N · 1            (full mass on the node)
w_a = w_a · (1 − t)
w_b = w_b · t
α       = 1 / (contact_stiffness · Δt_sub²)
Δλ      = C / (w_N + w_a + w_b + α)
N += +n̂ · w_N · Δλ
a -= +n̂ · w_a · Δλ
b -= +n̂ · w_b · Δλ
```

This is mass-weighted symmetric scatter — momentum stays put when both
sides are free; an infinite-mass beam (e.g. an anchored static obstacle)
absorbs the full correction.

### Node-vs-node fallback

When a node's broadphase query returns no candidate beams (the node has
penetrated entirely past an opposing body's outline), we fall back to
nearest-other-body-node with a contact radius of `2 · contact_thickness`
and the symmetric two-body Δλ form. This is a safety net for deep
penetration; the beam pass dominates in normal operation.

### Broadphase

Uniform-grid spatial hash on current node positions. Cell size is
`max(beam.rest_length) · broadphase_cell_factor` (default factor 1.5).
The hash is rebuilt once per substep — the candidate pair list it
produces is reused across all `iters` projections inside the substep.
Inside the build:

* Cell coordinates `(i, j)` are packed to a single `int64` via XOR of
  two large primes (`73856093 · i ⊕ 19349663 · j`).
* Each beam contributes its two endpoint cells. Keys are sorted once.
* For every node, the 9 neighbour cells are joined into the sorted beam
  table via `numpy.searchsorted`; the join is fully vectorised across
  all nodes and all 9 offsets.
* Self-beams and same-body candidates are filtered out, then duplicate
  `(node, beam)` pairs from overlapping cell hits are removed with
  `np.unique` over a packed `node · (num_beams + 1) + beam` key.

The fallback node-vs-node pass uses the same packed-key + searchsorted
join on the node-cell index.

### Parameters

`config/softbody.yml` carries the contact defaults under the
`contact:` section:

| key                       | default | meaning                                      |
| ------------------------- | ------- | -------------------------------------------- |
| `enabled`                 | `true`  | master toggle                                |
| `default_thickness`       | `0.04`  | capsule half-thickness in metres             |
| `default_stiffness`       | `1.0e9` | XPBD contact compliance (Pa)                 |
| `broadphase_cell_factor`  | `1.5`   | cell size = `max(beam.rest_length) · factor` |

`contact_thickness ≈ 0.5 · cell_size` of a typical lattice is the
working setting. Bumping it to `cell_size` produces "thick rubber"
contact; pushing it well below `0.5 · cell_size` causes tunnelling.
`contact_stiffness` is held very large by default so that contact
behaves nearly rigidly relative to the beam network it pushes against.

Per-material `contact_thickness` and `contact_stiffness` fields exist on
:class:`Material` (so external tools can read them) but the solver
currently uses the world-level defaults — per-material override is the
next refinement.

## Stability notes

- `substeps = 8`, `iters = 4`, `Δt = 1/60` is the baseline that passes
  all four smoke tests.
- Stone is the stiffest brittle material. Bumping substeps to 16 helps
  it ring less but isn't required for the smoke tests.
- Don't drop a body so high that it intersects the floor in a single
  predicted step — the position clamp creates a velocity spike. Spawning
  the body fully *above* `floor_y` is safe.
- Steel's `break_strain` is now `0.005` (close to physical reality)
  because plastic flow keeps `length ≈ rest_length` during a crumple.
  If you drop a steel body so hard that a single substep deviation
  exceeds `0.005` before plasticity catches up, you will still get a
  fracture — increase `substeps` (or enable `plasticity_subcycle`) for
  very high-velocity impacts.

## Rendering

`softbody.render.SoftBodyRenderer` is the engine renderer for soft-body
scenes. It consumes a `SoftBodyWorld` directly (no cells, no hulls) and
forward-splats beams and nodes onto an HDR float buffer, then runs the
same kind of bloom + Reinhard tonemap + gamma pass the rest of the
engine uses so output looks consistent with the legacy
`physics/render.PhysicsRenderer`.

The pipeline per frame:

1. **Background.** Vertical gradient from `bg_top` to `bg_bottom`.
2. **Floor.** One pixel row at `world.floor_y`.
3. **Skin polygon fill.** For multi-layer bodies (`make_layered_creature`),
   the outer-ring nodes are ordered by angle around the body centroid and
   filled as a polygon at ~70% brightness so the silhouette reads as a
   skin envelope. Broken-beam fraction tints the polygon toward the
   material's `damage_color`.
4. **Beams.** Each intact beam is splatted as an antialiased capsule
   between its two node positions, coloured by:
   * the beam-owner's bound material (single-material bodies), or
   * `nodes.layer` → material map (`0=bone, 1=muscle, 2=skin, 3=steel`)
     when the body has mixed layers.
   Strain `|length − rest|/rest` blends the colour toward `damage_color`
   as it approaches `break_strain`. Beams perpendicular to the
   `light_dir` get a small diffuse boost.
5. **Broken beams.** Drawn faintly (`broken_beam_dim` fraction of base) in
   the damage tint, unless `draw_broken=false`.
6. **Nodes.** Soft dots; the per-node count of incident broken beams
   tints the node toward `damage_color` up to `damage_break_count_max`.
7. **Post-process.** Box-blur bloom around bright luma + Reinhard tonemap
   `x / (1 + x)` + gamma.

All numeric defaults live in `config/softbody.yml` under `render:`. Each
:class:`Material` carries its own `render_color` and `damage_color`
tuples; override either in the YAML `materials:` section.

The smoke tests at `python/tests/test_softbody_smoke.py` route their GIF
emission through `SoftBodyRenderer`, so the artefacts in
`SlapPyEngineTests/tests/output/softbody/` look like real engine output (lit, shaded,
material-coloured) rather than flat line plots.

## Vehicles

`softbody.vehicle.build_vehicle` glues three sub-structures into one
body — no new constraint primitive, just :class:`Beam`:

```
        chassis lattice (steel, ductile)
        +---+---+---+---+---+---+
        |\ /|\ /|\ /|\ /|\ /|\ /|
        +---+---+---+---+---+---+
        |/ \|/ \|/ \|/ \|/ \|/ \|
        +---+---+---+---+---+---+
            |\         /|
            | \       / |   <-- suspension beams (vertical "spring"
            |  \     /  |       + diagonal "control arm"), one pair
            |   \   /   |       per wheel
            v    v v    v
          (hub)         (hub)
         12 rim nodes around each hub, joined by tread
         (circumferential), spoke (radial), and optional
         half-circle cross-spokes — all `tire_rubber`.
```

* **Chassis** is `make_lattice_body`-style (axial + diagonal beams) but
  with a per-vehicle `chassis_density_scale` (default `0.10`) so the
  body mass corresponds to a hollow shell rather than solid steel.
  Defaults: 6×3 cells of `chassis_cell_size = 0.40 m`, material
  `steel`. Total mass works out to ≈ 3500 kg.
* **Wheel** has one hub node (mass scaled up by `hub_mass_scale = 4×` so
  it acts as the wheel's centre-of-rotation), plus `rim_count = 12` rim
  nodes around it at `wheel_radius = 0.35 m`. Beams: 12 tread
  (circumferential), 12 spoke (hub→rim), and 6 cross-spokes
  (`rim_i ↔ rim_(i+6)`) for torsional rigidity. All `tire_rubber`.
* **Suspension** wires each hub to the chassis with two beams: a vertical
  "spring" anchored to the nearest bottom-row chassis node
  (`spring_stiffness_scale = 1.0`), and a diagonal "control arm" to the
  next bottom-row node along (`arm_stiffness_scale = 2.0`) that resists
  lateral motion. Material `suspension` has very high damping
  (`0.65 + dt boost`) and effectively unbreakable strain (`1.5`).

### Material additions

Two materials were added to the catalog purely for vehicles:

| name          | stiffness | damping | yield | plast | break | notes                          |
| ------------- | --------- | ------- | ----- | ----- | ----- | ------------------------------ |
| tire_rubber   | 8.0e6     | 0.40    | 0.350 | 0.20  | 2.000 | stretchy, mostly elastic       |
| suspension    | 6.0e7     | 0.65    | 0.001 | 0.05  | 1.500 | medium-stiff, very damped      |

Both have intentionally very high `break_strain` so that running a
vehicle off a kerb at 5 m/s doesn't pop a wheel off; the test
`test_wheel_can_break_off` forces the break by flipping
`beams.broken[susp_ids] = True`.

### Drivetrain torque

Per-frame tangential velocity kick on the rim nodes of each drive wheel:

```python
hub_pos = world.nodes.pos[hub]
r       = world.nodes.pos[rim_ids] - hub_pos
rlen    = np.linalg.norm(r, axis=1)
tangent = np.stack([-r[:,1], r[:,0]], axis=1) / np.maximum(rlen, eps)[:, None]
dv_mag  = (torque / (rlen * world.nodes.mass[rim_ids])) * dt
world.nodes.vel[rim_ids] += tangent * dv_mag[:, None]
```

This is `F = T / r`, `Δv = F / m · Δt`, fully vectorised over the rim
nodes. `drivetrain_mode` selects which wheels are driven: `rwd` (last),
`fwd` (first), `awd` (all). Steering is not implemented — the engine is
2D side-view and the demo drives along the x-axis only.

### What still isn't there

- Steering (no out-of-plane angular freedom in 2D — would need a
  pivot-style chassis–wheel joint we don't have yet).
- Engine RPM / gear-curve. Current `apply_throttle` is linear in the
  `[-1, 1]` throttle input multiplied by `drivetrain_max_torque`.
- Multi-vehicle scenes — vehicles are bodies and body–body contact
  already works; nothing prevents two vehicles in one world, but no
  test covers the case yet.

## What is intentionally not here yet

- Per-material contact thickness / stiffness in the solver path (the
  fields exist on :class:`Material` but the solver reads world-level
  defaults).
- Friction inside body-body contacts (only the floor row has friction).
- Steering, engine-RPM curve, multi-vehicle interaction tests
  (see "Vehicles" above).
- Bullet trace as a first-class primitive (the smoke test inlines its own
  segment-vs-beam intersector).
- GPU port — the solver and renderer are intentionally pure NumPy on CPU
  for this tick.

## Burn-down list (old `physics/`)

The old `physics/` module (hierarchical sparse hulls, per-pixel state)
is *not* touched in this tick. It still drives `test_drop_scenarios.py`
and the existing demo suite. As features above land, we replace the
corresponding old paths and delete dead code; the module stays
operational the whole way.
