"""Tests for :mod:`SlapPyEngineExamples.examples.hello_v2_showcase` (EE2).

The V2 showcase drives 15+ subsystems in one scripted run — project
registry, user theme store, prefab library + preview baker, autosave,
chain manifest + baked chain, material graph bridge + shader lint,
hotkey remap, camera tweens, toast manager, command palette, layout
baker, timeline editor, feature map, and the user-overrides watcher.

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

import hello_v2_showcase as demo  # type: ignore[import-not-found]  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def run_trace(tmp_path_factory):
    """Run the demo once for the module and share the trace across tests."""
    trace_dir = tmp_path_factory.mktemp("hello_v2_showcase")
    trace_path = trace_dir / "hello_v2_showcase_trace.yaml"
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
# 1. Entrypoint + trace file basics
# ---------------------------------------------------------------------------


def test_demo_run_returns_trace(run_trace) -> None:
    """``run_demo`` returns a populated :class:`DemoTrace` without raising."""
    trace, _ = run_trace
    assert isinstance(trace, demo.DemoTrace)
    assert trace.events, "trace should record at least one event"


def test_trace_has_at_least_50_events(run_trace) -> None:
    """The scripted flow must record ≥ 50 events per the EE2 contract."""
    trace, trace_path = run_trace
    assert len(trace.events) >= 50, (
        f"in-memory trace must record ≥ 50 events, got {len(trace.events)}"
    )
    doc = _load_yaml(trace_path)
    on_disk = doc.get("events") or []
    assert len(on_disk) >= 50, (
        f"YAML trace must contain ≥ 50 events, got {len(on_disk)}"
    )


def test_trace_yaml_written(run_trace) -> None:
    _, trace_path = run_trace
    assert trace_path.exists(), "trace YAML must be persisted"
    assert trace_path.stat().st_size > 0


def test_trace_starts_and_ends_cleanly(trace_events) -> None:
    kinds = [e["kind"] for e in trace_events]
    assert kinds[0] == "demo_start"
    assert "demo_end" in kinds


# ---------------------------------------------------------------------------
# 2. Subsystem coverage
# ---------------------------------------------------------------------------


def test_seventeen_subsystems_declared() -> None:
    """The subsystem map must list at least 15 subsystems (EE2 contract)."""
    assert len(demo.SUBSYSTEM_MAP) >= 15, (
        f"expected ≥ 15 subsystems, got {len(demo.SUBSYSTEM_MAP)}"
    )


def test_every_subsystem_recorded(trace_events) -> None:
    """Every SUBSYSTEM_MAP entry must have its verify-event in the trace."""
    kinds = {e["kind"] for e in trace_events}
    missing = [
        subsystem for subsystem, event_kind in demo.SUBSYSTEM_MAP.items()
        if event_kind not in kinds
    ]
    assert not missing, f"subsystems missing verify events: {missing}"


def test_demo_end_reports_all_verified(trace_events) -> None:
    """The ``demo_end`` event must confirm every subsystem was verified."""
    end = next((e for e in trace_events if e["kind"] == "demo_end"), None)
    assert end is not None, "demo_end event missing"
    verified = end.get("verified", {})
    assert isinstance(verified, dict) and verified, (
        "demo_end.verified must be a non-empty dict"
    )
    total = end.get("summary", {}).get("subsystems_total")
    verified_count = end.get("summary", {}).get("subsystems_verified")
    assert total == len(demo.SUBSYSTEM_MAP)
    assert verified_count == len(demo.SUBSYSTEM_MAP), (
        f"expected all {total} subsystems verified, got {verified_count}"
    )


# ---------------------------------------------------------------------------
# 3. Project registry (V2)
# ---------------------------------------------------------------------------


def test_project_registry_added_three(trace_events) -> None:
    added = [e for e in trace_events if e["kind"] == "project_added"]
    assert len(added) == 3, (
        f"expected 3 project_added events, got {len(added)}"
    )
    summary = next(
        (e for e in trace_events if e["kind"] == "project_registry"), None,
    )
    assert summary is not None, "project_registry summary event missing"
    assert summary["added_count"] == 3
    assert summary["recent_count"] >= 3


# ---------------------------------------------------------------------------
# 4. User theme store (U2)
# ---------------------------------------------------------------------------


def test_user_theme_store_loaded(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "user_theme_store"), None,
    )
    assert evt is not None, "user_theme_store event missing"
    assert evt["baked_count"] > 0, "expected at least one baked theme"


# ---------------------------------------------------------------------------
# 5. Prefab library + preview baker
# ---------------------------------------------------------------------------


def test_four_prefabs_spawned(trace_events) -> None:
    spawns = [e for e in trace_events if e["kind"] == "prefab_spawned"]
    names = [e["name"] for e in spawns]
    assert len(spawns) == 4, (
        f"expected 4 prefab_spawned events, got {len(spawns)} ({names})"
    )
    for expected in ("crate", "ball", "chain", "ragdoll"):
        assert expected in names, f"prefab {expected!r} was never spawned"


def test_prefab_previews_baked(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "preview_baked"), None,
    )
    assert evt is not None, "preview_baked event missing"
    assert evt["count"] >= 4, (
        f"expected ≥ 4 baked previews, got {evt['count']}"
    )


# ---------------------------------------------------------------------------
# 6. Autosave (Y6 / AA2 read_snapshot)
# ---------------------------------------------------------------------------


def test_three_autosave_snapshots_written(trace_events) -> None:
    snaps = [e for e in trace_events if e["kind"] == "autosave_snapshot"]
    assert len(snaps) >= 3, (
        f"expected ≥ 3 autosave snapshots, got {len(snaps)}"
    )


def test_autosave_read_snapshot_round_trip(trace_events) -> None:
    """The ``read_snapshot`` classmethod must decode the latest snapshot."""
    read = next(
        (e for e in trace_events if e["kind"] == "autosave_read"), None,
    )
    assert read is not None, "autosave_read event missing"
    assert read["latest"], "latest snapshot path should be non-empty"
    assert read["meta_keys"], "read_snapshot should populate meta"
    assert read["payload_keys"], (
        "read_snapshot should decode payload with dict shape"
    )


# ---------------------------------------------------------------------------
# 7. Chain manifest (X5) + baked chain (Z3)
# ---------------------------------------------------------------------------


def test_chain_manifest_applied(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "chain_manifest"), None,
    )
    assert evt is not None
    assert evt["pass_count"] >= 3
    assert evt["applied_ok"] is True
    assert evt["applied_shape"] == [16, 16, 3]


def test_chain_baker_dreamy_loaded(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "chain_baker"), None,
    )
    assert evt is not None, "chain_baker event missing"
    assert evt["loaded"] == "dreamy"
    assert evt["pass_count"] > 0


# ---------------------------------------------------------------------------
# 8. Material graph bridge + shader lint
# ---------------------------------------------------------------------------


def test_material_bridge_emitted_wgsl(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "material_bridge"), None,
    )
    assert evt is not None, "material_bridge event missing"
    assert evt["used_bridge"] is True, (
        "MaterialGraphBridge should have compiled the graph"
    )
    assert evt["wgsl_bytes"] > 0, "bridge should emit non-empty WGSL"
    assert evt["node_count"] == 5
    assert evt["edge_count"] == 4


def test_shader_lint_result(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "shader_lint"), None,
    )
    assert evt is not None, "shader_lint event missing"
    assert evt["source_id"], "lint should carry a source id"
    assert evt["size_bytes"] > 0


# ---------------------------------------------------------------------------
# 9. Hotkey remap + camera tweens
# ---------------------------------------------------------------------------


def test_hotkey_remap_loaded_three_presets(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "hotkey_remap"), None,
    )
    assert evt is not None, "hotkey_remap event missing"
    assert len(evt["preset_names"]) >= 3, (
        f"expected ≥ 3 baked hotkey style presets, got "
        f"{evt['preset_names']}"
    )


def test_camera_two_tweens_scheduled(trace_events) -> None:
    scheduled = [
        e for e in trace_events if e["kind"] == "camera_tween_scheduled"
    ]
    assert len(scheduled) == 2, (
        f"expected 2 camera tweens scheduled, got {len(scheduled)}"
    )
    slots = {e["slot"] for e in scheduled}
    assert slots == {"position", "zoom"}
    done = next(
        (e for e in trace_events if e["kind"] == "camera_tween_done"), None,
    )
    assert done is not None
    assert done["scheduled"] == 2


# ---------------------------------------------------------------------------
# 10. Toast manager + command palette
# ---------------------------------------------------------------------------


def test_five_toasts_pushed(trace_events) -> None:
    shown = [e for e in trace_events if e["kind"] == "toast_shown"]
    assert len(shown) == 5, (
        f"expected 5 toasts shown, got {len(shown)}"
    )
    levels = {e["level"] for e in shown}
    assert {"INFO", "SUCCESS", "WARN", "ERROR"}.issubset(levels), (
        f"expected varied toast levels, got {levels}"
    )


def test_command_palette_fuzzy_matched_spawn(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "command_palette"), None,
    )
    assert evt is not None, "command_palette event missing"
    assert evt["query"] == "spawn"


# ---------------------------------------------------------------------------
# 11. Layout baker + timeline editor
# ---------------------------------------------------------------------------


def test_layout_baker_loaded_debugging(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "layout_baker"), None,
    )
    assert evt is not None, "layout_baker event missing"
    assert evt["loaded"] == "debugging", (
        f"expected 'debugging' layout loaded, got {evt['loaded']!r}"
    )


def test_timeline_two_tracks_with_keyframes(trace_events) -> None:
    tracks = [e for e in trace_events if e["kind"] == "timeline_track"]
    assert len(tracks) == 2, (
        f"expected 2 timeline tracks, got {len(tracks)}"
    )
    for evt in tracks:
        assert evt["keyframe_count"] >= 3
    summary = next(
        (e for e in trace_events if e["kind"] == "timeline_summary"), None,
    )
    assert summary is not None
    assert summary["track_count"] == 2
    assert summary["total_keyframes"] >= 6


# ---------------------------------------------------------------------------
# 12. Feature map + user overrides watcher
# ---------------------------------------------------------------------------


def test_feature_map_meets_wired_threshold(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "feature_map"), None,
    )
    assert evt is not None, "feature_map event missing"
    assert evt["wired_rows"] >= 250, (
        f"expected ≥ 250 WIRED rows in feature map, got {evt['wired_rows']}"
    )
    assert evt["met_threshold"] is True


def test_user_overrides_watcher_start_stop_clean(trace_events) -> None:
    evt = next(
        (e for e in trace_events if e["kind"] == "user_overrides_watcher"),
        None,
    )
    assert evt is not None, "user_overrides_watcher event missing"
    assert evt["stopped_clean"] is True, (
        "user-overrides watcher must stop without raising"
    )


# ---------------------------------------------------------------------------
# 13. Structural / regression checks
# ---------------------------------------------------------------------------


def test_demo_exposes_run_demo() -> None:
    assert callable(getattr(demo, "run_demo", None))


def test_demo_exposes_subsystem_map() -> None:
    assert isinstance(demo.SUBSYSTEM_MAP, dict)
    assert len(demo.SUBSYSTEM_MAP) >= 15


def test_never_opens_viewport_on_import() -> None:
    """Importing the demo must not open a viewport (segfault-prone)."""
    assert demo.__name__ == "hello_v2_showcase"
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
