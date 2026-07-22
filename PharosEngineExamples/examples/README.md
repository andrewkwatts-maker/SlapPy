# Pharos Engine Examples

This directory holds runnable demos for the **per-pixel physics simulator**
and its renderer.  Every demo here is a single self-contained Python file
that builds a `PhysicsWorld`, simulates a fixed number of frames, and writes
a `.gif` (and sometimes still `.png` snapshots) under `examples/output/`.

The demos pair with the user-facing documentation:

| If you want to...                                  | Read first                          |
|----------------------------------------------------|-------------------------------------|
| Walk through your first physics scene end-to-end   | [`docs/physics_tutorial.md`](../docs/physics_tutorial.md)         |
| Look up `PhysicsWorld` / `PhysicsBody` / renderer  | `docs/physics_api.md`               |
| Pick a material (steel vs lava vs water vs ...)    | `docs/materials_guide.md`           |
| Understand GPU vs CPU substeps + dispatch          | `docs/gpu_pipeline.md`              |
| Verify mass / momentum / energy invariants         | `docs/conservation_proofs.md`       |

> Running a demo from a source checkout?  Either install the package
> (`pip install -e .`) or prepend `python/` to `PYTHONPATH`.  The demos
> all import from `pharos_engine.physics`.

---

## Physics demos

Each demo writes its output to `examples/output/<demo_name>.gif`.

### `physics_vehicle_demo.py`
A rectangular iron chassis with two rubber wheels rolls across a chain of
stone/sand hills.  Contacts kick up dust particles, the chassis cell field
takes plastic strain on each bump, and the scene is composited through the
default bloom + tonemap chain with a directional `ShadowPass`.

- **Run:** `python examples/physics_vehicle_demo.py`
- **Output:** `examples/output/physics_vehicle_demo.gif`
- **What you'll see:** A boxy iron buggy bouncing across a striped terrain,
  trailing puffs of dust where the wheels strike rock, with soft cast
  shadows from above-left.
- **APIs:** `PhysicsWorld`, `make_rect_silhouette`, `make_circle_silhouette`,
  `ParticleSystem.emit_from_contacts`, `ShadowPass`, `default_post_process_chain`,
  `PhysicsRenderer.save_gif`.

![](output/physics_vehicle_demo.gif)

---

### `physics_projectile_demo.py`
Three high-velocity steel pellets fire horizontally at three armor plates —
**glass**, **iron**, and **diamond** — in zero gravity.  Each plate's
per-cell deformation simulator responds in character: glass shatters
(connected-components > 1), iron dents (plastic strain accumulates), and
diamond shrugs the projectile off with damage below `0.3`.

- **Run:** `python examples/physics_projectile_demo.py`
- **Outputs:**
    - `examples/output/physics_projectile_demo.gif` — full animation
    - `examples/output/projectile_pre_impact.png` — frame 20 (in flight)
    - `examples/output/projectile_impact.png` — frame 60 (at peak contact)
    - `examples/output/projectile_post_impact.png` — frame 120 (debris settled)
- **What you'll see:** Three horizontal tracks; the glass plate explodes into
  bright shards, the iron plate dents and gets nudged backwards, the diamond
  plate barely budges.
- **APIs:** `PhysicsYaml`, `load_physics_config`, `world.hulls.mass`,
  `connected_components`, `ParticleSystem`, key-frame PNG capture via
  `Image.fromarray`.

![](output/physics_projectile_demo.gif)

---

### `physics_sand_pile_demo.py`
A 28-ball triangular **sand pyramid** is dropped into a stone funnel (two
angled walls + a floor).  Demonstrates granular contact resolution, oriented
static walls, and the contact solver finding a settled angle of repose.

- **Run:** `python examples/physics_sand_pile_demo.py`
- **Output:** `examples/output/physics_sand_pile_demo.gif`
- **What you'll see:** A neat pyramid of small tan-coloured balls collapses
  into the funnel, slithers down the angled walls, and forms a settled pile.
  The summary prints the empirical angle of repose at the end.
- **APIs:** rotated walls via `world.hulls.angle`, `world.hulls.mark_dirty()`,
  per-frame `kinetic_energy` / `mean_y` / contact-count diagnostics.

![](output/physics_sand_pile_demo.gif)

---

### `physics_lava_flow_demo.py`
A 48-diameter **lava blob** (`initial_heat = 12.0 > melt_point = 9.0`)
rests on a wide **ice slab**.  `BoundaryExchange` conducts heat across the
contact seam: lava cools monotonically, ice locally heats and *melts*
(density at the seam drops), and the demo asserts total mass stays conserved
to within tolerance.  Bloom + tonemap give the molten cells a halo.

- **Run:** `python examples/physics_lava_flow_demo.py`
- **Output:** `examples/output/physics_lava_flow_demo.gif`
- **What you'll see:** A glowing orange blob sitting on a pale-blue slab
  while two steel witnesses flank it.  The blob's glow fades over 300 frames
  as heat conducts into the ice; the slab darkens locally under the blob.
- **APIs:** `BoundaryExchange` (cross-body heat conduction),
  `BloomPass`, `TonemapPass`, custom `PostProcessChain`, conservation of
  Σ density × ρ_mat × cell_area.

![](output/physics_lava_flow_demo.gif)

---

### `physics_materials_gallery_demo.py`
The **visual reference** for every supported material.  Drops one circle of
each of `steel / iron / stone / glass / wood / rubber / ice / mud / water /
sand / clay / lava / concrete / oil / slime / diamond / paper / snow / gold`
onto a wide stone slab in a single shot.  Skips any material the registry
doesn't know about.

- **Run:** `python examples/physics_materials_gallery_demo.py`
- **Outputs:**
    - `examples/output/physics_materials_gallery.gif` — 180-frame fall + settle
    - `examples/output/materials_strip.png` — annotated still with each
      ball labelled (great for documentation)
- **What you'll see:** A long row of differently coloured balls falling
  in unison.  Lava glows, glass and ice read as cool blues, oil as near-black,
  gold as a warm yellow, etc.
- **APIs:** `list_materials`, `PhysicsRenderer(palette=...)` overrides,
  PIL annotation for the strip.

![](output/physics_materials_gallery.gif)

![](output/materials_strip.png)

---

## Hello-X demos (non-physics)

Smaller "hello world" scripts for adjacent subsystems.  They are not
covered in the physics tutorial but help orient new contributors:

| Script                            | What it shows                                     |
|-----------------------------------|---------------------------------------------------|
| `hello_world.py`                  | Minimum boot of the engine + a single sprite.     |
| `hello_physics.py`                | Smallest possible `PhysicsWorld` step loop.       |
| `hello_lighting.py`               | Point lights + ambient on a basic scene.          |
| `hello_3d_layer.py`               | The 3D layer interop (mesh + camera).             |
| `hello_pixel.py`                  | Direct cell-grid writes for pixel-art workflows.  |
| `hello_bake.py`                   | Bake a lighting/AO probe to texture.              |
| `editor_demo.py`                  | Launch the Nova3D-themed editor shell.            |
| `fluid_sandbox.py`                | Interactive fluid scratchpad.                     |
| `hud_demo.py` / `landscape_demo.py` / `layered_character.py` / `multiplayer_demo.py` | Specialized one-off demos. |
| `particles_sample.py`             | Standalone `ParticleSystem` shower.               |

---

## Visual tests (under `tests/visual/`)

These are pytest-driven render tests.  Each one drives a real
`PhysicsWorld` or scene through `PhysicsRenderer` and asserts the output
frames look right.  Outputs live under `tests/visual/output/<name>/`.

Run all of them with `pytest tests/visual/ -q`.  Each test prints which
frames it wrote, and on failure leaves the rendered PNGs/GIFs behind for
inspection.

| Test file                                  | Produces                                                                                                  |
|--------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `test_vis_collision.py`                    | 90-frame steel-on-glass-on-stone drop sequence under `output/collision/`.                                  |
| `test_vis_fluid.py`                        | Steel ball into water pool; splash + waves under `output/fluid/`.                                          |
| `test_vis_particles.py`                    | Two stone balls colliding in zero-g; contact-shatter particle frames under `output/particles/`.            |
| `test_vis_shadows.py`                      | 60 frames of four balls casting `ShadowPass` shadows under `output/shadows/` (plus a longer `shadows_long/` variant). |
| `test_vis_lighting_2d.py`                  | 2D point-lighting smoke frames under `output/lighting_2d/`.                                                 |
| `test_vis_lighting_clustered.py`           | Clustered-shading lighting frames under `output/lighting_clustered/`.                                       |
| `test_vis_taa.py`                          | TAA-resolved sequence under `output/taa/`.                                                                  |
| `test_vis_fog.py`                          | Volumetric fog passes under `output/fog/`.                                                                  |
| `test_vis_ao.py`                           | GTAO at default + small + big radii under `output/ao/`, `output/ao_small_r/`, `output/ao_big_r/`.           |
| `test_vis_gi_cascade.py`                   | Cascade-of-radiance GI frames under `output/gi_cascade/`.                                                   |
| `test_vis_gi_restir.py`                    | ReSTIR GI frames under `output/gi_restir/`.                                                                  |
| `test_vis_pbr.py`                          | PBR sphere matrix under `output/pbr/`.                                                                       |
| `test_vis_sdf.py`                          | Signed-distance-field visualisations under `output/sdf/`.                                                    |

The `tests/visual/output/physics_drops/` directory holds the canonical
per-pair drop GIFs and impact-frame stills used in `docs/materials_guide.md`
(`steel_into_stone`, `steel_into_mud`, `steel_into_water`, `glass_into_stone`,
`lava_onto_ice`, `iron_into_iron`).

---

## Where to go next

- Start with [`docs/physics_tutorial.md`](../docs/physics_tutorial.md) — it
  walks through *building* a scene rather than reading finished demos.
- After that, the `physics_*_demo.py` scripts are good "next-step" reading,
  because every one of them factors its scene into a `_build_world()` /
  `run_demo()` pair that you can copy and modify.
