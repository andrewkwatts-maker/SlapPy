"""Tests for :class:`NotebookNodeEditor` — the visual node graph editor.

The editor lives in the diary page's "Nodes" mode and operates on the
``pharos_engine.visual_scripting.NodeGraph`` data model. Both that page
(P3) and the data model (P4) land in sibling sprints; the editor
soft-imports both and falls back to an in-module stub data model so it
remains importable + testable in every state of the sprint stack.

Coverage:

* Construction with / without an explicit graph and / without DPG.
* ``build()`` runs cleanly without raising under a stub DPG module.
* ``add_node``, ``move_node``, ``remove_node`` all mutate the graph
  and fire the ``on_change`` callback.
* ``connect`` creates an edge, deduplicates, rejects self-loops, and
  rejects port-kind mismatches.
* ``remove_node`` sweeps connected edges.
* The palette returns the builtin nodes grouped by kind.
* ``generate_python`` produces a non-empty string.
* Theme switch refreshes wire colour.
"""
from __future__ import annotations

import sys
import types
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Headless DPG stub — mirrors the pattern used by other notebook panel tests.
# ---------------------------------------------------------------------------


class _StubCM:
    def __init__(self, recorder: dict, name: str) -> None:
        self._recorder = recorder
        self._name = name

    def __enter__(self):
        self._recorder.setdefault("contexts", []).append(self._name)
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    """Minimal dearpygui surface with call tracking + tag bookkeeping."""

    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: set[str] = set()
        self.values: dict[str, Any] = {}

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items.add(tag)

    # context managers
    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM(self.calls, "group")

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM(self.calls, "window")

    # primitives
    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_menu_item(self, *a, **kw):
        self._track("add_menu_item", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_drawlist(self, *a, **kw):
        self._track("add_drawlist", a, kw)

    def draw_rectangle(self, *a, **kw):
        self._track("draw_rectangle", a, kw)

    def draw_text(self, *a, **kw):
        self._track("draw_text", a, kw)

    def draw_circle(self, *a, **kw):
        self._track("draw_circle", a, kw)

    def draw_bezier_cubic(self, *a, **kw):
        self._track("draw_bezier_cubic", a, kw)

    def draw_polyline(self, *a, **kw):
        self._track("draw_polyline", a, kw)

    def configure_item(self, tag, *a, **kw):
        self._track("configure_item", (tag,) + a, kw)

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)

    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items


@pytest.fixture
def stub_dpg(monkeypatch):
    """Install a fresh stub DPG module before each test."""
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")

    def _fallback(name: str):
        if hasattr(stub, name):
            return getattr(stub, name)

        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))

        return _noop

    mod.__getattr__ = _fallback
    for name in (
        "group", "window",
        "add_text", "add_button", "add_menu_item", "add_separator",
        "add_drawlist",
        "draw_rectangle", "draw_text", "draw_circle",
        "draw_bezier_cubic", "draw_polyline",
        "configure_item", "delete_item", "does_item_exist",
    ):
        setattr(mod, name, getattr(stub, name))

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# Import guard.
# ---------------------------------------------------------------------------


try:
    from pharos_engine.ui.editor.notebook_node_editor import (
        BUILTIN_NODES,
        Edge,
        Node,
        NodeGraph,
        NodePort,
        NotebookNodeEditor,
    )
except Exception as _err:  # pragma: no cover
    pytest.skip(
        f"NotebookNodeEditor not importable: {_err}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_constructs_without_dpg(self):
        """Editor must construct cleanly without a DPG module."""
        editor = NotebookNodeEditor()
        assert editor.TITLE == "Nodes"
        assert editor.NODE_W == 160
        assert editor.NODE_H == 80
        assert editor.PORT_RADIUS == 6

    def test_constructs_with_empty_graph(self):
        editor = NotebookNodeEditor()
        graph = editor.get_graph()
        assert graph is not None
        assert list(graph.nodes) == []
        assert list(graph.edges) == []

    def test_constructs_with_supplied_graph(self):
        """A pre-built graph is stashed verbatim on the editor."""
        graph = NodeGraph()
        editor = NotebookNodeEditor(graph=graph)
        assert editor.get_graph() is graph

    def test_set_graph_replaces_handle(self):
        editor = NotebookNodeEditor()
        new_graph = NodeGraph()
        editor.set_graph(new_graph)
        assert editor.get_graph() is new_graph

    def test_set_graph_rejects_none(self):
        editor = NotebookNodeEditor()
        with pytest.raises(TypeError):
            editor.set_graph(None)


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


class TestBuild:
    def test_build_runs_without_dpg_errors(self, stub_dpg):
        editor = NotebookNodeEditor()
        editor.build("parent_x")
        assert editor._panel_tag in stub_dpg.items

    def test_build_registers_canvas(self, stub_dpg):
        """The build path registers a drawlist canvas tag."""
        editor = NotebookNodeEditor()
        editor.build("parent_x")
        assert editor._canvas_tag in stub_dpg.items
        assert "add_drawlist" in stub_dpg.calls

    def test_build_registers_toolbar(self, stub_dpg):
        editor = NotebookNodeEditor()
        editor.build("parent_x")
        assert editor._toolbar_tag in stub_dpg.items
        # Toolbar buttons: Add Node / Generate Python / Clear.
        buttons = stub_dpg.calls.get("add_button", [])
        labels = [kw.get("label") for _, kw in buttons]
        assert "+ Add Node" in labels
        assert "Generate Python" in labels
        assert "Clear" in labels

    def test_build_creates_palette_popup(self, stub_dpg):
        editor = NotebookNodeEditor()
        editor.build("parent_x")
        assert editor._palette_popup_tag in stub_dpg.items


# ---------------------------------------------------------------------------
# add_node / move_node / remove_node
# ---------------------------------------------------------------------------


class TestAddNode:
    def test_add_node_creates_node(self):
        editor = NotebookNodeEditor()
        nid = editor.add_node("math.add", (100, 80))
        assert isinstance(nid, str) and nid
        graph = editor.get_graph()
        assert len(graph.nodes) == 1
        node = graph.nodes[0]
        assert node.id == nid
        assert node.node_type == "math.add"
        assert tuple(node.position) == (100, 80)

    def test_add_node_populates_ports_from_template(self):
        editor = NotebookNodeEditor()
        editor.add_node("math.add", (0, 0))
        node = editor.get_graph().nodes[0]
        assert any(p.name == "a" for p in node.inputs)
        assert any(p.name == "b" for p in node.inputs)
        assert any(p.name == "sum" for p in node.outputs)

    def test_add_node_unknown_type_still_creates_node(self):
        """Unknown types create a node with no ports — graceful fallback."""
        editor = NotebookNodeEditor()
        nid = editor.add_node("MysteryNode", (0, 0))
        node = editor.get_graph().nodes[0]
        assert node.id == nid
        assert node.node_type == "MysteryNode"
        assert list(node.inputs) == []
        assert list(node.outputs) == []

    def test_add_node_rejects_empty_type(self):
        editor = NotebookNodeEditor()
        with pytest.raises(ValueError):
            editor.add_node("", (0, 0))

    def test_add_node_rejects_bad_position(self):
        editor = NotebookNodeEditor()
        with pytest.raises(TypeError):
            editor.add_node("math.add", "not a tuple")  # type: ignore[arg-type]

    def test_move_node_updates_position(self):
        editor = NotebookNodeEditor()
        nid = editor.add_node("math.add", (10, 10))
        editor.move_node(nid, (200, 150))
        node = editor.get_graph().nodes[0]
        assert tuple(node.position) == (200, 150)

    def test_move_node_missing_id_is_noop(self):
        editor = NotebookNodeEditor()
        # Should not raise — silent no-op when id isn't present.
        editor.move_node("nope", (10, 10))

    def test_remove_node_drops_node(self):
        editor = NotebookNodeEditor()
        nid = editor.add_node("math.add", (0, 0))
        editor.remove_node(nid)
        assert len(editor.get_graph().nodes) == 0

    def test_remove_node_sweeps_attached_edges(self):
        editor = NotebookNodeEditor()
        a = editor.add_node("math.add", (0, 0))
        b = editor.add_node("io.print", (200, 0))
        # math.add.sum is float; io.print.message is any → compatible.
        assert editor.connect(a, "sum", b, "message") is True
        assert len(editor.get_graph().edges) == 1
        editor.remove_node(a)
        assert len(editor.get_graph().edges) == 0


# ---------------------------------------------------------------------------
# connect / disconnect
# ---------------------------------------------------------------------------


class TestConnect:
    def test_connect_creates_edge(self):
        editor = NotebookNodeEditor()
        a = editor.add_node("math.add", (0, 0))
        b = editor.add_node("io.print", (200, 0))
        ok = editor.connect(a, "sum", b, "message")
        assert ok is True
        edges = editor.get_graph().edges
        assert len(edges) == 1
        edge = edges[0]
        # Real Edge uses ``from_node_id``; the editor's accessor handles
        # both schemas.
        assert NotebookNodeEditor._edge_from_id(edge) == a
        assert edge.from_port == "sum"
        assert NotebookNodeEditor._edge_to_id(edge) == b
        assert edge.to_port == "message"

    def test_connect_self_loop_rejected(self):
        editor = NotebookNodeEditor()
        a = editor.add_node("math.add", (0, 0))
        assert editor.connect(a, "sum", a, "a") is False

    def test_connect_missing_node_rejected(self):
        editor = NotebookNodeEditor()
        a = editor.add_node("math.add", (0, 0))
        assert editor.connect(a, "sum", "ghost", "message") is False

    def test_connect_type_mismatch_rejected(self):
        """float -> bool is rejected by the editor's type check."""
        editor = NotebookNodeEditor()
        a = editor.add_node("math.add", (0, 0))     # sum: float
        b = editor.add_node("logic.and", (200, 0))   # a: bool
        ok = editor.connect(a, "sum", b, "a")
        assert ok is False
        assert editor.get_graph().edges == []

    def test_connect_duplicate_rejected(self):
        editor = NotebookNodeEditor()
        a = editor.add_node("math.add", (0, 0))
        b = editor.add_node("io.print", (200, 0))
        assert editor.connect(a, "sum", b, "message") is True
        assert editor.connect(a, "sum", b, "message") is False
        assert len(editor.get_graph().edges) == 1

    def test_disconnect_removes_edge(self):
        editor = NotebookNodeEditor()
        a = editor.add_node("math.add", (0, 0))
        b = editor.add_node("io.print", (200, 0))
        editor.connect(a, "sum", b, "message")
        edge = editor.get_graph().edges[0]
        editor.disconnect(edge)
        assert editor.get_graph().edges == []

    def test_disconnect_unknown_edge_is_noop(self):
        editor = NotebookNodeEditor()
        # Synthesise a ghost edge using whatever Edge schema is in scope.
        try:
            ghost = Edge(
                from_node_id="x", from_port="y",
                to_node_id="z", to_port="w",
            )
        except TypeError:
            ghost = Edge(
                from_node="x", from_port="y",
                to_node="z", to_port="w",
            )
        editor.disconnect(ghost)  # must not raise


# ---------------------------------------------------------------------------
# Palette / builtin nodes
# ---------------------------------------------------------------------------


class TestPalette:
    def test_builtin_nodes_non_empty(self):
        editor = NotebookNodeEditor()
        assert len(editor.builtin_nodes) > 0
        # Each entry exposes node_type and kind.
        for entry in editor.builtin_nodes:
            assert getattr(entry, "node_type", None)
            assert getattr(entry, "kind", None)

    def test_palette_entries_grouped_by_kind(self):
        editor = NotebookNodeEditor()
        groups = editor.palette_entries()
        assert isinstance(groups, dict)
        # The default builtin set covers at least math + logic + io.
        assert "math" in groups
        assert len(groups["math"]) > 0
        assert "logic" in groups
        assert "io" in groups

    def test_open_palette_records_spawn(self):
        editor = NotebookNodeEditor()
        editor.open_palette((42, 24))
        assert ("open_palette", (42, 24)) in editor.call_log


# ---------------------------------------------------------------------------
# Codegen
# ---------------------------------------------------------------------------


class TestCodegen:
    def test_generate_python_returns_non_empty(self):
        editor = NotebookNodeEditor()
        editor.add_node("math.add", (0, 0))
        out = editor.generate_python()
        assert isinstance(out, str)
        assert out.strip()

    def test_generate_python_empty_graph_still_returns_string(self):
        editor = NotebookNodeEditor()
        out = editor.generate_python()
        assert isinstance(out, str)
        # Either the real generator or the stub fallback produces something.
        assert len(out) > 0

    def test_generate_python_pushes_to_code_panel(self):
        """When a code panel is bound the codegen output lands in it."""
        editor = NotebookNodeEditor()
        editor.add_node("math.add", (0, 0))

        class _FakePanel:
            def __init__(self):
                self._code_text = ""

            def _sync_inputs_to_dpg(self):
                pass

        panel = _FakePanel()
        editor.bind_code_panel(panel)
        out = editor.generate_python()
        assert panel._code_text == out


# ---------------------------------------------------------------------------
# on_change callback
# ---------------------------------------------------------------------------


class TestOnChange:
    def test_on_change_fires_on_add(self):
        events: list[Any] = []
        editor = NotebookNodeEditor(on_change=lambda g: events.append("add"))
        editor.add_node("math.add", (0, 0))
        assert events == ["add"]

    def test_on_change_fires_on_move(self):
        events: list[str] = []
        editor = NotebookNodeEditor(on_change=lambda g: events.append("change"))
        nid = editor.add_node("math.add", (0, 0))
        events.clear()
        editor.move_node(nid, (10, 10))
        assert events == ["change"]

    def test_on_change_fires_on_connect(self):
        events: list[str] = []
        editor = NotebookNodeEditor(on_change=lambda g: events.append("change"))
        a = editor.add_node("math.add", (0, 0))
        b = editor.add_node("io.print", (200, 0))
        events.clear()
        editor.connect(a, "sum", b, "message")
        assert events == ["change"]

    def test_on_change_fires_on_remove(self):
        events: list[str] = []
        editor = NotebookNodeEditor(on_change=lambda g: events.append("change"))
        nid = editor.add_node("math.add", (0, 0))
        events.clear()
        editor.remove_node(nid)
        assert events == ["change"]

    def test_on_change_does_not_fire_on_rejected_connect(self):
        events: list[str] = []
        editor = NotebookNodeEditor(on_change=lambda g: events.append("change"))
        a = editor.add_node("math.add", (0, 0))
        b = editor.add_node("logic.and", (200, 0))
        events.clear()
        # Type-mismatched connect: float -> bool.
        assert editor.connect(a, "sum", b, "a") is False
        assert events == []

    def test_on_change_listener_error_does_not_break_editor(self):
        """A crashing listener must not cascade into the editor."""
        def _boom(_g: Any) -> None:
            raise RuntimeError("listener exploded")

        editor = NotebookNodeEditor(on_change=_boom)
        # Should not raise.
        nid = editor.add_node("math.add", (0, 0))
        assert nid in [n.id for n in editor.get_graph().nodes]


# ---------------------------------------------------------------------------
# Refresh / theme switch
# ---------------------------------------------------------------------------


class TestRefresh:
    def test_refresh_repaints_drawlist(self, stub_dpg):
        editor = NotebookNodeEditor()
        editor.build("parent_x")
        editor.add_node("math.add", (10, 20))
        # add_node calls refresh internally — a draw_rectangle (card body)
        # must have been issued for the new node.
        assert "draw_rectangle" in stub_dpg.calls

    def test_refresh_emits_wire_for_each_edge(self, stub_dpg):
        editor = NotebookNodeEditor()
        editor.build("parent_x")
        a = editor.add_node("math.add", (0, 0))
        b = editor.add_node("io.print", (200, 0))
        editor.connect(a, "sum", b, "message")
        # At least one bezier (or polyline fallback) call for the edge.
        assert (
            "draw_bezier_cubic" in stub_dpg.calls
            or "draw_polyline" in stub_dpg.calls
        )

    def test_theme_switch_updates_wire_color(self, stub_dpg):
        """When the theme changes, the next refresh queries the new accent."""
        from pharos_engine.ui.widgets.notebook_theme import (
            NotebookTheme,
            set_active_theme,
        )

        editor = NotebookNodeEditor()
        editor.build("parent_x")
        a = editor.add_node("math.add", (0, 0))
        b = editor.add_node("io.print", (200, 0))
        editor.connect(a, "sum", b, "message")

        custom = NotebookTheme(
            name="test",
            palette={"accent": (1, 2, 3, 255)},
        )
        try:
            set_active_theme(custom)
            stub_dpg.calls.pop("draw_bezier_cubic", None)
            stub_dpg.calls.pop("draw_polyline", None)
            editor.refresh()
            calls = (
                stub_dpg.calls.get("draw_bezier_cubic", [])
                + stub_dpg.calls.get("draw_polyline", [])
            )
            assert calls, "wire repaint must emit at least one call"
            for _args, kwargs in calls:
                colour = kwargs.get("color")
                assert colour is not None
                # The custom accent must propagate to every wire colour.
                assert tuple(colour) == (1, 2, 3, 255)
        finally:
            set_active_theme(None)


# ---------------------------------------------------------------------------
# Soft-import fallback
# ---------------------------------------------------------------------------


class TestSoftImport:
    def test_data_model_exports_present(self):
        """The editor module always re-exports the data model symbols."""
        assert NodeGraph is not None
        assert Node is not None
        assert Edge is not None
        assert NodePort is not None
        assert BUILTIN_NODES is not None

    def test_builtin_nodes_is_list_like(self):
        """The exported BUILTIN_NODES must be iterable."""
        items = list(BUILTIN_NODES)
        assert len(items) >= 1
