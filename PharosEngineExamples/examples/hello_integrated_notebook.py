"""hello_integrated_notebook — DiaryShell + notebook editor panels end-to-end.

W-batch sprint (2026-07-04) — task W6. Exercises the notebook-editor
family the way a real user session drives it, but headlessly so CI can
run the demo without opening a viewport.

What the demo does
------------------
1. Boots a :class:`DiaryShell` seeded with the 6 default pages (Scene /
   Code / Material / Animation / FX / Settings).
2. Registers 3 mock entities on a :class:`NotebookOutliner` via
   ``outliner.set_scene(mock_scene)``.
3. Programmatically walks Scene → Code → Material → Animation → FX →
   Settings and asserts every transition lands.
4. Applies each of the 6 built-in diary themes via a
   :class:`ThemeSwitcherPanel` and asserts the semantic colour vector
   actually mutates when the active theme changes.
5. Simulates an outliner ``on_select`` → inspector ``set_target`` flow
   and asserts the inspector materialises rows for the picked entity.
6. Records every step into a scripted trace and writes
   ``hello_integrated_notebook_trace.yaml`` next to this example.

Headless contract
-----------------
The whole demo runs *inside* a ``dpg.create_context()`` sandbox but
never calls the DPG ``show_viewport`` entrypoint — the DPG windows
exist in memory so the panels' item registrations succeed, but
nothing is painted. The ``if __name__ == "__main__":`` guard is the
only place the demo actually spins up a viewport so tests can import
+ call ``run_demo()`` without segfaulting.

Run:
    python PharosEngineExamples/examples/hello_integrated_notebook.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional DPG import guard — the demo still runs headless (no create_context)
# when Dear PyGui is missing so ``import`` never explodes in CI.
# ---------------------------------------------------------------------------

try:
    import dearpygui.dearpygui as dpg  # type: ignore
    _HAS_DPG = True
except Exception:  # pragma: no cover — DPG missing means headless path
    dpg = None  # type: ignore[assignment]
    _HAS_DPG = False


from pharos_editor.ui.editor.diary_shell import (
    DEFAULT_PAGES,
    DiaryShell,
    _resolve_panel_key,
)
from pharos_editor.ui.editor.notebook_inspector import NotebookInspector
from pharos_editor.ui.editor.notebook_outliner import NotebookOutliner
from pharos_editor.ui.editor.theme_switcher_panel import ThemeSwitcherPanel
from pharos_editor.ui.theme import (
    apply_theme,
    get_active_theme,
    list_registered_themes,
)
from pharos_editor.ui.theme.themes import register_all_themes


# ---------------------------------------------------------------------------
# Demo-local fixtures — mock scene + mock editor shell.
# ---------------------------------------------------------------------------

# Names of the six built-in diary themes the demo walks through.
DEMO_THEMES: tuple[str, ...] = (
    "teengirl_notebook",
    "cozy_diary",
    "bullet_journal",
    "scrapbook_summer",
    "cottagecore_garden",
    "kawaii_planner",
)

# Deliberate walk order — same order a first-run user would tab through.
PAGE_WALK: tuple[str, ...] = ("scene", "code", "material", "animation", "fx", "settings")


@dataclass
class MockEntity:
    """Minimal ``NotebookOutliner``-compatible entity.

    Uses a plain ``__dict__`` so :class:`NotebookInspector` reflects
    ``position`` / ``rotation`` / ``label`` into its three sections
    without needing a dataclass-of-dataclasses.
    """

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
    """The subset of a scene the outliner + shell touch."""

    entities: list[MockEntity] = field(default_factory=list)

    # NotebookOutliner.set_scene(scene) inspects ``scene.world`` first,
    # falling back to ``scene`` when the attribute is missing — matching
    # that either shape is fine, but the ``.entities`` list must be
    # visible on whatever ``world`` returns.
    @property
    def world(self) -> "MockScene":  # noqa: D401
        return self


class _FakeWrapper:
    """MovablePanelWindow stand-in — the diary shell only reads show/hide.

    Mirrors ``test_diary_shell._FakeWrapper`` so the demo behaves
    identically to the tests when DPG is missing (or headless).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self._visible = True
        self.show_calls = 0
        self.hide_calls = 0

    def show(self) -> None:
        self._visible = True
        self.show_calls += 1

    def hide(self) -> None:
        self._visible = False
        self.hide_calls += 1

    def is_visible(self) -> bool:
        return self._visible


class _FakeStatusBar:
    """DiaryShell only calls ``.set_message(msg, kind=...)`` on this."""

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def set_message(self, msg: str, kind: str = "info") -> None:
        self.messages.append((msg, kind))


class _MockShell:
    """The subset of :class:`EditorShell` the diary shell reads.

    Real ``EditorShell`` boot pulls in the Engine, layout persistence,
    project registry, etc. — none of that is needed to exercise the
    page-switch + panel-hide/show plumbing, so this stand-in wires the
    minimum attributes the shell dereferences.
    """

    def __init__(self) -> None:
        # Union of every default page's panel-id, resolved through the
        # PANEL_ID_ALIAS table — matches the pattern used by the diary
        # shell's own tests.
        panel_ids: set[str] = set()
        for page in DEFAULT_PAGES:
            for pid in page.panels:
                panel_ids.add(_resolve_panel_key(pid))
        self._panel_windows: dict[str, _FakeWrapper] = {
            pid: _FakeWrapper(pid) for pid in sorted(panel_ids)
        }
        self._notebook_status_bar = _FakeStatusBar()
        self._running = False
        # Keep apply_preset off the DPG path — bare dict + slot suffice.
        self._panel_layout_state: dict = {}
        self._active_layout_preset: str | None = None


# ---------------------------------------------------------------------------
# Trace recorder — the scripted trace serialised to YAML at demo end.
# ---------------------------------------------------------------------------


def _semantic_vector(theme: Any) -> list[list[int]]:
    """Return a stable ``[[r,g,b,a], ...]`` snapshot of the theme's semantic colours.

    Used to detect whether a theme swap actually mutates the on-screen
    colour surface. Falls back to the plain palette when ``theme.semantic``
    is missing so custom themes still produce a distinguishing vector.
    """
    semantic = getattr(theme, "semantic", None)
    if semantic is not None:
        out: list[list[int]] = []
        # SemanticTokens._COLOR_FIELDS is a ClassVar — read defensively.
        fields = getattr(type(semantic), "_COLOR_FIELDS", None) or (
            "primary", "secondary", "accent", "background",
            "surface", "text_primary",
        )
        for name in fields:
            tok = getattr(semantic, name, None)
            if tok is None:
                continue
            if hasattr(tok, "as_rgba_tuple"):
                try:
                    out.append(list(tok.as_rgba_tuple()))
                    continue
                except Exception:
                    pass
            out.append([0, 0, 0, 0])
        return out
    palette = getattr(theme, "palette", None)
    if palette is None:
        return []
    try:
        entries = dict(palette.entries) if hasattr(palette, "entries") else dict(palette)
    except Exception:
        return []
    out2: list[list[int]] = []
    for _key, value in sorted(entries.items()):
        if hasattr(value, "as_rgba_tuple"):
            try:
                out2.append(list(value.as_rgba_tuple()))
                continue
            except Exception:
                pass
        out2.append([0, 0, 0, 0])
    return out2


class DemoTrace:
    """Scripted event log — collected at every demo step and dumped to YAML."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def record(self, kind: str, **payload: Any) -> None:
        """Append one event. Values must be YAML-safe (str / int / list / …)."""
        entry: dict[str, Any] = {"kind": kind}
        entry.update(payload)
        self.events.append(entry)

    def as_yaml(self) -> str:
        """Serialise to YAML.

        Prefers ``pyyaml`` when installed (produces canonical output); falls
        back to a hand-rolled indented dumper so the demo still writes a
        parseable file when the optional dep is missing.
        """
        try:
            import yaml  # type: ignore

            return yaml.safe_dump(
                {"events": self.events, "event_count": len(self.events)},
                sort_keys=False,
            )
        except Exception:
            return _hand_yaml({"events": self.events, "event_count": len(self.events)})


def _hand_yaml(data: Any, indent: int = 0) -> str:
    """Minimal YAML dumper — only what the trace needs.

    Handles nested dicts, lists of dicts, lists of scalars, and scalars.
    Kept intentionally small: the demo runs whether or not pyyaml is
    installed, and the tests parse this back with pyyaml when available.
    """
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
                # Emit a `- ` list marker + inline first key
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
# Demo runner
# ---------------------------------------------------------------------------


def build_mock_scene() -> MockScene:
    """Create the 3-entity mock scene the demo drives.

    Deliberately three distinct :attr:`~MockEntity.kind` values so the
    outliner's badge library exercises multiple SVGs and the inspector
    rows differ per selection.
    """
    return MockScene(
        entities=[
            MockEntity(
                id="ent_a",
                name="pressed_dandelion",
                kind="mesh",
                label="folium",
                position=(10.0, 0.0, 0.0),
                rotation=0.0,
            ),
            MockEntity(
                id="ent_b",
                name="fox_specimen",
                kind="body",
                label="vulpes corpus",
                position=(-4.5, 2.0, 1.0),
                rotation=0.75,
            ),
            MockEntity(
                id="ent_c",
                name="lantern_bug",
                kind="light",
                label="sol",
                position=(0.0, 5.0, -2.0),
                rotation=1.57,
            ),
        ],
    )


def _register_themes() -> list[str]:
    """Ensure every built-in diary theme is in the registry.

    ``register_all_themes`` is idempotent so re-running the demo simply
    overwrites the entries with the same constants — no state carried
    from a previous run leaks into the trace.
    """
    return register_all_themes()


def run_demo(
    *,
    trace_path: Path | str | None = None,
    use_dpg_context: bool = True,
) -> DemoTrace:
    """Run the integrated notebook demo end-to-end and return the trace.

    Parameters
    ----------
    trace_path:
        Where to write the YAML trace. Defaults to
        ``hello_integrated_notebook_trace.yaml`` next to this file.
    use_dpg_context:
        When ``True`` and ``dearpygui`` is available, wrap the demo in
        a headless ``create_context`` / ``destroy_context`` pair. Tests
        can opt out to keep the DPG registry singleton clean.

    Returns
    -------
    DemoTrace
        The populated trace object; also written to *trace_path*.
    """
    trace = DemoTrace()
    trace.record("demo_start", python=sys.version.split()[0], has_dpg=_HAS_DPG)

    # ------------------------------------------------------------------
    # DPG bring-up — headless. We create a context so panel .build()
    # calls that reference DPG functions don't crash, but we **never**
    # call show_viewport() from within run_demo — the viewport lives
    # only under the ``__main__`` guard at the bottom of the file.
    # ------------------------------------------------------------------
    ctx_created = False
    if use_dpg_context and _HAS_DPG:
        try:
            dpg.create_context()
            ctx_created = True
            trace.record("dpg_context", state="created")
        except Exception as exc:
            # DPG's global context is single-instance; a create_context
            # after a prior destroy sometimes needs a fresh interpreter.
            # Fall through headless — the panels still exercise cleanly.
            trace.record("dpg_context", state="unavailable", error=str(exc))
    else:
        trace.record("dpg_context", state="skipped")

    try:
        # --------------------------------------------------------------
        # Step 1 — theme registry seed.
        # --------------------------------------------------------------
        registered = _register_themes()
        trace.record("themes_registered", names=registered, count=len(registered))
        # Prime the active theme so subsequent panel .build() calls that
        # ask for get_active_theme() don't hit the "no theme active"
        # LookupError.
        apply_theme(DEMO_THEMES[0])
        trace.record("theme_prime", name=DEMO_THEMES[0])

        # --------------------------------------------------------------
        # Step 2 — build the mock shell + diary shell.
        # --------------------------------------------------------------
        shell = _MockShell()
        diary = DiaryShell(shell)
        diary.build()
        trace.record(
            "diary_built",
            page_count=len(diary.list_pages()),
            page_ids=[p.id for p in diary.list_pages()],
            active=diary.get_active_page_id(),
        )

        # --------------------------------------------------------------
        # Step 3 — outliner registration + scene binding.
        # --------------------------------------------------------------
        selected_ref: dict[str, Any] = {"entity": None}

        def _on_select(entity: Any) -> None:
            selected_ref["entity"] = entity

        outliner = NotebookOutliner(world_getter=lambda: None, on_select=_on_select)
        scene = build_mock_scene()
        outliner.set_scene(scene)
        rows = outliner.iter_rows()
        trace.record(
            "outliner_scene_bound",
            entity_count=len(scene.entities),
            outliner_rows=len(rows),
            row_names=[r["name"] for r in rows],
        )
        # Cross-check: every mock entity produced a row.
        assert len(rows) == len(scene.entities), (
            f"outliner should surface {len(scene.entities)} rows, got {len(rows)}"
        )

        # --------------------------------------------------------------
        # Step 4 — walk every page and record the transition.
        # --------------------------------------------------------------
        for page_id in PAGE_WALK:
            before = diary.get_active_page_id()
            page = diary.switch_page(page_id)
            after = diary.get_active_page_id()
            assert after == page_id, (
                f"switch_page({page_id!r}) landed on {after!r}"
            )
            trace.record(
                "page_switch",
                from_page=before,
                to_page=after,
                label=page.label,
                preset=page.default_layout_preset,
                switch_count=diary.switch_count,
            )

        # --------------------------------------------------------------
        # Step 5 — theme switcher: apply each theme, verify the semantic
        # colour vector actually mutates between successive applications.
        # --------------------------------------------------------------
        switcher = ThemeSwitcherPanel()
        # Not calling switcher.build() — the panel's build path needs a
        # real DPG parent container, and the demo's contract is that the
        # panel's semantic-swap behaviour is what we care about, which
        # runs entirely through :func:`apply_theme`.
        previous_vec: list[list[int]] | None = None
        for theme_id in DEMO_THEMES:
            switcher._on_theme_card_clicked(theme_id)  # noqa: SLF001 — public flow
            active = get_active_theme()
            vec = _semantic_vector(active)
            mutated = previous_vec is None or vec != previous_vec
            trace.record(
                "theme_applied",
                theme_id=theme_id,
                active_name=active.name,
                sample_color=vec[0] if vec else [],
                vector_length=len(vec),
                mutated=mutated,
            )
            assert active.name == theme_id, (
                f"active theme {active.name!r} != requested {theme_id!r}"
            )
            assert mutated, (
                f"applying {theme_id!r} did not mutate the semantic colour vector"
            )
            previous_vec = vec

        # --------------------------------------------------------------
        # Step 6 — outliner→inspector selection flow.
        # --------------------------------------------------------------
        inspector = NotebookInspector()
        # Bind the outliner's on_select to the inspector's set_target so a
        # row-click populates the field-journal automatically. Mimics
        # what EditorShell.setup() wires in production.
        outliner.set_on_select(inspector.set_target)

        for entity in scene.entities:
            outliner._handle_select(entity)  # noqa: SLF001 — mimic real click path
            assert inspector.target is entity, (
                f"inspector.target should track outliner selection"
            )
            fields = inspector._iter_fields()  # noqa: SLF001 — inspection API
            trace.record(
                "entity_selected",
                entity_id=entity.id,
                entity_name=entity.name,
                inspector_field_count=len(fields),
                inspector_field_names=[name for name, _ in fields],
            )
            assert len(fields) > 0, (
                f"inspector produced no rows for {entity.name!r}"
            )

        # --------------------------------------------------------------
        # Step 7 — dump trace to disk.
        # --------------------------------------------------------------
        out_path = Path(trace_path) if trace_path is not None else (
            Path(__file__).with_name("hello_integrated_notebook_trace.yaml")
        )
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(trace.as_yaml(), encoding="utf-8")
            trace.record("trace_written", path=str(out_path), events=len(trace.events))
        except Exception as exc:  # pragma: no cover — disk failure paths
            trace.record("trace_write_failed", error=str(exc))

        trace.record("demo_end", total_events=len(trace.events))
        return trace
    finally:
        if ctx_created and _HAS_DPG:
            try:
                dpg.destroy_context()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI entrypoint — only place a live viewport ever spins up.
# ---------------------------------------------------------------------------


def _run_with_viewport() -> None:  # pragma: no cover — visual smoke path
    """Run the demo, then flash a viewport so a human can eyeball the panels.

    Only invoked from ``__main__`` so pytest's ``import`` never trips
    the segfault-prone ``show_viewport()``.
    """
    if not _HAS_DPG:
        print("dearpygui not installed — running headless demo only.")
        run_demo()
        return

    # Run the scripted trace headlessly first so the YAML is on disk
    # regardless of whether the viewport survives.
    trace = run_demo()
    print(f"hello_integrated_notebook: {len(trace.events)} events recorded.")

    # Now a lightweight preview — a single window listing the trace so
    # the demo *shows* something on the screen without wiring up the
    # entire editor.
    try:
        dpg.create_context()
        dpg.create_viewport(title="Hello Integrated Notebook", width=720, height=520)
        with dpg.window(label="Trace", tag="__hello_trace_win", width=720, height=520):
            dpg.add_text("hello_integrated_notebook — recorded events")
            dpg.add_separator()
            for evt in trace.events:
                dpg.add_text(f"[{evt['kind']}] {evt}")
        dpg.setup_dearpygui()
        dpg.set_primary_window("__hello_trace_win", True)
        dpg.show_viewport()
        dpg.start_dearpygui()
    finally:
        try:
            dpg.destroy_context()
        except Exception:
            pass


if __name__ == "__main__":  # pragma: no cover
    _run_with_viewport()
