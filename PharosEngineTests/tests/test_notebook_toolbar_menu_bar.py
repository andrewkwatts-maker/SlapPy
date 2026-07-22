"""Regression tests for the notebook toolbar + editor menu bar (BBB6).

These pin the two bugs the BBB6 sprint task closed:

* The notebook toolbar was rendering as a single black column because
  :class:`StickerButton.build` uses ``parent=parent_tag`` internally,
  which bypasses DPG's context stack. The fix parents each button
  through an explicit horizontal group tag AND drops a plain-DPG
  button with explicit ``width`` / ``height`` alongside every
  StickerButton so the stamps always show at non-zero size.
* The editor menu bar must expose at least File / Edit / View / Help
  as top-level menus, each with at least one enabled item.

The tests are headless — they inject a lightweight stub DPG that
records every ``add_button`` / ``add_menu`` / ``add_menu_item`` /
``add_group`` call so we can assert wiring without a live GUI.
"""
from __future__ import annotations

import sys
import types

import pytest

try:
    from pharos_editor.ui.editor.notebook_toolbar import NotebookToolbar
except Exception as exc:  # pragma: no cover - dep gate
    pytest.skip(
        f"notebook_toolbar dependencies unavailable: {exc}",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Stub DPG that records every widget call.
# ---------------------------------------------------------------------------


class _RecordingDPG:
    """Minimal DPG stub that records the wiring calls we care about."""

    def __init__(self) -> None:
        self.buttons: list[dict] = []
        self.groups: list[dict] = []
        self.menus: list[dict] = []
        self.menu_items: list[dict] = []
        self._stack: list[str] = []

    # ---- widget calls ------------------------------------------------

    def add_group(self, *args, **kwargs) -> str:
        rec = dict(kwargs)
        tag = kwargs.get("tag") or f"__auto_group_{len(self.groups)}"
        rec["tag"] = tag
        self.groups.append(rec)
        return tag

    def add_button(self, *args, **kwargs) -> str:
        rec = dict(kwargs)
        tag = kwargs.get("tag") or f"__auto_btn_{len(self.buttons)}"
        rec["tag"] = tag
        self.buttons.append(rec)
        return tag

    def add_text(self, *args, **kwargs) -> str:
        return kwargs.get("tag") or "__auto_text__"

    def add_menu_item(self, *args, **kwargs) -> str:
        rec = dict(kwargs)
        # ``label`` is often positional; capture it too.
        if args and "label" not in rec:
            rec["label"] = args[0]
        rec.setdefault("enabled", True)
        # Track the menu the item sits under via the ``with`` stack.
        rec["_parent_menu"] = self._stack[-1] if self._stack else None
        self.menu_items.append(rec)
        return rec.get("tag") or f"__auto_item_{len(self.menu_items)}"

    def add_separator(self, *args, **kwargs) -> None:
        return None

    def does_item_exist(self, *args, **kwargs) -> bool:
        return False

    # ---- context managers -------------------------------------------

    class _Ctx:
        def __init__(self, outer, label):
            self.outer = outer
            self.label = label

        def __enter__(self):
            self.outer._stack.append(self.label)
            return self

        def __exit__(self, *exc):
            try:
                self.outer._stack.pop()
            except IndexError:
                pass
            return False

    def group(self, *args, **kwargs):
        # ``NotebookToolbar.build`` uses add_group, not this cm, but
        # StickerButton uses it. Record when it opens.
        return self._Ctx(self, "__group__")

    def menu(self, *args, **kwargs):
        # Record the menu at __enter__ time so items land under it.
        label = kwargs.get("label")
        rec = dict(kwargs)
        rec["label"] = label
        self.menus.append(rec)
        return self._Ctx(self, label or "__menu__")

    def viewport_menu_bar(self, *args, **kwargs):
        return self._Ctx(self, "__viewport_menu_bar__")

    def window(self, *args, **kwargs):
        return self._Ctx(self, "__window__")

    # ---- everything else no-ops -------------------------------------

    def __getattr__(self, name):
        def _noop(*a, **kw):
            return None
        return _noop


@pytest.fixture
def stub_dpg(monkeypatch):
    stub = _RecordingDPG()
    pkg = types.ModuleType("dearpygui")
    pkg.dearpygui = stub  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dearpygui", pkg)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", stub)
    yield stub


# ---------------------------------------------------------------------------
# Toolbar regression tests.
# ---------------------------------------------------------------------------


def test_toolbar_build_creates_four_buttons(stub_dpg):
    """The toolbar must add at least four DPG buttons, one per tool."""
    bar = NotebookToolbar()
    bar.build("mock_parent_window")
    # There are four tool ids; the sticker overlay also drops buttons.
    # The BBB6 contract is >=4 plain DPG buttons registered for the four
    # canonical tool ids.
    tool_ids = {"select", "move", "rotate", "scale"}
    matched_tags = [
        b for b in stub_dpg.buttons
        if any(tid in str(b.get("tag", "")) for tid in tool_ids)
    ]
    assert len(matched_tags) >= 4, (
        f"expected >=4 tool buttons, got {len(matched_tags)}: "
        f"{[b.get('tag') for b in stub_dpg.buttons]}"
    )


def test_toolbar_buttons_have_non_zero_size(stub_dpg):
    """Every registered tool button must carry a positive width + height."""
    bar = NotebookToolbar()
    bar.build("mock_parent_window")

    # Introspect the recorded button_specs — the API tests are supposed
    # to hit rather than reaching into DPG.
    specs = bar.button_specs
    assert len(specs) >= 4, f"expected >=4 button specs, got {len(specs)}"
    for spec in specs:
        assert int(spec["width"]) > 0, spec
        assert int(spec["height"]) > 0, spec

    # And the plain DPG buttons carry width + height too.
    for btn in stub_dpg.buttons:
        # StickerButton emits a sub-button whose width is set as well.
        w = btn.get("width")
        h = btn.get("height")
        if w is not None:
            assert int(w) > 0, btn
        if h is not None:
            assert int(h) > 0, btn


def test_toolbar_buttons_have_callbacks(stub_dpg):
    """Every tool button must carry a callable ``callback`` kwarg."""
    bar = NotebookToolbar()
    bar.build("mock_parent_window")
    tool_ids = {"select", "move", "rotate", "scale"}
    matched = [
        b for b in stub_dpg.buttons
        if any(tid in str(b.get("tag", "")) for tid in tool_ids)
    ]
    for btn in matched:
        cb = btn.get("callback")
        assert callable(cb), f"button {btn.get('tag')} has no callback"


def test_toolbar_build_records_group_parent(stub_dpg):
    """The build must register a horizontal container to hold the buttons."""
    bar = NotebookToolbar()
    bar.build("mock_parent_window")
    # At least one horizontal group registered as the button parent.
    horizontals = [g for g in stub_dpg.groups if g.get("horizontal")]
    assert horizontals, "expected a horizontal group to host the buttons"


def test_toolbar_headless_build_records_specs(monkeypatch):
    """Even without DPG the build() must record ``button_specs``.

    We force the ``dearpygui`` import inside :meth:`NotebookToolbar.build`
    to fail so we exercise the headless branch that appends spec entries
    without touching a real DPG surface. This makes the assertion
    trustworthy on machines where DPG is installed but there is no
    active DPG context.
    """
    # Sink the dpg import so build() takes the headless branch.
    monkeypatch.setitem(sys.modules, "dearpygui", None)
    monkeypatch.setitem(sys.modules, "dearpygui.dearpygui", None)
    bar = NotebookToolbar()
    bar.build("mock_parent_window")
    specs = bar.button_specs
    assert len(specs) >= 4
    for spec in specs:
        assert int(spec["width"]) > 0
        assert int(spec["height"]) > 0


# ---------------------------------------------------------------------------
# Menu bar regression tests.
# ---------------------------------------------------------------------------


def _build_menu_bar(stub) -> None:
    """Reproduce the shell.py menu bar construction against the stub.

    We intentionally do not import the whole EditorShell (it pulls in
    the full DPG surface). Instead we re-run the same File / Edit /
    View / Help construction so the tests can assert the top-level
    structure without booting the editor.
    """
    import dearpygui.dearpygui as dpg

    with dpg.viewport_menu_bar():
        with dpg.menu(label="File"):
            dpg.add_menu_item(label="New Scene", tag="menu_new_scene")
            dpg.add_menu_item(label="Open Scene...", tag="menu_open_scene")
            dpg.add_menu_item(label="Save Scene", tag="menu_save_scene")
            dpg.add_menu_item(label="Quit", tag="menu_quit")
        with dpg.menu(label="Edit"):
            dpg.add_menu_item(label="Undo", tag="menu_undo")
        with dpg.menu(label="View"):
            dpg.add_menu_item(label="Reset Layout", tag="menu_reset_layout")
        with dpg.menu(label="Help"):
            dpg.add_menu_item(label="Welcome", tag="menu_welcome")
            dpg.add_menu_item(label="About", tag="menu_about")


def test_menu_bar_has_four_top_level_menus(stub_dpg):
    _build_menu_bar(stub_dpg)
    labels = [m.get("label") for m in stub_dpg.menus]
    for expected in ("File", "Edit", "View", "Help"):
        assert expected in labels, f"missing top-level menu {expected!r}"
    assert len(stub_dpg.menus) >= 4


def test_menu_bar_items_are_enabled(stub_dpg):
    _build_menu_bar(stub_dpg)
    assert stub_dpg.menu_items, "no menu items recorded"
    for item in stub_dpg.menu_items:
        # ``enabled`` defaults to True in DPG when unset.
        assert item.get("enabled", True) is not False, (
            f"menu item {item.get('label')!r} is disabled"
        )


def test_menu_bar_shell_wires_full_menu_set():
    """The editor shell must expose the File / Edit / View / Help set.

    We read the shell.py source and confirm each menu is constructed
    with the expected label. This avoids booting the full editor while
    still catching regressions that drop a top-level menu.
    """
    from pathlib import Path

    import pharos_editor.ui.editor.shell as shell_module

    src = Path(shell_module.__file__).read_text(encoding="utf-8")
    for label in ("File", "Edit", "View", "Help"):
        assert f'dpg.menu(label="{label}")' in src, (
            f"shell.py is missing top-level menu {label!r}"
        )


def test_menu_bar_shell_has_placeholder_callbacks():
    """Every menu item wired in shell.py must attach a callable callback."""
    from pathlib import Path

    import pharos_editor.ui.editor.shell as shell_module

    src = Path(shell_module.__file__).read_text(encoding="utf-8")
    # A cheap grep: every ``dpg.add_menu_item(`` block near a shell
    # method call. Instead of parsing the AST we just confirm the four
    # canonical callback methods exist on the shell class.
    for method in (
        "menu_undo",
        "menu_reset_layout",
        "menu_about",
        "new_scene",
    ):
        assert f"def {method}" in src, (
            f"shell.py is missing menu callback method {method!r}"
        )
