# Tier 11 GPU Compute (wgpu) — discussion document

Per the user's instruction: *"wait on tier 11 until previous are done.
then review the state and discuss before going forward."* This document
captures the state and trade-offs for that decision.

## Where we landed after Tiers 1-10

Engine end-state at the end of the CPU-Rust migration session. All
numbers measured on the dev workstation (Windows, Python 3.13, Rust
release build):

### Small / typical scene (5 lattices 6×6 or 140 fluid particles)
| Pipeline | Time | FPS equivalent |
|---|---:|---:|
| Softbody step | ~1.4 ms | — |
| Softbody render (basic) | ~2.0 ms | 499 |
| Softbody render (texture-deform) | 1.20 ms | 833 |
| **Softbody end-to-end** | **~3.0 ms** | **~333 fps** |
| PBF step | ~0.88 ms | — |
| Fluid render (basic) | 0.53 ms | 1887 |
| Fluid render (watery polish) | 2.30 ms | 435 |
| **Fluid end-to-end (basic)** | ~1.4 ms | ~715 fps |
| **Fluid end-to-end (watery polish)** | ~3.2 ms | ~310 fps |

### Big scene (20 lattices 8×8 or 600 fluid particles)
| Pipeline | Time | Note |
|---|---:|---|
| Softbody step (20×8×8) | ~12-15 ms | After Tier 10 lands |
| PBF step (600 part) | ~4-5 ms | After Tier 10 lands |

### Achieved: small scenes hit ~300-700 fps end-to-end. Big scenes hit ~70-200 fps.

## What Tier 11 (GPU compute) would deliver

Moving solver loops to WGSL compute shaders + buffer state on GPU
(wgpu) typically gives **10-100×** on large parallel workloads. For
small scenes the GPU launch overhead (~50-100 µs per dispatch) means
the per-frame win is smaller; for big scenes the speedup is dramatic.

Realistic GPU end-state targets:
| Pipeline | CPU Rust (now) | GPU compute (estimated) |
|---|---:|---:|
| Softbody step (5×6×6, 245 nodes) | 1.4 ms | ~0.5 ms (dispatch-bound) |
| Softbody step (20×8×8, 1620 nodes) | ~13 ms | **1-2 ms** |
| Softbody step (5000-node mega scene) | ~50 ms | **3-5 ms** |
| PBF step (140 part) | 0.88 ms | ~0.5 ms |
| PBF step (600 part) | ~4 ms | ~1.5 ms |
| PBF step (10k particles) | 60+ ms | **5-10 ms** |
| Render (any size) | <2 ms | Already-GPU-resident → ~0.5 ms |

**The big-scene win is what matters.** Small scenes are already
"infinite fps" (300+) which is well beyond display refresh.

## What Tier 11 requires

### Scope of work (rough estimate)

**Phase 1 — POC** (~1-2 days):
- Pick the SMALLEST hot-path kernel to port first (PBF density iter
  is a good candidate — it's pure data-parallel per particle).
- Write a WGSL compute shader for that one kernel.
- Build the GPU buffer plumbing: upload pos/mass/idx to GPU once, run
  compute, read back results.
- Validate bit-equivalence with the CPU Rust path.
- Measure: is the GPU win real, or does PCIe transfer + dispatch
  overhead eat it?

**Phase 2 — Full solver port** (~3-5 days if POC works):
- Port all solver kernels (XPBD distance, contact projection,
  broadphase, PBF iter, friction, thermal).
- Keep buffers GPU-resident across iterations — readback only once
  per frame (or never, if render runs from same buffers).
- Wire `_HAS_NATIVE_GPU` switch on top of `_HAS_NATIVE_*` CPU switches.

**Phase 3 — Render integration** (~1-2 days):
- Currently `src/raster.rs` is CPU SIMD. We could:
  - Option A: keep CPU raster, read back from GPU each frame
  - Option B: port raster to WGSL too, render directly from GPU
    physics buffers (zero readback)
- Option B is the AAA path — but the existing CPU raster is already
  excellent (1500+ fps fluid).

### Engineering risks
1. **GPU dispatch overhead at small N**. The current CPU Rust path
   is ~50-100 µs per kernel call. GPU dispatch is ~50-100 µs per
   compute pass. For small scenes the GPU brings NO win, only
   complexity. Mitigation: keep `_HAS_NATIVE_*` CPU paths as a
   small-scene fast path; only switch to GPU above a threshold.
2. **Precision differences**. WGSL f32 is IEEE-754 but optimizer
   may reorder ops, causing the `test_block_on_block_stacks` and
   `test_block_buries_in_sand` canaries to drift. Mitigation:
   bit-equivalence is unrealistic on GPU; we may need a tolerance
   bump on those tests for the GPU path.
3. **Cross-platform GPU support**. wgpu abstracts but each backend
   (Vulkan / D3D12 / Metal) has subtle differences in compute
   capabilities. Need to verify multi-platform CI.
4. **The current path is already FAST**. We're at 300-700 fps for
   typical game scenes. Most users won't notice the GPU win.

### Build / dependency impact
- `wgpu` already exists in the workspace (used by the renderer's
  shader compilation path). Adding compute pipelines is incremental.
- No new big deps. Existing pyo3 + bytemuck + rayon stack is fine.

## My recommendation

**Defer Tier 11 unless we have a real scene that's slow.**

Reasons:
1. The small + typical scenes (which represent 99% of games using
   this engine) are already running at 300-700+ fps. Further wins
   are invisible to users.
2. Tier 11 is multi-day work with non-trivial complexity
   (precision drift, dispatch overhead at small N, dual code paths,
   cross-platform GPU testing).
3. The diminishing returns are real: CPU Rust gave us ~10×; GPU on
   small scenes maybe ~2×; GPU on big scenes maybe ~5-10×. The big
   wins materialize only when somebody actually builds a 5000+ node
   destructible scene that the CPU can't handle.

**Better next moves (lower-risk, still wins):**

- **A. Validate with real game content.** Run Ochema Circuit and
  Bullet Strata against the current Rust build. If their actual
  scenes are slow, we have a perf bug to investigate. If they're
  fast enough, ship the current build to PyPI as `pharos-engine
  v1.0` and let the Tier 11 conversation be driven by a real user
  complaint.
- **B. Profile the editor.** A common indie-engine bottleneck is
  not the solver, it's the editor UI redrawing too often. If the
  user sees jank, it's likely DearPyGui not the physics.
- **C. Ship + measure.** Build a PyPI wheel today, give it to a
  beta user, get real perf numbers from real scenes.

## When to revisit Tier 11

Build it when ONE of these is true:
- A real scene requires > 5000 active physics bodies (we don't have
  this today).
- Multi-system per-frame budget exceeds 16 ms on a target device
  (we have ~3 ms now — 5× headroom).
- A user-facing feature explicitly needs GPU buffers (e.g., realtime
  GI updated from physics density grids).

## Open question for the user

Three concrete options:

**Option 1 — Ship now, defer Tier 11.** Mark the migration done.
Build wheel. Iterate on user feedback. Estimated time to ship: hours.

**Option 2 — POC Tier 11 on PBF density iter.** ~1-2 days to
validate the dispatch-overhead-vs-throughput trade-off on real
hardware before committing. Outcome: a clear yes/no on whether full
GPU porting is worth the effort.

**Option 3 — Full Tier 11 commit.** Multi-day push to port all
solver kernels + render. Best long-term position; biggest immediate
investment.

My vote: **Option 1**. The CPU Rust state is already excellent.
Ship + measure + only invest in GPU when a real scene demands it.

---

## Decision (2026-05-26)

**User chose Option 1 — ship now, defer Tier 11.**

If we ever come back to GPU compute, the full execution plan is
documented at [docs/tier_11_future_instructions.md](tier_11_future_instructions.md):
- Phase 11.A POC on PBF density iter (1-2 days, decision gate)
- Phase 11.B full solver port (3-5 days, conditional on 11.A win)
- Phase 11.C render integration (1-2 days, optional)
- Pre-commit checklist + file list + precision concerns + cross-platform
  testing notes.

This document remains as the trade-off rationale; the other doc is the
"go-do-this" recipe.
