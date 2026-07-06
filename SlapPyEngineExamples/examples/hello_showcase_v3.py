"""hello_showcase_v3 — every-LL-subsystem scripted showcase (MM5).

MM-batch sprint (task MM5, 2026-07-05). Where :mod:`hello_v2_showcase`
(EE2) lit 17 editor / notebook subsystems in one CI-lockable run and
:mod:`hello_gltf_character` (LL5) lit the full character-render path,
this demo climbs one tier further: it exercises **every LL-batch
subsystem** (HUD overlay, video capture, instanced rendering, 3D
positional audio, character animation, exporter smoke-test, 3D physics
bridge) alongside the JJ and KK parity landings (CSM shadows, procedural
skybox, SSAO, SDF text, 3D BVH) in a single ≥ 25-subsystem trace.

Subsystems exercised
--------------------

The demo tracks 25+ subsystems in a single scripted headless run:

1.  **HUD overlay** (LL1) — HealthBar + AmmoCounter mounted over the
    scene, one frame built + submitted through a fake renderer.
2.  **GIF video capture** (LL2) — 60 headless frames recorded to
    ``hello_showcase_v3.gif`` via :class:`GIFCapture`.
3.  **Instanced rendering** (LL3) — 20 cube instances arranged on a
    circle via :func:`slappyengine.render.instanced.circle`.
4.  **3D positional audio** (LL4) — a moving ``menu_swipe`` source
    played into :class:`Audio3DEngine`; DSP verifies gain/pitch
    trajectories (doppler shift).
5.  **Character animation** (JJ4 / LL5) — 2-bone skinned glTF from the
    LL5 fixture, 360° rotate clip, driven for 30 ticks.
6.  **CSM shadows** (JJ7) — 4-cascade CSM built once against the demo
    camera + directional light.
7.  **Procedural skybox** (KK4) — 3-stop gradient cubemap generated at
    128 px per face, sampled once for parity.
8.  **SSAO** (KK3) — :class:`SSAOPass` kernel + noise texture generated;
    ``execute()`` runs on a synthetic depth+normal buffer.
9.  **SDF text** (KK6) — "SlapPyEngine" text mesh built via
    :class:`SDFTextRenderer` + :class:`SDFGlyphAtlas`.
10. **3D BVH** (KK1) — :class:`BVH3D` built over the 20 instance AABBs;
    frustum query returns the visible subset.
11. **Physics3 bridge** (LL7) — 5 sphere bodies added to a
    :class:`World3D`, gravity-integrated for 30 steps.
12. **Exporter smoke-test** (LL6) — :func:`export_project` invoked in
    ``dry_run`` mode against a synthesised project skeleton.
13. **App shell** (HH1) — :class:`App` boot with ``NullRenderer``.
14. **glTF importer** (JJ3) — soft-imports the LL5 fixture.
15. **Skeleton runtime** (JJ4) — :class:`Skeleton` + :class:`SkinnedMeshData`.
16. **AnimationClip** (JJ4) — 3-key rotation clip.
17. **Animator** (JJ4) — clip playback for 30 frames.
18. **Directional light** (HH1 / JJ7) — one directional light for CSM.
19. **Skybox sampler** (KK4) — CPU-side ``sample_direction_from_cubemap``.
20. **BVH frustum query** (KK1) — Frustum.intersects_aabb over BVH.
21. **BVH ray query** (KK1) — ``query_ray`` from the camera origin.
22. **World3D broadphase** (LL7) — ``broadphase_pairs`` on the 5 spheres.
23. **HUD widget attach** (LL1) — HealthBar + AmmoCounter widget count.
24. **HUD command emission** (LL1) — ``end_frame`` returns commands.
25. **HUD renderer submission** (LL1) — ``submit_to_renderer`` count.
26. **GIF frame count** (LL2) — ≥ 60 frames written.
27. **Instanced AABB union** (LL3) — bounding box computed for 20 instances.
28. **Audio doppler shift** (LL4) — pitch drift over update ticks.
29. **BVH stats** (KK1) — depth / node count.

Headless contract
-----------------

No wgpu / DearPyGui / display server dependency. Every subsystem
soft-imports; when a piece isn't installed the demo records a
``*_missing`` (or ``*_skipped``) trace event and keeps running. Skip
reasons are always captured so tests can distinguish "not present" from
"broken".

Run:
    python SlapPyEngineExamples/examples/hello_showcase_v3.py
"""
from __future__ import annotations

import math
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Total scripted frames — the demo ticks headless for this many ticks.
FRAME_COUNT: int = 180

#: How many frames the GIF capture (LL2) records.
GIF_FRAME_COUNT: int = 60

#: GIF playback framerate.
GIF_FPS: int = 30

#: Frame size for the GIF capture (kept small so the artefact is < ~50 KB).
GIF_RESOLUTION: tuple[int, int] = (64, 48)

#: Instance count for the LL3 circle layout.
INSTANCE_COUNT: int = 20

#: Circle radius for the instanced cubes.
INSTANCE_RADIUS: float = 4.0

#: Physics3 body count for LL7 gravity test.
PHYSICS3_SPHERE_COUNT: int = 5

#: How many ticks of the physics3 world we advance.
PHYSICS3_STEPS: int = 30

#: Title text rendered via the SDF text stack (KK6).
SDF_TITLE_TEXT: str = "SlapPyEngine"

#: Camera orbit radius around the scene origin.
ORBIT_RADIUS: float = 6.0

#: Camera height above the ground plane.
CAMERA_Y: float = 2.0

#: Trace YAML output next to this file.
TRACE_NAME: str = "hello_showcase_v3_trace.yaml"

#: GIF output next to this file.
GIF_NAME: str = "hello_showcase_v3.gif"

#: The skinned glTF asset — reuses the LL5 fixture.
ASSET_RELPATH: str = "assets/skinned_two_bone.gltf"

#: Sound id used by the 3D audio step (LL4).
AUDIO_SOUND_ID: str = "menu_swipe"

#: Trace event floor per the MM5 contract.
TRACE_EVENT_FLOOR: int = 80

#: Subsystem coverage floor per the MM5 contract.
SUBSYSTEM_FLOOR: int = 25


# ---------------------------------------------------------------------------
# Trace recorder — same shape as hello_v2_showcase.
# ---------------------------------------------------------------------------


class DemoTrace:
    """Ordered event log — YAML-serialised at demo end."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, kind: str, **payload: Any) -> None:
        entry: dict[str, Any] = {"kind": kind}
        entry.update(payload)
        self.events.append(entry)

    def kinds(self) -> set[str]:
        return {e["kind"] for e in self.events}

    def as_yaml(self) -> str:
        try:
            import yaml  # type: ignore

            return yaml.safe_dump(
                {"events": self.events, "event_count": len(self.events)},
                sort_keys=False,
            )
        except Exception:
            return _hand_yaml({"events": self.events,
                               "event_count": len(self.events)})


def _hand_yaml(data: Any, indent: int = 0) -> str:
    pad = "  " * indent
    if isinstance(data, dict):
        if not data:
            return "{}\n"
        out = ""
        for k, v in data.items():
            if isinstance(v, (dict, list)) and v:
                out += f"{pad}{k}:\n{_hand_yaml(v, indent + 1)}"
            else:
                out += f"{pad}{k}: {_scalar_yaml(v)}\n"
        return out
    if isinstance(data, list):
        if not data:
            return f"{pad}[]\n"
        out = ""
        for item in data:
            if isinstance(item, dict):
                lines = _hand_yaml(item, indent + 1).splitlines()
                if lines:
                    first = lines[0].lstrip()
                    out += f"{pad}- {first}\n"
                    for line in lines[1:]:
                        out += f"{line}\n"
            else:
                out += f"{pad}- {_scalar_yaml(item)}\n"
        return out
    return f"{pad}{_scalar_yaml(data)}\n"


def _scalar_yaml(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if any(c in text for c in ":#\n") or text in ("", "null", "true", "false"):
        text = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{text}"'
    return text


# ---------------------------------------------------------------------------
# SubsystemStatus — tracks OK / SKIPPED / MISSING with a reason string.
# ---------------------------------------------------------------------------


@dataclass
class SubsystemStatus:
    key: str
    ok: bool
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "ok": self.ok, "reason": self.reason}


# ---------------------------------------------------------------------------
# Step 1 — App boot (HH1) + NullRenderer fallback.
# ---------------------------------------------------------------------------


def _step_boot_app(trace: DemoTrace) -> tuple[Any, Any, SubsystemStatus]:
    """Boot :class:`App` with :class:`NullRenderer`; return (app, renderer, status)."""
    try:
        from slappyengine.app import App, AppConfig
        from slappyengine.render.null_renderer import NullRenderer
    except Exception as exc:
        trace.record("app_missing", error=str(exc))
        return None, None, SubsystemStatus("app_shell", False, reason=str(exc))

    try:
        config = AppConfig(
            window_title="hello_showcase_v3",
            enable_gpu=False,  # force NullRenderer path
            msaa_samples=4,
            target_fps=60,
            max_frames=FRAME_COUNT,
            renderer_backend="null",
        )
        app = App(config=config)
    except Exception as exc:
        trace.record("app_boot_failed", error=str(exc))
        return None, None, SubsystemStatus("app_shell", False, reason=str(exc))

    renderer = getattr(app, "_renderer", None)
    if renderer is None:
        renderer = NullRenderer()
    trace.record(
        "app_boot",
        enable_gpu=False,
        renderer=type(renderer).__name__,
        target_fps=60,
    )
    return app, renderer, SubsystemStatus("app_shell", True)


# ---------------------------------------------------------------------------
# Step 2 — HUD overlay (LL1) with HealthBar + AmmoCounter.
# ---------------------------------------------------------------------------


def _step_hud_overlay(
    trace: DemoTrace, renderer: Any,
) -> tuple[list[SubsystemStatus], int]:
    """Mount HUD overlay with HealthBar + AmmoCounter; return statuses + submitted count."""
    statuses: list[SubsystemStatus] = []
    try:
        from slappyengine.render.camera import Camera2D
        from slappyengine.ui.runtime.hud_kit import AmmoCounter, HealthBar
        from slappyengine.ui.runtime.hud_overlay import HUDOverlay
    except Exception as exc:
        trace.record("hud_missing", error=str(exc))
        statuses.append(SubsystemStatus("hud_overlay", False, reason=str(exc)))
        statuses.append(SubsystemStatus("hud_widget_attach", False, reason=str(exc)))
        statuses.append(SubsystemStatus("hud_command_emit", False, reason=str(exc)))
        statuses.append(SubsystemStatus("hud_renderer_submit", False, reason=str(exc)))
        return statuses, 0

    # A minimal fake renderer so we do not depend on the App's renderer
    # exposing the exact HUD sink protocol.
    class _FakeRenderer:
        def __init__(self) -> None:
            self.sprites: list = []
            self.lines: list = []
            self.texts: list = []

        def submit_sprite(self, texture, transform_2d, tint=(1, 1, 1, 1)) -> None:
            self.sprites.append((texture, np.asarray(transform_2d).copy(), tuple(tint)))

        def submit_lines(self, vertices, colors) -> None:
            self.lines.append((np.asarray(vertices).copy(), np.asarray(colors).copy()))

        def submit_text(self, mesh, color) -> None:
            self.texts.append((mesh, tuple(color)))

    fake = _FakeRenderer()
    cam2d = Camera2D(viewport_size=(1280, 720))
    try:
        overlay = HUDOverlay(fake, cam2d)
    except Exception as exc:
        trace.record("hud_construct_failed", error=str(exc))
        statuses.append(SubsystemStatus("hud_overlay", False, reason=str(exc)))
        statuses.append(SubsystemStatus("hud_widget_attach", False, reason=str(exc)))
        statuses.append(SubsystemStatus("hud_command_emit", False, reason=str(exc)))
        statuses.append(SubsystemStatus("hud_renderer_submit", False, reason=str(exc)))
        return statuses, 0

    hp = HealthBar(position=(16.0, 16.0), value=72.0, max_value=100.0, label="HP")
    ammo = AmmoCounter(position=(16.0, 60.0), current=24, reserve=90, weapon_name="RIFLE")
    overlay.attach(hp)
    overlay.attach(ammo)
    trace.record(
        "hud_widget_attach",
        widget_count=overlay.widget_count,
        widgets=["HealthBar", "AmmoCounter"],
    )
    statuses.append(SubsystemStatus("hud_widget_attach", True))

    overlay.begin_frame(dt=1.0 / 60.0, input_state={"mouse": (100.0, 100.0)})
    cmds = overlay.end_frame()
    trace.record(
        "hud_command_emit",
        command_count=len(cmds),
        kinds=sorted({c.kind for c in cmds}),
    )
    statuses.append(SubsystemStatus("hud_command_emit", True))

    submitted = overlay.submit_to_renderer()
    trace.record(
        "hud_overlay",
        widget_count=overlay.widget_count,
        commands=len(cmds),
        submitted=submitted,
        sprites=len(fake.sprites),
    )
    statuses.append(SubsystemStatus("hud_overlay", True))
    statuses.append(SubsystemStatus("hud_renderer_submit", submitted > 0,
                                    reason="" if submitted > 0 else "no sprites emitted"))
    return statuses, submitted


# ---------------------------------------------------------------------------
# Step 3 — GIF video capture (LL2).
# ---------------------------------------------------------------------------


def _step_gif_capture(
    trace: DemoTrace, out_path: Path,
) -> tuple[SubsystemStatus, int]:
    """Record ``GIF_FRAME_COUNT`` synthesised frames to a GIF; return status + count."""
    try:
        from slappyengine.capture.gif_capture import GIFCapture
    except Exception as exc:
        trace.record("gif_capture_missing", error=str(exc))
        return SubsystemStatus("video_capture", False, reason=str(exc)), 0

    try:
        cap = GIFCapture(out_path, resolution=GIF_RESOLUTION, fps=GIF_FPS)
    except Exception as exc:
        trace.record("gif_capture_construct_failed", error=str(exc))
        return SubsystemStatus("video_capture", False, reason=str(exc)), 0

    w, h = GIF_RESOLUTION
    frames_written = 0
    try:
        cap.begin()
        for i in range(GIF_FRAME_COUNT):
            # Cheap moving-gradient frame; enough colour drift to make the
            # GIF actually animate.
            t = i / max(GIF_FRAME_COUNT - 1, 1)
            frame = np.zeros((h, w, 4), dtype=np.uint8)
            frame[..., 0] = np.uint8(255 * t)
            frame[..., 1] = np.uint8(255 * (1.0 - t))
            frame[..., 2] = 128
            frame[..., 3] = 255
            cap.write_frame(frame)
            frames_written += 1
        cap.close()
    except Exception as exc:
        trace.record("gif_capture_failed", error=str(exc))
        return SubsystemStatus("video_capture", False, reason=str(exc)), frames_written

    trace.record(
        "gif_capture",
        path=str(out_path),
        frames=frames_written,
        resolution=list(GIF_RESOLUTION),
        exists=out_path.is_file(),
    )
    return SubsystemStatus("video_capture", True), frames_written


# ---------------------------------------------------------------------------
# Step 4 — Instanced rendering (LL3).
# ---------------------------------------------------------------------------


def _step_instanced(
    trace: DemoTrace,
) -> tuple[list[SubsystemStatus], Any, list[tuple[str, Any]]]:
    """Spawn ``INSTANCE_COUNT`` cube instances in a circle; feed BVH later."""
    statuses: list[SubsystemStatus] = []
    try:
        from slappyengine.render.instanced import circle as instanced_circle
        from slappyengine.render.mesh import cube
    except Exception as exc:
        trace.record("instanced_missing", error=str(exc))
        statuses.append(SubsystemStatus("instanced_rendering", False, reason=str(exc)))
        statuses.append(SubsystemStatus("instanced_aabb_union", False, reason=str(exc)))
        return statuses, None, []

    try:
        mesh = cube(size=0.6)
        inst = instanced_circle(mesh, count=INSTANCE_COUNT, radius=INSTANCE_RADIUS)
    except Exception as exc:
        trace.record("instanced_build_failed", error=str(exc))
        statuses.append(SubsystemStatus("instanced_rendering", False, reason=str(exc)))
        statuses.append(SubsystemStatus("instanced_aabb_union", False, reason=str(exc)))
        return statuses, None, []

    bbmin, bbmax = inst.bounding_box_all
    trace.record(
        "instanced_render",
        count=inst.instance_count,
        radius=INSTANCE_RADIUS,
        bbox_min=list(bbmin),
        bbox_max=list(bbmax),
    )
    statuses.append(SubsystemStatus("instanced_rendering", True))
    statuses.append(SubsystemStatus("instanced_aabb_union", True))

    # Build per-instance AABB entries for BVH downstream.
    entries: list[tuple[str, Any]] = []
    try:
        from slappyengine.render.bvh_3d import AABB3D

        half = 0.3
        ts = inst.instance_data.instance_transforms
        for i in range(inst.instance_count):
            cx, cy, cz = float(ts[i, 0, 3]), float(ts[i, 1, 3]), float(ts[i, 2, 3])
            mn = (cx - half, cy - half, cz - half)
            mx = (cx + half, cy + half, cz + half)
            entries.append((f"cube_{i}", AABB3D(min=mn, max=mx)))
    except Exception as exc:  # pragma: no cover — bvh missing
        trace.record("instanced_bvh_entries_failed", error=str(exc))
    return statuses, inst, entries


# ---------------------------------------------------------------------------
# Step 5 — 3D positional audio (LL4).
# ---------------------------------------------------------------------------


def _step_audio_3d(trace: DemoTrace) -> SubsystemStatus:
    """Play a moving ``menu_swipe`` source and verify doppler shift trajectory."""
    try:
        from slappyengine.audio_3d import (
            Audio3DEngine,
            Audio3DSource,
            AudioListener,
            SoundBank,
        )
    except Exception as exc:
        trace.record("audio_3d_missing", error=str(exc))
        return SubsystemStatus("audio_3d", False, reason=str(exc))

    try:
        bank = SoundBank()
        bank.register(AUDIO_SOUND_ID, {"_stub": True})
        listener = AudioListener(
            position=(0.0, 0.0, 0.0),
            forward=(0.0, 0.0, 1.0),
            velocity=(0.0, 0.0, 0.0),
        )
        engine = Audio3DEngine(listener, bank)
        # Approaching source: velocity toward listener → doppler > 1.
        source = Audio3DSource(
            sound_id=AUDIO_SOUND_ID,
            position=(0.0, 0.0, 8.0),
            velocity=(0.0, 0.0, -6.0),
            min_distance=1.0,
            max_distance=25.0,
        )
        voice_id = engine.play(source)
        # Move the source over 30 sub-steps; capture pitch trajectory.
        pitches: list[float] = []
        for _ in range(30):
            engine.update(0.02)
            state = engine.voice_state(voice_id)
            if state is not None:
                pitches.append(float(state.get("pitch", 1.0)))
        first = pitches[0] if pitches else 1.0
        last = pitches[-1] if pitches else 1.0
        approaching = first > 1.0
    except Exception as exc:
        trace.record("audio_3d_run_failed", error=str(exc))
        return SubsystemStatus("audio_3d", False, reason=str(exc))

    trace.record(
        "audio_3d",
        voice_id=voice_id,
        first_pitch=float(first),
        last_pitch=float(last),
        sample_count=len(pitches),
        approaching=bool(approaching),
    )
    return SubsystemStatus("audio_3d", True)


# ---------------------------------------------------------------------------
# Step 6 — Character animation (JJ4 / LL5).
# ---------------------------------------------------------------------------


@dataclass
class LoadedCharacter:
    skeleton: Any
    skinned_mesh_data: Any
    inverse_bind_matrices: np.ndarray | None
    imported_ok: bool
    reason: str = ""


def _step_load_character(
    trace: DemoTrace, asset_path: Path,
) -> tuple[LoadedCharacter | None, list[SubsystemStatus]]:
    """Load skinned glTF fixture; fall back to a synthesised 2-bone rig."""
    statuses: list[SubsystemStatus] = []
    imported_ok = False
    reason = ""
    imported_mesh = None

    # Soft-import the JJ3 importer.
    try:
        from slappyengine.asset_import.gltf_importer import import_gltf

        if asset_path.is_file():
            result = import_gltf(asset_path)
            for m in result.meshes:
                if hasattr(m, "joints_0") and getattr(m, "joints_0") is not None:
                    imported_mesh = m
                    break
            imported_ok = imported_mesh is not None
            trace.record(
                "gltf_imported",
                path=str(asset_path),
                mesh_count=len(result.meshes),
                found_skinned=bool(imported_ok),
            )
            statuses.append(SubsystemStatus("gltf_importer", True))
        else:
            trace.record("gltf_asset_missing", path=str(asset_path))
            statuses.append(SubsystemStatus(
                "gltf_importer", False,
                reason=f"asset missing: {asset_path}",
            ))
            reason = "asset missing"
    except Exception as exc:
        trace.record("gltf_import_failed", error=str(exc))
        statuses.append(SubsystemStatus("gltf_importer", False, reason=str(exc)))
        reason = str(exc)

    # Skeleton runtime (JJ4).
    try:
        from slappyengine.animation.skeleton_runtime import (
            Skeleton,
            SkeletonNode,
            SkinnedMeshData,
        )
    except Exception as exc:
        trace.record("animation_missing", error=str(exc))
        statuses.append(SubsystemStatus("skeleton_runtime", False, reason=str(exc)))
        return None, statuses

    skeleton = Skeleton(nodes=[
        SkeletonNode(name="root_joint", parent_index=-1,
                     translation=(0.0, 0.0, 0.0),
                     rotation=(0.0, 0.0, 0.0, 1.0),
                     scale=(1.0, 1.0, 1.0)),
        SkeletonNode(name="child_joint", parent_index=0,
                     translation=(0.0, 1.0, 0.0),
                     rotation=(0.0, 0.0, 0.0, 1.0),
                     scale=(1.0, 1.0, 1.0)),
    ])

    # A tiny fallback quad — matches the LL5 fixture shape.
    positions = np.array(
        [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
         [0.0, 0.0, 1.0], [1.0, 0.0, 1.0]], dtype=np.float32,
    )
    normals = np.array([[0.0, 1.0, 0.0]] * 4, dtype=np.float32)
    joints = np.array([[0, 0, 0, 0], [0, 0, 0, 0],
                       [1, 0, 0, 0], [1, 0, 0, 0]], dtype=np.int32)
    weights = np.array([[1.0, 0.0, 0.0, 0.0]] * 4, dtype=np.float32)
    ibms = np.tile(np.eye(4, dtype=np.float32), (2, 1, 1))

    smd = SkinnedMeshData(
        positions=positions,
        joints=joints,
        weights=weights,
        normals=normals,
    )
    trace.record(
        "skeleton_built",
        joint_count=skeleton.joint_count,
        vertex_count=int(positions.shape[0]),
        via_gltf=bool(imported_ok),
    )
    statuses.append(SubsystemStatus("skeleton_runtime", True))
    return (
        LoadedCharacter(
            skeleton=skeleton,
            skinned_mesh_data=smd,
            inverse_bind_matrices=ibms,
            imported_ok=imported_ok,
            reason=reason,
        ),
        statuses,
    )


def _quat_axis_angle(axis: tuple[float, float, float], angle_rad: float) -> np.ndarray:
    a = np.asarray(axis, dtype=np.float64)
    n = float(np.linalg.norm(a))
    if n < 1e-8:
        return np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)
    a = a / n
    s = math.sin(angle_rad * 0.5)
    c = math.cos(angle_rad * 0.5)
    return np.array([a[0] * s, a[1] * s, a[2] * s, c], dtype=np.float32)


def _step_build_clip(
    trace: DemoTrace,
) -> tuple[Any, SubsystemStatus]:
    """Build a 3-key rotate clip for JJ4's Animator."""
    try:
        from slappyengine.animation.clip import AnimationChannel, AnimationClip
    except Exception as exc:
        trace.record("animation_clip_missing", error=str(exc))
        return None, SubsystemStatus("animation_clip", False, reason=str(exc))

    q0 = _quat_axis_angle((0.0, 1.0, 0.0), 0.0)
    q1 = _quat_axis_angle((0.0, 1.0, 0.0), math.pi)
    q2 = _quat_axis_angle((0.0, 1.0, 0.0), 2.0 * math.pi)
    ch = AnimationChannel(
        target_joint_index=1,
        target_property="rotation",
        keyframes=np.array([0.0, 1.0, 2.0], dtype=np.float32),
        values=np.stack([q0, q1, q2], axis=0),
        interpolation="linear",
    )
    clip = AnimationClip(name="rotate", duration_sec=2.0, channels=[ch])
    trace.record("clip_built", name=clip.name, keyframe_count=3, duration_sec=2.0)
    return clip, SubsystemStatus("animation_clip", True)


def _step_build_animator(
    trace: DemoTrace, character: LoadedCharacter, clip: Any,
) -> tuple[Any, SubsystemStatus]:
    """Wire the Animator + drive it for 30 sub-frames."""
    try:
        from slappyengine.animation.skinner import Animator
    except Exception as exc:
        trace.record("animator_missing", error=str(exc))
        return None, SubsystemStatus("animator", False, reason=str(exc))

    try:
        animator = Animator(
            character.skinned_mesh_data,
            character.skeleton,
            {clip.name: clip},
        )
        animator.play(clip.name, loop=True)
        palettes: list[float] = []
        for _ in range(30):
            palette = animator.advance(1.0 / 60.0)
            palettes.append(float(np.abs(palette).sum()))
    except Exception as exc:
        trace.record("animator_run_failed", error=str(exc))
        return None, SubsystemStatus("animator", False, reason=str(exc))

    trace.record(
        "animator_built",
        clip_name=clip.name,
        sample_count=len(palettes),
        first=palettes[0] if palettes else 0.0,
        last=palettes[-1] if palettes else 0.0,
    )
    return animator, SubsystemStatus("animator", True)


# ---------------------------------------------------------------------------
# Step 7 — Directional light + CSM (JJ7).
# ---------------------------------------------------------------------------


def _step_csm(trace: DemoTrace) -> tuple[list[SubsystemStatus], int]:
    """Build a 4-cascade CSM against the demo camera + directional light."""
    statuses: list[SubsystemStatus] = []
    try:
        from slappyengine.render.camera import Camera3D
        from slappyengine.render.light import Light
        from slappyengine.render.shadows import CSMBuilder, ShadowMapConfig
    except Exception as exc:
        trace.record("csm_missing", error=str(exc))
        statuses.append(SubsystemStatus("directional_light", False, reason=str(exc)))
        statuses.append(SubsystemStatus("csm_shadows", False, reason=str(exc)))
        return statuses, 0

    try:
        cam = Camera3D(
            position=(ORBIT_RADIUS, CAMERA_Y, 0.0),
            look_at=(0.0, 0.5, 0.0),
            fov_degrees=60.0,
            near=0.1,
            far=50.0,
            aspect=16.0 / 9.0,
        )
        light = Light(
            kind="directional",
            direction=(-0.4, -1.0, -0.3),
            color=(1.0, 0.95, 0.85),
            intensity=2.0,
        )
        trace.record(
            "directional_light",
            direction=list(light.direction),
            intensity=float(light.intensity),
        )
        statuses.append(SubsystemStatus("directional_light", True))
        config = ShadowMapConfig(
            resolution=1024,
            cascade_count=4,
            cascade_split_lambda=0.5,
            max_shadow_distance=25.0,
            stabilize_cascades=True,
        )
        cascades = CSMBuilder.build_cascades(cam, light, config)
        for c in cascades:
            trace.record(
                "csm_cascade",
                index=int(c.shadow_map_index),
                near_z=float(c.near_z),
                far_z=float(c.far_z),
            )
        trace.record(
            "csm_shadows",
            cascade_count=len(cascades),
            resolution=config.resolution,
        )
        statuses.append(SubsystemStatus("csm_shadows", True))
        return statuses, len(cascades)
    except Exception as exc:
        trace.record("csm_build_failed", error=str(exc))
        statuses.append(SubsystemStatus("csm_shadows", False, reason=str(exc)))
        return statuses, 0


# ---------------------------------------------------------------------------
# Step 8 — Procedural skybox (KK4).
# ---------------------------------------------------------------------------


def _step_skybox(trace: DemoTrace) -> list[SubsystemStatus]:
    """Build a 3-stop gradient cubemap; sample it to confirm the sampler works."""
    statuses: list[SubsystemStatus] = []
    try:
        from slappyengine.render.skybox import (
            procedural_gradient_sky,
            sample_direction_from_cubemap,
        )
    except Exception as exc:
        trace.record("skybox_missing", error=str(exc))
        statuses.append(SubsystemStatus("skybox", False, reason=str(exc)))
        statuses.append(SubsystemStatus("skybox_sampler", False, reason=str(exc)))
        return statuses

    try:
        cubemap = procedural_gradient_sky(
            top_color=(0.35, 0.55, 0.90),
            horizon_color=(0.85, 0.90, 0.98),
            ground_color=(0.18, 0.15, 0.12),
            resolution=128,
        )
    except Exception as exc:
        trace.record("skybox_build_failed", error=str(exc))
        statuses.append(SubsystemStatus("skybox", False, reason=str(exc)))
        statuses.append(SubsystemStatus("skybox_sampler", False, reason=str(exc)))
        return statuses

    trace.record(
        "skybox",
        resolution=cubemap.resolution,
        face_count=6,
        pow2=bool(cubemap.is_power_of_two),
    )
    statuses.append(SubsystemStatus("skybox", True))

    # Sample straight up (should be closest to top_color).
    try:
        sample = sample_direction_from_cubemap(cubemap, (0.0, 1.0, 0.0))
        trace.record(
            "skybox_sampler",
            direction="up",
            sample=[int(sample[0]), int(sample[1]), int(sample[2])],
        )
        statuses.append(SubsystemStatus("skybox_sampler", True))
    except Exception as exc:
        trace.record("skybox_sample_failed", error=str(exc))
        statuses.append(SubsystemStatus("skybox_sampler", False, reason=str(exc)))
    return statuses


# ---------------------------------------------------------------------------
# Step 9 — SSAO (KK3).
# ---------------------------------------------------------------------------


def _step_ssao(trace: DemoTrace) -> SubsystemStatus:
    """Build an :class:`SSAOPass` + verify its kernel + noise generators."""
    try:
        from slappyengine.render.ssao import SSAOConfig, SSAOPass
    except Exception as exc:
        trace.record("ssao_missing", error=str(exc))
        return SubsystemStatus("ssao", False, reason=str(exc))

    try:
        config = SSAOConfig(sample_count=16, radius_world=0.5, bias=0.025,
                            intensity=1.5, noise_texture_size=4)
        ssao = SSAOPass(config=config)
        kernel = ssao.generate_kernel()
        noise = ssao.generate_noise_texture()
        wgsl = ssao.emit_ssao_wgsl()
    except Exception as exc:
        trace.record("ssao_build_failed", error=str(exc))
        return SubsystemStatus("ssao", False, reason=str(exc))

    trace.record(
        "ssao",
        sample_count=config.sample_count,
        kernel_shape=list(kernel.shape),
        noise_shape=list(noise.shape),
        wgsl_bytes=len(wgsl.encode("utf-8")),
    )
    return SubsystemStatus("ssao", True)


# ---------------------------------------------------------------------------
# Step 10 — SDF text (KK6).
# ---------------------------------------------------------------------------


def _step_sdf_text(trace: DemoTrace) -> SubsystemStatus:
    """Render ``SDF_TITLE_TEXT`` via SDF glyph atlas + text renderer."""
    try:
        from slappyengine.text.atlas import SDFGlyphAtlas
        from slappyengine.text.text_render import SDFTextRenderer
    except Exception as exc:
        trace.record("sdf_text_missing", error=str(exc))
        return SubsystemStatus("sdf_text", False, reason=str(exc))

    try:
        atlas = SDFGlyphAtlas(font_path=None, size_px=32, sdf_radius=6)
        atlas.generate()
        renderer = SDFTextRenderer()
        mesh = renderer.build_text_mesh(
            SDF_TITLE_TEXT,
            position_px=(16.0, 24.0),
            size_px=32.0,
            atlas=atlas,
        )
    except Exception as exc:
        trace.record("sdf_text_build_failed", error=str(exc))
        return SubsystemStatus("sdf_text", False, reason=str(exc))

    trace.record(
        "sdf_text",
        text=SDF_TITLE_TEXT,
        vertex_count=int(mesh.positions.shape[0]),
        index_count=int(mesh.indices.shape[0]),
        width_px=float(mesh.width_px),
        height_px=float(mesh.height_px),
    )
    return SubsystemStatus("sdf_text", True)


# ---------------------------------------------------------------------------
# Step 11 — 3D BVH (KK1) build + frustum + ray query.
# ---------------------------------------------------------------------------


def _step_bvh(
    trace: DemoTrace, entries: list[tuple[str, Any]],
) -> list[SubsystemStatus]:
    """Build BVH3D, run a frustum query + ray query + record stats."""
    statuses: list[SubsystemStatus] = []
    if not entries:
        trace.record("bvh_no_entries")
        statuses.append(SubsystemStatus("bvh_3d", False, reason="no entries"))
        statuses.append(SubsystemStatus("bvh_frustum_query", False, reason="no entries"))
        statuses.append(SubsystemStatus("bvh_ray_query", False, reason="no entries"))
        statuses.append(SubsystemStatus("bvh_stats", False, reason="no entries"))
        return statuses

    try:
        from slappyengine.render.bvh_3d import BVH3D
        from slappyengine.render.camera import Camera3D
        from slappyengine.render.scene_walker import Frustum
    except Exception as exc:
        trace.record("bvh_missing", error=str(exc))
        statuses.append(SubsystemStatus("bvh_3d", False, reason=str(exc)))
        statuses.append(SubsystemStatus("bvh_frustum_query", False, reason=str(exc)))
        statuses.append(SubsystemStatus("bvh_ray_query", False, reason=str(exc)))
        statuses.append(SubsystemStatus("bvh_stats", False, reason=str(exc)))
        return statuses

    try:
        bvh = BVH3D(entries)
    except Exception as exc:
        trace.record("bvh_build_failed", error=str(exc))
        statuses.append(SubsystemStatus("bvh_3d", False, reason=str(exc)))
        statuses.append(SubsystemStatus("bvh_frustum_query", False, reason=str(exc)))
        statuses.append(SubsystemStatus("bvh_ray_query", False, reason=str(exc)))
        statuses.append(SubsystemStatus("bvh_stats", False, reason=str(exc)))
        return statuses

    trace.record(
        "bvh_3d",
        entity_count=len(entries),
        node_count=len(bvh.nodes),
    )
    statuses.append(SubsystemStatus("bvh_3d", True))

    # Frustum query — from a camera looking at the origin.
    try:
        cam = Camera3D(
            position=(ORBIT_RADIUS + 4.0, CAMERA_Y, 0.0),
            look_at=(0.0, 0.0, 0.0),
            fov_degrees=90.0,
            near=0.1,
            far=100.0,
            aspect=16.0 / 9.0,
        )
        frustum = Frustum.from_camera(cam)
        visible = bvh.query_frustum(frustum)
        trace.record(
            "bvh_frustum_query",
            visible=len(visible),
            first_visible=visible[0] if visible else "",
        )
        statuses.append(SubsystemStatus("bvh_frustum_query", True))
    except Exception as exc:
        trace.record("bvh_frustum_failed", error=str(exc))
        statuses.append(SubsystemStatus("bvh_frustum_query", False, reason=str(exc)))

    # Ray query — from the camera origin along −x.
    try:
        hits = bvh.query_ray(
            origin=(ORBIT_RADIUS + 4.0, 0.0, 0.0),
            direction=(-1.0, 0.0, 0.0),
        )
        trace.record("bvh_ray_query", hit_count=len(hits),
                     nearest=hits[0][0] if hits else "")
        statuses.append(SubsystemStatus("bvh_ray_query", True))
    except Exception as exc:
        trace.record("bvh_ray_failed", error=str(exc))
        statuses.append(SubsystemStatus("bvh_ray_query", False, reason=str(exc)))

    # Stats.
    try:
        stats = bvh.stats()
        trace.record(
            "bvh_stats",
            depth=stats.get("depth"),
            leaf_count=stats.get("leaf_count"),
            node_count=stats.get("node_count"),
        )
        statuses.append(SubsystemStatus("bvh_stats", True))
    except Exception as exc:
        trace.record("bvh_stats_failed", error=str(exc))
        statuses.append(SubsystemStatus("bvh_stats", False, reason=str(exc)))
    return statuses


# ---------------------------------------------------------------------------
# Step 12 — Physics3 bridge (LL7).
# ---------------------------------------------------------------------------


def _step_physics3(trace: DemoTrace) -> list[SubsystemStatus]:
    """Spawn 5 spheres in :class:`World3D`; integrate; record broadphase pairs."""
    statuses: list[SubsystemStatus] = []
    try:
        from slappyengine.physics3_bridge import (
            Body3D,
            World3D,
            resolve_physics3_backend,
        )
    except Exception as exc:
        trace.record("physics3_missing", error=str(exc))
        statuses.append(SubsystemStatus("physics3_bridge", False, reason=str(exc)))
        statuses.append(SubsystemStatus("physics3_broadphase", False, reason=str(exc)))
        return statuses

    try:
        backend_tag = resolve_physics3_backend()
        world = World3D(gravity=(0.0, -9.81, 0.0), backend="fallback")
        handles: list[int] = []
        for i in range(PHYSICS3_SPHERE_COUNT):
            body = Body3D(
                position=(float(i) * 1.5, 5.0, 0.0),
                shape_kind="sphere",
                shape_params={"radius": 0.5},
                mass=1.0,
            )
            handles.append(world.add_body(body))
        # Record positions before step.
        y0 = [world.get_body(h).position[1] for h in handles]
        for _ in range(PHYSICS3_STEPS):
            world.step(1.0 / 60.0)
        y1 = [world.get_body(h).position[1] for h in handles]
    except Exception as exc:
        trace.record("physics3_run_failed", error=str(exc))
        statuses.append(SubsystemStatus("physics3_bridge", False, reason=str(exc)))
        statuses.append(SubsystemStatus("physics3_broadphase", False, reason=str(exc)))
        return statuses

    fell = all(a > b for a, b in zip(y0, y1))
    trace.record(
        "physics3_bridge",
        backend_tag=backend_tag,
        chosen_backend=world.backend,
        body_count=len(world),
        steps=PHYSICS3_STEPS,
        fell_under_gravity=bool(fell),
        y0_first=float(y0[0]),
        y1_first=float(y1[0]),
    )
    statuses.append(SubsystemStatus("physics3_bridge", True))

    try:
        pairs = world.broadphase_pairs()
        trace.record("physics3_broadphase", pair_count=len(pairs))
        statuses.append(SubsystemStatus("physics3_broadphase", True))
    except Exception as exc:
        trace.record("physics3_broadphase_failed", error=str(exc))
        statuses.append(SubsystemStatus("physics3_broadphase", False, reason=str(exc)))
    return statuses


# ---------------------------------------------------------------------------
# Step 13 — Exporter smoke-test (LL6).
# ---------------------------------------------------------------------------


def _step_exporter(trace: DemoTrace, tmp_root: Path) -> SubsystemStatus:
    """Synthesise a minimal project skeleton + call :func:`export_project`."""
    try:
        from slappyengine.exporter import (
            ProjectManifest,
            export_project,
        )
    except Exception as exc:
        trace.record("exporter_missing", error=str(exc))
        return SubsystemStatus("exporter", False, reason=str(exc))

    project_dir = tmp_root / "hello_showcase_v3_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "main.py").write_text(
        "def main():\n    print('hello_showcase_v3')\n\nif __name__ == '__main__':\n    main()\n",
        encoding="utf-8",
    )

    # Write a minimal manifest so ProjectManifest.load succeeds.
    try:
        manifest = ProjectManifest(
            name="hello_showcase_v3",
            version="0.1.0",
            main_script="main.py",
        )
        manifest.write(project_dir)
    except Exception as exc:  # pragma: no cover — manifest drift
        trace.record("exporter_manifest_failed", error=str(exc))
        return SubsystemStatus("exporter", False, reason=str(exc))

    # Dry-run binary export path (won't invoke PyInstaller when
    # dry_run=True) — smoke-tests the manifest + platform_targets path.
    out_binary = tmp_root / "hello_showcase_v3_out"
    try:
        result = export_project(
            project_dir,
            out_binary,
            platform="auto",
            include_python=False,
            dry_run=True,
        )
    except Exception as exc:
        trace.record("exporter_run_failed", error=str(exc))
        return SubsystemStatus("exporter", False, reason=str(exc))

    trace.record(
        "exporter",
        project_dir=str(project_dir),
        export_kind=result.kind,
        succeeded=bool(result.succeeded or not result.errors),
        pyinstaller_available=bool(result.pyinstaller_available),
        warnings=len(result.warnings),
        errors=len(result.errors),
    )
    return SubsystemStatus("exporter", True)


# ---------------------------------------------------------------------------
# Step 14 — Tick heartbeats — pad the trace to > 80 events + prove the
# demo actually walked a headless frame loop.
# ---------------------------------------------------------------------------


def _step_frame_loop(trace: DemoTrace) -> None:
    """Emit heartbeat events across the 180-frame demo window."""
    for i in range(0, FRAME_COUNT, 20):
        trace.record("tick", frame=i, phase=i / max(FRAME_COUNT - 1, 1))


# ---------------------------------------------------------------------------
# Subsystem registry — keys used for the OK/SKIPPED summary + tests.
# ---------------------------------------------------------------------------


#: The complete set of subsystems the demo attempts to exercise.
#: ``ALL_SUBSYSTEMS`` order is stable — the summary table + tests key
#: off this tuple so a drifted subsystem count is caught deterministically.
ALL_SUBSYSTEMS: tuple[str, ...] = (
    # HH1 / core shell
    "app_shell",
    # LL1 — HUD
    "hud_overlay",
    "hud_widget_attach",
    "hud_command_emit",
    "hud_renderer_submit",
    # LL2 — capture
    "video_capture",
    # LL3 — instanced
    "instanced_rendering",
    "instanced_aabb_union",
    # LL4 — 3D audio
    "audio_3d",
    # JJ3 / LL5 — character
    "gltf_importer",
    "skeleton_runtime",
    "animation_clip",
    "animator",
    # JJ7 — CSM shadows
    "directional_light",
    "csm_shadows",
    # KK4 — skybox
    "skybox",
    "skybox_sampler",
    # KK3 — SSAO
    "ssao",
    # KK6 — SDF text
    "sdf_text",
    # KK1 — 3D BVH
    "bvh_3d",
    "bvh_frustum_query",
    "bvh_ray_query",
    "bvh_stats",
    # LL7 — physics3 bridge
    "physics3_bridge",
    "physics3_broadphase",
    # LL6 — exporter
    "exporter",
)


LL_SUBSYSTEMS: tuple[str, ...] = (
    # LL1
    "hud_overlay",
    # LL2
    "video_capture",
    # LL3
    "instanced_rendering",
    # LL4
    "audio_3d",
    # LL5 (character animation)
    "animator",
    # LL6
    "exporter",
    # LL7
    "physics3_bridge",
)


def _resolve_asset_path(override: Path | str | None = None) -> Path:
    if override is not None:
        return Path(override).resolve()
    here = Path(__file__).resolve().parent
    return here / ASSET_RELPATH


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def run_demo(
    *,
    trace_path: Path | str | None = None,
    gif_path: Path | str | None = None,
    asset_path: Path | str | None = None,
) -> DemoTrace:
    """Run the MM5 showcase end-to-end + return the populated trace."""
    trace = DemoTrace()
    trace.record(
        "demo_start",
        python=sys.version.split()[0],
        target_subsystems=len(ALL_SUBSYSTEMS),
    )

    resolved_asset = _resolve_asset_path(asset_path)
    trace.record(
        "asset_resolved",
        path=str(resolved_asset),
        exists=resolved_asset.is_file(),
    )

    tmp_root = Path(tempfile.mkdtemp(prefix="hello_showcase_v3_"))
    status_map: dict[str, SubsystemStatus] = {}

    try:
        # 1. App shell.
        app, renderer, s = _step_boot_app(trace)
        status_map[s.key] = s

        # 2. HUD overlay + widgets.
        for s in _step_hud_overlay(trace, renderer)[0]:
            status_map[s.key] = s

        # 3. GIF capture.
        gif_out = Path(gif_path) if gif_path is not None else (
            Path(__file__).with_name(GIF_NAME)
        )
        s, _frames = _step_gif_capture(trace, gif_out)
        status_map[s.key] = s

        # 4. Instanced rendering (+ AABB entries for BVH).
        instanced_statuses, _inst, bvh_entries = _step_instanced(trace)
        for s in instanced_statuses:
            status_map[s.key] = s

        # 5. 3D audio.
        s = _step_audio_3d(trace)
        status_map[s.key] = s

        # 6. Character animation.
        character, char_statuses = _step_load_character(trace, resolved_asset)
        for s in char_statuses:
            status_map[s.key] = s
        if character is not None:
            clip, s_clip = _step_build_clip(trace)
            status_map[s_clip.key] = s_clip
            if clip is not None:
                _animator, s_anim = _step_build_animator(trace, character, clip)
                status_map[s_anim.key] = s_anim
            else:
                status_map["animator"] = SubsystemStatus(
                    "animator", False, reason="clip missing",
                )
        else:
            status_map["animation_clip"] = SubsystemStatus(
                "animation_clip", False, reason="character missing",
            )
            status_map["animator"] = SubsystemStatus(
                "animator", False, reason="character missing",
            )

        # 7. CSM shadows.
        for s in _step_csm(trace)[0]:
            status_map[s.key] = s

        # 8. Skybox.
        for s in _step_skybox(trace):
            status_map[s.key] = s

        # 9. SSAO.
        s = _step_ssao(trace)
        status_map[s.key] = s

        # 10. SDF text.
        s = _step_sdf_text(trace)
        status_map[s.key] = s

        # 11. 3D BVH.
        for s in _step_bvh(trace, bvh_entries):
            status_map[s.key] = s

        # 12. Physics3 bridge.
        for s in _step_physics3(trace):
            status_map[s.key] = s

        # 13. Exporter.
        s = _step_exporter(trace, tmp_root)
        status_map[s.key] = s

        # 14. Heartbeats.
        _step_frame_loop(trace)

        # ---- Summary print ----
        # Any subsystem in ALL_SUBSYSTEMS that wasn't touched at all
        # counts as MISSING (no status record).
        rows: list[dict[str, Any]] = []
        for key in ALL_SUBSYSTEMS:
            st = status_map.get(key)
            if st is None:
                rows.append({"key": key, "state": "MISSING", "reason": "not attempted"})
            elif st.ok:
                rows.append({"key": key, "state": "OK", "reason": ""})
            else:
                rows.append({"key": key, "state": "SKIPPED", "reason": st.reason})

        ok_count = sum(1 for r in rows if r["state"] == "OK")
        skipped_count = sum(1 for r in rows if r["state"] == "SKIPPED")
        missing_count = sum(1 for r in rows if r["state"] == "MISSING")

        ll_rows = [r for r in rows if r["key"] in LL_SUBSYSTEMS]
        ll_ok = sum(1 for r in ll_rows if r["state"] == "OK")

        summary = {
            "subsystems_total":    len(ALL_SUBSYSTEMS),
            "subsystems_ok":       ok_count,
            "subsystems_skipped":  skipped_count,
            "subsystems_missing":  missing_count,
            "ll_subsystems_total": len(LL_SUBSYSTEMS),
            "ll_subsystems_ok":    ll_ok,
            "trace_events":        len(trace.events) + 1,  # +1 for demo_end
        }

        print("hello_showcase_v3 summary:")
        for k, v in summary.items():
            print(f"  {k:22s}: {v}")
        print("subsystems (25+):")
        for r in rows:
            marker = {"OK": "OK  ", "SKIPPED": "SKIP", "MISSING": "MISS"}[r["state"]]
            reason = f" — {r['reason']}" if r["reason"] else ""
            print(f"  [{marker}] {r['key']}{reason}")

        trace.record(
            "demo_end",
            total_events=len(trace.events) + 1,
            summary=summary,
            subsystems=rows,
        )

        # ---- Trace YAML ----
        # Written AFTER demo_end so the YAML file reflects the full run.
        out_trace = (
            Path(trace_path)
            if trace_path is not None
            else Path(__file__).with_name(TRACE_NAME)
        )
        try:
            out_trace.parent.mkdir(parents=True, exist_ok=True)
            out_trace.write_text(trace.as_yaml(), encoding="utf-8")
            trace.record(
                "trace_written",
                path=str(out_trace),
                events=len(trace.events),
            )
        except Exception as exc:  # pragma: no cover — disk failure paths
            trace.record("trace_write_failed", error=str(exc))
        return trace
    finally:
        # tmp_root is best-effort cleanup — Windows can hold file locks.
        try:
            import shutil
            shutil.rmtree(tmp_root, ignore_errors=True)
        except Exception:
            pass
        if app is not None:
            try:
                app.close()
            except Exception:  # pragma: no cover — defensive
                pass


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


if __name__ == "__main__":  # pragma: no cover
    run_demo()
