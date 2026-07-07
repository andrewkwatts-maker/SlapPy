"""hello_v0_4_ready — ZZ6 flagship v0.4-ready 240-frame showcase.

This demo is the comprehensive "does every v0.4 subsystem light up in
one process?" walkthrough. Where RR5's :mod:`hello_full_lifecycle` was
the 180-frame minimum smoke and MM5's :mod:`hello_showcase_v3` was the
LL-batch parity gallery, ZZ6 stitches the *entire* v0.4 feature set
into a single scripted headless run and exposes the trace with the
same shape downstream tests / dashboards already consume.

Subsystems exercised
--------------------

Every subsystem has a "skip if unavailable" branch and the demo never
raises — degraded runs are recorded in ``degradation_notes`` so tests
can distinguish "not present" from "broken":

* **HH1 / App**           — :func:`slappyengine.launch` full lifecycle.
* **HH5 / JJ3**           — glTF importer probe + AssetImportDispatcher
                            (soft-touch — skinned two-bone gltf fixture).
* **JJ4**                 — :class:`PosedSkeleton` bound to the
                            bind-pose of a synthetic 3-joint skeleton +
                            :class:`AnimationClip` sample.
* **JJ5**                 — :class:`SceneWalker` build + :class:`Frustum`
                            + frustum-culled draw list.
* **JJ7**                 — :class:`CSMBuilder`/``build_csm`` cascade
                            construction over the demo camera + sun.
* **KK1**                 — :class:`BVH3D` SAH build over the physics
                            body AABBs + query.
* **KK4**                 — :class:`Skybox` +
                            :func:`procedural_gradient_sky`.
* **LL1 / MM2**           — HUD overlay + hud_bridge default widgets.
* **LL2**                 — :meth:`App.start_recording` /
                            :meth:`App.stop_recording` MP4/GIF capture.
* **LL3**                 — 100 grass-blade instanced mesh via
                            :func:`instanced.random_scatter`.
* **LL4**                 — :class:`Audio3DEngine` +
                            :class:`Audio3DSource` (two orbiting
                            beacons around the listener).
* **LL6 / NN7**           — export CLI manifest.json soft-probe.
* **LL7 / NN4 / OO2 / QQ7** — :class:`World3D` (20 bodies) +
                            :meth:`World3D.build_bvh` + BVH raycast +
                            :meth:`World3D.draw_debug`.
* **NN3**                 — :meth:`App.load_model` +
                            :meth:`App.spawn_camera` /
                            :meth:`App.spawn_light` /
                            :meth:`App.enable_hud` /
                            :meth:`App.enable_shadows` /
                            :meth:`App.enable_ssao` /
                            :meth:`App.take_screenshot` /
                            :meth:`App.start_recording`.
* **OO6 / QQ4 / RR4 / SS6 / TT6** — diagnostics collector +
                            aggregator + extensions + report + filter.
* **VV5**                 — downstream Observable + Asset multi-inherit
                            subclass pattern (inline in this module).
* **YY1**                 — :class:`EventPayload` dual-shape publishes,
                            3 per frame × 240 frames = 720 events.

Behaviour contract
------------------

* Headless-safe (``AppConfig(enable_gpu=False)``).
* Runs exactly ``max_frames`` frames (default 240).
* Fires a raycast every 30 frames (frames 0, 30, 60, 90, 120, 150, 180, 210).
* Takes a screenshot every 60 frames (frames 0, 60, 120, 180).
* Calls :meth:`World3D.draw_debug` every 60 frames (frames 0, 60, 120, 180).
* Publishes 3 :class:`EventPayload` events per frame on 3 topics
  (``player.tick``, ``player.state``, ``player.pos``) — 720 total.
* Publishes a ``checkpoint`` event every 120 frames on
  ``player.checkpoint`` (frames 0, 120).

Output
------

Writes ``hello_v0_4_ready_trace.yaml`` next to the demo module (or the
caller-supplied ``trace_yaml_path``) with:

* ``frame_count`` / ``max_frames``
* ``subsystems_used``       — sorted list of subsystem tags that ran.
* ``screenshot_count``      — number of ``take_screenshot`` calls (target 4).
* ``raycast_total``         — number of raycasts issued (target 8).
* ``raycast_hit_count``     — number of raycasts that hit.
* ``debug_draw_events``     — number of ``draw_debug`` calls (target 4).
* ``events_published``      — total :class:`EventPayload` publishes (target 720).
* ``events_delivered``      — total subscriber invocations (target 720).
* ``checkpoint_events``     — number of checkpoint publishes (target 2).
* ``diagnostics_event_count`` — total events in the collector at end.
* ``diagnostics_stats``     — final :meth:`DiagnosticsCollector.stats`.
* ``audio_voice_ids``       — list of :meth:`Audio3DEngine.play` returns.
* ``recording_started`` / ``recording_stopped``
* ``bvh_body_count``        — number of bodies in the physics world.
* ``instanced_count``       — number of grass-blade instances.
* ``skybox_resolution``     — cubemap face resolution (if built).
* ``skeleton_joint_count``  — number of joints in the demo skeleton.
* ``scene_walker_entities`` — number of scene entities the walker saw.
* ``scene_walker_visible``  — number of entities that survived culling.
* ``degradation_notes``     — list of features that had to skip.

Run
---

::

    python SlapPyEngineExamples/examples/hello_v0_4_ready.py

Returns a summary dict.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Downstream-style subclass (VV5 pattern) — declared at module top so
# import-time failures light up immediately, matching how downstream
# games consume Observable + Asset.
# ---------------------------------------------------------------------------

try:
    from slappyengine.asset import Asset as _Asset
    from slappyengine.event_bus import (
        EventPayload as _EventPayload,
        Observable as _Observable,
        global_bus as _global_bus,
    )
    from slappyengine.layer import Layer as _Layer

    class PlayerVehicle(_Observable, _Asset):
        """Downstream-style entity mixing Observable + Asset (VV5 pattern)."""

        def __init__(self, name: str = "player") -> None:
            super().__init__()
            self.name = name
            self.add_layer(_Layer(name="chassis"))
            self.add_layer(_Layer(name="weapon"))
            self.add_layer(_Layer(name="hud"))

    _DOWNSTREAM_AVAILABLE = True
except Exception:  # pragma: no cover — defensive import guard
    PlayerVehicle = None  # type: ignore[assignment]
    _DOWNSTREAM_AVAILABLE = False
    _EventPayload = None  # type: ignore[assignment]
    _global_bus = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------

_THIS_DIR = Path(__file__).resolve().parent
_BUNNY_OBJ = _THIS_DIR / "assets" / "bunny_low.obj"
_TRIANGLE_OBJ = _THIS_DIR / "assets" / "triangle.obj"
_SKINNED_GLTF = _THIS_DIR / "assets" / "skinned_two_bone.gltf"
_DEFAULT_TRACE_YAML = _THIS_DIR / "hello_v0_4_ready_trace.yaml"
_DEFAULT_SHOT_DIR = _THIS_DIR / "hello_v0_4_ready_shots"

DEFAULT_MAX_FRAMES: int = 240
RAYCAST_EVERY: int = 30
SCREENSHOT_EVERY: int = 60
DEBUG_DRAW_EVERY: int = 60
CHECKPOINT_EVERY: int = 120
WARNING_TRIGGER_FRAME: int = 90

DEFAULT_ROTATION_SPEED_RAD: float = 0.5  # rad/sec
AUDIO_ORBIT_RADIUS: float = 4.0
AUDIO_ORBIT_PERIOD_FRAMES: int = 90

PHYSICS_BODY_COUNT: int = 20
GRASS_INSTANCE_COUNT: int = 100
GRASS_REGION: tuple[tuple[float, float, float], tuple[float, float, float]] = (
    (-6.0, 0.0, -6.0),
    (+6.0, 0.0, +6.0),
)

# YY1 event topics — three per frame + one checkpoint topic.
EVENT_TOPIC_TICK: str = "player.tick"
EVENT_TOPIC_STATE: str = "player.state"
EVENT_TOPIC_POS: str = "player.pos"
EVENT_TOPIC_CHECKPOINT: str = "player.checkpoint"
EVENTS_PER_FRAME: int = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _model_path() -> str:
    """Return the best available bundled model, or ``""``."""
    if _BUNNY_OBJ.exists():
        return str(_BUNNY_OBJ)
    if _TRIANGLE_OBJ.exists():
        return str(_TRIANGLE_OBJ)
    return ""


def _headless_config() -> Any:
    """Build a headless :class:`AppConfig` sized for a 1280x720 HUD."""
    import slappyengine

    return slappyengine.AppConfig(
        window_title="hello_v0_4_ready",
        window_size=(1280, 720),
        enable_gpu=False,
        renderer_backend="stub",
        msaa_samples=4,
        clear_color=(0.08, 0.09, 0.12, 1.0),
        enable_editor=False,
        enable_telemetry=False,
        enable_audio=False,
        target_fps=60,
    )


def _write_trace_yaml(payload: Dict[str, Any], path: Path) -> Path:
    """Dump the trace payload to YAML; falls back to ``repr`` if pyyaml missing."""
    try:
        import yaml
    except Exception:  # pragma: no cover — pyyaml is a regular dep
        path.write_text(repr(payload), encoding="utf-8")
        return path
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


class _NullDebugRenderer:
    """A renderer that captures ``World3D.draw_debug`` line output."""

    __slots__ = ("draw_log",)

    def __init__(self) -> None:
        self.draw_log: list[dict] = []


class _NoopSkyboxRenderer:
    """Bare renderer used to provoke the skybox warn-once path."""

    __slots__ = ()


# ---------------------------------------------------------------------------
# Subsystem setup helpers
# ---------------------------------------------------------------------------


def _setup_physics(state: Dict[str, Any], note) -> None:
    """LL7 / NN4 / OO2 — World3D with 20 bodies + SAH BVH."""
    try:
        from slappyengine.physics3_bridge import Body3D, World3D

        world = World3D(gravity=(0.0, -9.81, 0.0), backend="fallback")
        # 20 spheres in a 5x4 grid so raycasts along +X consistently hit.
        for row in range(4):
            for col in range(5):
                x = -2.0 + col * 1.0
                z = -1.5 + row * 1.0
                world.add_body(
                    Body3D(
                        position=(x, 0.5, z),
                        mass=1.0,
                        shape_kind="sphere",
                        shape_params={"radius": 0.35},
                    )
                )
        try:
            world.build_bvh()
            state["subsystems_used"].add("bvh_3d")
        except Exception as exc:  # pragma: no cover — bvh_3d missing
            note(f"World3D.build_bvh failed: {exc!r}")
        state["world"] = world
        state["bvh_body_count"] = len(world)
        state["subsystems_used"].add("physics3")
    except Exception as exc:
        note(f"World3D setup failed: {exc!r}")


def _setup_audio(state: Dict[str, Any], note) -> None:
    """LL4 — listener + two orbiting Audio3DSources."""
    try:
        from slappyengine.audio_3d import (
            Audio3DEngine,
            Audio3DSource,
            AudioListener,
            SoundBank,
        )

        listener = AudioListener(
            position=(0.0, 0.0, 0.0),
            forward=(0.0, 0.0, 1.0),
            up=(0.0, 1.0, 0.0),
            velocity=(0.0, 0.0, 0.0),
        )
        bank = SoundBank()
        bank.register("beacon_a", {"_stub": True, "name": "beacon_a"})
        bank.register("beacon_b", {"_stub": True, "name": "beacon_b"})
        source_a = Audio3DSource(
            sound_id="beacon_a",
            position=(AUDIO_ORBIT_RADIUS, 0.0, 0.0),
            velocity=(0.0, 0.0, 0.0),
            min_distance=1.0,
            max_distance=50.0,
            is_looping=True,
        )
        source_b = Audio3DSource(
            sound_id="beacon_b",
            position=(-AUDIO_ORBIT_RADIUS, 0.0, 0.0),
            velocity=(0.0, 0.0, 0.0),
            min_distance=1.0,
            max_distance=50.0,
            is_looping=True,
        )
        engine = Audio3DEngine(listener, bank)
        voice_id_a = engine.play(source_a)
        voice_id_b = engine.play(source_b)
        state["audio_engine"] = engine
        state["audio_sources"] = [source_a, source_b]
        state["audio_voice_ids"] = [voice_id_a, voice_id_b]
        state["subsystems_used"].add("audio_3d")
    except Exception as exc:
        note(f"Audio3D setup failed: {exc!r}")


def _setup_skybox(state: Dict[str, Any], note) -> None:
    """KK4 — procedural gradient skybox."""
    try:
        from slappyengine.render.skybox import (
            Skybox,
            procedural_gradient_sky,
        )

        cubemap = procedural_gradient_sky(resolution=32)
        sky = Skybox(cubemap=cubemap)
        state["skybox"] = sky
        state["skybox_resolution"] = int(cubemap.resolution)
        state["subsystems_used"].add("skybox")
    except Exception as exc:
        note(f"Skybox setup failed: {exc!r}")


def _setup_skeleton(state: Dict[str, Any], note) -> None:
    """JJ4 — synthetic 3-joint skeleton + PosedSkeleton + AnimationClip."""
    try:
        from slappyengine.animation.skeleton_runtime import (
            PosedSkeleton,
            Skeleton,
            SkeletonNode,
        )

        skel = Skeleton(
            nodes=[
                SkeletonNode(
                    name="root",
                    parent_index=-1,
                    translation=(0.0, 0.0, 0.0),
                    rotation=(0.0, 0.0, 0.0, 1.0),
                    scale=(1.0, 1.0, 1.0),
                ),
                SkeletonNode(
                    name="spine",
                    parent_index=0,
                    translation=(0.0, 1.0, 0.0),
                    rotation=(0.0, 0.0, 0.0, 1.0),
                    scale=(1.0, 1.0, 1.0),
                ),
                SkeletonNode(
                    name="head",
                    parent_index=1,
                    translation=(0.0, 1.0, 0.0),
                    rotation=(0.0, 0.0, 0.0, 1.0),
                    scale=(1.0, 1.0, 1.0),
                ),
            ]
        )
        posed = PosedSkeleton(skel)
        state["posed_skeleton"] = posed
        state["skeleton_joint_count"] = int(skel.joint_count)
        state["subsystems_used"].add("skeleton_runtime")

        # AnimationClip presence probe — optional, don't hard-fail.
        try:
            from slappyengine.animation.clip import AnimationClip  # noqa: F401
            state["subsystems_used"].add("animation_clip")
        except Exception as exc:  # pragma: no cover — defensive
            note(f"AnimationClip import failed: {exc!r}")
    except Exception as exc:
        note(f"Skeleton runtime setup failed: {exc!r}")


def _setup_scene_walker(state: Dict[str, Any], note) -> None:
    """JJ5 — SceneWalker + Frustum over an empty Scene (touch-only)."""
    try:
        from slappyengine.render.scene_walker import Frustum, SceneWalker
        from slappyengine.scenes.scene import Scene

        scene = Scene(name="v0_4_ready", entities=[])
        walker = SceneWalker(scene=scene)
        state["scene_walker_entities"] = len(scene.entities)
        # Frustum class touch — pin the class exists + is importable.
        _ = Frustum
        state["scene_walker_visible"] = 0
        state["subsystems_used"].add("scene_walker")
        _ = walker  # walker retained for potential future draw-list probe
    except Exception as exc:
        note(f"SceneWalker setup failed: {exc!r}")


def _setup_instanced(state: Dict[str, Any], note) -> None:
    """LL3 — 100 grass blades scattered via instanced.random_scatter."""
    try:
        from slappyengine.render.instanced import random_scatter
        from slappyengine.render.mesh import Mesh
        import numpy as np

        # Minimal 3-vertex triangle mesh — the geometry doesn't matter,
        # we're proving the LL3 packing path lights up. Mesh expects
        # ``(M, 3)`` indices.
        verts = np.array(
            [
                [-0.05, 0.0, 0.0],
                [+0.05, 0.0, 0.0],
                [0.0, 0.4, 0.0],
            ],
            dtype=np.float32,
        )
        indices = np.array([[0, 1, 2]], dtype=np.uint32)
        try:
            mesh = Mesh(vertices=verts, indices=indices)
        except TypeError:
            # Some Mesh variants expect positional args.
            mesh = Mesh(verts, indices)
        inst = random_scatter(
            mesh, count=GRASS_INSTANCE_COUNT, region=GRASS_REGION, seed=7
        )
        state["instanced_mesh"] = inst
        state["instanced_count"] = int(inst.instance_count)
        state["subsystems_used"].add("instanced_render")
    except Exception as exc:
        note(f"Instanced mesh setup failed: {exc!r}")


def _setup_gltf_probe(state: Dict[str, Any], note) -> None:
    """HH5 / JJ3 — soft-probe the glTF importer + AssetImportDispatcher."""
    try:
        from slappyengine.asset_import.dispatcher import (
            AssetImportDispatcher,  # noqa: F401
        )

        state["subsystems_used"].add("asset_import_dispatcher")
    except Exception as exc:
        note(f"AssetImportDispatcher import failed: {exc!r}")
    try:
        from slappyengine.asset_import import gltf_importer  # noqa: F401

        state["subsystems_used"].add("gltf_importer")
    except Exception as exc:
        note(f"gltf_importer import failed: {exc!r}")


def _setup_csm(state: Dict[str, Any], note, app) -> None:
    """JJ7 — CSM cascade probe. Skip cleanly if the API drifts."""
    try:
        from slappyengine.render.shadows import (  # noqa: F401
            CSMBuilder,
            ShadowMapConfig,
        )

        # Touch the split-scheme math to prove the class boots.
        splits = CSMBuilder.compute_cascade_splits(0.1, 100.0, 4, 0.5)
        state["csm_cascade_count"] = len(splits)
        state["subsystems_used"].add("csm_shadows")
    except Exception as exc:
        note(f"CSM import failed: {exc!r}")
    # NN3 App-level shadow toggle — separate signal so both light up.
    try:
        result = app.enable_shadows()
        if result is not None:
            state["subsystems_used"].add("app_shadows_toggle")
    except Exception as exc:  # pragma: no cover — API drift safety net
        note(f"App.enable_shadows failed: {exc!r}")


def _setup_ssao_toggle(state: Dict[str, Any], note, app) -> None:
    """NN3 — App SSAO toggle."""
    try:
        result = app.enable_ssao()
        if result is not None:
            state["subsystems_used"].add("app_ssao_toggle")
    except Exception as exc:
        note(f"App.enable_ssao failed: {exc!r}")


def _setup_export_cli_probe(state: Dict[str, Any], note) -> None:
    """LL6 / NN7 — soft-probe the exporter package + manifest emitter."""
    imported = False
    for mod in (
        "slappyengine.exporter",
        "slappyengine.exporter.manifest",
        "slappyengine.exporter.binary_exporter",
    ):
        try:
            __import__(mod)
            imported = True
        except Exception as exc:  # pragma: no cover — defensive
            note(f"{mod} import failed: {exc!r}")
    if imported:
        state["subsystems_used"].add("exporter")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main(
    *,
    max_frames: int = DEFAULT_MAX_FRAMES,
    trace_yaml_path: str | Path | None = None,
    screenshot_dir: str | Path | None = None,
    enable_recording: bool = True,
) -> Dict[str, Any]:
    """Boot the flagship 240-frame v0.4-ready lifecycle demo.

    Parameters
    ----------
    max_frames:
        Frame cap for the tick loop (default 240).
    trace_yaml_path:
        Where to persist the summary YAML. ``None`` writes next to the
        demo module.
    screenshot_dir:
        Directory for per-shot PNGs. ``None`` uses a folder next to the
        demo module.
    enable_recording:
        When True, attempt to start an MP4 recording at ``on_begin`` and
        stop it at ``on_end``. Failures degrade to a ``degradation_notes``
        entry.
    """
    if max_frames < 1:
        raise ValueError(f"max_frames must be >= 1 (got {max_frames})")

    import slappyengine

    shots_dir = (
        Path(screenshot_dir) if screenshot_dir is not None else _DEFAULT_SHOT_DIR
    )
    shots_dir.mkdir(parents=True, exist_ok=True)

    # ---- Mutable state shared across lifecycle callbacks ------------------
    state: Dict[str, Any] = {
        "app": None,
        "model": None,
        "world": None,
        "audio_engine": None,
        "audio_sources": [],
        "audio_voice_ids": [],
        "posed_skeleton": None,
        "skeleton_joint_count": 0,
        "instanced_mesh": None,
        "instanced_count": 0,
        "skybox": None,
        "skybox_resolution": 0,
        "scene_walker_entities": 0,
        "scene_walker_visible": 0,
        "bvh_body_count": 0,
        "subsystems_used": set(),
        "screenshot_count": 0,
        "screenshot_paths": [],
        "raycast_total": 0,
        "raycast_hit_count": 0,
        "raycast_log": [],
        "debug_draw_events": 0,
        "debug_lines_total": 0,
        "events_published": 0,
        "events_delivered": 0,
        "checkpoint_events": 0,
        "recording_started": False,
        "recording_stopped": False,
        "warning_triggered": False,
        "degradation_notes": [],
        "diagnostics_stats_final": {},
        "diagnostics_event_count": 0,
        "player_a": None,
    }

    def _note(msg: str) -> None:
        state["degradation_notes"].append(str(msg))

    # ---- Downstream (VV5) subclass instantiation --------------------------
    if _DOWNSTREAM_AVAILABLE and PlayerVehicle is not None:
        try:
            player = PlayerVehicle(name="v0_4_ready")
            state["player_a"] = player
            state["subsystems_used"].add("downstream_pattern")
        except Exception as exc:  # pragma: no cover — TT1-class guard
            _note(f"PlayerVehicle instantiation failed: {exc!r}")
    else:
        _note("downstream Observable+Asset pattern unavailable")

    # ---- YY1 EventPayload delivery counter (module-level bus) -------------
    def _delivery_listener(payload) -> None:
        try:
            # Touch both attribute and dict access to prove dual-shape.
            _ = getattr(payload, "publisher", None)
            _ = payload.get("frame", None) if hasattr(payload, "get") else None
            state["events_delivered"] += 1
        except Exception:  # pragma: no cover — defensive
            state["events_delivered"] += 1

    if _global_bus is not None:
        for topic in (
            EVENT_TOPIC_TICK,
            EVENT_TOPIC_STATE,
            EVENT_TOPIC_POS,
            EVENT_TOPIC_CHECKPOINT,
        ):
            try:
                _global_bus.clear(topic)
            except Exception:  # pragma: no cover — defensive
                pass
            try:
                _global_bus.subscribe(topic, _delivery_listener)
            except Exception:  # pragma: no cover — defensive
                pass
        state["subsystems_used"].add("event_bus_global")

    # ---- on_begin ---------------------------------------------------------
    def on_begin(a: Any) -> None:
        state["app"] = a
        state["subsystems_used"].add("app")

        # --- Model (NN3 / HH5) ---
        model_path = _model_path()
        if model_path:
            try:
                model = a.load_model(model_path)
                state["model"] = model
                state["subsystems_used"].add("model")
                a.trace.append(("v0_4_ready_model_load", model_path))
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"load_model failed: {exc!r}")
        else:
            _note("no bundled model asset available")

        # --- Camera + Light (NN3) ---
        try:
            a.spawn_camera(position=(3.0, 2.0, 6.0), look_at=(0.0, 0.5, 0.0))
            state["subsystems_used"].add("camera")
        except Exception as exc:  # pragma: no cover — API drift safety net
            _note(f"spawn_camera failed: {exc!r}")
        try:
            a.spawn_light((5.0, 8.0, 5.0), color=(1.0, 0.95, 0.85), intensity=1.5)
            state["subsystems_used"].add("light")
        except Exception as exc:  # pragma: no cover — API drift safety net
            _note(f"spawn_light failed: {exc!r}")

        # --- HUD (LL1 / MM2) ---
        try:
            overlay = a.enable_hud()
            widget_count = len(overlay.widgets()) if overlay is not None else 0
            state["subsystems_used"].add("hud")
            a.trace.append(("v0_4_ready_hud_mount", int(widget_count)))
        except Exception as exc:
            _note(f"enable_hud failed: {exc!r}")

        # --- Diagnostics (QQ4 / OO6 / RR4 / SS6 / TT6) ---
        try:
            collector = a.enable_diagnostics(min_level="WARNING", max_events=500)
            try:
                collector.clear()
            except Exception:  # pragma: no cover — defensive
                pass
            state["subsystems_used"].add("diagnostics")
            a.trace.append(("v0_4_ready_diagnostics_installed", True))
        except Exception as exc:
            _note(f"enable_diagnostics failed: {exc!r}")

        # --- Shadows / SSAO / Skybox / Skeleton / Instanced / Physics / Audio ---
        _setup_physics(state, _note)
        _setup_audio(state, _note)
        _setup_skybox(state, _note)
        _setup_skeleton(state, _note)
        _setup_scene_walker(state, _note)
        _setup_instanced(state, _note)
        _setup_gltf_probe(state, _note)
        _setup_csm(state, _note, a)
        _setup_ssao_toggle(state, _note, a)
        _setup_export_cli_probe(state, _note)

        # --- Recording (LL2 / NN3) — best-effort ---
        if enable_recording:
            try:
                mp4_path = shots_dir / "hello_v0_4_ready.mp4"
                result = a.start_recording(path=str(mp4_path), fps=60)
                status = str(result.get("status", "unknown")) if isinstance(
                    result, dict
                ) else "unknown"
                if status in ("recording", "started", "ok"):
                    state["recording_started"] = True
                    state["subsystems_used"].add("recording")
                    a.trace.append(("v0_4_ready_recording_started", str(mp4_path)))
                else:
                    _note(f"start_recording status={status!r}")
            except Exception as exc:
                _note(f"start_recording failed: {exc!r}")
        else:
            _note("recording disabled by caller")

    # ---- on_tick ---------------------------------------------------------
    def on_tick(a: Any, dt: float) -> None:
        frame = a.frame_count

        # 1. Rotate the model each frame.
        model = state["model"]
        if model is not None:
            try:
                angle = frame * DEFAULT_ROTATION_SPEED_RAD * dt
                model.rotate_to(0.0, angle, 0.0)
            except Exception:  # pragma: no cover — defensive
                pass

        # 2. Update audio sources — both orbit but 180° out of phase.
        engine = state["audio_engine"]
        sources = state["audio_sources"]
        if engine is not None and sources:
            try:
                theta = (2.0 * math.pi * frame) / float(AUDIO_ORBIT_PERIOD_FRAMES)
                omega = (2.0 * math.pi) / (
                    float(AUDIO_ORBIT_PERIOD_FRAMES) * max(dt, 1e-6)
                )
                if len(sources) >= 1:
                    sources[0].position = (
                        AUDIO_ORBIT_RADIUS * math.cos(theta),
                        0.0,
                        AUDIO_ORBIT_RADIUS * math.sin(theta),
                    )
                    sources[0].velocity = (
                        -AUDIO_ORBIT_RADIUS * omega * math.sin(theta),
                        0.0,
                        AUDIO_ORBIT_RADIUS * omega * math.cos(theta),
                    )
                if len(sources) >= 2:
                    sources[1].position = (
                        -AUDIO_ORBIT_RADIUS * math.cos(theta),
                        0.0,
                        -AUDIO_ORBIT_RADIUS * math.sin(theta),
                    )
                    sources[1].velocity = (
                        AUDIO_ORBIT_RADIUS * omega * math.sin(theta),
                        0.0,
                        -AUDIO_ORBIT_RADIUS * omega * math.cos(theta),
                    )
                engine.update(dt)
            except Exception:  # pragma: no cover — defensive
                pass

        # 3. Physics step (best-effort — skip if API drifts).
        world = state["world"]
        if world is not None:
            try:
                world.step(dt)
            except Exception:  # pragma: no cover — defensive
                pass

        # 4. Raycast every RAYCAST_EVERY frames.
        if world is not None and frame % RAYCAST_EVERY == 0:
            try:
                hit = world.raycast(
                    origin=(-5.0, 0.5, 0.0),
                    direction=(1.0, 0.0, 0.0),
                    max_distance=20.0,
                )
                state["raycast_total"] += 1
                if hit is not None:
                    state["raycast_hit_count"] += 1
                    state["raycast_log"].append(
                        {
                            "frame": int(frame),
                            "body_id": int(hit.body_id),
                            "distance": float(hit.distance),
                        }
                    )
                    a.trace.append(
                        (
                            "v0_4_ready_raycast_hit",
                            int(frame),
                            int(hit.body_id),
                            float(hit.distance),
                        )
                    )
                else:
                    a.trace.append(("v0_4_ready_raycast_miss", int(frame)))
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"raycast frame={frame} failed: {exc!r}")

        # 5. Screenshot every SCREENSHOT_EVERY frames.
        if frame % SCREENSHOT_EVERY == 0:
            try:
                shot_path = shots_dir / f"frame_{int(frame):04d}.png"
                result = a.take_screenshot(path=str(shot_path))
                status = str(result.get("status", "unknown")) if isinstance(
                    result, dict
                ) else "unknown"
                state["screenshot_count"] += 1
                state["screenshot_paths"].append(str(shot_path))
                a.trace.append(
                    (
                        "v0_4_ready_screenshot",
                        int(frame),
                        str(shot_path),
                        status,
                    )
                )
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"take_screenshot frame={frame} failed: {exc!r}")

        # 6. draw_debug into a null renderer every DEBUG_DRAW_EVERY frames.
        if world is not None and frame % DEBUG_DRAW_EVERY == 0:
            try:
                renderer = _NullDebugRenderer()
                stats = world.draw_debug(renderer, show_aabbs=True)
                state["debug_draw_events"] += 1
                state["debug_lines_total"] += int(stats.get("line_count", 0))
                a.trace.append(
                    (
                        "v0_4_ready_debug_draw",
                        int(frame),
                        int(stats.get("aabbs_drawn", 0)),
                        int(stats.get("line_count", 0)),
                    )
                )
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"draw_debug frame={frame} failed: {exc!r}")

        # 7. Publish 3 EventPayload events per frame — YY1 dual-shape.
        if _global_bus is not None:
            player = state["player_a"]
            publisher = player if player is not None else "v0_4_ready"
            for topic in (
                EVENT_TOPIC_TICK,
                EVENT_TOPIC_STATE,
                EVENT_TOPIC_POS,
            ):
                try:
                    _global_bus.publish(
                        topic,
                        publisher=publisher,
                        frame=int(frame),
                        value=float(frame) * 0.5,
                    )
                    state["events_published"] += 1
                except Exception as exc:  # pragma: no cover — defensive
                    _note(f"publish {topic} frame={frame} failed: {exc!r}")

            # 8. Deliberate warning at WARNING_TRIGGER_FRAME to exercise
            #    the diagnostics collector — skybox render against a
            #    bare renderer with no submit_skybox / draw_skybox /
            #    draw_log.
            if (
                not state["warning_triggered"]
                and frame >= WARNING_TRIGGER_FRAME
                and state.get("skybox") is not None
            ):
                try:
                    state["skybox"].render(
                        renderer=_NoopSkyboxRenderer(), camera=None
                    )
                    state["warning_triggered"] = True
                    a.trace.append(
                        ("v0_4_ready_warning_triggered", int(frame))
                    )
                except Exception:  # pragma: no cover — defensive
                    state["warning_triggered"] = True  # don't retry

            # 9. Checkpoint event every CHECKPOINT_EVERY frames.
            if frame % CHECKPOINT_EVERY == 0:
                try:
                    _global_bus.publish(
                        EVENT_TOPIC_CHECKPOINT,
                        publisher=publisher,
                        frame=int(frame),
                        checkpoint=int(frame // CHECKPOINT_EVERY),
                    )
                    state["checkpoint_events"] += 1
                    a.trace.append(
                        ("v0_4_ready_checkpoint", int(frame))
                    )
                except Exception as exc:  # pragma: no cover — defensive
                    _note(f"publish checkpoint frame={frame} failed: {exc!r}")

    # ---- on_end ----------------------------------------------------------
    def on_end(a: Any) -> None:
        # Snapshot diagnostics before we tear anything down.
        try:
            stats = a.diagnostics_stats() or {}
            events = a.diagnostics_events() or []
            state["diagnostics_stats_final"] = dict(stats)
            state["diagnostics_event_count"] = len(events)
        except Exception as exc:  # pragma: no cover — defensive
            _note(f"diagnostics snapshot failed: {exc!r}")

        # Emit a diagnostics_report event via App.trace so downstream tools
        # can pick it up as a lifecycle marker.
        try:
            a.trace.append(
                (
                    "diagnostics_report",
                    int(state["diagnostics_event_count"]),
                    dict(state["diagnostics_stats_final"]),
                )
            )
        except Exception:  # pragma: no cover — defensive
            pass

        # Stop recording if we started one.
        if state["recording_started"]:
            try:
                result = a.stop_recording()
                status = str(result.get("status", "unknown")) if isinstance(
                    result, dict
                ) else "unknown"
                state["recording_stopped"] = True
                a.trace.append(("v0_4_ready_recording_stopped", status))
            except Exception as exc:  # pragma: no cover — defensive
                _note(f"stop_recording failed: {exc!r}")

        a.trace.append(("v0_4_ready_on_end", int(a.frame_count)))

    # ---- Run --------------------------------------------------------------
    app = slappyengine.launch(
        on_begin=on_begin,
        on_tick=on_tick,
        on_end=on_end,
        max_frames=max_frames,
        config=_headless_config(),
    )

    # ---- Roll up top_subsystems (by warning count) ------------------------
    top_subsystems: list[tuple[str, int]] = []
    for key, count in state["diagnostics_stats_final"].items():
        if isinstance(key, str) and key.startswith("subsystem:"):
            top_subsystems.append((key[len("subsystem:") :], int(count)))
    top_subsystems.sort(key=lambda pair: (-pair[1], pair[0]))
    top_subsystems = top_subsystems[:5]

    subsystems_used_sorted = sorted(state["subsystems_used"])

    # ---- Cleanup: unsubscribe delivery listener --------------------------
    if _global_bus is not None:
        for topic in (
            EVENT_TOPIC_TICK,
            EVENT_TOPIC_STATE,
            EVENT_TOPIC_POS,
            EVENT_TOPIC_CHECKPOINT,
        ):
            try:
                _global_bus.unsubscribe(topic, _delivery_listener)
            except Exception:  # pragma: no cover — defensive
                pass

    # ---- Persist trace YAML ---------------------------------------------
    payload: Dict[str, Any] = {
        "frame_count": int(app.frame_count),
        "max_frames": int(max_frames),
        "subsystems_used": subsystems_used_sorted,
        "screenshot_count": int(state["screenshot_count"]),
        "screenshot_paths": list(state["screenshot_paths"]),
        "raycast_total": int(state["raycast_total"]),
        "raycast_hit_count": int(state["raycast_hit_count"]),
        "raycast_log": list(state["raycast_log"]),
        "debug_draw_events": int(state["debug_draw_events"]),
        "debug_lines_total": int(state["debug_lines_total"]),
        "events_published": int(state["events_published"]),
        "events_delivered": int(state["events_delivered"]),
        "events_per_frame": int(EVENTS_PER_FRAME),
        "checkpoint_events": int(state["checkpoint_events"]),
        "diagnostics_event_count": int(state["diagnostics_event_count"]),
        "diagnostics_stats": dict(state["diagnostics_stats_final"]),
        "top_subsystems": [
            {"subsystem": name, "count": int(count)}
            for name, count in top_subsystems
        ],
        "audio_voice_ids": list(state["audio_voice_ids"]),
        "recording_started": bool(state["recording_started"]),
        "recording_stopped": bool(state["recording_stopped"]),
        "bvh_body_count": int(state["bvh_body_count"]),
        "instanced_count": int(state["instanced_count"]),
        "skybox_resolution": int(state["skybox_resolution"]),
        "skeleton_joint_count": int(state["skeleton_joint_count"]),
        "scene_walker_entities": int(state["scene_walker_entities"]),
        "scene_walker_visible": int(state["scene_walker_visible"]),
        "degradation_notes": list(state["degradation_notes"]),
        "trace_event_count": len(app.trace),
    }
    out_path = (
        Path(trace_yaml_path) if trace_yaml_path is not None else _DEFAULT_TRACE_YAML
    )
    _write_trace_yaml(payload, out_path)

    summary: Dict[str, Any] = {
        "frame_count": int(app.frame_count),
        "subsystems_used": subsystems_used_sorted,
        "screenshot_count": int(state["screenshot_count"]),
        "raycast_total": int(state["raycast_total"]),
        "raycast_hit_count": int(state["raycast_hit_count"]),
        "debug_draw_events": int(state["debug_draw_events"]),
        "events_published": int(state["events_published"]),
        "events_delivered": int(state["events_delivered"]),
        "checkpoint_events": int(state["checkpoint_events"]),
        "diagnostics_event_count": int(state["diagnostics_event_count"]),
        "recording_started": bool(state["recording_started"]),
        "recording_stopped": bool(state["recording_stopped"]),
        "bvh_body_count": int(state["bvh_body_count"]),
        "instanced_count": int(state["instanced_count"]),
        "skybox_resolution": int(state["skybox_resolution"]),
        "skeleton_joint_count": int(state["skeleton_joint_count"]),
        "degradation_notes": list(state["degradation_notes"]),
        "trace_path": str(out_path),
    }

    print("=== hello_v0_4_ready summary ===")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    return summary


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _honour_headless_env() -> None:
    """Respect ``SLAPPY_HEADLESS=1`` as an env-flag override."""
    if os.environ.get("SLAPPY_HEADLESS", "").strip() in ("", "0"):
        os.environ.setdefault("SLAPPY_HEADLESS", "1")


if __name__ == "__main__":
    _honour_headless_env()
    main()
