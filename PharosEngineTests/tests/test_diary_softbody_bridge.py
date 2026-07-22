"""Tests for :mod:`pharos_editor.ui.editor.diary_softbody_bridge`.

Covers the AA3 shim that closes rows 80 + 223 in
``docs/engine_feature_map_2026_07_04.md`` — the diary tick's
softbody import + file-import entry point.

Test surface (8 named cases):

1. ``resolve_softbody_class`` returns a callable in the vanilla
   import order (dynamics available, WIP softbody may or may not be).
2. ``resolve_softbody_class`` prefers ``pharos_engine.softbody`` when
   both are importable (via a mocked WIP path).
3. ``resolve_softbody_class`` falls back to
   ``pharos_engine.dynamics`` when the WIP softbody path is missing.
4. ``resolve_softbody_class`` raises a friendly ``ImportError``
   naming both paths when both are absent.
5. ``import_softbody_file`` round-trips a ``.softbody.json``
   fixture into a dynamics world.
6. ``import_softbody_file`` round-trips a ``.softbody.yaml``
   fixture into a dynamics world.
7. ``import_softbody_file`` raises ``FileNotFoundError`` on a
   missing path.
8. ``import_softbody_file`` raises ``ValueError`` on an unsupported
   suffix.

Plus a bonus case: ``import_softbody_file`` falls back to
``world.bodies.append`` when the world does not expose
``register_body``.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from pharos_editor.ui.editor.diary_softbody_bridge import (
    _MISSING_MESSAGE,
    import_softbody_file,
    resolve_softbody_class,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dynamics_world() -> Any:
    """Return a fresh :class:`pharos_engine.dynamics.World` seeded with
    enough nodes to host a small imported body."""
    from pharos_engine.dynamics import World

    world = World()
    # Give the world 4 nodes so a body with node_count=4 is valid.
    for i in range(4):
        world.add_node((float(i), 0.0), mass=1.0)
    return world


def _write_json_fixture(path: Path) -> dict[str, Any]:
    """Write a minimal ``.softbody.json`` fixture and return the payload."""
    payload = {
        "_kind": "Body",
        "kind": "lattice",
        "node_offset": 0,
        "node_count": 4,
        "label": "diary_import_json",
        "parameters": {"origin": "aa3_test"},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


def _write_yaml_fixture(path: Path) -> dict[str, Any]:
    """Write a minimal ``.softbody.yaml`` fixture and return the payload.

    Uses a plain ``key: value`` format so the test also exercises the
    naive-parser fallback path when PyYAML is unavailable.
    """
    text = (
        "# Diary softbody fixture — AA3 test\n"
        "kind: lattice\n"
        "node_offset: 0\n"
        "node_count: 4\n"
        'label: "diary_import_yaml"\n'
        'parameters: {"origin": "aa3_test"}\n'
    )
    path.write_text(text, encoding="utf-8")
    return {
        "kind": "lattice",
        "node_offset": 0,
        "node_count": 4,
        "label": "diary_import_yaml",
        "parameters": {"origin": "aa3_test"},
    }


# ---------------------------------------------------------------------------
# 1. resolve returns a callable
# ---------------------------------------------------------------------------


def test_resolve_returns_callable_default_env() -> None:
    """In the current test env at least one path should resolve."""
    cls = resolve_softbody_class()
    assert callable(cls), "resolve_softbody_class must return a constructor"


# ---------------------------------------------------------------------------
# 2. resolve prefers WIP softbody when both are importable
# ---------------------------------------------------------------------------


def test_resolve_prefers_softbody_when_present(monkeypatch) -> None:
    """When the WIP softbody module is mockable to a class, it wins."""

    class _FakeWorld:
        """Sentinel — never instantiated, we just check identity."""

    fake_mod = types.ModuleType("pharos_engine.softbody")
    fake_mod.SoftBodyWorld = _FakeWorld
    monkeypatch.setitem(sys.modules, "pharos_engine.softbody", fake_mod)

    cls = resolve_softbody_class()
    assert cls is _FakeWorld, (
        "resolve_softbody_class must prefer pharos_engine.softbody when it "
        "exposes SoftBodyWorld"
    )


# ---------------------------------------------------------------------------
# 3. resolve falls back to dynamics when WIP softbody is missing
# ---------------------------------------------------------------------------


def test_resolve_falls_back_to_dynamics(monkeypatch) -> None:
    """When the WIP softbody import fails, dynamics.SoftBodyWorld wins."""
    # Force the WIP softbody import to raise by stubbing a broken module
    # into sys.modules; the bridge should catch and fall through.
    broken = types.ModuleType("pharos_engine.softbody")
    # No SoftBodyWorld attr — mimics "package present but symbol missing".
    monkeypatch.setitem(sys.modules, "pharos_engine.softbody", broken)

    from pharos_engine.dynamics import SoftBodyWorld as DynamicsSoftBody

    cls = resolve_softbody_class()
    assert cls is DynamicsSoftBody, (
        "resolve_softbody_class must fall back to dynamics.SoftBodyWorld "
        "when the WIP softbody path lacks SoftBodyWorld"
    )


# ---------------------------------------------------------------------------
# 4. resolve raises a friendly ImportError when both are missing
# ---------------------------------------------------------------------------


def test_resolve_raises_friendly_when_both_missing(monkeypatch) -> None:
    """Both paths mocked out -> friendly ImportError naming both."""
    # Wipe both cached modules so our sentinel modules take effect.
    for key in ("pharos_engine.softbody", "pharos_engine.dynamics"):
        monkeypatch.delitem(sys.modules, key, raising=False)

    def _bad_softbody_import(name: str, *args: Any, **kwargs: Any):
        if name == "pharos_engine.softbody" or name.startswith(
            "pharos_engine.softbody."
        ):
            raise ImportError(f"forced-off: {name}")
        if name == "pharos_engine.dynamics" or name.startswith(
            "pharos_engine.dynamics"
        ):
            raise ImportError(f"forced-off: {name}")
        return _real_import(name, *args, **kwargs)

    _real_import = __builtins__["__import__"] if isinstance(
        __builtins__, dict
    ) else __builtins__.__import__
    monkeypatch.setattr(
        "builtins.__import__", _bad_softbody_import
    )

    with pytest.raises(ImportError) as excinfo:
        resolve_softbody_class()
    msg = str(excinfo.value)
    assert "pharos_engine.softbody" in msg
    assert "pharos_engine.dynamics" in msg
    # Sanity — bridge exports the canonical message string.
    assert _MISSING_MESSAGE == msg


# ---------------------------------------------------------------------------
# 5. import_softbody_file round-trips JSON
# ---------------------------------------------------------------------------


def test_import_softbody_file_json_roundtrip(tmp_path) -> None:
    fixture = tmp_path / "test.softbody.json"
    payload = _write_json_fixture(fixture)
    world = _make_dynamics_world()

    body = import_softbody_file(fixture, world)

    assert body is not None
    assert body.kind == payload["kind"]
    assert body.node_count == payload["node_count"]
    assert body.label == payload["label"]
    # World should now hold exactly one registered body.
    assert len(world.bodies) == 1
    assert world.bodies[0] is body


# ---------------------------------------------------------------------------
# 6. import_softbody_file round-trips YAML
# ---------------------------------------------------------------------------


def test_import_softbody_file_yaml_roundtrip(tmp_path) -> None:
    fixture = tmp_path / "test.softbody.yaml"
    payload = _write_yaml_fixture(fixture)
    world = _make_dynamics_world()

    body = import_softbody_file(fixture, world)

    assert body is not None
    assert body.kind == payload["kind"]
    assert body.node_count == payload["node_count"]
    # The naive-YAML parser strips quotes; the PyYAML parser keeps
    # the raw string. Either way the label should decode to the same
    # payload value.
    assert body.label == payload["label"]
    assert len(world.bodies) == 1


# ---------------------------------------------------------------------------
# 7. import_softbody_file raises FileNotFoundError on missing path
# ---------------------------------------------------------------------------


def test_import_softbody_file_missing_path(tmp_path) -> None:
    world = _make_dynamics_world()
    missing = tmp_path / "does_not_exist.softbody.json"
    with pytest.raises(FileNotFoundError) as excinfo:
        import_softbody_file(missing, world)
    assert "does not exist" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 8. import_softbody_file raises ValueError on unsupported suffix
# ---------------------------------------------------------------------------


def test_import_softbody_file_bad_suffix(tmp_path) -> None:
    world = _make_dynamics_world()
    bogus = tmp_path / "test.softbody.txt"
    bogus.write_text("kind: lattice\n", encoding="utf-8")
    with pytest.raises(ValueError) as excinfo:
        import_softbody_file(bogus, world)
    assert "unsupported suffix" in str(excinfo.value)


# ---------------------------------------------------------------------------
# BONUS: bodies.append fallback when world lacks register_body
# ---------------------------------------------------------------------------


def test_import_softbody_file_bodies_append_fallback(tmp_path) -> None:
    """A duck-typed world with just ``bodies.append`` still accepts the
    imported body — matches the WIP softbody-world contract."""

    class _DuckWorld:
        def __init__(self) -> None:
            self.bodies: list[Any] = []

    fixture = tmp_path / "duck.softbody.json"
    _write_json_fixture(fixture)
    world = _DuckWorld()

    body = import_softbody_file(fixture, world)

    assert len(world.bodies) == 1
    assert world.bodies[0] is body
