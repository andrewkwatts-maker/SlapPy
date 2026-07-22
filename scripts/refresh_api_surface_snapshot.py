"""Regenerate the API-surface snapshot at
``PharosEngineTests/tests/data/api_surface_snapshot.json``.

Run this ONLY when a deletion is intentional. Per
``docs/api_stability_2026_07_07.md``:

* Require a CHANGELOG entry naming the deleted symbol(s).
* Require a 1-minor-version deprecation cycle (``warnings.warn`` on the
  old symbol) before the actual removal.

Then run this script to lock the new surface. The paired
``PharosEngineTests/tests/test_backcompat_api_surface.py`` will then
accept the new state.

Usage
-----

    python scripts/refresh_api_surface_snapshot.py

Prints the new symbol count and diff summary so the operator can sanity
check before committing the JSON change.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


# Load-bearing modules whose public surface downstream games depend on.
# Additions here are permanent — every module listed becomes a
# pinned tripwire for future deletions.
MODULES = [
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
]


REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON_PKG = REPO_ROOT / "python"
SNAPSHOT_PATH = (
    REPO_ROOT
    / "PharosEngineTests"
    / "tests"
    / "data"
    / "api_surface_snapshot.json"
)


def _current_public_names(module_name: str) -> list[str]:
    m = importlib.import_module(module_name)
    if module_name == "pharos_engine":
        # Top-level uses PEP 562 lazy-load — enumerate __all__.
        return sorted(set(getattr(m, "__all__", [])))
    return sorted(n for n in dir(m) if not n.startswith("_"))


def _load_prev_snapshot() -> dict[str, list[str]]:
    if SNAPSHOT_PATH.exists():
        with SNAPSHOT_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def main() -> int:
    # Make in-tree source importable without a pip install.
    if str(PYTHON_PKG) not in sys.path:
        sys.path.insert(0, str(PYTHON_PKG))

    prev = _load_prev_snapshot()
    new: dict[str, list[str]] = {}

    for mod_name in MODULES:
        try:
            new[mod_name] = _current_public_names(mod_name)
        except Exception as e:  # pragma: no cover — operator-visible
            print(f"FAILED to import {mod_name}: {e}", file=sys.stderr)
            return 1

    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SNAPSHOT_PATH.open("w", encoding="utf-8") as f:
        json.dump(new, f, indent=2, sort_keys=True)
        f.write("\n")

    # Report the diff so the operator can sanity-check.
    print(f"Wrote {SNAPSHOT_PATH}")
    total_new = sum(len(v) for v in new.values())
    total_prev = sum(len(v) for v in prev.values())
    print(
        f"Symbols: {total_prev} -> {total_new} "
        f"({total_new - total_prev:+d}) across {len(new)} modules"
    )
    for mod in sorted(set(prev) | set(new)):
        p = set(prev.get(mod, []))
        n = set(new.get(mod, []))
        added = sorted(n - p)
        removed = sorted(p - n)
        if added or removed:
            print(f"  {mod}:")
            if removed:
                print(f"    - removed ({len(removed)}): {removed}")
            if added:
                print(f"    + added   ({len(added)}): {added}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
