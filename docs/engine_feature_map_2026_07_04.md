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
| 229 | `editor.save_project` action | Router action id (X3) | WIRED | `tool_router.py:672` → `_fb_save_project` → `actions/project_actions.py:73` (`save_project`) | Writes `project.slap_proj` via `Project.save()`; returns `{"status":"saved","path":...}`. |
| 230 | `editor.new_project` action | Router action id (X3) | WIRED | `tool_router.py:680` → `_fb_new_project` → `actions/project_actions.py:91` (`new_project`) | Scaffolds a fresh project via `Project.new()` and registers it in the recents. |
| 231 | `editor.open_recent` action | Router action id (X3) | WIRED | `tool_router.py:688` → `_fb_open_recent` → `actions/project_actions.py:143` (`open_recent`) | Opens by `path` or `index` from `ProjectRegistry.list_recent()`. |
| 232 | `view.reset_layout` action | Router action id (X3) | WIRED | `tool_router.py:816` → `_fb_view_reset_layout` → `actions/view_actions.py:19` (`reset_layout`) | Restores DEFAULT preset via `apply_layout_preset` with a headless-safe fallback to `apply_preset`. |
| 233 | `edit.duplicate_selection` action | Router action id (X3) | WIRED | `tool_router.py:757` → `_fb_duplicate_selection` → `actions/edit_actions.py:44` (`duplicate_selection`) | Snapshots + pastes via `EntityClipboard`; prefers shell's `_duplicate_selected` when present. |
| 234 | Notebook Startup Prompt: open recent row | `notebook_startup_prompt.py:428` → `_on_row_clicked` | WIRED | V2. Routes through `project_registry.open`. |
| 235 | Notebook Startup Prompt: New project | `notebook_startup_prompt.py:431` → `_on_new_clicked` | WIRED | V2. Launches new-project flow. |
| 236 | Notebook Startup Prompt: Skip | `notebook_startup_prompt.py:434` → `_on_skip_clicked` | WIRED | V2. Closes the modal. |
| 237 | Notebook Project Registry: Open project | `notebook_project_registry.py:413` → `_on_open_clicked` | WIRED | V2. Commits to `ProjectRegistry.open`. |
| 238 | Notebook Project Registry: Remove project | `notebook_project_registry.py:416` → `_on_remove_clicked` | WIRED | V2. |
| 239 | Notebook Project Registry: Add project | `notebook_project_registry.py:419` → `_on_add_clicked` → `_on_folder_chosen` | WIRED | V2. Uses Tk folder dialog. |
| 240 | Notebook SnapOverlay: snap preview | Drag event | WIRED | V4. `notebook_snap_overlay.py:626` → `_on_snap_preview` renders dashed-rect ghost. |
| 241 | Notebook SnapOverlay: dock preview | Drag event | WIRED | V4. `notebook_snap_overlay.py:635` → `_on_dock_preview` renders arrow indicator. |
| 242 | Content Browser: `set_project` project asset tree | X4 `notebook_content_browser.py::set_project` | WIRED | Groups files into 6 kinds; fuzzy search + right-click ctx menu. |
| 243 | Content Browser: Delete asset (ctx menu) | X4 right-click ctx entry | STUB | Ctx entry rendered but delete handler defers to host callback which may be unbound; Y1 target. |
| 244 | Post-Process: `apply_manifest` executor | X5 `post_process/executor.py::from_manifest` + `apply_manifest` | WIRED | Declarative pass ordering; carries manifest through the CPU dispatcher. |
| 245 | User Overrides: live-reload autoreload | X6 `ui/user_overrides.py::autoreload` | WIRED | Watchdog soft-imported; NullWatcherHandle when unavailable. |
| 246 | Widget primitives: 6 new notebook widgets | X7 `ui/widgets/{glitter_progress_bar, ribbon_tab, paper_clip_attachment, washi_tape_divider, sketch_button, ink_stamp_badge}.py` | WIRED | Each inherits `_NotebookWidget` lifecycle (mount / set_theme / set_enabled). |
| 247 | Visual Scripting: 18+ material graph nodes | V5 `visual_scripting/material_nodes.py` | WIRED | WGSL-emitting nodes. Palette-visible from Notebook Node Editor. |
| 248 | Visual Scripting: Python <-> Graph codegen | V6 `visual_scripting/codegen.py` | WIRED | Bidirectional; still not wired into the Diary "Generate Python from nodes" button (row 79 remains STUB). |
| 249 | Theming Editor: Save as new (via UserThemeStore) | W2 `notebook_theming_editor.py::save_as_new` | WIRED | V1 row 189 flipped STUB -> WIRED under W2 hardening. Import / Export still STUB (rows 191/192). |
| 250 | `editor.toggle_panel_tag_painter` action | `tool_router.py` (post-V1 registration `b019bdb`) | WIRED | Fills tag-painter toggle gap. |
| 251 | 8 animated washi-tape shaders | V7 `ui/theme/washi_tape/library.py` | WIRED | heart_pulse / sparkle_shimmer / rainbow_flow / marching_dots / wave_shift / dashed_scroll / stars_twinkle / music_notes_flow. Budget widened to 1000B for animated variants. |
| 252 | `tool.select_all` action | Router action id (Y1) | WIRED | `tool_router.py:846` → `_fb_select_all` → `actions/selection_actions.py:137` (`select_all`) | Reads scene from `ctx["scene"]` / `shell._engine.scene`; writes `_selected_entities` + populates `_selected_entity` with the head. |
| 253 | `tool.deselect_all` action | Router action id (Y1) | WIRED | `tool_router.py:854` → `_fb_deselect_all` → `actions/selection_actions.py:173` (`deselect_all`) | Clears both `_selected_entity` + `_selected_entities`; headless-safe when shell missing. |
| 254 | `editor.copy_selection` action | Router action id (Y1) | WIRED | `tool_router.py:796` → `_fb_copy_selection` → `actions/selection_actions.py:192` (`copy_selection`) | Snapshots into the process-wide `EntityClipboard`; does NOT auto-paste (contrast with `edit.duplicate_selection`). |
| 255 | `editor.paste_selection` action | Router action id (Y1) | WIRED | `tool_router.py:804` → `_fb_paste_selection` → `actions/selection_actions.py:212` (`paste_selection`) | Pulls from `EntityClipboard`, applies `name_suffix` (default `" (paste)"`), best-effort `scene.add(clone)` when reachable. |
| 256 | `theme.cycle` action | Router action id (Y1) | WIRED | `tool_router.py:939` → `_fb_theme_cycle` → `actions/theme_actions.py:42` (`cycle_theme`) | Prefers `shell.cycle_theme()`; headless fallback walks `list_registered_themes()` with a module-level deterministic cursor. |
| 257 | `tool.snap_to_grid` action | Router action id (Z7) | WIRED | `tool_router.py` → `_fb_snap_to_grid` → `actions/tool_settings_actions.py::toggle_snap_to_grid` | Toggles `shell._snap_manager.config.enable_grid`; accepts `ctx["force"]` to lock ON/OFF; headless-safe module-level flag when no shell is reachable. |
| 258 | `view.zoom_in` action | Router action id (Z7) | WIRED | `tool_router.py` → `_fb_zoom_in` → `actions/camera_actions.py::zoom_in` | Divides `_cam_distance` by `ctx["step"]` (default 1.2); clamped to `[0.05, 10000]`; handles 2D `_zoom_level` cameras too. |
| 259 | `view.zoom_out` action | Router action id (Z7) | WIRED | `tool_router.py` → `_fb_zoom_out` → `actions/camera_actions.py::zoom_out` | Mirror of `view.zoom_in`; multiplies distance / shrinks 2D zoom. Same clamps. |
| 260 | `view.zoom_reset` action | Router action id (Z7) | WIRED | `tool_router.py` → `_fb_zoom_reset` → `actions/camera_actions.py::zoom_reset` | Restores `_cam_distance = 5.0` (ViewportPanel default) or `_zoom_level = 1.0`; `ctx["distance"]` overrides for "recenter-on-selection" flows. |
| 261 | `theme.export_current` action | Router action id (Z7) | WIRED | `tool_router.py` → `_fb_export_current_theme` → `actions/theme_io_actions.py::export_current_theme` | Writes active `ThemeSpec` to `ctx["path"]` (or via `shell.prompt_save_path` hook) via `UserThemeStore._atomic_write_text`. YAML round-trippable through `ThemeSpec.from_yaml`. |
| 262 | `edit.cut_selection` action | Router action id (AA1) | WIRED | `tool_router.py` → `_fb_cut_selection` → `actions/destructive_edit_actions.py::cut_selection` | Snapshots into `EntityClipboard.cut()` + removes originals via `scene.remove_entity`; clears shell selection. Headless-safe when scene missing (removed=0). |
| 263 | `edit.delete_selection` action | Router action id (AA1) | WIRED | `tool_router.py` → `_fb_delete_selection` → `actions/destructive_edit_actions.py::delete_selection` | Multi-select-aware scene removal without touching the clipboard. Distinguished from `editor.delete` which routes through the legacy single-select shell hook. |
| 264 | `view.center_on_selection` action | Router action id (AA1) | WIRED | `tool_router.py` → `_fb_center_on_selection` → `actions/viewport_framing_actions.py::center_on_selection` | Pans `camera._cam_target` to the centroid of the selection's `(x, y, z)` positions; `_cam_distance` untouched. 2D fallback writes `_pan_x`/`_pan_y`. |
| 265 | `view.frame_all` action | Router action id (AA1) | WIRED | `tool_router.py` → `_fb_frame_all` → `actions/viewport_framing_actions.py::frame_all` | Computes AABB + centroid + bounding-sphere radius across every scene entity; writes `_cam_target` and `_cam_distance = radius * 2 * 1.15` with clamps. |
| 266 | `tool.pan` action | Router action id (AA1) | WIRED | `tool_router.py` → `_fb_activate_pan_tool` → `actions/tool_mode_actions.py::activate_pan_tool` | Sets `shell._active_tool = "pan"` and mirrors to notebook status bar + engine hook. Deliberately bypasses `NotebookToolbar.set_active` (pan isn't a sticker-button tool). |
| 267 | `theme.import_from_file` action | Router action id (BB1) | WIRED | `tool_router.py` → `_fb_theme_import_from_file` → `actions/theme_import_actions.py::import_from_file` | Loads a ``*.theme.yaml`` via ``ThemeSpec.from_yaml`` + ``register_theme`` + optional ``apply_theme``. Rejects ``.theme.css`` as `unsupported` until the declarative-CSS loader lands. |
| 268 | `file.save_layout_as` action | Router action id (BB1) | WIRED | `tool_router.py` → `_fb_save_layout_as` → `actions/layout_io_actions.py::save_layout_as` | Snapshots the shell via ``LayoutPersistence.snapshot_from_shell`` (or accepts a ``ctx["layout"]`` override) and atomically writes YAML to a caller-picked path. Sibling to the implicit ``.slappy/layout.yaml`` write. |
| 269 | `file.load_layout_from_file` action | Router action id (BB1) | WIRED | `tool_router.py` → `_fb_load_layout_from_file` → `actions/layout_io_actions.py::load_layout_from_file` | Reads YAML, validates schema, dispatches through ``LayoutPersistence.apply_to_shell``. Returns ``malformed`` on schema mismatch instead of silently loading defaults. |
| 270 | `edit.undo` action | Router action id (BB1) | WIRED | `tool_router.py` → `_fb_edit_undo` → `actions/history_actions.py::undo` | Resolves ``ctx["stack"]`` / ``shell._undo_stack`` / ``shell._engine._undo_manager`` in that order, then calls ``UndoStack.undo``. Returns ``empty`` when the stack is idle so callers can grey out the button. |
| 271 | `edit.redo` action | Router action id (BB1) | WIRED | `tool_router.py` → `_fb_edit_redo` → `actions/history_actions.py::redo` | Mirror of `edit.undo` — calls ``UndoStack.redo`` and returns the popped entry's action id + label + updated depths. |
| 272 | `edit.select_by_name` action | Router action id (CC1) | WIRED | `tool_router.py` → `_fb_select_by_name` → `actions/edit_by_name_actions.py::select_by_name` | Walks `scene.find_by_name(ctx["name"])`, writes matches to `shell._selected_entity` / `_selected_entities`. Returns `not_found` when nothing matches, `missing_name` on empty input, `no_scene` when unreachable. |
| 273 | `spawn.repeat_last` action | Router action id (CC1) | WIRED | `tool_router.py` → `_fb_repeat_last_spawn` → `actions/spawn_history_actions.py::repeat_last` | Reads `shell._last_spawn` tuple `(card_id, spec)` (or `shell._spawn_menu._last_spawn`), re-fires `shell._on_spawn` with the same card+spec. Supports `ctx["offset"]` for micro-translation so successive presses don't stack copies. |
| 274 | `view.toggle_grid` action | Router action id (CC1) | WIRED | `tool_router.py` → `_fb_toggle_grid` → `actions/view_toggle_actions.py::toggle_grid` | Flips `shell._grid_visible`; fires optional `shell._on_view_toggle(attr, value)` hook so the DPG draw callback observes the change next tick. Accepts `ctx["visible"]` seed for headless tests. |
| 275 | `view.toggle_gizmos` action | Router action id (CC1) | WIRED | `tool_router.py` → `_fb_toggle_gizmos` → `actions/view_toggle_actions.py::toggle_gizmos` | Symmetric to `view.toggle_grid` — flips `shell._gizmos_visible` (plural: covers transform gizmo, marquee, IK bone lines). Same seed / hook semantics. |
| 276 | `content.copy_asset_path` action | Router action id (CC1) | WIRED | `tool_router.py` → `_fb_copy_asset_path` → `actions/content_shell_actions.py::copy_asset_path` | Prefers `NotebookContentBrowser.copy_path` (already walks DPG / pyperclip / tkinter fallback). Direct pyperclip → tkinter → noop chain when no browser is reachable. Reports `backend` so tests can assert on graceful degradation. |
| 277 | `edit.duplicate_layer` action | Router action id (DD1) | WIRED | `tool_router.py` → `_fb_duplicate_layer` → `actions/layer_duplicate_actions.py::duplicate_layer` | Deep-copies the active `ZLayer`, bumps the name (`bg` → `bg copy`, then `bg copy 2` on collision), and repoints `shell._active_layer` at the clone. Falls back to `scene.z_layers[-1]` when no active layer is set. |
| 278 | `theme.cycle_reverse` action | Router action id (DD1) | WIRED | `tool_router.py` → `_fb_cycle_theme_reverse` → `actions/theme_cycle_reverse_actions.py::cycle_theme_reverse` | Symmetric to `theme.cycle`. Shares `_THEME_CURSOR` so a forward tick followed by a reverse tick returns to the starting theme. Shell hooks preferred (`cycle_theme_reverse`, or `cycle_theme(direction="reverse")`), else walks the registered-themes list backwards. |
| 279 | `panel.close_all` action | Router action id (DD1) | WIRED | `tool_router.py` → `_fb_close_all_panels` → `actions/panel_visibility_actions.py::close_all_panels` | Sweeps the canonical panel roster (`outliner`, `inspector`, `content_browser`, `code`, `layer_panel`, `behavior_panel`, `tag_painter`) and calls `shell.set_panel_visible(id, False)` (or the `toggle_panel` fallback) on every currently-visible entry. Pushes the closed batch onto `shell._hidden_panel_stack` so `panel.restore_last_hidden` can undo. Viewport panel is skipped (always-visible in the shell). |
| 280 | `panel.restore_last_hidden` action | Router action id (DD1) | WIRED | `tool_router.py` → `_fb_restore_last_hidden_panel` → `actions/panel_visibility_actions.py::restore_last_hidden_panel` | Pops the top of `shell._hidden_panel_stack` and re-shows every panel id in it. Returns `empty_stack` when nothing has been hidden yet (legal on fresh editors). |
| 281 | `spawn.repeat_last_batch` action | Router action id (DD1) | WIRED | `tool_router.py` → `_fb_repeat_last_batch` → `actions/spawn_batch_actions.py::repeat_last_batch` | Sibling to `spawn.repeat_last`. Reads the same `shell._last_spawn` slot, then lays down `count` copies (default 4) in a `ceil(sqrt(count))`-wide grid with per-cell offset `ctx["spacing"]` (default `(1.0, 1.0)`). Updates the last-spawn slot to the final cell so a follow-up `spawn.repeat_last` continues the grid. |
| 282 | `edit.group_selection` action | Router action id (EE1) | WIRED | `tool_router.py` → `_fb_group_selection` → `actions/edit_group_actions.py::group_selection` | Wraps the current selection into a `_GroupEntity` (local stub — scene has no `GroupEntity` primitive yet) sitting at the selection centroid. Every child's position is rewritten as an offset from the centroid so the visual layout stays fixed. Removes originals from the scene, adds the wrapper, retargets shell selection at the group. |
| 283 | `edit.ungroup_selection` action | Router action id (EE1) | WIRED | `tool_router.py` → `_fb_ungroup_selection` → `actions/edit_group_actions.py::ungroup_selection` | Flattens a selected group — each child gets `group.position + child.position` written back so absolute coordinates are restored. Removes the group and re-adds each child to the scene at top level. Returns `not_a_group` when the selection contains no groups. |
| 284 | `theme.random` action | Router action id (EE1) | WIRED | `tool_router.py` → `_fb_random_theme` → `actions/theme_random_actions.py::random_theme` | Picks a random registered theme via `random.choice`; deterministic under `ctx["rng"]`. Excludes the current theme by default (`exclude_current=True`) so a click never lands on the theme already in use. Distinguishes `single_theme` (only one registered) from `no_themes` (empty registry). |
| 285 | `spawn.spawn_at_cursor` action | Router action id (EE1) | WIRED | `tool_router.py` → `_fb_spawn_at_cursor` → `actions/spawn_cursor_actions.py::spawn_at_cursor` | Two-mode action. `mode="arm"` (default) stashes the resolved cursor coord on `shell._pending_spawn_position` for the next spawn-menu click. `mode="repeat"` re-fires `shell._last_spawn` centred on the cursor. Cursor probe walks `ctx["cursor"]` → `shell.get_cursor_world_position()` → `shell._cursor_world_position` → `shell._last_cursor`. |
| 286 | `edit.snap_to_pixel_grid` action | Router action id (EE1) | WIRED | `tool_router.py` → `_fb_snap_to_pixel_grid` → `actions/edit_snap_pixel_actions.py::snap_to_pixel_grid` | Rounds selected entity positions to integer pixels (or an arbitrary `ctx["pixel_size"]` grid — 32 for tilemaps). Default axes are `xy` so 2D pixel-art work doesn't collapse fractional Z ordering; pass `ctx["axes"] = "xyz"` to include Z. `ctx["all"]=True` walks every scene entity instead of just the selection. |
| 287 | `content.new_folder` action | Router action id (FF1) | WIRED | `tool_router.py` → `_fb_new_folder` → `actions/content_folder_actions.py::new_folder` | Creates a sub-directory beneath the resolved parent (`ctx["parent"]` → `browser.current_path` → `browser.root_path` → `shell._content_root`). Default name `"New Folder"` on empty input; auto-uniquifies collisions (`Sprites` → `Sprites (2)` → `Sprites (3)`). Best-effort `browser.refresh()` after creation. |
| 288 | `content.rename_asset` action | Router action id (FF1) | WIRED | `tool_router.py` → `_fb_rename_asset` → `actions/content_rename_actions.py::rename_asset` | Renames `ctx["path"]` to sibling `ctx["new_name"]`. Preserves source extension when the new name has none (so `bar.png` → `foo` yields `foo.png`); directories pass through untouched. Rejects path-separators in `new_name` with `invalid_name` so rename never accidentally moves. `ctx["overwrite"]=True` opts into replacing the target. |
| 289 | `panel.close_others` action | Router action id (FF1) | WIRED | `tool_router.py` → `_fb_close_other_panels` → `actions/panel_close_others_actions.py::close_other_panels` | Companion to DD1 `panel.close_all`. Hides every panel except `ctx["keep"]` (falls back to `shell._active_panel_id` / `shell._last_focused_panel_id`). Reuses the DD1 `_hidden_panel_stack` so `panel.restore_last_hidden` cleanly undoes the batch. Returns `no_target` when no focus is resolvable. |
| 290 | `edit.select_children` action | Router action id (FF1) | WIRED | `tool_router.py` → `_fb_select_children` → `actions/edit_select_children_actions.py::select_children` | Depth-first walk of `entity.children` / `entity._children` / dict `children` from every currently-selected entity. `mode="add"` (default) appends descendants to the selection; `mode="replace"` drops the roots. Cycle-guarded via visited-set on `id()`. Returns `no_children` when the selection is a leaf (differentiated from `no_selection`). |
| 291 | `theme.reload_all` action | Router action id (FF1) | WIRED | `tool_router.py` → `_fb_reload_all_themes` → `actions/theme_reload_actions.py::reload_all_themes` | Snapshots active theme name → resets `_THEME_CURSOR` → clears `_REGISTRY` → re-runs `bake_default_themes` → re-registers user themes from `UserThemeStore` (or `ctx["store"]`) → re-applies the previously-active theme. Fires `shell.on_themes_reloaded(themes)` broadcast so the switcher panel rebuilds. `ctx["skip_bake"]=True` opt-out for headless tests. |
| 292 | `content.delete_asset` action | Router action id (GG1) | WIRED | `tool_router.py` → `_fb_delete_asset` → `actions/content_delete_actions.py::delete_asset` | Modal-confirm + on-disk delete. Default call returns `{"status": "confirm_required", "path", "kind", "prompt", "size"}` so the shell can render its confirm modal; caller re-invokes with `ctx["confirmed"]=True` to actually trash the file / recursively delete the directory (`shutil.rmtree`). Best-effort `browser.refresh()` after delete + clears `shell._selected_asset_path` when it referenced the deleted path. Row 243 STUB flipped -> WIRED. |
| 293 | `panel.tile_grid` action | Router action id (GG1) | WIRED | `tool_router.py` → `_fb_tile_grid` → `actions/panel_layout_actions.py::tile_grid` | Auto-tiles every currently-visible panel (via DD1 `_pv._is_visible`) into a near-square `ceil(sqrt(n))`-wide grid that fills `ctx["viewport_size"]` (falls back to `shell.get_viewport_size()` / `shell._viewport_size` / `(1280, 720)`). Writes through `shell.set_panel_rect` when present, else per-wrapper `x/y/width/height` attribute assignment; mirrors to `shell._panel_layout_state` so BB1 `file.save_layout_as` picks it up. |
| 294 | `panel.cascade` action | Router action id (GG1) | WIRED | `tool_router.py` → `_fb_cascade_panels` → `actions/panel_layout_actions.py::cascade` | Cascades every visible panel into an offset staircase (`(dx, dy)` default `(32, 32)`; `(w, h)` default `(640, 480)`). Clamps against `viewport_size` so no panel walks fully off the viewport edge. Same rect-writer as `panel.tile_grid`. |
| 295 | `edit.invert_selection` action | Router action id (GG1) | WIRED | `tool_router.py` → `_fb_invert_selection` → `actions/edit_invert_selection_actions.py::invert_selection` | Selects every scene entity that is *not* currently selected. Walks `scene.entities` / `scene.get_entities()` / `scene.z_layers`; skips locked (`entity.locked`) and hidden (`entity.visible=False`) entries by default (`ctx["include_locked"]` / `ctx["include_hidden"]` opt-in). Distinguishes `no_scene` / `empty_scene` / `all_selected` so callers can render distinct hints. |
| 296 | `view.fullscreen` action | Router action id (GG1) | WIRED | `tool_router.py` → `_fb_view_fullscreen` → `actions/view_fullscreen_actions.py::fullscreen` | Focus-mode fullscreen — hides every chrome element (`_menu_bar_visible`, `_toolbar_visible`, `_status_bar_visible`, `_left_sidebar_visible`, `_right_sidebar_visible`) + every non-viewport panel. Snapshots the pre-FS state on `shell._fullscreen_snapshot` so `mode="exit"` restores it exactly. `mode="toggle"` (default) / `mode="enter"` / `mode="exit"` — enter-while-in-FS returns `already_fullscreen`; exit-while-not-in-FS returns `not_fullscreen`. Complementary to the OS-level `editor.toggle_fullscreen` (`F11`) which handles the OS window chrome. |
| 297 | `edit.select_next` action | Router action id (II5) | WIRED | `tool_router.py` → `_fb_select_next` → `actions/edit_select_next_actions.py::select_next` | Tab-through the scene entity roster (Blender `[` / Maya `.` / AE `F2` semantics). Reuses the GG1 `_walk_scene_entities` walker so ordering matches `select_all` / `invert_selection`. Wraps by default (`ctx["wrap"] = False` clamps → `at_end` / `at_start`). Skips locked / hidden entries unless `include_locked` / `include_hidden` opt in. Empty-selection cursor lands on entity 0 for forward and N-1 for reverse. |
| 298 | `edit.select_previous` action | Router action id (II5) | WIRED | `tool_router.py` → `_fb_select_previous` → `actions/edit_select_next_actions.py::select_previous` | Shift+Tab; retreats the cursor by one entity. Same ctx contract + roster walker as `edit.select_next`; only the direction flips. |
| 299 | `edit.paste_at_original_position` action | Router action id (II5) | WIRED | `tool_router.py` → `_fb_paste_at_original_position` → `actions/edit_paste_original_actions.py::paste_at_original_position` | Illustrator `Cmd+Shift+V` / Photoshop `Shift+Ctrl+V` / Blender `Alt+V` semantics — pulls the clipboard snapshots but *does not* apply a cursor-relative offset. Default `name_suffix` is `" (copy)"` (pass `""` to preserve names); positions are always preserved. Best-effort `scene.add_entity` / `scene.add` walk. Distinct `pasted_at_original` status so the shell can toast "pasted at original position" instead of the generic "pasted". |
| 300 | `spawn.spawn_batch_row` action | Router action id (II5) | WIRED | `tool_router.py` → `_fb_spawn_batch_row` → `actions/spawn_batch_row_actions.py::spawn_batch_row` | Sibling to DD1 `spawn.repeat_last_batch` — lays down `count` (default 5) copies in a single row instead of a grid. `direction="horizontal"` (default, +X) / `direction="vertical"` (+Y); `spacing` scalar picks the stride. `ctx["stride"]` 2/3-vec overrides direction+spacing for arbitrary diagonals. Retargets `shell._last_spawn` to the final cell so a follow-up `spawn.repeat_last` continues the row. |
| 301 | `content.duplicate_asset` action | Router action id (II5) | WIRED | `tool_router.py` → `_fb_duplicate_asset` → `actions/content_duplicate_asset_actions.py::duplicate_asset` | Explorer / Finder style in-place duplicate. Files splice `_copy` before the extension (`hero.png` → `hero_copy.png`); directories append the suffix (`Sprites` → `Sprites_copy`) and copy recursively via `shutil.copytree`. Auto-uniquify on collision (`hero_copy.png` → `hero_copy_2.png` → `hero_copy_3.png`). `ctx["suffix"]` overrides the default. Best-effort `browser.refresh()` after the copy so the new entry shows up without an explicit reload. Returns `not_found` / `missing_path` / `error` alongside the success shape. |
| 302 | `edit.hide_selection` action | Router action id (JJ6) | WIRED | `tool_router.py` → `_fb_hide_selection` → `actions/edit_hide_show_actions.py::hide_selection` | Blender `H` — marks every currently-selected entity as invisible. Writes both Nova3D (`entity.visible = False`) and Ochema legacy (`entity.hidden = True`) flags when either attribute is present. Returns `no_selection` (nothing to hide) vs `already_hidden` (selection was fully hidden) so the toast can differentiate. |
| 303 | `edit.show_all` action | Router action id (JJ6) | WIRED | `tool_router.py` → `_fb_show_all` → `actions/edit_hide_show_actions.py::show_all` | Blender `Alt+H` — un-hides every entity in the scene. Walks `scene.entities` / `scene.get_entities()` / `scene.z_layers` (shared roster with GG1 `invert_selection`), reads `_is_hidden`, clears the flag on every hit. Returns `no_scene` / `empty_scene` / `all_visible` distinct from success `shown` (with `previous_hidden_count`) so the caller can render "nothing to show" toasts. |
| 304 | `edit.lock_selection` action | Router action id (JJ6) | WIRED | `tool_router.py` → `_fb_lock_selection` → `actions/edit_lock_unlock_actions.py::lock_selection` | Sibling to hide_selection — marks selected entities uneditable. Writes both public (`entity.locked = True`) and legacy underscored (`entity._locked = True`) attributes when present. Locked entries are skipped by GG1 `invert_selection`, II5 Tab-through, and the JJ6 `select_by_prefab_kind` helper (unless `include_locked=True`) so locking effectively removes an entity from every selection flow. Returns `no_selection` / `already_locked` distinct from success `locked`. |
| 305 | `edit.unlock_all` action | Router action id (JJ6) | WIRED | `tool_router.py` → `_fb_unlock_all` → `actions/edit_lock_unlock_actions.py::unlock_all` | Maya `Ctrl+Shift+L` — clears the lock flag scene-wide. Same roster walker + selection retarget as `show_all`. Returns `no_scene` / `empty_scene` / `all_unlocked` / `unlocked` (with `previous_locked_count`). |
| 306 | `edit.select_by_prefab_kind` action | Router action id (JJ6) | WIRED | `tool_router.py` → `_fb_select_by_prefab_kind` → `actions/edit_select_by_kind_actions.py::select_by_prefab_kind` | Blender `Shift+G` "Select Similar" — swaps the selection for every entity whose `kind` / `prefab_kind` / `type` / `category` attribute matches the reference. Kind resolved from `ctx["kind"]` first (explicit override), else from the current selection's head entity. `mode="replace"` (default) / `mode="add"`. Locked / hidden entries filtered by default (`include_locked` / `include_hidden` opt back in). Returns `no_scene` / `empty_scene` / `no_selection` (kind unresolvable) / `no_kind_on_reference` (reference has no kind-like attribute) / `no_matches` / success `selected` (with `kind`, `count`, `previous_count`, `match_count`). |
| 307 | `edit.mirror_selection_x` action | Router action id (KK7) | WIRED | `tool_router.py` → `_fb_mirror_selection_x` → `actions/edit_mirror_actions.py::mirror_selection_x` | Blender `Ctrl+M X` — reflects every selected entity's position across the X axis. Default pivot is the selection centroid (self-mirror = flip-in-place); `ctx["pivot"]` accepts a scalar or 2/3-tuple to override. When an entity carries an `entity.scale` iterable the corresponding axis component is negated so the mesh flips visually (opt-out via `ctx["flip_scale"]=False`). 2D positions (length-2) round-trip cleanly — the position tuple keeps its arity. Returns `no_selection` / `no_positions` distinct from success `mirrored` (with `axis`, `pivot`, `count`). |
| 308 | `edit.mirror_selection_y` action | Router action id (KK7) | WIRED | `tool_router.py` → `_fb_mirror_selection_y` → `actions/edit_mirror_actions.py::mirror_selection_y` | Blender `Ctrl+M Y` — mirror of row 307, swaps `position.y` and negates `scale.y`. Same pivot / scale / return contract. |
| 309 | `edit.mirror_selection_z` action | Router action id (KK7) | WIRED | `tool_router.py` → `_fb_mirror_selection_z` → `actions/edit_mirror_actions.py::mirror_selection_z` | Blender `Ctrl+M Z` — 3D-scene mirror. For 2D shells the `z_height` slot is written when the position stays length-2 so pixel-art tilemaps still round-trip. Same pivot / scale / return contract as rows 307-308. |
| 310 | `view.orbit_selection` action | Router action id (KK7) | WIRED | `tool_router.py` → `_fb_orbit_selection` → `actions/view_orbit_actions.py::orbit_selection` | Blender `Numpad 4/6/8/2` — spins the viewport camera around the selection centroid. Increments `_cam_yaw` / `_cam_pitch` by `ctx["yaw_deg"]` (default 15°) / `ctx["pitch_deg"]` (default 0°). Pitch clamped to `[-π/2 + ε, π/2 - ε]` so the up-vector never inverts. Retargets `_cam_target` to the selection centroid on every fire (mirrors AA1 `view.center_on_selection`). Returns `no_camera` / `no_selection` / `no_positions` / success `orbited` (with `yaw` / `pitch` in radians + degrees). |
| 311 | `view.top_down_view` action | Router action id (KK7) | WIRED | `tool_router.py` → `_fb_top_down_view` → `actions/view_snap_actions.py::top_down_view` | Blender `Numpad 7` — snaps the viewport camera to a top-down orthographic pose. Writes `_cam_yaw = 0`, `_cam_pitch = -π/2`, and (when the slot exists) `_cam_projection = "ortho"` (pass `ctx["projection"]="perspective"` to keep perspective). Optional `ctx["selection"]` / `ctx["entities"]` retargets `_cam_target` to the centroid; when omitted the previous look-at is kept so the snap only changes orientation. Returns `no_camera` / success `snapped` (with `view = "top_down"`, `yaw`, `pitch`, `projection`, `target`). |

**Total rows: 311.** Status tally:

* **WIRED**: 294 (215 baseline + 18 delta + 5 Y1 + 5 Z7 + 5 AA1 + 5 BB1 + 5 CC1 + 5 DD1 + 5 EE1 + 5 FF1 + 5 GG1 + 5 II5 + 5 JJ6 + 5 KK7; rows 189 + 243 also flipped STUB -> WIRED)
* **STUB**: 14 (rows 50, 78, 79, 94, 95, 191, 192, 193, 222, 224, 225, 226, 227, 228 — row 243 flipped to WIRED under GG1)
* **BROKEN**: 3 (rows 80, 223 code-paths — see previous note; dedupes to 2 real import/attribute defects)

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

---

## X3 STUB-triage patch (2026-07-04)

Five new action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED:

* `editor.save_project` → `slappyengine.actions.project_actions.save_project`
* `editor.new_project` → `slappyengine.actions.project_actions.new_project`
* `editor.open_recent` → `slappyengine.actions.project_actions.open_recent`
* `view.reset_layout` → `slappyengine.actions.view_actions.reset_layout`
* `edit.duplicate_selection` → `slappyengine.actions.edit_actions.duplicate_selection`

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_x3.py`
(25 tests, all passing).

---

## Y7 delta re-audit (2026-07-04)

Appended rows 234-251 covering V-, W-, X-batch additions committed
between V1's freeze (`db56df3`) and the Y-batch scrum window (through
`194a0c9`). See `docs/feature_map_delta_2026_07_04.md` for the full
delta breakdown, including STUB-to-WIRED flips, feature-drift risks,
and the roll-up percentages (WIRED 92.8% / STUB 6.0% / BROKEN 1.2%).

New row totals: **251 total, 233 WIRED, 15 STUB, 3 BROKEN**.

Highest-impact remaining STUBs after Y7:

1. Row 80 / 223 — Diary softbody import + Open-picker fallback.
2. Row 79 — Diary "Generate Python from nodes" (V6 codegen exists;
   Diary panel button still emits placeholder).
3. Rows 191 / 192 — Theming editor Import / Export.

---

## Y1 STUB-triage patch (2026-07-04, round 2 after X3)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 252-256):

* `tool.select_all` → `slappyengine.actions.selection_actions.select_all`
* `tool.deselect_all` → `slappyengine.actions.selection_actions.deselect_all`
* `editor.copy_selection` → `slappyengine.actions.selection_actions.copy_selection`
* `editor.paste_selection` → `slappyengine.actions.selection_actions.paste_selection`
* `theme.cycle` → `slappyengine.actions.theme_actions.cycle_theme`

New subpackages: `python/slappyengine/actions/selection_actions.py`
+ `python/slappyengine/actions/theme_actions.py`.

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_y1.py`
(29 tests, all passing). Combined X3+Y1 wiring now covers 10 previously-
absent router action ids across 5 category buckets (`file`, `edit`,
`tool`, `view`, `theme`). Roll-up: **256 total, 238 WIRED (93.0%),
15 STUB (5.9%), 3 BROKEN (1.1%)**.

---

## Z7 STUB-triage patch (2026-07-04, round 3 after X3 + Y1)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 257-261):

* `tool.snap_to_grid` → `slappyengine.actions.tool_settings_actions.toggle_snap_to_grid`
* `view.zoom_in` → `slappyengine.actions.camera_actions.zoom_in`
* `view.zoom_out` → `slappyengine.actions.camera_actions.zoom_out`
* `view.zoom_reset` → `slappyengine.actions.camera_actions.zoom_reset`
* `theme.export_current` → `slappyengine.actions.theme_io_actions.export_current_theme`

New subpackages: `python/slappyengine/actions/tool_settings_actions.py`
+ `python/slappyengine/actions/camera_actions.py` +
`python/slappyengine/actions/theme_io_actions.py`.

Behavioural notes for Z7:

* **`tool.snap_to_grid`** — toggles `SnapManager.config.enable_grid`
  in place; accepts `ctx["force"]=bool` for menu-item "Snap: ON" /
  "Snap: OFF" callers; falls back to a module-level flag when no
  shell is reachable so tests + notebook mode still round-trip a
  boolean.
* **`view.zoom_in` / `view.zoom_out`** — multiplicative stepping
  (default 1.2×) against `_cam_distance` (3D) or `_zoom_level` (2D),
  clamped to `[0.05, 10000]` / `[0.01, 100]` so a runaway wheel-spin
  can't send the camera to infinity. Reads camera from
  `ctx["camera"]`, `shell._viewport_panel`, or `shell._camera` in that
  order.
* **`view.zoom_reset`** — writes back the ViewportPanel ctor default
  (5.0) or 1.0 for 2D shells; accepts `ctx["distance"]` for
  bounding-box-aware "frame the selection" resets.
* **`theme.export_current`** — YAML-round-trippable through
  `ThemeSpec.from_yaml`; reuses `UserThemeStore._atomic_write_text`
  for crash-safe writes. Prefers `ctx["path"]`; falls back to
  `shell.prompt_save_path(default_name)` when the shell exposes it.

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_z7.py`
(36 tests, all passing). Combined X3+Y1+Z7 wiring now covers 15
previously-absent router action ids across 5 category buckets
(`file`, `edit`, `tool`, `view`, `theme`). Roll-up: **261 total,
243 WIRED (93.1%), 15 STUB (5.7%), 3 BROKEN (1.1%)**.

---

## AA1 STUB-triage patch (2026-07-05, round 4 after X3 + Y1 + Z7)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 262-266):

* `edit.cut_selection` → `slappyengine.actions.destructive_edit_actions.cut_selection`
* `edit.delete_selection` → `slappyengine.actions.destructive_edit_actions.delete_selection`
* `view.center_on_selection` → `slappyengine.actions.viewport_framing_actions.center_on_selection`
* `view.frame_all` → `slappyengine.actions.viewport_framing_actions.frame_all`
* `tool.pan` → `slappyengine.actions.tool_mode_actions.activate_pan_tool`

New subpackages: `python/slappyengine/actions/destructive_edit_actions.py`
+ `python/slappyengine/actions/viewport_framing_actions.py` +
`python/slappyengine/actions/tool_mode_actions.py`.

Behavioural notes for AA1:

* **`edit.cut_selection`** — the "copy-and-delete" combo: routes
  through `EntityClipboard.cut()` so `last_action == "cut"`, then walks
  the resolved selection through `scene.remove_entity`. Headless-safe:
  a missing scene keeps the clipboard snapshot but returns
  `removed=0`. The shell's `_selected_entity` / `_selected_entities`
  slots are cleared post-cut so the outliner refreshes empty.
* **`edit.delete_selection`** — pure scene removal. Distinguished from
  `editor.delete` (which uses the legacy single-select shell hook) by
  supporting multi-select via `ctx["selection"]` and returning
  `{"status": "no_scene"}` when no scene is reachable so tests can
  assert on the failure mode.
* **`view.center_on_selection`** — writes only `camera._cam_target`
  (a list[3]). The 2D fallback writes `_pan_x` / `_pan_y` when the
  camera exposes them. `_cam_distance` is untouched — this is a *pan*.
* **`view.frame_all`** — walks every entity in the scene (or
  `ctx["entities"]` for headless testing), computes AABB + centroid +
  bounding-sphere radius, writes `_cam_target = centroid` and
  `_cam_distance = max(radius * 2 * 1.15, 5.0)` with clamps to the
  same `[0.05, 10000]` range camera_actions uses.
* **`tool.pan`** — sets `shell._active_tool = "pan"`. Deliberately
  bypasses `NotebookToolbar.set_active` (which rejects unknown ids —
  pan isn't one of the four sticker-button tools). Notebook status bar
  + engine `set_active_tool` hooks fire best-effort.

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_aa1.py`
(34 tests, all passing). Combined X3+Y1+Z7+AA1 wiring now covers 20
previously-absent router action ids across 5 category buckets
(`file`, `edit`, `tool`, `view`, `theme`). Roll-up: **266 total,
248 WIRED (93.2%), 15 STUB (5.6%), 3 BROKEN (1.1%)**.

---

## BB1 STUB-triage patch (2026-07-05, round 5 after X3 + Y1 + Z7 + AA1)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 267-271):

* `theme.import_from_file` → `slappyengine.actions.theme_import_actions.import_from_file`
* `file.save_layout_as` → `slappyengine.actions.layout_io_actions.save_layout_as`
* `file.load_layout_from_file` → `slappyengine.actions.layout_io_actions.load_layout_from_file`
* `edit.undo` → `slappyengine.actions.history_actions.undo`
* `edit.redo` → `slappyengine.actions.history_actions.redo`

New subpackages: `python/slappyengine/actions/theme_import_actions.py`
+ `python/slappyengine/actions/layout_io_actions.py`
+ `python/slappyengine/actions/history_actions.py`.

Behavioural notes for BB1:

* **`theme.import_from_file`** — sibling to Z7's `theme.export_current`.
  Reads a ``*.theme.yaml`` (or plain ``.yaml`` / ``.yml``) through
  ``ThemeSpec.from_yaml``, calls ``register_theme(spec)``, and (unless
  ``ctx["activate"]=False``) swaps the process-wide active theme via
  ``apply_theme``. ``*.theme.css`` files return ``unsupported`` so a
  future CSS loader can land without breaking this contract. Falls
  back to ``ctx["shell"].prompt_open_path(".theme.yaml")`` when no
  path override is supplied — a mirror of the ``prompt_save_path``
  hook the export action uses.
* **`file.save_layout_as`** — snapshots the shell via
  ``LayoutPersistence.snapshot_from_shell`` (or accepts a
  ``ctx["layout"]`` override for headless tests) and writes YAML
  atomically (temp file + ``os.replace``). The suggested default
  filename is ``layout.layout.yaml`` so the Tk chooser hints the
  compound extension. This is the *explicit-path* counterpart to
  ``LayoutPersistence.save`` which owns the implicit per-project
  ``.slappy/layout.yaml`` path.
* **`file.load_layout_from_file`** — reads YAML, validates
  ``schema_version == SCHEMA_VERSION``, and dispatches through
  ``LayoutPersistence.apply_to_shell``. Returns ``malformed`` on
  schema mismatch instead of silently loading defaults so a
  "layout from an older / newer editor build" case surfaces cleanly
  in the toast. Supports ``ctx["apply"]=False`` for preview flows.
* **`edit.undo` / `edit.redo`** — distinct from the legacy
  ``editor.undo`` / ``editor.redo`` router entries which route
  through ``shell._undo`` / ``shell._engine._undo_manager.redo``.
  The BB1 pair resolves the process-wide undo stack via
  ``ctx["stack"]`` → ``shell._undo_stack`` →
  ``shell._engine._undo_manager`` (that last hop is the legacy
  path — kept so this action is a strict superset), then calls
  ``UndoStack.undo`` / ``UndoStack.redo`` directly. Returns
  ``{"status": "empty"}`` on an idle stack so hotkey handlers can
  grey out the button without extra probing.

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_bb1.py`
(37 tests, all passing). Combined X3+Y1+Z7+AA1+BB1 wiring now covers
25 previously-absent router action ids across 5 category buckets
(`file`, `edit`, `tool`, `view`, `theme`). Roll-up: **271 total,
253 WIRED (93.4%), 15 STUB (5.5%), 3 BROKEN (1.1%)**.

---

## CC1 STUB-triage patch (2026-07-05, round 6 after X3 + Y1 + Z7 + AA1 + BB1)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 272-276):

* `edit.select_by_name` → `slappyengine.actions.edit_by_name_actions.select_by_name`
* `spawn.repeat_last` → `slappyengine.actions.spawn_history_actions.repeat_last`
* `view.toggle_grid` → `slappyengine.actions.view_toggle_actions.toggle_grid`
* `view.toggle_gizmos` → `slappyengine.actions.view_toggle_actions.toggle_gizmos`
* `content.copy_asset_path` → `slappyengine.actions.content_shell_actions.copy_asset_path`

New subpackages: `python/slappyengine/actions/edit_by_name_actions.py`
+ `python/slappyengine/actions/spawn_history_actions.py`
+ `python/slappyengine/actions/view_toggle_actions.py`
+ `python/slappyengine/actions/content_shell_actions.py`.

Behavioural notes for CC1:

* **`edit.select_by_name`** — prefers `Scene.find_by_name(name)` when
  the scene exposes it, falls back to a manual walk over `_entities`.
  Writes the full match list to `shell._selected_entities` and the
  first match to `shell._selected_entity` (so the inspector still
  fires on single-select semantics). Returns `not_found` when no
  entity has the name, `missing_name` on empty input, `no_scene`
  when no scene is reachable.
* **`spawn.repeat_last`** — reads `shell._last_spawn = (card_id, spec)`
  (or the notebook spawn menu's own `_last_spawn` slot) and re-fires
  `shell._on_spawn` with the same arguments. The companion
  `record_last_spawn(shell, card_id, spec)` helper is exposed so
  future ticks can wire the "record on dispatch" side without owning
  a new module. Supports `ctx["offset"]` to nudge the position by a
  fixed delta so successive Shift-D presses don't overlap copies.
* **`view.toggle_grid` / `view.toggle_gizmos`** — cheap boolean flips
  on `shell._grid_visible` / `shell._gizmos_visible`. Both default to
  ON when the attribute is missing (matches the DPG editor's initial
  state). Both fire an optional `shell._on_view_toggle(attr, value)`
  hook so the draw callback observes the change next tick. Both
  accept a `ctx["visible"]` seed so headless tests can drive the
  flip without a shell.
* **`content.copy_asset_path`** — routes through
  `NotebookContentBrowser.copy_path` when the shell owns a browser
  (that method already walks DPG → pyperclip → tkinter). Falls back
  to `pyperclip.copy` → `tkinter.clipboard_append` → noop when no
  browser is reachable. Reports the `backend` used so tests can
  assert on the graceful-degradation path. Never spawns a subprocess
  (unlike `content.reveal_in_folder`).

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_cc1.py`
(39 tests, all passing). Combined X3+Y1+Z7+AA1+BB1+CC1 wiring now
covers 30 previously-absent router action ids across 6 category
buckets (`file`, `edit`, `tool`, `view`, `theme`, `spawn`,
`content`). Roll-up: **276 total, 258 WIRED (93.5%), 15 STUB (5.4%),
3 BROKEN (1.1%)**.

---

## DD1 STUB-triage patch (2026-07-05, round 7 after X3 + Y1 + Z7 + AA1 + BB1 + CC1)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 277-281):

* `edit.duplicate_layer` → `slappyengine.actions.layer_duplicate_actions.duplicate_layer`
* `theme.cycle_reverse` → `slappyengine.actions.theme_cycle_reverse_actions.cycle_theme_reverse`
* `panel.close_all` → `slappyengine.actions.panel_visibility_actions.close_all_panels`
* `panel.restore_last_hidden` → `slappyengine.actions.panel_visibility_actions.restore_last_hidden_panel`
* `spawn.repeat_last_batch` → `slappyengine.actions.spawn_batch_actions.repeat_last_batch`

New subpackages: `python/slappyengine/actions/layer_duplicate_actions.py`
+ `python/slappyengine/actions/theme_cycle_reverse_actions.py`
+ `python/slappyengine/actions/panel_visibility_actions.py`
+ `python/slappyengine/actions/spawn_batch_actions.py`.

Behavioural notes for DD1:

* **`edit.duplicate_layer`** — deep-copies the source layer (falls back
  to a shallow `copy.copy` when deep-copy fails on custom slots), bumps
  the name so `"bg"` → `"bg copy"` → `"bg copy 2"` on collision, and
  registers the clone via `scene.add_z_layer(clone)` (falls through to
  a direct `scene._z_layers.append` when the setter is missing). The
  shell's `_active_layer` slot is then retargeted at the clone so the
  next inspector refresh binds to the fresh copy. Returns `no_scene` /
  `no_layer` cleanly when either side is missing.
* **`theme.cycle_reverse`** — mirrors `theme.cycle` semantics but rewinds
  the shared `_THEME_CURSOR`. Preferred shell hooks: `cycle_theme_reverse`
  (dedicated method) or `cycle_theme(direction="reverse")` (kwarg). Falls
  back to a walk over `list_registered_themes()` using
  `(idx - 1) % len(themes)`. When the cursor has never been seeded a
  single reverse click lands on the *tail* of the list so the wrap
  semantics stay consistent.
* **`panel.close_all`** — pushes an N-item batch onto
  `shell._hidden_panel_stack`. Deliberately skips `viewport_panel` (the
  DPG canvas is `no_close=True` in the shell). Reads `panel_windows[id].is_visible()`
  before `panel_layout_state[id].visible` before defaulting to `True`
  so a first-run editor with no persisted state still hides everything.
  Uses `set_panel_visible` when the shell exposes it; falls back to
  `toggle_panel` when current != target so we don't spuriously flip a
  panel that was already at the target state.
* **`panel.restore_last_hidden`** — companion pop. Returns
  `{"status": "empty_stack"}` (not an error) when the stack is empty so
  the caller can toast "nothing to restore" without special-casing.
* **`spawn.repeat_last_batch`** — reuses the CC1
  `_resolve_last_spawn` / `record_last_spawn` helpers from
  `spawn_history_actions`. Grid layout: `count` default 4, `columns`
  default `ceil(sqrt(count))` (near-square), `spacing` default
  `(1.0, 1.0)` (2-vec auto-pads a `0.0` Z-stride; 3-vec applies xyz).
  Each cell gets a deep-copy of the template spec with its
  `position`/`origin`/`pos` field shifted. Records the *final* cell as
  the new `_last_spawn` so a subsequent `spawn.repeat_last` continues
  the grid rather than restarting at the template origin. Rejects
  non-positive counts with `no_history` (nothing to lay down).

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_dd1.py`
(40 tests, all passing). Combined X3+Y1+Z7+AA1+BB1+CC1+DD1 wiring now
covers 35 previously-absent router action ids across 7 category
buckets (`file`, `edit`, `tool`, `view`, `theme`, `panel`, `spawn`,
`content`). Roll-up: **281 total, 263 WIRED (93.6%), 15 STUB (5.3%),
3 BROKEN (1.1%)**.

---

## EE1 STUB-triage patch (2026-07-05, round 8 after X3 + Y1 + Z7 + AA1 + BB1 + CC1 + DD1)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 282-286):

* `edit.group_selection` → `slappyengine.actions.edit_group_actions.group_selection`
* `edit.ungroup_selection` → `slappyengine.actions.edit_group_actions.ungroup_selection`
* `theme.random` → `slappyengine.actions.theme_random_actions.random_theme`
* `spawn.spawn_at_cursor` → `slappyengine.actions.spawn_cursor_actions.spawn_at_cursor`
* `edit.snap_to_pixel_grid` → `slappyengine.actions.edit_snap_pixel_actions.snap_to_pixel_grid`

New subpackages: `python/slappyengine/actions/edit_group_actions.py`
+ `python/slappyengine/actions/theme_random_actions.py`
+ `python/slappyengine/actions/spawn_cursor_actions.py`
+ `python/slappyengine/actions/edit_snap_pixel_actions.py`.

Behavioural notes for EE1:

* **`edit.group_selection`** — wraps the selection into a local
  `_GroupEntity` stub (the scene module ships no `GroupEntity`
  primitive today, so this action owns its own duck-typed class with
  `position` / `children` / `name` / `is_group=True`). Centroid is the
  arithmetic mean of the child positions across whichever positional
  field they carry (`position` / `origin` / `pos`). Children are
  re-parented relative to the centroid so the visible layout stays
  fixed when the group carries the offset. Removes originals from the
  scene, adds the wrapper, retargets `shell._selected_entity` +
  `_selected_entities` at the group.
* **`edit.ungroup_selection`** — mirror of the above. Walks every
  group in the current selection (non-group entries are ignored) and
  for each child writes back `group.position + child.position` so
  absolute coordinates are restored. Removes the group from the scene
  and re-adds each child at top level. Returns `not_a_group` when the
  selection contains no groups (distinguishing from `no_selection`).
  Shell selection retargets at the released children.
* **`theme.random`** — shares `_THEME_CURSOR` with `theme.cycle` /
  `theme.cycle_reverse`. `ctx["rng"]` accepts a `random.Random`
  instance for deterministic tests. Excludes the currently active
  theme by default so a click never no-ops. Distinguishes
  `{"status": "single_theme", "theme": name}` (only one registered
  theme + exclude filter would leave the pool empty) from
  `{"status": "no_themes"}` (empty registry) so the caller can render
  a "no other themes available" toast without special-casing.
* **`spawn.spawn_at_cursor`** — two-mode. `mode="arm"` (default)
  stashes the resolved cursor coord on
  `shell._pending_spawn_position` for the next spawn-menu click to
  consume. `mode="repeat"` uses `_resolve_last_spawn` /
  `record_last_spawn` from `spawn_history_actions` to re-fire
  `shell._last_spawn` at the cursor immediately; falls back to `"arm"`
  when no history exists (so the click isn't wasted). Cursor probe
  walks `ctx["cursor"]` → `shell.get_cursor_world_position()` →
  `shell._cursor_world_position` → `shell._last_cursor` in that order.
* **`edit.snap_to_pixel_grid`** — rounds selected entity positions to
  the nearest multiple of `ctx["pixel_size"]` (default 1.0). Default
  axes are `"xy"` so 2D pixel-art work doesn't collapse fractional Z
  layer ordering; pass `ctx["axes"] = "xyz"` to include Z. Custom
  pixel sizes like 32 support tilemap workflows (32-unit snap).
  `ctx["all"]=True` walks every entity in the scene instead of just
  the selection (matches an "Edit → Snap All to Pixel Grid" menu
  variant). Returns per-entity `(entity, before, after)` tuples in
  `deltas` so the caller can wire an undo hook.

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_ee1.py`
(40 tests, all passing). Combined X3+Y1+Z7+AA1+BB1+CC1+DD1+EE1 wiring
now covers 40 previously-absent router action ids across 7 category
buckets (`file`, `edit`, `tool`, `view`, `theme`, `panel`, `spawn`,
`content`). Roll-up: **286 total, 268 WIRED (93.7%), 15 STUB (5.2%),
3 BROKEN (1.0%)**.

---

## FF1 STUB-triage patch (2026-07-05, round 9 after X3 + Y1 + Z7 + AA1 + BB1 + CC1 + DD1 + EE1)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 287-291):

* `content.new_folder` → `slappyengine.actions.content_folder_actions.new_folder`
* `content.rename_asset` → `slappyengine.actions.content_rename_actions.rename_asset`
* `panel.close_others` → `slappyengine.actions.panel_close_others_actions.close_other_panels`
* `edit.select_children` → `slappyengine.actions.edit_select_children_actions.select_children`
* `theme.reload_all` → `slappyengine.actions.theme_reload_actions.reload_all_themes`

New subpackages: `python/slappyengine/actions/content_folder_actions.py`
+ `python/slappyengine/actions/content_rename_actions.py`
+ `python/slappyengine/actions/panel_close_others_actions.py`
+ `python/slappyengine/actions/edit_select_children_actions.py`
+ `python/slappyengine/actions/theme_reload_actions.py`.

Behavioural notes for FF1:

* **`content.new_folder`** — resolves the parent directory in order
  (`ctx["parent"]` → `browser.current_path` → `browser.root_path` →
  `shell._content_root`) so the same helper backs both "New Folder"
  button clicks and right-click context menu commands. Default name
  is `"New Folder"` (matches Explorer / Finder). Collisions
  auto-uniquify — `Sprites` → `Sprites (2)` → `Sprites (3)`, bounded
  at 999 attempts so a mis-configured filesystem can never spin the
  helper forever. Best-effort `browser.refresh()` after creation so
  the new folder shows up without an explicit reload. Returns
  `parent_missing` (parent doesn't exist on disk) distinct from
  `no_parent` (no parent could be resolved) so the caller can route
  the two error modes to different toasts.
* **`content.rename_asset`** — preserves the source extension when
  the new name has none (typing `foo` for `bar.png` yields
  `foo.png`), matching Explorer / Finder. Directories skip the
  extension step so `Old Folder` → `New Folder` isn't mangled into
  `New Folder.Folder`. Rejects path-separators in `new_name` with
  `invalid_name` so "rename" never accidentally does a "move".
  `ctx["overwrite"]=True` opts into `os.replace` semantics.
  Retargets `shell._selected_asset_path` at the new path on success.
* **`panel.close_others`** — companion to DD1 `panel.close_all`.
  Solo the currently-focused panel by hiding every other visible
  panel. Reuses `panel_visibility_actions._panel_ids` /
  `_is_visible` / `_set_panel_visibility` / `_push_stack` so the
  DD1 `panel.restore_last_hidden` cleanly undoes the batch. Keep-
  target resolution walks `ctx["keep"]` →
  `shell._active_panel_id` → `shell._last_focused_panel_id`, or
  returns `no_target` when unresolvable (caller surfaces "click a
  panel first" toast).
* **`edit.select_children`** — depth-first walk of `entity.children`
  / `entity._children` / dict `children` from every currently-
  selected entity. Cycles are guarded via a visited-set on `id()`.
  Two modes: `mode="add"` (default, Blender's Shift+G→Children
  semantics) appends descendants to the existing selection;
  `mode="replace"` drops the roots and selects just the leaves.
  Returns `no_children` when the selection is a leaf (differentiated
  from `no_selection` so the caller can say "leaf node" instead of
  "nothing selected"). Works on the EE1 `_GroupEntity` (children
  live on `.children`) plus dict-shaped and legacy Nova3D entities.
* **`theme.reload_all`** — flushes and re-scans the process-wide
  theme registry after the user edits a theme's underlying JSON /
  TOML on disk. Six-step sequence: (1) snapshot active theme name
  (via `get_active_theme()` — LookupError-safe when no theme is
  active), (2) reset the shared `_THEME_CURSOR` so post-reload
  `theme.cycle` starts fresh, (3) clear `_REGISTRY` via
  `_reset_registry_for_tests()`, (4) re-run `bake_default_themes()`
  (skip via `ctx["skip_bake"]` for headless tests), (5) re-register
  user themes from `UserThemeStore`, (6) re-apply the previously-
  active theme. Fires `shell.on_themes_reloaded(themes)` broadcast
  when the shell exposes the hook so the theme-switcher panel
  rebuilds.

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_ff1.py`
(30 tests, all passing). Combined
X3+Y1+Z7+AA1+BB1+CC1+DD1+EE1+FF1 wiring now covers 45 previously-
absent router action ids across 7 category buckets (`file`, `edit`,
`tool`, `view`, `theme`, `panel`, `spawn`, `content`). Roll-up:
**291 total, 273 WIRED (93.8%), 15 STUB (5.2%), 3 BROKEN (1.0%)**.


## II5 STUB-triage patch (2026-07-05, round 11 after X3 + Y1 + Z7 + AA1 + BB1 + CC1 + DD1 + EE1 + FF1 + GG1)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 297-301):

* `edit.select_next` → `slappyengine.actions.edit_select_next_actions.select_next`
* `edit.select_previous` → `slappyengine.actions.edit_select_next_actions.select_previous`
* `edit.paste_at_original_position` → `slappyengine.actions.edit_paste_original_actions.paste_at_original_position`
* `spawn.spawn_batch_row` → `slappyengine.actions.spawn_batch_row_actions.spawn_batch_row`
* `content.duplicate_asset` → `slappyengine.actions.content_duplicate_asset_actions.duplicate_asset`

New subpackages:
`python/slappyengine/actions/edit_select_next_actions.py`
+ `python/slappyengine/actions/edit_paste_original_actions.py`
+ `python/slappyengine/actions/spawn_batch_row_actions.py`
+ `python/slappyengine/actions/content_duplicate_asset_actions.py`.

Behavioural notes for II5:

* **`edit.select_next` / `edit.select_previous`** — Tab-through the
  scene entity roster (Blender `[` / `]`, Maya `,` / `.`, AE `F2` /
  `Shift+F2`). Reuses the GG1 `_walk_scene_entities` iterator so
  ordering matches `select_all` / `invert_selection`. Cursor wraps by
  default (`ctx["wrap"] = False` clamps → returns `at_end` /
  `at_start` when the cursor sits at the roster boundary). Locked
  (`entity.locked`) and hidden (`entity.visible = False`) entries are
  skipped so Tab never lands on an unclickable entry — the caller opts
  back in via `ctx["include_locked"] = True` /
  `ctx["include_hidden"] = True`. Empty selection lands on entity 0
  for forward and entity N-1 for reverse, matching Blender.
* **`edit.paste_at_original_position`** — Illustrator `Cmd+Shift+V` /
  Photoshop `Shift+Ctrl+V` semantics. Pulls the process-wide
  `EntityClipboard` snapshots and returns them *without* any offset
  applied, so a copy → paste-in-place cycle yields a clone sitting at
  the exact source coordinate. Default `name_suffix` is `" (copy)"` so
  the outliner can still tell the copies from the sources; pass
  `ctx["name_suffix"] = ""` to preserve names verbatim. Best-effort
  `scene.add_entity` / `scene.add` walk on the resolved scene handle.
  Distinct `pasted_at_original` status string lets the shell render
  "pasted at original position" toasts.
* **`spawn.spawn_batch_row`** — Sibling to DD1
  `spawn.repeat_last_batch`. Where the DD1 helper lays down copies in
  a near-square grid, this variant lays down N copies in a single
  straight row (default `count = 5`). `direction = "horizontal"`
  (default, +X) or `"vertical"` (+Y); `spacing` scalar picks the
  stride. `ctx["stride"]` 2/3-tuple overrides both for arbitrary
  diagonals. Same shell probe (`_on_spawn` + `_last_spawn`), same
  final-cell retarget so a follow-up `spawn.repeat_last` continues
  the row. Returns `no_history` for `count <= 0` / missing history,
  `no_shell` when neither `shell` nor `last_spawn` is in ctx.
* **`content.duplicate_asset`** — Explorer / Finder in-place duplicate
  with a `_copy` suffix. Files splice the suffix before the extension
  (`hero.png` → `hero_copy.png`); directories append it
  (`Sprites` → `Sprites_copy`) and copy recursively via
  `shutil.copytree`. Repeated duplicates auto-uniquify with a numeric
  suffix (`hero_copy.png` → `hero_copy_2.png` → `hero_copy_3.png`,
  bounded at 999 attempts). `ctx["suffix"]` swaps the default for
  `_backup` / `_v2` / whatever. Best-effort `browser.refresh()` after
  the copy so the new entry shows up without an explicit reload.
  Returns `duplicated` / `missing_path` / `not_found` / `error`.

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_ii5.py`
(34 tests, all passing). Combined
X3+Y1+Z7+AA1+BB1+CC1+DD1+EE1+FF1+GG1+II5 wiring now covers 55
previously-absent router action ids across 8 category buckets
(`file`, `edit`, `tool`, `view`, `theme`, `panel`, `spawn`,
`content`). Roll-up: **301 total, 284 WIRED (94.4%), 14 STUB (4.7%),
3 BROKEN (1.0%)**.


## JJ6 STUB-triage patch (2026-07-05, round 12 after X3 + Y1 + Z7 + AA1 + BB1 + CC1 + DD1 + EE1 + FF1 + GG1 + II5)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 302-306).
Per II5's finding, the remaining 14 named STUBs are DPG-shell-dependent
(HUD toggle, diary "Open…" file picker, inspector help popups, theming
save-as-new / import / export modals). This round wires common QoL
actions that don't need the DPG shell — hide/show/lock/unlock plus
Blender-style "select similar":

* `edit.hide_selection` → `slappyengine.actions.edit_hide_show_actions.hide_selection`
* `edit.show_all` → `slappyengine.actions.edit_hide_show_actions.show_all`
* `edit.lock_selection` → `slappyengine.actions.edit_lock_unlock_actions.lock_selection`
* `edit.unlock_all` → `slappyengine.actions.edit_lock_unlock_actions.unlock_all`
* `edit.select_by_prefab_kind` → `slappyengine.actions.edit_select_by_kind_actions.select_by_prefab_kind`

New subpackages:
`python/slappyengine/actions/edit_hide_show_actions.py`
+ `python/slappyengine/actions/edit_lock_unlock_actions.py`
+ `python/slappyengine/actions/edit_select_by_kind_actions.py`.

Behavioural notes for JJ6:

* **`edit.hide_selection`** — Blender `H` / Maya `Ctrl+H`. Marks every
  entry in the current selection as invisible. Both Nova3D
  (`entity.visible = False`) and Ochema legacy (`entity.hidden = True`)
  conventions are honoured — if the entity carries `visible` we clear
  it; if it carries `hidden` we set it. When neither attribute is
  present the helper installs `hidden = True` so a subsequent
  `show_all` can round-trip it. Distinguishes `no_selection` (nothing
  to hide) from `already_hidden` (selection was fully hidden already)
  so the caller can toast "already hidden" instead of "nothing
  selected".
* **`edit.show_all`** — Blender `Alt+H`. Walks the shared GG1
  `_walk_scene_entities` roster (matches `select_all` / `invert_selection`
  ordering), filters through `_is_hidden`, clears the flag on every hit.
  Success payload includes `previous_hidden_count` so a follow-up undo
  hook knows how many entities to re-hide.
* **`edit.lock_selection`** — Padlock icon in Blender's outliner /
  Maya's layer editor "R" toggle. Marks selected entities uneditable.
  Writes both public `locked` and legacy `_locked` attributes so
  downstream readers agree. Locked entries are already respected by
  GG1 `invert_selection`, II5 `select_next` / `select_previous`, and
  the JJ6 `select_by_prefab_kind` helper (unless the caller opts in
  via `include_locked=True`), so locking effectively marks-as-uneditable
  across the entire editor selection surface.
* **`edit.unlock_all`** — Maya `Ctrl+Shift+L`. Scene-wide clear of the
  lock flag. Same roster walker + selection retarget as `show_all`.
  Distinguishes `no_scene` / `empty_scene` / `all_unlocked` from success
  `unlocked` (with `previous_locked_count`).
* **`edit.select_by_prefab_kind`** — Blender `Shift+G → Similar`, Maya
  "Select Similar", AE right-click "Select same type". Swaps the
  selection for every entity whose kind matches a reference. Kind is
  resolved from `ctx["kind"]` first (explicit override — always wins),
  else from the first entity in the current selection. Walks four
  attribute names in order: `kind`, `prefab_kind`, `type`, `category`
  — so both Nova3D (`kind`) and Ochema-legacy (`prefab_kind`) entities
  match cleanly. Enum / class values are coerced via `str(value)` so a
  `PrefabKind.ROPE` enum matches `"PrefabKind.ROPE"`. `mode="replace"`
  (default) swaps the selection; `mode="add"` extends it with de-dup
  on `id()`. Locked / hidden entries filtered by default; the
  `include_locked` / `include_hidden` flags opt back in for
  batch-fixing locked layers. Distinct `no_kind_on_reference` status
  when the reference entity has none of the four attribute names — so
  the caller can render "click a kinded entity first" instead of the
  generic "nothing selected".

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_jj6.py`
(40 tests, all passing). Combined
X3+Y1+Z7+AA1+BB1+CC1+DD1+EE1+FF1+GG1+II5+JJ6 wiring now covers 60
previously-absent router action ids across 8 category buckets
(`file`, `edit`, `tool`, `view`, `theme`, `panel`, `spawn`,
`content`). Roll-up: **306 total, 289 WIRED (94.4%), 14 STUB (4.6%),
3 BROKEN (1.0%)**.


## KK7 STUB-triage patch (2026-07-05, round 13 after X3 + Y1 + Z7 + AA1 + BB1 + CC1 + DD1 + EE1 + FF1 + GG1 + II5 + JJ6)

Five more action ids landed in this tick, moving 5 rows from STUB
(implicit — the ids were not yet registered) to WIRED (rows 307-311).
The remaining 14 named STUBs are still DPG-shell-dependent
(HUD toggle, diary "Open…" file picker, inspector help popups, theming
save-as-new / import / export modals). This round wires the last set of
common DCC QoL actions that don't need the DPG shell — the mirror-X/Y/Z
trio plus two camera-orientation snaps:

* `edit.mirror_selection_x` → `slappyengine.actions.edit_mirror_actions.mirror_selection_x`
* `edit.mirror_selection_y` → `slappyengine.actions.edit_mirror_actions.mirror_selection_y`
* `edit.mirror_selection_z` → `slappyengine.actions.edit_mirror_actions.mirror_selection_z`
* `view.orbit_selection` → `slappyengine.actions.view_orbit_actions.orbit_selection`
* `view.top_down_view` → `slappyengine.actions.view_snap_actions.top_down_view`

New subpackages:
`python/slappyengine/actions/edit_mirror_actions.py`
+ `python/slappyengine/actions/view_orbit_actions.py`
+ `python/slappyengine/actions/view_snap_actions.py`.

Behavioural notes for KK7:

* **`edit.mirror_selection_x` / `_y` / `_z`** — Blender `Ctrl+M X/Y/Z`,
  Maya "Mesh > Mirror", AE "Layer > Transform > Flip Horizontal /
  Vertical". Reflects each selected entity's position through the
  requested axis. Default pivot is the selection centroid so a self-
  mirror produces a stable flip-in-place (no drift on repeated calls —
  the two-mirror round-trip test exercises this); `ctx["pivot"]` accepts
  a scalar (axis-coordinate) or a 2/3-vec (only the relevant component
  is consumed). When the entity carries an iterable `scale` slot the
  corresponding axis component is negated so triangles / meshes flip
  visually (opt-out via `ctx["flip_scale"] = False`). Position tuples
  keep their arity — a 2D sprite stays 2D, and the mirrored Z folds
  into `z_height` when present. Return contract:
  `no_selection` (nothing to mirror) / `no_positions` (selection had
  no position-carrying entries) / success `mirrored` (with `axis`,
  `pivot`, `count`).
* **`view.orbit_selection`** — Blender Numpad-4/6/8/2 orbit gesture.
  Retargets the camera's `_cam_target` to the selection centroid, then
  increments `_cam_yaw` by `ctx["yaw_deg"]` (default 15°) and
  `_cam_pitch` by `ctx["pitch_deg"]` (default 0°). Pitch clamped to
  `[-π/2 + 1°, π/2 - 1°]` — matches Blender's pole-avoidance behaviour
  so the up-vector stays well-defined. Camera distance is not touched;
  a follow-up `view.frame_all` re-fits the zoom. Return contract:
  `no_camera` / `no_selection` / `no_positions` / success `orbited`
  (with `yaw`, `pitch` in both radians + degrees, plus `target`).
* **`view.top_down_view`** — Blender Numpad-7. Snaps camera orientation
  to canonical top-down orthographic: `_cam_yaw = 0`,
  `_cam_pitch = -π/2`, `_cam_projection = "ortho"` when the camera
  carries the slot. Pass `ctx["projection"] = "perspective"` to keep
  perspective (rare — matches Blender's `Numpad 5` toggle). Optional
  `ctx["selection"]` / `ctx["entities"]` retargets `_cam_target` to the
  centroid; when neither is provided the camera keeps its previous
  look-at target so the snap is purely an orientation change (matches
  Blender's "no selection" Numpad-7 behaviour). Return contract:
  `no_camera` / success `snapped` (with `view = "top_down"`, `yaw`,
  `pitch`, `projection`, `target`).

Regression tests: `SlapPyEngineTests/tests/test_stub_triage_kk7.py`
(36 tests, all passing). Combined
X3+Y1+Z7+AA1+BB1+CC1+DD1+EE1+FF1+GG1+II5+JJ6+KK7 wiring now covers 65
previously-absent router action ids across 8 category buckets
(`file`, `edit`, `tool`, `view`, `theme`, `panel`, `spawn`,
`content`). Roll-up: **311 total, 294 WIRED (94.5%), 14 STUB (4.5%),
3 BROKEN (1.0%)**.
