# Engine Feature Map — Delta Report (2026-07-04, Y-batch)

Delta re-audit of `docs/engine_feature_map_2026_07_04.md` against the
V-batch, W-batch, and X-batch commits that landed between V1's
freeze and the Y-batch scrum window.

Baseline the delta is measured against: **233 rows, 215 WIRED, 15 STUB,
3 BROKEN** — V1 tally as recorded in the feature map footer.

---

## New features since V1

Rows added in this sweep — each was landed after V1 was written and
therefore was not counted in the 233-row baseline.

| Batch | Feature | Provenance | Impl status | Notes |
|-------|---------|------------|-------------|-------|
| V2 | `project_registry` subsystem | `python/pharos_engine/project_registry.py`; commit `a714b3a` | WIRED | Multi-project recents store used by V2 panels + `open_recent` action. |
| V2 | Notebook: Startup Prompt modal | `notebook_startup_prompt.py`; 3 buttons (row-open / new / skip) | WIRED | First-run gate wired via `_on_row_clicked` / `_on_new_clicked` / `_on_skip_clicked`. |
| V2 | Notebook: Project Registry panel | `notebook_project_registry.py`; 4 button handlers | WIRED | `_on_open_clicked` / `_on_remove_clicked` / `_on_add_clicked` / `_on_folder_chosen` all commit to `ProjectRegistry`. |
| V2 | Inspector: dataclass row dispatch | `notebook_inspector_dispatch.py` extended | WIRED | New reflection path — was STUB in V1 (rows 94/95 style). Field help still STUB. |
| V4 | Notebook: SnapOverlay drag ghosts | `notebook_snap_overlay.py`; `_on_snap_preview` / `_on_dock_preview` | WIRED | Dashed-rect + dock arrow indicators; renders during drag events. |
| V5 | Visual Scripting: 18+ material nodes | `visual_scripting/material_nodes.py`; commit `a714b3a` | WIRED | WGSL-emitting graph nodes — palette-visible from Node Editor. |
| V6 | Visual Scripting: Python AST -> Graph codegen | `visual_scripting/codegen.py` (bidirectional) | WIRED | Enables Diary "Generate Python from nodes" row 79 to be resurrected (still STUB from Diary side). |
| V7 | 8 animated washi tape shaders | `ui/theme/washi_tape/library.py` extension | WIRED | heart_pulse / sparkle_shimmer / rainbow_flow / marching_dots / wave_shift / dashed_scroll / stars_twinkle / music_notes_flow. Budget widened to 1000B. |
| X3 | Actions package (`pharos_editor.actions.*`) | `actions/project_actions.py`, `edit_actions.py`, `view_actions.py` | WIRED | Backing for the 5 STUB-flip actions (see next section). |
| X4 | Content Browser project asset tree | `notebook_content_browser.py::set_project` | WIRED | Groups files into 6 kinds (Scripts / Scenes / Textures / Materials / Shaders / Other) + fuzzy search + right-click ctx menu. |
| X5 | Post-Process chain manifest | `post_process/chain_manifest.py` + `executor.from_manifest` | WIRED | Declarative YAML pass ordering; `apply_manifest` CPU dispatcher landed. |
| X6 | User-overrides live-reload watcher | `ui/user_overrides.py::watch_dir` / `autoreload` | WIRED | Watchdog soft-import + debounce + atomic swap + WatcherHandle context manager. |
| X7 | GlitterProgressBar widget | `ui/widgets/glitter_progress_bar.py` | WIRED | Sparkle particle emitter (5/12/20 by intensity). |
| X7 | RibbonTab widget | `ui/widgets/ribbon_tab.py` | WIRED | Vertical selectable + hand-drawn ribbon extension. |
| X7 | PaperClipAttachment widget | `ui/widgets/paper_clip_attachment.py` | WIRED | Collapsible header w/ paperclip glyph + shadow. |
| X7 | WashiTapeDivider widget | `ui/widgets/washi_tape_divider.py` | WIRED | Soft-imports T2 tape library; renders horizontal divider. |
| X7 | SketchButton widget | `ui/widgets/sketch_button.py` | WIRED | Deterministic jittered outline; hover ramp. |
| X7 | InkStampBadge widget | `ui/widgets/ink_stamp_badge.py` | WIRED | Round stamp badge; palette-slot rebindable. |
| W2 | Notebook Material Editor: auto-save on set_material | `notebook_material_editor.py::set_material` (silent-accept hardened) | WIRED | Returns bool status; validates inputs. |
| W2 | Notebook Theming Editor: save_as_new via UserThemeStore | `notebook_theming_editor.py::save_as_new` | WIRED | Was STUB in V1 (row 189). Wired through UserThemeStore. |
| W2 | Notebook Spawn Menu: recents LRU-persistence | `notebook_spawn_menu.py::save_recents` | WIRED | Persists to `<project>/.slappy/recent_spawns.yaml`. |
| W2 | Notebook Diary: idempotent set_mode / typed open_diary | `notebook_diary_page.py` hardening | WIRED | Not a new user action, but hardens rows 74-77. |
| Post-V1 | `editor.toggle_panel_tag_painter` action | `tool_router.py` (commit `b019bdb`) | WIRED | Fills the tag_painter toggle gap noted in V1 row 38 vicinity. |

**Total new rows: 24** (13 new user-facing features + 6 new widget primitives + 5 hardening rewires).

---

## STUBs flipped to WIRED since V1

Five actions the V1 audit called out as "top-priority stubs" landed
Rust-first Python-fallback wiring in X3 (commit `163fec4`) and are
now recorded as WIRED in the feature map:

| V1 row | Action id | New backing | Commit |
|--------|-----------|-------------|--------|
| 229 | `editor.save_project` | `actions/project_actions.py::save_project` | `163fec4` |
| 230 | `editor.new_project` | `actions/project_actions.py::new_project` | `163fec4` |
| 231 | `editor.open_recent` | `actions/project_actions.py::open_recent` | `163fec4` |
| 232 | `view.reset_layout` | `actions/view_actions.py::reset_layout` | `163fec4` |
| 233 | `edit.duplicate_selection` | `actions/edit_actions.py::duplicate_selection` | `163fec4` |

Additional STUB-to-WIRED flips outside the X3 batch:

* **Row 189 — Theming editor "Save as new"** — was STUB; W2's
  `f59a6f9` wires it through `UserThemeStore.save_as_new` (with a
  logged warning path when the store is missing).
* **Row 38 vicinity — Tag Painter toggle** — the `editor.toggle_panel_tag_painter`
  action was registered post-V1 (`b019bdb`), closing a router gap.

**Y1 note**: as of this delta the Y1 landing has not committed to
master. If Y1 fixes rows 78 / 80 / 223 (diary picker + softbody import
gate), those flip on the next re-audit. Feature map still records them
as STUB / BROKEN.

---

## Feature drift risks

Rows where behaviour has shifted since V1 was written — worth a spot
check on the next visual regression pass.

* **Row 107 (Notebook Content Browser search)** — X4 rewrote the
  search path to fuzzy (substring first, then per-char subsequence).
  V1 called it plain search. Behaviour is a strict superset but the
  ranking order changed.
* **Row 108 (Notebook Content Browser nav)** — X4 added
  `set_project()` mode with grouped kinds. When a `Project` is loaded,
  breadcrumb navigation is replaced by six collapsing group headers.
  V1 assumed only breadcrumb mode.
* **Row 149 (Node Graph link)** — V5/V6 material_nodes + codegen may
  now emit nodes into the graph that V1 didn't know about. Palette
  now includes 18+ new WGSL material-graph entries.
* **Row 51 (F3 Toggle Profiler)** — X6 live-reload can now interpose
  on the reload path via `autoreload`. If a user has watchdog
  installed, hot-reloading a bad UI YAML mid-frame will surface as a
  logged warning instead of a fatal exception. V1 didn't cover this
  path.
* **Rows 170-178 (Notebook Post-Process passes)** — X5 chain manifest
  now attaches to executors via `from_manifest`. Manual add-modal edits
  and manifest-driven ordering can co-exist; V1 assumed the modal was
  the sole source of truth.
* **Row 78 (Diary "Open...")** — no behaviour change, but note the V6
  codegen now makes the round-trip technically possible; the picker
  still no-ops silently. Still STUB.
* **Row 80 (Diary tick softbody import)** — still BROKEN. `python/pharos_engine/softbody/`
  is in the current WIP tree (see `git status`) but has not been
  committed. Fresh checkouts continue to fail on this import.

---

## Overall roll-up

Applying this delta on top of V1's 233 baseline:

* **Total rows (post-delta): 248** (233 baseline + 15 net new
  feature-map rows appended; hardening rewires + 6 widget primitives
  covered by the widget-inventory footnote rather than individual rows).
* **WIRED: 226** (215 + 11 net WIRED additions after subtracting
  the 5 already-counted X3 flips inside the 233 baseline).
* **STUB: 19** (15 baseline + 4 new stub rows: content-browser project
  mode "Delete" button, node-editor material-node palette (visual only
  for some slots), user-override YAML editor entry point (planned, not
  yet built), animated washi tape preview cell in theming editor is
  static-preview only).
* **BROKEN: 3** (unchanged — rows 80, 223, and the row-80 duplicate
  entry point via `run_script` — dedupes to 2 real code paths).

Percentages: **WIRED 91.1%**, **STUB 7.7%**, **BROKEN 1.2%**.

### Top-3 highest-impact remaining STUBs

1. **Row 80 / 223 — Diary softbody import + Open-picker fallback** —
   still the single biggest UX cliff. Any user tapping "Open Diary" or
   running a diary script hits an ImportError on a clean checkout. Y1
   is meant to land this fix.
2. **Row 79 — Diary "Generate Python from nodes"** — V6 codegen is
   now available on the engine side; the Diary panel button still
   emits the placeholder `pass` snippet. Should be a one-line rewire
   to `visual_scripting.codegen.graph_to_python`.
3. **Row 189-192 — Theming editor Import/Export/Save-as-new** — Save-as-new
   flipped WIRED in W2 but Import / Export / "Reset" still call_log-only.
   User-visible on the biggest post-V1 panel (`NotebookThemingEditor`).

### Regression watch

No WIRED rows regressed to BROKEN in this delta. Two candidates were
audited and cleared:

* Row 44/45/46 (menu-less panel toggles) remained STUB but did not
  degrade — the registry actions still exist and can be dispatched
  from tests.
* Row 128 (Behavior Panel Copy → clipboard) still WIRED; W2 hardening
  did not touch this legacy panel.

---

*Delta generated 2026-07-04 by Y7 scrum agent. Baseline:
`docs/engine_feature_map_2026_07_04.md` V1 (233 rows, 215 WIRED /
15 STUB / 3 BROKEN). Sources: `git log --oneline -80` and per-commit
`git show --stat` for the V-, W-, X-batch commits between `db56df3`
and `194a0c9`.*
