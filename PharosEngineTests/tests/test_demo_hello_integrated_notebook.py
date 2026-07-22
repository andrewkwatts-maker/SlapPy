"""Tests for :mod:`PharosEngineExamples.examples.hello_integrated_notebook`.

The demo exercises DiaryShell + notebook editor panels end-to-end.
These tests verify the scripted trace lands on disk, every page switch
and theme swap actually mutated state, and the inspector rows populate
from the outliner selection.

The whole test module runs headless — the demo is careful to keep
``dpg.show_viewport()`` inside its ``__main__`` guard so we can import
without a live viewport. A single session-scoped fixture makes sure
each theme-registry hop uses the same shared context if DPG is present.
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
_EXAMPLES = _REPO_ROOT / "PharosEngineExamples" / "examples"
if str(_EXAMPLES) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES))

import hello_integrated_notebook as demo  # type: ignore[import-not-found]  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def run_trace(tmp_path: Path):
    """Run the demo once and hand each test a fresh trace + YAML path."""
    trace_path = tmp_path / "hello_integrated_notebook_trace.yaml"
    # ``use_dpg_context=True`` mirrors the __main__ path; the demo
    # handles missing DPG gracefully so this works on CI boxes too.
    trace = demo.run_demo(trace_path=trace_path, use_dpg_context=True)
    return trace, trace_path


@pytest.fixture()
def trace_events(run_trace):
    """Shortcut to the recorded event list."""
    trace, _ = run_trace
    return trace.events


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load the YAML trace, preferring pyyaml; fall back to a lenient parser."""
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except Exception:
        # Very minimal fallback — tests only need to count "- kind:" markers.
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
    trace, _ = run_trace
    assert isinstance(trace, demo.DemoTrace)
    assert trace.events, "trace should record at least one event"


def test_trace_yaml_file_written(run_trace) -> None:
    _, trace_path = run_trace
    assert trace_path.exists(), "trace YAML should be written to disk"
    assert trace_path.stat().st_size > 0


def test_trace_yaml_has_at_least_15_events(run_trace) -> None:
    trace, trace_path = run_trace
    doc = _load_yaml(trace_path)
    events = doc.get("events") or []
    assert len(events) >= 15, (
        f"trace YAML must record ≥ 15 events, got {len(events)}"
    )
    # In-memory trace matches on-disk YAML (excluding any final events
    # recorded after the write, which we allow to drift by 1-2).
    assert abs(len(events) - len(trace.events)) <= 2


def test_trace_starts_and_ends_cleanly(trace_events) -> None:
    kinds = [e["kind"] for e in trace_events]
    assert kinds[0] == "demo_start", f"first event should be demo_start, got {kinds[0]}"
    assert "demo_end" in kinds, "demo_end should be recorded"


# ---------------------------------------------------------------------------
# 2. Theme registration + application
# ---------------------------------------------------------------------------


def test_all_six_themes_registered(trace_events) -> None:
    reg = next((e for e in trace_events if e["kind"] == "themes_registered"), None)
    assert reg is not None, "themes_registered event missing"
    names = reg["names"]
    assert set(names) >= set(demo.DEMO_THEMES), (
        f"registered themes missing entries: {set(demo.DEMO_THEMES) - set(names)}"
    )


def test_each_theme_applied_without_error(trace_events) -> None:
    applied = [e for e in trace_events if e["kind"] == "theme_applied"]
    assert len(applied) == len(demo.DEMO_THEMES), (
        f"expected {len(demo.DEMO_THEMES)} theme_applied events, got {len(applied)}"
    )
    applied_names = [e["theme_id"] for e in applied]
    for name in demo.DEMO_THEMES:
        assert name in applied_names, f"theme {name!r} never applied"


def test_every_theme_switch_mutates_colour_vector(trace_events) -> None:
    """Applying a new theme must change the semantic colour vector."""
    applied = [e for e in trace_events if e["kind"] == "theme_applied"]
    # Skip index 0 — the "previous_vec" starts empty so the first
    # application is trivially different; we care that entries 1..N
    # each report ``mutated=True`` after the previous vector is set.
    for evt in applied[1:]:
        assert evt["mutated"] is True, (
            f"theme {evt['theme_id']!r} should mutate the semantic vector"
        )


def test_theme_applied_active_name_matches_request(trace_events) -> None:
    for evt in (e for e in trace_events if e["kind"] == "theme_applied"):
        assert evt["theme_id"] == evt["active_name"], (
            f"theme_applied reports theme_id={evt['theme_id']!r} but "
            f"active_name={evt['active_name']!r}"
        )


# ---------------------------------------------------------------------------
# 3. DiaryShell page switching
# ---------------------------------------------------------------------------


def test_diary_shell_built_with_six_pages(trace_events) -> None:
    built = next((e for e in trace_events if e["kind"] == "diary_built"), None)
    assert built is not None
    assert built["page_count"] == 6, (
        f"DiaryShell should carry 6 default pages, got {built['page_count']}"
    )
    assert built["page_ids"] == list(demo.PAGE_WALK)


def test_each_page_switch_recorded(trace_events) -> None:
    switches = [e for e in trace_events if e["kind"] == "page_switch"]
    assert len(switches) == len(demo.PAGE_WALK), (
        f"expected {len(demo.PAGE_WALK)} page_switch events, got {len(switches)}"
    )
    for evt, expected_id in zip(switches, demo.PAGE_WALK):
        assert evt["to_page"] == expected_id, (
            f"page_switch expected to_page={expected_id!r}, got {evt['to_page']!r}"
        )


def test_page_switches_are_monotonically_counted(trace_events) -> None:
    """DiaryShell.switch_count must strictly increase across every switch."""
    counts = [
        e["switch_count"] for e in trace_events if e["kind"] == "page_switch"
    ]
    assert counts, "no page_switch events recorded"
    for prev, curr in zip(counts, counts[1:]):
        assert curr > prev, (
            f"switch_count non-monotonic: {prev} -> {curr}"
        )


def test_fx_page_uses_focus_preset(trace_events) -> None:
    fx = next(
        (e for e in trace_events
         if e["kind"] == "page_switch" and e["to_page"] == "fx"),
        None,
    )
    assert fx is not None, "no page_switch to fx recorded"
    assert fx["preset"] == "focus"


# ---------------------------------------------------------------------------
# 4. Outliner + inspector selection flow
# ---------------------------------------------------------------------------


def test_outliner_bound_to_three_entities(trace_events) -> None:
    bound = next(
        (e for e in trace_events if e["kind"] == "outliner_scene_bound"), None,
    )
    assert bound is not None
    assert bound["entity_count"] == 3
    assert bound["outliner_rows"] == 3


def test_each_entity_selection_populates_inspector(trace_events) -> None:
    selections = [e for e in trace_events if e["kind"] == "entity_selected"]
    assert len(selections) == 3, (
        f"expected 3 entity_selected events, got {len(selections)}"
    )
    for evt in selections:
        assert evt["inspector_field_count"] > 0, (
            f"inspector should populate rows for {evt['entity_name']!r}, "
            f"got {evt['inspector_field_count']}"
        )
        # Fields must include the transform + property fields we
        # deliberately put on MockEntity.
        assert "position" in evt["inspector_field_names"]
        assert "label" in evt["inspector_field_names"]


def test_selection_order_matches_scene_order(trace_events) -> None:
    """Entities should be selected in the same order they appear in the scene."""
    selections = [
        e for e in trace_events if e["kind"] == "entity_selected"
    ]
    # build_mock_scene ordering.
    expected = ["ent_a", "ent_b", "ent_c"]
    assert [e["entity_id"] for e in selections] == expected


# ---------------------------------------------------------------------------
# 5. Structural / regression checks on the module surface
# ---------------------------------------------------------------------------


def test_demo_exposes_run_demo() -> None:
    assert callable(getattr(demo, "run_demo", None))


def test_demo_exposes_build_mock_scene() -> None:
    scene = demo.build_mock_scene()
    assert len(scene.entities) == 3
    kinds = {e.kind for e in scene.entities}
    assert {"mesh", "body", "light"} <= kinds


def test_demo_theme_walk_is_the_six_defaults() -> None:
    assert set(demo.DEMO_THEMES) == {
        "teengirl_notebook", "cozy_diary", "bullet_journal",
        "scrapbook_summer", "cottagecore_garden", "kawaii_planner",
    }


def test_demo_page_walk_matches_default_pages_order() -> None:
    from pharos_editor.ui.editor.diary_shell import DEFAULT_PAGES

    assert list(demo.PAGE_WALK) == [p.id for p in DEFAULT_PAGES]


def test_run_demo_headless_without_dpg_context_flag(tmp_path: Path) -> None:
    """``use_dpg_context=False`` still works — proves the ``__main__`` guard.

    This exercises the code path that pytest cares about: no viewport,
    no create_context — but the trace still records the scripted flow.
    """
    trace_path = tmp_path / "no_ctx_trace.yaml"
    trace = demo.run_demo(trace_path=trace_path, use_dpg_context=False)
    assert trace_path.exists()
    kinds = [e["kind"] for e in trace.events]
    # dpg_context is still recorded (as ``skipped``) so the count matches.
    assert "dpg_context" in kinds
    ctx = next(e for e in trace.events if e["kind"] == "dpg_context")
    assert ctx["state"] == "skipped"


def test_never_opens_viewport_on_import() -> None:
    """The mere act of ``import hello_integrated_notebook`` must not open a viewport.

    If the demo forgot the ``if __name__ == "__main__":`` guard, importing
    would call ``dpg.show_viewport()`` which segfaults the test process.
    We reach this test only because that import already succeeded at the
    top of the module, so passing means the guard is in place.
    """
    assert demo.__name__ == "hello_integrated_notebook"
    # Read the source to be doubly sure ``dpg.show_viewport()`` — the
    # actual call, not just a mention of the name — sits behind the
    # ``__main__`` guard.
    src = Path(demo.__file__).read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in src
    # We match the *call* string (``.show_viewport(``) rather than the
    # bare identifier so docstrings mentioning ``show_viewport`` don't
    # trip the guard check.
    call_pattern = ".show_viewport("
    assert call_pattern in src, "sanity: demo should contain a show_viewport call"
    guard_idx = src.index('if __name__ == "__main__":')
    helper_idx = src.index("def _run_with_viewport")
    boundary = min(guard_idx, helper_idx)
    for occurrence in _iter_indices(src, call_pattern):
        assert occurrence > boundary, (
            f"dpg.show_viewport() call at index {occurrence} appears "
            f"before the __main__/helper boundary at index {boundary}"
        )


def _iter_indices(haystack: str, needle: str) -> list[int]:
    """Return every start index of *needle* in *haystack*."""
    out: list[int] = []
    start = 0
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            return out
        out.append(idx)
        start = idx + len(needle)
