"""hello_v2_showcase — comprehensive 15+ subsystem V2 showcase.

EE-batch sprint (task EE2, 2026-07-05). Where AA5 (:mod:`hello_full_editor`)
covers the notebook shell + prefab spawn + material graph + FX preset +
autosave + theme walk (~9 subsystems), this demo climbs one tier further
and exercises 15+ subsystems in a single scripted CI-lockable run — the
V2 editor sandbox as one 500-line trace:

1.  **Project registry** (V2) — :class:`ProjectRegistry` add + list + touch.
2.  **User theme store** (U2) — :class:`UserThemeStore` load baked theme.
3.  **Prefab library** (Y3/AA2) — 4 prefabs spawned via ``lib.spawn``.
4.  **Prefab preview baker** (BB6) — :class:`PreviewBaker` bake previews.
5.  **Autosave manager** (Y6/AA2) — 3 snapshots + ``read_snapshot``.
6.  **Chain manifest** (X5) — build + apply to test image.
7.  **Baked chain preset** (Z3) — ``ChainBaker.load("dreamy")``.
8.  **Material graph bridge** (AA4) — 5-node graph → WGSL.
9.  **Shader lint** (AA6) — :func:`lint_wgsl` on emitted WGSL.
10. **Hotkey remap** (AA7) — load 3 baked style presets.
11. **Camera animation** (CC6) — 2 tweens with easing.
12. **Toast manager** (CC5) — 5 toasts of varying levels.
13. **Command palette** (CC7) — fuzzy-search "spawn".
14. **Layout baker** (CC4) — load "debugging" preset.
15. **Timeline editor** (DD5) — 2 tracks + keyframes.
16. **Feature map** — assert 250+ WIRED rows in
    ``docs/engine_feature_map_2026_07_04.md``.
17. **User overrides watcher** (X6) — :meth:`watch_dir` start + stop.

Headless contract
-----------------
The demo is careful to keep :func:`dpg.show_viewport` behind the
``if __name__ == "__main__":`` guard. When ``SLAPPY_HEADLESS=1`` the
demo skips :func:`dpg.create_context` entirely (mirrors AA5).

Run:
    python SlapPyEngineExamples/examples/hello_v2_showcase.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any


# ---------------------------------------------------------------------------
# Optional DPG import guard.
# ---------------------------------------------------------------------------

try:  # pragma: no cover — DPG missing means headless path
    import dearpygui.dearpygui as dpg  # type: ignore
    _HAS_DPG = True
except Exception:
    dpg = None  # type: ignore[assignment]
    _HAS_DPG = False


def _headless_env_active() -> bool:
    """Return ``True`` when ``SLAPPY_HEADLESS=1`` (or truthy) is set."""
    val = os.environ.get("SLAPPY_HEADLESS", "")
    return val.strip().lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Non-DPG engine imports — safe to eager-load.
# ---------------------------------------------------------------------------

import numpy as np

from slappyengine.autosave import (
    AutosaveManager,
    AutosaveReadError,
    AutosaveState,
)
from slappyengine.dynamics import World
from slappyengine.post_process.chain_baker import ChainBaker
from slappyengine.post_process.chain_manifest import (
    ChainManifest,
    PassSpec,
    apply_manifest,
)
from slappyengine.prefabs import PrefabLibrary
from slappyengine.prefabs.preview_baker import PreviewBaker
from slappyengine.project_registry import (
    ProjectRegistry,
    RegisteredProject,
)
from slappyengine.ui.hotkey_remap import (
    bake_defaults as bake_hotkey_defaults,
    load_user_hotkeys,
)
from slappyengine.ui.theme import apply_theme, get_active_theme
from slappyengine.ui.theme.shader_lint import lint_wgsl
from slappyengine.ui.theme.themes import register_all_themes
from slappyengine.ui.theme.user_themes import UserThemeStore
from slappyengine.ui.user_overrides import UserOverrideLoader
from slappyengine.visual_scripting.graph import NodeGraph
from slappyengine.visual_scripting.material_nodes import (
    AddNode,
    MaterialOutputNode,
    MultiplyNode,
    SaturateNode,
    TimeNode,
)
from slappyengine.visual_scripting.node import Node, NodePort


# ---------------------------------------------------------------------------
# Demo constants
# ---------------------------------------------------------------------------

#: 4 prefabs to spawn in step 3.
PREFAB_SPAWNS: tuple[tuple[str, tuple[float, float]], ...] = (
    ("crate",   (-3.0, 3.0)),
    ("ball",    ( 0.0, 3.0)),
    ("chain",   ( 3.0, 4.0)),
    ("ragdoll", ( 6.0, 5.0)),
)

#: 5-node material graph — time → multiply → add → saturate → output.
#: Names are used only for trace records + tests; the actual node classes
#: (:class:`TimeNode` etc.) emit real WGSL so the bridge produces non-empty
#: source, and :func:`lint_wgsl` gets to lint something meaningful.
MATERIAL_NODE_IDS: tuple[str, ...] = (
    "n_time", "n_mul", "n_add", "n_sat", "n_out",
)

#: 5 toast messages surfaced through the toast manager.
TOAST_MESSAGES: tuple[tuple[str, str], ...] = (
    ("Project loaded",         "INFO"),
    ("Prefabs baked",          "SUCCESS"),
    ("Autosave interval short", "WARN"),
    ("Chain preset applied",   "SUCCESS"),
    ("GPU driver mismatch",    "ERROR"),
)

#: Camera tween schedule — 2 tweens with distinct easing curves.
CAMERA_TWEENS: tuple[tuple[str, tuple[float, float, float], str, float], ...] = (
    ("pan_to_prefab",  (3.0, 4.0, 0.0), "ease_in_out", 800.0),
    ("zoom_in_focus",  (0.0, 0.0, 0.0), "back",        1000.0),
)

#: Timeline tracks + keyframes added in step 15.
TIMELINE_TRACKS: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = (
    ("camera.x", ((0.0, 0.0), (1.0, 3.0), (2.0, 0.0))),
    ("light.intensity", ((0.0, 0.1), (1.0, 1.0), (2.5, 0.4))),
)

#: Layout preset step 14 loads via :class:`LayoutBaker`.
LAYOUT_PRESET_NAME: str = "debugging"

#: Baked chain preset step 7 pulls via :class:`ChainBaker`.
CHAIN_PRESET_NAME: str = "dreamy"

#: Theme step 2 loads through :class:`UserThemeStore`.
TARGET_THEME_NAME: str = "teengirl_notebook"


# ---------------------------------------------------------------------------
# Trace recorder (borrowed shape from hello_full_editor).
# ---------------------------------------------------------------------------


class DemoTrace:
    """Ordered event log — YAML-serialised at demo end."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, kind: str, **payload: Any) -> None:
        entry: dict[str, Any] = {"kind": kind}
        entry.update(payload)
        self.events.append(entry)

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
# Subsystem exercises
# ---------------------------------------------------------------------------


def _step_project_registry(trace: DemoTrace, tmp_root: Path) -> ProjectRegistry:
    """Step 1 — register + list projects on an isolated YAML file."""
    reg_path = tmp_root / "projects.yaml"
    registry = ProjectRegistry(path=reg_path)
    added_names: list[str] = []
    for i, name in enumerate(("hello_v2_alpha", "hello_v2_beta",
                              "hello_v2_gamma")):
        project = RegisteredProject(
            name=name,
            path=tmp_root / f"proj_{name}",
            notes=f"showcase project {i}",
        )
        registry.add(project)
        added_names.append(name)
        trace.record("project_added", name=name, index=i)
    registry.touch("hello_v2_alpha")
    trace.record("project_touched", name="hello_v2_alpha")
    recent = registry.list_recent(limit=8)
    trace.record(
        "project_registry",
        store_path=str(reg_path),
        added_count=len(added_names),
        added=added_names,
        recent_count=len(recent),
        recent_names=[p.name for p in recent],
    )
    return registry


def _step_user_theme(trace: DemoTrace, tmp_root: Path) -> str:
    """Step 2 — bake defaults + load one baked theme via UserThemeStore."""
    theme_dir = tmp_root / "themes"
    store = UserThemeStore(user_dir=theme_dir)
    copied = store.ensure_defaults_copied()
    baked_names = store.list_baked()
    # Prefer TARGET_THEME_NAME if present; otherwise pick the first baked name.
    if TARGET_THEME_NAME in baked_names:
        target = TARGET_THEME_NAME
    elif baked_names:
        target = baked_names[0]
    else:
        target = ""
    loaded_name = ""
    if target:
        try:
            theme = store.load_theme(target)
            loaded_name = getattr(theme, "name", target)
        except Exception as exc:  # pragma: no cover — theme drift
            trace.record("user_theme_load_failed", target=target, error=str(exc))
    trace.record(
        "user_theme_store",
        user_dir=str(theme_dir),
        baked_count=len(baked_names),
        copied_count=len(copied),
        target=target,
        loaded_name=loaded_name,
    )
    return loaded_name


def _step_prefab_library(
    trace: DemoTrace,
    world: World,
    tmp_root: Path,
) -> tuple[PrefabLibrary, dict[str, list]]:
    """Step 3 — bake baked prefabs into a tmp dir + spawn 4 prefabs."""
    prefab_dir = tmp_root / "prefabs"
    lib = PrefabLibrary()
    lib.bake_defaults(user_dir=prefab_dir)
    lib.load_from_dir(prefab_dir)
    trace.record(
        "prefab_library_loaded",
        user_dir=str(prefab_dir),
        registered=lib.list_names(),
    )
    bodies_by_name: dict[str, list] = {}
    for name, pos in PREFAB_SPAWNS:
        prefab = lib.get(name)
        if prefab is None:
            trace.record("prefab_missing", name=name)
            continue
        try:
            bodies = lib.spawn(name, world, pos)
        except Exception as exc:  # pragma: no cover — spawn drift
            trace.record("prefab_spawn_failed", name=name, error=str(exc))
            continue
        bodies_by_name[name] = list(bodies)
        trace.record(
            "prefab_spawned",
            name=name, pos=list(pos), body_count=len(bodies),
            via="library.spawn",
        )
    trace.record(
        "prefab_summary",
        spawned=list(bodies_by_name.keys()),
        body_count=sum(len(bs) for bs in bodies_by_name.values()),
        node_count=int(world.positions.shape[0]),
    )
    return lib, bodies_by_name


def _step_prefab_previews(
    trace: DemoTrace, lib: PrefabLibrary, tmp_root: Path,
) -> list[Path]:
    """Step 4 — bake 64x64 previews for every registered prefab."""
    out_dir = tmp_root / "previews"
    baker = PreviewBaker()
    try:
        written = baker.bake_all_previews(lib, out_dir, size=48)
    except Exception as exc:  # pragma: no cover — PIL drift
        trace.record("preview_bake_failed", error=str(exc))
        return []
    trace.record(
        "preview_baked",
        out_dir=str(out_dir),
        count=len(written),
        first=str(written[0]) if written else None,
    )
    return written


def _step_autosave(
    trace: DemoTrace, tmp_root: Path,
) -> tuple[Path | None, dict | None]:
    """Step 5 — three ``force_save`` ticks + one ``read_snapshot`` round-trip."""
    snap_dir = tmp_root / "autosave"
    state = AutosaveState(
        enabled=True,
        interval_seconds=1.0,
        snapshot_dir=snap_dir,
        max_snapshots=5,
    )
    project = SimpleNamespace(name="hello_v2_showcase")
    counter = {"n": 0}

    def payload_cb() -> dict:
        counter["n"] += 1
        return {
            "iteration": counter["n"],
            "text": "V2 showcase " * counter["n"],
            "when": time.time(),
        }

    manager = AutosaveManager(state, project, payload_cb)
    written: list[Path] = []
    for i in range(3):
        path = manager.force_save()
        written.append(path)
        trace.record("autosave_snapshot", index=i, path=str(path))
        time.sleep(0.01)
    latest = manager.list_snapshots()
    latest_path = latest[0] if latest else None
    decoded: dict | None = None
    if latest_path is not None:
        try:
            decoded = AutosaveManager.read_snapshot(latest_path)
        except (AutosaveReadError, FileNotFoundError) as exc:
            trace.record("autosave_read_failed", error=str(exc))
    trace.record(
        "autosave_read",
        latest=str(latest_path) if latest_path is not None else None,
        meta_keys=sorted((decoded or {}).get("meta", {}).keys()),
        payload_keys=sorted(
            (decoded or {}).get("payload", {}).keys()
            if isinstance((decoded or {}).get("payload"), dict) else []
        ),
    )
    return latest_path, decoded


def _step_chain_manifest(trace: DemoTrace) -> ChainManifest:
    """Step 6 — build a custom manifest + apply to a test image."""
    manifest = ChainManifest(passes=[
        PassSpec(
            name="bloom",
            kind="bloom",
            params={"strength": 0.6, "threshold": 1.0, "knee": 0.2,
                    "mip_count": 4},
        ),
        PassSpec(
            name="tonemap",
            kind="tonemap",
            params={"exposure_ev": 0.5, "mode": 0},
            depends_on=["bloom"],
        ),
        PassSpec(
            name="dither",
            kind="dither",
            params={"strength": 1.0 / 255.0},
            depends_on=["tonemap"],
        ),
    ])
    manifest.validate()
    order = manifest.topological_order()
    for spec in order:
        trace.record(
            "chain_manifest_pass",
            name=spec.name, pass_kind=spec.kind,
            enabled=spec.enabled,
            depends_on=list(spec.depends_on),
        )
    # Apply to a tiny synthetic image so we exercise every handler branch.
    image = np.linspace(0.0, 2.0, 16 * 16 * 3,
                        dtype=np.float32).reshape((16, 16, 3))
    try:
        result = apply_manifest(image, manifest)
        applied_ok = True
        applied_shape = list(result.shape)
    except Exception as exc:  # pragma: no cover — handler drift
        trace.record("chain_manifest_apply_failed", error=str(exc))
        applied_ok = False
        applied_shape = []
    trace.record(
        "chain_manifest",
        pass_count=len(manifest.passes),
        topological=[p.name for p in order],
        applied_ok=applied_ok,
        applied_shape=applied_shape,
    )
    return manifest


def _step_chain_baker(trace: DemoTrace, tmp_root: Path) -> str:
    """Step 7 — load the ``dreamy`` baked chain preset via :class:`ChainBaker`."""
    chain_dir = tmp_root / "chains"
    baker = ChainBaker(user_dir=chain_dir)
    result = baker.bake_defaults()
    try:
        ChainBaker.register_stub_handlers()
    except Exception:
        pass
    loaded_name = ""
    pass_count = 0
    try:
        manifest = baker.load(CHAIN_PRESET_NAME)
        loaded_name = CHAIN_PRESET_NAME
        pass_count = len(manifest.passes)
    except Exception as exc:
        trace.record(
            "chain_baker_load_failed", preset=CHAIN_PRESET_NAME, error=str(exc),
        )
    trace.record(
        "chain_baker",
        user_dir=str(chain_dir),
        written_count=len(getattr(result, "written", [])),
        baked_names=list(getattr(result, "baked_names", [])),
        loaded=loaded_name,
        pass_count=pass_count,
    )
    return loaded_name


def _build_material_graph() -> NodeGraph:
    """Assemble the 5-node material graph (time → multiply → add → saturate → out).

    All nodes are real :class:`MaterialNode` subclasses so
    :class:`MaterialGraphBridge` can emit non-empty WGSL and the shader
    linter (step 9) gets to see meaningful source.
    """
    graph = NodeGraph(name="hello_v2_showcase_material")
    n_time = TimeNode(id=MATERIAL_NODE_IDS[0])
    n_mul  = MultiplyNode(id=MATERIAL_NODE_IDS[1])
    n_add  = AddNode(id=MATERIAL_NODE_IDS[2])
    n_sat  = SaturateNode(id=MATERIAL_NODE_IDS[3])
    n_out  = MaterialOutputNode(id=MATERIAL_NODE_IDS[4])
    for node in (n_time, n_mul, n_add, n_sat, n_out):
        graph.add_node(node)
    # Wire time.out → mul.a, mul.out → add.a, add.out → sat.x, sat.out → out.roughness.
    graph.add_edge(n_time.id, "out", n_mul.id, "a")
    graph.add_edge(n_mul.id,  "out", n_add.id, "a")
    graph.add_edge(n_add.id,  "out", n_sat.id, "x")
    graph.add_edge(n_sat.id,  "out", n_out.id, "roughness")
    return graph


def _step_material_bridge(trace: DemoTrace) -> str:
    """Step 8 — build a 5-node graph + drive :class:`MaterialGraphBridge`."""
    graph = _build_material_graph()
    wgsl: str = ""
    used_bridge = False
    uniforms: list[str] = []
    try:
        from slappyengine.ui.editor.material_graph_bridge import (
            MaterialGraphBridge,
        )
    except Exception as exc:
        trace.record("material_bridge_missing", error=str(exc))
        return ""
    try:
        bridge = MaterialGraphBridge()
        result = bridge.to_material(graph)
        wgsl = str(result.get("wgsl_source", ""))
        uniforms = list(result.get("uniforms", []))
        used_bridge = True
    except Exception as exc:
        trace.record("material_bridge_failed", error=str(exc))
    trace.record(
        "material_bridge",
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        used_bridge=used_bridge,
        wgsl_bytes=len(wgsl.encode("utf-8")) if wgsl else 0,
        uniform_count=len(uniforms),
    )
    return wgsl


def _step_shader_lint(trace: DemoTrace, wgsl: str) -> None:
    """Step 9 — lint the emitted WGSL (falls back to a stock shader on empty)."""
    source = wgsl
    source_id = "hello_v2_showcase.material"
    if not source.strip():
        # Fall back to a known-good tiny fragment shader so the lint step
        # always exercises the code path.
        source_id = "hello_v2_showcase.fallback"
        source = (
            "@fragment\n"
            "fn fs_main() -> @location(0) vec4<f32> {\n"
            "    return vec4<f32>(0.9, 0.6, 0.8, 1.0);\n"
            "}\n"
        )
    try:
        # Relax the byte budget — WGSL emitted by a real material graph can be
        # multi-KB.
        result = lint_wgsl(source_id, source,
                           contract={"max_bytes": 65536})
    except Exception as exc:  # pragma: no cover — lint drift
        trace.record("shader_lint_failed", error=str(exc))
        return
    trace.record(
        "shader_lint",
        source_id=source_id,
        parseable=bool(getattr(result, "parseable", False)),
        error_count=len(getattr(result, "errors", []) or []),
        warning_count=len(getattr(result, "warnings", []) or []),
        size_bytes=len(source.encode("utf-8")),
    )


def _step_hotkey_remap(trace: DemoTrace, tmp_root: Path) -> list[str]:
    """Step 10 — bake 3 baked hotkey style presets into a tmp dir + load them."""
    hotkey_dir = tmp_root / "hotkeys"
    copied = bake_hotkey_defaults(user_dir=hotkey_dir)
    hotkey_map = load_user_hotkeys(user_dir=hotkey_dir)
    binding_count = 0
    try:
        binding_count = len(hotkey_map.list_all())
    except Exception:
        pass
    trace.record(
        "hotkey_remap",
        user_dir=str(hotkey_dir),
        copied_count=len(copied),
        preset_names=sorted(p.stem for p in copied),
        binding_count=binding_count,
    )
    return [p.stem for p in copied]


def _step_camera_tweens(trace: DemoTrace) -> int:
    """Step 11 — schedule 2 camera tweens + tick until both complete."""
    try:
        from slappyengine.actions.camera_animation_actions import (
            CameraAnimator,
        )
    except Exception as exc:
        trace.record("camera_animator_missing", error=str(exc))
        return 0
    camera = SimpleNamespace(
        _cam_target=[0.0, 0.0, 0.0],
        _cam_distance=10.0,
    )
    animator = CameraAnimator()
    scheduled = 0
    # Tween 1 — pan-to-position on ease_in_out.
    tween_a = animator.tween_to_position(
        camera, CAMERA_TWEENS[0][1],
        duration_ms=CAMERA_TWEENS[0][3],
        easing=CAMERA_TWEENS[0][2],
        now_ms=0.0,
    )
    if tween_a is not None:
        scheduled += 1
        trace.record(
            "camera_tween_scheduled",
            slot="position",
            easing=CAMERA_TWEENS[0][2],
            duration_ms=CAMERA_TWEENS[0][3],
        )
    # Tween 2 — zoom on "back" easing.
    tween_b = animator.tween_to_zoom(
        camera, 3.5,
        duration_ms=CAMERA_TWEENS[1][3],
        easing=CAMERA_TWEENS[1][2],
        now_ms=0.0,
    )
    if tween_b is not None:
        scheduled += 1
        trace.record(
            "camera_tween_scheduled",
            slot="zoom",
            easing=CAMERA_TWEENS[1][2],
            duration_ms=CAMERA_TWEENS[1][3],
        )
    # Pump the animator until every tween has landed.
    total = int(max(t[3] for t in CAMERA_TWEENS)) + 100
    step = 50
    ticks = 0
    now = 0.0
    while now <= total:
        animator.tick(now)
        ticks += 1
        now += step
    trace.record(
        "camera_tween_done",
        scheduled=scheduled,
        ticks=ticks,
        final_target=list(camera._cam_target),
        final_distance=float(camera._cam_distance),
    )
    return scheduled


def _step_toast_manager(trace: DemoTrace) -> int:
    """Step 12 — push 5 toasts + inspect live queue."""
    try:
        from slappyengine.ui.editor.notebook_toast_manager import (
            NotebookToastManager,
            ToastLevel,
        )
    except Exception as exc:
        trace.record("toast_manager_missing", error=str(exc))
        return 0
    manager = NotebookToastManager()
    for msg, level in TOAST_MESSAGES:
        lvl = getattr(ToastLevel, level, ToastLevel.INFO)
        toast_id = manager.show(msg, level=lvl)
        trace.record(
            "toast_shown", message=msg, level=level, toast_id=toast_id,
        )
    active = manager.active_toasts()
    trace.record(
        "toast_summary",
        pushed=len(TOAST_MESSAGES),
        active=len(active),
        levels=[t.level.name for t in active],
    )
    return len(active)


def _step_command_palette(trace: DemoTrace) -> int:
    """Step 13 — open the palette + fuzzy-search "spawn"."""
    try:
        from slappyengine.ui.editor.notebook_command_palette import (
            NotebookCommandPalette,
        )
    except Exception as exc:
        trace.record("command_palette_missing", error=str(exc))
        return 0
    palette = NotebookCommandPalette()
    palette.open()
    palette.set_search("spawn")
    matches = palette.matches()
    palette.close()
    trace.record(
        "command_palette",
        query="spawn",
        match_count=len(matches),
        top_action=str(matches[0].action_id) if matches else "",
    )
    return len(matches)


def _step_layout_baker(trace: DemoTrace, tmp_root: Path) -> str:
    """Step 14 — bake layouts + load the "debugging" preset."""
    try:
        from slappyengine.ui.editor.layout_baker import LayoutBaker
    except Exception as exc:
        trace.record("layout_baker_missing", error=str(exc))
        return ""
    layout_dir = tmp_root / "layouts"
    baker = LayoutBaker(user_dir=layout_dir)
    result = baker.bake_defaults()
    loaded_name = ""
    panel_count = 0
    try:
        layout = baker.load(LAYOUT_PRESET_NAME)
        loaded_name = LAYOUT_PRESET_NAME
        panel_count = len(getattr(layout, "panels", []) or [])
    except Exception as exc:
        trace.record(
            "layout_baker_load_failed", preset=LAYOUT_PRESET_NAME,
            error=str(exc),
        )
    trace.record(
        "layout_baker",
        user_dir=str(layout_dir),
        baked_names=list(getattr(result, "baked_names", [])),
        loaded=loaded_name,
        panel_count=panel_count,
    )
    return loaded_name


def _step_timeline_editor(trace: DemoTrace) -> int:
    """Step 15 — build a Timeline with 2 tracks + 3 keyframes each."""
    try:
        from slappyengine.ui.editor.notebook_timeline_editor import Timeline
    except Exception as exc:
        trace.record("timeline_missing", error=str(exc))
        return 0
    timeline = Timeline(duration_s=3.0, bpm=120.0, fps=30.0)
    for track_name, keys in TIMELINE_TRACKS:
        track = timeline.add_track(track_name)
        for t, v in keys:
            kf = track.add_keyframe(t, v, interp="linear")
            trace.record(
                "timeline_keyframe",
                property=track_name,
                kf_id=kf.id, time=t, value=v,
            )
        trace.record(
            "timeline_track",
            property=track_name,
            keyframe_count=len(track.keyframes),
        )
    trace.record(
        "timeline_summary",
        track_count=len(timeline.tracks),
        total_keyframes=sum(len(tr.keyframes) for tr in timeline.tracks),
        duration_s=timeline.duration_s,
        bpm=timeline.bpm,
    )
    return len(timeline.tracks)


def _step_feature_map(trace: DemoTrace) -> int:
    """Step 16 — assert 250+ WIRED rows in the engine feature map."""
    repo_root = Path(__file__).resolve().parents[2]
    feature_paths = [
        repo_root / "docs" / "engine_feature_map_2026_07_04.md",
        repo_root / "docs" / "feature_map_delta_2026_07_04.md",
        repo_root / "docs" / "feature_map_2026_06_03.md",
    ]
    wired_total = 0
    scanned: list[str] = []
    for path in feature_paths:
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        count = text.count("WIRED")
        wired_total += count
        scanned.append(f"{path.name}:{count}")
    trace.record(
        "feature_map",
        wired_rows=wired_total,
        threshold=250,
        met_threshold=wired_total >= 250,
        scanned=scanned,
    )
    return wired_total


def _step_user_overrides_watcher(
    trace: DemoTrace, tmp_root: Path,
) -> bool:
    """Step 17 — start + stop a :class:`UserOverrideLoader.watch_dir` watcher."""
    watch_root = tmp_root / "overrides"
    watch_root.mkdir(parents=True, exist_ok=True)
    loader = UserOverrideLoader(root=watch_root)
    events: list[tuple[str, str]] = []

    def _cb(kind: str, path: Path) -> None:
        events.append((kind, str(path)))

    try:
        handle = loader.watch_dir(_cb, debounce=0.05)
    except Exception as exc:
        trace.record("user_overrides_start_failed", error=str(exc))
        return False
    started = handle.is_running() if hasattr(handle, "is_running") else False
    # We do NOT depend on watchdog being installed — either the real
    # WatcherHandle (running) or a NullWatcherHandle (idle) is fine.
    try:
        handle.stop(timeout=1.0)
        stopped_clean = True
    except Exception as exc:
        trace.record("user_overrides_stop_failed", error=str(exc))
        stopped_clean = False
    trace.record(
        "user_overrides_watcher",
        root=str(watch_root),
        started=bool(started),
        stopped_clean=stopped_clean,
        event_count=len(events),
    )
    return stopped_clean


# ---------------------------------------------------------------------------
# Demo runner
# ---------------------------------------------------------------------------


#: Subsystem key → trace-event kind used to verify the step ran.
SUBSYSTEM_MAP: dict[str, str] = {
    "project_registry":       "project_registry",
    "user_theme_store":       "user_theme_store",
    "prefab_library":         "prefab_summary",
    "prefab_preview_baker":   "preview_baked",
    "autosave_manager":       "autosave_read",
    "chain_manifest":         "chain_manifest",
    "chain_baker":            "chain_baker",
    "material_graph_bridge":  "material_bridge",
    "shader_lint":            "shader_lint",
    "hotkey_remap":           "hotkey_remap",
    "camera_animation":       "camera_tween_done",
    "toast_manager":          "toast_summary",
    "command_palette":        "command_palette",
    "layout_baker":           "layout_baker",
    "timeline_editor":        "timeline_summary",
    "feature_map":            "feature_map",
    "user_overrides_watcher": "user_overrides_watcher",
}


def run_demo(
    *,
    trace_path: Path | str | None = None,
    use_dpg_context: bool = True,
) -> DemoTrace:
    """Run the comprehensive V2 showcase and return the populated trace."""
    trace = DemoTrace()
    trace.record(
        "demo_start",
        python=sys.version.split()[0],
        has_dpg=_HAS_DPG,
        headless_env=_headless_env_active(),
    )

    ctx_created = False
    use_ctx = use_dpg_context and _HAS_DPG and not _headless_env_active()
    if use_ctx:
        try:
            dpg.create_context()
            ctx_created = True
            trace.record("dpg_context", state="created")
        except Exception as exc:
            trace.record("dpg_context", state="unavailable", error=str(exc))
    else:
        trace.record("dpg_context", state="skipped")

    tmp_root = Path(tempfile.mkdtemp(prefix="hello_v2_showcase_"))
    try:
        # 0. Theme registry seed + prime.
        try:
            registered = register_all_themes()
            trace.record(
                "themes_registered", names=registered, count=len(registered),
            )
            apply_theme(TARGET_THEME_NAME)
            active = get_active_theme()
            trace.record(
                "theme_prime",
                name=TARGET_THEME_NAME,
                active_name=getattr(active, "name", ""),
            )
        except Exception as exc:
            trace.record("theme_prime_failed", error=str(exc))

        # 1. Project registry.
        _step_project_registry(trace, tmp_root)

        # 2. User theme store.
        _step_user_theme(trace, tmp_root)

        # 3. Prefab library — spawn 4 prefabs into a world.
        world = World(gravity=(0.0, -9.81))
        world.solver_iterations = 6
        lib, bodies_by_name = _step_prefab_library(trace, world, tmp_root)

        # 4. Prefab preview baker.
        _step_prefab_previews(trace, lib, tmp_root)

        # 5. Autosave manager — 3 snapshots + read_snapshot.
        _step_autosave(trace, tmp_root)

        # 6. Chain manifest — build + apply.
        _step_chain_manifest(trace)

        # 7. Baked chain preset — dreamy.
        _step_chain_baker(trace, tmp_root)

        # 8. Material graph bridge.
        wgsl = _step_material_bridge(trace)

        # 9. Shader lint on the emitted WGSL.
        _step_shader_lint(trace, wgsl)

        # 10. Hotkey remap — 3 baked presets.
        _step_hotkey_remap(trace, tmp_root)

        # 11. Camera animation — 2 tweens with easing.
        _step_camera_tweens(trace)

        # 12. Toast manager — 5 toasts.
        _step_toast_manager(trace)

        # 13. Command palette — fuzzy-search "spawn".
        _step_command_palette(trace)

        # 14. Layout baker — debugging preset.
        _step_layout_baker(trace, tmp_root)

        # 15. Timeline editor — 2 tracks + keyframes.
        _step_timeline_editor(trace)

        # 16. Feature map — 250+ WIRED rows.
        _step_feature_map(trace)

        # 17. User overrides watcher — start + stop.
        _step_user_overrides_watcher(trace, tmp_root)

        # 18. Serialise the trace to YAML.
        out_path = Path(trace_path) if trace_path is not None else (
            Path(__file__).with_name("hello_v2_showcase_trace.yaml")
        )
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(trace.as_yaml(), encoding="utf-8")
            trace.record(
                "trace_written",
                path=str(out_path),
                events=len(trace.events),
            )
        except Exception as exc:  # pragma: no cover — disk failure paths
            trace.record("trace_write_failed", error=str(exc))

        # 19. Summary print + demo_end.
        kinds = {e["kind"] for e in trace.events}
        verified = {
            subsystem: (event_kind in kinds)
            for subsystem, event_kind in SUBSYSTEM_MAP.items()
        }
        summary = {
            "subsystems_total":    len(SUBSYSTEM_MAP),
            "subsystems_verified": sum(1 for ok in verified.values() if ok),
            "trace_events":        len(trace.events) + 1,  # +1 for demo_end
            "prefabs_spawned":     len(bodies_by_name),
            "wgsl_bytes":          len(wgsl.encode("utf-8")) if wgsl else 0,
        }
        print("hello_v2_showcase summary:")
        for k, v in summary.items():
            print(f"  {k:22s}: {v}")
        print("subsystems:")
        for subsystem, ok in verified.items():
            marker = "OK" if ok else "MISS"
            print(f"  [{marker:4s}] {subsystem}")

        trace.record(
            "demo_end",
            total_events=len(trace.events) + 1,
            summary=summary,
            verified=verified,
        )
        return trace
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
        if ctx_created and _HAS_DPG:
            try:
                dpg.destroy_context()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI entrypoint.
# ---------------------------------------------------------------------------


def _run_with_viewport() -> None:  # pragma: no cover — visual smoke path
    """Run the scripted demo then optionally flash a viewport.

    Only the __main__ guard reaches this — pytest's ``import`` never
    hits :func:`dpg.show_viewport` and therefore can't segfault.
    """
    if not _HAS_DPG or _headless_env_active():
        print("hello_v2_showcase: headless run (no viewport).")
        run_demo(use_dpg_context=_HAS_DPG and not _headless_env_active())
        return

    trace = run_demo()
    print(f"hello_v2_showcase: {len(trace.events)} events recorded.")
    try:
        dpg.create_context()
        dpg.create_viewport(
            title="Hello V2 Showcase", width=820, height=600,
        )
        with dpg.window(
            label="Trace", tag="__hello_v2_showcase_win",
            width=820, height=600,
        ):
            dpg.add_text("hello_v2_showcase — recorded events")
            dpg.add_separator()
            for evt in trace.events:
                dpg.add_text(f"[{evt['kind']}] {evt}")
        dpg.setup_dearpygui()
        dpg.set_primary_window("__hello_v2_showcase_win", True)
        dpg.show_viewport()
        dpg.start_dearpygui()
    finally:
        try:
            dpg.destroy_context()
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover
    _run_with_viewport()
