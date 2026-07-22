# UI Lessons from EyesOfAzrael (2026-06-03)

A read-only audit of the EyesOfAzrael (EoA) web project's UI architecture
(89 CSS files, 8 mythology themes, glassmorphism design system) with a
translation map for the patterns Pharos Engine should adopt, has already
adopted, or should explicitly *not* port. Pure-docs commit; no source
edits accompany this file.

EoA reference paths (all read-only):

* `H:/Github/EyesOfAzrael/css/CSS_ARCHITECTURE.md` — top-level CSS
  conventions, BEM naming, design-token vocabulary.
* `H:/Github/EyesOfAzrael/css/firebase-themes.css` (588 lines) —
  glassmorphism design system + 8 mythology themes.
* `H:/Github/EyesOfAzrael/css/header-theme-picker.css` — dropdown theme
  picker styling + transition animations.
* `H:/Github/EyesOfAzrael/components/COMPONENT_GUIDE.md` — 12 reusable
  HTML component templates (glass card, deity card, hero, tabs, modal, …).
* `H:/Github/EyesOfAzrael/FIREBASE/CHANGELOG_UI_SYSTEM.md` — historical
  rollout (v1.0.0, 2025-12-13): theme manager, content loader, demo.

Pharos Engine cross-references (where each lesson lands):

* U1 — `python/pharos_engine/ui/theme/theme_spec.py` (semantic-token layer,
  spacing/radius/transition/z-index scales).
* U2 — theme *variants* registry (`apply_theme(name)` in
  `python/pharos_engine/ui/theme/__init__.py`).
* U5 — planned `ThemeSwitcherPanel` for the editor shell.
* U6 — `glass_blur` shader effect in `python/pharos_engine/ui/theme/shader_effects.py`.
* Pattern audit:
  [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md).
* Diary theme family:
  [`theme_diary_family_2026_06_03.md`](theme_diary_family_2026_06_03.md).
* TeenGirl Notebook theme:
  [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md).

---

## 1. Token system — raw colours vs semantic layer

### What EoA does

EoA splits theming into two layers in `firebase-themes.css`:

```css
:root {
  /* Raw palette (implementation). */
  --greek-primary:    #9370DB;
  --egyptian-primary: #DAA520;
  --norse-primary:    #4682B4;
  /* … 5 more mythologies. */

  /* Semantic token (contract every widget binds to). */
  --theme-primary: var(--greek-primary);
  --theme-primary-rgb: 147, 112, 219;

  /* Glassmorphism tokens. */
  --glass-bg:       rgba(255, 255, 255, 0.1);
  --glass-bg-hover: rgba(255, 255, 255, 0.15);
  --glass-border:   rgba(255, 255, 255, 0.1);
  --glass-shadow:   0 8px 32px rgba(0, 0, 0, 0.1);
  --glass-blur:     10px;
}
```

Widget rules read only the semantic layer:

```css
.glass-card {
  background:       var(--glass-bg);
  backdrop-filter:  blur(var(--glass-blur));
  border:           1px solid var(--glass-border);
  border-radius:    var(--radius-md);
  box-shadow:       var(--glass-shadow);
  transition:       var(--transition-normal);
}
```

### How Pharos Engine translates it

`SemanticTokens` (already in `theme_spec.py`) is the dataclass equivalent
of the EoA `--theme-*` / `--glass-*` surface:

```python
@dataclass
class SemanticTokens:
    primary: Color
    primary_gradient: Gradient
    secondary: Color
    accent: Color
    background: Color
    surface: Color
    surface_hover: Color
    border: Color
    text_primary: Color
    text_secondary: Color
    text_disabled: Color
    success: Color
    warning: Color
    error: Color
    info: Color
    focus_ring: Color
    glass_bg: Color
    glass_blur_px: float
```

The `Palette.entries` dict on `ThemeSpec` is the raw-colour bag
(equivalent of `--greek-primary`); `SemanticTokens` is the named
contract widget code binds against. The provenance docstring on
`theme_spec.py` explicitly cites EoA as the design source.

### Status — **ADOPTED** (U1 already landed).

---

## 2. Theme variants via attribute selector

### What EoA does

EoA scopes every theme under a `[data-theme="…"]` attribute selector. JS
flips `document.documentElement.dataset.theme = "norse"`; the CSS cascade
re-resolves `--theme-primary` and the entire UI repaints with no DOM
swap:

```css
[data-theme="greek"]    { --theme-primary: var(--greek-primary); }
[data-theme="egyptian"] { --theme-primary: var(--egyptian-primary); }
[data-theme="norse"]    { --theme-primary: var(--norse-primary); }
/* … */
```

### How Pharos Engine translates it

`apply_theme(name)` in `ui/theme/__init__.py` is the analogue: a single
mutable `_ACTIVE` slot plus a `_REGISTRY` keyed by `ThemeSpec.name`. The
"attribute selector" becomes "look up `ThemeSpec.name` in a registry":

```python
register_theme(teengirl_notebook())   # name="teengirl_notebook"
register_theme(cottagecore_garden())  # name="cottagecore_garden"
apply_theme("teengirl_notebook")      # _ACTIVE = registry entry
```

Widgets read tokens from `get_active_theme()` (or its `SemanticTokens`
once U1 wires the slot in). Switching themes is one assignment plus a
re-render — the same conceptual move as setting `data-theme="norse"`.

### Status — **ADOPTED** for primitives (U2 registry live); **PLANNED** for
the full hot-swap re-render path (Sprint 1 of the editor-notebook
overhaul will exercise this with the diary-family rotation).

---

## 3. Spacing / radius / transition / z-index scales

### What EoA does

A single `:root` block of CSS custom properties:

```css
:root {
  --spacing-xs: 0.25rem;
  --spacing-sm: 0.5rem;
  --spacing-md: 1rem;
  --spacing-lg: 1.5rem;
  --spacing-xl: 2rem;
  --spacing-2xl: 3rem;

  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;

  --transition-fast:   all 0.2s ease;
  --transition-normal: all 0.3s ease;
  --transition-slow:   all 0.5s ease;

  --z-base:     1;
  --z-dropdown: 100;
  --z-modal:    1000;
  --z-toast:    2000;
}
```

### How Pharos Engine translates it

The four frozen dataclasses now live next to `SemanticTokens` in
`theme_spec.py` and mirror the EoA shape verbatim (per-field):

```python
@dataclass(frozen=True)
class SpacingScale:
    xs: float = 4.0;  sm: float = 8.0;  md: float = 16.0
    lg: float = 24.0; xl: float = 32.0; xxl: float = 48.0

@dataclass(frozen=True)
class RadiusScale:
    sm: float = 4.0;  md: float = 8.0;  lg: float = 12.0
    xl: float = 16.0; pill: float = 999.0

@dataclass(frozen=True)
class TransitionScale:
    fast: float = 0.15;  normal: float = 0.25;  slow: float = 0.5

@dataclass(frozen=True)
class ZIndexScale:
    base: int = 1;  dropdown: int = 100
    modal: int = 1000;  toast: int = 2000
```

`ZIndexScale.__post_init__` asserts monotonic tiers (a typo cannot
silently shuffle a toast under a modal). The EoA CSS layout has no
analogue — only runtime asserts can catch this in Python.

### Status — **ADOPTED** (U1).

---

## 4. Component-driven design — copy-paste templates

### What EoA does

`components/COMPONENT_GUIDE.md` catalogues 12 reusable HTML templates
(button, card, nav, hero, grid, expandable, tabs, search, modal, form,
list, page-template). Each entry documents *purpose, variants, when to
use, accessibility notes, example HTML*. Components are "copy-paste
ready" — no build step required.

### How Pharos Engine translates it

`python/pharos_engine/ui/widgets/` ships the analogue:

* `sticker_button.py`, `washi_panel.py`, `notebook_tab.py`,
  `highlighter_slider.py`, `heart_checkbox.py`, `doodle_separator.py`,
  `sticker_corner.py`.
* `_dpg_base.py` factors out DPG-specific glue so each widget is a
  ~50-line dataclass + render function pair.
* `api/ui_widgets.md` is the catalogue index (analogue of
  `COMPONENT_GUIDE.md`).

EoA's "copy-paste" maps to "import the dataclass, instantiate, render"
in Python — no global namespace pollution, and themes can substitute
custom render functions without rewriting the widget contract.

### Status — **ADOPTED** for the diary family (P6 widget set landed);
**PLANNED** for a broader catalogue index that matches the EoA
component-guide structure (purpose / variants / when-to-use / a11y / example).

---

## 5. Glassmorphism — frosted glass effect

### What EoA does

The EoA glassmorphism aesthetic is three CSS rules layered:

```css
.glass-card {
  background:               var(--glass-bg);      /* rgba(255,255,255,0.1) */
  backdrop-filter:          blur(var(--glass-blur));
  -webkit-backdrop-filter:  blur(var(--glass-blur));
  border:                   1px solid var(--glass-border);
  box-shadow:               var(--glass-shadow);
}
```

`backdrop-filter` blurs whatever is *behind* the element, giving the
frosted-glass read. The vendor-prefixed copy is mandatory for Safari.

### How Pharos Engine translates it

DPG has no `backdrop-filter` equivalent. Pharos Engine pre-bakes the
blur into a procedural texture via `glass_blur` in `shader_effects.py`:

```python
def glass_blur(width: int, height: int,
               base_color: tuple[int, int, int, int],
               blur_sigma: float, ...) -> np.ndarray:
    """Bake a translucent-noise plate that reads as 'frosted glass'."""
```

Widget code samples the baked texture as its panel background instead
of compositing live blur every frame. The Windows DWM Acrylic FFI in
`ui/editor/theme.py:apply_dwm_glass` provides the *real* live blur for
the editor's outer window only; child surfaces use the baked plate.

The notebook themes opt *out* of glassmorphism entirely (paper is
opaque) — `glass_blur_px = 0` on the `SemanticTokens` instance.

### Status — **ADOPTED** for primitive (U6 shader); **OPT-IN** per
theme (Nova3D inherits, notebook family disables).

---

## 6. Theme picker UI — dropdown + transition animation

### What EoA does

`header-theme-picker.css` ships a 378-line dropdown panel with:

* Category groupings (`.theme-category` with separator + label).
* Per-option preview swatch (`.theme-preview` with 2-3 colour slices).
* Active-state checkmark with a spring-bounce animation
  (`@keyframes checkBounce`).
* A global `body.theme-transitioning` class that scopes a 0.35 s
  cubic-bezier transition over `background-color / color / border-color
  / box-shadow` so the *entire UI cross-fades* between themes.
* `prefers-reduced-motion` honoured (animations cut, transitions
  cut, no exceptions).
* High-contrast media query (`@media (prefers-contrast: high)`).

```css
body.theme-transitioning,
body.theme-transitioning * {
  transition:
    background-color 0.35s cubic-bezier(0.4, 0.0, 0.2, 1),
    color            0.35s cubic-bezier(0.4, 0.0, 0.2, 1),
    border-color     0.35s cubic-bezier(0.4, 0.0, 0.2, 1),
    box-shadow       0.35s cubic-bezier(0.4, 0.0, 0.2, 1) !important;
}
```

### How Pharos Engine translates it

`ThemeSwitcherPanel` (U5, planned for the editor sprint) — a DPG combo
or grid showing each registered `ThemeSpec` with a preview swatch built
from `SemanticTokens.primary / accent / surface`. On selection:

1. `apply_theme(name)` swaps the `_ACTIVE` slot.
2. The editor shell re-binds DPG theme handles (one assignment per
   widget; DPG doesn't support a cross-fade transition primitive).
3. `engine.theme.changed` event fires on the global bus; widget
   subscribers re-render lazily on their next dirty tick.

Cross-fade — DPG can't do it natively, but the
`TransitionScale.normal = 0.25 s` value at least lets a one-shot
opacity tween land if the editor shell wants to invest the frames.
`prefers-reduced-motion` translates to the engine-side
`AccessibilitySettings.reduced_motion` flag (per the idle-animation
spec, doc 32 in the inventory).

### Status — **PLANNED** (U5 sprint target).

---

## 7. Animation conventions — transition tokens drive timing

### What EoA does

The `--transition-fast / normal / slow` tokens are reused as the
duration argument for *every* animation in the system:

```css
.glass-card    { transition: var(--transition-normal); }     /* 0.3 s */
.glass-btn     { transition: var(--transition-normal); }     /* 0.3 s */
.theme-option  { transition: all 0.15s ease; }               /* fast  */
.dropdownFadeIn { animation: dropdownFadeIn 0.25s cubic-bezier(0.16, 1, 0.3, 1); }
```

The duration vocabulary is shared between transitions
(state changes) and keyframe animations (entry/exit).

### How Pharos Engine translates it

`TransitionScale.fast / normal / slow` is the same vocabulary, available
to both editor-side widget hover transitions (DPG style) *and*
engine-side creature-animation timings:

| Use case                            | Token              | Value |
|-------------------------------------|--------------------|-------|
| Widget hover / focus state change   | `fast`             | 0.15 s |
| Theme switch cross-fade             | `normal`           | 0.25 s |
| Idle creature one-shot (peek, blink) | `normal` × 4-8    | 1-2 s |
| Idle creature long loop (sleep)     | `slow` × 6-12      | 3-6 s |

The creature-animation system (no analog in EoA — uniquely Pharos)
sources its base timing from the same `TransitionScale` instance the
widget hover states use. That way "make the UI feel snappier" is a
single token edit, not a 200-call-site search-and-replace.

### Status — **ADOPTED** for primitives (U1 scale); **PLANNED** for
creature scheduler integration (the idle-animation spec already cites
TransitionScale as its source of truth).

---

## 8. SlapPyEngine-specific gaps EoA doesn't cover

EoA is web-only and stateless w.r.t. rendering — these axes have no CSS
analogue:

### 8.1 DPG / desktop vs CSS / web rendering primitives

EoA renders via the browser's compositor. Pharos Engine renders via Dear
PyGui's immediate-mode draw list (for the editor) or via numpy / Rust
kernels (for the engine viewport). Implications:

* **No CSS cascade.** Every widget receives a `SemanticTokens` instance
  by argument; there is no "inherit from parent" mechanism. This is
  *fine* — the cascade is a frequent source of EoA's "specificity wars"
  (per `CSS_ARCHITECTURE.md` § "File Consolidation").
* **No `backdrop-filter`.** Glass must be pre-baked (`glass_blur`) or
  realised via the platform's compositor (DWM Acrylic on Windows).
* **No `@media (max-width: 768px)`.** Responsive layout is `ImGui`-style
  auto-resize; explicit breakpoint logic lives in the editor shell.

### 8.2 Headless rendering (visual tests)

EoA has no headless test harness (browser screenshots are
out-of-band). Pharos Engine's `pharos_engine.testing` module provides
`render_scene_to_png` + `assert_scene_matches`, which means *every theme
needs a headless baseline*. The TeenGirl Notebook theme should ship a
baseline plate per sprint to catch palette / scale regressions.

### 8.3 Hot-swap theme runtime requirement

EoA can afford a full page repaint on theme switch (a browser FLIP is
~16 ms). Pharos Engine runs at 60-1000 fps with retained DPG textures;
re-baking every nine-slice + every SVG icon on theme swap costs ~50 ms
on a warm cache. The `_REGISTRY` should be augmented with a per-theme
texture cache so swapping back to a previously-used theme is O(1).

### 8.4 Creature animation system — uniquely Pharos

EoA has no analogue. The `ui/theme/creatures/` subpackage (CreatureBus
adapter, idle-event emitter, 19 event-to-creature bindings) is *new
ground*. EoA contributes only the timing-token vocabulary
(`TransitionScale`); the dispatch + lifecycle layer is Pharos-original.
The reference doc is
[`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md).

---

## 9. Recommendations table

Priority legend:
**P0** = ship-blocker for v0.4 editor overhaul.
**P1** = strongly recommended for v0.4.
**P2** = nice-to-have, slot when time allows.
**P3** = informational; do not pursue.

| # | Pattern                                        | Priority | Sprint target          | Status        |
|---|------------------------------------------------|----------|------------------------|---------------|
| 1 | Semantic-token layer (`SemanticTokens`)        | P0       | U1 (done)              | ADOPTED       |
| 2 | Spacing / radius / transition / z-index scales | P0       | U1 (done)              | ADOPTED       |
| 3 | `[data-theme="X"]` analogue (`apply_theme`)    | P0       | U2 (done)              | ADOPTED       |
| 4 | Glassmorphism shader primitive (`glass_blur`)  | P1       | U6 (done)              | ADOPTED       |
| 5 | `ThemeSwitcherPanel` for the editor shell      | P0       | U5 (next)              | PLANNED       |
| 6 | Per-theme texture cache on `_REGISTRY`         | P1       | Sprint 1, Phase C      | PLANNED       |
| 7 | `engine.theme.changed` event-bus broadcast     | P1       | U5 (with switcher)     | PLANNED       |
| 8 | Headless baseline plate per theme              | P1       | Sprint 1, Phase E      | PLANNED       |
| 9 | Widget-catalogue index (EoA COMPONENT_GUIDE)   | P2       | Sprint 1, Phase D      | PLANNED       |
| 10 | `AccessibilitySettings.reduced_motion` honour | P1       | Sprint 6 (profiler)    | PLANNED       |
| 11 | High-contrast theme variant                   | P2       | v0.5 (post-ship polish)| BACKLOG       |
| 12 | Per-token YAML round-trip parity              | P1       | U1 follow-up           | PARTIAL       |
| 13 | DPG cross-fade tween on theme swap            | P2       | Sprint 6               | INVESTIGATE   |
| 14 | LocalStorage-style theme persistence (config) | P1       | Sprint 1, Phase E      | PLANNED       |
| 15 | BEM-style widget class naming                 | P3       | n/a                    | NOT APPLICABLE |

Notes per row:

* **Row 12 — PARTIAL.** `SemanticTokens.to_dict / from_dict` exist;
  `ThemeSpec.to_yaml / from_yaml` exist. The remaining gap is that the
  active `SemanticTokens` slot is not yet stored on `ThemeSpec`; the
  TeenGirl theme encodes semantics as additional palette keys per its
  module docstring. Closing this is a one-day U1 follow-up.
* **Row 13 — INVESTIGATE.** DPG does not ship a tween primitive. A
  pure-Python ease loop is feasible at the editor-shell level but adds
  one frame of input latency; defer until profile data justifies it.
* **Row 15 — NOT APPLICABLE.** BEM (Block-Element-Modifier) is a CSS
  selector-scoping convention. Python class names already enforce
  scoping by module — no analogue needed.

---

## 10. Anti-patterns explicitly *not* ported

A few EoA conventions are web-specific or would actively hurt the
desktop engine; record them so future contributors do not import them
by reflex.

* **No `!important` hammer.** EoA's `body.theme-transitioning *`
  cascade override uses `!important` to win the cascade. Python has no
  cascade; the equivalent is "always read from `get_active_theme()`",
  which is already enforced by the `_REGISTRY` having a single
  `_ACTIVE` slot.
* **No "polish" file duplicates.** EoA's `CSS_ARCHITECTURE.md` admits
  to `user-profile.css` *and* `user-profile-polished.css`, etc. — a
  symptom of the "consolidate later" debt. Python's import system makes
  this less seductive (you would have to name the second module
  awkwardly), but the rule stands: one widget = one module.
* **No mobile-first responsive breakpoints.** EoA cascades
  `@media (max-width: 768px)` everywhere. Editor windows do not resize
  below useful thresholds; respond to DPI changes instead, via
  `RadiusScale` and `SpacingScale` rescaling.
* **No 89-file CSS sprawl.** EoA admits in its own architecture doc to
  needing a consolidation pass. The Pharos theme system caps at four
  primitives modules (`nine_slice`, `svg_icon`, `shader_effects`,
  `theme_spec`) plus one module per concrete theme. Adding a fifth
  primitive requires a design doc.

---

## 11. Cross-references

* [`theme_diary_family_2026_06_03.md`](theme_diary_family_2026_06_03.md)
  — six-theme rollup that exercises the U2 hot-swap path.
* [`theme_teengirl_notebook_2026_06_03.md`](theme_teengirl_notebook_2026_06_03.md)
  — first concrete theme; cites this audit as its design provenance
  (per its module docstring §1).
* [`ui_pattern_audit_2026_06_03.md`](ui_pattern_audit_2026_06_03.md) —
  per-panel contract audit; the EoA → Pharos translation map landed
  here and is referenced by every panel's "translation" section.
* [`ui_concept_art_2026_06_03.md`](ui_concept_art_2026_06_03.md) — visual
  inspection template for the user-side art pass.
* [`idle_animation_system_2026_06_03.md`](idle_animation_system_2026_06_03.md)
  — uses `TransitionScale` as its base timing vocabulary.
* [`sprint_plan_2026_06_03.md`](sprint_plan_2026_06_03.md) §1 —
  editor-UI theme is the first sprint; this audit is the design source
  for the semantic-token + theme-variant + glass-shader primitives that
  sprint relies on.
* [`api/ui_theme.md`](api/ui_theme.md) — primitive surface API ref.
* [`api/ui_widgets.md`](api/ui_widgets.md) — widget catalogue index.

---

## 12. Summary

| Lesson                                  | Status        | Pharos artefact                                |
|-----------------------------------------|---------------|------------------------------------------------|
| Semantic-token layer                    | ADOPTED       | `theme_spec.SemanticTokens`                    |
| Spacing / radius / transition / z-index | ADOPTED       | `theme_spec.{Spacing,Radius,Transition,ZIndex}Scale` |
| Theme-variant attribute selector        | ADOPTED       | `ui/theme/__init__.apply_theme`                |
| Component-driven widgets                | ADOPTED       | `ui/widgets/`                                  |
| Glassmorphism                           | ADOPTED       | `shader_effects.glass_blur`                    |
| Theme picker UI                         | PLANNED (U5)  | `ThemeSwitcherPanel`                           |
| Animation timing conventions            | ADOPTED       | `TransitionScale` shared between widgets + creatures |
| Headless visual baselines               | PLANNED       | `pharos_engine.testing` per-theme plates        |
| Hot-swap performance cache              | PLANNED       | Per-theme texture cache on `_REGISTRY`         |
| Creature animation dispatch             | SLAPPY-ORIGINAL | `ui/theme/creatures/`                        |

Five P0/P1 lessons are already adopted; five P0/P1 lessons remain
planned and are slotted into the Sprint 1 editor overhaul.

---

**Maintainer note.** This audit is read-only on EoA. If EoA evolves
(its v1.0.0 was 2025-12-13 — six months stale by the date of this
audit), re-run the same five reference reads and append a "delta"
section rather than rewriting prior text.
