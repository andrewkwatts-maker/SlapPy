# Sprite Audit & Regenerate Recipe

When a downstream game (e.g. Ochema Circuit) ends up with a washed-out or
mis-extracted UI sprite, run this recipe to inventory, diagnose, regenerate,
and verify the asset without touching engine source.

The recipe stays headless and uses only Pillow + numpy. All work products live
under `H:/tmp/sprite_audit/`; the only file modified in the downstream tree is
the sprite itself (which lives on the game's SVN, not in the engine repo).

## 1. Inventory

Enumerate every candidate file the failing scene might load. For Ochema's
garage panel the candidates were `vehicle_topdown_*`, `vehicle_car_*`,
`vehicle_assembled_*`.

For each PNG, record:

- width × height
- file size (KB)
- mean RGB across **opaque** pixels (so transparent margin doesn't dilute the
  average)
- alpha coverage percent

Save the table to `H:/tmp/sprite_audit/inventory.md`.

## 2. Identify the broken sprite

Walk the scene's fallback chain in order and pick the first file that exists
on disk — that is what's actually rendering. Open it at 4× nearest-neighbour
zoom on the panel background colour (`#0E141E` for the scorched-wasteland
theme) and save to `H:/tmp/sprite_audit/current_first_hit_4x.png`.

Common failure modes you'll see in the 4× preview:

- **Muddy / faded colour** — mean RGB is low and channels are close together.
  Usually means the sprite was extracted from a sheet with imperfect
  background-key removal: the chroma key bled into the body texture.
- **Sub-50% alpha coverage** with mottled holes — same root cause; the keyer
  ate body pixels because the tolerance was too loose.
- **Wrong orientation / aspect** — the extraction box was right but the
  source sheet pose doesn't match what the consumer expects.

## 3. Regenerate

If a dedicated tool exists in the downstream tree (e.g.
`tools/extract_vehicle_sprites.py`), prefer raising its resolution and
saturation. Otherwise compose from PIL primitives:

- Render at **4× supersample** then `Image.resize(..., Image.LANCZOS)` down
  to target. This gives free anti-aliasing on every edge.
- Use the project's documented palette literally — for the scorched-wasteland
  theme that's amber `#FFBE28`, panel-dark `#0E141E`, mute-grey accents,
  and red `#C84020` for spike accents. Do **not** introduce blues, greens, or
  purples unless replacing a debug placeholder.
- Build the silhouette as a single filled polygon (darker rim colour) and
  then a slightly inset polygon (bright body colour) so the LANCZOS pass
  produces a clean dark outline ring.
- Add a Gaussian-blurred drop shadow underneath so the sprite reads against
  the dark panel.
- Keep the file under 100 KB and call `save(..., optimize=True)`.

Always back the original up to `H:/tmp/sprite_audit/<name>.old.png` before
overwriting.

## 4. Verify

Produce three verification PNGs:

- `vehicle_topdown_redspiked_100.png` — new sprite at 100% on the dark panel
  background.
- `vehicle_topdown_redspiked_4x.png` — same, but nearest-neighbour 4×.
- `before_after.png` — side-by-side OLD | NEW, both at 4×, with text labels
  showing dimensions, file size, and the colour-quality blurb (e.g.
  "vivid amber, ~82% alpha cov").

Re-stat the new sprite with the inventory script and confirm the mean RGB and
alpha coverage moved in the expected direction (more saturated, higher
coverage).

## 5. Commit boundary

The engine-side commit is just this recipe doc plus its companion test
(`SlapPyEngineTests/tests/test_sprite_audit_recipe.py`). The sprite itself ships through the
downstream game's own VCS (SVN for Ochema) — do not check binary art into
the engine tree.

## Sprint 2 findings (2026-05-30)

Cross-game sprite quality audit ran the procedure above against the
engine's own bundled PNGs. Full inventory + analysis lives in
`H:/tmp/sprite_audit_sprint2/inventory.md`; key results:

- **Scope.** No repo-root `assets/` directory exists. `SlapPyEngineTests/tests/visual/reference/`
  only contains `.npy` numeric goldens. The only PNGs the engine ships are
  the 21 baselines under `python/slappyengine/testing/baselines/`, which are
  full-frame render captures, not isolated sprites — they were still audited
  because they form the engine's golden canon and the Sprint 2 anchor test
  iterates them.
- **Audited:** 21 PNGs.
- **Flagged (any heuristic):** 20 of 21 tripped *only* the `desaturated`
  heuristic (mean RGB on opaque dark-scene captures sits near grey-of-low-luma,
  which is by design for the chroma-spread metric tuned to UI sprites).
- **Critical recommendation:** 0. The Sprint 2 anchor test
  (`SlapPyEngineTests/tests/test_sprint_2_sprite_audit.py`) asserts
  `assess_quality(entry)['recommendation'] != "critical"` for every PNG.
- **Regenerated:** 0. These are render goldens — rewriting them would
  invalidate the visual-regression suite they back.
- **Threshold note.** The sprint task spec called for `width < 32` / `height < 32`
  to flag "tiny" sprites; the in-tree
  `slappyengine.tools.sprite_audit.MIN_DIMENSION_CUTOFF` is the stricter
  `64`. Per the do-not-modify-the-tool directive, the audit reports against
  the tool default; no baseline is below 64 on either axis under either rule.

Treat the `desaturated`-only flags on full-frame render captures as a
known-good false positive for engine baselines; the heuristic stays valuable
for foreground/UI sprites in downstream games.
