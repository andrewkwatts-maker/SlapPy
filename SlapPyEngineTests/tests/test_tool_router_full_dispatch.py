"""YY5 omnibus integration test — dispatch every registered ToolRouter action.

Every ``action_id`` in :data:`slappyengine.tool_router.REGISTRY` is
dispatched through :meth:`ToolRouter.dispatch` with a synthetic ``ctx``
dict. The test asserts that:

1. No uncaught exceptions escape ``dispatch`` (except pre-declared cases
   documented in :data:`_EXPECTED_MISSING_CTX`).
2. Every result is either
   * a :class:`dict` (canonical action-return shape — carries
     ``status`` / ``warning`` / ``error`` payloads), or
   * ``None`` (declared-but-no-op valid result), or
   * a non-dict value returned by a legacy fallback (accepted but
     surfaced in the metrics for visibility).

This is a **read-only** integration exercise: it must not modify
``tool_router.py`` or any action module. The synthetic ``ctx`` provides
the union of keys named by ``ToolAction.required_args`` across every
row of the registry so no single action starves of a required key.

Design provenance
-----------------

STUB-triage rounds r14-r24 landed 60+ action ids with Python fallbacks
across ``slappyengine.actions``. Each individual round shipped its own
targeted test module (``test_actions_stub_triage_r15`` …
``test_actions_stub_triage_r24``) exercising the ~5 action ids added
that round. This omnibus test is the load-bearing regression net that
guards against a future stub landing without a fallback — dispatching
the full ``REGISTRY`` in one loop surfaces any raise-on-empty-ctx bug
before it ships.

The test also collects human-readable metrics (success dict count,
no-op count, raised count) and asserts a lower-bound registry size
(sanity check against a future refactor that silently drops rows).
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from slappyengine.tool_router import (
    REGISTRY,
    ToolAction,
    ToolRouter,
    register_default_actions,
)


# ---------------------------------------------------------------------------
# Pre-declared exceptions
# ---------------------------------------------------------------------------

# Action ids that are *allowed* to raise from a synthetic ctx. Empty for
# now — every landed fallback is documented headless-safe. Grows only if
# a future action legitimately requires a live editor context (e.g. GPU
# handle, DPG viewport) and cannot be exercised headlessly.
_EXPECTED_MISSING_CTX: set[str] = set()


# ---------------------------------------------------------------------------
# Synthetic ctx builder
# ---------------------------------------------------------------------------


def _make_layer(name: str, z: float) -> SimpleNamespace:
    return SimpleNamespace(name=name, z=z)


def _make_entity(
    tags: tuple[str, ...] = (),
    layer: SimpleNamespace | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        name=f"e_{id(tags):x}",
        tags=set(tags),
        layer=layer,
        hidden=False,
        locked=False,
        prefab_kind="rope",
        kind="rope",
        material="mat_a",
        type="rope",
        selected=False,
        position=(0.0, 0.0, 0.0),
        transform=SimpleNamespace(position=(0.0, 0.0, 0.0)),
    )


def _make_scene() -> SimpleNamespace:
    layers = [_make_layer("A", 0.0), _make_layer("B", 1.0)]
    entities = [
        _make_entity(tags=("hero",), layer=layers[0]),
        _make_entity(tags=("enemy",), layer=layers[0]),
        _make_entity(tags=("prop",), layer=layers[1]),
    ]
    scene = SimpleNamespace(
        _entities=list(entities),
        _z_layers=list(layers),
        entities=entities,
        z_layers=layers,
    )
    return scene


def _make_shell() -> SimpleNamespace:
    scene = _make_scene()
    return SimpleNamespace(
        _scene=scene,
        _selected_entities=[],
        _active_layer=scene._z_layers[0],
        _cursor_position=[0.0, 0.0, 0.0],
    )


def _make_ctx() -> dict[str, Any]:
    """Return the union of every key any registered action might look up.

    A single ctx dict is reused across every dispatch call — the router
    normalises ``None`` to ``{}`` and every registered fallback is
    documented ctx-tolerant. The keys below cover:

    * ``shell`` / ``scene`` / ``selection`` / ``target`` — editor
      handles named by the older ``_fb_*`` shell-delegator fallbacks.
    * ``path`` / ``name`` / ``new_name`` / ``tag`` / ``kind`` — string
      arguments named by ``ToolAction.required_args`` for content /
      naming / tag flows.
    * ``spec`` / ``card_id`` — spawn payloads.
    * ``position`` / ``cursor`` / ``grid_size`` / ``distance`` /
      ``degrees`` / ``size`` — numeric arguments for camera + snap +
      spawn actions.
    * ``layer`` / ``layer_name`` / ``panel_id`` / ``theme`` — targeting
      arguments for layer / panel / theme actions.
    """
    shell = _make_shell()
    return {
        "shell": shell,
        "scene": shell._scene,
        "selection": list(shell._selected_entities),
        "target": shell._scene._entities[0],
        # Content-browser + naming args.
        "path": "C:/nonexistent/asset.png",
        "name": "entity_0",
        "new_name": "entity_new",
        # Panel / theme / tag / kind targeting.
        "panel_id": "inspector",
        "theme": "dark",
        "tag": "enemy",
        "kind": "rope",
        # Spawn args.
        "spec": {},
        "card_id": "rope",
        # Numeric args.
        "position": [1.0, 2.0, 3.0],
        "cursor": (0.0, 0.0, 0.0),
        "grid_size": 1.0,
        "distance": 5.0,
        "degrees": 15.0,
        "size": 2.0,
        # Layer targeting.
        "layer": shell._scene._z_layers[0],
        "layer_name": "A",
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def router() -> ToolRouter:
    """Return a fresh router pre-populated with the canonical seed set.

    A dedicated router (rather than the module-level :data:`REGISTRY`)
    keeps the omnibus test hermetic — nothing this test does can bleed
    into later tests in the same session.
    """
    r = ToolRouter()
    register_default_actions(r)
    return r


# ---------------------------------------------------------------------------
# Sanity checks
# ---------------------------------------------------------------------------


def test_registry_populated(router: ToolRouter) -> None:
    """Guard against a refactor that silently drops seed rows."""
    actions = router.list_actions()
    # Round 24 (WW4) put the registry above 160 rows. Round-numeric to
    # 100 so a future consolidation pass doesn't have to re-tune this
    # bound every time.
    assert len(actions) >= 100, (
        f"REGISTRY size dropped below 100 rows (got {len(actions)}) — "
        "check register_default_actions for silently-removed seeds."
    )


def test_module_singleton_matches_fresh_router(
    router: ToolRouter,
) -> None:
    """The module-level :data:`REGISTRY` should carry the same action ids."""
    fresh_ids = {a.action_id for a in router.list_actions()}
    module_ids = {a.action_id for a in REGISTRY.list_actions()}
    assert fresh_ids == module_ids, (
        "REGISTRY singleton diverged from register_default_actions() — "
        "fresh set has "
        f"{fresh_ids ^ module_ids} that the other doesn't."
    )


# ---------------------------------------------------------------------------
# Omnibus dispatch
# ---------------------------------------------------------------------------


def _dispatch_result_shape(result: Any) -> str:
    """Classify ``result`` into one of the metric buckets.

    Returns
    -------
    str
        ``"dict_status"``    — result is a dict with a ``status``,
                              ``warning``, or ``error`` key.
        ``"dict_other"``     — result is a dict without any of those
                              canonical keys (still accepted, but
                              flagged for visibility).
        ``"noop"``           — result is ``None`` (declared no-op).
        ``"scalar"``         — result is a non-dict, non-None value
                              (legacy fallbacks returning e.g. the
                              tool id string).
    """
    if result is None:
        return "noop"
    if isinstance(result, dict):
        canonical_keys = {"status", "warning", "error"}
        if canonical_keys & set(result.keys()):
            return "dict_status"
        return "dict_other"
    return "scalar"


def test_full_dispatch_no_uncaught_exceptions(
    router: ToolRouter,
) -> None:
    """Every action dispatches without raising (except pre-declared cases).

    Metrics collected in the loop are printed at teardown via
    :func:`pytest.fail` when an unexpected raise is detected — the
    failure message lists every raiser so a single test run pinpoints
    the regression source.
    """
    action_ids = [a.action_id for a in router.list_actions()]
    metrics: dict[str, list[str]] = {
        "dict_status": [],
        "dict_other": [],
        "noop": [],
        "scalar": [],
    }
    raised: list[tuple[str, str, str]] = []
    for aid in action_ids:
        ctx = _make_ctx()
        try:
            result = router.dispatch(aid, ctx)
        except Exception as exc:  # noqa: BLE001 — this is the assertion.
            if aid in _EXPECTED_MISSING_CTX:
                continue
            raised.append((aid, type(exc).__name__, str(exc)[:120]))
            continue
        metrics[_dispatch_result_shape(result)].append(aid)
    if raised:
        detail = "\n".join(
            f"  {aid}: {exc}: {msg}" for aid, exc, msg in raised
        )
        pytest.fail(
            f"{len(raised)} action(s) raised on dispatch with synthetic "
            f"ctx:\n{detail}"
        )
    # Summary metrics (visible in verbose pytest output) — asserted as
    # lower bounds so a future refactor that consolidates fallbacks
    # doesn't trip the guard rails.
    total = sum(len(v) for v in metrics.values())
    assert total == len(action_ids), (
        f"metric bucket total ({total}) diverged from action count "
        f"({len(action_ids)}) — classifier missed a branch."
    )
    # At least *some* action must land in the canonical status bucket —
    # this guards against a router regression that silently returns
    # ``None`` for every call.
    assert len(metrics["dict_status"]) >= 30, (
        "fewer than 30 actions returned a canonical status dict — "
        "router regression? "
        f"buckets: dict_status={len(metrics['dict_status'])}, "
        f"dict_other={len(metrics['dict_other'])}, "
        f"noop={len(metrics['noop'])}, scalar={len(metrics['scalar'])}"
    )


def test_full_dispatch_with_none_ctx_no_crash(
    router: ToolRouter,
) -> None:
    """``dispatch(aid, None)`` must not raise for any registered action.

    :meth:`ToolRouter.dispatch` normalises ``ctx=None`` to ``{}`` before
    invoking the fallback. Every fallback is documented tolerant of the
    empty-dict case (may return ``{"status": "no_shell"}`` or ``None``,
    but must not raise).
    """
    action_ids = [a.action_id for a in router.list_actions()]
    raised: list[tuple[str, str, str]] = []
    for aid in action_ids:
        try:
            router.dispatch(aid, None)
        except Exception as exc:  # noqa: BLE001
            if aid in _EXPECTED_MISSING_CTX:
                continue
            raised.append((aid, type(exc).__name__, str(exc)[:120]))
    if raised:
        detail = "\n".join(
            f"  {aid}: {exc}: {msg}" for aid, exc, msg in raised
        )
        pytest.fail(
            f"{len(raised)} action(s) raised on dispatch(aid, None):\n"
            f"{detail}"
        )


def test_full_dispatch_returns_valid_shape(
    router: ToolRouter,
) -> None:
    """Every dispatch result satisfies the three-way shape contract."""
    for a in router.list_actions():
        if a.action_id in _EXPECTED_MISSING_CTX:
            continue
        ctx = _make_ctx()
        result = router.dispatch(a.action_id, ctx)
        assert (
            result is None
            or isinstance(result, dict)
            or isinstance(result, (str, int, float, bool, tuple, list))
        ), (
            f"{a.action_id} returned an unexpected shape "
            f"{type(result).__name__}: {result!r}"
        )


# ---------------------------------------------------------------------------
# Category coverage
# ---------------------------------------------------------------------------


def test_every_category_dispatches_cleanly(
    router: ToolRouter,
) -> None:
    """Bucket dispatch results by :attr:`ToolAction.category`.

    Ensures no single category is silently broken — a per-category
    raise-count assertion means a targeted regression (e.g. every
    ``layer.*`` action starts raising because the layer module went
    read-only) surfaces without a full-registry scan.
    """
    per_cat_raised: dict[str, list[str]] = {}
    per_cat_total: dict[str, int] = {}
    for a in router.list_actions():
        per_cat_total[a.category] = per_cat_total.get(a.category, 0) + 1
        ctx = _make_ctx()
        try:
            router.dispatch(a.action_id, ctx)
        except Exception:  # noqa: BLE001
            if a.action_id in _EXPECTED_MISSING_CTX:
                continue
            per_cat_raised.setdefault(a.category, []).append(a.action_id)
    for cat, raised_ids in per_cat_raised.items():
        pytest.fail(
            f"category {cat!r} had {len(raised_ids)} raiser(s) "
            f"(of {per_cat_total[cat]}): {raised_ids}"
        )


# ---------------------------------------------------------------------------
# Metrics dump (skipped by default — enable with -k full_dispatch_metrics)
# ---------------------------------------------------------------------------


def test_full_dispatch_metrics_dump(
    router: ToolRouter,
    capsys: pytest.CaptureFixture,
) -> None:
    """Print the success / no-op / raised breakdown for humans.

    This test always passes — it exists so ``pytest -s`` produces the
    human-readable summary that the YY5 sprint deliverable calls for.
    Use ``pytest -s -k full_dispatch_metrics`` to see it.
    """
    metrics: dict[str, list[str]] = {
        "dict_status": [],
        "dict_other": [],
        "noop": [],
        "scalar": [],
    }
    raised: list[tuple[str, str]] = []
    for a in router.list_actions():
        ctx = _make_ctx()
        try:
            result = router.dispatch(a.action_id, ctx)
        except Exception as exc:  # noqa: BLE001
            raised.append((a.action_id, type(exc).__name__))
            continue
        metrics[_dispatch_result_shape(result)].append(a.action_id)
    total = len(router.list_actions())
    print(f"\n[YY5] Total registered actions: {total}")
    print(f"[YY5] dict with status/warning/error: {len(metrics['dict_status'])}")
    print(f"[YY5] dict without canonical keys:    {len(metrics['dict_other'])}")
    print(f"[YY5] None (no-op):                   {len(metrics['noop'])}")
    print(f"[YY5] Non-dict scalar:                {len(metrics['scalar'])}")
    print(f"[YY5] Raised:                         {len(raised)}")
    if raised:
        for aid, exc in raised:
            print(f"  RAISED: {aid} -> {exc}")
    # Always pass — this is a metrics-only test.
    assert total >= 100
