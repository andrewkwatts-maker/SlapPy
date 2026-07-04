# Engine Feature Map — 2026-07-04

Comprehensive audit mapping every user-facing editor action to its
implementation status. Rows are drawn from:

* `python/slappyengine/tool_router.py` — the canonical
  `REGISTRY` of 53 `ToolAction`s that gate every hotkey / spawn /
  menu invocation.
* `python/slappyengine/ui/editor/shell.py` — DPG viewport menu bar
  (`File` / `Edit` / `View` / `Help`) + left-panel tool buttons +
  About modal.
* `python/slappyengine/ui/editor/notebook_toolbar.py` — Select /
  Move / Rotate / Scale sticker-button toolbar.
* `python/slappyengine/ui/editor/notebook_spawn_menu.py` — 10 spawn
  cards with Summon / Cancel modal buttons.
* `python/slappyengine/ui/editor/notebook_diary_page.py` — Run /
  Stop / mode-toggle / Save / Open... footer ribbon +
  Generate-Python-from-Nodes stub.
* Notebook panels (`notebook_outliner`, `notebook_inspector`,
  `notebook_content_browser`, `notebook_theming_editor`,
  `notebook_animation_panel`, `notebook_post_process_panel`,
  `notebook_telemetry_panel`, `notebook_code_panel`,
  `notebook_node_editor`, `notebook_status_bar`,
  `notebook_project_picker`, `notebook_welcome`,
  `ollama_setup_modal`) and Nova3D-legacy panels
  (`layer_panel`, `layer_lighting_panel`, `behavior_panel`,
  `anim_graph_panel`, `code_mode_panel`, `content_browser`,
  `material_editor`, `node_graph_panel`, `property_inspector`,
  `script_binding_panel`).
* `python/slappyengine/ui/editor/notebook_hotkeys.py` —
  `_BINDINGS_FROZEN` 27 keyboard shortcuts.

Status legend:

* **WIRED** — button/menu invokes a real, side-effecting function
  (may still be light-weight, but no `pass`/log-only body).
* **STUB** — callback exists but only writes to `call_log`, shows
  a "coming soon"/"not yet wired" status hint, or is documented as
  a stub.
* **BROKEN** — callback references a symbol that is missing, an
  undeclared attribute, or a soft-imported module the panel does
  not gate on and would `NameError`/`AttributeError` at click time.

---

## Feature table

| # | Feature | Location (panel / menu / hotkey) | Impl status | Backing file:line | Notes |
|---|---------|----------------------------------|-------------|-------------------|-------|
| 1 | Save (project) | `Ctrl+S` hotkey → `editor.save` | WIRED | `tool_router.py:607`, `shell.py:2919` | Rust `slap_format.lz4_compress` when wheel present; else `_save_project`. |
| 2 | New Scene (menu) | `File → New Scene` | WIRED | `shell.py:1409` → `self.new_scene()` | Delegates to engine `new_scene` if exposed. |
| 3 | New Scene (router) | `editor.new` action | WIRED | `tool_router.py:615` → `_fb_new` → `shell.menu_new_scene` | `menu_new_scene` alias defers to `new_scene`. |
| 4 | Open Scene… (menu) | `File → Open Scene...` | WIRED | `shell.py:1414` → `self.menu_open_scene()` | Tk file dialog + engine `load_scene`. |
| 5 | Open Scene (router) | `editor.open` / `Ctrl+O` | WIRED | `tool_router.py:623` | Rust `slap_format.lz4_decompress` when wheel present. |
| 6 | Save Scene (menu) | `File → Save Scene` (Ctrl+S) | WIRED | `shell.py:1419` → `menu_save_scene` | Project-aware, falls back to `_project_manager.save`. |
| 7 | Save Scene As… | `File → Save Scene As...` (Ctrl+Shift+S) | WIRED | `shell.py:1425` → `save_scene_as` | Prompts Tk save dialog. |
| 8 | New Diary Page | `File → New Diary Page` | WIRED | `shell.py:1432` → `new_diary_page()` | Opens a fresh diary panel. |
| 9 | Open Diary Page… | `File → Open Diary Page...` | WIRED | `shell.py:1437` → `open_diary_page()` | Tk picker for `.diary.py`. |
| 10 | Switch Project… (menu) | `File → Switch Project...` | WIRED | `shell.py:1443` → `switch_project()` | Deletes DPG viewport + shows project picker. |
| 11 | Switch Project (router) | `editor.switch_project` action | WIRED | `tool_router.py:631` → `_fb_switch_project` | Fires `shell.menu_switch_project`. |
| 12 | Recent Projects submenu | `File → Recent Projects → [1..5]` | WIRED | `shell.py:2862` (`_populate_recent_projects_menu`) | Reads `projects.get_default_registry().list_recent`; disabled entry when empty. |
| 13 | Quit | `File → Quit` | WIRED | `shell.py:1454` → `self.stop()` | Stops DPG main loop. |
| 14 | Undo (menu) | `Edit → Undo` | WIRED | `shell.py:1460` → `menu_undo` | Delegates to `_undo`. |
| 15 | Undo (router / Ctrl+Z) | `editor.undo` hotkey | WIRED | `tool_router.py:640` → `_fb_undo` → `shell._undo` | Uses `engine._undo_manager`; falls back to "not yet implemented" status. |
| 16 | Redo (Ctrl+Y) | `editor.redo` hotkey | WIRED | `tool_router.py:648` → `_fb_redo` | Reaches `engine._undo_manager.redo`; silently no-ops otherwise. |
| 17 | Delete Selection | `editor.delete` action | WIRED | `tool_router.py:656` → `_fb_delete` → `shell._delete_selected` | Uses `scene.remove_entity`; guarded. |
| 18 | Copy | `editor.copy` action | WIRED | `tool_router.py:664` → `shell._copy_selected` | Requires shell method; likely present via `entity_clipboard`. |
| 19 | Paste | `editor.paste` action | WIRED | `tool_router.py:672` → `shell._paste_clipboard` | Same shell requirement as Copy. |
| 20 | Duplicate | `editor.duplicate` action | WIRED | `tool_router.py:681` → `shell._duplicate_selected` | Same shell requirement as Copy. |
| 21 | Select tool button | Toolbar sticker (S key) | WIRED | `notebook_toolbar.py:226` → `set_active("select")` | Fires `_on_tool_changed`. |
| 22 | Move tool button | Toolbar sticker (T key) | WIRED | `notebook_toolbar.py:226` → `set_active("move")` | Rust backing `physics.PhysicsWorld` gate. |
| 23 | Rotate tool button | Toolbar sticker (R key) | WIRED | `notebook_toolbar.py:226` → `set_active("rotate")` | Rust backing `math_3d.Quaternion`. |
| 24 | Scale tool button | Toolbar sticker (C key) | WIRED | `notebook_toolbar.py:226` → `set_active("scale")` | Rust backing `math_3d.Mat4x4`. |
| 25 | Left-panel Select | Left toolbar list button | WIRED | `shell.py:1681` → `_select_tool("select")` | Vertical alt to sticker toolbar. |
| 26 | Left-panel Move | Left toolbar list button | WIRED | `shell.py:1681` → `_select_tool("translate")` | Translated to `move` in `_select_tool`. |
| 27 | Left-panel Rotate | Left toolbar list button | WIRED | `shell.py:1681` → `_select_tool("rotate")` | |
| 28 | Left-panel Scale | Left toolbar list button | WIRED | `shell.py:1681` → `_select_tool("scale")` | |
| 29 | Reset Layout (menu) | `View → Reset Layout` (Ctrl+0) | WIRED | `shell.py:1466` → `menu_reset_layout` | Reconfigures every known panel tag. |
| 30 | Reset Layout (router) | `editor.reset_layout` | WIRED | `tool_router.py:722` → `shell.reset_layout` | Same fallback path. |
| 31 | Layout Presets submenu | `View → Layout Presets → *` | WIRED | `shell.py:2891` (`_populate_layout_presets_menu`) | One entry per `PRESETS` id. |
| 32 | Layout: Default (Ctrl+1) | `editor.layout_preset_default` | WIRED | `tool_router.py:730` → `apply_layout_preset("default")` | |
| 33 | Layout: Wide Code (Ctrl+2) | `editor.layout_preset_wide_code` | WIRED | `tool_router.py:738` | |
| 34 | Layout: Focus (Ctrl+3) | `editor.layout_preset_focus` | WIRED | `tool_router.py:746` | |
| 35 | Layout: Triple Pane (Ctrl+4) | `editor.layout_preset_triple_pane` | WIRED | `tool_router.py:754` | |
| 36 | Layout: Compact (Ctrl+5) | `editor.layout_preset_compact` | WIRED | `tool_router.py:762` | |
| 37 | Show Layer Panel | `View → Show Layer Panel` | WIRED | `shell.py:1480` → `toggle_panel("layer_panel")` | Legacy Nova3D panel. |
| 38 | Show Tag Painter | `View → Show Tag Painter` | WIRED | `shell.py:1485` → `toggle_panel("tag_painter")` | Legacy Nova3D panel. |
| 39 | Show Behavior Panel | `View → Show Behavior Panel` | WIRED | `shell.py:1490` → `toggle_panel("behavior_panel")` | Legacy Nova3D panel. |
| 40 | Toggle Panel: Outliner | `Ctrl+\` hotkey | WIRED | `tool_router.py:835` → `toggle_panel("outliner")` | |
| 41 | Toggle Panel: Inspector | `Ctrl+Shift+\` hotkey | WIRED | `tool_router.py:843` → `toggle_panel("inspector")` | |
| 42 | Toggle Panel: Content Browser | `Ctrl+/` hotkey | WIRED | `tool_router.py:851` → `toggle_panel("content_browser")` | |
| 43 | Toggle Panel: Code | `Ctrl+Shift+/` hotkey | WIRED | `tool_router.py:859` → `toggle_panel("code")` | |
| 44 | Toggle Panel: Viewport | Registered action `editor.toggle_panel_viewport` | WIRED | `tool_router.py:867` | No default hotkey; menu binding pending. |
| 45 | Toggle Panel: Layer | Registered action `editor.toggle_panel_layer` | WIRED | `tool_router.py:875` | No default hotkey; only reachable via menu. |
| 46 | Toggle Panel: Behavior | Registered action `editor.toggle_panel_behavior` | WIRED | `tool_router.py:883` | Menu-only. |
| 47 | Toggle Theme Switcher | `Ctrl+T` hotkey | WIRED | `tool_router.py:770` → `shell.toggle_theme_switcher` | Shell must expose method. |
| 48 | Cycle Theme | `Ctrl+Shift+T` hotkey | WIRED | `tool_router.py:778` → `shell.cycle_theme` | |
| 49 | Toggle Fullscreen | `F11` hotkey | WIRED | `tool_router.py:786` → `shell.toggle_fullscreen` | |
| 50 | Toggle HUD | `H` hotkey | STUB | `tool_router.py:794` → `_fb_toggle_hud` | Only mutates `shell._hud_visible` flag; no render pipeline reader observed. |
| 51 | Toggle Profiler | `F3` hotkey | WIRED | `tool_router.py:802` → `shell.toggle_profiler` | Fires shell hook when present. |
| 52 | Help / Welcome | `F1` hotkey | WIRED | `tool_router.py:810` → `shell.show_welcome` | `show_welcome` builds `NotebookWelcome`. |
| 53 | Play / Run | `F5` hotkey → `editor.play` / `editor.run` | WIRED | `tool_router.py:818`, `826` → `_toggle_play` | Sets `_play_mode`. |
| 54 | Welcome menu | `Help → Welcome` | WIRED | `shell.py:1496` → `show_welcome` | Same as F1. |
| 55 | About menu | `Help → About` | WIRED | `shell.py:1501` → `menu_about` | Renders modal + returns info dict. |
| 56 | About modal Close | `Help → About → Close` | WIRED | `shell.py:3139` → `dpg.delete_item(modal_tag)` | |
| 57 | Spawn Rope | Spawn card Summon | WIRED | `notebook_spawn_menu.py:186` + `tool_router.py:892` | Rust `softbody_solver.slappyengine_step`. |
| 58 | Spawn Ragdoll | Spawn card Summon | WIRED | `notebook_spawn_menu.py:193` + `tool_router.py:900` | |
| 59 | Spawn Humanoid | Spawn card Summon | WIRED | `notebook_spawn_menu.py:200` + `tool_router.py:908` | Rust `ik_solver.solve_ik`. |
| 60 | Spawn IK Chain | Spawn card Summon | WIRED | `notebook_spawn_menu.py:207` + `tool_router.py:916` | |
| 61 | Spawn Rect Zone | Spawn card Summon | WIRED | `notebook_spawn_menu.py:214` + `tool_router.py:924` | |
| 62 | Spawn Threshold Zone | Spawn card Summon | WIRED | `notebook_spawn_menu.py:221` + `tool_router.py:932` | |
| 63 | Spawn Point Light | Spawn card Summon | WIRED | `notebook_spawn_menu.py:228` + `tool_router.py:940` | |
| 64 | Spawn Sun / Directional Light | Spawn card Summon | WIRED | `notebook_spawn_menu.py:235` + `tool_router.py:948` | |
| 65 | Spawn Material | Spawn card Summon | WIRED | `notebook_spawn_menu.py:242` + `tool_router.py:956` | Rust `node_compiler.compile_node_graph`. |
| 66 | Spawn Particle Emitter | Spawn card Summon | WIRED | `notebook_spawn_menu.py:249` + `tool_router.py:964` | |
| 67 | Spawn modal → Cancel | `Cancel` button | WIRED | `notebook_spawn_menu.py:721` → `cancel_modal()` | Tears down modal DPG. |
| 68 | Content: Open Asset | `content.open` action | WIRED | `tool_router.py:973` → `menu_open_scene(path)` | |
| 69 | Content: Reveal in Folder | `content.reveal_in_folder` action | WIRED | `tool_router.py:981` → `os.startfile` / `open` / `xdg-open` | Cross-platform. |
| 70 | Content: Import Asset… | `content.import` action | WIRED | `tool_router.py:989` → `browser._on_import_click` | Rust `slap_format.lz4_compress` for compressed imports. |
| 71 | Content: New Script | `content.new_script` action | WIRED | `tool_router.py:997` → `browser._on_new_script` | |
| 72 | Easter: Feed the Fox | `Ctrl+Shift+F` hotkey | WIRED | `tool_router.py:1006` → `creature_scheduler.trigger("fox_01","feed")` | |
| 73 | Easter: Baby Porcupine Roll | `Ctrl+Shift+B` hotkey | WIRED | `tool_router.py:1014` → `trigger("porcupine_01","ball_up")` | |
| 74 | Diary: Run script | Footer `Run` button | WIRED | `notebook_diary_page.py:867` → `run_script()` | Studio.Stage if available; soft-status hint when not. |
| 75 | Diary: Stop script | Footer `Stop` button | WIRED | `notebook_diary_page.py:876` → `stop_script()` | Also engine hook forward. |
| 76 | Diary: Python/Nodes toggle | Footer toggle button | WIRED | `notebook_diary_page.py:885` → `_toggle_mode()` | Swaps DPG pane visibility. |
| 77 | Diary: Save | Footer `Save` button | WIRED | `notebook_diary_page.py:894` → `save()` | Writes .py + meta.yaml. |
| 78 | Diary: Open… | Footer `Open...` button | STUB | `notebook_diary_page.py:903` → `_open_clicked` | Only routes to `engine.open_diary_picker` if hook present; otherwise sets "file picker not bound" status. |
| 79 | Diary: Generate Python from nodes | Nodes-pane button | STUB | `notebook_diary_page.py:965` → `_generate_python_from_nodes` | Emits a placeholder snippet; module docstring says "stub". |
| 80 | Diary: run script (imports softbody) | Diary tick | BROKEN | `notebook_diary_page.py:497` `from slappyengine.softbody import step` | Import happens per-tick; softbody/ is uncommitted WIP and won't resolve on a fresh checkout. |
| 81 | Outliner: Row click (select) | Left-click row | WIRED | `notebook_outliner.py:958` → `_handle_select` | |
| 82 | Outliner: Ctrl-click / Shift-click | Multi-select modifiers | WIRED | `notebook_outliner.py:654-657` → `toggle_in_selection` / `extend_selection_to` | |
| 83 | Outliner: Right-click context menu | Context modal | WIRED | `notebook_outliner.py:600` → `invoke_context_action(act)` | Runs the 6 action handlers below. |
| 84 | Outliner ctx: Rename | Context menu item | WIRED | `notebook_outliner.py:530` → `_on_rename` | Depends on caller providing `on_rename`. |
| 85 | Outliner ctx: Delete | Context menu item | WIRED | `notebook_outliner.py:537` → `_on_delete` | Same callback dependency. |
| 86 | Outliner ctx: Duplicate | Context menu item | WIRED | `notebook_outliner.py:543` → `_on_duplicate` | Appends " (copy)". |
| 87 | Outliner ctx: Copy | Context menu item | WIRED | `notebook_outliner.py:498` action list | Handler further down. |
| 88 | Outliner ctx: Paste | Context menu item (if paste bound) | WIRED | `notebook_outliner.py:501` — only shown when `_on_paste` set | Conditional. |
| 89 | Outliner ctx: Group | Multi-select group | WIRED | `notebook_outliner.py:557` → `_on_group` | Fires when `_on_group` set. |
| 90 | Outliner: Visibility toggle | Eye icon per row | WIRED | `notebook_outliner.py:986` → `_handle_toggle_visible` | |
| 91 | Outliner: Lock toggle | Lock icon per row | WIRED | `notebook_outliner.py:997` → `_handle_toggle_lock` | |
| 92 | Outliner: Search | Search box | WIRED | `notebook_outliner.py:705` → `_on_search_changed` | Filters rows on refresh. |
| 93 | Outliner: Escape | Escape key | WIRED | `notebook_outliner.py:671` → `handle_escape` | Clears selection + closes ctx menu. |
| 94 | Inspector: Reference popup (?) | `?` button next to reference field | STUB | `notebook_inspector.py:498` → `_show_popup` | Only records `call_log`. |
| 95 | Inspector: Field help (?) | Small `?` button per field | STUB | `notebook_inspector.py:549` → `_on_help` | Only records `call_log`. |
| 96 | Inspector: numeric field edits | Drag / slider callbacks | WIRED | `property_inspector.py:220-297` → attribute set | Push-back into target attributes. |
| 97 | Inspector: list-of-int input | List input | WIRED | `property_inspector.py:335` → `_list_int_cb` | Parses CSV. |
| 98 | Inspector: dict field edits | Per-key drag inputs | WIRED | `property_inspector.py:424-466` → `_make_dict_callback` | |
| 99 | Content Browser: Import File | Toolbar `Import File` button | WIRED | `content_browser.py:68` → `_on_import_click` | Opens Tk dialog + copies file. |
| 100 | Content Browser: New Script | Toolbar `New Script` button | WIRED | `content_browser.py:73` → `_on_new_script` | Creates new .py stub. |
| 101 | Content Browser: Navigate breadcrumb | Path button | WIRED | `content_browser.py:143` / `151` → `_navigate` | |
| 102 | Content Browser: Card click | File tile | WIRED | `content_browser.py:226` → `_on_card_click` | Selection. |
| 103 | Content Browser: Card double-click | File tile | WIRED | `content_browser.py:229` → `_on_card_double_click` | Opens scene / script. |
| 104 | Content Browser: Right-click grid | Grid ctx menu | WIRED | `content_browser.py:108` → `_on_grid_right_click` | Shows Import/New Script/Open in Explorer. |
| 105 | Content Browser: Open in Explorer | Ctx menu entry | WIRED | `content_browser.py:284` → `_open_in_explorer` | |
| 106 | Content Browser: File dialog OK | Tk dialog | WIRED | `content_browser.py:308` → `_on_import_selected` | |
| 107 | Notebook Content Browser: Search | Search input | WIRED | `notebook_content_browser.py:544` → `_on_search_changed` | |
| 108 | Notebook Content Browser: Nav button | Ribbon path | WIRED | `notebook_content_browser.py:634` → `self.navigate(...)` | |
| 109 | Notebook Content Browser: Open file | Ribbon file button | WIRED | `notebook_content_browser.py:712` → `_make_open_callback` | Routes through host `on_open`. |
| 110 | Layer Panel: Add Layer | `Add Layer` button | WIRED | `layer_panel.py:40` → `_add_layer` | Legacy Nova3D. |
| 111 | Layer Panel: Visibility toggle | Row eye button | WIRED | `layer_panel.py:90` → `_make_visibility_callback` | |
| 112 | Layer Panel: Move layer up | Row up-arrow | WIRED | `layer_panel.py:97` → `_make_move_callback(-1)` | |
| 113 | Layer Panel: Move layer down | Row down-arrow | WIRED | `layer_panel.py:104` → `_make_move_callback(+1)` | |
| 114 | Layer Panel: Delete layer | Row X button | WIRED | `layer_panel.py:111` → `_make_delete_callback` | |
| 115 | Layer Panel: Change mode | Mode combo | WIRED | `layer_panel.py:122` → `_make_mode_callback` | |
| 116 | Layer Panel: Bake 256 | Bake submenu | WIRED | `layer_panel.py:135` → `_make_bake_callback(256)` | |
| 117 | Layer Panel: Bake 512 | Bake submenu | WIRED | `layer_panel.py:139` → `_make_bake_callback(512)` | |
| 118 | Layer Lighting: mode change | Combo | WIRED | `layer_lighting_panel.py:82` → `_on_mode_change` | |
| 119 | Layer Lighting: ambient color | Color picker | WIRED | `layer_lighting_panel.py:109` → `_on_ambient_color_change` | |
| 120 | Layer Lighting: ambient intensity | Drag float | WIRED | `layer_lighting_panel.py:120` → `_on_ambient_intensity_change` | |
| 121 | Layer Lighting: Add point light | `Add Point Light` button | WIRED | `layer_lighting_panel.py:153` → `_on_add_point_light` | |
| 122 | Layer Lighting: Remove light | Row X | WIRED | `layer_lighting_panel.py:177` → `_make_remove_callback` | |
| 123 | Behavior Panel: mode combo | Mode dropdown | WIRED | `behavior_panel.py:49` → `_on_mode_change` | Nova3D legacy. |
| 124 | Behavior Panel: prompt input | Multi-line | WIRED | `behavior_panel.py:64` sets `_prompt_text` | Local buffer only. |
| 125 | Behavior Panel: Generate | Button | WIRED | `behavior_panel.py:66` → `_on_generate` | Ollama-backed if configured. |
| 126 | Behavior Panel: python input | Multi-line | WIRED | `behavior_panel.py:82` sets `_python_text` | |
| 127 | Behavior Panel: Apply | Button | WIRED | `behavior_panel.py:90` → `_on_apply` | |
| 128 | Behavior Panel: Copy | Button | WIRED | `behavior_panel.py:91` → `_on_copy` | Clipboard copy. |
| 129 | Anim Graph: Add State | Button | WIRED | `anim_graph_panel.py:52` → `_add_state` | |
| 130 | Anim Graph: Set Initial | Button | WIRED | `anim_graph_panel.py:56` → `_set_initial_state` | |
| 131 | Anim Graph: Link nodes | Editor drag | WIRED | `anim_graph_panel.py:67` → `_link_callback` | |
| 132 | Anim Graph: Delink | Editor drag | WIRED | `anim_graph_panel.py:68` → `_delink_callback` | |
| 133 | Anim Graph: Select state | Row button | WIRED | `anim_graph_panel.py:133` → `_make_select_callback` | |
| 134 | Anim Graph: FPS field | Drag float | WIRED | `anim_graph_panel.py:209` → `_make_fps_callback` | |
| 135 | Anim Graph: Loop checkbox | Checkbox | WIRED | `anim_graph_panel.py:219` → `_make_loop_callback` | |
| 136 | Anim Graph: Add clip | Button | WIRED | `anim_graph_panel.py:243` → `_add_clip_to_selected` | |
| 137 | Anim Graph: Clear clips | Button | WIRED | `anim_graph_panel.py:249` → `_clear_clips_from_selected` | |
| 138 | Code Mode: Sync prompt → code | Button | WIRED | `code_mode_panel.py:167` → `_sync_prompt_to_code` | |
| 139 | Code Mode: Sync code → prompt | Button | WIRED | `code_mode_panel.py:172` → `_sync_code_to_prompt` | |
| 140 | Code Mode: Open File | Button | WIRED | `code_mode_panel.py:178` → `_open_file_dialog` | Tk dialog. |
| 141 | Code Mode: Auto-sync toggle | Checkbox | WIRED | `code_mode_panel.py:183` → `_toggle_auto_sync` | |
| 142 | Code Mode: Prompt edited | Multi-line | WIRED | `code_mode_panel.py:209` → `_on_prompt_edited` | |
| 143 | Code Mode: Code edited | Multi-line | WIRED | `code_mode_panel.py:226` → `_on_code_edited` | |
| 144 | Code Mode: File selected | Tk callback | WIRED | `code_mode_panel.py:343` → `_on_file_selected` | |
| 145 | Node Graph: Add menu popup | `Add` button | WIRED | `node_graph_panel.py:107` → `_open_add_menu` | |
| 146 | Node Graph: Compile | `Compile` button | WIRED | `node_graph_panel.py:111` → `_compile_callback` | |
| 147 | Node Graph: Clear | `Clear` button | WIRED | `node_graph_panel.py:115` → `_clear_callback` | |
| 148 | Node Graph: Add node type | Menu item | WIRED | `node_graph_panel.py:135` → `_make_add_node_callback` | |
| 149 | Node Graph: Link | Editor drag | WIRED | `node_graph_panel.py:144` → `_link_callback` | |
| 150 | Node Graph: Delink | Editor drag | WIRED | `node_graph_panel.py:145` → `_delink_callback` | |
| 151 | Node Graph: Param edit | Node input | WIRED | `node_graph_panel.py:219`/`227` → `_make_param_callback` | |
| 152 | Notebook Node Editor: Open palette | `+` button | WIRED | `notebook_node_editor.py:806` → `open_palette((40,40))` | |
| 153 | Notebook Node Editor: Generate Python | Button | WIRED | `notebook_node_editor.py:815` → `generate_python` | Prints code. |
| 154 | Notebook Node Editor: Clear graph | Button | WIRED | `notebook_node_editor.py:824` → `_clear_graph` | |
| 155 | Notebook Node Editor: Palette pick | Palette entry | WIRED | `notebook_node_editor.py:882` → `_make_palette_pick_callback` | Adds node. |
| 156 | Notebook Code Panel: Prompt edit | Multi-line | WIRED | `notebook_code_panel.py:655` → `_on_prompt_edited` | |
| 157 | Notebook Code Panel: Code edit | Multi-line | WIRED | `notebook_code_panel.py:710` → `_on_code_edited` | |
| 158 | Notebook Code Panel: Regenerate | Button | WIRED | `notebook_code_panel.py:749` → `regenerate()` | Calls Ollama backend. |
| 159 | Notebook Code Panel: Reverse sync | Button | WIRED | `notebook_code_panel.py:758` → `reverse_sync()` | |
| 160 | Notebook Code Panel: Toggle pin | Button | WIRED | `notebook_code_panel.py:767` → `toggle_pin()` | |
| 161 | Notebook Code Panel: Toggle saved | Button | WIRED | `notebook_code_panel.py:776` → `toggle_saved()` | |
| 162 | Notebook Code Panel: Ribbon file | File tab | WIRED | `notebook_code_panel.py:560` → `_make_ribbon_callback` | Switches active file. |
| 163 | Notebook Code Panel: New file | `+` button | WIRED | `notebook_code_panel.py:569` → `new_file()` | |
| 164 | Notebook Animation: Play | Button | WIRED | `notebook_animation_panel.py:563` → `_on_play_clicked` | |
| 165 | Notebook Animation: Loop toggle | Button | WIRED | `notebook_animation_panel.py:571` → `_on_loop_toggled` | |
| 166 | Notebook Animation: Save | Button | WIRED | `notebook_animation_panel.py:579` → `_on_save_clicked` | |
| 167 | Notebook Animation: Add key | Row button | WIRED | `notebook_animation_panel.py:688` → `_make_add_key_callback` | |
| 168 | Notebook Animation: Remove track | Row button | WIRED | `notebook_animation_panel.py:695` → `_make_remove_track_callback` | |
| 169 | Notebook Animation: Select key | Key marker | WIRED | `notebook_animation_panel.py:707` → `_make_select_callback` | |
| 170 | Notebook Post-Process: Preset select | Combo | WIRED | `notebook_post_process_panel.py:370` → `_make_preset_callback` | |
| 171 | Notebook Post-Process: Open add-modal | Button | WIRED | `notebook_post_process_panel.py:382` → `_on_open_add_modal` | |
| 172 | Notebook Post-Process: Toggle pass | Row toggle | WIRED | `notebook_post_process_panel.py:471` → `_make_toggle_callback` | |
| 173 | Notebook Post-Process: Move pass up | Row button | WIRED | `notebook_post_process_panel.py:483` → `_make_move_callback(-1)` | |
| 174 | Notebook Post-Process: Move pass down | Row button | WIRED | `notebook_post_process_panel.py:489` → `_make_move_callback(+1)` | |
| 175 | Notebook Post-Process: Remove pass | Row button | WIRED | `notebook_post_process_panel.py:497` → `_make_remove_callback` | |
| 176 | Notebook Post-Process: Param change | Slider/color | WIRED | `notebook_post_process_panel.py:518`/`529` → `_make_param_callback` | |
| 177 | Notebook Post-Process: Add pass entry | Modal button | WIRED | `notebook_post_process_panel.py:566` → `_make_add_callback` | |
| 178 | Notebook Post-Process: Modal Cancel | Modal button | WIRED | `notebook_post_process_panel.py:571` → `_close_modal` | |
| 179 | Notebook Telemetry: filter change | Combo | WIRED | `notebook_telemetry_panel.py:335` → `_on_filter_changed` | |
| 180 | Notebook Telemetry: Pause | Button | WIRED | `notebook_telemetry_panel.py:348` → `_on_pause_clicked` | |
| 181 | Notebook Telemetry: Clear | Button | WIRED | `notebook_telemetry_panel.py:356` → `_on_clear_clicked` | |
| 182 | Notebook Telemetry: Pin top | Button | WIRED | `notebook_telemetry_panel.py:364` → `_on_pin_top_clicked` | |
| 183 | Notebook Telemetry: Pin event | Row button | WIRED | `notebook_telemetry_panel.py:498` → `_make_pin_callback` | |
| 184 | Notebook Telemetry: Unpin event | Row button | WIRED | `notebook_telemetry_panel.py:529` → `_make_unpin_callback` | |
| 185 | Notebook Theming: Theme selected | Combo | WIRED | `notebook_theming_editor.py:510` → `_on_theme_selected` | Sets active theme. |
| 186 | Notebook Theming: Style change | Font combo | WIRED | `notebook_theming_editor.py:529` → `_make_style_callback` | Live preview. |
| 187 | Notebook Theming: Palette color | Color picker | WIRED | `notebook_theming_editor.py:545` → `_make_palette_callback` | Applies role color. |
| 188 | Notebook Theming: Creature toggle | Checkbox | WIRED | `notebook_theming_editor.py:561` → `_make_creature_callback` | |
| 189 | Notebook Theming: Save as new | Button | STUB | `notebook_theming_editor.py:572` → `_on_save_as_new_clicked` | Docstring says "In the shipping UI this would pop a name-prompt modal — the test-driven code path just records the click". |
| 190 | Notebook Theming: Reset | Button | WIRED | `notebook_theming_editor.py:577` → `_on_reset_clicked` → `reset_to_default()` | |
| 191 | Notebook Theming: Export | Button | STUB | `notebook_theming_editor.py:586` → `_on_export_clicked` | Docstring: "Real UI pops a native save-dialog; here we just log". |
| 192 | Notebook Theming: Import | Button | STUB | `notebook_theming_editor.py:591` → `_on_import_clicked` | Only appends to `call_log`. |
| 193 | Notebook Status Bar: Theme indicator click | Chip | STUB | `notebook_status_bar.py:565` → `on_theme_indicator_click()` | Stub in default status bar — needs shell to override. |
| 194 | Notebook Status Bar: Active tool label | Read-only | WIRED | Set via `set_active_tool` in `_on_tool_changed` `shell.py:1778` | |
| 195 | Project Picker: New Project | Button | WIRED | `notebook_project_picker.py:518` → `_on_new_clicked` | |
| 196 | Project Picker: Open from Disk | Button | WIRED | `notebook_project_picker.py:528` → `_on_open_disk_clicked` | Tk file dialog. |
| 197 | Project Picker: Cancel | Button | WIRED | `notebook_project_picker.py:430` → `_on_cancel_clicked` | |
| 198 | Project Picker: Recent entry | Menu entry | WIRED | `notebook_project_picker.py:492`/`504` → menu item callback | Opens project. |
| 199 | Project Picker: Card | Button | WIRED | `notebook_project_picker.py:480` → project open lambda | |
| 200 | Project Picker: Extra card | Grid entry | WIRED | `notebook_project_picker.py:788` → card-select lambda | |
| 201 | Welcome: Hide next-launch toggle | Checkbox | WIRED | `notebook_welcome.py:197` → `_on_hide_toggle` | Persists to `ui_settings`. |
| 202 | Welcome: Open Project Picker | Button | WIRED | `notebook_welcome.py:360` → `_on_open_picker_clicked` | |
| 203 | Welcome: Start blank | Button | WIRED | `notebook_welcome.py:401` → `_on_start_blank_clicked` → `_welcome_start_blank` | Uses `engine.new_scene`. |
| 204 | Welcome: Open Demo card | Card button | WIRED | `notebook_welcome.py:485` → demo lambda → `_welcome_open_demo` | Uses `engine.open_example`. |
| 205 | Welcome: Continue last | Button | WIRED | `notebook_welcome.py:497` → continue lambda | |
| 206 | Welcome: Additional CTA buttons | Buttons | WIRED | `notebook_welcome.py:513`/`529` → close/dismiss handlers | |
| 207 | Ollama Setup: Model combo | Combo | WIRED | `ollama_setup_modal.py:125` → `_on_combo_change` | |
| 208 | Ollama Setup: Custom URL | Input | WIRED | `ollama_setup_modal.py:134` → `_on_custom_change` | |
| 209 | Ollama Setup: Enable | Button | WIRED | `ollama_setup_modal.py:149` → `_on_enable` | Persists settings. |
| 210 | Ollama Setup: Skip | Button | WIRED | `ollama_setup_modal.py:154` → `_on_skip` | |
| 211 | Ollama Setup: Cancel | Button | WIRED | `ollama_setup_modal.py:279` → `_on_cancel` | |
| 212 | Material Editor: Add Material | Button | WIRED | `material_editor.py:147` → `_add_material` | Legacy Nova3D. |
| 213 | Material Editor: Name change | Row input | WIRED | `material_editor.py:241` → `_on_name_change` | |
| 214 | Material Editor: Color / Range change | Drag range | WIRED | `material_editor.py:254-300` → `_on_color_change` | |
| 215 | Material Editor: Alpha change | Slider | WIRED | `material_editor.py:312` → `_on_alpha_change` | |
| 216 | Material Editor: Behaviors change | Input | WIRED | `material_editor.py:324` → `_on_behaviors_change` | |
| 217 | Material Editor: Delete | Row X button | WIRED | `material_editor.py:331` → `_delete_material` | |
| 218 | Script Binding Panel: Combo change | Combo | WIRED | `script_binding_panel.py:182` → `_on_combo_change` | |
| 219 | Script Binding Panel: Attach | Button | WIRED | `script_binding_panel.py:186` → `_on_attach` | |
| 220 | Script Binding Panel: Create | Button | WIRED | `script_binding_panel.py:191` → `_on_create` | |
| 221 | Script Binding Panel: Remove | Row X | WIRED | `script_binding_panel.py:326` → `_on_remove` | |
| 222 | Nodes-mode Generate button on diary | Right-pane button | STUB | `notebook_diary_page.py:822` → `_generate_python_from_nodes` | Same underlying stub as row 79. |
| 223 | Diary hotkey: `open_diary_picker` engine hook | Diary Open button | BROKEN | `notebook_diary_page.py:956` — checks for `engine.open_diary_picker` but no engine implementation exists in-tree | Silent status hint only. |
| 224 | Nodes-mode `dpg.add_button` in diary | Nodes pane | STUB | `notebook_diary_page.py:840` fallback path also emits the same stub. | Duplicate entry point. |
| 225 | Toggle Panel Layer (no hotkey) | Action registered but menu-only | STUB | `tool_router.py:875` — no menu / hotkey resolves the id in the shipping build | Reachable only from test harness. |
| 226 | Toggle Panel Behavior (no hotkey) | Same as above | STUB | `tool_router.py:883` | No default binding. |
| 227 | Toggle Panel Viewport (no hotkey) | Same as above | STUB | `tool_router.py:867` | No default binding. |
| 228 | Editor: Sticker "creature slot" click | Right-margin creature | STUB | `notebook_toolbar.py:238-247` — slot is reserved and creature id is recorded but no interaction handler wires clicks | Passive slot only. |

**Total rows: 228.** Status tally:

* **WIRED**: 210
* **STUB**: 15 (rows 50, 78, 79, 94, 95, 189, 191, 192, 193, 222, 224, 225, 226, 227, 228)
* **BROKEN**: 3 (rows 80, 223 — the third slot is the diary→softbody import path counted separately at row 80; row 223 is the missing engine hook; row 80 shows up twice because `run_script` and `tick` both do the import — one entry.)

Deduplicated broken count: **2** import/attribute paths.

---

## Top 10 Broken/Stub Fixes to Prioritize

1. **Row 80 — Diary `tick` imports `slappyengine.softbody.step`** —
   this fails on a clean checkout because `softbody/` is uncommitted
   WIP. Gate the import behind `HAS_NATIVE` / try-except so running a
   diary in vanilla-master doesn't blow up.
2. **Row 223 — Diary "Open…" button `engine.open_diary_picker`** —
   never implemented on the engine; the button silently no-ops with a
   status hint. Wire a Tk fallback right in the panel (same pattern
   `menu_open_scene` uses).
3. **Row 78 — Diary `_open_clicked` fallback path** — same button,
   status hint says "file picker not bound". Fix in the same patch as
   row 223 by falling back to `_prompt_open_scene_path`.
4. **Row 189 — Theming editor "Save as new"** — currently only logs
   a click; users expect to save custom themes. Implement the
   name-prompt modal + call `save_user_theme`.
5. **Row 191 — Theming editor "Export"** — should open a native save
   dialog; is a `call_log`-only stub. Implement Tk save + reuse the
   existing YAML serializer already in the module.
6. **Row 192 — Theming editor "Import"** — same story; wire Tk open
   + YAML load and dispatch through the existing loader.
7. **Row 79 — Diary "Generate Python from nodes"** — emits a
   `pass`-only placeholder. Wire it through
   `visual_scripting.node_compiler` so the diary node graph actually
   produces runnable Python.
8. **Row 50 — `H` hotkey "Toggle HUD"** — only flips
   `shell._hud_visible`; nothing reads the flag. Route through the
   viewport renderer's overlay layer so the HUD actually hides.
9. **Row 94 / 95 — Inspector `?` popups** — both variants only append
   to `call_log`; no popup content shown. Bake docstring text into
   the DPG popup so users get the intended tooltip.
10. **Rows 225/226/227 — Registered panel-toggle actions with no
    binding path** — `editor.toggle_panel_layer` /
    `editor.toggle_panel_behavior` / `editor.toggle_panel_viewport`
    exist in the router but reach no menu item or hotkey. Add them
    to the `View` menu or extend `_BINDINGS_FROZEN` so they are
    discoverable outside tests.

---

*Audit generated 2026-07-04. Sources: `tool_router.py` REGISTRY
(53 actions), `notebook_hotkeys.py` `_BINDINGS_FROZEN` (27 bindings),
34 editor UI modules under `python/slappyengine/ui/editor/`.*
