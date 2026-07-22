# AAA-quality default page-lining shaders (BBB5, 2026-07-19)

## Summary

Per the user directive *"ensure AAA quality shaders in default themes"*,
the four *default* page-lining presets in
`python/pharos_engine/ui/theme/page_linings/` were upgraded from **flat
pixel-perfect line drawings** to **realistic hand-drawn / offset-print
paper stock**. The upgrade covers:

* `ruled_paper` — the classic notebook rule pattern
* `dot_grid` — bullet-journal dot lattice
* `graph_grid` — 1mm mint graph paper
* `blank_cream` — plain solid cream stock

A companion set of three quality tiers is exposed as
`AAAShaderQualityPreset` (`LOW` / `MEDIUM` / `HIGH`) so downstream
callers can pick the visual budget they want per texture bake.

## Before / after

| Preset | Before (LOW) | After (HIGH) |
|---|---|---|
| `ruled_paper` | flat cream (250,247,235), crisp 1-px blue rule every 24 px, exact red vertical at x=32 | cream with ±3-4 luma Perlin grain, 2-octave; blue rules soft-AA'd across 2 px with ±0.5-px per-column jitter; warm sun-lit tint top-left |
| `dot_grid` | 1.5-px hard circular dot | 2.4-px anti-aliased dot, per-dot alpha variance ±30 (deterministic hash), Perlin grain, warm tint |
| `graph_grid` | 1-px hard mint gridlines every 10 px | dual-axis AA'd gridlines with `ink_bleed` widening the effective footprint, Perlin grain, warm tint |
| `blank_cream` | high-freq WGSL noise only | high-freq noise + 2× Perlin low-freq grain + warm sun-lit gradient |

Numerical dimension comparison at 128 × 96 (RGB std, higher = more
texture variance):

| Preset | LOW std | HIGH std |
|---|---|---|
| `ruled_paper` | ≈ 26 (dominated by discrete rules) | ≈ 27 (rules + grain, smoother) |
| `dot_grid` | ≈ 12 | ≈ 14 |
| `graph_grid` | ≈ 40 | ≈ 42 |
| `blank_cream` | ≈ 1.5 | ≈ 4.5 |

`blank_cream` sees the largest relative uplift because it starts flat.

## Per-preset AAA-quality checklist

### `ruled_paper`
- [x] Paper grain — 2-octave Perlin-style (65 % 1-px + 35 % 4× down-sampled)
- [x] Line anti-aliasing — 2-3-pixel gradient at each ruled line
- [x] Line jitter — ±0.5-pixel row wobble smoothed across x
- [x] Warm cream tint — top-left warm / bottom-right cool
- [x] Preserves margin rule at x=32 with matching AA
- [x] LOW tier byte-for-byte matches pre-BBB5 output

### `dot_grid`
- [x] Per-dot alpha variance ±30 (deterministic sine-hash of cell index)
- [x] Dot size 2-3 px anti-aliased edge
- [x] Paper grain
- [x] Warm tint
- [x] LOW tier byte-for-byte matches pre-BBB5 output

### `graph_grid`
- [x] Dual-axis line AA (nearest-line signed distance)
- [x] Blue-ink bleed — line footprint expanded by `1 + 3 * ink_bleed`
- [x] Paper grain
- [x] Warm tint
- [x] LOW tier byte-for-byte matches pre-BBB5 output

### `blank_cream`
- [x] Perlin low-freq grain layered on top of existing WGSL noise (2× amp
      to compensate for lack of contrast anchors)
- [x] Warm sun-lit gradient
- [x] LOW tier byte-for-byte matches pre-BBB5 output

## Public API

```python
from pharos_editor.ui.theme.page_linings import (
    AAAShaderQualityPreset, DEFAULT_AAA_PRESET, render_lining,
)

# HIGH is the new editor default.
arr = render_lining(
    "ruled_paper", (256, 128),
    quality=AAAShaderQualityPreset.HIGH,
    force_fallback=True,
)

# LOW recovers legacy flat output for golden-image regression tests.
arr_legacy = render_lining(
    "ruled_paper", (256, 128),
    quality=AAAShaderQualityPreset.LOW,
    force_fallback=True,
)
```

The `shader_effects.ruled_paper()` numpy helper gained three new
kwargs — `grain_intensity`, `jitter_px`, `warm_tint` — all defaulting to
`0.0` so existing callers see the exact same pixels they did
pre-upgrade.

## Rust-migration note

Per the engine architectural directive
(`project_architecture_pattern.md` — *every hot path ports to Rust;
Python is glue*), the per-preset numpy fallbacks in
`python/pharos_engine/ui/theme/page_linings/renderer.py` are hot enough
under editor-panel rebake (each panel resize triggers a fresh 256 × 128
bake) that they are formally **marked as Rust-port candidates**.

Suggested port scope:

1. `_paper_grain(w, h, intensity, seed_salt) -> ndarray` — trivial 2-octave
   PRNG; drop-in replacement matching the numpy seed.
2. `_row_wobble(w, amp_px, seed_salt) -> ndarray` — 5-tap 1-D convolve;
   trivial.
3. `_fp_ruled_paper`, `_fp_dot_grid`, `_fp_graph_grid`, `_fp_blank_cream`
   — port the AAA branches; keep the LOW branch in Python for parity /
   test-vector stability.

Expected speedup at 512 × 512: 12-15× (from render profiling at 3.6 ms
numpy → ~0.28 ms Rust extrapolated from `raster.rs` numbers).

## Testing

`SlapPyEngineTests/tests/test_aaa_shaders.py` (34 tests):

* 3 preset-sanity tests (three tiers exist, default is HIGH, LOW is all
  zeros)
* 4 × HIGH-renders-without-exception (per upgraded preset)
* 4 × shape-invariant-across-tiers
* 4 × LOW-deterministic
* 4 × LOW-matches-legacy
* 4 × HIGH-luma-variance > 3.0
* 4 × HIGH-deterministic-across-runs
* 7 × `shader_effects.ruled_paper` kwarg regressions (defaults preserve
  legacy, each new kwarg works, all three together, range validation)

All pre-existing tests in `test_page_lining_shaders.py` (28) and
`test_theme_primitives.py` (56) continue to pass unchanged.
