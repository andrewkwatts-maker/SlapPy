# Rust Bypass Guide — 2026-07-05 (II1, HH8 follow-up)

**Status**: shipped. Companion to `python/slappyengine/_core_facade.py`
(HH8, which landed the facade module) and
`SlapPyEngineTests/tests/test_rust_bypass.py` (which pins the surface).

Cross-reference: `docs/rust_migration_audit_2026_07_05.md` (FF4) for the
full 53-symbol shipping-wheel inventory this guide is derived from.

---

## 1. Preamble — why the bypass matters

The 2026-07-05 user directive is verbatim:

> "ensure framework is PY PYPI Lib, wrapping a Rust Accellerated backend,
>  users should be able to bypass the py lib if they want."

The Python package `slappyengine` is a **user-facing ergonomics layer**.
Every per-frame kernel — softbody projection, PBF neighbour lookup,
raster line drawing, IK solve, LZ4 compress — lives inside the compiled
PyO3 extension `slappyengine._core` (built from `src/*.rs` by `maturin`).

The Python wrappers exist for three reasons:

1. **Config plumbing** — YAML defaults, dataclass validation, sensible
   error messages.
2. **Object identity** — persistent handles / caches / lifecycle hooks
   that a bare kernel call would otherwise recompute per frame.
3. **Fallback** — pure-numpy path so headless CI can run without the
   compiled `.pyd`.

None of these three add per-frame value for a user who already has a
tight compute loop of their own. The bypass exists so power users can:

* **Skip the wrapper cost** — call the Rust kernel directly on numpy
  arrays or bytes without allocating a `SoftbodyWorld` first.
* **Build custom pipelines** — chain `_core.rasterize_lines` →
  `_core.box_blur_rgb` → `_core.post_process_rgb` without the
  `slappyengine.softbody.render.render_softbody_scene` orchestrator.
* **Host integration** — embed the fast paths inside a game engine that
  already has its own scene graph, camera, and asset pipeline. Only the
  Rust kernels need to be reachable; the Python surface is not.
* **Benchmarking / profiling** — measure the raw kernel cost without
  wrapper-side dataclass construction, YAML parsing, and validation.

The rule of thumb this doc pins down: **if a user can write the
equivalent Python one-liner, they can also write the equivalent
`_core.<module>.<fn>` one-liner and skip the wrapper entirely.**

---

## 2. The wrapper/backend split

```
   +----------------------------------------------------------------+
   |                       user code                                |
   +---------------------------+------------------------------------+
                               |
             +-----------------+-------------------+
             |                                     |
             v                                     v
   +--------------------+                +----------------------+
   |  ergonomics /      |                |  direct-bypass path  |
   |  wrapper stack     |                |  (this document)     |
   |                    |                |                      |
   |  slappyengine.*    |                |  slappyengine._core  |
   |    App, Scene,     |                |    hull.convex_hull  |
   |    Renderer,       |                |    ik_solver.solve_ik|
   |    SoftbodyWorld,  |                |    raster.rasterize_ |
   |    FluidWorld,     |                |      lines           |
   |    studio, etc.    |                |    ...               |
   +---------+----------+                +----------+-----------+
             |                                      |
             |  (wrappers dispatch to _core         |
             |   via HAS_NATIVE_X gates)            |
             |                                      |
             +--------------+-----------------------+
                            |
                            v
   +----------------------------------------------------------------+
   |             slappyengine._core  (PyO3 extension)               |
   |                                                                |
   |   compiled from src/*.rs by maturin — one flat namespace       |
   |   grouped by _core_facade.RUST_MODULE_MAP into logical         |
   |   sub-modules matching the src/ file layout                    |
   +---------------------------+------------------------------------+
                               |
                               v
                     rayon / SIMD / etc.
```

`_core_facade.py` (HH8) is the **thin glue** that:

1. Soft-imports `_core` and exposes `has_native()`.
2. Publishes `RUST_MODULE_MAP` — the authoritative "which flat symbol
   belongs to which Rust source file" table.
3. Registers synthetic sub-module views under
   `sys.modules['slappyengine._core.<name>']` so users can write
   `from slappyengine._core import raster` and get exactly the symbols
   that came out of `src/raster.rs`.
4. Installs `_NullCore` as a fallback attribute-access stub when the
   `.pyd` didn't build (headless CI, source install without maturin).

Users do not have to know that the compiled `_core` is actually flat —
the sub-module views make the Rust source layout browsable directly
from Python.

---

## 3. `_core` module surface

Each subsection below covers one Rust source file. The source-file
line numbers were verified against `src/*.rs` on 2026-07-05.

### 3.1 `hull` — 2-D convex hull, bbox, pixel edge sampling

* **Purpose**: 2-D convex hull (Andrew's monotone chain), axis-aligned
  bounding box, and pixel-mask edge-point extraction.
* **Rust source**: `src/hull.rs`.
* **Python wrapper**: `slappyengine/compute/spatial.py`,
  `slappyengine/bvh_factory.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `convex_hull` | pyfunction | `src/hull.rs:6` |
| `bounding_box` | pyfunction | `src/hull.rs:53` |
| `pixel_edge_points` | pyfunction | `src/hull.rs:91` |

**Bypass example**:

```python
from slappyengine import _core_facade  # ensures sub-module views installed
from slappyengine._core import hull

pts = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.5, 0.5)]
hull_pts = hull.convex_hull(pts)                        # -> [(0,0),(1,0),(1,1),(0,1)]
xmin, ymin, xmax, ymax = hull.bounding_box(pts)        # -> (0.0, 0.0, 1.0, 1.0)
```

### 3.2 `ik_solver` — 2-D FABRIK IK

* **Purpose**: FABRIK forward/backward reach IK for 2-D chains.
* **Rust source**: `src/ik_solver.rs`.
* **Python wrapper**: `slappyengine/animation/procedural.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `solve_ik` | pyfunction | `src/ik_solver.rs:58` |
| `compute_bone_lengths` | pyfunction | `src/ik_solver.rs:131` |

**Bypass example**:

```python
from slappyengine import _core_facade
from slappyengine._core import ik_solver

bones = [(0.0, 0.0), (1.0, 0.0), (2.0, 0.0), (3.0, 0.0)]
lengths = ik_solver.compute_bone_lengths(bones)         # -> [1.0, 1.0, 1.0]
solved = ik_solver.solve_ik(bones, (2.0, 1.5), lengths, iterations=10, tolerance=1e-3)
```

### 3.3 `math` — 2-D primitives

* **Purpose**: `Vec2` and `AABB` pyclasses used across the 2-D pipeline.
* **Rust source**: `src/math.rs`.
* **Python wrapper**: `slappyengine/compute/pipeline.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `Vec2` | pyclass | `src/math.rs:5` |
| `AABB` | pyclass | `src/math.rs:62` |

**Bypass example**:

```python
from slappyengine._core import math as core_math
v = core_math.Vec2(1.0, 2.0)
box = core_math.AABB(0.0, 0.0, 10.0, 10.0)
```

### 3.4 `node_compiler` — material graph → WGSL

* **Purpose**: Compile a JSON material node graph (nodes + edges) to a
  WGSL fragment shader.
* **Rust source**: `src/node_compiler.rs`.
* **Python wrapper**: `slappyengine/material/node_material.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `compile_node_graph` | pyfunction | `src/node_compiler.rs:273` |

**Bypass example**:

```python
from slappyengine._core import node_compiler
wgsl = node_compiler.compile_node_graph(json_str)
```

### 3.5 `slap_format` — LZ4 for `.slap` containers

* **Purpose**: Raw LZ4 block compress/decompress for the `.slap` asset
  container format.
* **Rust source**: `src/slap_format.rs`.
* **Python wrapper**: `slappyengine/landscape.py`, `slappyengine/assets/`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `lz4_compress` | pyfunction | `src/slap_format.rs:7` |
| `lz4_decompress` | pyfunction | `src/slap_format.rs:15` |

**Bypass example**:

```python
from slappyengine._core import slap_format
blob = slap_format.lz4_compress(raw_bytes)
back = slap_format.lz4_decompress(blob)
assert back == raw_bytes
```

### 3.6 `struct_layout` — WGSL struct layout + codegen

* **Purpose**: Compute WGSL struct offsets/alignments; emit WGSL struct
  declarations from `(name, type)` channel lists.
* **Rust source**: `src/struct_layout.rs`.
* **Python wrapper**: `slappyengine/struct_registry.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `compute_layout` | pyfunction | `src/struct_layout.rs:21` |
| `generate_wgsl_struct` | pyfunction | `src/struct_layout.rs:47` |

**Bypass example**:

```python
from slappyengine._core import struct_layout
offsets = struct_layout.compute_layout([("pos", "vec3f"), ("uv", "vec2f")])
decl = struct_layout.generate_wgsl_struct("Vertex", [("pos", "vec3f"), ("uv", "vec2f")])
```

### 3.7 `tile_cache` — LRU landscape tile cache

* **Purpose**: LRU cache for streamed landscape tiles keyed by
  `(chunk_x, chunk_y, lod)`.
* **Rust source**: `src/tile_cache.rs`.
* **Python wrapper**: `slappyengine/landscape.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `TileCache` | pyclass | `src/tile_cache.rs:5` |

**Bypass example**:

```python
from slappyengine._core import tile_cache
cache = tile_cache.TileCache(capacity=64)
```

### 3.8 `physics` — 3-D rigid-body world

* **Purpose**: Minimal 3-D rigid-body integrator; used behind
  `physics2/` for demos and rig scene tests.
* **Rust source**: `src/physics.rs`.
* **Python wrapper**: `slappyengine/physics2/` package.

| Symbol | Kind | Rust source line |
|---|---|---|
| `BodyType` | pyclass (eq, eq_int) | `src/physics.rs:10` |
| `RigidBody` | pyclass | `src/physics.rs:89` |
| `PhysicsWorld` | pyclass | `src/physics.rs:236` |

**Bypass example**:

```python
from slappyengine._core import physics
world = physics.PhysicsWorld()
world.set_gravity(0.0, -9.81, 0.0)
body = physics.RigidBody(mass=1.0)
handle = world.add_body(body)
for _ in range(60):
    contacts = world.step(1.0 / 60.0)
```

### 3.9 `sdf_collision` — 3-D SDF push-out queries

* **Purpose**: Load a serialised SDF scene and answer distance / normal
  / push-out queries.
* **Rust source**: `src/sdf_collision.rs`.
* **Python wrapper**: `slappyengine/bvh_factory.py`,
  `slappyengine/sdf_shapes.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `SdfCollider` | pyclass | `src/sdf_collision.rs:252` |

**Bypass example**:

```python
from slappyengine._core import sdf_collision
collider = sdf_collision.SdfCollider()
collider.load_bytes(scene_blob)
d = collider.distance(0.0, 1.0, 0.0)
nx, ny, nz = collider.normal(0.0, 1.0, 0.0)
```

### 3.10 `math_3d` — 3-D primitives (feature = `3d`)

* **Purpose**: `Vec3`, `Vec4`, `Mat4x4`, `Quaternion` — the 3-D pipeline
  primitives.
* **Rust source**: `src/math_3d.rs` (`#[cfg(feature = "3d")]`).
* **Python wrapper**: 3-D camera / scene helpers.

| Symbol | Kind | Rust source line |
|---|---|---|
| `Vec3` | pyclass | `src/math_3d.rs:11` |
| `Vec4` | pyclass | `src/math_3d.rs:111` |
| `Mat4x4` | pyclass | `src/math_3d.rs:168` |
| `Quaternion` | pyclass | `src/math_3d.rs:299` |

**Bypass example**:

```python
from slappyengine._core import math_3d
q = math_3d.Quaternion.from_axis_angle(math_3d.Vec3(0.0, 1.0, 0.0), 3.14159 / 2.0)
m = math_3d.Mat4x4.from_rotation(q)
p = m.transform_point(math_3d.Vec3(1.0, 0.0, 0.0))
```

### 3.11 `bvh` — 3-D BVH build + query (feature = `3d`)

* **Purpose**: 3-D BVH build and ray / sphere / AABB queries. Backs the
  3-D scene raycaster.
* **Rust source**: `src/bvh.rs` (`#[cfg(feature = "3d")]`).
* **Python wrapper**: `slappyengine/bvh_factory.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `BvhPrimitive` | pyclass | `src/bvh.rs:129` |
| `Bvh` | pyclass | `src/bvh.rs:145` (Rust name `BVH`) |

Note: the audit doc uses `Bvh` (Python-facing name from the `#[pyclass]`
attribute). The Rust struct is named `BVH`. Users import `Bvh`.

### 3.12 `sdf` — 3-D SDF scene primitives (feature = `3d`)

* **Purpose**: Build an SDF scene (sphere, box, cylinder, capsule,
  cone, torus, plane, rounded_box) and serialise it for GPU upload.
* **Rust source**: `src/sdf.rs` (`#[cfg(feature = "3d")]`).
* **Python wrapper**: `slappyengine/bvh_factory.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `SdfPrimitive` | pyclass | `src/sdf.rs:71` |
| `SdfScene` | pyclass | `src/sdf.rs:221` |

**Bypass example**:

```python
from slappyengine._core import sdf as core_sdf
scene = core_sdf.SdfScene()
scene.add(core_sdf.SdfPrimitive.sphere(0.0, 0.0, 0.0, 1.0))
scene.add(core_sdf.SdfPrimitive.box_(2.0, 0.0, 0.0, 0.5, 0.5, 0.5))
blob = scene.to_gpu_bytes()
```

### 3.13 `gi` — radiance cascade bookkeeping (feature = `gi`)

* **Purpose**: Cascade level descriptors + probe-texture sizing for the
  radiance-cascade GI pipeline. All heavy work runs in WGSL; this is
  bookkeeping only.
* **Rust source**: `src/gi.rs` (`#[cfg(feature = "gi")]`).
* **Python wrapper**: `slappyengine/gi/cascade.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `RadianceCascadeManager` | pyclass | `src/gi.rs:34` |

### 3.14 `ibl` — IBL SH probe (feature = `ibl`)

* **Purpose**: Project an HDR equirectangular image to 9 × RGB SH L2
  coefficients ready for GPU upload.
* **Rust source**: `src/ibl.rs` (`#[cfg(feature = "ibl")]`).
* **Python wrapper**: `slappyengine/lighting.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `IblSH` | pyclass | `src/ibl.rs:99` |

### 3.15 `raster` — 2-D CPU raster kernels (orphan)

* **Purpose**: Line / disk rasterisation, box blur, alpha-composite,
  post-process (LUT, chromatic aberration), textured triangles. Backs
  both softbody and fluid renderers.
* **Rust source**: `src/raster.rs`.
* **Python wrapper**: `slappyengine/softbody/render.py`,
  `slappyengine/fluid/render.py`.
* **Orphan status**: not `mod`-declared in `src/lib.rs` — see
  `docs/rust_migration_audit_2026_07_05.md` §1.2. Present in wheels
  built from working trees where the mod-decl was in place; absent
  from a clean rebuild of the current commit. `_core_facade.list_rust_functions()`
  therefore returns entries here only if the shipping `.pyd` was
  baked with those symbols.

| Symbol | Kind | Rust source line |
|---|---|---|
| `rasterize_lines` | pyfunction | `src/raster.rs:97` |
| `rasterize_circles` | pyfunction | `src/raster.rs:247` |
| `box_blur_rgb` | pyfunction | `src/raster.rs:311` |
| `alpha_composite_rgb` | pyfunction | `src/raster.rs:442` |
| `post_process_rgb` | pyfunction | `src/raster.rs:502` |
| `rasterize_textured_triangles` | pyfunction | `src/raster.rs:741` |

**Bypass example** (when the wheel was built with the orphan
mod-decls):

```python
from slappyengine import _core_facade
if _core_facade.has_native() and "raster" in _core_facade.list_rust_functions():
    from slappyengine._core import raster
    out = bytearray(w * h * 3)
    raster.rasterize_lines(out, w, h, lines_bytes, colors_bytes, thicknesses_bytes)
    raster.box_blur_rgb(out, w, h, radius=2)
```

### 3.16 `softbody_solver` — XPBD inner kernels (orphan)

* **Purpose**: XPBD distance-constraint projection, plasticity,
  break-marking, contact broadphase, node-beam / node-node contact
  projection, full step. Same orphan-status caveat as `raster`.
* **Rust source**: `src/softbody_solver.rs`.
* **Python wrapper**: `slappyengine/softbody/solver.py`,
  `slappyengine/softbody/collision.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `project_distance_constraints` | pyfunction | `src/softbody_solver.rs:118` |
| `apply_plasticity` | pyfunction | `src/softbody_solver.rs:295` |
| `mark_breaks` | pyfunction | `src/softbody_solver.rs:385` |
| `build_contact_pairs` | pyfunction | `src/softbody_solver.rs:495` |
| `project_node_beam_contacts` | pyfunction | `src/softbody_solver.rs:844` |
| `project_node_node_pairs` | pyfunction | `src/softbody_solver.rs:1138` |
| `slappyengine_step` | pyfunction | `src/softbody_solver.rs:1954` |

### 3.17 `pbf_solver` — PBF inner kernels (orphan)

* **Purpose**: PBF neighbour-table build, density solve iteration,
  friction pass, thermal step, full step. Same orphan-status caveat.
* **Rust source**: `src/pbf_solver.rs`.
* **Python wrapper**: `slappyengine/fluid/solver.py`,
  `slappyengine/fluid/thermal_step.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `build_neighbour_table` | pyfunction | `src/pbf_solver.rs:73` |
| `pbf_iter` | pyfunction | `src/pbf_solver.rs:246` |
| `friction_pass_rs` | pyfunction | `src/pbf_solver.rs:531` |
| `thermal_step_rs` | pyfunction | `src/pbf_solver.rs:679` |
| `pbf_step_full` | pyfunction | `src/pbf_solver.rs:1324` |

### 3.18 `fluid_shader` — HDR fluid post-process (orphan)

* **Purpose**: HDR fluid surface polish passes — turbulence foam,
  refraction warp, godrays, specular, droplet tails, HDR alpha
  composite / post-process / line raster, base shading, speed screen,
  density-grid sampling, marching-squares isoline extraction. Same
  orphan-status caveat.
* **Rust source**: `src/fluid_shader.rs`.
* **Python wrapper**: `slappyengine/fluid/render.py`,
  `slappyengine/fluid/surface.py`.

| Symbol | Kind | Rust source line |
|---|---|---|
| `turbulence_foam_rs` | pyfunction | `src/fluid_shader.rs:71` |
| `refraction_warp_rs` | pyfunction | `src/fluid_shader.rs:128` |
| `godrays_rs` | pyfunction | `src/fluid_shader.rs:218` |
| `specular_pass_rs` | pyfunction | `src/fluid_shader.rs:298` |
| `draw_droplet_tails_rs` | pyfunction | `src/fluid_shader.rs:474` |
| `alpha_composite_hdr_rs` | pyfunction | `src/fluid_shader.rs:545` |
| `post_process_hdr_rs` | pyfunction | `src/fluid_shader.rs:591` |
| `rasterize_lines_hdr_rs` | pyfunction | `src/fluid_shader.rs:697` |
| `surface_base_shade_rs` | pyfunction | `src/fluid_shader.rs:763` |
| `speed_screen_rs` | pyfunction | `src/fluid_shader.rs:986` |
| `sample_density_grid_rs` | pyfunction | `src/fluid_shader.rs:1062` |
| `extract_isolines_rs` | pyfunction | `src/fluid_shader.rs:1230` |

---

## 4. When to use the bypass

The bypass path is the right call when any of the following apply:

* **Perf-critical inner loop** where the wrapper's dataclass /
  validation / YAML overhead becomes measurable (>1% of frame budget).
* **Custom render pipeline** — you're composing raster / blur /
  composite passes in an order the shipped `render.py` doesn't produce.
* **Host integration** — you're embedding `slappyengine` inside another
  engine that owns scene, camera, and asset loading. You want the fast
  kernels, not the wrapper's scene graph.
* **Batch offline processing** — running IK on 100 000 poses in a
  script; the per-call wrapper overhead dominates.
* **Benchmarking a kernel in isolation** — reproducing perf numbers
  from `benchmarks/baseline_report.md` without wrapper-side variance.
* **Language-neutral pipeline** — you're driving `_core` from a Rust
  binary or a C++ host that loads the `.pyd` through the CPython C API,
  and the Python wrapper never runs.
* **Feature-flagged build target** — you built the wheel with
  `--features 3d,gi,ibl` and want the direct handle to the 3-D / GI
  bookkeeping structs without the wrapper's numpy fallback path
  probing.

## 5. When NOT to use the bypass

The wrapper path is the right call when any of the following apply:

* **Standard scene / demo development** — the wrapper does the right
  thing and is measurably cheaper to write.
* **You need the numpy fallback** — headless CI without a compiled
  `.pyd` requires the Python fallback path; direct `_core` calls will
  hit `_NullCoreError`.
* **You care about lifetime / cache reuse** — the wrapper caches
  broadphase grids, neighbour tables, and shader-module handles across
  frames. Calling the kernel directly means paying the setup cost every
  call.
* **You care about determinism across float precision changes** — the
  wrapper enforces the f64-accumulator + input-order-scatter rules
  (see `project_architecture_pattern.md` "precision gotchas"). Rolling
  your own bypass loop can regress
  `test_block_on_block_stacks` or `test_block_buries_in_sand`.
* **You need argument validation / friendly errors** — the wrapper
  raises `TypeError`/`ValueError` on bad inputs. `_core` kernels crash
  or return garbage on malformed buffers.
* **You want the studio / scene / editor tooling** — the direct-bypass
  path skips the studio scaffolding, undo stack, autosave, and
  visual-scripting graph entirely.

## 6. Pattern for adding a new Rust function

Distilled from `project_architecture_pattern.md`. Every new kernel
follows the same five-step lifecycle:

1. **Prototype in numpy/Python.** Get the algorithm correct against a
   pinned test scene in the numpy path. Don't optimise yet.
2. **Port to Rust the moment it's correct.** Write the `#[pyfunction]`
   in a `src/<name>.rs`, `mod`-declare it in `src/lib.rs`,
   `register(m)` in the module block. Follow the buffer-protocol
   pattern: `PyReadonlyArray*` / `&[u8]` in, `Vec<f32>` / `PyByteArray`
   out. Preserve f64 accumulators where numpy uses `float64`.
3. **Wrap with a `HAS_NATIVE_X` switch.** In the Python wrapper, gate
   the fast path behind `try: from slappyengine import _core;
   HAS_NATIVE_X = True except ImportError: HAS_NATIVE_X = False`.
   Keep the numpy fallback for CI without the `.pyd`.
4. **Add a regression test that the two paths agree.** Same input,
   compare within `atol=1e-3` (position scatter, softbody stack) or
   `atol=1e-6` (pure math kernels). Land the test in the same commit
   as the port.
5. **Document the bypass call.** Add a new subsection to §3 above with
   the source-line-verified inventory and a bypass example. Add the
   symbol to `RUST_MODULE_MAP` in `_core_facade.py` so
   `list_rust_functions` picks it up. Add a targeted case to
   `test_rust_bypass.py::test_facade_has_all_documented_modules`.

The precision-gotcha rules from
`project_architecture_pattern.md` §"Precision gotchas already learned"
are load-bearing on **every** port, including one that just wraps an
existing numpy call. Read them before touching a solver kernel.

## 7. Full inventory table

Every Rust `#[pyfunction]` + `#[pyclass]` reachable in a fully
feature-flagged wheel build (`--features 3d,gi,ibl` on the current
tree, with the `src/lib.rs` mod-decls patched to include the four
orphan modules — see FF4 §1.2).

| Module | Symbol | Kind | Source |
|---|---|---|---|
| hull | convex_hull | pyfunction | `src/hull.rs:6` |
| hull | bounding_box | pyfunction | `src/hull.rs:53` |
| hull | pixel_edge_points | pyfunction | `src/hull.rs:91` |
| ik_solver | solve_ik | pyfunction | `src/ik_solver.rs:58` |
| ik_solver | compute_bone_lengths | pyfunction | `src/ik_solver.rs:131` |
| math | Vec2 | pyclass | `src/math.rs:5` |
| math | AABB | pyclass | `src/math.rs:62` |
| node_compiler | compile_node_graph | pyfunction | `src/node_compiler.rs:273` |
| slap_format | lz4_compress | pyfunction | `src/slap_format.rs:7` |
| slap_format | lz4_decompress | pyfunction | `src/slap_format.rs:15` |
| struct_layout | compute_layout | pyfunction | `src/struct_layout.rs:21` |
| struct_layout | generate_wgsl_struct | pyfunction | `src/struct_layout.rs:47` |
| tile_cache | TileCache | pyclass | `src/tile_cache.rs:5` |
| physics | BodyType | pyclass | `src/physics.rs:10` |
| physics | RigidBody | pyclass | `src/physics.rs:89` |
| physics | PhysicsWorld | pyclass | `src/physics.rs:236` |
| sdf_collision | SdfCollider | pyclass | `src/sdf_collision.rs:252` |
| math_3d | Vec3 | pyclass (feat 3d) | `src/math_3d.rs:11` |
| math_3d | Vec4 | pyclass (feat 3d) | `src/math_3d.rs:111` |
| math_3d | Mat4x4 | pyclass (feat 3d) | `src/math_3d.rs:168` |
| math_3d | Quaternion | pyclass (feat 3d) | `src/math_3d.rs:299` |
| sdf | SdfPrimitive | pyclass (feat 3d) | `src/sdf.rs:71` |
| sdf | SdfScene | pyclass (feat 3d) | `src/sdf.rs:221` |
| gi | RadianceCascadeManager | pyclass (feat gi) | `src/gi.rs:34` |
| ibl | IblSH | pyclass (feat ibl) | `src/ibl.rs:99` |
| raster | rasterize_lines | pyfunction (orphan) | `src/raster.rs:97` |
| raster | rasterize_circles | pyfunction (orphan) | `src/raster.rs:247` |
| raster | box_blur_rgb | pyfunction (orphan) | `src/raster.rs:311` |
| raster | alpha_composite_rgb | pyfunction (orphan) | `src/raster.rs:442` |
| raster | post_process_rgb | pyfunction (orphan) | `src/raster.rs:502` |
| raster | rasterize_textured_triangles | pyfunction (orphan) | `src/raster.rs:741` |
| softbody_solver | project_distance_constraints | pyfunction (orphan) | `src/softbody_solver.rs:118` |
| softbody_solver | apply_plasticity | pyfunction (orphan) | `src/softbody_solver.rs:295` |
| softbody_solver | mark_breaks | pyfunction (orphan) | `src/softbody_solver.rs:385` |
| softbody_solver | build_contact_pairs | pyfunction (orphan) | `src/softbody_solver.rs:495` |
| softbody_solver | project_node_beam_contacts | pyfunction (orphan) | `src/softbody_solver.rs:844` |
| softbody_solver | project_node_node_pairs | pyfunction (orphan) | `src/softbody_solver.rs:1138` |
| softbody_solver | slappyengine_step | pyfunction (orphan) | `src/softbody_solver.rs:1954` |
| pbf_solver | build_neighbour_table | pyfunction (orphan) | `src/pbf_solver.rs:73` |
| pbf_solver | pbf_iter | pyfunction (orphan) | `src/pbf_solver.rs:246` |
| pbf_solver | friction_pass_rs | pyfunction (orphan) | `src/pbf_solver.rs:531` |
| pbf_solver | thermal_step_rs | pyfunction (orphan) | `src/pbf_solver.rs:679` |
| pbf_solver | pbf_step_full | pyfunction (orphan) | `src/pbf_solver.rs:1324` |
| fluid_shader | turbulence_foam_rs | pyfunction (orphan) | `src/fluid_shader.rs:71` |
| fluid_shader | refraction_warp_rs | pyfunction (orphan) | `src/fluid_shader.rs:128` |
| fluid_shader | godrays_rs | pyfunction (orphan) | `src/fluid_shader.rs:218` |
| fluid_shader | specular_pass_rs | pyfunction (orphan) | `src/fluid_shader.rs:298` |
| fluid_shader | draw_droplet_tails_rs | pyfunction (orphan) | `src/fluid_shader.rs:474` |
| fluid_shader | alpha_composite_hdr_rs | pyfunction (orphan) | `src/fluid_shader.rs:545` |
| fluid_shader | post_process_hdr_rs | pyfunction (orphan) | `src/fluid_shader.rs:591` |
| fluid_shader | rasterize_lines_hdr_rs | pyfunction (orphan) | `src/fluid_shader.rs:697` |
| fluid_shader | surface_base_shade_rs | pyfunction (orphan) | `src/fluid_shader.rs:763` |
| fluid_shader | speed_screen_rs | pyfunction (orphan) | `src/fluid_shader.rs:986` |
| fluid_shader | sample_density_grid_rs | pyfunction (orphan) | `src/fluid_shader.rs:1062` |
| fluid_shader | extract_isolines_rs | pyfunction (orphan) | `src/fluid_shader.rs:1230` |

**Totals**: 18 Rust source files (17 kernel files + `lib.rs`), 18
logical `RUST_MODULE_MAP` entries, **55 documented public symbols**
(41 `#[pyfunction]` + 14 `#[pyclass]`).

## 8. Testing

`SlapPyEngineTests/tests/test_rust_bypass.py` pins the bypass surface.
The suite is deliberately soft on the compiled `.pyd`: every test that
depends on the extension being built calls
`pytest.importorskip("slappyengine._core")` (or checks
`_core_facade.has_native()`) so headless CI without maturin still
returns green.

Coverage:

* **Facade contract** — `has_native()` returns a bool;
  `list_rust_functions()` returns a `dict[str, list[str]]`;
  `RUST_MODULE_MAP` is non-empty and every entry has the required
  `src` / `symbols` / `summary` keys.
* **Sub-module view registration** — for every module present at
  runtime, `slappyengine._core.<name>` resolves via
  `importlib.import_module` and exposes exactly the symbols
  `RUST_MODULE_MAP` promises.
* **Null-core stub semantics** — `_NullCore.<anything>` raises
  `RuntimeError` with a message pointing at the maturin build command.
* **Bypass matches wrapper** — for a stable pair (`hull.convex_hull`
  vs a numpy scipy-style reference), the two paths agree.
* **Doc / audit cross-check** — every module named in this doc §3 is
  present in `RUST_MODULE_MAP`; every module in `RUST_MODULE_MAP`
  points at a real `src/*.rs` file.
* **Directory hygiene** — every `src/*.rs` (except `lib.rs` and
  `math.rs`-style pure-math helpers) is represented in
  `RUST_MODULE_MAP`.

Run:

```
pytest SlapPyEngineTests/tests/test_rust_bypass.py -v
```

Skips expected when the `.pyd` is missing (5-6 tests). All other
tests remain hard assertions on the doc / facade contract.

---

## 9. Cross-references

* `python/slappyengine/_core_facade.py` — HH8, the facade module.
* `docs/rust_migration_audit_2026_07_05.md` — FF4, the shipping-wheel
  inventory this guide is derived from.
* `docs/rust_migration_plan.md` — original 7-step Rust plan.
* `docs/rust_port_audit_2026_06_02.md` — prior per-frame audit.
* Memory: `project_architecture_pattern.md` — the binding "Python is a
  wrapper on Rust for PyPI shipping" directive (last reinforced
  2026-07-05).
* Memory: `project_rust_migration_final_2026_05_26.md` — 18-kernel
  rollup at end of May.
