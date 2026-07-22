"""Smoke test for every live example under `examples/`.

Each demo must:

1. **Parse as valid Python** (catches syntax errors).
2. **Resolve every `pharos_engine.*` symbol it references** (catches
   stale imports of deleted modules).

Tests do NOT execute the demo's body — `engine.run()` calls would
block on a window. The intent is "did the refactor break any demo's
import chain?", not "does the demo run end-to-end" (a separate
manual-run task per the project culture of GIF/PNG outputs).

Demos under `examples/legacy/` are intentionally skipped — they
remain on the old `pharos_engine.physics.*` surface, gated for
removal in Phase D.
"""
from __future__ import annotations

import ast
import importlib
import importlib.util
import sys
from pathlib import Path

import pytest


_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"


def _live_demos() -> list[Path]:
    """All `.py` files directly under `examples/` — excludes `legacy/`."""
    return sorted(
        p for p in _EXAMPLES_DIR.glob("*.py")
        if p.is_file() and not p.name.startswith("__")
    )


def _pharos_engine_imports(source: str) -> list[str]:
    """Return every fully-qualified `pharos_engine.<dotted>` import seen."""
    tree = ast.parse(source)
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "pharos_engine" or alias.name.startswith("pharos_engine."):
                    out.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "pharos_engine" or mod.startswith("pharos_engine."):
                out.append(mod)
    return out


@pytest.mark.parametrize("demo_path", _live_demos(), ids=lambda p: p.name)
def test_demo_parses(demo_path: Path) -> None:
    """Every live demo must be syntactically valid Python."""
    source = demo_path.read_text(encoding="utf-8")
    ast.parse(source)  # raises SyntaxError on failure


@pytest.mark.parametrize("demo_path", _live_demos(), ids=lambda p: p.name)
def test_demo_imports_resolvable(demo_path: Path) -> None:
    """Every `pharos_engine.*` module a demo imports must exist now."""
    source = demo_path.read_text(encoding="utf-8")
    for mod_name in _pharos_engine_imports(source):
        spec = importlib.util.find_spec(mod_name)
        assert spec is not None, (
            f"{demo_path.name}: imports {mod_name!r} which is not findable"
        )


def test_legacy_demos_are_isolated_in_subfolder() -> None:
    """The `physics_*.py` demos are pinned to old-physics; they must live
    under `examples/legacy/` so they don't clutter the live demo list."""
    stray = list(_EXAMPLES_DIR.glob("physics_*.py"))
    assert stray == [], (
        f"physics_*.py demos found at top level (should be under legacy/): {stray}"
    )
    legacy_dir = _EXAMPLES_DIR / "legacy"
    if legacy_dir.is_dir():
        legacy_demos = list(legacy_dir.glob("physics_*.py"))
        assert legacy_demos, "examples/legacy/ exists but is empty"


def test_live_demos_have_expected_names() -> None:
    """Sanity-check the set of live (non-legacy) demos."""
    names = {p.name for p in _live_demos()}
    expected = {
        "hello_world.py",
        "hello_pixel.py",
        "hello_lighting.py",
        "hello_3d_layer.py",
        "hello_bake.py",
        "hello_physics.py",
        "layered_character.py",
        "editor_demo.py",
        "hud_demo.py",
        "landscape_demo.py",
        "multiplayer_demo.py",
        "particles_sample.py",
        "fluid_demo.py",
        "softbody_vehicle_demo.py",
    }
    missing = expected - names
    assert not missing, f"expected demos missing from examples/: {missing}"
