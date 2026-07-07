# Engine Feature Map — Delta Report (2026-07-10 → post-RR1)

Compact delta covering the RR1 STUB-triage sprint tick (round 19 after
QQ1's round-18 ``spawn.at_origin`` / ``selection.by_type`` /
``selection.by_layer`` / ``selection.same_material`` /
``view.toggle_stats`` batch).

## RR1 STUB-triage patch (2026-07-10, round 19)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered on the router) to WIRED:

| Action id | Fallback module (`slappyengine.actions.*`) | Category |
|-----------|--------------------------------------------|----------|
| `edit.select_similar`      | `edit_select_similar_actions.select_similar`              | edit |
| `theme.reset_to_default`   | `theme_reset_default_actions.reset_to_default`            | theme |
| `layer.hide_others`        | `layer_hide_others_actions.hide_others`                   | layer |
| `layer.isolate`            | `layer_isolate_actions.isolate`                           | layer |
| `snap.toggle_incremental`  | `snap_toggle_incremental_actions.toggle_incremental`      | snap |

New action modules:

* `python/slappyengine/actions/edit_select_similar_actions.py`
* `python/slappyengine/actions/theme_reset_default_actions.py`
* `python/slappyengine/actions/layer_hide_others_actions.py`
* `python/slappyengine/actions/layer_isolate_actions.py`
* `python/slappyengine/actions/snap_toggle_incremental_actions.py`

Router entries and `_fb_*` shims live in
`python/slappyengine/tool_router.py` under the
`# ── RR1 STUB-triage: select-similar, theme reset-to-default, layer
hide-others + isolate, snap toggle-incremental (round 19) ──` block.

### Behavioural notes for RR1

* **`edit.select_similar`** — Photoshop ``Select → Similar`` /
  Blender ``Shift+G → Extended``. Distinct from QQ1's
  `selection.by_type` (kind-only, inclusive) and
  `selection.same_material` (material-only, inclusive) — this helper
  fuses both keys into a `(kind, material)` signature. A candidate
  matches when it shares the full tuple, OR shares the seed's kind
  when either side has no material tag. Bare classes with no explicit
  `kind` / `material` slot still cluster via the
  `type(entity).__name__` fallback. Return contract: `no_scene` /
  `no_selection` / `unchanged` / `selected` (with `signatures`,
  `added`, `previous_count`, `total`).
* **`theme.reset_to_default`** — Photoshop ``Reset Workspace`` /
  Blender ``Load Factory Settings → Theme``. Distinct from FF1's
  `theme.reload_all` (which flushes the registry) — this verb picks
  the shipped default and re-applies it without touching disk. Default
  resolution: `ctx["default"]` → `shell._default_theme` →
  `ctx["ui_settings"].default_theme` /
  `shell._ui_settings.default_theme` → `list_registered_themes()[0]`.
  Parks the shared `_THEME_CURSOR` at the reset target so a follow-up
  `theme.cycle` walks forward from there. Return contract: `no_themes` /
  `unchanged` (already at default) / `reset` (with `previous`, `path`)
  / `error` (ui.theme import failed).
* **`layer.hide_others`** — Photoshop ``Alt+click`` on eye-icon
  (one-shot). Distinct from OO1's `layer.solo` (which snapshots and
  supports toggle-restore) — this verb has no state / no toggle. The
  active layer is left as-is (no force-show); every other visible
  layer flips to `visible=False`. Return contract: `no_scene` /
  `no_layer` / `no_layers` / `already_hidden` / `hidden` (with
  `target`, `hidden`, `count`).
* **`layer.isolate`** — Blender ``Numpad /`` local-view / Maya
  ``Show → Isolate Selected``. Entity-level (not layer-level) — the
  `layer.` prefix is a namespace-only misnomer that groups every
  visibility-management verb. Second-call toggle: an existing
  `shell._isolate_snapshot` triggers a restore path that rewinds every
  entity to its snapshotted visibility. Seed entities are force-shown
  even when previously hidden (matches the "focus on these" intent).
  Return contract: `no_scene` / `empty_scene` / `no_selection` (only
  on first-pass) / `isolated` (with `selection_count`, `hidden`,
  `hidden_count`) / `restored` (with `shown`, `shown_count`).
* **`snap.toggle_incremental`** — Blender modifier ``Shift`` during
  drag / Unity ProGrids `Ctrl` snap. Distinct from `tool.snap_to_grid`
  (primary grid-snap gate) and OO1's `snap.increase_grid_size` /
  `snap.decrease_grid_size` (which step grid resolution): this
  toggles the *mode* between numeric-step and freeform. Flips
  `shell._snap_incremental_mode` and fires
  `shell._on_snap_toggle("_snap_incremental_mode", value)` for
  downstream renderer refresh. Return contract: `no_shell` /
  `toggled` (with `target`, `enabled`, `previous`).

Regression tests:
`SlapPyEngineTests/tests/test_actions_stub_triage_r19.py` — one
registration test per id (5 tests) plus a category assertion + a
singleton-check test (7 registration tests total) plus behavioural
coverage per module (~24 behavioural tests). Combined with r15 (31),
r16 (29), r17 (34), r18 (33), the r15+r16+r17+r18+r19 dispatch surface
is exercised across ~155+ tests.

## STUB roster unchanged

The 5 new WIRED rows are all NEW router entries — no previously-listed
STUB row (from the roster tracked in
`feature_map_delta_2026_07_06.md`) is affected. The DPG-shell-dependent
STUBs (HUD toggle, diary "Open…" file picker, inspector help popups,
theming save-as-new / import / export modals) remain untouched by RR1.

---

*Delta generated 2026-07-10 by RR1 STUB-triage agent (parallel-sprint
lane). Sources: `336263c` (r18 baseline) + RR1 commit.*
