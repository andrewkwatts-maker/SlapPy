<!-- handauthored: do not regenerate -->
# slappyengine.testing — API Reference

> Hand-curated reference for the testing subpackage. The auto-generator
> (`scripts/gen_subpackage_api_docs.py`) skips files carrying the
> `<!-- handauthored: do not regenerate -->` marker above.

```python
from slappyengine.testing import (
    assert_scene_matches,
    render_scene_to_png,
    diff_pngs,
    BASELINES_DIR,
    DIFF_DIR,
)
```

## Overview

`slappyengine.testing` is the engine's **visual regression harness**.
Any engine change can be screenshot-verified with a single line of
test code:

```python
from slappyengine.testing import assert_scene_matches
assert_scene_matches(my_scene, "hello_softbody")
```

The Sprint 7E surface audit lists **15 public attributes**. Five are
the load-bearing entries above; the other ten are stdlib aliases
(`Any`, `Path`, `logging`, `np`) plus six `_validation` helpers
(`validate_baseline_name`, `validate_non_negative_float`,
`validate_non_negative_int`, `validate_pathlike`,
`validate_positive_int`, `validate_tolerance`). Only the five entries
in the import block above are part of the supported contract.

## Design goals

The harness was promoted out of the polish-visual-regression-harness
branch with four constraints:

1. **Headless.** No GPU device is required. The harness reads back
   whatever CPU-side `numpy` buffer the engine has already produced
   (layer `_image_data`, fluid CPU density, landscape tile composite).
   When nothing is available it returns a deterministic synthetic
   gradient so tests never silently no-op on an empty scene.
2. **Golden-master on first run.** If no baseline PNG exists for a
   given `baseline_name`, the rendered frame is written into
   `BASELINES_DIR` and the assertion passes. Subsequent runs diff
   against that file. New tests bootstrap on their first CI tick
   without anyone hand-curating a reference image.
3. **Cheap diff.** Per-channel mean absolute difference scaled to
   `[0, 1]`. Tolerance defaults to `0.02` — tight enough to catch
   any-pixel regressions, loose enough to survive font / PIL aliasing
   jitter across machines.
4. **Reviewable failures.** When the diff fails, a red-overlay
   visualisation is written to `DIFF_DIR` so a reviewer can scan
   exactly which pixels moved.

## Public API

### `assert_scene_matches(scene, baseline_name, *, tolerance=0.02, width=1280, height=720) -> None`

Render *scene*, compare to the named baseline, raise on mismatch.

- `scene` — any object with a `_tick` / `tick(dt)` method, or any of
  the layer-shapes the frame extractor recognises (see below). `None`
  is accepted and produces the synthetic fallback frame, which is
  handy for self-tests.
- `baseline_name` — filename stem (no `.png`). Must match
  `[A-Za-z0-9_-]+` (rejected by `validate_baseline_name`). The strict
  character class blocks accidental path traversal at the boundary —
  `"../etc/passwd"` raises `ValueError` before it touches the
  filesystem.
- `tolerance` — max acceptable per-channel absolute diff in `[0, 1]`.
- `width` / `height` — render resolution. If they differ from the
  baseline the diff resizes the baseline to match, so changing
  resolution mid-stream isn't fatal — just noisier.

First-run semantics: if `BASELINES_DIR / f"{baseline_name}.png"` does
not exist, the rendered frame becomes the new baseline and the
assertion passes. Subsequent runs render to
`<name>.actual.png`, diff via `diff_pngs`, and either delete the
throwaway actual frame (on pass) or write a red-overlay diff to
`DIFF_DIR / f"{baseline_name}_diff.png"` and raise
`AssertionError` (on fail).

Raises:

- `TypeError` if `baseline_name` is not a `str`, or
  `tolerance` / `width` / `height` are not numeric.
- `ValueError` if `baseline_name` contains path separators or
  disallowed characters, `tolerance < 0`, or `width` / `height < 1`.

### `render_scene_to_png(scene, path, width=1280, height=720, frames_to_settle=2) -> Path`

Render *scene* to a PNG at *path*. Returns `Path(path)` for chaining.

- `frames_to_settle` — number of `_tick(1/60)` calls applied before
  grabbing the frame so deferred work (compute kernels, layer blits)
  has a chance to land in the CPU buffers. Defaults to 2; bump it for
  scenes with multi-frame setup.

Frame extraction is best-effort. The harness walks a fallback chain:

1. `scene._image_data` if the scene itself is layer-like (shape
   `H × W × 4`, `uint8`).
2. The first non-`None` `_image_data` on `scene._z_layers` or
   `scene.z_layers`.
3. The first non-`None` `_image_data` on `scene.entities` (or their
   `.layer`).
4. `scene.fluid` CPU density readback (`_density_cpu`, `density_cpu`,
   or `_cpu_density`), colourised to RGBA.
5. The first non-`None` `_image_data` on the landscape's
   `visible_tiles()`.
6. A deterministic synthetic diagonal gradient + off-axis blob.

The result is always coerced to `(height, width, 4)` `uint8` RGBA via
PIL bilinear resize.

Raises:

- `TypeError` if `path` is not str / `os.PathLike`, or
  `width` / `height` / `frames_to_settle` are not plain ints.
- `ValueError` if `width` or `height` < 1, or `frames_to_settle` < 0.

### `diff_pngs(actual_path, baseline_path, *, tolerance=0.02) -> dict`

Compare two PNGs and return diff metrics. Cross-resolution comparisons
produce a number rather than crash — the baseline is resized to the
actual's shape before the per-channel subtract.

Returns a dict:

| Key | Type | Meaning |
|-----|------|---------|
| `max_pixel_diff` | `float` in `[0, 1]` | Worst single channel-pixel. |
| `mean_pixel_diff` | `float` in `[0, 1]` | Averaged across the frame. |
| `passes` | `bool` | `max_pixel_diff <= tolerance`. |
| `diff_path` | `Path \| None` | Always `None` here — diff PNGs are written by `assert_scene_matches`, not by this primitive. |

The PSNR / SSIM helpers some teams expect are **not** shipped — the
mean-absolute-difference metric proved sufficient for every regression
caught so far, and adding SSIM would pull in `scikit-image`. If you
need them, compute them in your test from the actual / baseline PNGs
loaded through PIL.

Raises:

- `TypeError` if either path is not str / `os.PathLike`, or
  `tolerance` is not a real number.
- `ValueError` if `tolerance` is NaN/inf or outside `[0, 1]`.

## Directory constants

### `BASELINES_DIR`

`Path(__file__).parent / "baselines"`. Resolves to
`python/slappyengine/testing/baselines/`. Ships **inside the wheel** so
downstream games can run the same harness against their own scenes
without depending on the source tree.

The directory currently holds the engine's own visual regression
baselines — one PNG per `hello_*` example plus the composite /
integration scenes (`engine_integration_v2.png`, `fluid_pool.png`, the
`outline_round5` stack used by the topology suite, etc.). They are
*data*, not source — keep them under Git LFS-or-equivalent if your
repo policy demands it.

### `DIFF_DIR`

`<repo-root>/docs/visual_diffs/`. Resolved lazily relative to the
package's installed path (`Path(__file__).resolve().parents[3]`), so
the harness works correctly in worktrees with different repo roots.

When `assert_scene_matches` fails, the red-overlay diff lands here
under `f"{baseline_name}_diff.png"`. Reviewers scan this directory
after a failed CI tick.

## Fixture conventions

The engine's own regression suite (`SlapPyEngineTests/tests/test_visual_*`) follows
three conventions:

1. **One baseline per scene.** Name = filename stem of the example
   (`hello_softbody` → `baselines/hello_softbody.png`). Tests that
   exercise the same example at multiple resolutions or settings use
   a suffix (`hello_softbody_240p`).
2. **Deterministic seeds.** Tests that touch any RNG (particle spawn,
   noise field) seed it explicitly before the first frame. The
   synthetic-fallback gradient is deterministic on its own, so test
   bootstrap on an empty scene is also reproducible.
3. **Pre-settle, then assert.** Tests call `assert_scene_matches`
   directly and let `render_scene_to_png(frames_to_settle=2)` handle
   warm-up. Scenes that need more frames pass `frames_to_settle`
   explicitly via a helper.

## Inner module surface

- `slappyengine.testing.assert_scene_matches` /
  `render_scene_to_png` / `diff_pngs` — public entry points.
- `slappyengine.testing.BASELINES_DIR` / `DIFF_DIR` — directory
  constants resolved at import.
- `slappyengine.testing._validation` — private input-validation
  helpers. Re-exported for introspection only; not part of the
  contract.

## Design notes

No separate `testing_design.md` ships — the four design goals
(headless, golden-master-on-first-run, cheap mean-absolute-difference
diff, reviewable red-overlay failures) plus the fallback-chain rules
for frame extraction are documented inline above.

If a future sprint promotes the harness to support SSIM / PSNR
metrics, structured baselines across multiple resolutions, or
GPU-side comparison, promote that material to a dedicated
`testing_design.md` and link both ways.

## See also

- [`studio.md`](studio.md) — the studio `record()` helper produces the
  exact PNG / GIF outputs this harness scores against.
- [`../studio_design.md`](../studio_design.md) — the `record()`
  contract that produces those outputs.
