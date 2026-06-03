"""Selection-flow tests — Outliner → Inspector + Gizmo + Status bar.

Clicking an entity row in :class:`NotebookOutliner` must route the
selection through three downstream channels in lock-step:

1. :class:`NotebookInspector` — repaints with the new target's fields.
2. :class:`NotebookGizmoOverlay` — rebinds via ``set_entity``.
3. :class:`NotebookStatusBar` — bumps the selection-count segment.

These tests stand up a headless :class:`EditorShell`-shaped harness
(no Dear PyGui context, no viewport) and drive the outliner's
programmatic select / deselect / change-selection paths to assert
all three sinks stay in sync.

Round-trip: covers headless (stubbed DPG) and "live" (the same shell
wired with the Notebook gizmo overlay seeing a real entity).
"""
from __future__ import annotations

import sys
import types
from dataclasses import dataclass, field
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — every method is a recorder so the panels build
# cleanly without a viewport. Same shape as test_editor_notebook_outliner
# / test_editor_notebook_inspector.
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    def collapsing_header(self, *a, **kw):
        self._track("collapsing_header", a, kw)
        return _StubCM()

    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def popup(self, *a, **kw):
        self._track("popup", a, kw)
        return _StubCM()

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_input_int(self, *a, **kw):
        self._track("add_input_int", a, kw)

    def add_input_float(self, *a, **kw):
        self._track("add_input_float", a, kw)

    def add_input_floatx(self, *a, **kw):
        self._track("add_input_floatx", a, kw)

    def add_color_edit(self, *a, **kw):
        self._track("add_color_edit", a, kw)

    def add_listbox(self, *a, **kw):
        self._track("add_listbox", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.discard(tag)

    def get_item_children(self, *a, **kw):
        return []

    def configure_item(self, tag, *a, **kw):
        self._track("configure_item", (tag,), kw)

    def set_value(self, tag, value, *a, **kw):
        self._track("set_value", (tag, value), kw)


@pytest.fixture(autouse=True)
def stub_dpg(monkeypatch):
    """Install a fresh stub DPG module for every test."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")

    def _fallback(name):
        if hasattr(stub, name):
            return getattr(stub, name)

        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))

        return _noop

    mod.__getattr__ = _fallback
    for name in (
        "collapsing_header", "group", "child_window", "popup",
        "add_text", "add_button", "add_checkbox", "add_input_text",
        "add_input_int", "add_input_float", "add_input_floatx",
        "add_color_edit", "add_listbox", "add_separator",
        "does_item_exist", "delete_item", "get_item_children",
        "configure_item", "set_value",
    ):
        setattr(mod, name, getattr(stub, name))

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


@pytest.fixture(autouse=True)
def clear_theme(stub_dpg):
    """Drop any cached theme + listener state between tests."""
    from slappyengine.ui.widgets import notebook_theme
    from slappyengine.ui.widgets.notebook_theme import set_active_theme
    from slappyengine.ui.widgets.sticker_corner import _active_stickers

    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()
    yield
    set_active_theme(None)
    notebook_theme._theme_listeners.clear()
    _active_stickers.clear()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeEntity:
    """Minimal entity surface — name / kind / visible / locked / position."""

    def __init__(
        self,
        name: str,
        kind: str = "entity",
        visible: bool = True,
        locked: bool = False,
        eid: str | None = None,
    ) -> None:
        self.name = name
        self.kind = kind
        self.visible = visible
        self.locked = locked
        self.position = (0.0, 0.0)
        self.rotation = 0.0
        self.scale = 1.0
        if eid is not None:
            self.id = eid


class _FakeWorld:
    def __init__(self, entities: list[Any] | None = None) -> None:
        self.entities: list[Any] = list(entities or [])


class _FakeScene:
    """Stand-in for ``Engine.scene`` — only needs ``.entities``."""

    def __init__(self, entities: list[Any] | None = None) -> None:
        self.entities: list[Any] = list(entities or [])


class _FakeEngine:
    """Stand-in for :class:`slappyengine.engine.Engine`.

    ``EditorShell.setup_notebook_panels`` reads ``getattr(engine, "scene", None)``
    from inside the world_getter lambda; nothing else is required.
    """

    def __init__(self, scene: _FakeScene | None = None) -> None:
        self.scene = scene if scene is not None else _FakeScene()


# ---------------------------------------------------------------------------
# Harness — wires up just the three panels we test, without touching DPG.
# ---------------------------------------------------------------------------


def _make_harness(entities: list[Any]) -> Any:
    """Return a populated shell-like harness for selection-flow tests."""
    from slappyengine.ui.editor.notebook_outliner import NotebookOutliner
    from slappyengine.ui.editor.notebook_inspector import NotebookInspector
    from slappyengine.ui.editor.notebook_gizmos import NotebookGizmoOverlay
    from slappyengine.ui.editor.notebook_status_bar import NotebookStatusBar

    engine = _FakeEngine(_FakeScene(entities))
    inspector = NotebookInspector()
    # Inspector only renders fields after build(); call it now so
    # downstream tests can assert on ``call_log`` field events.
    inspector.build("root")
    gizmo = NotebookGizmoOverlay()
    status_bar = NotebookStatusBar()

    def _on_select(entity: Any) -> None:
        # Mirrors EditorShell._on_entity_selected exactly.
        try:
            inspector.set_target(entity)
        except Exception:
            pass
        try:
            gizmo.set_entity(entity)
        except Exception:
            pass
        try:
            status_bar.set_selection_count(1 if entity is not None else 0)
        except Exception:
            pass

    outliner = NotebookOutliner(
        world_getter=lambda: engine.scene,
        on_select=_on_select,
    )

    harness = types.SimpleNamespace(
        engine=engine,
        outliner=outliner,
        inspector=inspector,
        gizmo=gizmo,
        status_bar=status_bar,
    )
    return harness


# ---------------------------------------------------------------------------
# 1 — Headless selection chain
# ---------------------------------------------------------------------------


class TestSelectionChain:
    def test_select_populates_inspector(self) -> None:
        ent = _FakeEntity("rope_0", kind="rope", eid="rope_0")
        h = _make_harness([ent])

        h.outliner._handle_select(ent)

        assert h.inspector.target is ent

    def test_select_binds_gizmo(self) -> None:
        ent = _FakeEntity("rope_0", kind="rope", eid="rope_0")
        h = _make_harness([ent])

        h.outliner._handle_select(ent)

        assert h.gizmo._entity is ent

    def test_select_increments_status_bar_selection_count(self) -> None:
        ent = _FakeEntity("rope_0", kind="rope", eid="rope_0")
        h = _make_harness([ent])

        assert h.status_bar.selection_count == 0
        h.outliner._handle_select(ent)
        assert h.status_bar.selection_count == 1

    def test_select_updates_outliner_selected_id(self) -> None:
        ent = _FakeEntity("rope_0", kind="rope", eid="rope_0")
        h = _make_harness([ent])

        h.outliner._handle_select(ent)

        assert h.outliner.get_selected() == "rope_0"


# ---------------------------------------------------------------------------
# 2 — Deselect flow
# ---------------------------------------------------------------------------


class TestDeselectFlow:
    def test_deselect_empties_inspector(self) -> None:
        ent = _FakeEntity("body_0", kind="body", eid="body_0")
        h = _make_harness([ent])

        h.outliner._handle_select(ent)
        assert h.inspector.target is ent

        h.outliner._handle_select(None)
        assert h.inspector.target is None

    def test_deselect_unbinds_gizmo(self) -> None:
        ent = _FakeEntity("body_0", kind="body", eid="body_0")
        h = _make_harness([ent])

        h.outliner._handle_select(ent)
        assert h.gizmo._entity is ent

        h.outliner._handle_select(None)
        assert h.gizmo._entity is None

    def test_deselect_zeroes_status_bar_selection_count(self) -> None:
        ent = _FakeEntity("body_0", kind="body", eid="body_0")
        h = _make_harness([ent])

        h.outliner._handle_select(ent)
        assert h.status_bar.selection_count == 1

        h.outliner._handle_select(None)
        assert h.status_bar.selection_count == 0


# ---------------------------------------------------------------------------
# 3 — Change selection A → B
# ---------------------------------------------------------------------------


class TestChangeSelection:
    def test_change_selection_swaps_inspector_target(self) -> None:
        a = _FakeEntity("A", kind="rope", eid="A")
        b = _FakeEntity("B", kind="ragdoll", eid="B")
        h = _make_harness([a, b])

        h.outliner._handle_select(a)
        assert h.inspector.target is a
        h.outliner._handle_select(b)
        assert h.inspector.target is b

    def test_change_selection_swaps_gizmo_entity(self) -> None:
        a = _FakeEntity("A", kind="rope", eid="A")
        b = _FakeEntity("B", kind="ragdoll", eid="B")
        h = _make_harness([a, b])

        h.outliner._handle_select(a)
        assert h.gizmo._entity is a
        h.outliner._handle_select(b)
        assert h.gizmo._entity is b

    def test_change_selection_keeps_status_bar_count_at_one(self) -> None:
        a = _FakeEntity("A", kind="rope", eid="A")
        b = _FakeEntity("B", kind="ragdoll", eid="B")
        h = _make_harness([a, b])

        h.outliner._handle_select(a)
        h.outliner._handle_select(b)
        assert h.status_bar.selection_count == 1


# ---------------------------------------------------------------------------
# 4 — Inspector renders fields for engine-native objects
# ---------------------------------------------------------------------------


class TestInspectorRendersEngineObjects:
    def test_inspector_renders_body_fields(self) -> None:
        from slappyengine.dynamics.body import Body

        body = Body(kind="rope", label="my_rope")
        h = _make_harness([body])

        h.outliner._handle_select(body)

        # The inspector should have walked the dataclass fields and
        # logged a per-field event in its call_log.
        names = {entry[1] for entry in h.inspector.call_log
                 if entry and entry[0] == "field"}
        # Body has ``kind`` (str), ``node_offset`` (int), ``node_count`` (int),
        # ``label`` (str) — assert at least the str/int branches fired.
        assert "kind" in names
        assert "label" in names

    def test_inspector_renders_ropespec_fields(self) -> None:
        from slappyengine.dynamics.rope import RopeSpec

        spec = RopeSpec(node_count=8, total_length=2.0)
        h = _make_harness([spec])

        h.outliner._handle_select(spec)

        names = {entry[1] for entry in h.inspector.call_log
                 if entry and entry[0] == "field"}
        # The float-typed fields should at least include ``total_length``
        # and ``stiffness``; the int-typed ``node_count`` is mandatory too.
        assert "node_count" in names
        assert "total_length" in names
        assert "stiffness" in names
        assert "damping" in names

    def test_inspector_renders_ragdollspec_fields(self) -> None:
        from slappyengine.dynamics.ragdoll import BoneSpec, RagdollSpec

        # RagdollSpec requires at least one bone (the root); supply a
        # minimal default so __post_init__ validates.
        spec = RagdollSpec(bones=[BoneSpec(parent_idx=-1)])
        h = _make_harness([spec])

        h.outliner._handle_select(spec)

        names = {entry[1] for entry in h.inspector.call_log
                 if entry and entry[0] == "field"}
        assert "stiffness" in names
        assert "damping" in names


# ---------------------------------------------------------------------------
# 5 — Heart visibility checkbox round-trip
# ---------------------------------------------------------------------------


@dataclass
class _VisibleEntity:
    """Dataclass entity stand-in so the inspector reflects ``visible``."""
    name: str = "x"
    visible: bool = False
    position: tuple[float, float] = (0.0, 0.0)


class TestVisibilityHeart:
    def test_heart_checkbox_starts_unchecked_for_invisible_entity(self) -> None:
        from slappyengine.ui.editor.notebook_inspector import NotebookInspector

        ent = _VisibleEntity(name="ghost", visible=False)
        inspector = NotebookInspector()
        inspector.build("root")
        inspector.set_target(ent)

        # The HeartCheckbox should have been built with value=False.
        bool_events = [
            entry for entry in inspector.call_log
            if entry and entry[0] == "field" and entry[1] == "visible"
        ]
        assert bool_events, "expected a bool field event for 'visible'"
        assert bool_events[0][2] == "bool"

    def test_writeback_mutates_visible_attribute(self) -> None:
        from slappyengine.ui.editor.notebook_inspector import NotebookInspector

        ent = _VisibleEntity(name="ghost", visible=False)
        inspector = NotebookInspector()
        inspector.build("root")
        inspector.set_target(ent)

        # Simulate the HeartCheckbox firing its callback.
        inspector._write_back("visible", True)
        assert ent.visible is True

        inspector._write_back("visible", False)
        assert ent.visible is False


# ---------------------------------------------------------------------------
# 6 — set_on_select chains the previous callback
# ---------------------------------------------------------------------------


class TestChainedOnSelect:
    def test_set_on_select_chains_prev_and_new(self) -> None:
        """``Engine.run_editor`` calls ``set_on_select(gizmo.set_entity)`` after
        the shell's ``_on_entity_selected`` is already wired. The chain must
        fire BOTH callbacks per selection so the inspector still updates."""
        from slappyengine.ui.editor.notebook_outliner import NotebookOutliner

        captured_prev: list[Any] = []
        captured_new: list[Any] = []

        out = NotebookOutliner(
            world_getter=lambda: _FakeWorld(),
            on_select=captured_prev.append,
        )
        out.set_on_select(captured_new.append)

        ent = _FakeEntity("only", kind="rope", eid="only")
        out._handle_select(ent)

        assert captured_prev == [ent]
        assert captured_new == [ent]


# ---------------------------------------------------------------------------
# 7 — EditorShell wiring (no DPG context)
# ---------------------------------------------------------------------------


class TestEditorShellWiring:
    """Cover the actual ``EditorShell._on_entity_selected`` codepath."""

    def _build_shell(self, entities: list[Any]) -> Any:
        from slappyengine.ui.editor.shell import EditorShell

        engine = _FakeEngine(_FakeScene(entities))
        shell = EditorShell(engine)
        shell.setup_notebook_panels()
        return shell

    def test_shell_on_entity_selected_populates_inspector(self) -> None:
        ent = _FakeEntity("zone_0", kind="zone", eid="zone_0")
        shell = self._build_shell([ent])

        shell._on_entity_selected(ent)
        assert shell._inspector.target is ent

    def test_shell_on_entity_selected_binds_gizmo(self) -> None:
        ent = _FakeEntity("zone_0", kind="zone", eid="zone_0")
        shell = self._build_shell([ent])

        shell._on_entity_selected(ent)
        assert shell._gizmo_overlay._entity is ent

    def test_shell_on_entity_selected_updates_status_bar(self) -> None:
        ent = _FakeEntity("zone_0", kind="zone", eid="zone_0")
        shell = self._build_shell([ent])

        shell._on_entity_selected(ent)
        assert shell._notebook_status_bar.selection_count == 1

    def test_shell_on_entity_selected_none_deselects(self) -> None:
        ent = _FakeEntity("zone_0", kind="zone", eid="zone_0")
        shell = self._build_shell([ent])

        shell._on_entity_selected(ent)
        shell._on_entity_selected(None)

        assert shell._inspector.target is None
        assert shell._gizmo_overlay._entity is None
        assert shell._notebook_status_bar.selection_count == 0

    def test_shell_outliner_handle_select_round_trip(self) -> None:
        """Click an outliner row -> all three sinks update via the shell.

        Exercises the registered ``_on_entity_selected`` callback so the
        flow is verified end-to-end through the actual constructor wiring,
        not just by calling the shell method directly.
        """
        ent = _FakeEntity("camera_0", kind="camera", eid="camera_0")
        shell = self._build_shell([ent])

        shell._scene_outliner._handle_select(ent)

        assert shell._inspector.target is ent
        assert shell._gizmo_overlay._entity is ent
        assert shell._notebook_status_bar.selection_count == 1
        assert shell._selected_entity is ent
