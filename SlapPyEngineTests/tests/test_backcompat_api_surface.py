"""Backcompat pinning: enforce that no public symbol is silently deleted.

Motivation
----------
TT1's game-compat re-run (2026-07-07) uncovered three silent breaking
changes that engine-side tests did not catch:

    1. ``RenderTarget.__init__`` MRO issue (subclass ``add_layer`` before
       base init).
    2. ``global_bus`` deleted from ``pharos_engine.event_bus``.
    3. ``EventBus.unsubscribe(...)`` signature change.

These broke ~735 game tests across Ochema Circuit + Bullet Strata
WITHOUT tripping any engine-side test.

Root cause: engine tests don't exercise "subclass-in-external-code"
patterns; deletions don't set off any tripwire.

This module addresses the deletion class. It:

* enumerates every top-level import name in ``pharos_engine.__all__`` and
* enumerates every module-level public name in a curated list of
  load-bearing modules (``event_bus``, ``entity``, ``layer``, ...).

It then compares against a locked snapshot at
``SlapPyEngineTests/tests/data/api_surface_snapshot.json``.

Contract
--------
* Every name in the snapshot must still exist on the current build
  (missing = FAILURE).
* New names added since the snapshot are informational (``warnings.warn``,
  not a failure).

When a deletion is intentional, regenerate the snapshot via:

    python scripts/refresh_api_surface_snapshot.py

...and include a CHANGELOG entry per ``docs/api_stability_2026_07_07.md``.
"""
from __future__ import annotations

import importlib
import json
import warnings
from pathlib import Path

import pytest


SNAPSHOT_PATH = (
    Path(__file__).parent / "data" / "api_surface_snapshot.json"
)


def _load_snapshot() -> dict[str, list[str]]:
    if not SNAPSHOT_PATH.exists():
        raise FileNotFoundError(
            f"API-surface snapshot missing at {SNAPSHOT_PATH}. "
            "Regenerate via `python scripts/refresh_api_surface_snapshot.py`."
        )
    with SNAPSHOT_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _current_public_names(module_name: str) -> list[str]:
    """Return the current public symbol list for ``module_name``.

    For the top-level ``pharos_engine`` package we use ``__all__`` because
    the package uses PEP 562 lazy-load and ``dir()`` won't enumerate lazy
    names until they've been resolved.

    For every other module we use ``dir(m)`` filtered to non-underscore
    names — mirrors what ``from mod import *`` would offer downstream.
    """
    m = importlib.import_module(module_name)
    if module_name == "pharos_engine":
        return sorted(set(getattr(m, "__all__", [])))
    return sorted(n for n in dir(m) if not n.startswith("_"))


SNAPSHOT = _load_snapshot()


@pytest.mark.parametrize("module_name", sorted(SNAPSHOT.keys()))
def test_no_public_symbol_deleted(module_name: str) -> None:
    """Every symbol in the snapshot must still exist on this build.

    A failure here means a downstream game (Ochema Circuit, Bullet
    Strata, Stone Keep) that imports the missing symbol will crash at
    collection time with ``ImportError`` — exactly the class of silent
    regression TT1 caught on 2026-07-07.
    """
    pinned = set(SNAPSHOT[module_name])
    current = set(_current_public_names(module_name))
    missing = sorted(pinned - current)
    assert not missing, (
        f"{module_name}: {len(missing)} pinned public symbol(s) deleted "
        f"since snapshot. Missing: {missing[:20]}"
        + (" ..." if len(missing) > 20 else "")
        + "\nIf the deletion is intentional, add a CHANGELOG entry "
        "(see docs/api_stability_2026_07_07.md) and refresh the snapshot "
        "via `python scripts/refresh_api_surface_snapshot.py`."
    )


def test_snapshot_covers_declared_modules() -> None:
    """Sanity: the snapshot must at minimum cover the load-bearing modules
    called out in the sprint spec (agent UU7, 2026-07-07)."""
    required = {
        "pharos_engine",
        "pharos_engine.event_bus",
        "pharos_engine.entity",
        "pharos_engine.layer",
        "pharos_engine.render_target",
        "pharos_engine.asset",
        "pharos_engine.app",
        "pharos_engine.dynamics",
        "pharos_engine.physics3_bridge",
        "pharos_engine.diagnostics",
        "pharos_engine.hud_bridge",
        "pharos_engine.audio_3d",
        "pharos_engine.capture",
        "pharos_engine.exporter",
    }
    missing = required - set(SNAPSHOT.keys())
    assert not missing, (
        f"Snapshot is missing coverage for load-bearing modules: {missing}. "
        "Add them to `MODULES` in scripts/refresh_api_surface_snapshot.py "
        "and regenerate."
    )


def test_new_symbols_are_informational() -> None:
    """Emit a warning (not a failure) when symbols are ADDED since the
    snapshot. Additions are safe for downstream games; they only care
    about deletions."""
    added_by_module: dict[str, list[str]] = {}
    for module_name in SNAPSHOT.keys():
        pinned = set(SNAPSHOT[module_name])
        current = set(_current_public_names(module_name))
        added = sorted(current - pinned)
        if added:
            added_by_module[module_name] = added
    if added_by_module:
        total = sum(len(v) for v in added_by_module.values())
        warnings.warn(
            f"API surface has grown by {total} public symbol(s) since the "
            f"snapshot was frozen. Consider running "
            "`python scripts/refresh_api_surface_snapshot.py` to lock the "
            f"new surface. Added per module: {added_by_module}",
            stacklevel=2,
        )


def test_snapshot_total_symbol_count_reasonable() -> None:
    """Sanity floor: the pinned surface must not have shrunk to zero
    (e.g. an accidental empty snapshot commit). At time of freeze the
    surface was ~338 symbols; require at least 250 as a defensive lower
    bound."""
    total = sum(len(v) for v in SNAPSHOT.values())
    assert total >= 250, (
        f"Snapshot only contains {total} symbols — expected at least 250. "
        "Was the snapshot generated against a broken build?"
    )
