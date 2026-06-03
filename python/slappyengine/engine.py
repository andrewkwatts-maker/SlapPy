from __future__ import annotations
import time
import wgpu
from pathlib import Path
try:
    from rendercanvas.auto import RenderCanvas as WgpuCanvas, loop as _rc_loop
    def run(): _rc_loop.run()
except ImportError:
    from wgpu.gui.auto import WgpuCanvas, run  # type: ignore[assignment]
from slappyengine.config import engine_config, Config, ConfigManager, _find_config_dir
from slappyengine.struct_registry import StructRegistry
from slappyengine.shader_gen import ShaderGen
from slappyengine.tags import TagRegistry
from slappyengine.gpu.context import GPUContext
from slappyengine.gpu.texture_manager import TextureManager
from slappyengine.gpu.buffer_manager import BufferManager
from slappyengine.gpu.render_pipeline import RenderPipeline
from slappyengine.gpu.entity_renderer import EntityRenderer
from slappyengine.camera import Camera
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.scene import Scene
    from slappyengine.compute.effect import EffectPipeline
    from slappyengine.residency.manager import ResidencyManager
    from slappyengine.lighting import LightingSystem
    from slappyengine.render_channel import RenderChannelCompositor
    from slappyengine.fluid_sim import GlobalFluidSim, FluidSimConfig
    from slappyengine.net.session import GameSession, SessionConfig
    from slappyengine.gpu.ibl import IBLSystem
    from slappyengine.gpu.sdf_renderer import SdfRenderer
    from slappyengine.gpu.cluster_3d import Cluster3DSystem


class Engine:
    def __init__(self, config_path: str | None = None, **overrides):
        self._cfg: Config = engine_config(config_path)
        # Apply keyword overrides to window config
        for key, val in overrides.items():
            if hasattr(self._cfg.window, key):
                setattr(self._cfg.window, key, val)
            else:
                raise TypeError(f"Unknown Engine override: '{key}'")

        # Resolve the absolute path to engine.yml for ConfigManager
        if config_path is not None:
            _engine_yml = str(Path(config_path))
        else:
            _engine_yml = str(_find_config_dir() / "engine.yml")
        self._config_manager = ConfigManager(_engine_yml)

        self._scene: Scene | None = None
        self._registry: StructRegistry = StructRegistry()
        self.camera: Camera = Camera()

        # Action-map / split-screen subsystems (zero-cost when unused)
        from slappyengine.input.action_map import ActionMap as _ActionMap  # noqa: F401
        self._action_maps: list = []           # list[ActionMap], one per player
        self._split_screen: "SplitScreenManager | None" = None

        # Mouse state — updated via canvas event handlers in _setup_gpu
        self._mouse_x: float = 0.0
        self._mouse_y: float = 0.0
        self._mouse_clicked: bool = False

        # GPU subsystems — None until run()
        self._gpu: GPUContext | None = None
        self._tex_mgr: TextureManager | None = None
        self._buf_mgr: BufferManager | None = None
        self._pipeline: RenderPipeline | None = None
        self._renderer: EntityRenderer | None = None
        self._shader_gen: ShaderGen | None = None
        self._tag_registry: TagRegistry | None = None
        self._effect_pipeline: "EffectPipeline | None" = None
        self._residency: "ResidencyManager | None" = None
        self._post_executor = None
        self._lighting: "LightingSystem | None" = None
        self._compositor: "RenderChannelCompositor | None" = None
        self._input: "InputManager | None" = None
        self._audio: "AudioManager | None" = None
        self._fluid_sim: "GlobalFluidSim | None" = None
        self._frame_index: int = 0
        self._net_session: "GameSession | None" = None

        # Profiling timing state (WP-7.7)
        self._last_frame_time: float = 0.0   # time.perf_counter of last frame start
        self._last_frame_ms: float = 0.0     # duration of the previous frame in ms
        self._fps: float = 0.0               # rolling-average FPS
        self._update_ms: float = 0.0         # time spent in user update/tick callback
        self._render_ms: float = 0.0         # time spent submitting GPU commands
        # Rolling buffer: last N frame durations for FPS smoothing
        self._frame_times: list[float] = []
        self._FPS_WINDOW: int = 60

        # 3D mesh rendering — None until first 3D Layer is encountered (WP-4.10)
        self._mesh_pipeline = None   # MeshPipeline — shared across all 3D layers
        self._mesh_renderers: dict = {}  # id(layer) → MeshRenderer

        # Optional rendering subsystems — off by default, enabled via enable_*()
        self._ibl: "IBLSystem | None" = None
        self._sdf_renderer: "SdfRenderer | None" = None
        self._cluster_3d: "Cluster3DSystem | None" = None

    def load_scene(self, scene: "Scene") -> None:
        self._scene = scene
        if self._gpu is not None:
            self._wire_compute(scene)

    def watch_config(self, callback) -> None:
        """Register callback(changed_keys: dict) for config hot-reload.

        The callback receives a flat dict of dotted key paths to their new
        values whenever ``engine.yml`` changes on disk.  Keys that require an
        engine restart (``window.width``, ``window.height``, ``window.title``)
        are excluded from the callback and emit a :mod:`warnings` warning
        instead.

        Requires ``watchdog`` (``pip install watchdog``).  If watchdog is not
        installed this method is a no-op — no exception is raised.

        Example::

            def on_config_change(changed):
                if "physics.default_dt" in changed:
                    engine._cfg.physics.default_dt = changed["physics.default_dt"]

            engine.watch_config(on_config_change)
        """
        self._config_manager.watch(callback)

    def register_module(self, module) -> None:
        """Register a StructModule before run() is called."""
        self._registry.register(module)

    def register_tags(self, tag_registry: "TagRegistry") -> None:
        """Replace the engine's tag registry (call before run())."""
        self._tag_registry = tag_registry

    def _wire_compute(self, scene: "Scene") -> None:
        from slappyengine.compute.asset_compute import AssetComputeAPI, PixelAPI
        from slappyengine.asset import Asset

        for entity in scene.entities:
            if isinstance(entity, Asset):
                entity.compute = AssetComputeAPI(
                    entity, self._gpu, self._registry, self._shader_gen,
                    self._tag_registry, self._buf_mgr,
                )
                entity.pixels = PixelAPI(
                    entity, self._gpu, self._registry, self._shader_gen,
                    self._tag_registry, self._buf_mgr,
                )

        # Wire scene-level compute
        from slappyengine.scene import SceneComputeAPI, DecalSystem
        scene.compute = SceneComputeAPI(scene, self._gpu)
        scene.decals = DecalSystem(self._gpu, self._registry, self._tex_mgr)

        if self._residency is not None:
            from slappyengine.asset import Asset as _Asset
            for entity in scene.entities:
                if isinstance(entity, _Asset):
                    entity._residency_mgr = self._residency

        if self._effect_pipeline is None and self._gpu is not None:
            from slappyengine.compute.effect import EffectPipeline
            self._effect_pipeline = EffectPipeline(
                self._gpu, self._registry, self._shader_gen, self._tag_registry
            )

        if hasattr(scene, 'collision') and scene.collision is not None:
            scene.collision.init_gpu(self._gpu,
                self._cfg.window.width, self._cfg.window.height)

    def _setup_gpu(self, canvas: WgpuCanvas) -> None:
        self._gpu = GPUContext(canvas)
        self._gpu.initialize(self._cfg)

        self._tex_mgr = TextureManager(self._gpu)
        self._buf_mgr = BufferManager(self._gpu, self._registry)

        self._pipeline = RenderPipeline(self._gpu)
        self._pipeline.build()

        self._renderer = EntityRenderer(
            self._gpu, self._tex_mgr, self._buf_mgr, self._pipeline
        )
        self._renderer.initialize()

        # Wire camera viewport size
        w, h = self._cfg.window.width, self._cfg.window.height
        self.camera._viewport_size = (w, h)

        self._shader_gen = ShaderGen(self._registry)
        if self._tag_registry is None:
            self._tag_registry = TagRegistry(
                max_bits=engine_config().tags.max_bits
            )

        self._registry.lock()

        from slappyengine.compute.effect import EffectPipeline
        self._effect_pipeline = EffectPipeline(
            self._gpu, self._registry, self._shader_gen, self._tag_registry
        )

        from slappyengine.residency.manager import ResidencyManager
        save_dir = Path(self._cfg.residency.save_dir) if hasattr(self._cfg.residency, 'save_dir') else Path(".")
        self._residency = ResidencyManager(
            ctx=self._gpu, buf_mgr=self._buf_mgr, tex_mgr=self._tex_mgr, save_dir=save_dir
        )

        from slappyengine.post_process.executor import PostProcessExecutor
        self._post_executor = PostProcessExecutor(self._gpu)

        from slappyengine.lighting import LightingSystem
        self._lighting = LightingSystem(
            self._gpu, self._cfg.window.width, self._cfg.window.height
        )
        from slappyengine.render_channel import RenderChannelCompositor
        self._compositor = RenderChannelCompositor(
            self._gpu, self._cfg.window.width, self._cfg.window.height
        )

        # Register canvas mouse event handlers to capture pointer state.
        # Wrapped in try/except so headless / test canvases that lack
        # add_event_handler don't crash the engine.
        try:
            @canvas.add_event_handler("pointer_move")
            def _on_pointer_move(event):
                self._mouse_x = float(event.get("x", 0))
                self._mouse_y = float(event.get("y", 0))

            @canvas.add_event_handler("pointer_down")
            def _on_pointer_down(event):
                self._mouse_x = float(event.get("x", 0))
                self._mouse_y = float(event.get("y", 0))
                self._mouse_clicked = True

            @canvas.add_event_handler("pointer_up")
            def _on_pointer_up(event):
                self._mouse_clicked = False
        except AttributeError:
            pass

        # InputManager: full keyboard + mouse + gamepad state tracking.
        from slappyengine.input import InputManager
        self._input = InputManager()
        try:
            def _combined_key_down(event):
                self._input._on_key_event(event)
                self._on_key_down(event.get("key", ""))

            def _combined_key_up(event):
                self._input._on_key_event(event)
                self._on_key_up(event.get("key", ""))

            canvas.add_event_handler(_combined_key_down, "key_down")
            canvas.add_event_handler(_combined_key_up,   "key_up")
        except AttributeError:
            pass  # headless / test canvas

        from slappyengine.audio import AudioManager
        self._audio = AudioManager()

        # If enable_fluid_sim() was called before run(), initialize it now that the GPU is ready.
        if self._fluid_sim is not None and not self._fluid_sim._initialized:
            self._fluid_sim.initialize()
            if hasattr(self._lighting, 'set_fluid_density'):
                self._lighting.set_fluid_density(self._fluid_sim.density_tex)

        # If enable_ibl() was called before run(), finish GPU initialization now.
        if self._ibl is not None and not self._ibl._initialized:
            try:
                self._ibl.init_gpu(self._gpu, self._cfg.window.width, self._cfg.window.height)
                pending = getattr(self._ibl, '_pending_hdri', None)
                if pending:
                    self._ibl.load_hdri(pending)
            except Exception:
                pass  # graceful degradation — IBL unavailable

        # If enable_sdf() / enable_cluster_3d() were called before run(),
        # the gpu arg was None; recreate them now with the live GPU context.
        if self._sdf_renderer is not None and self._sdf_renderer._gpu is None:
            try:
                from slappyengine.gpu.sdf_renderer import SdfRenderer
                self._sdf_renderer = SdfRenderer(
                    self._gpu, self._cfg.window.width, self._cfg.window.height
                )
            except Exception:
                pass

        if self._cluster_3d is not None and self._cluster_3d._gpu is None:
            try:
                from slappyengine.gpu.cluster_3d import Cluster3DSystem
                self._cluster_3d = Cluster3DSystem(
                    self._gpu, self._cfg.window.width, self._cfg.window.height
                )
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # 3D layer render path (WP-4.10)
    # -----------------------------------------------------------------------

    def _draw_3d_layer_to_texture(self, layer, w: int, h: int):
        """Render a single Layer(mode="3D") to an offscreen texture and return it.

        Lazy-creates MeshPipeline (once per engine, shared) and MeshRenderer
        (once per layer, keyed by id(layer)).  Returns a ``wgpu.GPUTexture``
        that the caller is responsible for destroying, or ``None`` when the
        layer has no geometry yet.

        Zero overhead when no 3D layers are present — this method is never
        called in that case (the caller checks for 3D layers first).
        """
        # Lazy-import keeps the module importable in test environments without wgpu
        from slappyengine.gpu.mesh_pipeline import MeshPipeline
        from slappyengine.gpu.mesh_renderer import MeshRenderer

        # --- Lazy pipeline creation (one per engine) ----------------------------
        if self._mesh_pipeline is None:
            self._mesh_pipeline = MeshPipeline(
                self._gpu.device,
                str(self._gpu.surface_format),
            )

        # --- Lazy renderer creation (one per layer) -----------------------------
        layer_id = id(layer)
        if layer_id not in self._mesh_renderers:
            self._mesh_renderers[layer_id] = MeshRenderer(
                self._gpu, self._mesh_pipeline
            )

        renderer = self._mesh_renderers[layer_id]

        # --- Upload geometry / material when present on the layer ---------------
        if layer.mesh_geometry is not None:
            renderer.set_mesh(layer.mesh_geometry)

        if layer.mesh_material is not None:
            renderer.set_material(layer.mesh_material)

        # --- Camera matrices — identity for Sprint 4; Sprint 5 wires real ones --
        _identity = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        renderer.update_camera(
            model=_identity,
            view=_identity,
            proj=_identity,
            normal_matrix=_identity,
        )

        # --- Render to an offscreen texture; return None if no mesh is ready ----
        if layer.mesh_geometry is None:
            return None  # nothing to draw yet

        return renderer.render_to_texture(
            w, h,
            output_format=str(self._gpu.surface_format),
        )

    def run(
        self,
        max_frames: int | None = None,
        target_fps: float | None = None,
    ) -> None:
        """Open the engine window and enter the main loop.

        Parameters
        ----------
        max_frames:
            When ``None`` (default), block in the platform event loop until
            the window is closed — today's behaviour.  When given an ``int``
            ``N >= 0``, drive the draw callback exactly ``N`` times in-process
            (no event loop, no window blocking) and return.  This is the
            CI-driveable smoke path that examples calling ``engine.run()``
            with no arguments rely on for headless testing.

            The ``SLAPPYENGINE_MAX_FRAMES`` environment variable provides a
            CI-friendly fallback: when ``max_frames`` is ``None`` and the env
            var is set to a non-negative integer, it is used instead.  The
            explicit kwarg always wins.
        target_fps:
            Optional frame-pacing target for the headless (``max_frames``)
            path.  When set, the draw loop sleeps between frames so the
            in-process tick rate is bounded.  ``None`` (default) runs frames
            as fast as possible.  Ignored in the live event-loop path.
        """
        # --- max_frames: kwarg wins; SLAPPYENGINE_MAX_FRAMES is the fallback --
        if max_frames is None:
            import os
            _env_val = os.environ.get("SLAPPYENGINE_MAX_FRAMES")
            if _env_val is not None and _env_val != "":
                try:
                    max_frames = int(_env_val)
                except ValueError:
                    raise ValueError(
                        "SLAPPYENGINE_MAX_FRAMES must be a non-negative integer, "
                        f"got {_env_val!r}"
                    )

        canvas = WgpuCanvas(
            title=self._cfg.window.title,
            size=(self._cfg.window.width, self._cfg.window.height),
        )
        self._setup_gpu(canvas)
        if self._scene is not None:
            self._wire_compute(self._scene)

        cc = tuple(self._cfg.window.clear_color)

        def _draw():
            # --- Frame timing (WP-7.7) -----------------------------------------
            _frame_start = time.perf_counter()
            if self._last_frame_time > 0.0:
                _frame_dt = _frame_start - self._last_frame_time
                self._last_frame_ms = _frame_dt * 1000.0
                self._frame_times.append(_frame_dt)
                if len(self._frame_times) > self._FPS_WINDOW:
                    self._frame_times.pop(0)
                _avg = sum(self._frame_times) / len(self._frame_times)
                self._fps = 1.0 / _avg if _avg > 0.0 else 0.0
            self._last_frame_time = _frame_start

            frame_tex = self._gpu.get_current_texture()
            encoder = self._gpu.create_encoder("frame")

            # In split-screen mode update each viewport camera; otherwise use
            # the single engine camera.  Camera upload happens inside the render
            # loop below, so we skip the eager update here when split is active.
            if self._split_screen is None:
                self._renderer.update_camera(self.camera)

            # Route mouse events to SceneUIEntity widgets
            if self._scene is not None:
                from slappyengine.ui.scene_ui import SceneUIEntity
                for entity in self._scene.entities:
                    if isinstance(entity, SceneUIEntity):
                        entity.handle_mouse(self._mouse_x, self._mouse_y,
                                            pressed=self._mouse_clicked)
                self._mouse_clicked = False  # consume click after routing

            if self._scene is not None and self._scene.landscape is not None:
                self._scene.landscape.update(self.camera)

            if self._scene is not None and self._effect_pipeline is not None:
                from slappyengine.asset import Asset
                for entity in self._scene.entities:
                    if isinstance(entity, Asset) and entity.effects:
                        self._effect_pipeline.dispatch_effects(entity, self._buf_mgr)

            # Pixel physics — dispatch per-pixel simulation for scenes that opt in
            if (self._scene is not None and
                    getattr(self._scene, 'pixel_physics_enabled', False)):
                from slappyengine.asset import Asset
                for entity in self._scene.entities:
                    if isinstance(entity, Asset) and entity.compute is not None:
                        try:
                            entity.compute.dispatch("pixel_physics",
                                                    dt=self._cfg.physics.default_dt)
                        except Exception:
                            pass

            rp = encoder.begin_render_pass(
                color_attachments=[{
                    "view": frame_tex.create_view(),
                    "resolve_target": None,
                    "clear_value": cc,
                    "load_op": wgpu.LoadOp.clear,
                    "store_op": wgpu.StoreOp.store,
                }]
            )

            if self._split_screen is not None and self._scene is not None:
                # --- Split-screen: render once per viewport -------------------
                original_camera = self._scene.camera
                for vp in self._split_screen.viewports:
                    if vp.camera is None:
                        continue
                    # Ensure the camera knows its panel dimensions
                    vp.camera._viewport_size = (vp.width, vp.height)
                    self._renderer.update_camera(vp.camera)
                    # Restrict GPU drawing to this panel
                    try:
                        rp.set_viewport(
                            float(vp.x), float(vp.y),
                            float(vp.width), float(vp.height),
                            0.0, 1.0,
                        )
                        rp.set_scissor_rect(vp.x, vp.y, vp.width, vp.height)
                    except Exception:
                        # wgpu version does not expose set_viewport / set_scissor_rect
                        # on this encoder type — render without clipping.
                        pass
                    # Temporarily expose this viewport's camera via scene.camera
                    # so parallax and other scene logic sees the right camera.
                    self._scene.camera = vp.camera
                    self._renderer.render(self._scene, rp)
                # Restore scene camera and full-screen viewport
                self._scene.camera = original_camera
                try:
                    rp.set_viewport(
                        0.0, 0.0,
                        float(self._cfg.window.width),
                        float(self._cfg.window.height),
                        0.0, 1.0,
                    )
                    rp.set_scissor_rect(
                        0, 0,
                        self._cfg.window.width,
                        self._cfg.window.height,
                    )
                except Exception:
                    pass
            elif self._scene is not None:
                # --- Normal single-player render ------------------------------
                self._renderer.render(self._scene, rp)

            rp.end()

            # --- 3D layer render path (WP-4.10) --------------------------------
            # Zero overhead guard: only enter this block when at least one 3D
            # layer exists.  getattr(..., "2D") default means old Layer objects
            # without a mode attribute are silently treated as 2D.
            if self._scene is not None:
                _w = self._cfg.window.width
                _h = self._cfg.window.height
                _3d_layers = [
                    (entity, layer)
                    for entity in self._scene.entities
                    for layer in getattr(entity, "layers", [])
                    if getattr(layer, "mode", "2D") == "3D"
                    and getattr(layer, "visible", True)
                ]
                if _3d_layers:
                    for _entity, _layer in _3d_layers:
                        # Render mesh to an offscreen texture, then blit onto
                        # the frame.  Uses a separate encoder so the 2D render
                        # pass above is never mutated.
                        _3d_tex = self._draw_3d_layer_to_texture(_layer, _w, _h)
                        if _3d_tex is not None:
                            # Blit 3D layer texture onto the frame surface via
                            # texture-to-texture copy (requires COPY_SRC on
                            # the offscreen texture and COPY_DST on the frame).
                            _blit_enc = self._gpu.create_encoder("3d_layer_blit")
                            try:
                                _blit_enc.copy_texture_to_texture(
                                    {
                                        "texture": _3d_tex,
                                        "mip_level": 0,
                                        "origin": (0, 0, 0),
                                    },
                                    {
                                        "texture": frame_tex,
                                        "mip_level": 0,
                                        "origin": (0, 0, 0),
                                    },
                                    (_w, _h, 1),
                                )
                                self._gpu.submit(_blit_enc)
                            except Exception:
                                # Graceful degradation: blit may fail if the
                                # surface texture lacks COPY_DST usage (some
                                # wgpu backends / platforms).  The 3D content
                                # is simply omitted for this frame rather than
                                # crashing the engine.
                                pass
                            _3d_tex.destroy()

            # SDF renderer dispatch — runs after the main scene and 3D layers
            # so the frame is fully composited before raymarching writes to g-buffer.
            if self._sdf_renderer is not None:
                try:
                    self._sdf_renderer.dispatch(
                        self.camera.position,
                        getattr(self.camera, 'forward', (0.0, 0.0, -1.0)),
                        getattr(self.camera, 'right',   (1.0, 0.0,  0.0)),
                        getattr(self.camera, 'up',      (0.0, 1.0,  0.0)),
                    )
                except Exception:
                    pass  # graceful degradation — SDF pass skipped this frame

            # Layer 2 pixel collision scan
            if (self._scene is not None and
                    hasattr(self._scene, 'collision') and
                    self._scene.collision is not None):
                col = self._scene.collision
                col.dispatch_pixel_scan(encoder)
                # Build entity index map
                entities_by_idx = {
                    (i + 1): e
                    for i, e in enumerate(self._scene.entities)
                    if getattr(e, 'collision_shape', None) is not None
                }
                hits = col.readback_pixel_hits(entities_by_idx)
                col.fire_pixel_callbacks(hits)

            # Scene-wide post-process (M10: operates on intermediate texture when available)
            if (self._scene is not None and self._post_executor is not None and
                    hasattr(self._scene, 'post_process') and self._scene.post_process):
                from slappyengine.post_process.chain import PostProcessChain
                if isinstance(self._scene.post_process, list) and self._scene.post_process:
                    pp_chain = PostProcessChain()
                    for p in self._scene.post_process:
                        pp_chain.add(p)
                    self._post_executor.execute(
                        pp_chain, frame_tex,
                        self._cfg.window.width,
                        self._cfg.window.height,
                    )

            from slappyengine.config import engine_config as _cfg

            # Tick transient lights and compositor transitions
            if self._lighting is not None:
                self._lighting.tick(_cfg().physics.default_dt)
                self._lighting.tick_flash_lights(_cfg().physics.default_dt)
            if self._compositor is not None:
                self._compositor.tick(_cfg().physics.default_dt)

            _render_t0 = time.perf_counter()
            self._gpu.submit(encoder)
            self._render_ms = (time.perf_counter() - _render_t0) * 1000.0

            # Fluid simulation dispatch (runs after frame encoder is submitted so
            # the GPU queue is drained before we schedule new compute work).
            physics_dt = _cfg().physics.default_dt
            if self._fluid_sim is not None:
                self._fluid_sim.dispatch(
                    encoder=None,  # fluid_sim manages its own encoders internally
                    dt=physics_dt,
                    frame_index=self._frame_index,
                )
                # Apply fluid forces to entities that opt in.
                if self._scene is not None:
                    for entity in self._scene.entities:
                        if getattr(entity, 'receives_fluid_forces', False):
                            ex, ey = getattr(entity, 'position', (0.0, 0.0))
                            vx, vy = self._fluid_sim.sample_velocity(ex, ey)
                            cfg_ff = self._fluid_sim.cfg.force_strength
                            if hasattr(entity, 'velocity'):
                                evt = entity.velocity
                                entity.velocity = (
                                    evt[0] + vx * cfg_ff * physics_dt,
                                    evt[1] + vy * cfg_ff * physics_dt,
                                )
                # Keep lighting system's density reference current.
                if self._lighting is not None and hasattr(self._lighting, 'set_fluid_density'):
                    self._lighting.set_fluid_density(self._fluid_sim.density_tex)

            self._frame_index += 1

            # Lighting dispatch — runs AFTER frame encoder is submitted so the
            # rendered scene is visible to copy operations (requires COPY_SRC on surface).
            if self._lighting is not None and self._lighting._lights:
                try:
                    self._lighting.dispatch(frame_tex)
                except Exception:
                    pass  # graceful degradation — lighting unavailable

            if self._scene is not None:
                _update_t0 = time.perf_counter()
                self._scene._tick(_cfg().physics.default_dt)
                self._update_ms = (time.perf_counter() - _update_t0) * 1000.0

            if self._scene is not None and self._residency is not None:
                self._residency.update(
                    self.camera.position,
                    self._scene.entities,
                )

            if self._input is not None:
                self._input.frame_reset()

        if max_frames is None:
            # Live mode — register the draw callback and hand control to the
            # platform event loop until the window is closed.
            canvas.request_draw(_draw)
            try:
                run()
            finally:
                self._shutdown_gpu_resources()
                self._config_manager.stop()
        else:
            # Headless / CI smoke mode — drive the draw callback ``max_frames``
            # times in-process and return.  No event loop, no window blocking.
            if max_frames < 0:
                raise ValueError(
                    f"max_frames must be >= 0, got {max_frames}"
                )
            _frame_budget = (
                1.0 / target_fps if (target_fps is not None and target_fps > 0.0)
                else 0.0
            )
            try:
                for _ in range(max_frames):
                    _tick_start = time.perf_counter()
                    _draw()
                    if _frame_budget > 0.0:
                        _elapsed = time.perf_counter() - _tick_start
                        _sleep = _frame_budget - _elapsed
                        if _sleep > 0.0:
                            time.sleep(_sleep)
            finally:
                self._shutdown_gpu_resources()
                self._config_manager.stop()

    def _shutdown_gpu_resources(self) -> None:
        """Release GPU buffers/textures and clear cached pipelines on exit.

        Idempotent and exception-safe — each step is guarded so partial
        initialisation (e.g. a stub GPU stack in tests) still cleans up
        cleanly.  Called from both the live event-loop and headless paths
        when ``run()`` returns or propagates an exception.
        """
        try:
            if self._buf_mgr is not None:
                self._buf_mgr.destroy_all()
        except Exception:
            pass
        try:
            if self._tex_mgr is not None:
                self._tex_mgr.destroy_all()
        except Exception:
            pass
        # Drop cached 3D-layer renderers / pipeline so a subsequent run() can
        # rebuild them against a fresh GPU context.
        self._mesh_renderers.clear()
        self._mesh_pipeline = None

    # -----------------------------------------------------------------------
    # Project detection helpers
    # -----------------------------------------------------------------------

    def _find_project(self) -> str | None:
        """Look for project.slap_proj in cwd and parent dirs (up to 3 levels).

        Returns the absolute path string if found, or ``None`` if no project
        file is present in any of the searched directories.
        """
        from pathlib import Path
        cwd = Path.cwd()
        for d in [cwd, cwd.parent, cwd.parent.parent]:
            p = d / "project.slap_proj"
            if p.exists():
                return str(p)
        return None

    def _show_project_wizard(self) -> None:
        """Show the pywebview project wizard until a project is created or user cancels.

        Blocks until the pywebview window is closed.  If pywebview is not
        installed, falls back to a plain CLI message so the engine never crashes.
        """
        try:
            import webview
        except ImportError:
            print("No project found. Run: slap new <ProjectName>")
            return

        from pathlib import Path
        from slappyengine.ui.project_manager import ProjectManager

        manager = ProjectManager(engine=self)
        html_path = Path(__file__).parent / "ui" / "project_ui.html"
        manager._window = webview.create_window(
            "SlapPyEngine — Open or Create Project",
            str(html_path) + "?wizard=1",
            js_api=manager._api,
            width=900,
            height=600,
            min_size=(700, 460),
            background_color="#0d0d14",
        )
        webview.start(debug=False)

    def run_editor(self) -> None:
        """Launch the engine in Dear PyGui editor mode.

        If no ``project.slap_proj`` is found in the current working directory
        or its two immediate parents, the pywebview project creation wizard is
        shown first.  The editor opens only after the user selects or creates a
        project.  If the user cancels the wizard without creating a project the
        method returns immediately without opening the editor.

        The wgpu canvas is created for GPU rendering, but the main event loop
        is driven by Dear PyGui rather than wgpu's ``run()``.  On every DPG
        frame the wgpu draw callback is tickled manually so the in-editor
        viewport stays live.

        Raises
        ------
        ImportError
            If ``dearpygui`` is not installed.  Install with::

                pip install SlapPyEngine[editor]
        """
        # --- Project detection (before any DPG window is created) -------
        project_path = self._find_project()
        if project_path is None:
            # No project found — show the wizard so the user can create or open one
            self._show_project_wizard()
            project_path = self._find_project()
            if project_path is None:
                # User cancelled the wizard without creating/opening a project
                return

        # --- Lazy imports (all editor deps are optional) ----------------
        try:
            import dearpygui.dearpygui as dpg  # noqa: F401 (checked here, used below)
        except ImportError as exc:
            raise ImportError(
                "dearpygui is required for the editor mode. "
                "Install it with: pip install SlapPyEngine[editor]"
            ) from exc

        from slappyengine.ui.editor.shell import EditorShell
        from slappyengine.ui.editor.layer_panel import LayerPanel
        from slappyengine.ui.editor.notebook_inspector import NotebookInspector
        from slappyengine.ui.editor.notebook_material_editor import (
            NotebookMaterialEditor,
        )
        from slappyengine.ui.editor.viewport_panel import ViewportPanel

        # TagPainter is a future panel — import gracefully so the editor
        # still works when the module hasn't been written yet.
        try:
            from slappyengine.ui.editor.tag_painter import TagPainter
            _has_tag_painter = True
        except ImportError:
            _has_tag_painter = False

        # BehaviorPanel (AI-assisted scripting) — optional; requires [ai] extra.
        try:
            from slappyengine.ui.editor.behavior_panel import BehaviorPanel
            _has_behavior_panel = True
        except ImportError:
            _has_behavior_panel = False

        # --- GPU setup --------------------------------------------------
        canvas = WgpuCanvas(
            title=self._cfg.window.title,
            size=(self._cfg.window.width, self._cfg.window.height),
        )
        self._setup_gpu(canvas)
        if self._scene is not None:
            self._wire_compute(self._scene)

        # --- Editor shell -----------------------------------------------
        shell = EditorShell(engine=self)

        # --- Panel construction -----------------------------------------
        vp_w, vp_h = self._cfg.window.width, self._cfg.window.height
        layer_panel = LayerPanel()
        property_inspector = NotebookInspector()
        material_editor = NotebookMaterialEditor()
        viewport_panel = ViewportPanel(engine=self, width=vp_w, height=vp_h)

        # Register sidebar panels (order determines display order)
        shell.register_panel(layer_panel)
        shell.register_panel(property_inspector)
        shell.register_panel(material_editor)
        if _has_tag_painter:
            shell.register_panel(TagPainter())  # type: ignore[name-defined]
        if _has_behavior_panel:
            behavior_panel = BehaviorPanel()  # type: ignore[name-defined]
            shell.register_panel(behavior_panel)

        # ViewportPanel occupies the right-hand canvas area
        # shell._on_editor_mode_change forwards to viewport_panel.set_mode()
        # and gizmo_overlay.set_mode() automatically via the toolbar callback.
        shell._viewport_panel = viewport_panel

        # NotebookCodePanel — diary-themed code mode tab
        from slappyengine.ui.editor.notebook_code_panel import NotebookCodePanel
        shell._code_mode_panel = NotebookCodePanel()

        # Build the DPG window layout
        shell.setup()

        # --- Wire content browser → code mode panel ----------------------
        if shell._content_browser is not None and shell._code_mode_panel is not None:
            shell._content_browser.set_on_open_script(
                shell._code_mode_panel.load_script
            )

        # --- Set content browser root to project/cwd ---------------------
        if shell._content_browser is not None:
            import pathlib
            shell._content_browser.set_root(pathlib.Path.cwd())

        # --- Wire scene outliner after setup (outliner auto-created inside setup) --
        if self._scene is not None:
            if shell._scene_outliner is not None:
                shell._scene_outliner.set_scene(self._scene)

        # --- Wire gizmo overlay: camera + outliner selection callback --------
        if shell._gizmo_overlay is not None:
            shell._gizmo_overlay.set_camera(self.camera)
            if shell._scene_outliner is not None:
                # Ensure the outliner selection also notifies the gizmo
                # (set_on_select was already called inside shell.setup; this
                # call is idempotent and handles the case where the outliner
                # was pre-assigned before setup ran).
                shell._scene_outliner.set_on_select(shell._gizmo_overlay.set_entity)

        # --- Pre-populate panels from the loaded scene ------------------
        if self._scene is not None and self._scene.entities:
            layer_panel.set_asset(self._scene.entities[0])
            property_inspector.set_object(self._scene.entities[0])

        # --- Main loop (DPG-driven) -------------------------------------
        import dearpygui.dearpygui as dpg  # already verified above

        while dpg.is_dearpygui_running():
            # Redraw gizmo handles before the DPG frame is rendered.
            if shell._gizmo_overlay is not None:
                shell._gizmo_overlay.update()
            dpg.render_dearpygui_frame()
            # Refresh Code Mode timestamps each frame.
            if shell._code_mode_panel is not None:
                shell._code_mode_panel.update()
            # Manually tick the wgpu draw callback so the viewport stays live.
            if self._gpu is not None:
                try:
                    canvas.draw_frame()
                except Exception:
                    # Canvas may not support draw_frame on all backends;
                    # full async wgpu+DPG integration is a future enhancement.
                    pass

        dpg.destroy_context()
        self._config_manager.stop()

    def open_project_manager(self) -> str:
        """Open the HTML project manager window.

        Blocks until the user selects a project or closes the window.
        Returns the selected project path, or '' if cancelled.

        Requires: pip install SlapPyEngine[editor]
        """
        from slappyengine.ui.project_manager import ProjectManager
        pm = ProjectManager(engine=self)
        pm.show()
        return pm.selected_project

    def launch(self) -> None:
        """Open project manager, then run() if a project/scene was selected.

        Convenience entry point for engine-first workflows::

            engine = Engine()
            engine.launch()
        """
        project_path = self.open_project_manager()
        if project_path and self._scene is not None:
            self.run()

    @property
    def mouse_pos(self) -> tuple[float, float]:
        """Current pointer position in canvas pixels, as ``(x, y)``."""
        return (self._mouse_x, self._mouse_y)

    @property
    def scene(self) -> "Scene | None":
        """The currently loaded scene, or ``None`` if none has been set."""
        return self._scene

    @property
    def device(self) -> wgpu.GPUDevice:
        if self._gpu is None:
            raise RuntimeError("Engine not running — call run() first")
        return self._gpu.device

    @property
    def post_executor(self):
        return self._post_executor

    @property
    def lighting(self) -> "LightingSystem | None":
        return self._lighting

    @property
    def compositor(self) -> "RenderChannelCompositor | None":
        return self._compositor

    @property
    def residency(self) -> "ResidencyManager | None":
        return self._residency

    @property
    def config(self) -> Config:
        return self._cfg

    @property
    def input(self) -> "InputManager | None":
        """The InputManager for keyboard, mouse, and gamepad state, or ``None`` before run()."""
        return self._input

    @property
    def audio(self) -> "AudioManager | None":
        return self._audio

    @property
    def fluid(self) -> "GlobalFluidSim | None":
        """The active fluid simulation, or None if not enabled."""
        return self._fluid_sim

    # -----------------------------------------------------------------------
    # Per-player action-map API
    # -----------------------------------------------------------------------

    def add_player(self, action_map) -> int:
        """Register a player's :class:`~SlapPyEngine.input.ActionMap`.

        Returns the ``player_id`` from the action map.  Players can be added
        before or after :meth:`run`; action dispatch begins as soon as the
        canvas is live.

        Example::

            from slappyengine.input import ActionMap
            engine.add_player(ActionMap.wasd(player_id=0))
            engine.add_player(ActionMap.arrows(player_id=1))
        """
        self._action_maps.append(action_map)
        return action_map.player_id

    @property
    def input_maps(self) -> list:
        """List of registered :class:`~SlapPyEngine.input.ActionMap` objects."""
        return self._action_maps

    def _on_key_down(self, raw_key: str) -> None:
        """Dispatch a key-down event to all registered action maps."""
        if not raw_key or not self._action_maps:
            return
        for am in self._action_maps:
            triggered = am._press(raw_key)
            for action in triggered:
                self._dispatch_action(action, am.player_id, True)

    def _on_key_up(self, raw_key: str) -> None:
        """Dispatch a key-up event to all registered action maps."""
        if not raw_key or not self._action_maps:
            return
        for am in self._action_maps:
            released = am._release(raw_key)
            for action in released:
                self._dispatch_action(action, am.player_id, False)

    def _dispatch_action(self, action: str, player_id: int, pressed: bool) -> None:
        """Call ``on_action(action, player_id, pressed)`` on every script in the scene."""
        if self._scene is None:
            return
        for entity in self._scene.entities:
            for script in getattr(entity, 'scripts', []):
                cb = getattr(script, 'on_action', None)
                if callable(cb):
                    try:
                        cb(action, player_id, pressed)
                    except Exception:
                        pass  # never let a user script crash the engine loop

    # -----------------------------------------------------------------------
    # Split-screen API
    # -----------------------------------------------------------------------

    def enable_split_screen(self, num_players: int,
                             cameras: list | None = None) -> "SplitScreenManager":
        """Enable N-way split-screen rendering.

        Parameters
        ----------
        num_players:
            Number of viewports to create.  Up to 8+ are supported.
        cameras:
            Optional list of :class:`~SlapPyEngine.camera.Camera` instances,
            one per player.  Pass ``None`` for individual cameras and assign
            them later with :meth:`SplitScreenManager.set_camera`.

        Returns
        -------
        SplitScreenManager
            The manager object; also accessible as :attr:`split_screen`.

        Example::

            ss = engine.enable_split_screen(num_players=2,
                                            cameras=[cam_p1, cam_p2])
        """
        from slappyengine.split_screen import SplitScreenManager
        self._split_screen = SplitScreenManager(
            self._cfg.window.width,
            self._cfg.window.height,
            num_players,
            cameras,
        )
        return self._split_screen

    @property
    def split_screen(self) -> "SplitScreenManager | None":
        """The active :class:`~SlapPyEngine.split_screen.SplitScreenManager`,
        or ``None`` when split-screen is not enabled."""
        return self._split_screen

    @property
    def net(self) -> "GameSession | None":
        """The active multiplayer session, or None if not hosting/joined."""
        return self._net_session

    async def host_game(
        self,
        player_id: int = 0,
        cfg: "SessionConfig | None" = None,
    ) -> "GameSession":
        """
        Host a new multiplayer room. Returns session with room_code to share.

        Example::

            session = await engine.host_game(player_id=0)
            print(f"Share this code: {session.room_code}")
        """
        from slappyengine.net.session import GameSession, SessionConfig  # noqa: F401
        self._net_session = await GameSession.host(player_id, cfg)
        return self._net_session

    async def join_game(
        self,
        room_code: str,
        player_id: int = 1,
        cfg: "SessionConfig | None" = None,
    ) -> "GameSession":
        """
        Join an existing multiplayer room by 6-character code.

        Example::

            session = await engine.join_game("X7K2MQ", player_id=1)
        """
        from slappyengine.net.session import GameSession, SessionConfig  # noqa: F401
        self._net_session = await GameSession.join(room_code, player_id, cfg)
        return self._net_session

    def enable_fluid_sim(self, cfg: "FluidSimConfig | None" = None) -> "GlobalFluidSim":
        """Create and initialize the scene-wide fluid simulation.

        Can be called before or after ``run()``.  If called before ``run()``,
        the simulation initializes lazily when the GPU becomes available.

        Parameters
        ----------
        cfg:
            FluidSimConfig instance.  Defaults to FluidSimConfig() (fog-like).

        Returns
        -------
        GlobalFluidSim
            The initialized fluid simulation object.
        """
        from slappyengine.fluid_sim import GlobalFluidSim, FluidSimConfig as _FSC
        _cfg = cfg or _FSC()
        self._fluid_sim = GlobalFluidSim(
            self._gpu, self._cfg.window.width, self._cfg.window.height, _cfg
        )
        if self._gpu is not None:
            self._fluid_sim.initialize()
            # Inform the lighting system so it can wire up god-ray density.
            if self._lighting is not None and hasattr(self._lighting, 'set_fluid_density'):
                self._lighting.set_fluid_density(self._fluid_sim.density_tex)
        return self._fluid_sim

    # -----------------------------------------------------------------------
    # Optional rendering subsystem APIs
    # -----------------------------------------------------------------------

    def enable_ibl(self, hdri_path: str | None = None) -> None:
        """Enable image-based lighting.

        If *hdri_path* is ``None``, a neutral uniform-gray SH is used
        (ambient white irradiance, no specular contribution from an HDRI).

        Safe to call before or after :meth:`run`.  Calling a second time is
        a no-op — the existing IBLSystem is kept.

        Parameters
        ----------
        hdri_path:
            Path to an HDR equirectangular image (e.g. ``"sky.hdr"``).
            Pass ``None`` to use the built-in neutral gray SH.
        """
        if self._ibl is not None:
            return  # idempotent
        from slappyengine.gpu.ibl import IBLSystem
        self._ibl = IBLSystem()
        if self._gpu is not None:
            try:
                self._ibl.init_gpu(
                    self._gpu,
                    self._cfg.window.width,
                    self._cfg.window.height,
                )
                if hdri_path:
                    self._ibl.load_hdri(hdri_path)
            except Exception:
                pass  # graceful degradation — IBL unavailable
        # If called before run(), store the path so _setup_gpu can finish init.
        self._ibl._pending_hdri = hdri_path  # type: ignore[attr-defined]

    def enable_sdf(self) -> None:
        """Enable the 3-pass SDF raymarching renderer.

        Safe to call before or after :meth:`run`.  Calling a second time is
        a no-op — the existing SdfRenderer is kept.

        Use :attr:`sdf` to access the renderer and call
        ``sdf.update_scene(...)`` to populate it with primitives.
        """
        if self._sdf_renderer is not None:
            return  # idempotent
        from slappyengine.gpu.sdf_renderer import SdfRenderer
        try:
            self._sdf_renderer = SdfRenderer(
                self._gpu,
                self._cfg.window.width,
                self._cfg.window.height,
            )
        except Exception:
            pass  # graceful degradation — SDF renderer unavailable

    def enable_cluster_3d(self) -> None:
        """Enable the 3D clustered lighting system.

        Safe to call before or after :meth:`run`.  Calling a second time is
        a no-op — the existing Cluster3DSystem is kept.

        Use :attr:`cluster_3d` to access the system and call
        ``cluster_3d.build_clusters(...)`` / ``cluster_3d.cull_lights(...)``.
        """
        if self._cluster_3d is not None:
            return  # idempotent
        from slappyengine.gpu.cluster_3d import Cluster3DSystem
        try:
            self._cluster_3d = Cluster3DSystem(
                self._gpu,
                self._cfg.window.width,
                self._cfg.window.height,
            )
        except Exception:
            pass  # graceful degradation — cluster system unavailable

    @property
    def ibl(self) -> "IBLSystem | None":
        """The active :class:`~SlapPyEngine.gpu.ibl.IBLSystem`, or ``None``
        when IBL has not been enabled via :meth:`enable_ibl`."""
        return self._ibl

    @property
    def sdf(self) -> "SdfRenderer | None":
        """The active :class:`~SlapPyEngine.gpu.sdf_renderer.SdfRenderer`,
        or ``None`` when SDF rendering has not been enabled via
        :meth:`enable_sdf`."""
        return self._sdf_renderer

    @property
    def cluster_3d(self) -> "Cluster3DSystem | None":
        """The active :class:`~SlapPyEngine.gpu.cluster_3d.Cluster3DSystem`,
        or ``None`` when 3D clustered lighting has not been enabled via
        :meth:`enable_cluster_3d`."""
        return self._cluster_3d

    # -----------------------------------------------------------------------
    # Profiling API (WP-7.7)
    # -----------------------------------------------------------------------

    def profile_frame(self) -> dict:
        """Return frame timing data.

        Returns
        -------
        dict with keys:
            "fps"       : float — current FPS (rolling average over last 60 frames)
            "frame_ms"  : float — last frame duration in milliseconds
            "update_ms" : float — time spent in the scene tick / update callback
            "render_ms" : float — time spent submitting GPU render commands
        """
        return {
            "fps": self._fps if hasattr(self, "_fps") else 0.0,
            "frame_ms": self._last_frame_ms if hasattr(self, "_last_frame_ms") else 0.0,
            "update_ms": getattr(self, "_update_ms", 0.0),
            "render_ms": getattr(self, "_render_ms", 0.0),
        }

    def profile_gpu(self) -> dict:
        """Return GPU adapter info.

        Returns
        -------
        dict with keys:
            "adapter"      : str — adapter name/device
            "backend"      : str — e.g. ``"Vulkan"``, ``"DX12"``
            "adapter_type" : str — e.g. ``"DiscreteGpu"``

        All values fall back to ``"unavailable"`` when the GPU is not yet
        initialised or the backend does not expose the requested field.
        """
        try:
            info = self._gpu.adapter.info
            return {
                "adapter": info.get("device", "unknown"),
                "backend": info.get("backend_type", "unknown"),
                "adapter_type": info.get("adapter_type", "unknown"),
            }
        except Exception:
            return {
                "adapter": "unavailable",
                "backend": "unavailable",
                "adapter_type": "unavailable",
            }
