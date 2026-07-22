# Nova3D Parity Sprint Plan — 2026-07-05 (II7)

Docs-only sprint plan translating the HH3 Nova3D gap audit into a
concrete, agent-scoped roadmap. Written by II7 background scrum agent
during the II-batch push.

**Inputs consulted**:

* `docs/nova3d_gap_audit_2026_07_05.md` (HH3) — 610-line gap audit,
  11 MUST_HAVE / 8 NICE_TO_HAVE / 3+ SKIP tally.
* `docs/big_picture_2026_07_05.md` (GG7) — 291-row feature map, 273
  WIRED (93.8%) at FF close.
* `docs/rust_migration_audit_2026_07_05.md` (FF4) — 17 shipped Rust
  kernels + top-3 next ports (`_slide`, `_sor_sweep`,
  `connected_components`).
* `git log --oneline --since=2026-07-04` — 60+ commits including HH1
  (App / launch), HH2 (project scaffolder), HH4 (`pharos_engine.render`
  wgpu-forward + null fallback), HH5–HH8 salvage, GG7 rollup.
* Live-verified against the source tree at
  `H:\Github\SlapPyEngine\python\pharos_engine\`.

---

## 1. Summary — where we stand

Per HH3: **12 WIRED / 20 PARTIAL / 10 GAP / 1 N/A** across Nova3D's 44
subsystems. Since HH3 landed, HH4 shipped `pharos_engine.render`
(a wgpu-forward + `NullRenderer`-fallback façade — 1221 LoC across 9
files) and HH1 shipped the top-level `App` / `launch()` / `load_model()`
API. The `asset_import/` subpackage also landed with a real
`pygltflib`-backed glTF importer (299 LoC) and a hand-written OBJ
parser (224 LoC). This means several HH3 P0 gaps are already partially
closed — most importantly gap #1 (mesh loading) — but the follow-through
work (MTL resolve, skinning, materials on drawcalls, real wgpu pipeline
compile) is still ahead of us.

**What "parity" means for this plan**: a shipping Python 3D engine that
can (a) import a glTF character with rig + textures, (b) walk a scene
graph and emit drawcalls through a real (not stubbed) wgpu forward
pipeline, (c) shade with PBR + IBL + cascaded shadows, (d) play a
skeletal animation, (e) resolve MSAA, (f) render text + a HUD, (g)
capture video, and (h) export a standalone game binary. Nova3D's SDF /
RTX / path-tracing / radiance-cascade / spectral / ReSTIR features stay
in the "SKIP" bucket per the user's explicit "no fancy pipeline"
directive; the plan below excludes them.

**Delta versus HH3**: the 20 sprints below are re-costed against the
live tree (HH4 render / HH1 API / asset_import already landed). Every
sprint was verified to be **real remaining work** — no sprint targets a
subsystem that already shipped in the V→HH window.

**Priority tally**: **P0 = 7 sprints** (blocking parity), **P1 = 9
sprints** (unlocks major categories), **P2 = 4 sprints** (polish and
nice-to-have).

---

## 2. The 20 next-tick sprints

Every sprint is scoped to a single agent (~3–6 hours). Deliverables
are file-specific; success criteria are test-runnable.

---

## Sprint 1: Real wgpu forward pipeline in HH4 Renderer

**Priority**: P0
**Scope**: `python/pharos_engine/render/renderer.py` (extend — currently
`submit_mesh` / `submit_sprite` / `submit_lines` forward to
`NullRenderer` even when wgpu is up)
**Dependencies**: none (HH4 landed the shell)
**Deliverable**:
* `render/renderer.py` — real `_compile_forward_pipeline()` +
  `_begin_render_pass()` + `_submit_drawcalls()` gated on
  `self._ctx is not None`.
* Shader stock (`render/shader_stock.py`) wired through
  `wgpu.RenderPipeline` for the Blinn-Phong 3D + unlit 3D + 2D sprite
  + line stocks.
* `SlapPyEngineTests/tests/test_render_wgpu_forward.py` — headless
  wgpu offscreen test, reads back pixels, asserts non-zero.
**Success**: `Renderer(force_null=False).submit_mesh(cube, I, mat)` +
`read_pixels()` returns a shaded cube on any machine with a real
wgpu adapter; `NullRenderer` still runs unchanged for headless CI.

---

## Sprint 2: MTL parser + material resolve for OBJ importer

**Priority**: P0
**Scope**: `python/pharos_engine/asset_import/obj_importer.py` (extend —
line 9 documents "mtllib recorded but not resolved") + new
`asset_import/mtl_parser.py`
**Dependencies**: none
**Deliverable**:
* `asset_import/mtl_parser.py` — parse `Ka` / `Kd` / `Ks` / `Ns` / `d`
  / `map_Kd` / `map_Bump` / `illum` per the Wavefront MTL spec.
* `obj_importer.py` — when `mtllib` is present, sibling-load the .mtl
  file, map material names → `PBRMaterial` structs (basecolor / metal
  / rough) via the classic Blinn approx.
* `SlapPyEngineTests/tests/test_asset_import_mtl.py` — round-trip a
  test cube.obj + cube.mtl fixture, assert basecolor + diffuse map
  resolve to `TextureData`.
**Success**: `import_obj("cube.obj").materials[0].basecolor_tex` is a
`TextureData` (not `None`), and the HH4 renderer picks it up on
`submit_mesh(...)`.

---

## Sprint 3: Skinned-mesh loader in glTF importer

**Priority**: P0
**Scope**: `python/pharos_engine/asset_import/gltf_importer.py` (extend
— currently no `JOINTS_0` / `WEIGHTS_0` handling)
**Dependencies**: none (Sprint 4 consumes this)
**Deliverable**:
* `gltf_importer.py` — parse `JOINTS_0` (uvec4) + `WEIGHTS_0` (vec4)
  vertex attributes, expose them on `ImportResult.meshes[i].joints`
  / `.weights`.
* Skeleton extraction — walk `gltf.skins[*].joints`, build a
  `Skeleton` dataclass (bone hierarchy, inverse-bind matrices).
* `ImportResult.skeletons: list[Skeleton]` field.
* `SlapPyEngineTests/tests/test_gltf_skinned.py` — load a rigged glTF
  fixture (add `SlapPyEngineTests/goldens/asset_import/rigged_cube.glb`),
  assert 4-way vertex weights + non-empty skeleton.
**Success**: importing a rigged glTF file yields a `Skeleton` with the
expected bone count + weights summing to ~1.0 per vertex.

---

## Sprint 4: Skeletal animation runtime (Skeleton + AnimationClip + Skinner)

**Priority**: P0
**Scope**: new `python/pharos_engine/animation/skeleton.py` +
`animation/clip.py` + `animation/skinner.py`
**Dependencies**: Sprint 3 (skinned-mesh loader)
**Deliverable**:
* `animation/skeleton.py` — `Skeleton` / `Joint` / bone-palette
  computation (world matrices from parent chain).
* `animation/clip.py` — `AnimationClip` (translation / rotation /
  scale channels per bone, linear + step + cubic interp), `.sample(t)`
  → local pose.
* `animation/skinner.py` — CPU skinning fallback + Rust hook
  placeholder (feeds a future `skinning.wgsl` GPU pass).
* `SlapPyEngineTests/tests/test_skeletal_animation.py` — sample a
  wagging-tail clip at 3 timestamps, assert bone matrices match golden.
**Success**: `Skeleton.pose_at(clip, t=0.5)` returns a coherent world
matrix palette; CPU skinning matches reference within 1e-3.

---

## Sprint 5: Scene → drawcall walker (HH3 gap #2)

**Priority**: P0
**Scope**: new `python/pharos_engine/gpu/scene_renderer.py`
**Dependencies**: Sprint 1 (real wgpu pipeline)
**Deliverable**:
* `gpu/scene_renderer.py::SceneRenderer.walk_and_draw(scene, camera)`
  — filters visible entities, sorts by material handle, batches per
  pipeline, emits `Renderer.submit_mesh(...)` calls.
* Integration with existing `FF3 scenes` (`pharos_engine.scenes.Scene`)
  and `entity_renderer.py`.
* `SlapPyEngineTests/tests/test_scene_renderer.py` — 10-entity mock
  scene, assert drawcall order (material-sorted) and cull count.
**Success**: `walk_and_draw` emits ≤ N drawcalls for N entities (no
duplicate binds) and integrates with `hello_scene_reg` demo.

---

## Sprint 6: 3D BVH + frustum culling (HH3 gap #4)

**Priority**: P0
**Scope**: new `python/pharos_engine/spatial/` subpackage + wire to
Sprint 5
**Dependencies**: Sprint 5 (SceneRenderer consumes the culler)
**Deliverable**:
* `spatial/__init__.py` — thin re-export.
* `spatial/frustum.py` — `Frustum.from_view_proj(vp)`,
  `Frustum.intersects_aabb(aabb) -> bool`.
* `spatial/bvh3d.py` — wraps existing `_core.Bvh` (Rust — see FF4
  audit §1.1), exposes `Bvh3D.build(aabbs)` + `query_frustum(frustum)`.
* `SlapPyEngineTests/tests/test_spatial_frustum.py` — 27-node grid of
  AABBs, camera looking along +Z, assert cull count matches expected.
**Success**: `walk_and_draw` (Sprint 5) with culler enabled emits ~½
the drawcalls of the naïve path on a 100-entity scene.

---

## Sprint 7: Cascaded shadow maps (HH3 gap #5)

**Priority**: P0
**Scope**: `python/pharos_engine/lighting.py` (extend — 1026 LoC, no
CSM tokens today) + new `python/pharos_engine/shaders/csm.wgsl`
**Dependencies**: Sprint 1 (needs a real wgpu pipeline first)
**Deliverable**:
* `lighting.py::DirectionalLight.compute_cascade_splits(camera, near,
  far, count=4)` — practical PSSM split scheme.
* `lighting.py::render_shadow_cascade(scene, cascade_idx)` — 4×
  depth-only pass at 2048×2048 into a `TextureArrayView`.
* `python/pharos_engine/shaders/csm.wgsl` — sample cascade based on
  view-space z, 3×3 PCF filter.
* `SlapPyEngineTests/tests/test_csm.py` — render a plane + cube under
  a directional light, read back, assert shadow region hash matches
  golden.
**Success**: `hello_csm_demo.py` (Sprint 20) shows a cube casting a
crisp shadow across a plane with no near-cascade acne.

---

## Sprint 8: MSAA resolve pipeline in HH4 Renderer

**Priority**: P1
**Scope**: `python/pharos_engine/render/renderer.py` (extend — takes
`msaa: int = 4` today but never wires a resolve target)
**Dependencies**: Sprint 1 (real wgpu pipeline)
**Deliverable**:
* `renderer.py::_create_msaa_target(sample_count)` — colour + depth
  attachments with the correct sample counts.
* `renderer.py::_resolve_pass()` — post-pass resolve to a
  single-sample target when `self.msaa > 1`.
* Update `create_offscreen(w, h)` to honour `self.msaa`.
* `SlapPyEngineTests/tests/test_render_msaa.py` — render two hairline
  triangles at 1× vs 4× MSAA, assert edge-pixel variance drops.
**Success**: `Renderer(msaa=4)` produces smoother diagonals than
`Renderer(msaa=1)`; `NullRenderer` path unchanged.

---

## Sprint 9: Depth prepass for HH4 Renderer

**Priority**: P1
**Scope**: `python/pharos_engine/render/renderer.py` (extend)
**Dependencies**: Sprint 1, Sprint 8
**Deliverable**:
* `renderer.py::_run_depth_prepass(scene, camera)` — depth-only pass
  with front-to-back sort + early-Z write; disables colour writes.
* Wire the `EQUAL` depth-test path for the main colour pass.
* `render/shader_stock.py::depth_only_stock` — new stripped vertex/
  fragment for the prepass.
* `SlapPyEngineTests/tests/test_render_depth_prepass.py` — 5
  overlapping cubes, assert overdraw shader (fragment-count telemetry
  from Sprint 10 EE7 sink) is monotonically lower with prepass on.
**Success**: overdraw counter drops ≥ 50% on a heavy-overlap test
scene.

---

## Sprint 10: Screen-space ambient occlusion (SSAO)

**Priority**: P1
**Scope**: new `python/pharos_engine/post_process/ssao.py` +
`post_process/ssao.wgsl`
**Dependencies**: Sprint 9 (needs depth buffer + normal buffer from
prepass)
**Deliverable**:
* `post_process/ssao.py::SSAOPass` — 16-sample kernel, hemisphere
  around normal, bilateral blur.
* `post_process/ssao.wgsl` — actual WGSL shader (fits the existing
  chain-manifest schema).
* Register in `post_process/chain_manifest.py` as `ssao` pass id.
* Add a baked chain preset `ssao_default.chain.yaml`.
* `SlapPyEngineTests/tests/test_ssao_pass.py` — corner-of-two-planes
  test, assert AO darkens the corner more than open regions.
**Success**: `hello_v2_showcase` gains AO in the crevices; toggle
via chain manifest.

---

## Sprint 11: Skybox + cubemap import + rendering

**Priority**: P1
**Scope**: new `python/pharos_engine/asset_import/cubemap_importer.py`
+ `python/pharos_engine/render/skybox.py`
**Dependencies**: Sprint 1
**Deliverable**:
* `cubemap_importer.py` — load 6 face PNGs OR an equirectangular HDR
  (via `imageio`, soft dep) → 6-face `TextureCube`.
* `render/skybox.py::Skybox` — vertex-shader-less full-screen tri
  that samples the cube through inverse view-proj.
* Register `skybox` as a distinct scene node type in `pharos_engine.
  scenes`.
* `SlapPyEngineTests/tests/test_skybox.py` — 6-colour cubemap, camera
  facing +X, assert readback pixel matches +X face colour.
**Success**: `hello_skybox.py` renders a coloured horizon around any
scene.

---

## Sprint 12: IBL prefiltered cubemap chain (extend gpu/ibl.py)

**Priority**: P1
**Scope**: `python/pharos_engine/gpu/ibl.py` (extend — current file
notes "Full cubemap prefilter requires the ibl_prefilter.wgsl shader"
at `:159` and does not ship it)
**Dependencies**: Sprint 11 (skybox provides the source HDR)
**Deliverable**:
* `python/pharos_engine/shaders/ibl_prefilter.wgsl` — GGX importance
  sampling, 5-mip roughness chain.
* `gpu/ibl.py::IBLSystem.prefilter_from_hdr(path)` — runs the compute
  pass, populates `.prefilter_tex`.
* `gpu/ibl.py::IBLSystem.brdf_lut_bake()` — compute pass for BRDF LUT
  (Fresnel + roughness → 2-channel LUT).
* `SlapPyEngineTests/tests/test_ibl_prefilter.py` — spiky HDR input,
  assert mip 0 = mirror-like, mip 4 = near-uniform.
**Success**: PBR spheres in `hello_pbr.py` reflect a real environment
matching the loaded HDRI.

---

## Sprint 13: Text rendering with SDF glyph atlas

**Priority**: P1
**Scope**: new `python/pharos_engine/text/` subpackage
**Dependencies**: Sprint 1
**Deliverable**:
* `text/__init__.py` — public `TextRenderer.draw(surface, text, xy,
  size, color)` immediate-mode API.
* `text/glyph_atlas.py` — msdfgen-CLI OR `freetype-py` fallback for
  SDF glyph baking; produces a 1024×1024 8-bit atlas + metrics YAML.
* `text/shader_stock.py::sdf_text` WGSL stock — samples SDF, applies
  smoothstep with per-pixel derivatives.
* Bake a default Roboto Mono fixture at
  `python/pharos_engine/text/baked/roboto_mono.atlas.png`.
* `SlapPyEngineTests/tests/test_text_render.py` — draw "SLAPPY", read
  back, assert five distinct glyph blobs.
**Success**: `hello_hud.py` (Sprint 14 or existing) can draw text at
1080p without pixelation.

---

## Sprint 14: Runtime HUD subsystem (HH3 gap #11)

**Priority**: P1
**Scope**: new `python/pharos_engine/hud/` subpackage
**Dependencies**: Sprint 13 (text rendering)
**Deliverable**:
* `hud/__init__.py` — public `HUD.begin_frame() / draw_rect / draw_text
  / draw_image / draw_widget / end_frame`.
* `hud/imgui_backend.py` — optional `imgui[glfw]` backend (soft dep,
  gated behind `pharos_engine[hud]` extra).
* `hud/null_backend.py` — headless fallback that records draw ops for
  testing.
* Bridge to editor theme via
  `hud/theme_bridge.py::apply_diary_theme()`.
* `SlapPyEngineTests/tests/test_hud_immediate.py` — mock draw list of
  10 ops, assert order + colour.
**Success**: `hello_hud.py` shows a live FPS counter + button + panel
in the top-left of any wgpu window.

---

## Sprint 15: Video capture (FFmpeg wrapper)

**Priority**: P1
**Scope**: extend `python/pharos_engine/media.py` OR new
`python/pharos_engine/capture/` subpackage
**Dependencies**: Sprint 1 (needs `read_pixels()` to work on wgpu path)
**Deliverable**:
* `capture/__init__.py` — public `VideoCapture(path, fps, size).write
  _frame(rgba)` + `.close()`.
* `capture/ffmpeg_backend.py` — subprocess pipe to `ffmpeg -f rawvideo
  -pix_fmt rgba -s WxH -i - -c:v libx264 out.mp4`; soft dep on the
  `ffmpeg` binary being on PATH.
* `capture/pyav_backend.py` — alternative via the already-listed `av`
  extra.
* `SlapPyEngineTests/tests/test_video_capture.py` — capture a 3-frame
  gradient sequence, assert output file exists + is non-empty +
  ffprobe reports 3 frames.
**Success**: `hello_scene_reg.py --capture out.mp4` produces a
playable mp4.

---

## Sprint 16: Instanced rendering + `InstancedMesh` component

**Priority**: P1
**Scope**: `python/pharos_engine/gpu/mesh_renderer.py` (extend) + new
`gpu/instanced_mesh.py`
**Dependencies**: Sprint 5 (walker knows about instanced batches)
**Deliverable**:
* `gpu/instanced_mesh.py::InstancedMesh` — one vertex/index buffer +
  a per-instance model-matrix + tint buffer.
* `mesh_renderer.py::draw_instanced(mesh, instance_count)` — real
  `draw_indexed(index_count, instance_count)` call.
* Component wiring: `InstancedMeshComponent` in
  `python/pharos_engine/components.py`.
* `SlapPyEngineTests/tests/test_instanced_mesh.py` — 1000 grass blades,
  assert drawcall count == 1 (not 1000).
**Success**: a grass-field demo goes from 1000 drawcalls → 1 drawcall
with the same visible geometry.

---

## Sprint 17: 3D positional audio + sound bank

**Priority**: P1
**Scope**: `python/pharos_engine/audio.py` (extend) + new
`python/pharos_engine/audio/sound_bank.py`
**Dependencies**: none (existing spatial support attenuates but has
no orientation)
**Deliverable**:
* `audio.py::AudioListener` (position + forward + up) — replaces the
  positional `listener_pos` param.
* `audio/sound_bank.py::SoundBank.from_yaml(path)` — YAML manifest
  mapping sound ids → file paths + default volume/pitch/loop; hot-reload.
* Simple HRTF or pan-law spatialisation using the listener orientation
  (start with cosine-pan; HRTF is a stretch goal).
* `SlapPyEngineTests/tests/test_audio_bank.py` — YAML round-trip + a
  panning test that verifies left/right volume ratio for a source to
  the listener's right.
**Success**: `hello_audio_3d.py` — a bee flying around the listener
pans left/right correctly.

---

## Sprint 18: 3D physics broadphase soft-import (unpin `physics/`)

**Priority**: P0
**Scope**: `python/pharos_engine/physics/` (currently untracked in
`git status`) — commit the ~40 module tree + wire BVH broadphase
**Dependencies**: Sprint 6 (Bvh3D)
**Deliverable**:
* Stage + review + commit the untracked `python/pharos_engine/physics/`
  tree (per GG7 §5 "P0 for surface hygiene").
* Wire `physics/broadphase.py::BVHBroadphase` to `_core.Bvh` from
  Sprint 6.
* Add / refresh `SlapPyEngineTests/tests/test_physics_broadphase.py`
  — 500 body 3D scene, assert broadphase reports ~O(N log N) pair
  candidates.
**Success**: `git status` no longer shows uncommitted `physics/`
files; broadphase test suite green; ragdoll demo still passes.

---

## Sprint 19: Cross-platform game exporter (HH3 gap #6)

**Priority**: P1
**Scope**: extend `python/pharos_engine/build_gen.py` → new
`python/pharos_engine/packaging/` subpackage
**Dependencies**: HH2 (project scaffolder) already landed
**Deliverable**:
* `packaging/__init__.py` — public `export_game(project_path,
  target, out_dir)`.
* `packaging/pyinstaller_backend.py` — wraps `PyInstaller` with a
  spec-file generator; targets `windows` / `linux` / `macos`.
* `packaging/asset_bundle.py` — walk the project's asset_manifest,
  encrypt via `content_encrypt.py`, pack into a single `.slap`
  container using `_core.lz4_compress`.
* `cli.py` — add `slap build --target <triple>` subcommand.
* `SlapPyEngineTests/tests/test_packaging_dry_run.py` — dry-run mode
  (no actual PyInstaller call), assert spec file contents.
**Success**: `slap build --target windows` on the tutorial project
produces a runnable `.exe` under 100 MB.

---

## Sprint 20: hello_gltf_character demo + parity harness

**Priority**: P2
**Scope**: new `SlapPyEngineExamples/examples/hello_gltf_character.py`
+ trace fixture
**Dependencies**: Sprints 1, 3, 4, 5, 6, 7 (end-to-end demo of the P0
stack)
**Deliverable**:
* `hello_gltf_character.py` — loads a rigged glTF (added under
  `SlapPyEngineExamples/assets/`), builds a scene, plays a walk cycle,
  renders with CSM under directional light, captures 60 frames.
* `hello_gltf_character_trace.yaml` — golden trace of per-frame bone
  poses + drawcall counts.
* `SlapPyEngineTests/tests/test_demo_hello_gltf_character.py` — runs
  the demo headless, asserts trace matches golden within 1e-3.
* Update `docs/tutorial_build_a_game.md` with a linked walkthrough.
**Success**: the demo is the acceptance test for Sprints 1-7; a green
run means "SlapPyEngine can render a Nova3D-comparable 3D scene".

---

## 3. Recommended sprint order (DAG)

Read top-to-bottom, left-to-right. Arrows = "must land first".

```
                            ┌────────────────────┐
                            │ Sprint 1  (P0)     │  Real wgpu pipeline
                            └────────┬───────────┘
                                     │
      ┌──────────────────────────────┼──────────────────────────────────┐
      │                              │                                  │
      ▼                              ▼                                  ▼
┌───────────────────┐   ┌──────────────────────────┐    ┌──────────────────────────┐
│ Sprint 8  (P1)    │   │ Sprint 5  (P0)  Scene    │    │ Sprint 15 (P1)  Video    │
│  MSAA resolve     │   │  → drawcall walker       │    │  capture (FFmpeg)        │
└─────────┬─────────┘   └────────┬─────────────────┘    └──────────────────────────┘
          │                      │
          ▼                      ▼
┌───────────────────┐   ┌───────────────────────┐
│ Sprint 9  (P1)    │   │ Sprint 6  (P0)        │  3D BVH + frustum culler
│  Depth prepass    │   │                       │
└────────┬──────────┘   └────────┬──────────────┘
         │                       │
         ▼                       ▼
┌───────────────────┐   ┌──────────────────────────────┐
│ Sprint 10 (P1)    │   │ Sprint 18 (P0)               │  Physics unpin +
│  SSAO             │   │  BVH broadphase              │  BVH wiring
└───────────────────┘   └──────────────────────────────┘

┌───────────────────┐   ┌───────────────────────┐   ┌──────────────────────────┐
│ Sprint 2  (P0)    │   │ Sprint 3  (P0)        │   │ Sprint 11 (P1)  Skybox   │
│  MTL parser       │   │  Skinned-mesh loader  │   │  + cubemap import        │
└───────────────────┘   └────────┬──────────────┘   └────────┬─────────────────┘
                                 │                            │
                                 ▼                            ▼
                        ┌────────────────────────┐   ┌────────────────────────┐
                        │ Sprint 4  (P0)         │   │ Sprint 12 (P1)  IBL    │
                        │  Skeletal runtime      │   │  prefilter chain       │
                        └────────────────────────┘   └────────────────────────┘

┌───────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
│ Sprint 7  (P0)    │   │ Sprint 13 (P1)  Text   │   │ Sprint 16 (P1)  Instanced│
│  Cascaded shadows │   │  SDF glyph atlas       │   │  rendering               │
└───────────────────┘   └────────┬───────────────┘   └──────────────────────────┘
                                 │
                                 ▼
                        ┌────────────────────────┐
                        │ Sprint 14 (P1)  Runtime│
                        │  HUD subsystem         │
                        └────────────────────────┘

┌───────────────────┐   ┌────────────────────────┐   ┌──────────────────────────┐
│ Sprint 17 (P1)    │   │ Sprint 19 (P1)  Game   │   │ Sprint 20 (P2)  Parity   │
│  3D positional    │   │  exporter              │   │  demo + harness          │
│  audio            │   └────────────────────────┘   └──────────────────────────┘
└───────────────────┘
```

**Suggested batches** (7-agent parallel windows):

* **Batch A (P0 unblock)**: 1, 2, 3, 11, 15, 17, 18. Parallelisable —
  no cross-deps.
* **Batch B (rendering middle)**: 4 (waits on 3), 5 (waits on 1), 6
  (waits on 5), 8 (waits on 1), 12 (waits on 11), 13, 19.
* **Batch C (visual polish + demo)**: 7 (needs 1), 9 (needs 8), 10
  (needs 9), 14 (needs 13), 16 (needs 5), 20 (needs 1/3/4/5/6/7).

Runway estimate: **3 batch windows ≈ 21 sprint slots at 7 agents each**.
With ~4-hour slot times that's ~12 hours of parallel work → ~1.5-2
calendar days at the current cadence.

---

## 4. Cross-reference to Nova3D subsystems (HH3 §2 / §3)

| Sprint | Nova3D subsystem HH3 flagged | HH3 status | HH3 §3 row |
|-------:|------------------------------|------------|------------|
| 1 | `graphics/` (Renderer 3075 LoC) | PARTIAL | row "graphics" |
| 2 | `import/` (Assimp OBJ+MTL) | GAP | row "import" |
| 3 | `import/` + `animation/` (glTF skin) | GAP + PARTIAL | rows "import" / "animation" |
| 4 | `animation/` (Skeleton, blend trees) | PARTIAL | row "animation" |
| 5 | `graphics/` + `scene/` (walker) | PARTIAL | rows "graphics" / "scene" |
| 6 | `spatial/` (BVH / Octree / Frustum) | PARTIAL (2D only) | row "spatial" |
| 7 | `graphics/` (`CascadedShadowMaps`) | PARTIAL | rendering deep-dive §5 |
| 8 | `graphics/` (framebuffer / MSAA) | PARTIAL | rendering deep-dive §5 |
| 9 | `graphics/` (depth prepass / GBuffer) | PARTIAL | rendering deep-dive §5 |
| 10 | `graphics/` (SSGI / SSAO) | PARTIAL | rendering deep-dive §5 |
| 11 | `graphics/` (skybox / LightProbeSystem) | PARTIAL | rendering deep-dive §5 |
| 12 | `lighting/` + `graphics/` (LightProbeSystem, IBL) | PARTIAL | rows "lighting" / "graphics" |
| 13 | `text/` | GAP | row "text" |
| 14 | `ui/` (runtime HUD ≠ editor UI) | PARTIAL | §7 UI system gap |
| 15 | none (Nova3D lacks capture — SlapPyEngine strength) | N/A | complements FF wheel |
| 16 | `graphics/` (`InstancedMesh` / `Batching`) | PARTIAL | rendering deep-dive §5 |
| 17 | `audio/` (`AudioEngine` 1236 LoC OpenAL) | PARTIAL | row "audio" |
| 18 | `physics/` (RigidBody 3D + broadphase) + `spatial/` | GAP + PARTIAL | rows "physics" / "spatial" |
| 19 | `packaging/` (9 files) | PARTIAL | row "packaging" |
| 20 | integration / demo harness | — | HH3 §11 summary card |

**Sprints skipping HH3's SKIP bucket**: no sprint targets path tracing,
RTX, spectral render, radiance cascade beyond current stub, SDF brick
cache, marching cubes, Firebase, or FBX. Those remain deprioritised
per the HH3 §4 tally and the user's "no fancy pipeline" directive.

**HH3 items not covered in this 20-sprint slate** (deferred to a
later plan):

* NavMesh + A* pathfinding (HH3 gap #12) — NICE_TO_HAVE, plan for
  a future sprint batch.
* GPU particle system (HH3 gap #13) — NICE_TO_HAVE, can piggy-back
  on Sprint 5's walker.
* Replay determinism harness (HH3 gap #14) — needs `_slide` port
  from FF4 to close the physics determinism gap first.
* Localization (HH3 gap #15), accessibility (#16), terrain (#17),
  modding (#19) — all NICE_TO_HAVE, batch as a "polish" round after
  parity.

---

## 5. Cross-references

* `H:\Github\SlapPyEngine\docs\nova3d_gap_audit_2026_07_05.md` — HH3
  audit (610 lines).
* `H:\Github\SlapPyEngine\docs\big_picture_2026_07_05.md` — GG7 rollup
  (291-row feature map @ 93.8% WIRED).
* `H:\Github\SlapPyEngine\docs\rust_migration_audit_2026_07_05.md` —
  FF4 audit (17 shipped kernels).
* `H:\Github\SlapPyEngine\python\pharos_engine\render\renderer.py` — HH4
  wgpu façade currently forwarding to `NullRenderer`.
* `H:\Github\SlapPyEngine\python\pharos_engine\asset_import\gltf_importer.py`
  — real pygltflib-backed glTF loader.
* `H:\Github\SlapPyEngine\python\pharos_engine\asset_import\obj_importer.py`
  — real OBJ parser, MTL not resolved.
* `H:\Github\SlapPyEngine\python\pharos_engine\lighting.py` — 1026 LoC,
  no CSM tokens yet.
* `H:\Github\SlapPyEngine\python\pharos_engine\gpu\ibl.py` — IBL system
  with prefilter shader marked "requires ibl_prefilter.wgsl" at `:159`.
* `H:\Github\SlapPyEngine\python\pharos_engine\input\_manager.py` —
  gamepad support already wired via glfw (Sprint deliberately excluded
  from this plan — already landed).

---

## 6. Summary card

* **Sprint count**: 20 (7 × P0, 9 × P1, 4 × P2).
* **Top-3 P0 sprints** (parity blockers):
  1. Real wgpu forward pipeline in HH4 Renderer.
  2. Scene → drawcall walker.
  3. Skeletal animation runtime + skinned-mesh loader.
* **Total agent-slots**: ~20 × 4-6 h = **80–120 hours** ≈ 3 parallel
  batches at 7 agents each.
* **HH3 subsystems addressed**: 12 (graphics, import, animation, scene,
  spatial, lighting, physics, text, ui, audio, packaging, plus a video
  capture bonus).
* **HH3 SKIP items untouched**: path tracing, RTX, spectral, radiance
  cascade beyond current stub, SDF brick cache, marching cubes,
  Firebase, FBX.
* **Downstream unlock**: Sprint 20 (`hello_gltf_character`) is the
  acceptance test — a green demo means SlapPyEngine has reached HH3-
  defined 3D content-pipeline parity minus the deprioritised "fancy"
  items.

---

*Nova3D parity sprint plan generated 2026-07-05 by II7 background
scrum agent. All 20 sprints verified against the live source tree at
`H:\Github\SlapPyEngine\python\pharos_engine\` — no sprint targets work
that already landed in the V→HH sprint window.*
