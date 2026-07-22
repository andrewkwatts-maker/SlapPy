# Diary Aesthetic Theme Family — Design Reference

> **Status:** design doc only (Sprint 5+, 2026-06-03). Pure spec; no engine
> code lands in this sprint.
>
> **Scope:** expands the TeenGirl Notebook prototype
> ([`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md))
> into a family of **six diary-aesthetic editor themes** plus a roster
> extension of **twelve new domestic-pet / cuddly-wild creatures** that
> live inside the editor UI alongside the fourteen woodland creatures
> already catalogued in
> [`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md).
> All six themes share one runtime contract — a creature roster, a
> nine-slice border vocabulary, a procedural background shader, and a
> palette — so the editor can hot-swap between them without restart.
>
> **Non-scope:** softbody / fluid runtime code is **out of bounds** for
> this sprint per the standing brief. No shader, no Python, no asset
> bytes land here; the artefact is exclusively design.
>
> **Sibling docs:**
> [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md) (base theme contract),
> [`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md) (existing 14 creatures),
> `idle_animation_system_2026_06_03.md` (scheduler + slot policy — landing in parallel),
> [`ui_concept_art_2026_06_03.md`](ui_concept_art_2026_06_03.md) (palette / sticker / layout extraction).

---

## 1. Overview

### 1.1 The diary aesthetic umbrella

Every theme in this family shares one promise to the user: **the editor
looks hand-made and lived-in**. Surfaces look like paper, fabric, or
parchment; borders look drawn or stitched; small creatures live in the
UI and react quietly to engine events. Nothing is rendered as a flat
hard-edged rectangle. Nothing is grey-on-grey. Even at rest the editor
feels like a notebook that has been carried around for a while —
sticker peel, washi tape, soft drop shadows, slightly-off rotations.

### 1.2 Shared contract

Every diary-family theme implements the same public surface so widget
code can stay theme-agnostic. The contract is:

| Slot | What every theme must declare |
|---|---|
| **palette** | A 17-row palette block (see `theme_teengirl_notebook` §1) mapped onto the existing glassmorphism constants in `theme.py`. |
| **fonts** | A header / body / code / decorative font pick, each SIL OFL 1.1 so the wheel can vendor them under `assets/fonts/`. |
| **background shader** | One WGSL `fragment` entry point, baked once at theme activation into a DPG raw texture. |
| **nine-slice border set** | Six border roles: `panel`, `toolbar`, `modal`, `tooltip`, `code_block`, `status_bar`. Patterns differ; margins do not (`(8, 8, 8, 8)` everywhere except `toolbar` at `(0, 8, 0, 8)`). |
| **sticker overlay defaults** | A `dict[panel_role, list[StickerPlacement]]` (re-using the catalog from `theme_teengirl_notebook` §6). |
| **creature roster** | A list of 3-5 creature IDs from the unified catalog (woodland + this doc) that spawn by default. |
| **seasonal flavour tag** | One of `{summer, autumn, winter, spring}`, fed to creatures so their palettes track the theme. |
| **typography size table** | Identical structure to `theme_teengirl_notebook` §2.2 — only the font family substitutes change. |

### 1.3 Opt-in customisation

Diary themes are **never** the default — first launch keeps the
glassmorphism baseline. A theme is selected through one settings key,
plus optional creature/sticker overrides:

```yaml
# config/editor_theme.yml
ui:
  theme: "cozy_diary"          # one of the six theme IDs in §3
  creature_animations: true    # global on/off (default true once a theme is active)
  creatures:
    disabled: ["raccoon_02"]   # per-creature opt-out by ID
    extra: ["fox_01"]          # add creatures not in the theme's default roster
  stickers:
    enabled: true              # off by default in headless / CI
  reduced_motion: false        # mirrors OS prefers-reduced-motion
```

The settings keys map 1:1 to the `Settings.ui` dataclass (Phase A
work). Headless / CI runs force `creature_animations = False` and
`stickers.enabled = False` via the existing `pharos_engine.testing`
fixture chain.

---

## 2. Creature catalogue extension

The existing 14 woodland creatures (fox, deer, owl, frog, rabbit,
butterfly, bee, snail, mushroom, acorn, fern, leaf, flower, pinecone)
are inherited verbatim from
[`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md).
This doc adds **12 domestic-pet + cuddly-wild species** that bring the
total roster to 26. Every entry below honours the woodland catalog's
design principles (shader-first, quiet by default, off-switch
first-class, per-creature perf budget) and slots into the same
`CreatureScheduler` defined in the idle-animation system spec.

### 2.1 New cast table

| ID | Name | Personality | Default home in UI | Render strategy | Personality colour |
|---|---|---|---|---|---|
| `cat_01` | Sleepy Tabby | curls on title bar; stretches at idle | viewport title bar (sleeps on edge of active window) | shader fur + SDF body + SVG eyes / nose / mouth | warm orange-cream `#E8A766` / `#FBE7C9` |
| `cat_02` | Curious Calico | bats at cursor occasionally | sidebar; follows scroll | nine-slice torso + shader patch noise + SVG face | patchy `#FFFFFF` / `#E8A766` / `#221C1A` |
| `golden_01` | Goofy Golden | wags tail on build success | toolbar empty space | shader fur + SDF body + SVG eyes/nose | honey `#E8C66A` / `#FFEFC0` |
| `golden_02` | Studio Golden | fetches "balls" (acorn confetti) on save | bottom status bar | shader fur + SDF body + SVG eyes/nose (slightly darker pup) | deep honey `#D4A84B` / `#F6E2A8` |
| `raccoon_01` | Trash Panda | rummages in property inspector (peeks behind drawers) | property inspector corner | shader striped tail + SDF body + SVG mask | grey-with-black-mask `#9BA0A6` / `#2A2A30` |
| `raccoon_02` | Bandit Raccoon | swipes a sticker every 10 min and runs to a new corner | floats between panels | shader tail + SDF body + SVG mask (with tiny SVG sticker held in paws) | grey-with-black-mask `#9BA0A6` / `#2A2A30` |
| `red_panda_01` | Red Panda Naphour | naps on toolbar like a draft excluder | toolbar baseline | shader russet fur + SDF body + SVG eye mask | russet-with-white-face `#C76A3F` / `#FAF1E2` |
| `red_panda_02` | Climber Red Panda | climbs the scrollbar | any scrollable panel edge | shader russet fur + SDF body + SVG face (claw-grip pose) | russet-with-white-face `#C76A3F` / `#FAF1E2` |
| `panda_01` | Bamboo Panda | chews bamboo (decorative leaves grow on a panel border) | scene outliner | shader white fur + SDF body + SVG black patches | white-with-black `#F8F4EC` / `#1F1F22` |
| `porcupine_01` | Baby Porcupine | rolls into a ball when the user clicks an error | error popup margins | shader soft-fur underbody + SVG quill cluster | soft brown-with-cream-quills `#7A5A40` / `#F3E4C2` |
| `porcupine_02` | Quill Porcupine | quills bristle on hover (delightful interactivity) | toolbar hover area | shader quill noise + SDF body + SVG face | soft brown-with-cream-quills `#7A5A40` / `#F3E4C2` |
| `hedgehog_01` | Tiny Hedgehog | balances a leaf on its quills | spawn menu modal | shader quill noise + SDF body + SVG belly | brown-with-cream-belly `#6F4E37` / `#F5E2BE` |

### 2.2 Per-entry detail

Every entry below carries the same anatomy as the woodland catalog —
**render strategy**, **idle behaviors**, **sleep pose**, **trigger
animation**, **personality colour**, and **perf budget**. Behaviours
are intentionally rare and low-amplitude (the woodland catalog
principle §0.2 carries through verbatim).

#### 2.2.1 `cat_01` — Sleepy Tabby

- **Role:** ambient idle mascot living on the **viewport title bar**.
  Sleeps at the right edge by default, stretches awake every couple of
  minutes, blinks gently.
- **Render strategy:**
  - **Shader fur** — soft fur via a 64×64 value-noise sampled in the
    fragment stage and tinted with the personality colour gradient
    (`#FBE7C9` belly → `#E8A766` back).
  - **SDF body** — three smooth-min capsules (head, body, tail). Tail
    curls under during sleep; uncurls during stretch.
  - **SVG eyes / nose / mouth** — < 500 bytes total; closed eyes are
    two `<path>` curves, open eyes are two `<ellipse>` + pupil
    circles, nose is a tiny pink triangle, mouth is a `w`-shape.
  - **Nine-slice** — none; cat sits on top of the title bar widget,
    not inside a bordered panel.
- **Idle behaviors:** blink 3-7 s; tail flick 20-40 s; stretch 60-120 s;
  rare yawn 180-300 s.
- **Sleep pose:** curled on right edge of title bar; gentle breathing
  via SDF scale `1.00 → 1.02 → 1.00` over 4 s.
- **Trigger animations:** `engine.idle_60s` → stretch (eyes open, body
  elongates +6 px, returns to curl over 1.2 s).
- **Perf budget:** 0.3 ms idle (SDF + cached fur texture); 0.9 ms
  during stretch.

#### 2.2.2 `cat_02` — Curious Calico

- **Role:** sidebar idle mascot; **follows scroll position** so it
  appears to ride the panel. Occasionally bats at the cursor.
- **Render strategy:**
  - **Nine-slice torso** — three colour-zone strips composited so the
    calico patches re-tile cleanly when the sidebar resizes.
  - **Shader patch noise** — drives the white / orange / black blotch
    distribution from a deterministic noise; identical sidebar size →
    identical patches (no flicker on resize).
  - **SVG face** — eyes + nose + whiskers, < 600 bytes.
- **Idle behaviors:** blink 3-7 s; tail flick 20-40 s; head turn
  toward cursor when cursor is within ~80 px (one-shot, 0.4 s);
  rare ear flick 10-20 s.
- **Sleep pose:** lies flat against the inner edge of the sidebar
  when scroll is idle for ≥ 60 s; breathing animation as §2.2.1.
- **Trigger animations:** `input.cursor_in_sidebar` proximity → paw
  bat (0.3 s swipe, capped at one per 8 s); `scroll.start` → mild
  body sway following scroll velocity.
- **Perf budget:** 0.35 ms idle (shader patches cached, SVG once).

#### 2.2.3 `golden_01` — Goofy Golden

- **Role:** lives in **toolbar empty space**, looking forward, tail
  visible. Tail wags when a build succeeds.
- **Render strategy:** SDF body (head / chest / haunches / tail tip)
  + shader fur (honey + cream blend, slight wave noise for ear floof) +
  SVG eyes / nose / smile.
- **Idle behaviors:** blink 3-7 s; tail flick 20-40 s; ear twitch
  15-30 s; rare head tilt 60-120 s.
- **Sleep pose:** head-on-paws crouch at the toolbar baseline; tail
  curls forward; breathing animation as §2.2.1.
- **Trigger animations:** `engine.build_success` → tail wag (3 cycles,
  0.9 s, +/- 18° at the tail tip); `engine.test_pass` → single bark
  (mouth-opens-and-closes silently, 0.4 s, no audio).
- **Perf budget:** 0.4 ms idle; 0.7 ms during tail wag.

#### 2.2.4 `golden_02` — Studio Golden

- **Role:** lives in the **bottom status bar**. On save, fetches an
  acorn confetti particle (re-uses `acorn_01` atlas).
- **Render strategy:** same anatomy as §2.2.3, slightly darker honey
  coat; carries an acorn in mouth during fetch animation (SVG overlay
  parented to the head bone).
- **Idle behaviors:** sit-pose, blink 3-7 s, tail flick 20-40 s.
- **Sleep pose:** curled at the left end of the status bar; breathing
  animation as §2.2.1.
- **Trigger animations:** `engine.save` → fetch (runs to the right end
  of the status bar, picks up a baked acorn, trots back to original
  slot — 1.6 s end-to-end).
- **Perf budget:** 0.4 ms idle; 1.1 ms during fetch (body translation
  + 1 acorn SVG transform).

#### 2.2.5 `raccoon_01` — Trash Panda

- **Role:** lives in a **corner of the property inspector**, peeking
  out from behind property drawers when the user expands one.
- **Render strategy:** SDF body + shader striped tail (UV-modulated
  alternating colour bands) + SVG mask + paws + ears.
- **Idle behaviors:** blink 3-7 s; ear twitch 15-30 s; peek-in /
  peek-out every 60-180 s.
- **Sleep pose:** curled inside the inspector corner, tail wrapped
  over the eyes; breathing animation as §2.2.1.
- **Trigger animations:** `property_inspector.drawer_expand` →
  rummage (one paw reaches into the drawer for 0.6 s, withdraws);
  `property_inspector.drawer_collapse` → peek out and look around.
- **Perf budget:** 0.35 ms idle; 0.9 ms during rummage.

#### 2.2.6 `raccoon_02` — Bandit Raccoon

- **Role:** **floats between panels** — every ~10 minutes, swipes
  a sticker from a panel corner and scampers to a new corner.
- **Render strategy:** same anatomy as §2.2.5 + a single sticker SVG
  parented to the right paw during the swipe sequence.
- **Idle behaviors:** small body sway every 5-10 s (looking around);
  blink 3-7 s.
- **Sleep pose:** lies flat in the last-visited corner during user
  idle ≥ 60 s; breathing animation as §2.2.1.
- **Trigger animations:** `engine.idle_600s` → swipe (cross-panel
  scamper, ~2 s, picks up a sticker on the way and drops it in the
  destination corner). Gated by `settings.ui.easter_eggs`.
- **Perf budget:** 0.3 ms idle; 1.5 ms during swipe (full body
  translation + sticker grab handoff).

#### 2.2.7 `red_panda_01` — Red Panda Naphour

- **Role:** lives on the **toolbar baseline**, lying down like a
  draft excluder along the bottom edge of the toolbar.
- **Render strategy:** SDF body (long, low silhouette) + shader russet
  fur + SVG eye mask + ears + white face patches.
- **Idle behaviors:** blink 3-7 s; ear twitch 15-30 s; deep breathing
  during sleep (4 s cycle as §2.2.1).
- **Sleep pose:** **default state** — full-body recline along the
  toolbar baseline; the creature is essentially permanently napping.
  Stretch animation only on user-triggered events.
- **Trigger animations:** `theme.switch` → stretch and reposition
  (0.9 s); `engine.error` → groggy head lift (0.3 s).
- **Perf budget:** 0.25 ms idle (mostly cached); 0.5 ms during stretch.

#### 2.2.8 `red_panda_02` — Climber Red Panda

- **Role:** clings to the **scrollbar of any scrollable panel** that's
  long enough (> 300 px). Climbs up / down with scroll.
- **Render strategy:** SDF body with claw-grip pose + shader russet
  fur + SVG face. Hands and feet anchor to the scrollbar thumb.
- **Idle behaviors:** small body sway 8-15 s; blink 3-7 s; tail tip
  flick 20-40 s.
- **Sleep pose:** hangs slumped on the thumb when scroll has been
  idle for ≥ 90 s; breathing animation as §2.2.1.
- **Trigger animations:** `scroll.start` → tighten grip + climb in
  scroll direction (continuous, follows scroll velocity); `scroll.end`
  → ease back to slumped pose over 0.3 s.
- **Perf budget:** 0.3 ms idle; 0.6 ms during active scroll.

#### 2.2.9 `panda_01` — Bamboo Panda

- **Role:** lives in the **scene outliner** at the bottom of the
  panel, chewing on a bamboo stalk. As it chews, decorative leaves
  grow on the panel's left border.
- **Render strategy:** SDF body + shader white fur + SVG black ear /
  eye / muzzle patches + procedural bamboo overlay (drawlist polygon)
  + SVG leaf growths on the panel border (placed by the leaf-growth
  scheduler, capped at 4).
- **Idle behaviors:** chew animation (jaw open/close at 1 Hz when
  bamboo is held); blink 3-7 s; bamboo grip switch every 30-60 s.
- **Sleep pose:** drops the bamboo, slumps against the outliner inner
  edge; breathing animation as §2.2.1.
- **Trigger animations:** every successful save → grow one new leaf
  on the panel border (up to the cap of 4; oldest leaf fades out
  when a fifth would spawn). `engine.scene_loaded` → fresh bamboo
  appears in paws (replace any worn bamboo).
- **Perf budget:** 0.4 ms idle (chew + 4 cached border leaves);
  0.7 ms during a leaf-grow event.

#### 2.2.10 `porcupine_01` — Baby Porcupine

- **Role:** lives in the **margin around the error popup**; rolls
  into a ball when the user clicks an error toast.
- **Render strategy:** SDF underbody + shader soft fur (cream belly,
  brown back) + SVG quill cluster (≈ 20 short cream strokes around
  the silhouette) + SVG face.
- **Idle behaviors:** blink 3-7 s; nose twitch 8-15 s; static while
  no errors are showing.
- **Sleep pose:** curls into a soft ball at the lower-right corner
  of the error popup; breathing animation as §2.2.1.
- **Trigger animations:** `editor.error_toast.click` → curl into a
  ball (quills tuck inward, 0.4 s); `editor.error_toast.dismiss`
  → uncurl, peek out (0.5 s).
- **Perf budget:** 0.2 ms idle; 0.6 ms during curl.

#### 2.2.11 `porcupine_02` — Quill Porcupine

- **Role:** lives in the **toolbar hover area**; quills bristle when
  the cursor enters the toolbar (delightful interactivity).
- **Render strategy:** shader quill noise (procedural radial spikes
  driven by a per-instance bristle-amount uniform) + SDF body + SVG
  face / belly.
- **Idle behaviors:** quill bristle responds continuously to cursor
  proximity (≤ 120 px). Blink 3-7 s. Quill bristle decays back to
  rest over 0.6 s once cursor leaves.
- **Sleep pose:** flat against the toolbar edge with quills fully
  relaxed; breathing animation as §2.2.1.
- **Trigger animations:** `input.cursor_in_toolbar` proximity → quills
  raise (continuous; amplitude proportional to inverse distance);
  `engine.build_failure` → full bristle (0.8 s spike, then decay).
- **Perf budget:** 0.5 ms idle (proximity + cached quill render);
  0.9 ms during full bristle.

#### 2.2.12 `hedgehog_01` — Tiny Hedgehog

- **Role:** lives in the **spawn menu modal** (the `+ Add` modal).
  Balances a single leaf on its back-quills while the modal is open.
- **Render strategy:** SDF body + shader quill noise + SVG belly + a
  single SVG leaf parented to the back of the body (the leaf is the
  current theme's `leaf_01` palette pick).
- **Idle behaviors:** blink 3-7 s; nose twitch 8-15 s; leaf gentle
  rotational sway (±4°, 2 s cycle) — the leaf is always present
  while the modal is open.
- **Sleep pose:** curled in the bottom-right corner of the modal
  when the modal has been open ≥ 60 s without interaction;
  breathing animation as §2.2.1.
- **Trigger animations:** `spawn_menu.item_added` → quick wiggle
  (0.3 s); `spawn_menu.close` → small wave goodbye with the front
  paw (0.5 s).
- **Perf budget:** 0.2 ms idle (most state cached); 0.5 ms during
  wiggle.

### 2.3 Cross-link to existing roster

The fourteen woodland creatures in
[`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md)
join the unified roster unchanged. Quick recall — they are:

| ID | Default role | New theme that promotes them |
|---|---|---|
| `fox_01` | toolbar idle mascot | `teengirl_notebook`, `cozy_diary` |
| `deer_01` | sidebar peek mascot | `cottagecore_garden` |
| `owl_01` | error popup | `cozy_diary` (paired with `porcupine_01`) |
| `frog_01` | toolbar hop | `kawaii_planner` |
| `rabbit_01` | progress bar | `cottagecore_garden` |
| `butterfly_01` | save event | `teengirl_notebook`, `scrapbook_summer` |
| `bee_01` | build event | `scrapbook_summer` |
| `snail_01` | loading | `cottagecore_garden` (reduced-motion default) |
| `mushroom_01` | viewport corner | `cottagecore_garden` |
| `acorn_01` | confetti | `cozy_diary` (fetched by `golden_02`) |
| `fern_01` | panel border | `cozy_diary`, `cottagecore_garden` |
| `leaf_01` | autumn ambient | `cozy_diary` |
| `flower_01` | scene-root badge | `cottagecore_garden`, `kawaii_planner` |
| `pinecone_01` | code-mode bookmark | `cozy_diary` |

Total unified roster: **14 + 12 = 26 creatures**.

---

## 3. Theme variants

All six themes are siblings under the diary umbrella. Each carries the
same shared-contract surface (§1.2). The table below is the at-a-glance
manifest; §3.1 – §3.6 detail each variant.

| Theme ID | Vibe | Palette accent | Default creatures | Background shader | Font picks (header / body / code) |
|---|---|---|---|---|---|
| `teengirl_notebook` | the original — lined paper, washi tape, hot-pink | cream + pink + lilac + mint + navy ink | `fox_01`, `butterfly_01`, `sparkle` sticker | ruled paper with red margin | Caveat / Quicksand / Fira Code |
| `scrapbook_summer` | bright, photographic, holiday-vibes | sky-blue + sunshine-yellow + watermelon-pink + grass-green | `golden_01`, `butterfly_01`, `bee_01` | gradient sky with washi photo-corners | Caveat / Comfortaa / Fira Code |
| `cozy_diary` | warm autumn, leather journal | dusty rose + caramel + sage + cream | `red_panda_01`, `fox_01`, `leaf_01` (autumn) | cream parchment with leather edge nine-slice | Patrick Hand / Quicksand / JetBrains Mono |
| `bullet_journal` | minimal grid, dot-pattern, ink + pastel highlight | white + soft black + 4 pastel highlights | `hedgehog_01`, `porcupine_01` | dot-grid shader | Nunito / Nunito / Cascadia Code |
| `cottagecore_garden` | floral, herbal, embroidered | mossy green + cream + lavender + peach | `rabbit_01`, `deer_01`, `mushroom_01`, `flower_01` | linen weave shader with embroidered border | Patrick Hand / Quicksand / Fira Code |
| `kawaii_planner` | sticker-overload, neon-pastel | pastel pink + mint + lavender + butter yellow | `cat_01`, `panda_01`, `porcupine_01` | grid paper with confetti shader | Caveat / Quicksand / Fira Code |

### 3.1 `teengirl_notebook` — the original

- **Vibe:** classroom notebook with washi tape, glitter pens, sticker
  collection on the inside cover. Hot-pink accents.
- **Palette:** verbatim from
  [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md)
  §1.1 (light) and §1.2 (dark). 17 palette rows; both variants ship.
- **Default creature roster:** `fox_01` (toolbar), `butterfly_01`
  (status bar / save), plus the `sparkle` sticker decoration on
  default panels. Three slots active.
- **Background shader:** §5.1 of the base theme — `fs_ruled_paper`,
  horizontal blue rules at 24 px, red margin at `x = 32 px`, soft
  right-edge highlight implying page curl.
- **Nine-slice border set:**
  - `panel` — washi-tape (`theme_teengirl_notebook` §3.1).
  - `toolbar` — lined paper (`theme_teengirl_notebook` §3.4).
  - `modal` — washi-tape polka-dot.
  - `tooltip` — sticky-note folded corner.
  - `code_block` — graph-paper grid (3 × 3 PNG tile, 24 px spacing).
  - `status_bar` — torn-paper edge (`theme_teengirl_notebook` §3.3).
- **Font picks:** Caveat (header) / Quicksand (body) / Fira Code (code) /
  Indie Flower (decorative).
- **Seasonal flavour:** `summer` by default; switches to `autumn`
  when the parent shell signals an autumn-season override.

### 3.2 `scrapbook_summer` — bright, photographic, holiday-vibes

- **Vibe:** travel scrapbook — washi photo-corners, bright sky
  gradients, polaroid frames.
- **Palette (light variant):**

  | Role | Hex | DPG colour |
  |---|---|---|
  | Primary surface — paper white | `#FCFAF3` | `[252, 250, 243, 255]` |
  | Panel base — sun-bleached cream | `#F4ECD8` | `[244, 236, 216, 255]` |
  | Panel border — kraft paper | `#C6A874` | `[198, 168, 116, 230]` |
  | Ink — deep ocean | `#1E3A5F` | `[ 30,  58,  95, 255]` |
  | Body — slate | `#3B4654` | `[ 59,  70,  84, 255]` |
  | Accent 1 — sky blue | `#7FC8E8` | `[127, 200, 232, 255]` |
  | Accent 2 — sunshine yellow | `#FFD43B` | `[255, 212,  59, 255]` |
  | Accent 3 — watermelon pink | `#FF6F8D` | `[255, 111, 141, 255]` |
  | Accent 4 — grass green | `#7BC275` | `[123, 194, 117, 255]` |
  | Success | `#5BC18A` | `[ 91, 193, 138, 255]` |
  | Warning | `#F2BB55` | `[242, 187,  85, 255]` |
  | Error | `#E85A6C` | `[232,  90, 108, 255]` |

  Dark variant exists but is a low-priority follow-up (the scrapbook
  metaphor is daylit; users who want a dark editor pick `cozy_diary`).
- **Default creature roster:** `golden_01` (toolbar — wags on
  build success), `butterfly_01` (status bar — save), `bee_01`
  (build event).
- **Background shader:** **`fs_sky_gradient`** — recipe builds on the
  base `fs_ruled_paper` template:
  - Vertical gradient `accent_1 (top) → primary_surface (bottom)`.
  - Three subtle white cloud arcs at `uv.y ∈ {0.25, 0.55, 0.85}` with
    `smoothstep(0.45, 0.5, noise)` masking.
  - Washi photo-corners as overlay nine-slice at each panel corner
    (kraft-paper colour, 16 × 16, 4 px overlap onto the panel).
- **Nine-slice border set:** `panel` = polaroid (white border 8 px on
  three sides, 24 px on bottom for the caption strip); `toolbar` =
  washi photo-corner; `modal` = polaroid frame; `tooltip` = kraft
  paper torn edge; `code_block` = kraft + dashed lines; `status_bar`
  = washi tape strip.
- **Font picks:** Caveat (header) / Comfortaa (body) / Fira Code
  (code) / Patrick Hand (decorative).
- **Seasonal flavour:** `summer` — locked.

### 3.3 `cozy_diary` — warm autumn, leather journal

- **Vibe:** worn leather travel journal, autumn leaves pressed between
  pages, ink and caramel tones. The "default for users who want a
  warmer editor".
- **Palette (light variant — "Warm Parchment"):**

  | Role | Hex | DPG colour |
  |---|---|---|
  | Primary surface — parchment | `#F5E6C8` | `[245, 230, 200, 255]` |
  | Panel base — cream | `#EFE0BE` | `[239, 224, 190, 255]` |
  | Panel border — leather edge | `#7C5532` | `[124,  85,  50, 230]` |
  | Ink — sepia | `#3B2A1C` | `[ 59,  42,  28, 255]` |
  | Body — coffee brown | `#5C4630` | `[ 92,  70,  48, 255]` |
  | Accent 1 — dusty rose | `#C97D7A` | `[201, 125, 122, 255]` |
  | Accent 2 — caramel | `#D4956A` | `[212, 149, 106, 255]` |
  | Accent 3 — sage | `#9BB28C` | `[155, 178, 140, 255]` |
  | Accent 4 — moss | `#6D7C5A` | `[109, 124,  90, 255]` |
  | Success | `#7AAA66` | `[122, 170, 102, 255]` |
  | Warning | `#D4A04A` | `[212, 160,  74, 255]` |
  | Error | `#B85040` | `[184,  80,  64, 255]` |

- **Palette (dark variant — "Midnight Journal"):** swap parchment for
  deep walnut `#2E2018`; ink becomes warm cream `#F0E1C5`; accents
  brighten by 10 % L*.
- **Default creature roster:** `red_panda_01` (toolbar, napping),
  `fox_01` (alternate toolbar slot — switches with red panda on each
  scene load for variety), `leaf_01` (autumn ambient — 1-3 drifting
  leaves), optional `pinecone_01` (bookmarks in code mode).
- **Background shader:** **`fs_parchment`** — recipe is the base
  `fs_ruled_paper` parameterised with:
  - Base colour = parchment cream; rule colour = brown ink at 40 %.
  - Add `value_noise(uv * 4) * 0.06` to simulate parchment fibre.
  - Soft burnt-edge vignette: `smoothstep(0.8, 1.0, dist_to_edge)` mixed
    with leather-edge colour at 35 % alpha.
- **Nine-slice border set:** `panel` = leather edge (8 px); `toolbar`
  = stitched-leather strip; `modal` = embossed leather (raised
  highlight on top/left, shadow on bottom/right); `tooltip` = tea-
  stained paper torn edge; `code_block` = sepia ink frame; `status_bar`
  = leather strap.
- **Font picks:** Patrick Hand (header) / Quicksand (body) /
  JetBrains Mono (code) / Indie Flower (decorative).
- **Seasonal flavour:** `autumn` — promotes `leaf_01` to active and
  re-tints all creature palettes to autumn variants.

### 3.4 `bullet_journal` — minimal grid, dot-pattern, ink + pastel highlight

- **Vibe:** a clean bullet-journal page; precise dotted grid, sparing
  pastel highlights, crisp ink. The "minimalist diary" pick — most
  restrained of the family.
- **Palette (light variant):**

  | Role | Hex | DPG colour |
  |---|---|---|
  | Primary surface — bright white | `#FFFFFF` | `[255, 255, 255, 255]` |
  | Panel base — off-white | `#F8F6F2` | `[248, 246, 242, 255]` |
  | Panel border — pencil grey | `#B0AAA0` | `[176, 170, 160, 200]` |
  | Ink — soft black | `#1A1A1A` | `[ 26,  26,  26, 255]` |
  | Body — slate | `#2E2E32` | `[ 46,  46,  50, 255]` |
  | Muted body | `#7A7680` | `[122, 118, 128, 255]` |
  | Accent 1 — pastel pink | `#F5C7CB` | `[245, 199, 203, 255]` |
  | Accent 2 — pastel mint | `#C9E8D5` | `[201, 232, 213, 255]` |
  | Accent 3 — pastel lavender | `#D6CCEA` | `[214, 204, 234, 255]` |
  | Accent 4 — pastel butter | `#F8E8B5` | `[248, 232, 181, 255]` |
  | Success | `#6FB388` | `[111, 179, 136, 255]` |
  | Warning | `#E0B45A` | `[224, 180,  90, 255]` |
  | Error | `#D45A6C` | `[212,  90, 108, 255]` |

- **Default creature roster:** `hedgehog_01` (spawn modal),
  `porcupine_01` (error popup). Intentionally a tiny roster of two,
  matching the minimalist vibe.
- **Background shader:** **`fs_dot_grid`** — recipe:
  - Background = primary surface.
  - Dots at `(px % 16, py % 16)` within radius 1.2 px, ink colour at
    35 % alpha.
  - Optional thicker dot every 5th (page-section marker) at 60 % alpha.
- **Nine-slice border set:** `panel` = single 1 px pencil-grey
  stroke (no decoration); `toolbar` = same; `modal` = double 1 px
  stroke with 3 px inner padding; `tooltip` = single pencil stroke
  + 4 px inner shadow; `code_block` = single 1 px stroke; `status_bar`
  = single 1 px stroke.
- **Font picks:** Nunito (header **and** body, weights 500 / 400) /
  Cascadia Code (code) / Patrick Hand (decorative — used sparingly).
- **Seasonal flavour:** `spring` (the pastels lean fresh / quiet); the
  theme is intentionally season-light, so creature seasonal variants
  default to their spring skins.

### 3.5 `cottagecore_garden` — floral, herbal, embroidered

- **Vibe:** cottage kitchen window, embroidered linen, dried herbs,
  pressed flowers. Heavier on plant motifs than animal ones.
- **Palette (light variant):**

  | Role | Hex | DPG colour |
  |---|---|---|
  | Primary surface — fresh linen | `#F4EFE0` | `[244, 239, 224, 255]` |
  | Panel base — cream | `#EBE5D0` | `[235, 229, 208, 255]` |
  | Panel border — embroidered moss | `#6B8456` | `[107, 132,  86, 220]` |
  | Ink — herb green | `#3D4F2E` | `[ 61,  79,  46, 255]` |
  | Body — earth brown | `#5A4A38` | `[ 90,  74,  56, 255]` |
  | Accent 1 — mossy green | `#7FA864` | `[127, 168, 100, 255]` |
  | Accent 2 — cream | `#F8F0DA` | `[248, 240, 218, 255]` |
  | Accent 3 — lavender | `#B8A4D4` | `[184, 164, 212, 255]` |
  | Accent 4 — peach | `#F2B889` | `[242, 184, 137, 255]` |
  | Sticker — embroidered floral | `#C97D7A` | `[201, 125, 122, 255]` |
  | Success | `#7AAA66` | `[122, 170, 102, 255]` |
  | Warning | `#E0B45A` | `[224, 180,  90, 255]` |
  | Error | `#B85040` | `[184,  80,  64, 255]` |

- **Default creature roster:** `rabbit_01` (progress bar), `deer_01`
  (sidebar peek), `mushroom_01` (viewport corner), `flower_01`
  (scene outliner badge). Largest creature roster of the family — four
  slots active.
- **Background shader:** **`fs_linen_weave`** — recipe builds on the
  base ruled-paper template:
  - Base colour = fresh linen.
  - Cross-hatch via two perpendicular sine bands at 4 px spacing,
    blended in at 6 % alpha each (warp + weft).
  - Tiny seed noise dotted at 30 % alpha to simulate linen fibre.
- **Nine-slice border set:** `panel` = embroidered border (3 px
  stitch-pattern repeat in mossy green); `toolbar` = herb-sprig
  border (sage SVG running motif); `modal` = pressed-flower frame
  (corner clusters in peach / lavender); `tooltip` = linen torn
  edge; `code_block` = simple cream-on-linen frame; `status_bar` =
  embroidered baseline.
- **Font picks:** Patrick Hand (header — looks handwritten, slightly
  script-like) / Quicksand (body) / Fira Code (code) / Caveat
  (decorative).
- **Seasonal flavour:** `spring` — promotes `flower_01` and
  re-tints other creatures to spring variants.

### 3.6 `kawaii_planner` — sticker-overload, neon-pastel

- **Vibe:** Korean stationery aisle; overwhelming pastel sticker
  variety, grid paper, confetti scatter. The maximalist diary pick.
- **Palette (light variant):**

  | Role | Hex | DPG colour |
  |---|---|---|
  | Primary surface — bright pastel white | `#FFFCF7` | `[255, 252, 247, 255]` |
  | Panel base — pastel cream | `#FBF3EC` | `[251, 243, 236, 255]` |
  | Panel border — pencil pink | `#E8A8C2` | `[232, 168, 194, 200]` |
  | Ink — soft navy | `#2F2A4A` | `[ 47,  42,  74, 255]` |
  | Body — plum grey | `#5A4F70` | `[ 90,  79, 112, 255]` |
  | Accent 1 — pastel pink | `#FFB8D9` | `[255, 184, 217, 255]` |
  | Accent 2 — pastel mint | `#B8E8C8` | `[184, 232, 200, 255]` |
  | Accent 3 — pastel lavender | `#D8C0F0` | `[216, 192, 240, 255]` |
  | Accent 4 — butter yellow | `#FFE89F` | `[255, 232, 159, 255]` |
  | Sticker — hot pink | `#FF6FB5` | `[255, 111, 181, 255]` |
  | Sticker — sky blue | `#7FC8E8` | `[127, 200, 232, 255]` |
  | Sticker — glitter gold | `#F5C84B` | `[245, 200,  75, 255]` |
  | Success | `#7BD0A0` | `[123, 208, 160, 255]` |
  | Warning | `#FFCC6A` | `[255, 204, 106, 255]` |
  | Error | `#FF7A8A` | `[255, 122, 138, 255]` |

- **Default creature roster:** `cat_01` (title bar), `panda_01`
  (scene outliner), `porcupine_01` (error popup). Plus sticker
  density turned up to ~6 stickers per panel default (vs. 2 in the
  other themes).
- **Background shader:** **`fs_grid_confetti`** — recipe:
  - Base = primary surface.
  - 12 × 12 px grid lines in pastel pink at 18 % alpha.
  - Confetti layer: per-cell deterministic random sticker stamp
    (`heart`, `star`, `sparkle`, `flower`) at ~6 % per-cell density,
    rotated by `hash(cell_id) % 360°`, scale `0.3`.
- **Nine-slice border set:** `panel` = washi tape (multiple colour
  variants — pink / mint / lavender / butter; one picked per panel
  role); `toolbar` = pink washi tape; `modal` = polka-dot pink;
  `tooltip` = sticky note (yellow accent); `code_block` = grid frame
  in pink-on-pastel; `status_bar` = scalloped pink trim.
- **Font picks:** Caveat (header) / Quicksand (body) / Fira Code
  (code) / Indie Flower (decorative — used heavily here).
- **Seasonal flavour:** `summer` (the palette is most-saturated and
  reads "summer-stationery"); creature seasonal variants pick their
  summer skins.

---

## 4. Theme switching contract

The user-facing requirement is **runtime switch between variants
without restart**, with creatures gracefully fading in / out across
the transition.

### 4.1 API sketch

```python
# python/pharos_engine/ui/editor/theme.py (Phase A scaffold)
def apply_diary_theme(
    theme_id: Literal[
        "teengirl_notebook",
        "scrapbook_summer",
        "cozy_diary",
        "bullet_journal",
        "cottagecore_garden",
        "kawaii_planner",
    ],
    variant: Literal["light", "dark"] = "light",
) -> ThemeHandle:
    """Apply a diary-family theme; returns a handle for hot-swap teardown.

    Hot-swap by calling `apply_diary_theme(other_id)` — the previous
    handle is torn down via the captured `bind_theme()` undo step (the
    same pattern already used by `get_accent_button_theme()`).
    """
```

### 4.2 Switch sequence

1. **`t = 0` ms** — user picks the new theme in the editor's settings
   panel.
2. **`t = 0-50` ms** — creature roster from the **outgoing** theme
   fades out: each creature's alpha animates `1.0 → 0.0` over 200 ms,
   and the scheduler stops dispatching their idle ticks during this
   window. New creatures are *not* yet visible.
3. **`t = 50` ms** — DPG style vars and palette constants swap; the
   previous handle's `bind_theme` rollback runs.
4. **`t = 50-80` ms** — new theme's background-shader bake runs into
   a DPG raw texture; new theme's nine-slice border PNGs (if any) are
   loaded; new theme's font registry is bound. This is the perf-budget
   hot spot — see §7.
5. **`t = 80-100` ms** — creature roster from the **incoming** theme
   fades in: each creature alpha animates `0.0 → 1.0` over 200 ms,
   starting from a static sleeping pose so the transition reads as
   "the cat noticed the lights changed and stretched out".
6. **`t = 100` ms** — `theme.switch.complete` event fires. Creatures
   now respond normally; any active one-shot animation (`butterfly_01`
   mid-flight, `bee_01` mid-dive) is **cancelled and reset** during
   the swap to avoid orphaned palettes.

### 4.3 What is preserved across the switch

- **Selected entity** in the scene outliner.
- **Open panels** and their dock positions.
- **Code Mode** buffer contents and cursor position.
- **Viewport camera** transform.
- **Sticker placements** at default panel slots — the *catalog* of
  stickers swaps (each theme has its own preferred sticker set), but
  user-placed custom stickers persist across the switch (they re-tint
  to the new palette's `Sticker` accent column).

---

## 5. User customisation

Theme behaviour is configurable through `config/editor_theme.yml`,
which maps onto the `Settings.ui` dataclass (Phase A work).

### 5.1 Settings keys

```yaml
ui:
  theme: "cozy_diary"               # required; one of the six theme IDs
  variant: "light"                  # "light" or "dark" (some themes light-only)
  creature_animations: true         # global on/off for the creature layer
  creatures:
    disabled: ["raccoon_02"]        # per-creature opt-out (catalog IDs)
    extra: ["fox_01", "flower_01"]  # additions beyond the theme's defaults
  stickers:
    enabled: true                   # off by default in headless / CI
    density: "normal"               # "minimal" | "normal" | "maximal"
  reduced_motion: false             # mirrors OS prefers-reduced-motion
  easter_eggs: true                 # gates rare one-shots (mushroom puff, raccoon swipe)
  seasonal_override: null           # null | "summer" | "autumn" | "winter" | "spring"
```

### 5.2 Resolution order

1. OS `prefers-reduced-motion` query → if `true`, force
   `reduced_motion = true` regardless of the YAML value.
2. CI / headless detection → force `creature_animations = false` and
   `stickers.enabled = false`.
3. `config/editor_theme.yml` (user file under `~/.config/pharos_engine/`).
4. Built-in theme default (the per-theme manifest at §3.x).

### 5.3 Per-creature opt-out semantics

- `creatures.disabled` is a deny-list applied **after** the theme's
  default roster is computed; any ID in the list is silently removed.
- `creatures.extra` is an allow-list applied last; any ID added must
  exist in the unified 26-creature catalog (else logged as a warning
  at theme-apply time, not an error).
- Slot conflicts are resolved by the existing slot-policy module
  (`idle_animation_system_2026_06_03.md` §3); if a slot is already
  occupied by a default creature and `extra` adds another for the
  same slot, the default keeps the slot and the extra is dropped.

### 5.4 Per-theme palette overrides (advanced)

Users may override individual palette rows without forking the theme:

```yaml
ui:
  theme: "cozy_diary"
  palette_overrides:
    "Accent 1 — dusty rose": "#D88B8B"
```

Override keys are the human-readable "Role" column from the §3.x
tables. Unknown keys log a warning and are ignored.

---

## 6. Implementation phase plan

Each phase is one PR with the existing 5-row checklist (palette ✅,
font ✅, theme switch ✅, headless test ✅, visual regression
sample ✅).

### Phase A — `teengirl_notebook` + 3 creatures (MVP)

- **Goal:** prove the contract end-to-end on the simplest possible
  surface.
- **Scope:**
  - One theme (`teengirl_notebook`, both light and dark variants).
  - Three creatures (`fox_01`, `butterfly_01`, plus the `sparkle`
    sticker decoration).
  - Settings → `ui.theme`, `ui.creature_animations` only.
  - Theme switch only between `teengirl_notebook` and the
    glassmorphism baseline.
- **Files touched:** new `apply_teengirl_notebook_theme()` in
  `theme.py`; new `ui/editor/theme_assets/{nine_slice,shaders,
  stickers,widgets}.py` modules (per the base theme's Phase E plan);
  new `ui/editor/creatures/{fox_01,butterfly_01,scheduler}.py`.
- **Acceptance:**
  - `apply_teengirl_notebook_theme()` round-trips with the baseline
    in a `pytest -k theme_switch` test.
  - Idle creature tick ≤ 1 ms / frame measured by
    `pharos_engine.telemetry`.
  - One visual-regression baseline per panel (toolbar, scene
    outliner, inspector, code mode) at 1080p.

### Phase B — `cozy_diary` + `bullet_journal` + 4 more creatures

- **Goal:** validate the family contract by introducing the second
  and third themes (most-requested vibes: warm autumn + minimal grid).
- **Scope:**
  - Two more themes (`cozy_diary`, `bullet_journal`).
  - Four more creatures from the woodland catalog
    (`red_panda_01` — though new in this doc, slots in the cozy
    palette; `leaf_01`, `pinecone_01` for cozy; `hedgehog_01`,
    `porcupine_01` for bullet).
  - Theme switcher UI (settings panel dropdown).
  - All `ui.creatures.*` and `ui.stickers.*` settings keys land.
- **Files touched:** extend `theme.py` with `apply_diary_theme()` and
  the three-way switcher; add per-theme palette modules under
  `theme_assets/palettes/{cozy_diary,bullet_journal}.py`; add
  creature modules for the four new IDs.
- **Acceptance:**
  - All three themes round-trip in the switch test.
  - Theme switch wall-clock ≤ 100 ms on the CI hardware baseline.
  - Visual-regression baselines for all three themes.

### Phase C — remaining 3 themes + full 26-creature roster + theme-switcher UI

- **Goal:** ship the family.
- **Scope:**
  - Three more themes (`scrapbook_summer`, `cottagecore_garden`,
    `kawaii_planner`).
  - Remaining 19 creatures (10 woodland + 9 new from §2).
  - First-class theme-switcher UI in the settings panel (live
    preview).
  - All seasonal variants wired.
  - All `palette_overrides` plumbing.
- **Files touched:** complete the palette / creature / shader
  modules under `theme_assets/` and `creatures/`; finalise the
  settings UI surface.
- **Acceptance:**
  - All six themes covered by `pytest -k theme_family`.
  - 26 creatures registered; per-creature opt-out test passes.
  - Doc update: this file moves from "design" to "shipped" status;
    `api/ui_editor.md` cross-link added.

### Phase ordering rationale

Phase A is small enough to ship in one sprint and de-risks every
runtime decision (DPG style hot-swap, shader bake, creature
scheduler). Phase B doubles the matrix (3 themes × 6 creatures) at
moderate marginal cost — palettes and nine-slice borders are new but
the scheduler / hot-swap pathway is already validated. Phase C is
the bulk of the visual work but mostly **fills in tables** rather
than introducing new pathways, so it can be safely parallelised
across multiple PRs.

---

## 7. Performance budget

| Metric | Budget | Measured on | Notes |
|---|---|---|---|
| Theme switch wall-clock (Phase A baseline) | ≤ 100 ms | CI hardware (i7-12700, RTX 3060) | Includes shader bake + nine-slice load + font registry; **not** including OS settings-panel close. |
| Creature roster idle tick (full Phase C roster) | ≤ 2 ms / frame total | same CI hardware | Aggregate across all active creatures; woodland catalog §7 already budgets 1 ms for ≤ 5 creatures, and we cap concurrent creatures at 5 active + 1 transient. |
| Theme-switch peak frame (during 50-100 ms swap window) | ≤ 33 ms (single 30 fps frame) | same CI hardware | A single dropped frame is acceptable; sustained drop is not. |
| First-paint after theme apply | ≤ 32 ms | same CI hardware | Background shader bakes into raw texture before bind_theme returns. |
| Memory cost per active theme | ≤ 4 MB | resident set delta | Includes one baked background PNG per panel + nine-slice texture set + font glyph atlases. |
| Memory cost per creature (idle) | ≤ 256 KB | resident set delta | SDF + shader fur cache + SVG path data. |
| Memory cost per creature (active one-shot) | ≤ 1 MB transient | resident set delta | Includes intermediate frame buffers for one-shot transforms. |

### 7.1 Headroom claim

At 60 fps with a 16.7 ms frame budget, the editor renders the
viewport game in ≤ 5 ms (existing budget from `theme.py`'s
viewport-opaque rule), the editor chrome in ≤ 6 ms baseline, and
the creature layer in ≤ 2 ms — leaving ≥ 3.7 ms of headroom for the
ad-hoc one-shot peak. The theme-switch event briefly consumes the
entire frame, which is acceptable because it is a once-per-session
user action; the engine's existing telemetry pattern logs the wall
time so regressions are caught.

### 7.2 Headless / CI carve-out

Headless / CI runs force:

- `creature_animations = False` → idle tick budget = 0.
- `stickers.enabled = False` → no sticker overlay drawlist.
- `reduced_motion = True` → no shader-shimmer / wobble animation.

Theme switching itself is still exercised in CI (asserting that the
DPG style-var teardown is idempotent) but the visual-regression diff
runs against a single static-render baseline per theme.

---

## 8. Cross-links

- [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md)
  — base-theme contract; this doc inherits the §1 palette structure,
  §2 typography rules, §3 nine-slice taxonomy, §5 shader hook points,
  §6 sticker overlay system, §7 widget overrides, §8 implementation
  strategy, and §9 risk callouts.
- [`woodland_creature_catalog_2026_06_03.md`](woodland_creature_catalog_2026_06_03.md)
  — the 14 existing creatures this doc extends; design principles
  (§0), cast table (§1), per-entry detail (§2), seasonal swap-out
  summary (§3), slot assignment (§4), render-strategy distribution
  (§5), accessibility matrix (§6), perf summary (§7) all carry
  forward unchanged.
- `idle_animation_system_2026_06_03.md` — sibling doc landing in
  parallel; defines `Creature`, `CreatureScheduler`, event bindings,
  and slot policy that this doc relies on. Cross-link will go live
  once the sibling commit lands.
- [`ui_concept_art_2026_06_03.md`](ui_concept_art_2026_06_03.md) —
  source palette / sticker / layout extraction; informs §3.1 – §3.6
  palette tables.
- [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md)
  — audit of current UI patterns; the diary family must respect
  every constraint listed there.
- [`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md) — v0.4
  sprint plan; Sprint 5 ("editor notebook theme") is the parent
  envelope for the Phase A → C rollout in §6.
- [`sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) — this
  doc is indexed there per the `test_docs_inventory.py` rule.
- [`wheel_size_audit_2026_06_02.md`](wheel_size_audit_2026_06_02.md)
  — wheel-size budget; the only PNG bake-out the family ships is the
  theme-switch background cache (one PNG per theme per variant, ≤ 64
  KB each).
