# Woodland Creature Catalog — TeenGirl Notebook Theme Layer

**Status:** Design catalogue (2026-06-03). Pure design; no source yet.
**Parent theme:** [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md)
**Concept-art inputs:** [`ui_concept_art_2026_06_03.md`](ui_concept_art_2026_06_03.md)
**Subsystem spec:** [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md)
**Pattern audit:** [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md)

This catalog defines the woodland creatures, plants, and decorative
motifs that may appear across the Pharos Engine editor. It is a **layer
on top of** the TeenGirl Notebook base theme — the creatures are not
required; a stripped-down TeenGirl Notebook with `creature_animations =
False` is the same theme minus the cast. Read this together with the
subsystem spec, which defines `Creature`, `CreatureScheduler`, and the
event bindings.

The catalogue is deliberately small (14 entries) so each creature can
be hand-tuned, performance-budgeted, and accessibility-reviewed.

## 0. Design principles

1. **Shader-first.** Procedural SDF + fragment-shader rendering is the
   preferred path. Sprites are a fallback. Vector (SVG) is reserved for
   crisp small icons. Nine-slice is for panel-bound creatures (e.g.
   snail shell forms part of a panel border).
2. **Quiet by default.** Creatures idle silently. They blink, ear-twitch,
   or sway on long cooldowns (10-90 s). Movement is small (≤ 8 px) and
   slow (≥ 250 ms).
3. **One-shot moments are earned.** A creature only acts on a real engine
   event (save, build, error). No random pop-ups.
4. **Off switch is first-class.** `settings.ui.creature_animations =
   False` removes the entire layer with no fallback artefacts.
5. **Performance budget.** Idle tick < 1 ms / frame for ≤ 5 active
   creatures; one-shot trigger < 5 ms / frame at peak.
6. **Theme-aware.** Every creature declares four seasonal alternates
   (summer / winter / spring / autumn) — the active palette can re-skin
   without recoding behaviour.

## 1. Cast table

| ID | Name | Role | Render | Animation states |
|----|------|------|--------|------------------|
| `fox_01` | Sleepy Fox | toolbar idle mascot | procedural (SDF body + fur shader) | idle, blink, stretch, yawn |
| `deer_01` | Curious Deer | sidebar peek mascot | nine-slice torso + SVG head | peek_in, peek_out, ear_twitch |
| `owl_01` | Wisdom Owl | error popups | shader feathered body + SVG eyes | hoot, blink, head_turn |
| `frog_01` | Bouncy Frog | toolbar hop | sprite (4-frame fallback) | sit, hop, blink |
| `rabbit_01` | Speedy Rabbit | progress bar | SVG | run, sit, ear_wiggle |
| `butterfly_01` | Save Butterfly | save event | shader wing flap | idle, flutter, land |
| `bee_01` | Build Bee | build event | shader gradient + SVG wings | hover, dive, sting |
| `snail_01` | Shy Snail | loading | nine-slice shell + SVG body | crawl, hide |
| `mushroom_01` | Decoy Mushroom | corner decoration | shader cap noise | static, spore_puff |
| `acorn_01` | Confetti Acorn | success | particle | drop, roll |
| `fern_01` | Fern Frond | panel borders | shader veins | static, sway |
| `leaf_01` | Falling Leaf | autumn theme | shader vein noise | drift |
| `flower_01` | Daisy | scene outliner badge | SVG | static, bloom |
| `pinecone_01` | Pinecone Marker | bookmarks | nine-slice | static, drop |

## 2. Per-entry detail

### 2.1 `fox_01` — Sleepy Fox

- **Role:** primary idle mascot in the editor toolbar (bottom-left
  corner, ~64×64 px slot).
- **Render strategy:** procedural — body as a stack of three SDF capsules
  (head / torso / tail) blended with a smooth-min; fur shaded by a
  cheap value-noise fragment shader at 64×64. No texture upload.
- **Trigger events:** none direct; idle-only by default. `engine.idle_60s`
  may trigger a `stretch`.
- **Idle behavior:** blink every 4-8 s, ear-twitch every 12-25 s, rare
  `yawn` every 60-90 s.
- **One-shot:** `stretch` on `engine.idle_60s` (≤ 1.2 s, body elongates
  +6 px, returns).
- **Theme alternates:**
  - summer: orange + cream fur.
  - winter: pale-orange fur, scarf overlay (nine-slice stripe).
  - spring: flower-crown SVG overlay on head.
  - autumn: deeper-red fur tint; acorn cheeks (two SVG dots).
- **Perf budget:** 0.3 ms idle (SDF eval is the cost); 0.9 ms during
  `stretch` (still pure shader).

### 2.2 `deer_01` — Curious Deer

- **Role:** sidebar peek mascot — appears on `engine.scene_loaded`
  peeking from the right edge of the scene outliner.
- **Render strategy:** nine-slice torso (so the body can extend off the
  panel edge cleanly) + SVG head + antlers.
- **Trigger events:** `engine.scene_loaded` → `peek_in`; `engine.scene_closed` → `peek_out`.
- **Idle behavior:** while peeking, `ear_twitch` every 8-15 s.
- **One-shot:** `peek_in` (0.8 s slide-in), `peek_out` (0.5 s slide-out).
- **Theme alternates:** summer brown, winter white-spot, spring with
  flower behind ear, autumn russet.
- **Perf budget:** 0.2 ms (nine-slice + SVG, both cached).

### 2.3 `owl_01` — Wisdom Owl

- **Role:** error popups — flies in next to the error dialog title.
- **Render strategy:** shader feathered body (cheap radial-gradient +
  noise overlay), SVG eyes (large round whites + black pupils).
- **Trigger events:** `engine.build_failure` → `hoot`; `engine.error` → `hoot`.
- **Idle behavior:** while present, `blink` every 3-6 s.
- **One-shot:** `hoot` (chest puffs 1.1×, head tilts 5°, 0.7 s);
  `head_turn` (180° head spin, 0.5 s) — reserved for repeated errors
  in the same session.
- **Theme alternates:** summer brown, winter snowy-white, spring
  greenish, autumn rust.
- **Perf budget:** 0.4 ms idle, 1.5 ms during `hoot`.

### 2.4 `frog_01` — Bouncy Frog

- **Role:** toolbar hop — occasional cross-toolbar hop animation.
- **Render strategy:** sprite anim (4-frame fallback path; this is the
  one creature where a sprite is acceptable because the hop deformation
  is hard to do well with SDF blend at small size).
- **Trigger events:** `engine.idle_120s` → `hop` (rare); `engine.build_success` → optional secondary hop.
- **Idle behavior:** `sit` (single frame), `blink` every 5-10 s.
- **One-shot:** `hop` (4 frames at 12 fps, jumps ~20 px horizontally,
  returns to sit on landing).
- **Theme alternates:** summer green, winter blue-tinged, spring with
  flower in mouth, autumn yellow-orange.
- **Perf budget:** 0.1 ms idle, 0.6 ms during hop (4 sprite blits).

### 2.5 `rabbit_01` — Speedy Rabbit

- **Role:** progress bar — runs along the top edge of any progress bar
  longer than 200 ms.
- **Render strategy:** SVG (crisp at any zoom; rabbit fits the indicator
  metaphor — fast, light).
- **Trigger events:** `progress.start` → `run`; `progress.end` → `sit`.
- **Idle behavior:** while progress is active, `run` loop; while sitting,
  `ear_wiggle` every 4-8 s.
- **One-shot:** spawn on `engine.first_run` for the parade.
- **Theme alternates:** summer grey, winter white, spring with flower
  collar, autumn brown.
- **Perf budget:** 0.15 ms (SVG path, single transform).

### 2.6 `butterfly_01` — Save Butterfly

- **Role:** save event — flutters across the status bar on every
  successful save.
- **Render strategy:** shader wing flap — two triangular wings each as
  an SDF with a per-frame angle parameter; body as a thin oval; no
  texture upload.
- **Trigger events:** `engine.save` → `flutter`.
- **Idle behavior:** absent unless triggered; `idle` is the post-land
  resting wing-open state for ~1 s before despawn.
- **One-shot:** `flutter` (1.5 s flight across status bar, wing flap at
  8 Hz), `land` (0.3 s deceleration onto save-button icon).
- **Theme alternates:** summer monarch orange/black, winter blue
  morpho, spring pink, autumn yellow swallowtail.
- **Perf budget:** 0.5 ms during flight (two SDF wings × 60 fps), 0
  when absent.

### 2.7 `bee_01` — Build Bee

- **Role:** build event — buzzes from the toolbar to the output panel
  on every successful build.
- **Render strategy:** shader body (stripes via UV-modulated gradient)
  + SVG wings (motion-blur trail via two stacked SVGs at low alpha).
- **Trigger events:** `engine.build_success` → `dive`.
- **Idle behavior:** absent unless triggered.
- **One-shot:** `hover` (0.4 s entry), `dive` (1.0 s curved path with
  drop), `sting` (reserved for `engine.build_failure` repeats — bee
  jabs at the error dialog).
- **Theme alternates:** summer yellow/black, winter pale-yellow, spring
  with flower trail, autumn deeper orange.
- **Perf budget:** 0.6 ms during dive (shader + 2 wing SVGs), 0 when
  absent.

### 2.8 `snail_01` — Shy Snail

- **Role:** loading indicator — crawls across the bottom of a long
  loading bar.
- **Render strategy:** nine-slice shell (spiral pattern composed as a
  nine-slice so the shell can sit on a panel edge cleanly) + SVG body.
- **Trigger events:** `loading.start` → `crawl`; `loading.cancel` → `hide`.
- **Idle behavior:** while loading, `crawl` loop (2 px / frame).
- **One-shot:** `hide` (body retracts into shell, 0.4 s).
- **Theme alternates:** summer brown, winter pale-grey shell, spring
  green moss on shell, autumn rust shell.
- **Perf budget:** 0.2 ms (nine-slice cached, SVG transformed).

### 2.9 `mushroom_01` — Decoy Mushroom

- **Role:** corner decoration in empty viewport panels.
- **Render strategy:** shader cap noise — a radial-symmetric cap with
  3D-ish lighting via a cheap dot-product against a fixed normal; stem
  as an SDF capsule.
- **Trigger events:** `engine.click_on_mushroom` (Easter egg) →
  `spore_puff`.
- **Idle behavior:** `static` 99% of the time; rare `spore_puff` every
  120-180 s (gated by `settings.ui.easter_eggs`).
- **One-shot:** `spore_puff` (5 small particles drift up, 1.2 s).
- **Theme alternates:** summer red/white (classic toadstool), winter
  brown, spring pink, autumn deep brown.
- **Perf budget:** 0.1 ms static, 0.8 ms during puff (5-particle
  emit).

### 2.10 `acorn_01` — Confetti Acorn

- **Role:** success — drops across the screen as confetti on
  `engine.build_success` and `engine.test_pass`.
- **Render strategy:** particle — 8-12 acorn primitives drawn as
  textured quads (the only one using a tiny baked atlas; the atlas is
  shared with `pinecone_01`).
- **Trigger events:** `engine.build_success`, `engine.test_pass`.
- **Idle behavior:** absent unless triggered.
- **One-shot:** `drop` (1.5 s gravity fall, slight horizontal drift),
  `roll` (0.5 s post-landing roll at the bottom edge).
- **Theme alternates:** summer green-cap, winter brown, spring with
  leaf trail, autumn (default) red-brown.
- **Perf budget:** 1.2 ms peak (12 quads × particle update + draw).

### 2.11 `fern_01` — Fern Frond

- **Role:** decorative motif on panel borders (sidebar dividers, status
  bar edges).
- **Render strategy:** shader veins — procedural fractal-vein pattern
  generated in a fragment shader at low resolution, cached as a
  texture per theme load (NOT per frame).
- **Trigger events:** none; `engine.window_resize` may trigger `sway`.
- **Idle behavior:** `static`. `sway` every 15-30 s (low-amplitude
  vertex offset, 1 s).
- **One-shot:** `sway` (mild bend, 1.0 s).
- **Theme alternates:** summer bright green, winter pale (frosted),
  spring fresh green, autumn yellow-brown.
- **Perf budget:** 0 ms idle (cached texture), 0.3 ms during sway.

### 2.12 `leaf_01` — Falling Leaf

- **Role:** autumn theme ambient — leaves drift across the viewport
  occasionally.
- **Render strategy:** shader vein noise — leaf SDF with per-instance
  rotation and noise-driven vein highlights.
- **Trigger events:** active only when `theme.season == "autumn"`;
  random spawn every 20-40 s.
- **Idle behavior:** `drift` (8-12 s descent across viewport, gentle
  rotation).
- **One-shot:** none; the drift IS the animation.
- **Theme alternates:** autumn (default red/orange); summer green
  (rare; appears only on user-action shake-tree Easter egg); winter
  brown skeletal; spring fresh green.
- **Perf budget:** 0.4 ms per active leaf; capped at 3 simultaneous.

### 2.13 `flower_01` — Daisy

- **Role:** scene outliner badge — sits next to a selected scene root
  node as a "you are here" marker.
- **Render strategy:** SVG (5 petals + centre dot; scales cleanly).
- **Trigger events:** `scene_outliner.select_root` → `bloom`.
- **Idle behavior:** `static` while shown.
- **One-shot:** `bloom` (0.4 s petal scale-up from 0 to 1, gentle
  overshoot).
- **Theme alternates:** summer white/yellow, winter blue (forget-me-
  not), spring pink, autumn orange.
- **Perf budget:** 0.05 ms (5 SVG path draws).

### 2.14 `pinecone_01` — Pinecone Marker

- **Role:** bookmarks — pinecone icon marks a bookmarked line in the
  Code Mode editor.
- **Render strategy:** nine-slice (scale-aware bookmark size as the
  code editor's line height changes).
- **Trigger events:** `code_mode.bookmark_add` → `drop`.
- **Idle behavior:** `static`.
- **One-shot:** `drop` (0.4 s bounce from -8 px to 0).
- **Theme alternates:** summer green-tinted, winter snow-dusted,
  spring with sprig, autumn brown.
- **Perf budget:** 0.05 ms (cached nine-slice).

## 3. Seasonal palette swap-out summary

Each creature carries a `theme_variants: dict[str, CreatureVariant]`
mapping season name → variant. A theme switch (e.g. summer → autumn)
re-binds creature visuals without changing behaviour.

| Season | Dominant palette tint | Notable overlays |
|---|---|---|
| summer (default) | warm earth tones, bright green | none |
| winter | cool greys, pale tints, white | scarves, snow dust |
| spring | pastel pinks/greens | flower crowns, fresh sprigs |
| autumn | russet, deep orange, brown | acorn cheeks, falling-leaf trails |

The seasonal variants are theme-driven, not per-creature-toggled. A
theme spec declares the active season once.

## 4. Slot assignment summary

| Slot region | Creatures it hosts | Concurrency |
|---|---|---|
| Toolbar (bottom-left, 64×64) | `fox_01`, `frog_01` | 1 |
| Sidebar right edge (scene outliner) | `deer_01`, `flower_01` | 2 (separate sub-slots) |
| Status bar | `butterfly_01`, `bee_01` | 1 |
| Progress bar overlay | `rabbit_01`, `snail_01` | 1 |
| Error dialog header | `owl_01` | 1 |
| Viewport corners (empty panels) | `mushroom_01` | 1 per corner, max 2 |
| Viewport ambient | `leaf_01` | 3 |
| Confetti / fullscreen | `acorn_01` | 1 burst at a time |
| Decorative borders | `fern_01` | unlimited (cached texture) |
| Code Mode gutter | `pinecone_01` | per bookmark, unlimited |

## 5. Render-strategy distribution

| Strategy | Count | Creatures |
|---|---:|---|
| procedural (SDF + shader) | 7 | fox, owl, butterfly, bee, mushroom, fern, leaf |
| nine-slice | 4 | deer (torso), snail (shell), pinecone, fern (border use) |
| SVG | 5 | deer (head), owl (eyes), rabbit, snail (body), flower |
| sprite | 1 | frog (fallback path) |
| particle | 1 | acorn |

(A creature can use multiple strategies — counts overlap; see per-entry
detail.)

## 6. Accessibility + opt-out matrix

| Mode | Idle anims | Trigger anims | Confetti | Movement |
|---|---|---|---|---|
| Full (default) | yes | yes | yes | yes |
| Reduced motion | blinks only | static reveal (no fly-in) | no | none |
| Off | none | none | none | none |

Reduced motion is the recommended default for accessibility-sensitive
users; "off" hides the entire layer (including static decorative
creatures like `flower_01`).

## 7. Performance budget summary

| Tier | Active count cap | Per-frame budget | Notes |
|---|---:|---:|---|
| Idle (resident) | ≤ 5 | ≤ 1.0 ms | most are 0.1-0.4 ms |
| One-shot (transient) | ≤ 1 visible | ≤ 5.0 ms peak | `acorn_01` confetti is the heaviest at ~1.2 ms |
| Cached (nine-slice/SVG cache rebuild) | n/a | one-time on theme apply | < 50 ms acceptable on theme switch |

Aggregate worst-case: 5 idle creatures (1.0 ms) + 1 one-shot
(5.0 ms) = 6.0 ms / frame, which leaves ≥ 10 ms headroom at 60 fps.

## 8. Open questions

1. Should `frog_01` ship sprite frames in the wheel or generate them
   from the SDF body at install time?
2. `mushroom_01` Easter-egg click handling — does the editor have a
   per-creature click router yet, or do we need to add one to the
   slot policy?
3. Acorn atlas: shared with `pinecone_01` — confirm both can fit in a
   single 64×64 RGBA atlas.

Tracked in [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md) §7 (Test plan + open items).

## 9. Cross-links

- [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md) — parent theme that registers these creatures.
- [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md) — scheduler, slot policy, performance contract.
- [`ui_concept_art_2026_06_03.md`](ui_concept_art_2026_06_03.md) — concept-art inputs (palette, sticker library, layout patterns).
- [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) — audit of current UI patterns the theme must respect.
