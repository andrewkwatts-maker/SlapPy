"""Tests for :mod:`slappyengine.tool_router` — the editor tool-routing contract.

Coverage
--------

* Registration + idempotency
* Duplicate-id conflict detection
* Rust-backing lookup (present + missing symbols, cache honesty)
* Dispatch of Rust-backed actions
* Dispatch of Python-fallback actions
* Dispatch of declared-but-unimplemented actions
* Missing-action raises ``KeyError``
* ``ctx`` propagation through the fallback signature
* Category enumeration
* Every canonical action is registered on module import (≥ 50 entries)
* Every hotkey-table command has a matching registration
* Signature-mismatch Rust call falls through to Python

Provenance: ``docs/tool_routing_2026_06_07.md`` names each test case.
"""
from __future__ import annotations

import types
from typing import Any

import pytest

from slappyengine import tool_router
from slappyengine.tool_router import (
    REGISTRY,
    ToolAction,
    ToolRouter,
    register_default_actions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fresh_router() -> ToolRouter:
    """Return an empty :class:`ToolRouter` — no default actions loaded."""
    return ToolRouter()


@pytest.fixture()
def seeded_router() -> ToolRouter:
    """Return a router pre-populated with the canonical default actions."""
    r = ToolRouter()
    register_default_actions(r)
    return r


# ---------------------------------------------------------------------------
# 1. Basic registration
# ---------------------------------------------------------------------------


def test_register_action_stores_entry(fresh_router: ToolRouter) -> None:
    action = ToolAction(
        action_id="test.noop",
        label="No-op",
    )
    fresh_router.register(action)
    assert fresh_router.has_action("test.noop")
    assert fresh_router.get("test.noop") is action


def test_register_rejects_non_toolaction(fresh_router: ToolRouter) -> None:
    with pytest.raises(TypeError, match="ToolAction"):
        fresh_router.register("not-an-action")  # type: ignore[arg-type]


def test_register_rejects_empty_action_id(
    fresh_router: ToolRouter,
) -> None:
    # The dataclass allows empty strings (it's a data holder); the
    # router is the enforcement point.
    with pytest.raises(ValueError, match="must be non-empty"):
        fresh_router.register(ToolAction(action_id="", label="X"))


def test_register_idempotent_same_triple(fresh_router: ToolRouter) -> None:
    action = ToolAction(action_id="a.b", label="AB")
    fresh_router.register(action)
    # Re-registering the identical triple is a no-op.
    fresh_router.register(action)
    assert len(fresh_router.list_actions()) == 1


def test_register_conflict_raises(fresh_router: ToolRouter) -> None:
    fresh_router.register(ToolAction(action_id="a.b", label="AB"))
    with pytest.raises(ValueError, match="already registered"):
        fresh_router.register(
            ToolAction(action_id="a.b", label="AB", rust_backing="foo.bar"),
        )


def test_unregister_returns_true_when_present(
    fresh_router: ToolRouter,
) -> None:
    fresh_router.register(ToolAction(action_id="a.b", label="AB"))
    assert fresh_router.unregister("a.b") is True
    assert fresh_router.has_action("a.b") is False


def test_unregister_returns_false_when_absent(
    fresh_router: ToolRouter,
) -> None:
    assert fresh_router.unregister("nope.nope") is False


# ---------------------------------------------------------------------------
# 2. Rust-backing lookup
# ---------------------------------------------------------------------------


def test_has_rust_backing_none_when_missing_action(
    fresh_router: ToolRouter,
) -> None:
    assert fresh_router.has_rust_backing("does.not.exist") is False


def test_has_rust_backing_false_when_backing_is_none(
    fresh_router: ToolRouter,
) -> None:
    fresh_router.register(
        ToolAction(action_id="a.b", label="AB", rust_backing=None),
    )
    assert fresh_router.has_rust_backing("a.b") is False


def test_has_rust_backing_true_when_symbol_exists(
    seeded_router: ToolRouter,
) -> None:
    """editor.save is wired to slap_format.lz4_compress — which ships."""
    try:
        import slappyengine._core  # noqa: F401
    except ImportError:
        pytest.skip("_core extension not available")
    assert seeded_router.has_rust_backing("editor.save") is True


def test_has_rust_backing_false_when_symbol_missing(
    fresh_router: ToolRouter,
) -> None:
    fresh_router.register(
        ToolAction(
            action_id="a.b",
            label="AB",
            rust_backing="nonexistent_module.absent_function",
        ),
    )
    assert fresh_router.has_rust_backing("a.b") is False


def test_rust_backing_symbol_returns_callable(
    seeded_router: ToolRouter,
) -> None:
    try:
        import slappyengine._core  # noqa: F401
    except ImportError:
        pytest.skip("_core extension not available")
    sym = seeded_router.rust_backing_symbol("editor.save")
    assert sym is not None
    assert callable(sym)


def test_rust_backing_cache_is_stable(
    fresh_router: ToolRouter,
) -> None:
    fresh_router.register(
        ToolAction(
            action_id="a.b", label="AB",
            rust_backing="nonexistent_module.absent_function",
        ),
    )
    # Two lookups — same result.
    a = fresh_router.has_rust_backing("a.b")
    b = fresh_router.has_rust_backing("a.b")
    assert a is False and b is False


def test_clear_rust_cache_forces_relookup(
    fresh_router: ToolRouter,
) -> None:
    fresh_router.register(
        ToolAction(
            action_id="a.b", label="AB",
            rust_backing="nonexistent_module.absent_function",
        ),
    )
    fresh_router.has_rust_backing("a.b")
    assert "a.b" in fresh_router._rust_cache
    fresh_router.clear_rust_cache()
    assert fresh_router._rust_cache == {}


def test_rust_backing_accepts_dotted_core_prefix(
    fresh_router: ToolRouter,
) -> None:
    """Both `_core.slap_format.lz4_compress` and `slap_format.lz4_compress` work."""
    try:
        import slappyengine._core  # noqa: F401
    except ImportError:
        pytest.skip("_core extension not available")
    fresh_router.register(
        ToolAction(
            action_id="test.compress",
            label="Compress",
            rust_backing="_core.slap_format.lz4_compress",
        ),
    )
    assert fresh_router.has_rust_backing("test.compress") is True


# ---------------------------------------------------------------------------
# 3. Dispatch
# ---------------------------------------------------------------------------


def test_dispatch_raises_on_unknown_action(
    fresh_router: ToolRouter,
) -> None:
    with pytest.raises(KeyError, match="unknown action_id"):
        fresh_router.dispatch("does.not.exist")


def test_dispatch_returns_none_when_no_backing(
    fresh_router: ToolRouter,
) -> None:
    fresh_router.register(ToolAction(action_id="a.b", label="AB"))
    assert fresh_router.dispatch("a.b") is None


def test_dispatch_ctx_defaults_to_empty_dict(
    fresh_router: ToolRouter,
) -> None:
    captured: dict[str, Any] = {}

    def fb(ctx: dict[str, Any]) -> str:
        captured.update(ctx)
        return "ran"

    fresh_router.register(
        ToolAction(action_id="a.b", label="AB", python_fallback=fb),
    )
    assert fresh_router.dispatch("a.b") == "ran"
    assert captured == {}


def test_dispatch_ctx_propagates_to_fallback(
    fresh_router: ToolRouter,
) -> None:
    captured: dict[str, Any] = {}

    def fb(ctx: dict[str, Any]) -> Any:
        captured.update(ctx)
        return ctx.get("value")

    fresh_router.register(
        ToolAction(action_id="a.b", label="AB", python_fallback=fb),
    )
    result = fresh_router.dispatch("a.b", {"value": 42, "extra": "yes"})
    assert result == 42
    assert captured["extra"] == "yes"


def test_dispatch_rejects_non_dict_ctx(
    fresh_router: ToolRouter,
) -> None:
    fresh_router.register(ToolAction(action_id="a.b", label="AB"))
    with pytest.raises(TypeError, match="ctx must be a dict"):
        fresh_router.dispatch("a.b", ["not", "a", "dict"])  # type: ignore[arg-type]


def test_dispatch_rust_backing_falls_through_on_type_error(
    fresh_router: ToolRouter,
) -> None:
    """When the Rust kernel raises TypeError, the fallback runs."""
    called: dict[str, bool] = {"fb": False}

    def fb(ctx: dict[str, Any]) -> str:
        called["fb"] = True
        return "python"

    # Point at a real Rust symbol that will TypeError on kwargs.
    try:
        import slappyengine._core  # noqa: F401
    except ImportError:
        pytest.skip("_core extension not available")
    fresh_router.register(
        ToolAction(
            action_id="test.type_mismatch",
            label="Type Mismatch",
            rust_backing="slap_format.lz4_compress",
            python_fallback=fb,
        ),
    )
    # Passing keyword args the Rust fn doesn't accept -> fallback fires.
    result = fresh_router.dispatch(
        "test.type_mismatch",
        {"nonsense_kwarg": "value"},
    )
    assert called["fb"] is True
    assert result == "python"


def test_dispatch_falls_back_when_rust_symbol_missing(
    fresh_router: ToolRouter,
) -> None:
    fresh_router.register(
        ToolAction(
            action_id="a.b",
            label="AB",
            rust_backing="nonexistent_module.absent_function",
            python_fallback=lambda ctx: "python-ran",
        ),
    )
    assert fresh_router.dispatch("a.b") == "python-ran"


# ---------------------------------------------------------------------------
# 4. Listing / introspection
# ---------------------------------------------------------------------------


def test_list_actions_is_sorted(fresh_router: ToolRouter) -> None:
    fresh_router.register(ToolAction(action_id="z.z", label="Z"))
    fresh_router.register(ToolAction(action_id="a.a", label="A"))
    fresh_router.register(ToolAction(action_id="m.m", label="M"))
    ids = [a.action_id for a in fresh_router.list_actions()]
    assert ids == ["a.a", "m.m", "z.z"]


def test_list_by_category_filters(fresh_router: ToolRouter) -> None:
    fresh_router.register(
        ToolAction(action_id="a.a", label="A", category="file"),
    )
    fresh_router.register(
        ToolAction(action_id="b.b", label="B", category="edit"),
    )
    fresh_router.register(
        ToolAction(action_id="c.c", label="C", category="file"),
    )
    file_ids = [a.action_id for a in fresh_router.list_by_category("file")]
    assert file_ids == ["a.a", "c.c"]


# ---------------------------------------------------------------------------
# 5. Default registration coverage
# ---------------------------------------------------------------------------


def test_default_registry_has_at_least_50_actions() -> None:
    """The canonical seed covers every hotkey + spawn + content action."""
    assert len(REGISTRY.list_actions()) >= 50


def test_every_hotkey_command_is_registered() -> None:
    """Every command in the NotebookHotkeys table has a router registration."""
    from slappyengine.ui.editor.notebook_hotkeys import _BINDINGS_FROZEN

    missing: list[str] = []
    for _key, command in _BINDINGS_FROZEN.items():
        # Layout / panel-toggle commands land as full ids in the registry.
        if not REGISTRY.has_action(command):
            missing.append(command)
    assert not missing, f"Hotkey commands missing router entries: {missing}"


def test_every_spawn_card_is_registered() -> None:
    """Every SpawnCard.card_id has a matching `spawn.<id>` action."""
    from slappyengine.ui.editor.notebook_spawn_menu import SPAWN_CARDS

    # SPAWN_CARDS entries are tuples whose first item is the card_id.
    for card_tuple in SPAWN_CARDS:
        card_id = card_tuple[0]
        aid = f"spawn.{card_id}"
        assert REGISTRY.has_action(aid), (
            f"spawn card {card_id!r} has no router action {aid!r}"
        )


def test_content_browser_actions_registered() -> None:
    for aid in (
        "content.open",
        "content.reveal_in_folder",
        "content.import",
        "content.new_script",
    ):
        assert REGISTRY.has_action(aid), f"Missing content action: {aid}"


def test_tool_change_actions_registered() -> None:
    for aid in (
        "editor.tool_select",
        "editor.tool_move",
        "editor.tool_rotate",
        "editor.tool_scale",
    ):
        assert REGISTRY.has_action(aid), f"Missing tool action: {aid}"


def test_layout_preset_actions_registered() -> None:
    for name in ("default", "wide_code", "focus", "triple_pane", "compact"):
        aid = f"editor.layout_preset_{name}"
        assert REGISTRY.has_action(aid), f"Missing layout preset: {aid}"


# ---------------------------------------------------------------------------
# 6. Shell integration — fake shell drives the router
# ---------------------------------------------------------------------------


class _FakeShell:
    """Minimal EditorShell double: captures method calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._active_tool = "select"
        self._selected_entity = None
        self._engine = types.SimpleNamespace()
        self._toolbar = None
        self._project = None
        self._content_browser = None
        self._creature_scheduler = None

    def __getattr__(self, name: str) -> Any:
        # Return a captured no-op callable for any missing attribute so
        # the router's _shell_call helper can invoke them.
        def _record(*args: Any, **kwargs: Any) -> Any:
            self.calls.append((name, args))
            return name
        return _record


def test_default_action_dispatches_via_shell_fallback() -> None:
    shell = _FakeShell()
    result = REGISTRY.dispatch("editor.save", {"shell": shell})
    # Either the fallback fired (calls captured) or the Rust backing was
    # tried and gracefully no-op'd. Either way, no exception should have
    # escaped; the shell's method table should show the routing decision.
    # The Rust backing (slap_format.lz4_compress) is very likely to
    # TypeError on our empty kwargs, so the fallback should have fired.
    assert "_save_project" in [c[0] for c in shell.calls]


def test_tool_change_updates_shell_active_tool() -> None:
    shell = _FakeShell()
    REGISTRY.dispatch("editor.tool_move", {"shell": shell})
    assert shell._active_tool == "move"


def test_registered_action_labels_are_populated() -> None:
    for action in REGISTRY.list_actions():
        assert action.label, (
            f"Action {action.action_id!r} has empty label"
        )


def test_register_default_actions_is_idempotent() -> None:
    """Re-seeding an already-populated router adds nothing."""
    before = len(REGISTRY.list_actions())
    added = register_default_actions(REGISTRY)
    after = len(REGISTRY.list_actions())
    assert added == 0
    assert before == after
