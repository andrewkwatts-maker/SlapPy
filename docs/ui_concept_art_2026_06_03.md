# UI Concept Art — TeenGirl Notebook Theme

**Status:** Concept-art inventory + extraction plan (2026-06-03).
**Source of truth:** the concept-art files under `UIConceptArt/` are the
authoritative visual reference for the TeenGirl Notebook theme. The formal
spec lives at [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md)
(authored by a parallel agent); this doc catalogues the raw inputs and
defines how the user-side inspection feeds into that spec.

The agent's role here is **structural only**: list files, define the
extraction tables, and reserve slots. The **visual content** (dominant
colours, sticker descriptions, layout call-outs) must be filled in by the
user from direct inspection of the images — the Read tool cannot ingest
these images as pixel data at their current size.

## 1. Inventory

All files live under `UIConceptArt/` (repo root). All five are tracked as
reference assets (see `.gitignore` allow-list block).

| Filename | Size | Expected role |
|---|---:|---|
| `Concepts.jfif` | 189 204 B (~185 KB) | Overall concept board — mood, palette, vibe references. |
| `Stickers.jfif` | 242 453 B (~237 KB) | Catalogue of sticker designs the user sketched (decorative motifs for HUD/menu overlays). |
| `download.jfif` | 202 907 B (~198 KB) | Found-art reference (mood / inspiration board, named per browser default). |
| `download (1).jfif` | 172 129 B (~168 KB) | Second found-art reference (mood / inspiration board). |
| `image_3e1d1a30.png` | 2 369 940 B (~2.3 MB) | High-resolution master concept render (largest, likely the most detailed source). |

Total: ~3.0 MB across 5 files — fits the "small enough to commit" budget.

## 2. Extraction plan

The TeenGirl Notebook theme implementation needs three artefacts pulled
out of the concept art:

1. **Palette** — the dominant hues, expressed as hex codes, mapped to
   semantic roles (background, ink, accent, sticker fills).
2. **Sticker library** — a discrete list of motif sketches the user wants
   to reproduce as drawable primitives (heart, star, doodle arrow, etc).
3. **Layout patterns** — recurring panel shapes, dividers, headers,
   margin-doodle styles.

### 2.1 Palette extraction table

User fills one row per dominant colour identified on inspection. Six
slots reserved (extend if the concept board demands more, but keep the
palette short — TeenGirl Notebook should read as a 5-7-colour theme).

| Slot | Hex | Role | Source file | Notes |
|---|---|---|---|---|
| 1 | `#______` | background / page | | |
| 2 | `#______` | primary ink | | |
| 3 | `#______` | accent A | | |
| 4 | `#______` | accent B | | |
| 5 | `#______` | sticker fill A | | |
| 6 | `#______` | sticker fill B | | |

### 2.2 Sticker library catalogue

One row per distinct sticker design visible in `Stickers.jfif` (and any
stickers appearing in `Concepts.jfif` / `image_3e1d1a30.png`). Use a
short snake_case `sticker_id` so it can be referenced from theme code.

| sticker_id | Description | hex_color | Source file | Use site |
|---|---|---|---|---|
| `heart_outline` | | `#______` | | |
| `star_filled` | | `#______` | | |
| `doodle_arrow` | | `#______` | | |
| `____________` | | `#______` | | |
| `____________` | | `#______` | | |
| `____________` | | `#______` | | |
| `____________` | | `#______` | | |
| `____________` | | `#______` | | |

(Pre-seeded the first three with the most likely TeenGirl-Notebook
motifs as a starting template — overwrite freely if the user's sketches
differ.)

### 2.3 Layout patterns catalogue

| Pattern | Where it appears | Description | Implementation note |
|---|---|---|---|
| Panel frame | | | |
| Divider | | | |
| Header strip | | | |
| Margin doodle | | | |
| Page edge | | | |

## 3. Workflow

1. User opens each `UIConceptArt/*.jfif` and `image_3e1d1a30.png` in an
   image viewer.
2. User fills hex codes into the palette table (eyedropper from a paint
   app, or by eye).
3. User names each sticker and fills the description column.
4. User identifies recurring layout motifs and fills the layout table.
5. The completed tables become the authoritative input to
   `theme_teengirl_notebook_2026_06_03.md`'s palette/sticker/layout
   sections.

## 4. Cross-references

- **Formal theme spec:** `docs/theme_teengirl_notebook_2026_06_03.md`
  (parallel agent) — consumes the tables in §2 above.
- **Editor surface:** `pharos_engine.ui.editor` — where the theme is
  applied (existing dark Nova3D theme will gain a TeenGirl-Notebook
  alternative).
- **Sticker rendering:** likely added under
  `pharos_engine.ui.theme.stickers` (TBD; see formal spec).

## 5. Why these files are committed

The concept art is **source material**, not generated output. It is
small (~3 MB total), versioned alongside the theme implementation it
drives, and required for any future re-derivation of the palette or
sticker set. An explicit allow-list block in `.gitignore`
(`!UIConceptArt/*.jfif`, `!UIConceptArt/*.png`) protects these files
from any future blanket image-ignore rules.
