# TeenGirl Notebook — Editor Theme Design

> **Status:** design doc only (Sprint 5+, 2026-06-03). No engine code lands in
> this sprint — this file is the contract Phases A-E will be cut against.
>
> **Scope:** alternate look-and-feel for the SlapPyEngine editor (`pharos_editor.ui.editor`).
> Lives alongside the existing glassmorphism theme in
> [`python/pharos_engine/ui/editor/theme.py`](../python/pharos_engine/ui/editor/theme.py).
> Opt-in via a future `apply_teengirl_notebook_theme()` entry point — never
> the default.
>
> **Non-scope:** softbody / fluid runtime code is **out of bounds** for this
> sprint per the brief. Renderer / shader work in the editor canvas only;
> game viewport keeps its existing opaque-background contract
> (see `get_viewport_opaque_theme()` in `theme.py`).
>
> **Concept art reference:**
> [`UIConceptArt/Concepts.jfif`](../UIConceptArt/Concepts.jfif) (panel layout
> sketches),
> [`UIConceptArt/Stickers.jfif`](../UIConceptArt/Stickers.jfif) (sticker
> vocabulary),
> [`UIConceptArt/download.jfif`](../UIConceptArt/download.jfif) and
> `UIConceptArt/download (1).jfif` (palette mood boards — bare path; the
> embedded `(1)` defeats markdown link parsing),
> [`UIConceptArt/image_3e1d1a30.png`](../UIConceptArt/image_3e1d1a30.png)
> (full-bleed reference render — 2.4 MB, do not read inline; ship as a
> documentation-only artefact).

---

## 1. Palette

All colours are listed as `RGB hex` plus the canonical DPG-friendly
`color = [r, g, b, a]` list (0-255 integer range, matching `_rgba()` in
`theme.py`). Alpha defaults to `255` unless a value is given.

### 1.1 Light variant — "Fresh Notebook" (default)

| Role | Hex | DPG colour |
|---|---|---|
| Primary surface — paper cream | `#FBF7EC` | `[251, 247, 236, 255]` |
| Primary surface (alt) — desaturated lilac | `#E7DDF1` | `[231, 221, 241, 255]` |
| Panel base — soft chalk white | `#F4EFE3` | `[244, 239, 227, 255]` |
| Panel border — pencil grey | `#B8B0A0` | `[184, 176, 160, 200]` |
| Ink — ballpoint navy | `#1F2F66` | `[ 31,  47, 102, 255]` |
| Body — charcoal grey | `#3B3B45` | `[ 59,  59,  69, 255]` |
| Muted body | `#7A7689` | `[122, 118, 137, 255]` |
| Disabled | `#B1ACB8` | `[177, 172, 184, 255]` |
| Accent 1 — bubblegum pink | `#FF6FB5` | `[255, 111, 181, 255]` |
| Accent 2 — highlighter yellow | `#FFE066` | `[255, 224, 102, 220]` |
| Accent 3 — mint green | `#A7E7C7` | `[167, 231, 199, 255]` |
| Sticker — hot pink | `#FF2E83` | `[255,  46, 131, 255]` |
| Sticker — neon purple | `#9D4BFF` | `[157,  75, 255, 255]` |
| Sticker — glitter gold | `#F5C84B` | `[245, 200,  75, 255]` |
| Success | `#5BC18A` | `[ 91, 193, 138, 255]` |
| Warning | `#F2BB55` | `[242, 187,  85, 255]` |
| Error | `#E85A6C` | `[232,  90, 108, 255]` |

### 1.2 Dark variant — "Midnight Diary"

A 1:1 role mapping so widget code stays identical between variants — only the
constants module swaps under `apply_teengirl_notebook_theme(variant="dark")`.

| Role | Hex | DPG colour |
|---|---|---|
| Primary surface — twilight indigo | `#1A1530` | `[ 26,  21,  48, 255]` |
| Primary surface (alt) — moonlit lilac | `#2D2447` | `[ 45,  36,  71, 255]` |
| Panel base — page-at-midnight | `#221C3D` | `[ 34,  28,  61, 240]` |
| Panel border — ribbon silver | `#5C5076` | `[ 92,  80, 118,  80]` |
| Ink — luminous chalk | `#F5EDFF` | `[245, 237, 255, 255]` |
| Body — soft lilac white | `#D6CCEA` | `[214, 204, 234, 255]` |
| Muted body | `#8A82A6` | `[138, 130, 166, 255]` |
| Disabled | `#5A5474` | `[ 90,  84, 116, 255]` |
| Accent 1 — bubblegum pink | `#FF6FB5` | `[255, 111, 181, 255]` |
| Accent 2 — highlighter yellow | `#FFE066` | `[255, 224, 102, 180]` |
| Accent 3 — mint green | `#7CD9B0` | `[124, 217, 176, 255]` |
| Sticker — hot pink | `#FF2E83` | `[255,  46, 131, 255]` |
| Sticker — neon purple | `#BD7BFF` | `[189, 123, 255, 255]` |
| Sticker — glitter gold | `#FFD66E` | `[255, 214, 110, 255]` |

### 1.3 Semantic mapping to existing constants

To keep `theme.py` symmetric between the glassmorphism baseline and the new
theme, each pre-existing constant has a one-shot replacement:

| Existing constant | Light replacement | Dark replacement |
|---|---|---|
| `_GLASS_BG` | paper cream | twilight indigo |
| `_GLASS_PANEL` | panel base | page-at-midnight |
| `_GLASS_BORDER` | panel border | panel border (dark) |
| `_GLASS_ACCENT` | bubblegum pink | bubblegum pink |
| `_GLASS_TEXT` | ink — ballpoint navy | ink — luminous chalk |
| `_GLASS_DIM` | muted body | muted body (dark) |
| `_GLASS_HOVER` | accent 3 mint @ 40 % | accent 1 pink @ 30 % |
| `_GLASS_ACTIVE` | accent 1 pink | accent 1 pink (brighter) |
| `_VIEWPORT_BG` | paper cream | twilight indigo |

The game-viewport rule from `get_viewport_opaque_theme()` is preserved
verbatim — the notebook texture **only** lives in editor chrome.

---

## 2. Typography

All recommended fonts are SIL Open Font License (OFL) 1.1 — safe to vendor
under `python/pharos_engine/ui/editor/assets/fonts/` and redistribute with the
wheel. Each font ships compressed (subset Latin + Latin-Extended-A for the
diacritics common in user content).

### 2.1 Font picks

| Role | Primary | Fallback | Notes |
|---|---|---|---|
| Headers (panel titles, modal banners, dock tab text) | **Caveat** (variable 400-700) | Patrick Hand → system serif | Handwritten ballpoint; Caveat's variable axis lets us bump weight on hover without a font swap. |
| Body (property labels, inspector rows, tooltips) | **Quicksand** (300/400/500/700) | Comfortaa → Nunito → system sans | Friendly rounded sans with full Latin-Extended-A coverage. |
| Code (Code Mode editor, REPL, shader source) | **Fira Code** (400/500) | Cascadia Code → JetBrains Mono → monospace | Pixel-art-mono alternative `PixelOperatorMono` listed as opt-in for the "sticker terminal" look. |
| Decorative accent (sticker labels, doodled callouts) | **Indie Flower** | Patrick Hand | Used sparingly — capped at one decorative string per modal. |

### 2.2 Size table

| Widget kind | Size (px) | Font + weight |
|---|---|---|
| H1 — window title / modal banner | 28 | Caveat 700 |
| H2 — panel title (dock tab, scene outliner header) | 22 | Caveat 600 |
| H3 — section header inside property inspector | 18 | Caveat 600 |
| Body — property labels, tree rows, button text | 14 | Quicksand 500 |
| Body small — table cells, status bar | 13 | Quicksand 400 |
| Caption — tooltips, hint text, "fill-in-the-blank" placeholders | 12 | Quicksand 400, italic |
| Code body — code mode buffer, REPL, shader source | 14 | Fira Code 400 |
| Code small — inline `code` in tooltips | 12 | Fira Code 400 |
| Decorative | 18-26 | Indie Flower / Patrick Hand |

### 2.3 Loading contract

- Fonts are registered as **`FontResource`** entries on theme activation —
  same lazy-load pattern as the existing texture manager. They are **not**
  loaded at import time; that keeps headless tests cheap.
- DPG font registry must be populated *before* `bind_theme()`; the existing
  `apply_editor_theme()` ordering rule (`create_context()` → fonts → theme →
  `create_viewport()`) is unchanged.
- A failure to load any handwritten / decorative font silently degrades to
  the next fallback in the chain. Body and code fonts are required — if both
  Quicksand and its fallbacks fail, the call raises (caught by the editor
  shell as a non-fatal warning).

---

## 3. Nine-slice patterns

Procedural-first. We only ship a PNG when a runtime shader is either too
expensive or DPG can't host one (DPG draws via `imgui` — fragment shaders
inside an arbitrary widget are not portable; the workaround is either a
canvas drawlist with pre-rasterised textures, or shader output baked once
on theme activation). See §9 for the fallback policy.

### 3.1 Panel border — washi-tape

- **Source PNG:** `assets/9slice/washi_tape.png` — 64 × 16 px, 9-slice
  margins `(8, 8, 8, 8)`.
- **Pattern:** repeating diagonal stripes (alternating pastel pink / mint),
  hand-drawn deckle edge, 4 % per-pixel hue jitter so the runtime tiling
  doesn't visibly band.
- **Subvariants:** pink, mint, lilac, polka-dot. Picked per panel role
  (scene outliner = mint, inspector = pink, code mode = lilac, modals =
  polka-dot).
- **Drop-shadow:** 4 px soft, 30 % alpha, offset `(2, 3)`.

### 3.2 Button — "sticker peel"

- **Procedural** — rendered via the DPG drawlist on theme load and cached
  into an `mvRawTexture`. One texture per `(role, size, state)` bucket.
- **Effect stack:** rounded rect → 1 px ink-navy stroke → drop-shadow → a
  per-button micro-rotation between `-2°` and `+2°` (seeded by `id(widget)`
  so the rotation is stable across redraws).
- **States:** rest / hover / active / disabled. Hover adds the §5.3 glitter
  shimmer. Active flattens the rotation to 0° and deepens the shadow.

### 3.3 Tab — notebook-tab divider

- **Procedural** — torn-paper edge generated by sampling a 1-D Perlin
  ridge along the bottom 6 px of the tab rect. Active tab gets a 2-pixel
  "page underline" in ink-navy.
- **Idle vs. active:** idle is paper-cream with a 50 % alpha overlay; active
  is full opacity with the underline.
- **Falls back** to a static 9-slice PNG (`assets/9slice/tab_torn.png`,
  48 × 24) on platforms where DPG `draw_polygon` perf is unacceptable.

### 3.4 Toolbar — lined-paper texture

- **Procedural shader** (§5.1) — three horizontal blue lines, one vertical
  red margin at `x = 32 px`. Toolbar is a thin strip so the shader renders
  cheaply (one full-screen quad per frame, or once into a static texture).
- **Fallback PNG:** `assets/9slice/lined_paper.png` — 96 × 24, 9-slice
  margins `(0, 8, 0, 8)`.

---

## 4. SVG icons

All icons inline as ≤ 500-byte XML strings. Loaded into a `dict[str, str]`
at module-init time, rasterised on first use through `nanosvg` (preferred)
or `svglib + reportlab` (fallback) into DPG textures. Each icon ships in
24 × 24 logical units; the colour attribute is `currentColor` so the
runtime can re-tint without re-rasterising.

### 4.1 Toolbar tools

| Tool | Glyph | SVG XML |
|---|---|---|
| Select | heart-arrow | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 21s-7-4.5-7-11a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 1.1-.2 2.1-.6 3l3.6-1-2 4 1 3-4-2-5 5z" fill="currentColor"/></svg>` |
| Move | four-arrow flower | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><g fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 4v6m0 4v6M4 12h6m4 0h6"/><path d="M12 2l2 2-2-2-2 2zM12 22l-2-2 2 2 2-2zM2 12l2 2-2-2 2-2zM22 12l-2-2 2 2-2 2z"/></g></svg>` |
| Rotate | spiral | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 4a8 8 0 1 1-8 8 6 6 0 0 1 12 0 4 4 0 0 1-8 0 2 2 0 0 1 4 0" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>` |
| Scale | bow-tie | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M4 6l8 6-8 6V6zM20 6l-8 6 8 6V6z" fill="currentColor"/><circle cx="12" cy="12" r="2" fill="currentColor"/></svg>` |

### 4.2 Scene outliner badges

| Badge | Glyph | SVG XML |
|---|---|---|
| Entity | star | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 2l3 7h7l-6 4 2 7-6-4-6 4 2-7-6-4h7z" fill="currentColor"/></svg>` |
| Component | heart | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M12 21s-8-5-8-11a5 5 0 0 1 8-4 5 5 0 0 1 8 4c0 6-8 11-8 11z" fill="currentColor"/></svg>` |
| Group | cloud | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M6 18a4 4 0 0 1 0-8 6 6 0 0 1 12 0 4 4 0 0 1 0 8H6z" fill="currentColor"/></svg>` |
| Locked | key | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><circle cx="8" cy="12" r="4" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 12h9v3h-2v3h-3v-3h-2v-3z" fill="currentColor"/></svg>` |
| Visible | eye | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="currentColor"/></svg>` |
| Hidden | eye-slash | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z" fill="none" stroke="currentColor" stroke-width="2"/><line x1="4" y1="4" x2="20" y2="20" stroke="currentColor" stroke-width="2"/></svg>` |

### 4.3 Code Mode

| Icon | Glyph | SVG XML |
|---|---|---|
| Ballpoint pen | pen | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M4 20l4-1 11-11-3-3L5 16l-1 4z" fill="currentColor"/><path d="M14 6l3 3" stroke="#1F2F66" stroke-width="1"/></svg>` |
| Eraser | eraser | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M3 17l8-8 8 8-4 4H7l-4-4zM11 9l4-4 4 4-4 4z" fill="currentColor"/></svg>` |
| Highlighter | marker | `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"><path d="M4 20l3-3h10l3 3H4zM6 16l8-12 4 2-8 12H6z" fill="currentColor"/></svg>` |

Each `<svg>` string is < 500 bytes (whitespace-collapsed). Bundle as a
constants dict; no on-disk SVG files needed.

---

## 5. Shader effects

The editor chrome runs on top of DPG, which does not natively expose a
fragment-shader hook. The supported routes are:

1. Render the effect once at theme-activation time into a DPG raw texture
   (works for static effects like ruled paper, washi tape).
2. Animate by re-rendering a small drawlist each frame (works for selection
   wobble and glitter shimmer at acceptable cost — both are tiny rects).
3. For larger surfaces requiring per-frame compute (the full toolbar
   background under heavy panning), the engine's existing wgpu context
   (`pharos_engine.gpu`) renders a quad with WGSL and writes the texture
   back to DPG. This is the same texture-handoff pattern already used by
   the viewport panel.

Each shader below is given as a WGSL `fragment` entry point. Inputs are
the standard editor canvas inputs (`uv` in `[0, 1]` of the target rect,
`time` in seconds, plus the surface-local pixel size in `params.size`).

### 5.1 Ruled-paper background

```wgsl
// pseudocode-WGSL — design-doc only; reference impl will land in Phase C.
struct Params { size: vec2<f32>, time: f32, _pad: f32 };
@group(0) @binding(0) var<uniform> params: Params;

@fragment fn fs_ruled_paper(@location(0) uv: vec2<f32>) -> @location(0) vec4<f32> {
    let px      = uv * params.size;
    let paper   = vec3<f32>(0.984, 0.969, 0.926);          // paper cream
    let blue    = vec3<f32>(0.62 , 0.74 , 0.93 );          // line ink
    let red     = vec3<f32>(0.91 , 0.43 , 0.54 );          // margin ink
    var col     = paper;

    // horizontal rules every 24 px
    let y_in_line = abs(fract(px.y / 24.0) - 0.5) * 24.0;
    if (y_in_line < 0.6) { col = mix(col, blue, 0.55); }

    // vertical red margin at x = 32
    if (abs(px.x - 32.0) < 0.6) { col = mix(col, red, 0.85); }

    // soft right-edge highlight to imply page curl
    let edge = smoothstep(params.size.x - 16.0, params.size.x, px.x);
    col = mix(col, vec3<f32>(1.0, 1.0, 1.0), edge * 0.25);

    return vec4<f32>(col, 1.0);
}
```

### 5.2 Selection highlight — "highlighter stroke"

- Translucent yellow (`#FFE066` @ 130 alpha) overlay.
- Stroke wobble: the rect is offset by `sin(time * 2 + px.y * 0.05) * 0.8`
  pixels along the X axis — visible as a hand-drawn waver.
- Drawn as a single drawlist quad per selection; updates only when the
  selection rect changes or every 4 frames (whichever is sooner).
- Pseudocode:

```wgsl
@fragment fn fs_highlight(@location(0) uv: vec2<f32>) -> @location(0) vec4<f32> {
    let wob = sin(params.time * 2.0 + uv.y * params.size.y * 0.05) * 0.04;
    let u   = uv.x + wob;
    let on  = step(0.02, u) * step(u, 0.98);
    return vec4<f32>(1.0, 0.878, 0.4, 0.51 * on);
}
```

### 5.3 Hover glow — "glitter shimmer"

- Small 32 × 32 looping value-noise texture × pastel-pink gradient.
- Applied additively at 22 % alpha. Animation: rotate UV by
  `time * 0.5 rad`.
- Pseudocode:

```wgsl
@fragment fn fs_shimmer(@location(0) uv: vec2<f32>) -> @location(0) vec4<f32> {
    let c   = cos(params.time * 0.5);
    let s   = sin(params.time * 0.5);
    let rot = mat2x2<f32>(c, -s, s, c);
    let n   = textureSample(noise32, samp, rot * (uv - 0.5) + 0.5).r;
    let grad= mix(vec3<f32>(1.0, 0.84, 0.93), vec3<f32>(1.0, 0.43, 0.71), uv.y);
    return vec4<f32>(grad, n * 0.22);
}
```

### 5.4 Drop-shadow — "paper-curl"

- Two-tap blur (5 × 5 → 9 × 9) of the panel alpha, offset `(2, 3)`,
  darkened to `#3B3B45` @ 30 %.
- Renders once into a panel-sized RGBA texture on resize; reused until the
  panel resizes again.

---

## 6. Sticker overlay system

### 6.1 SVG sticker library

Stored exactly like the icon library (§4) — inline XML, < 500 bytes each.

| ID | Glyph | Default colour | Default rotation |
|---|---|---|---|
| `bow` | bow | hot pink `#FF2E83` | `-8°` |
| `sparkle` | 4-point sparkle | glitter gold `#F5C84B` | `+12°` |
| `smiley` | smiley face | accent 1 pink | `0°` |
| `peace` | peace sign | neon purple `#9D4BFF` | `+5°` |
| `star` | five-point star | glitter gold | `-15°` |
| `heart` | heart | bubblegum pink | `+3°` |
| `butterfly` | butterfly | mint green | `-7°` |
| `flower` | five-petal flower | accent 1 pink | `+10°` |
| `lightning` | lightning bolt | highlighter yellow | `-20°` |
| `arrow` | doodled arrow | ink navy | `+22°` |

### 6.2 Placement contract

```python
@dataclass(frozen=True)
class StickerSpec:
    svg_id: str               # one of the IDs above
    default_color: tuple[int, int, int, int]
    default_rotation: float   # degrees, signed

@dataclass(frozen=True)
class StickerPlacement:
    sticker: StickerSpec
    corner: Literal["tl", "tr", "bl", "br"]
    offset: tuple[int, int] = (-8, -8)   # px, signed; clamps inside panel
    scale: float = 1.0
    rotation_override: float | None = None
    color_override: tuple[int, int, int, int] | None = None
```

- Editor panels opt in via `panel.add_sticker(StickerPlacement)`. Stickers
  are layered above the panel content in their own drawlist (one drawlist
  per panel, drawn after content but before the viewport pop).
- Each sticker carries a drop-shadow (same parameters as §3.1) and a
  *seeded* tiny rotation jitter `±2°` on top of `default_rotation` so two
  identical stickers in the same scene look hand-placed instead of cloned.
- Defaults: scene outliner gets `bow` (top-right) and `sparkle` (bottom-left);
  property inspector gets `smiley` (top-left). All sticker placements are
  user-overridable through the theme config YAML (`config/editor_theme.yml`).
  Off by default in headless / CI mode.

### 6.3 Catalog spec

```python
STICKER_CATALOG: dict[str, StickerSpec] = {
    "bow":       StickerSpec("bow",       (255,  46, 131, 255),  -8.0),
    "sparkle":   StickerSpec("sparkle",   (245, 200,  75, 255), +12.0),
    "smiley":    StickerSpec("smiley",    (255, 111, 181, 255),   0.0),
    "peace":     StickerSpec("peace",     (157,  75, 255, 255),  +5.0),
    "star":      StickerSpec("star",      (245, 200,  75, 255), -15.0),
    "heart":     StickerSpec("heart",     (255, 111, 181, 255),  +3.0),
    "butterfly": StickerSpec("butterfly", (167, 231, 199, 255),  -7.0),
    "flower":    StickerSpec("flower",    (255, 111, 181, 255), +10.0),
    "lightning": StickerSpec("lightning", (255, 224, 102, 255), -20.0),
    "arrow":     StickerSpec("arrow",     ( 31,  47, 102, 255), +22.0),
}
```

Lookup helper signature: `def get_sticker(svg_id: str) -> StickerSpec`.
Raises `KeyError` on miss — no silent fallback.

---

## 7. Widget overrides

DPG-specific mapping. Each row pairs the upstream DPG factory with the
theme-aware visual treatment we apply on top of it.

| DPG factory | Treatment | Notes |
|---|---|---|
| `add_button` | sticker peel (§3.2) | One cached texture per `(size, role, state)`. Role is `primary` / `secondary` / `danger`. |
| `add_input_text` | "fill-in-the-blank" line | Underline only, no rounded rect; placeholder rendered in Indie Flower italic. Focus state thickens the underline by 1 px and adds a navy "I" pen-cursor blink at 1.2 Hz. |
| `add_slider_float` | highlighter strip with star marker | Track is a yellow highlighter rect; thumb is the `star` sticker @ scale 0.6 with hot-pink fill. Value label is Caveat 14. |
| `add_slider_int` | same as `add_slider_float` | Ticks rendered as faint blue notches under the highlighter strip. |
| `add_checkbox` | heart that fills when checked | Unchecked = `heart` SVG outline only. Checked = filled `heart` in accent 1 pink. Click animates a 80 ms scale punch (1.0 → 1.15 → 1.0) via drawlist. |
| `add_radio_button` | sparkle that lights on select | Selected = `sparkle` in gold; unselected = grey heart outline. |
| `add_tree_node` | notebook tab edge (§3.3) | Toggle arrow replaced with a tiny doodled arrow SVG. |
| `add_collapsing_header` | washi-tape header (§3.1) | Title in Caveat 18; chevron is a doodled arrow. |
| `add_combo` | sticky-note dropdown | Combo body rendered as a 4 px rotated sticky-note (yellow accent 2). |
| `add_tab_bar` / `add_tab` | torn-paper tabs (§3.3) | Active tab gets the page underline. Reorder cursor is the `pen` icon. |
| `add_separator` | doodled dashed line | Drawlist polygon: 8 px dashes, 4 px gaps, slight Y wobble. |
| `add_tooltip` | folded-corner sticky note | Yellow accent 2 background, ink-navy text, 6 px folded-corner highlight in drop-shadow. |
| `add_progress_bar` | washi-tape fill | Track = panel base; fill = washi-tape (pink). Thumb-end gets a `sparkle` overlay during animation. |

The override layer is a thin set of helpers — `tg_button(...)`, `tg_input_text(...)`, etc. — that
wrap the DPG factory and bind the appropriate per-item theme + drawlist
decorations. Call sites that bypass the wrapper still render in the global
glassmorphism→notebook palette, just without the sticker treatments.

---

## 8. Implementation strategy

| Phase | Deliverable | Estimated LOC | Files touched |
|---|---|---|---|
| A | Palette + font load only | ~5 | `theme.py` (new `apply_teengirl_notebook_theme()` entry point + constants block) |
| B | Nine-slice + SVG icon system | ~200 | New `ui/editor/theme_assets/__init__.py` + `icons.py`, `nine_slice.py` |
| C | Shader background + selection overlay | ~150 | New `ui/editor/theme_assets/shaders.py` (WGSL strings + raw-texture bake helpers); a thin `selection_overlay.py` |
| D | Sticker placement | ~100 | New `ui/editor/theme_assets/stickers.py` (catalog + placement); 1-line hook in `shell.py` + `scene_outliner.py` + `property_inspector.py` to register default placements behind a feature flag. |
| E | Full widget override sweep | ~300 | New `ui/editor/theme_assets/widgets.py` (`tg_button`, `tg_input_text`, …). Migrate `toolbar.py`, `scene_outliner.py`, `property_inspector.py`, `spawn_menu.py`, `code_mode_panel.py` call sites. |

Phases A, B, D are independent of softbody / fluid and ship without
touching either subsystem (constraint honoured). Phases C and E only read
from the existing `pharos_engine.gpu` and `pharos_editor.ui.editor` module
boundaries.

Each phase is one PR with its own design checklist (palette ✅, font ✅,
theme switch ✅, headless test ✅, visual regression sample ✅).

---

## 9. Risk callouts

1. **DPG fragment-shader support.** DPG draws through Dear ImGui; arbitrary
   fragment shaders inside widgets are not portable. Mitigation:
   pre-rasterise on theme activation into raw textures (panel borders,
   ruled-paper background). Only animated effects (highlight wobble,
   glitter shimmer) run through the drawlist each frame, and even those
   can fall back to a baked still texture if the per-frame cost in headless
   tests exceeds 1 ms.
2. **SVG → DPG texture rendering.** No first-party SVG rasteriser in DPG.
   Plan: prefer **nanosvg** (Python bindings) for the one-shot rasterise on
   theme activation; fall back to **svglib + reportlab** if nanosvg isn't
   importable; final fallback is a small per-icon PNG bake checked into
   `assets/icons/` and used unmodified. This keeps the wheel size under
   the 50 MB PyPI cap measured in
   [`wheel_size_audit_2026_06_02.md`](wheel_size_audit_2026_06_02.md).
3. **Font licensing.** All recommended fonts (Caveat, Patrick Hand,
   Indie Flower, Quicksand, Comfortaa, Nunito, Fira Code) are SIL OFL 1.1.
   We can vendor them under `assets/fonts/` and redistribute on PyPI. Each
   font directory gets a copy of the upstream `OFL.txt` plus a top-level
   `THIRD_PARTY_LICENSES.md` index entry.
4. **Concept-art reference files.** The five files under `UIConceptArt/`
   total ~3.2 MB — they should not ship in the wheel. Add
   `UIConceptArt/` to `MANIFEST.in`'s `prune` rules at Phase A.
5. **Theme switching at runtime.** DPG style vars cannot all hot-swap
   without a `bind_theme()` re-call. Plan: `apply_teengirl_notebook_theme()`
   tears down the previous theme via a captured handle (mirroring the
   pattern used by `get_accent_button_theme()`).
6. **Headless / CI.** Sticker placements and animated shimmer **must** be
   off by default in `pharos_engine.testing` runs — they would inflate
   visual-regression diff baselines. The theme module exposes
   `set_decorations_enabled(False)` for the visual-diff harness.
7. **Sprite-audit interaction.** The notebook theme doesn't change any
   in-game sprite anchors / atlases — but the editor `content_browser.py`
   sticker overlay must skip thumbnails to keep sprite previews honest.

---

## 10. References

### Concept art (do not inline-read; large image files)

- [`UIConceptArt/Concepts.jfif`](../UIConceptArt/Concepts.jfif) (189 KB) —
  panel-layout sketches.
- [`UIConceptArt/Stickers.jfif`](../UIConceptArt/Stickers.jfif) (242 KB) —
  sticker vocabulary reference.
- [`UIConceptArt/download.jfif`](../UIConceptArt/download.jfif) (203 KB) —
  light-palette mood board.
- `UIConceptArt/download (1).jfif` (172 KB) — dark-palette mood board.
  (Filename literal — the embedded `(1)` defeats markdown link parsing;
  use the bare path when opening in a viewer.)
- [`UIConceptArt/image_3e1d1a30.png`](../UIConceptArt/image_3e1d1a30.png)
  (2.4 MB) — full-bleed reference render.

### Engine modules to integrate against

- [`python/pharos_engine/ui/editor/theme.py`](../python/pharos_engine/ui/editor/theme.py)
  — entry point; existing glassmorphism palette + `apply_editor_theme()`
  / `get_accent_button_theme()` / `get_viewport_opaque_theme()` /
  `apply_dwm_glass()`. The notebook theme adds a sibling
  `apply_teengirl_notebook_theme()`.
- [`python/pharos_engine/ui/editor/toolbar.py`](../python/pharos_engine/ui/editor/toolbar.py)
  — Select / Move / Rotate / Scale tool palette consuming §4.1 icons.
- [`python/pharos_engine/ui/editor/scene_outliner.py`](../python/pharos_engine/ui/editor/scene_outliner.py)
  — uses §4.2 badges for the visibility / lock toggles and §6 default
  sticker placements.
- [`python/pharos_engine/ui/editor/property_inspector.py`](../python/pharos_engine/ui/editor/property_inspector.py)
  — three-section reflective inspector; §7 widget overrides land here.
- [`python/pharos_engine/ui/editor/spawn_menu.py`](../python/pharos_engine/ui/editor/spawn_menu.py)
  — `+ Add` modal; reuses inspector widget overrides verbatim.
- [`python/pharos_engine/ui/editor/code_mode_panel.py`](../python/pharos_engine/ui/editor/code_mode_panel.py)
  — Code Mode tab; §4.3 icons + Fira Code body font.
- [`python/pharos_engine/ui/editor/gizmo_overlay.py`](../python/pharos_engine/ui/editor/gizmo_overlay.py)
  — viewport drawlist gizmos; only affected by §1 accent palette (gizmo
  geometry stays as-is).

### Adjacent docs

- [`api/ui_editor.md`](api/ui_editor.md) — editor public-API reference;
  cross-link target once Phase A lands.
- [`sprint_5_doc_inventory.md`](sprint_5_doc_inventory.md) — this file
  is indexed there.
- [`tutorial_build_a_game.md`](tutorial_build_a_game.md) — the
  "build a game in 15 min" tutorial; an opt-in screenshot pass with the
  notebook theme is a Phase E follow-up.
- [`wheel_size_audit_2026_06_02.md`](wheel_size_audit_2026_06_02.md) —
  the wheel-size budget all asset additions must respect.
