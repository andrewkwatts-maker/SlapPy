"""hello_full_editor — end-to-end DiaryShell editor sandbox.

AA-batch sprint (task AA5, 2026-07-05). Ties every notebook-editor
subsystem together in one scripted run so CI can lock the "full first
session" a real user experiences on their first boot of the editor:

1. Boots :class:`DiaryShell` seeded with the 6 default pages
   (Scene / Code / Material / Animation / FX / Settings).
2. Spawns 3 baked prefabs (crate, ball, chain) into a shared
   :class:`pharos_engine.dynamics.World` via :class:`PrefabLibrary`.
   Prefers ``lib.spawn(name, world, pos)`` (AA2 shape) if it exists,
   otherwise falls back to ``lib.get(name).spawn(world, pos)``.
3. Switches to the Scene page + fires 5 outliner selects.
4. Switches to the Material page + creates a 3-node graph. If AA4's
   :class:`MaterialGraphBridge` is available it drives that; otherwise
   the demo assembles a :class:`NodeGraph` directly via
   ``add_node`` / ``add_edge``.
5. Switches to the FX page + loads the "dreamy" baked post-process
   chain preset via :class:`ChainBaker`.
6. Switches to the Code page + evaluates a Python expression via
   :func:`pharos_engine.math.evaluate`.
7. Wires an :class:`AutosaveManager` with ``interval_seconds=1``,
   ticks it three times via :meth:`force_save`, and prints the last
   snapshot path.
8. Applies each of the 6 built-in diary themes in sequence.
9. Records every step into ``hello_full_editor_trace.yaml`` (≥ 25
   events).
10. Prints a compact summary + returns the trace.

Headless contract
-----------------
The demo is careful to keep :func:`dpg.show_viewport` behind the
``if __name__ == "__main__":`` guard. When
``SLAPPY_HEADLESS=1`` is set the demo skips
:func:`dpg.create_context` entirely (mirrors the Z4 pattern from
``notebook_message_log``) — this avoids the Windows access-violation
that hits when the real DPG module is imported before create_context
on some CI configurations.

Run:
    python SlapPyEngineExamples/examples/hello_full_editor.py
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

from pharos_engine.autosave import AutosaveManager, AutosaveState
from pharos_engine.dynamics import World
from pharos_engine.math import evaluate
from pharos_engine.prefabs import PrefabLibrary
from pharos_engine.ui.editor.diary_shell import (
    DEFAULT_PAGES,
    DiaryShell,
    _resolve_panel_key,
)
from pharos_engine.ui.editor.notebook_inspector import NotebookInspector
from pharos_engine.ui.editor.notebook_outliner import NotebookOutliner
from pharos_engine.ui.editor.theme_switcher_panel import ThemeSwitcherPanel
from pharos_engine.ui.theme import apply_theme, get_active_theme
from pharos_engine.ui.theme.themes import register_all_themes
from pharos_engine.visual_scripting.graph import NodeGraph
from pharos_engine.visual_scripting.node import Node, NodePort


# ---------------------------------------------------------------------------
# Public demo constants.
# ---------------------------------------------------------------------------

# The 6 themes DiaryShell ships with — walked in this order in step 8.
DEMO_THEMES: tuple[str, ...] = (
    "teengirl_notebook",
    "cozy_diary",
    "bullet_journal",
    "scrapbook_summer",
    "cottagecore_garden",
    "kawaii_planner",
)

# Which prefabs to spawn (step 2). Matched against ``PrefabLibrary`` after
# ``bake_defaults`` + ``load_from_dir`` populate the registry.
PREFAB_SPAWNS: tuple[tuple[str, tuple[float, float]], ...] = (
    ("crate", (-3.0, 3.0)),
    ("ball",  ( 0.0, 3.0)),
    ("chain", ( 3.0, 4.0)),
)

# Which outliner rows to click on the Scene page (step 3). The scene
# below has 5 entities so every click lands on a real row.
SCENE_ENTITY_IDS: tuple[str, ...] = (
    "ent_crate", "ent_ball", "ent_chain",
    "ent_light", "ent_camera",
)

# The 3 material nodes we assemble in step 4 (constant → gain → output).
MATERIAL_NODE_SPEC: tuple[dict[str, Any], ...] = (
    {
        "id": "mat_input",
        "node_type": "math.constant",
        "kind": "math",
        "outputs": [("value", "float", 1.0)],
        "params": {"value": 1.0},
    },
    {
        "id": "mat_gain",
        "node_type": "math.mul",
        "kind": "math",
        "inputs": [("a", "float", 1.0), ("b", "float", 0.5)],
        "outputs": [("product", "float", 0.0)],
    },
    {
        "id": "mat_output",
        "node_type": "render.material_out",
        "kind": "render",
        "inputs": [("albedo", "float", 0.0)],
    },
)

# Baked PP chain preset that step 5 loads.
FX_PRESET_NAME: str = "dreamy"

# The Python expression step 6 asks pharos_engine.math.evaluate to run.
CODE_EXPRESSION: str = "sin(x) * a + b"


# ---------------------------------------------------------------------------
# Diary-shell + notebook plumbing stand-ins (mirrors hello_integrated_notebook).
# ---------------------------------------------------------------------------


@dataclass
class MockEntity:
    """Minimal outliner-compatible entity — three transform fields + a label."""

    id: str
    name: str
    kind: str = "entity"
    label: str = "specimen"
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: float = 0.0
    visible: bool = True
    locked: bool = False


@dataclass
class MockScene:
    """The subset of ``Scene`` the outliner + shell touch."""

    entities: list[MockEntity] = field(default_factory=list)

    @property
    def world(self) -> "MockScene":  # noqa: D401
        return self


class _FakeWrapper:
    """Stand-in for ``MovablePanelWindow`` — only show/hide are used."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._visible = True

    def show(self) -> None:
        self._visible = True

    def hide(self) -> None:
        self._visible = False

    def is_visible(self) -> bool:
        return self._visible


class _FakeStatusBar:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def set_message(self, msg: str, kind: str = "info") -> None:
        self.messages.append((msg, kind))


class _MockShell:
    """The subset of :class:`EditorShell` the diary shell dereferences."""

    def __init__(self) -> None:
        panel_ids: set[str] = set()
        for page in DEFAULT_PAGES:
            for pid in page.panels:
                panel_ids.add(_resolve_panel_key(pid))
        self._panel_windows: dict[str, _FakeWrapper] = {
            pid: _FakeWrapper(pid) for pid in sorted(panel_ids)
        }
        self._notebook_status_bar = _FakeStatusBar()
        self._running = False
        self._panel_layout_state: dict = {}
        self._active_layout_preset: str | None = None


# ---------------------------------------------------------------------------
# Trace recorder (borrowed shape from hello_integrated_notebook).
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
# Scene / prefab / material helpers.
# ---------------------------------------------------------------------------


def build_scene() -> MockScene:
    """Return a 5-entity scene so step 3 has 5 rows to click through."""
    return MockScene(entities=[
        MockEntity(id="ent_crate", name="crate_alpha",
                   kind="body", label="wooden crate",
                   position=(-3.0, 3.0, 0.0)),
        MockEntity(id="ent_ball", name="ball_beta",
                   kind="body", label="rubber ball",
                   position=(0.0, 3.0, 0.0)),
        MockEntity(id="ent_chain", name="chain_gamma",
                   kind="chain", label="iron links",
                   position=(3.0, 4.0, 0.0)),
        MockEntity(id="ent_light", name="lantern_delta",
                   kind="light", label="sun lantern",
                   position=(0.0, 8.0, -2.0)),
        MockEntity(id="ent_camera", name="orbit_epsilon",
                   kind="camera", label="main cam",
                   position=(6.0, 5.0, 6.0)),
    ])


def _spawn_prefabs(
    library: PrefabLibrary,
    world: World,
    trace: DemoTrace,
) -> dict[str, list]:
    """Spawn each :data:`PREFAB_SPAWNS` entry — soft-import AA2 shape.

    Prefers ``library.spawn(name, world, pos)`` when the AA2 sugar
    landed. Falls back to ``library.get(name).spawn(world, pos)`` when
    it hasn't (which is the current baseline API).
    """
    spawn_sugar = getattr(library, "spawn", None)
    bodies_by_name: dict[str, list] = {}
    for name, pos in PREFAB_SPAWNS:
        if callable(spawn_sugar):
            try:
                bodies = spawn_sugar(name, world, pos)
                trace.record(
                    "prefab_spawned",
                    name=name, pos=list(pos),
                    body_count=len(bodies) if bodies is not None else 0,
                    via="library.spawn",
                )
                bodies_by_name[name] = list(bodies or [])
                continue
            except Exception as exc:  # pragma: no cover — AA2 shape drift
                trace.record(
                    "prefab_spawn_sugar_failed",
                    name=name, error=str(exc),
                )
        prefab = library.get(name)
        if prefab is None:
            trace.record("prefab_missing", name=name)
            continue
        bodies = prefab.spawn(world, pos)
        bodies_by_name[name] = list(bodies)
        trace.record(
            "prefab_spawned",
            name=name, pos=list(pos),
            body_count=len(bodies),
            via="prefab.spawn",
        )
    return bodies_by_name


def _build_material_graph(trace: DemoTrace) -> NodeGraph:
    """Assemble a 3-node material-ish graph.

    The graph itself is always built via direct :meth:`NodeGraph.add_node`
    calls (the current visual_scripting API). When AA4's
    :class:`MaterialGraphBridge` is available it's fed the finished graph
    via :meth:`MaterialGraphBridge.to_material` so the WGSL compile path
    is also exercised end-to-end.
    """
    graph = NodeGraph(name="hello_full_editor_material")

    # 1. Populate the 3 nodes + 2 wires.
    for spec in MATERIAL_NODE_SPEC:
        inputs = [
            NodePort(name=n, port_kind=k, default=d)
            for (n, k, d) in spec.get("inputs", [])
        ]
        outputs = [
            NodePort(name=n, port_kind=k, default=d)
            for (n, k, d) in spec.get("outputs", [])
        ]
        node = Node(
            node_type=spec["node_type"],
            kind=spec["kind"],
            inputs=inputs,
            outputs=outputs,
            params=dict(spec.get("params", {})),
            id=spec["id"],
        )
        graph.add_node(node)
    # Wire constant → gain.a and gain.product → output.albedo.
    graph.add_edge("mat_input", "value", "mat_gain", "a")
    graph.add_edge("mat_gain", "product", "mat_output", "albedo")

    # 2. Soft-poke AA4's bridge — if the WGSL compile succeeds we log it,
    #    otherwise the graph itself is enough for the tests + trace.
    used_bridge = False
    bridge_result: dict[str, Any] | None = None
    try:  # pragma: no cover — AA4 optional
        from pharos_engine.ui.editor.material_graph_bridge import (
            MaterialGraphBridge,  # type: ignore
        )
        try:
            bridge_result = MaterialGraphBridge().to_material(graph)
            used_bridge = True
        except Exception as exc:
            trace.record("material_bridge_failed", error=str(exc))
    except Exception:
        pass

    trace.record(
        "material_graph_built",
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        used_bridge=used_bridge,
        node_ids=[n.id for n in graph.nodes],
        bridge_output_keys=list(bridge_result.keys()) if bridge_result else [],
    )
    return graph


def _load_fx_preset(trace: DemoTrace) -> str:
    """Load the "dreamy" baked PP chain preset via :class:`ChainBaker`.

    The panel-level ``apply_preset`` only knows the three shell
    presets (cinematic/arcade/iso_strategy); the six baked chain
    presets (default/crisp/dreamy/neon/retro_film/debug) come from
    :class:`ChainBaker`. We hit the baker directly so ``dreamy``
    round-trips through YAML end-to-end.
    """
    tmp_user = Path(tempfile.mkdtemp(prefix="hello_full_editor_fx_"))
    try:
        from pharos_engine.post_process import ChainBaker

        baker = ChainBaker(user_dir=tmp_user)
        baker.bake_defaults()
        try:
            ChainBaker.register_stub_handlers()
        except Exception:
            pass
        manifest = baker.load(FX_PRESET_NAME)
        pass_count = len(getattr(manifest, "passes", []) or [])
        trace.record(
            "fx_preset_loaded",
            preset=FX_PRESET_NAME,
            pass_count=pass_count,
            user_dir=str(tmp_user),
        )
        return FX_PRESET_NAME
    finally:
        shutil.rmtree(tmp_user, ignore_errors=True)


# ---------------------------------------------------------------------------
# Autosave wiring.
# ---------------------------------------------------------------------------


def _run_autosave(trace: DemoTrace) -> Path | None:
    """Tick :class:`AutosaveManager` three times and record every snapshot."""
    snap_dir = Path(tempfile.mkdtemp(prefix="hello_full_editor_autosave_"))
    try:
        state = AutosaveState(
            enabled=True,
            interval_seconds=1.0,
            snapshot_dir=snap_dir,
            max_snapshots=5,
        )
        project = SimpleNamespace(name="hello_full_editor")
        counter = {"n": 0}

        def payload_cb() -> dict:
            counter["n"] += 1
            return {
                "iteration": counter["n"],
                "notebook_text": "editor session " * counter["n"],
                "when": time.time(),
            }

        manager = AutosaveManager(state, project, payload_cb)
        for i in range(3):
            path = manager.force_save()
            trace.record(
                "autosave_snapshot",
                index=i,
                path=str(path),
                iteration=counter["n"],
            )
            # Tiny sleep so the timestamp component of the filename ticks;
            # avoids two ticks colliding on the same second-resolution stem.
            time.sleep(0.01)
        snapshots = manager.list_snapshots()
        latest = snapshots[0] if snapshots else None
        trace.record(
            "autosave_done",
            snapshot_count=len(snapshots),
            latest=str(latest) if latest is not None else None,
        )
        return latest
    finally:
        # ``force_save`` doesn't start the timer thread so no ``stop`` is
        # strictly needed, but keep the tmpdir cleanup deterministic.
        shutil.rmtree(snap_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Prefab library boot.
# ---------------------------------------------------------------------------


def _boot_library() -> PrefabLibrary:
    """Bake defaults into a temp dir + load them so ``spawn`` finds every prefab."""
    lib = PrefabLibrary()
    tmp = Path(tempfile.mkdtemp(prefix="hello_full_editor_prefab_"))
    lib.bake_defaults(user_dir=tmp)
    lib.load_from_dir(tmp)
    return lib


# ---------------------------------------------------------------------------
# Demo runner.
# ---------------------------------------------------------------------------


def run_demo(
    *,
    trace_path: Path | str | None = None,
    use_dpg_context: bool = True,
) -> DemoTrace:
    """Run the full editor sandbox and return the populated trace."""
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

    try:
        # 0. Theme registry seed + prime.
        registered = register_all_themes()
        trace.record(
            "themes_registered",
            names=registered,
            count=len(registered),
        )
        apply_theme(DEMO_THEMES[0])
        trace.record("theme_prime", name=DEMO_THEMES[0])

        # 1. DiaryShell — 6 default pages.
        shell = _MockShell()
        diary = DiaryShell(shell)
        diary.build()
        trace.record(
            "diary_built",
            page_count=len(diary.list_pages()),
            page_ids=[p.id for p in diary.list_pages()],
            active=diary.get_active_page_id(),
        )

        # 2. Prefab library + world + spawn 3 prefabs.
        library = _boot_library()
        world = World(gravity=(0.0, -9.81))
        world.solver_iterations = 8
        bodies_by_name = _spawn_prefabs(library, world, trace)
        trace.record(
            "prefabs_summary",
            spawned=list(bodies_by_name.keys()),
            body_count=sum(len(bs) for bs in bodies_by_name.values()),
            node_count=int(world.positions.shape[0]),
        )

        # 3. Scene page + 5 outliner selects.
        diary.switch_page("scene")
        trace.record(
            "page_switch",
            to_page="scene",
            switch_count=diary.switch_count,
        )
        selected_ref: dict[str, Any] = {"entity": None}

        def _on_select(entity: Any) -> None:
            selected_ref["entity"] = entity

        outliner = NotebookOutliner(
            world_getter=lambda: None,
            on_select=_on_select,
        )
        scene = build_scene()
        outliner.set_scene(scene)
        inspector = NotebookInspector()
        outliner.set_on_select(inspector.set_target)
        by_id = {e.id: e for e in scene.entities}
        for ent_id in SCENE_ENTITY_IDS:
            ent = by_id.get(ent_id)
            if ent is None:
                trace.record("outliner_missing_entity", entity_id=ent_id)
                continue
            outliner._handle_select(ent)  # noqa: SLF001 — click flow
            fields = inspector._iter_fields()  # noqa: SLF001 — inspection
            trace.record(
                "outliner_select",
                entity_id=ent_id,
                entity_name=ent.name,
                inspector_field_count=len(fields),
            )

        # 4. Material page + 3-node graph.
        diary.switch_page("material")
        trace.record(
            "page_switch",
            to_page="material",
            switch_count=diary.switch_count,
        )
        material_graph = _build_material_graph(trace)
        # Validate the graph — must not raise; empty error list means a
        # clean topology (or the bridge produced something structural).
        try:
            errors = material_graph.validate(raise_on_error=False)
        except Exception as exc:
            errors = [f"validate raised {type(exc).__name__}: {exc}"]
        trace.record(
            "material_graph_validated",
            error_count=len(errors),
            errors=errors[:3],
        )

        # 5. FX page + dreamy PP chain.
        diary.switch_page("fx")
        trace.record(
            "page_switch",
            to_page="fx",
            switch_count=diary.switch_count,
        )
        preset_name = _load_fx_preset(trace)
        trace.record("fx_preset_applied", preset=preset_name)

        # 6. Code page + evaluate an expression.
        diary.switch_page("code")
        trace.record(
            "page_switch",
            to_page="code",
            switch_count=diary.switch_count,
        )
        code_bindings = {"x": 0.5, "a": 2.0, "b": 3.0}
        try:
            code_value = float(evaluate(CODE_EXPRESSION, **code_bindings))
            code_ok = True
            code_err = ""
        except Exception as exc:
            code_value = 0.0
            code_ok = False
            code_err = str(exc)
        trace.record(
            "code_evaluated",
            expression=CODE_EXPRESSION,
            bindings=code_bindings,
            value=code_value,
            ok=code_ok,
            error=code_err,
        )

        # 7. Autosave — three snapshots at interval_seconds=1.
        latest_snap = _run_autosave(trace)
        trace.record(
            "autosave_summary",
            latest=str(latest_snap) if latest_snap is not None else None,
        )
        # Print the last snapshot path (per demo contract).
        print(f"hello_full_editor: last autosave snapshot: {latest_snap}")

        # 8. Apply each of the 6 diary themes in sequence.
        switcher = ThemeSwitcherPanel()
        for theme_id in DEMO_THEMES:
            switcher._on_theme_card_clicked(theme_id)  # noqa: SLF001 — public flow
            active = get_active_theme()
            trace.record(
                "theme_applied",
                theme_id=theme_id,
                active_name=active.name,
            )

        # 9. Serialise the trace to YAML.
        out_path = Path(trace_path) if trace_path is not None else (
            Path(__file__).with_name("hello_full_editor_trace.yaml")
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

        # 10. Summary print + demo_end.
        summary = {
            "prefabs_spawned": len(bodies_by_name),
            "material_nodes": len(material_graph.nodes),
            "fx_preset": preset_name,
            "code_value": code_value,
            "themes_applied": len(DEMO_THEMES),
            "trace_events": len(trace.events) + 1,  # +1 for demo_end below
        }
        print("hello_full_editor summary:")
        for k, v in summary.items():
            print(f"  {k:16s}: {v}")

        trace.record("demo_end", total_events=len(trace.events) + 1,
                     summary=summary)
        return trace
    finally:
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
        print("hello_full_editor: headless run (no viewport).")
        run_demo(use_dpg_context=_HAS_DPG and not _headless_env_active())
        return

    trace = run_demo()
    print(f"hello_full_editor: {len(trace.events)} events recorded.")
    try:
        dpg.create_context()
        dpg.create_viewport(
            title="Hello Full Editor", width=760, height=560,
        )
        with dpg.window(
            label="Trace", tag="__hello_full_editor_win",
            width=760, height=560,
        ):
            dpg.add_text("hello_full_editor — recorded events")
            dpg.add_separator()
            for evt in trace.events:
                dpg.add_text(f"[{evt['kind']}] {evt}")
        dpg.setup_dearpygui()
        dpg.set_primary_window("__hello_full_editor_win", True)
        dpg.show_viewport()
        dpg.start_dearpygui()
    finally:
        try:
            dpg.destroy_context()
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover
    _run_with_viewport()
