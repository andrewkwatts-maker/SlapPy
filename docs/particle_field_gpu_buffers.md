# ParticleField GPU Buffer Layout

Design document for the upcoming GPU compute port of
`slappyengine.physics.particle_field.ParticleField`. Covers std430 storage
buffer layouts for the per-particle SoA, 2D textures for the per-pixel state,
growth + readback strategies, workgroup sizing, and a migration order.

This is a **design** doc — no code is committed against it yet. The shape of
each buffer is dictated by the existing CPU SoA on `ParticleField`
(see `python/slappyengine/physics/particle_field.py`, `__post_init__` at line
482) and the lazy-loaded `slappyengine.compute` API
(`ComputePipeline`, `ReadbackBuffer`, etc.).

---

## 1. Per-particle storage buffer layout

WGSL `std430` rules apply: scalars align to their size, `vec2<f32>` aligns
to 8, `vec3<u8>` is not a thing (use a packed `u32` for colour), structs pad
to their largest member. All buffers below are `array<T>` so the std430
struct-padding rule does not apply — only element alignment matters.

| binding | name             | WGSL type          | bytes/particle | notes |
|---------|------------------|--------------------|----------------|-------|
| 0       | `pos`            | `array<vec2<f32>>` | 8              | hot — read by integrate, collide, bake; align 8 |
| 1       | `vel`            | `array<vec2<f32>>` | 8              | hot — read by integrate, collide, slump |
| 2       | `phase_packed`   | `array<u32>`       | 4              | bits 0-7 phase (i8), 8-31 phase_age (24-bit signed); see §1.1 |
| 3       | `material_id`    | `array<i32>`       | 4              | indexed into material LUT uniform; cold-ish |
| 4       | `radius`         | `array<f32>`       | 4              | airborne render radius |
| 5       | `bake_radius`    | `array<i32>`       | 4              | settle stamp radius (0=1px, 1=3x3, ...) |
| 6       | `color_rgba`     | `array<u32>`       | 4              | rgba8 packed (a=255); CPU `color` is `(N,3) u8` |
| 7       | `shape_idx`      | `array<i32>`       | 4              | fragment family index — bake-time only |
| 8       | `shape_rotation` | `array<f32>`       | 4              | radians; bake-time only |
| 9       | `kinetic_age`    | `array<i32>`       | 4              | frames since spawn (rigidify timer) |
| 10      | `rigidify_at`    | `array<i32>`       | 4              | per-particle rigidify threshold |
| 11      | `settle_age`     | `array<i32>`       | 4              | frames since first settled (gates bake) |
| 12      | `impact_vel`     | `array<vec2<f32>>` | 8              | velocity at landing — drives splat |
| 13      | `temperature`    | `array<f32>`       | 4              | °C; relaxed each step; thermal-driven phase change |

**Total: 68 bytes / particle** packed across 14 buffers (one per SoA).

### 1.1 Packing rationale

Three packing decisions to highlight:

- **`phase` + `phase_age` → one u32.** Phase is an `IntEnum` with 4 values
  (AIRBORNE / LANDED / SETTLING / BAKED) — 2 bits would suffice, 8 leaves
  headroom. `phase_age` is `int32` on the CPU but only ever increments to a
  few hundred before transitioning, so 24 bits (max ~16M frames at 60 fps =
  3 years) is overkill-safe. Packing halves the bandwidth for what is the
  single most-frequently-touched state field.
- **`color` → rgba8 u32.** CPU has `(N, 3) uint8` which std430 cannot
  represent natively; promote to packed RGBA8 (alpha=255) and unpack on
  texture write at bake time.
- **`landed` / `settled` / `bake_flag` dropped.** These are derived booleans
  on the CPU (recomputed by `_set_phase`). On GPU, derive them in shader
  from `phase_packed` whenever needed — zero storage cost.

### 1.2 What *not* to keep on the GPU

`_rng` (numpy Generator), `region_grid` (spatial-hash helper), `_name_to_id`,
and the `materials` list are control-plane data. Materials become a small
**uniform buffer** (≤ 64 entries × ~64 bytes per material profile — well
under the 64 KB UBO limit). The fragment-family shape tables can ride on the
material UBO as flat fixed-length arrays. RNG becomes a per-thread
counter-based PCG seeded from `(particle_index, frame)`.

---

## 2. Per-pixel storage texture layout

The four per-pixel fields stay as **2D storage textures** rather than
buffers. They are spatially addressed, get sampled with neighbourhood
stencils (slump pass, fixed-mask carve), and benefit from
hardware-accelerated tiling.

| binding | name            | format       | size          | usage             | notes |
|---------|-----------------|--------------|---------------|-------------------|-------|
| 14      | `mask`          | `rgba8unorm` | W × H         | storage read+write | rgb = colour, a = solid (255 if filled) |
| 15      | `material_grid` | `r8sint`     | W × H         | storage read+write | -1 = empty; matches CPU `int8` |
| 16      | `loose`         | `r8uint`     | W × H         | storage read+write | 0/1 bool; only loose pixels slump |
| 17      | `fixed_mask`    | `r8uint`     | W × H         | storage read+write | 0/1 bool; pinned by `fill_ground` |

Total per-pixel footprint: **7 bytes/pixel** (4 + 1 + 1 + 1).
For a 1920×1080 stage: ~14.5 MB. Negligible vs particle buffer.

Notes:

- `loose` and `fixed_mask` are conceptually 1-bit; `r8uint` is the smallest
  widely-supported storage format. Packing both into a single `r8uint`
  bitfield (bit 0 = loose, bit 1 = fixed) would cut memory by 50 % but
  complicates atomic updates from the bake kernel — defer that micro-opt.
- `material_grid` as `r8sint` is exact-fit; -1 sentinel survives.
- `mask` keeps alpha as a binary solid flag so the existing renderer paths
  (which sample mask.a) work unchanged.

---

## 3. Growth strategy

`spawn_batch` is the hot path during explosions. CPU side it currently does
`np.concatenate` per field — a full O(N) realloc on every batch. On the GPU,
we cannot afford a `create_buffer` + copy per spawn.

**Plan: pre-allocated capacity with high-water mark.**

- Allocate every per-particle buffer at `capacity = max_particles`
  (default **131,072** — fits 100 k headroom with one geometric growth left).
- Maintain a **uniform** `particle_count: u32` that all kernels read.
  Particles `[count, capacity)` are dead — kernels short-circuit if their
  `gid >= count`.
- `spawn_batch(n)` becomes:
  1. CPU stages `n` particles in a small ring-buffer in pinned host memory
     (one upload buffer per field).
  2. Single `queue.writeBuffer` (or `copyBufferToBuffer` from a staging
     buffer) into each field at byte offset `count * bytes_per_particle`.
  3. CPU bumps `count += n`, re-uploads the count uniform.
- **Overflow:** if `count + n > capacity`, double capacity. This requires
  destroy/create on every per-particle buffer and a full GPU copy of the
  live region — costly but rare. Log a warning so users tune
  `max_particles`.
- **Compaction:** once `BAKED` particles accumulate, the live region gets
  sparse. Run a **stream-compaction pass** (prefix-sum of `phase != BAKED`)
  every N frames (N≈600 / 10s @ 60 fps) to reclaim slots. This avoids
  unbounded growth in long sessions.

Upload bandwidth budget at 60 fps spawning 10k particles/frame:
10 000 × 68 B = 680 KB/frame = 41 MB/s. Well within PCIe x16.

---

## 4. Readback strategy and bake-on-GPU

### 4.1 The readback bottleneck

The CPU `bake_settled_particles` pass currently:
1. Identifies particles with `bake_flag == True`.
2. For each, looks up fragment shape + rotation + material colour.
3. Stamps `bake_radius`-sized chunks into `mask`, `material_grid`, `loose`.
4. Flips phase → `BAKED`.

If we leave bake on the CPU, every frame with a non-empty bake set forces a
**round-trip readback** of pos / phase / shape_idx / shape_rotation /
material_id / color / bake_radius — minimum 36 B × N_baking. At even
500 particles/frame that's an 18 KB stall per frame, but the real cost is
the **synchronous map-await** in `ReadbackBuffer.read_from` (already used
by `ComputePipeline.dispatch`). A single readback can cost 1–3 ms on
discrete GPUs because of the round-trip — for a 16.6 ms frame that is 6-18%
of frame time burned on a stall.

### 4.2 Bake-on-GPU path

Keep the data on the GPU and run a `bake.wgsl` compute kernel that:
- One thread per particle, gated on `phase == SETTLING && settle_age >= 3`.
- Looks up shape + rotation from a `fragment_shapes` uniform (constant LUT
  of (offset_x, offset_y) per shape).
- For each pixel in the stamp footprint, performs `atomicMax` on
  `mask.a` to mark solid + `atomicStore` for colour and material id.
- Writes `loose = 1` (atomic OR if we packed loose/fixed together).
- Flips `phase_packed` → BAKED.
- The CPU never sees the per-particle bake data.

Tricky bits:
- Concurrent stamps writing the same pixel — last-writer-wins is fine for
  colour, but `material_grid` should pick the *most recent* (latest spawn).
  Use a per-pixel `frame_idx` atomic guard, or accept non-determinism
  (it's already non-deterministic from numpy iteration order on CPU).
- `loose` / `fixed_mask` interaction: only set `loose = 1` if
  `fixed_mask[xy] == 0`. Read-then-write race is acceptable since
  `fixed_mask` is only mutated by `fill_ground` (CPU command, no concurrent
  GPU writes).

### 4.3 When readback is unavoidable

User-facing API still exposes `mask`, `pos`, etc. as numpy arrays. Keep a
**dirty-region tracker**: only stage a readback when the user actually
accesses `field.mask` (lazy property). For the bake event itself we avoid
readback entirely.

Stats / counts (`particle_count`, `settled_count`) flow through the
existing `StatsCompute` pattern — a single u32 result buffer, ~4 B
readback per query.

---

## 5. Workgroup sizes

| kernel               | dispatch domain  | suggested workgroup | rationale |
|----------------------|------------------|---------------------|-----------|
| `integrate.wgsl`     | per-particle     | `@workgroup_size(64)` | safe default; matches existing `ComputePipeline.dispatch` |
| `collide.wgsl`       | per-particle     | `@workgroup_size(64)` | spatial-hash lookup is divergent; small wg helps |
| `kinetic_relax.wgsl` | per-particle     | `@workgroup_size(64)` | uniform load |
| `bake.wgsl`          | per-particle     | `@workgroup_size(64)` | divergent stamp loop; keep small |
| `slump.wgsl`         | per-pixel        | `@workgroup_size(8, 8)` | 64 threads with 2D locality for neighbour reads |
| `thermal.wgsl`       | per-particle     | `@workgroup_size(64)` | embarrassingly parallel |
| `phase_change.wgsl`  | per-particle     | `@workgroup_size(64)` | reads temperature, writes phase_packed |
| `compact.wgsl`       | per-particle     | `@workgroup_size(256)` | prefix-sum benefits from larger wg |
| `stats.wgsl`         | per-particle     | `@workgroup_size(64)` | matches `health_sum.wgsl` |

64 is the floor for occupancy on most GPUs (one warp/wavefront = 32 or 64).
8×8 is the canonical choice for image kernels — 64 threads, square tile,
good `textureLoad` cache reuse. Larger workgroups (128, 256) only help
for prefix-sum style reductions where shared-memory size matters.

---

## 6. Migration order

Order by **risk × integration cost**, lowest first. Each step keeps the
CPU implementation as the canonical reference; the GPU path is an opt-in
toggle (`use_gpu=True` on `ParticleField`) until parity is proven.

1. **`integrate.wgsl`** — pos/vel/temperature only. Pure stateless math,
   no atomics, no neighbour reads. Easiest to test (compare arrays after
   one step). This is the recommended first kernel.
2. **`thermal.wgsl`** — temperature relax + ambient bleed. Independent of
   integrate; can land in parallel.
3. **`stats.wgsl`** — particle counts, settled count, average temperature.
   Reuses the `StatsCompute` / `health_sum.wgsl` pattern. Low risk; proves
   the per-particle dispatch + readback pipeline.
4. **`phase_change.wgsl`** — temperature-driven material swap (ice→water,
   water→ice, lava→rock). Touches `phase_packed` and `material_id`. Modest
   complexity, easy to verify with thermal regression tests.
5. **`collide.wgsl`** — per-particle mask sampling. Requires the
   per-pixel textures to exist on GPU first. Medium risk: this is where
   numerical drift vs CPU first becomes visible.
6. **`kinetic_relax.wgsl`** — jostling pass for SETTLING particles.
   Reads pos + neighbour pixels; harder to vectorise but no atomics.
7. **`bake.wgsl`** — the centrepiece. Particles → mask stamps with
   atomics. Highest correctness risk (concurrent writes, material priority)
   but largest perf win (eliminates the readback stall described in §4).
8. **`slump.wgsl`** — per-pixel cellular-automaton over `loose` mask.
   Multiple passes per frame; needs ping-pong textures. Highest *complexity*
   risk; do last.
9. **`compact.wgsl`** — stream-compaction of dead particles. Only needed
   once long sessions show fragmentation; ship after all the above.

Each step gates the next only when it shares a buffer. `integrate` and
`thermal` can land in parallel. `bake` blocks `slump` (slump reads `loose`
which `bake` writes). `collide` blocks `kinetic_relax`.

---

## 7. Memory budget summary

For **100 000 particles** on a 1920×1080 stage:

- Per-particle: 68 B × 100 000 = **6.5 MB**
- Per-pixel (4 textures): ~14.5 MB
- Material / shape uniform LUT: < 64 KB
- Spatial-hash buffer (RegionGrid replacement): ~2 MB (estimate, depends
  on cell_size)
- Readback staging ring (1 frame worth): < 1 MB

**Total: ~24 MB** — comfortably within mid-range GPU budgets (Steam
Deck APU has 4 GB shared; even integrated Intel has 256 MB+ reserved).
Pre-allocating to 131 072 capacity raises particle footprint to **8.5 MB**;
total budget **~26 MB**. Both well below targets.

For comparison, the CPU NumPy SoA at 100 k particles is ~6.6 MB live plus
~3× working memory during `np.concatenate` resizes during a heavy spawn —
the GPU path with pre-allocation is actually **less peak memory**.

---

## 8. Open questions for review

- Should fragment shape tables ride on a constant uniform, a storage
  buffer, or be inlined into `bake.wgsl` as `const` arrays? Inline gives
  best perf but locks the shape catalogue at shader compile time.
- Is per-frame stream compaction worth the complexity, or can we live with
  a sparse live region until session length forces a manual reset?
- Spatial hash on GPU: build per-frame with atomic counters, or maintain
  incrementally? Build-from-scratch is simpler and probably fine at 60 fps
  with 100 k particles.
- Do we want async readback (frame N+2 sees frame N data) for user-facing
  numpy mirrors? Probably yes — tests don't need it but interactive editors
  benefit hugely.
