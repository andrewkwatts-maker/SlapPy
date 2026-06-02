<!-- handauthored: do not regenerate -->
# SlapPyEngine Demo Gallery

Curated tour of the engine's flagship runnable demos. Every entry below
is reproducible from a clean clone with `PYTHONPATH=python` and the
exact command shown. Generated artefacts live under
`SlapPyEngineExamples/examples/output/<subdir>/` and are committed alongside this document so
the gallery renders correctly on GitHub and the docs site without a
local engine install.

For the full pass/fail audit of every script in `SlapPyEngineExamples/examples/` (47 demos,
47/47 GREEN as of the v3 audit) see
[`examples_smoke_2026_06_01_v3.md`](examples_smoke_2026_06_01_v3.md).

The artefacts below were refreshed 2026-06-01 against the current
master (engine `0.3.0b0`, Rust kernels live).

## Cinematic table

| Demo | Artefact | One-line |
|---|---|---|
| [Hello Ragdoll](#hello-ragdoll) | `SlapPyEngineExamples/examples/output/ragdoll/hello_ragdoll.gif` | 6-bone ragdoll falls + tumbles on a flat floor; XPBD distance + angular joints. |
| [Hello Studio](#hello-studio) | `SlapPyEngineExamples/examples/output/studio/hello_studio.gif` | 24-node rope hung between two pinned anchors, recorded via the unified `studio.record()` one-liner. |
| [Humanoid Walking](#humanoid-walking) | `SlapPyEngineExamples/examples/output/humanoid/humanoid_walking.gif` | Textured biped strides L→R on a flat floor with 2-bone knee IK foot-plant. |
| [Humanoid IK Terrain](#humanoid-ik-terrain) | `SlapPyEngineExamples/examples/output/humanoid/humanoid_ik_terrain.gif` | Same biped walks across a heightfield while the IK solver keeps feet planted on terrain. |
| [Hello Rope](#hello-rope) | `SlapPyEngineExamples/examples/output/rope/hello_rope.png` | 24-node rope settles into a catenary droop between two pinned anchors (single-frame render). |
| [Hello GI](#hello-gi) | `SlapPyEngineExamples/examples/output/hello_gi/hello_gi.png` | 3-panel showcase: direct only \| radiance cascade + noise \| SVGF-denoised. |

## Hello Ragdoll

**What it shows.** A six-bone humanoid ragdoll (pelvis + spine + head +
arms) constructed via `make_ragdoll(...)` falls under gravity and
settles into a slumped pose on the floor. Every joint is a `JointSpec`
in the XPBD substrate: distance joints lock the bones together,
angular joints clamp the elbows and knees so the limbs don't flip
through themselves. The summary reports the lowest bone Y, the
peak final speed, and confirms `joint_limits_respected` is `True` —
no joint exceeded its configured angular range during the trace.

```
Running:    PYTHONPATH=python python examples/hello_ragdoll.py --frames 180 --render
Reference:  examples/output/ragdoll/hello_ragdoll.gif
What it shows: 6 bones / 11 joints / dt = 1/60 / GIF_FPS = 30.
```

The smoke harness drives this demo with `--frames 5 --no-gif` and
verifies the summary dict. See
[`hello_ragdoll.py`](../SlapPyEngineExamples/examples/hello_ragdoll.py) and the gallery
entry in
[`examples_smoke_2026_06_01_v3.md`](examples_smoke_2026_06_01_v3.md).

## Hello Studio

**What it shows.** The smallest possible end-to-end demo of the unified
`slappyengine.studio` API. A 24-node rope is hung between two pinned
anchors at y = 2.0 m with span 4 m / total length 6 m, then recorded
into a 120-frame GIF with a single `stage.record(out, frames=120,
fps=30)` call. The point is the API surface, not the simulation —
this is the entry point most users will copy-paste when starting a new
project.

```
Running:    PYTHONPATH=python python examples/hello_studio.py
Reference:  examples/output/studio/hello_studio.gif
What it shows: studio.dynamics_stage() + build_rope() + stage.record(...) one-liner.
```

For the full studio surface see
[`api/studio.md`](api/studio.md) and the 5-minute
[`studio_quickstart.md`](studio_quickstart.md).

## Humanoid Walking

**What it shows.** A skeletal biped wrapped in muscle + skin
(`wrap_in_flesh`) strides left to right on a flat floor at
~0.62 u/s. Per frame the pelvis advances at constant x-velocity, the
ankles oscillate fore/back ±0.18 m out of phase (1 s period), and the
pelvis bobs ±0.035 m on a 2× cycloid. The 2-bone knee IK solver
(`place_feet_on_terrain`) keeps the feet planted on the floor. The
texture-deform render path paints `textures/humanoid_character.png`
across the outer silhouette, falling back to wireframe if the texture
fails the paint-coverage smoke check.

```
Running:    PYTHONPATH=python python examples/humanoid_walking_demo.py
Reference:  examples/output/humanoid/humanoid_walking.gif
What it shows: 240 frames @ 30 fps, period = 1 s, speed = 0.62 u/s.
```

## Humanoid IK Terrain

**What it shows.** Same biped as `humanoid_walking_demo`, but the floor
is replaced with a heightfield. The IK solver re-plants the feet on
the local terrain height every frame, so the legs visibly bend and
straighten as the character walks over bumps. Demonstrates the
`solve_ik` / `IKChainSpec(node_indices=...)` API on a softbody-backed
character rather than a rigid skeleton.

```
Running:    PYTHONPATH=python python examples/humanoid_ik_terrain_demo.py --frames 180
Reference:  examples/output/humanoid/humanoid_ik_terrain.gif
What it shows: heightmap traversal + per-frame foot-plant IK.
```

## Hello Rope

**What it shows.** A 24-node rope is pinned at both ends and integrated
for 180 dt=1/60 steps. The midpoint settles into a catenary droop of
~1.92 m (anchor Y = 2.0 m, midpoint Y = 0.08 m) which falls cleanly
inside the analytic [1.0, 3.0] m expected-droop range. The render is
a single PNG of the final frame rather than a GIF — useful as a
correctness sanity check for the XPBD distance-joint solver.

```
Running:    PYTHONPATH=python python examples/hello_rope.py --frames 180 --render --out examples/output/rope/hello_rope.png
Reference:  examples/output/rope/hello_rope.png
What it shows: catenary droop, nodes = 24, anchor y = 2.0, midpoint y ≈ 0.08.
```

## Hello GI

**What it shows.** A small 2D alcove (three walls + floor, open top)
lit by one bright warm point light, rendered as a 3-panel comparison
PNG:

1. **Direct only** — only the point light's direct contribution.
   Walls outside the light's reach are nearly black.
2. **Direct + cascade bounce** — radiance-cascade indirect added.
   Warm side walls bleed red onto the floor, the cool side wall bleeds
   blue onto the opposite wall, ambient occlusion in the corners.
   Noisy (the cascade samples sparsely).
3. **SVGF denoised** — same image after `SVGFDenoiser` smooths it.
   Same energy, ~+15 dB PSNR, soft penumbrae, no fireflies.

Headless-friendly, finishes in <2 s on CPU. This is the canonical
showcase for the GI + SVGF pipeline.

```
Running:    PYTHONPATH=python python examples/hello_gi.py
Reference:  examples/output/hello_gi/hello_gi.png
What it shows: direct | cascade + noise | SVGF-denoised 3-panel composite.
```

## Reproducing the gallery

Every command above is run from the repo root with
`PYTHONPATH=python` and no extra setup. Total wall-clock for the six
refreshes on the reference workstation:

| Demo | Wall | Output bytes |
|---|---|---|
| hello_ragdoll | ~4 s | 265 KB |
| hello_studio | ~3 s | 173 KB |
| humanoid_walking | ~30 s | 1.87 MB |
| humanoid_ik_terrain | ~25 s | 1.18 MB |
| hello_rope | ~1 s | 7 KB |
| hello_gi | ~1 s | 307 KB |

To refresh every artefact in one shot:

```bash
PYTHONPATH=python python examples/hello_ragdoll.py --frames 180 --render
PYTHONPATH=python python examples/hello_studio.py
PYTHONPATH=python python examples/humanoid_walking_demo.py
PYTHONPATH=python python examples/humanoid_ik_terrain_demo.py --frames 180
PYTHONPATH=python python examples/hello_rope.py --frames 180 --render --out examples/output/rope/hello_rope.png
PYTHONPATH=python python examples/hello_gi.py
```

## See also

- [`examples_smoke_2026_06_01_v3.md`](examples_smoke_2026_06_01_v3.md)
  — read-only smoke audit of every `SlapPyEngineExamples/examples/*.py` (47/47 GREEN).
- [`studio_quickstart.md`](studio_quickstart.md) — 5-minute tour of
  the `slappyengine.studio` surface used by `hello_studio`.
- [`getting_started.md`](getting_started.md) — game-dev tutorial that
  builds a runnable mini-game in 15 minutes.
- [`dynamics_quickstart.md`](dynamics_quickstart.md) — 10-minute
  hands-on quick-start for the dynamics primitives backing every
  demo above.
- [`api/dynamics.md`](api/dynamics.md) — auto-generated API surface
  for the `JointSpec` / `RopeSpec` / `RagdollSpec` / `IKChainSpec`
  types referenced throughout this gallery.

The gallery deliberately excludes `softbody_*` and `fluid_*` demos
because their source examples may still depend on uncommitted WIP.
Once that work lands, this gallery will gain entries for the
softbody vehicle obstacle course, the buoyancy demo, and the dam
break / water basin showcases.
