"""Tests for :mod:`SlapPyEngineExamples.examples.hello_full_editor` (AA5).

The demo ties every notebook-editor subsystem together in one scripted
run. These tests lock the "full first session" behaviour end-to-end:
prefab spawns, page walks, material graph, FX preset, code eval,
autosave snapshots, and the 6 diary themes.

Every test is headless — the demo keeps ``dpg.show_viewport()`` behind
its ``__main__`` guard so pytest can import + call ``run_demo`` without
opening a viewport.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Make examples/ importable as a top-level package.
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES = _REPO_ROOT / "SlapPyEngineExamples" / "examples"
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

import hello_full_editor as demo  # type: ignore[import-not-found]  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def run_trace(tmp_path_factory):
    """Run the demo once for the module and share the trace across tests."""
    trace_dir = tmp_path_factory.mktemp("hello_full_editor")
    trace_path = trace_dir / "hello_full_editor_trace.yaml"
    trace = demo.run_demo(trace_path=trace_path, use_dpg_context=False)
    return trace, trace_path


@pytest.fixture(scope="module")
def trace_events(run_trace):
    trace, _ = run_trace
    return trace.events


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        events: list[dict[str, Any]] = []
        for line in text.splitlines():
            stripped = line.lstrip()
            if stripped.startswith("- kind:"):
                events.append({"kind": stripped.split(":", 1)[1].strip()})
        return {"events": events, "event_count": len(events)}


# ---------------------------------------------------------------------------
# 1. Demo entrypoint + trace file
# ---------------------------------------------------------------------------


def test_demo_run_returns_trace(run_trace) -> None:
    """``run_demo`` returns a populated :class:`DemoTrace` without raising."""
    trace, _ = run_trace
    assert isinstance(trace, demo.DemoTrace)
    assert trace.events, "trace should record at least one event"


def test_trace_has_at_least_25_events(run_trace) -> None:
    """The scripted flow must record ≥ 25 events per the AA5 contract."""
    trace, trace_path = run_trace
    assert len(trace.events) >= 25, (
        f"in-memory trace must record ≥ 25 events, got {len(trace.events)}"
    )
    doc = _load_yaml(trace_path)
    on_disk = doc.get("events") or []
    assert len(on_disk) >= 25, (
        f"YAML trace must contain ≥ 25 events, got {len(on_disk)}"
    )


def test_trace_yaml_written(run_trace) -> None:
    _, trace_path = run_trace
    assert trace_path.exists(), "trace YAML must be persisted"
    assert trace_path.stat().st_size > 0


def test_trace_starts_and_ends_cleanly(trace_events) -> None:
    kinds = [e["kind"] for e in trace_events]
    assert kinds[0] == "demo_start", (
        f"first event must be demo_start, got {kinds[0]!r}"
    )
    assert "demo_end" in kinds, "demo_end must be recorded"


# ---------------------------------------------------------------------------
# 2. Prefab spawns
# ---------------------------------------------------------------------------


def test_three_prefabs_spawned(trace_events) -> None:
    """Each of crate / ball / chain must land a ``prefab_spawned`` event."""
    spawns = [e for e in trace_events if e["kind"] == "prefab_spawned"]
    names = [e["name"] for e in spawns]
    assert len(spawns) == 3, (
        f"expected 3 prefab_spawned events, got {len(spawns)} ({names})"
    )
    for expected in ("crate", "ball", "chain"):
        assert expected in names, f"prefab {expected!r} was never spawned"


def test_prefab_summary_reports_bodies(trace_events) -> None:
    summary = next(
        (e for e in trace_events if e["kind"] == "prefabs_summary"),
        None,
    )
    assert summary is not None, "prefabs_summary event missing"
    assert summary["body_count"] >= 3, (
        f"expected at least 3 bodies across prefabs, got "
        f"{summary['body_count']}"
    )
    assert summary["node_count"] > 0, "world should have simulation nodes"


# ---------------------------------------------------------------------------
# 3. Page walk + outliner selects
# ---------------------------------------------------------------------------


def test_diary_shell_built_with_six_pages(trace_events) -> None:
    built = next(
        (e for e in trace_events if e["kind"] == "diary_built"), None,
    )
    assert built is not None, "diary_built event missing"
    assert built["page_count"] == 6, (
        f"DiaryShell should have 6 pages, got {built['page_count']}"
    )


def test_page_switches_cover_all_target_pages(trace_events) -> None:
    """Scene, Material, FX, Code pages must each receive a switch."""
    switches = [e["to_page"] for e in trace_events if e["kind"] == "page_switch"]
    for expected in ("scene", "material", "fx", "code"):
        assert expected in switches, (
            f"page_switch missed target page {expected!r}; saw {switches}"
        )


def test_five_outliner_selects_recorded(trace_events) -> None:
    """The Scene page must fire exactly 5 outliner selects."""
    selects = [e for e in trace_events if e["kind"] == "outliner_select"]
    assert len(selects) == 5, (
        f"expected 5 outliner_select events, got {len(selects)}"
    )
    for evt in selects:
        assert evt["inspector_field_count"] > 0, (
            f"inspector should populate for {evt['entity_name']!r}"
        )


# ---------------------------------------------------------------------------
# 4. Material graph
# ---------------------------------------------------------------------------


def test_material_graph_has_three_nodes(trace_events) -> None:
    built = next(
        (e for e in trace_events if e["kind"] == "material_graph_built"),
        None,
    )
    assert built is not None, "material_graph_built event missing"
    assert built["node_count"] >= 3, (
        f"material graph must have ≥ 3 nodes, got {built['node_count']}"
    )
    assert built["edge_count"] >= 2, (
        f"material graph must have ≥ 2 wires, got {built['edge_count']}"
    )


def test_material_graph_validates(trace_events) -> None:
    """The material graph must survive :meth:`NodeGraph.validate`."""
    validated = next(
        (e for e in trace_events if e["kind"] == "material_graph_validated"),
        None,
    )
    assert validated is not None, "material_graph_validated event missing"
    assert validated["error_count"] == 0, (
        f"material graph validation failed: {validated['errors']}"
    )


# ---------------------------------------------------------------------------
# 5. FX preset
# ---------------------------------------------------------------------------


def test_fx_dreamy_preset_loaded(trace_events) -> None:
    """The dreamy baked PP chain preset must round-trip through the baker."""
    fx = next(
        (e for e in trace_events if e["kind"] == "fx_preset_loaded"),
        None,
    )
    assert fx is not None, "fx_preset_loaded event missing"
    assert fx["preset"] == "dreamy"
    assert fx["pass_count"] > 0, "dreamy preset should carry at least one pass"


# ---------------------------------------------------------------------------
# 6. Code eval
# ---------------------------------------------------------------------------


def test_code_expression_evaluated(trace_events) -> None:
    """``slappyengine.math.evaluate`` must return a real number."""
    evt = next(
        (e for e in trace_events if e["kind"] == "code_evaluated"),
        None,
    )
    assert evt is not None, "code_evaluated event missing"
    assert evt["ok"] is True, f"code eval failed: {evt.get('error')}"
    # sin(0.5)*2.0 + 3.0 ≈ 3.9588
    assert 3.9 < float(evt["value"]) < 4.0, (
        f"expected sin(0.5)*2 + 3 ≈ 3.96, got {evt['value']}"
    )


# ---------------------------------------------------------------------------
# 7. Autosave
# ---------------------------------------------------------------------------


def test_three_autosave_snapshots_written(trace_events) -> None:
    """AutosaveManager must produce ≥ 3 snapshots via ``force_save``."""
    snaps = [e for e in trace_events if e["kind"] == "autosave_snapshot"]
    assert len(snaps) >= 3, (
        f"expected ≥ 3 autosave snapshots, got {len(snaps)}"
    )
    for evt in snaps:
        assert evt["path"], "each snapshot must have a path"


def test_autosave_summary_reports_latest(trace_events) -> None:
    summary = next(
        (e for e in trace_events if e["kind"] == "autosave_summary"),
        None,
    )
    assert summary is not None, "autosave_summary event missing"
    assert summary["latest"], "latest snapshot path should be non-empty"


# ---------------------------------------------------------------------------
# 8. Theme application
# ---------------------------------------------------------------------------


def test_all_six_themes_applied(trace_events) -> None:
    """Each of the 6 built-in diary themes must land a ``theme_applied`` event."""
    applied = [e for e in trace_events if e["kind"] == "theme_applied"]
    assert len(applied) == len(demo.DEMO_THEMES), (
        f"expected {len(demo.DEMO_THEMES)} theme_applied events, "
        f"got {len(applied)}"
    )
    applied_ids = [e["theme_id"] for e in applied]
    for theme_id in demo.DEMO_THEMES:
        assert theme_id in applied_ids, (
            f"theme {theme_id!r} was never applied"
        )


def test_theme_active_name_matches_request(trace_events) -> None:
    for evt in (e for e in trace_events if e["kind"] == "theme_applied"):
        assert evt["theme_id"] == evt["active_name"], (
            f"theme mismatch: requested {evt['theme_id']!r} but "
            f"active is {evt['active_name']!r}"
        )


# ---------------------------------------------------------------------------
# 9. Structural / regression checks
# ---------------------------------------------------------------------------


def test_demo_exposes_run_demo() -> None:
    assert callable(getattr(demo, "run_demo", None))


def test_demo_theme_walk_is_the_six_defaults() -> None:
    assert set(demo.DEMO_THEMES) == {
        "teengirl_notebook", "cozy_diary", "bullet_journal",
        "scrapbook_summer", "cottagecore_garden", "kawaii_planner",
    }


def test_never_opens_viewport_on_import() -> None:
    """Importing the demo must not open a viewport (segfault-prone).

    The mere fact that this test module reached this point proves the
    top-level ``import hello_full_editor`` above didn't crash. We also
    read the source file to confirm every ``dpg.show_viewport()`` call
    sits behind the ``__main__`` / helper guard.
    """
    assert demo.__name__ == "hello_full_editor"
    src = Path(demo.__file__).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in src, (
        "demo must have a __main__ guard"
    )
    call_pattern = ".show_viewport("
    assert call_pattern in src, (
        "sanity: demo should contain a show_viewport call"
    )
    guard_idx = src.index('if __name__ == "__main__":')
    helper_idx = src.index("def _run_with_viewport")
    boundary = min(guard_idx, helper_idx)
    idx = 0
    while True:
        found = src.find(call_pattern, idx)
        if found == -1:
            break
        assert found > boundary, (
            f".show_viewport( at index {found} appears before the "
            f"__main__/helper boundary at index {boundary}"
        )
        idx = found + len(call_pattern)
