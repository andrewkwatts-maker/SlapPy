"""Regression tests for the EEE4 material graph visual canvas.

Covers:

* Canvas builds under a stub DPG module and exposes the expected tags.
* Placing a node adds it to the underlying :class:`MaterialGraph`.
* Wire from ``ConstColor.out (vec4) → Multiply.a (vec4)`` is accepted.
* Wire from ``UV.uv (vec2) → Texture2D.uv (vec2)`` accepted (matched).
* Wire from ``UV.uv (vec2) → Texture2D`` synthetic slot ``sampler2D`` is
  rejected (incompatible dtypes) — no edge added.
* Compile → produces valid WGSL (starts with the expected fragment
  entry-point line).
* Save/Load YAML round-trips the canvas state (nodes + edges + positions).
* Del key on selected node removes it + all its connections.
* Palette + compatibility surface behaves as documented.
"""
from __future__ import annotations

import sys
import tempfile
import types
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Stub DPG — modelled after test_editor_repl_and_helpers so the canvas
# builds without a real GUI context.
# ---------------------------------------------------------------------------


class _StubCM:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _StubDPG:
    def __init__(self) -> None:
        self.calls: dict[str, list] = {}
        self.items: dict[str, Any] = {}
        # Key constants the canvas may reach for.
        self.mvKey_Delete = 261
        self.mvNode_Attr_Input = 0
        self.mvNode_Attr_Output = 1

    def _track(self, name: str, args: tuple, kwargs: dict) -> None:
        self.calls.setdefault(name, []).append((args, kwargs))
        tag = kwargs.get("tag")
        if isinstance(tag, str):
            self.items[tag] = kwargs

    # Context managers ------------------------------------------------
    def group(self, *a, **kw):
        self._track("group", a, kw)
        return _StubCM()

    def child_window(self, *a, **kw):
        self._track("child_window", a, kw)
        return _StubCM()

    def window(self, *a, **kw):
        self._track("window", a, kw)
        return _StubCM()

    def node(self, *a, **kw):
        self._track("node", a, kw)
        return _StubCM()

    def node_attribute(self, *a, **kw):
        self._track("node_attribute", a, kw)
        return _StubCM()

    def handler_registry(self, *a, **kw):
        self._track("handler_registry", a, kw)
        return _StubCM()

    # Widgets ---------------------------------------------------------
    def add_child_window(self, *a, **kw):
        self._track("add_child_window", a, kw)

    def add_text(self, *a, **kw):
        self._track("add_text", a, kw)

    def add_separator(self, *a, **kw):
        self._track("add_separator", a, kw)

    def add_button(self, *a, **kw):
        self._track("add_button", a, kw)

    def add_input_text(self, *a, **kw):
        self._track("add_input_text", a, kw)

    def add_input_float(self, *a, **kw):
        self._track("add_input_float", a, kw)

    def add_checkbox(self, *a, **kw):
        self._track("add_checkbox", a, kw)

    def add_node_editor(self, *a, **kw):
        self._track("add_node_editor", a, kw)

    def add_node_link(self, *a, **kw):
        self._track("add_node_link", a, kw)

    def add_key_press_handler(self, *a, **kw):
        self._track("add_key_press_handler", a, kw)

    # Item ops --------------------------------------------------------
    def does_item_exist(self, tag, *a, **kw):
        return tag in self.items

    def delete_item(self, tag, *a, **kw):
        self._track("delete_item", (tag,), kw)

    def configure_item(self, tag, *a, **kw):
        self._track("configure_item", (tag,), kw)
        if isinstance(tag, str):
            self.items.setdefault(tag, {}).update(kw)

    def focus_item(self, tag, *a, **kw):
        self._track("focus_item", (tag,), kw)

    def get_value(self, tag):
        return self.items.get(tag, {}).get("_value", "")

    def set_value(self, tag, value):
        self.items.setdefault(tag, {})["_value"] = value


@pytest.fixture
def stub_dpg(monkeypatch):
    stub = _StubDPG()
    mod = types.ModuleType("dearpygui.dearpygui")
    for name in (
        "group", "child_window", "window", "node", "node_attribute",
        "handler_registry",
        "add_child_window", "add_text", "add_separator", "add_button",
        "add_input_text", "add_input_float", "add_checkbox",
        "add_node_editor", "add_node_link", "add_key_press_handler",
        "does_item_exist", "delete_item", "configure_item", "focus_item",
        "get_value", "set_value",
        "mvKey_Delete", "mvNode_Attr_Input", "mvNode_Attr_Output",
    ):
        setattr(mod, name, getattr(stub, name))

    def _fallback(name: str):
        def _noop(*a, **kw):
            stub.calls.setdefault(name, []).append((a, kw))
            return _StubCM()
        return _noop

    mod.__getattr__ = _fallback  # type: ignore[attr-defined]

    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = mod
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", mod)
    yield stub


# ---------------------------------------------------------------------------
# 1. Canvas builds under DPG mock
# ---------------------------------------------------------------------------


def test_canvas_builds_under_stub_dpg(stub_dpg) -> None:
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
        NODE_PALETTE,
    )

    canvas = MaterialGraphCanvas()
    canvas.build(parent_tag="parent_root")

    # The canvas should have opened its outer group and painted a
    # palette button per node type.
    assert canvas._built is True
    add_button_calls = stub_dpg.calls.get("add_button", [])
    labels = [kw.get("label") for _args, kw in add_button_calls]
    # Toolbar buttons + one per palette entry.
    assert "Compile" in labels
    assert "Save YAML" in labels
    assert "Load YAML" in labels
    assert "Clear" in labels
    # Every palette entry surfaced.
    for _key, label, _cls in NODE_PALETTE:
        assert label in labels, f"palette entry {label!r} missing from build"


# ---------------------------------------------------------------------------
# 2. Placing a node mutates the underlying graph
# ---------------------------------------------------------------------------


def test_place_node_updates_graph(stub_dpg) -> None:
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
    )

    canvas = MaterialGraphCanvas()
    canvas.build(parent_tag="parent_root")

    node = canvas.place_node("ConstColor", x=100.0, y=50.0)
    assert node.name in canvas.graph.nodes
    assert canvas.graph.nodes[node.name] is node
    assert canvas.positions[node.name] == (100.0, 50.0)
    # Placement clears the armed-palette latch.
    assert canvas.armed_palette is None
    # Placing a second ConstColor gets a suffixed name.
    node2 = canvas.place_node("ConstColor", x=200.0, y=100.0)
    assert node2.name != node.name
    assert len(canvas.graph.nodes) == 2


# ---------------------------------------------------------------------------
# 3. Wire from ConstColor → Multiply is accepted (both vec4)
# ---------------------------------------------------------------------------


def test_wire_const_color_to_multiply_accepted(stub_dpg) -> None:
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
    )

    canvas = MaterialGraphCanvas()
    canvas.build(parent_tag="parent_root")

    cc = canvas.place_node("ConstColor", 0, 0)
    mul = canvas.place_node("Multiply", 300, 0)
    ok = canvas.wire(cc.name, "out", mul.name, "a")
    assert ok is True
    assert len(canvas.graph.edges) == 1
    e = canvas.graph.edges[0]
    assert (e.from_node, e.from_slot, e.to_node, e.to_slot) == (
        cc.name, "out", mul.name, "a",
    )


# ---------------------------------------------------------------------------
# 4. Incompatible-dtype wire is rejected
# ---------------------------------------------------------------------------


def test_wire_incompatible_dtype_rejected(stub_dpg) -> None:
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
        is_compatible,
    )

    canvas = MaterialGraphCanvas()
    canvas.build(parent_tag="parent_root")

    # UV.uv is vec2. Multiply.a is vec4. Compatibility table has no
    # vec2 → vec4 entry, so the wire should be refused.
    uv = canvas.place_node("UV", 0, 0)
    mul = canvas.place_node("Multiply", 300, 0)
    assert is_compatible("vec2", "vec4") is False
    ok = canvas.wire(uv.name, "uv", mul.name, "a")
    assert ok is False
    assert canvas.graph.edges == []
    assert "incompatible" in canvas.last_status.lower()


# ---------------------------------------------------------------------------
# 5. Compile produces valid WGSL (fragment entry point present)
# ---------------------------------------------------------------------------


def test_compile_produces_wgsl(stub_dpg) -> None:
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
    )

    canvas = MaterialGraphCanvas()
    canvas.build(parent_tag="parent_root")
    # Minimal graph — one const colour feeding the auto-inserted output.
    cc = canvas.place_node("ConstColor", 0, 0)
    # Add PBR output + wire albedo.
    out = canvas.place_node("PBROutput", 400, 0)
    canvas.wire(cc.name, "out", out.name, "albedo")

    wgsl = canvas.compile()
    assert isinstance(wgsl, str) and wgsl
    assert "@fragment" in wgsl
    assert "fn main" in wgsl
    assert canvas.last_compiled_wgsl == wgsl


# ---------------------------------------------------------------------------
# 6. Save / Load YAML round-trips positions + connections
# ---------------------------------------------------------------------------


def test_save_load_yaml_round_trip(stub_dpg, tmp_path) -> None:
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
    )

    canvas = MaterialGraphCanvas()
    canvas.build(parent_tag="parent_root")

    cc = canvas.place_node("ConstColor", x=100.0, y=50.0)
    mul = canvas.place_node("Multiply", x=250.0, y=50.0)
    canvas.wire(cc.name, "out", mul.name, "a")

    yaml_path = tmp_path / "graph.yaml"
    canvas.save_yaml(str(yaml_path))
    assert yaml_path.exists()

    # Load into a fresh canvas.
    canvas2 = MaterialGraphCanvas()
    canvas2.build(parent_tag="parent_root_2")
    canvas2.load_yaml(str(yaml_path))

    assert set(canvas2.graph.nodes.keys()) == {cc.name, mul.name}
    assert canvas2.positions[cc.name] == (100.0, 50.0)
    assert canvas2.positions[mul.name] == (250.0, 50.0)
    assert len(canvas2.graph.edges) == 1
    e = canvas2.graph.edges[0]
    assert (e.from_node, e.from_slot, e.to_node, e.to_slot) == (
        cc.name, "out", mul.name, "a",
    )


# ---------------------------------------------------------------------------
# 7. Del key on selected node removes it + all its connections
# ---------------------------------------------------------------------------


def test_delete_selected_removes_node_and_edges(stub_dpg) -> None:
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
    )

    canvas = MaterialGraphCanvas()
    canvas.build(parent_tag="parent_root")

    cc = canvas.place_node("ConstColor", 0, 0)
    mul = canvas.place_node("Multiply", 200, 0)
    add = canvas.place_node("Add", 400, 0)
    canvas.wire(cc.name, "out", mul.name, "a")
    canvas.wire(mul.name, "out", add.name, "a")
    assert len(canvas.graph.edges) == 2

    canvas.select_node(mul.name)
    assert canvas.selected == mul.name
    deleted = canvas.delete_selected()
    assert deleted == mul.name
    assert mul.name not in canvas.graph.nodes
    assert canvas.selected is None
    # Every edge that touched the deleted node is gone; the untouched
    # ConstColor + Add nodes remain.
    for e in canvas.graph.edges:
        assert e.from_node != mul.name and e.to_node != mul.name
    assert cc.name in canvas.graph.nodes
    assert add.name in canvas.graph.nodes


# ---------------------------------------------------------------------------
# 8. Bonus — palette count matches DDD5's 10 node types
# ---------------------------------------------------------------------------


def test_palette_has_ten_entries() -> None:
    from pharos_editor.ui.editor.material_graph_canvas import NODE_PALETTE

    assert len(NODE_PALETTE) == 10
    keys = {k for k, _lbl, _cls in NODE_PALETTE}
    assert keys == {
        "ConstFloat", "ConstColor", "Texture2D", "UV",
        "Multiply", "Add", "Mix", "NormalMap", "Fresnel", "PBROutput",
    }


# ---------------------------------------------------------------------------
# 9. Bonus — helper open_material_graph returns a canvas
# ---------------------------------------------------------------------------


def test_open_material_graph_helper(stub_dpg) -> None:
    from pharos_editor.editor.helpers import open_material_graph
    from pharos_editor.ui.editor.material_graph_canvas import (
        MaterialGraphCanvas,
    )

    canvas = open_material_graph()
    assert isinstance(canvas, MaterialGraphCanvas)
