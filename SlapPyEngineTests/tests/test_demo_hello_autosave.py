"""Tests for the ``examples/hello_autosave.py`` demo (sprint Z4).

These tests pin the demo behaviour end-to-end:

1. ``main()`` runs without exception and returns a summary dict.
2. At least three snapshots are written under the target directory.
3. The latest snapshot round-trips through the YAML loader cleanly.
4. :class:`RecoveryPrompt` detects the newest snapshot after the crash.
5. The demo restores notebook_text + scene_nodes after simulated crash.
6. Snapshot filenames follow the ``YYYYMMDD_HHMMSS_<seq>.snap.yaml`` shape.
7. The ring buffer caps the on-disk count at ``max_snapshots``.
8. ``simulate_crash`` truly clears state — no leftovers from before.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from slappyengine.autosave import RecoveryPrompt


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "hello_autosave.py"

_SNAP_NAME_RE = re.compile(r"^\d{8}_\d{6}_\d{4}\.snap\.yaml$")


def _load_demo():
    spec = importlib.util.spec_from_file_location("hello_autosave_demo", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["hello_autosave_demo"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def demo():
    return _load_demo()


# ────────────────────────────────────────────────────────────────────────────
# Test 1: main() runs cleanly end-to-end
# ────────────────────────────────────────────────────────────────────────────

def test_hello_autosave_main_runs_without_error(demo, tmp_path):
    """``main(duration=2, interval=0.5)`` returns a summary and never raises."""
    summary = demo.main(
        duration=2.0,
        interval=0.5,
        max_snapshots=5,
        snapshot_dir=tmp_path / "snaps",
        keep_dir=True,
        edit_tick=0.1,
    )
    assert isinstance(summary, dict)
    assert summary["snapshot_count"] >= 3
    assert summary["recovered"] is True


# ────────────────────────────────────────────────────────────────────────────
# Test 2: at least 3 snapshots hit disk over 2 seconds at 0.5 s interval
# ────────────────────────────────────────────────────────────────────────────

def test_hello_autosave_writes_multiple_snapshots(demo, tmp_path):
    """Ticks at 0.5 s over 2 s yield >= 3 snapshot files."""
    snap_dir = tmp_path / "snaps"
    demo.main(
        duration=2.0,
        interval=0.5,
        max_snapshots=10,
        snapshot_dir=snap_dir,
        keep_dir=True,
        edit_tick=0.1,
    )
    files = sorted(snap_dir.glob("*.snap.yaml"))
    assert len(files) >= 3, f"expected >= 3 snapshots, got {len(files)}"


# ────────────────────────────────────────────────────────────────────────────
# Test 3: latest snapshot round-trips through the YAML reader
# ────────────────────────────────────────────────────────────────────────────

def test_hello_autosave_latest_snapshot_round_trips(demo, tmp_path):
    """The newest snapshot YAML-decodes to a dict with the expected shape."""
    from slappyengine.autosave import _decode_payload, _yaml_loads

    snap_dir = tmp_path / "snaps"
    demo.main(
        duration=2.0,
        interval=0.5,
        max_snapshots=5,
        snapshot_dir=snap_dir,
        keep_dir=True,
        edit_tick=0.1,
    )
    files = sorted(
        snap_dir.glob("*.snap.yaml"), key=lambda p: p.stat().st_mtime,
    )
    assert files, "no snapshots written"
    newest = files[-1]
    document = _yaml_loads(newest.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    assert "meta" in document
    assert "payload" in document
    payload = _decode_payload(document["payload"])
    assert isinstance(payload, dict)
    assert "notebook_text" in payload
    assert "scene_nodes" in payload
    assert "edits_since_boot" in payload


# ────────────────────────────────────────────────────────────────────────────
# Test 4: RecoveryPrompt returns the newest snapshot
# ────────────────────────────────────────────────────────────────────────────

def test_hello_autosave_recovery_prompt_detects_newest(demo, tmp_path):
    """After the run, ``RecoveryPrompt(dir).check()`` yields an offer."""
    snap_dir = tmp_path / "snaps"
    demo.main(
        duration=2.0,
        interval=0.5,
        max_snapshots=5,
        snapshot_dir=snap_dir,
        keep_dir=True,
        edit_tick=0.1,
    )
    prompt = RecoveryPrompt(snap_dir, project_last_saved=None)
    offer = prompt.check()
    assert offer is not None
    assert offer.snapshot_path.exists()
    assert offer.snapshot_path.suffix == ".yaml"


# ────────────────────────────────────────────────────────────────────────────
# Test 5: recovered editor state is non-empty (real payload restored)
# ────────────────────────────────────────────────────────────────────────────

def test_hello_autosave_restores_state_after_crash(demo, tmp_path):
    """After ``main``, the restored editor has non-empty notebook + edits."""
    summary = demo.main(
        duration=2.0,
        interval=0.5,
        max_snapshots=5,
        snapshot_dir=tmp_path / "snaps",
        keep_dir=True,
        edit_tick=0.1,
    )
    assert summary["recovered"] is True
    assert summary["post_recovery_notebook_len"] > 0
    assert summary["post_recovery_edits"] > 0
    # Restored count should never exceed the pre-crash count.
    assert summary["post_recovery_edits"] <= summary["pre_crash_edits"]


# ────────────────────────────────────────────────────────────────────────────
# Test 6: snapshot filenames follow the timestamp+seq convention
# ────────────────────────────────────────────────────────────────────────────

def test_hello_autosave_snapshot_names_follow_convention(demo, tmp_path):
    """Every ``.snap.yaml`` matches ``YYYYMMDD_HHMMSS_NNNN.snap.yaml``."""
    snap_dir = tmp_path / "snaps"
    demo.main(
        duration=1.5,
        interval=0.5,
        max_snapshots=5,
        snapshot_dir=snap_dir,
        keep_dir=True,
        edit_tick=0.1,
    )
    for path in snap_dir.glob("*.snap.yaml"):
        assert _SNAP_NAME_RE.match(path.name), (
            f"snapshot name {path.name!r} does not match the timestamp pattern"
        )


# ────────────────────────────────────────────────────────────────────────────
# Test 7: ring buffer caps the on-disk count at ``max_snapshots``
# ────────────────────────────────────────────────────────────────────────────

def test_hello_autosave_ring_buffer_caps_at_max(demo, tmp_path):
    """A run that would emit >5 snapshots keeps at most 5 on disk."""
    snap_dir = tmp_path / "snaps"
    demo.main(
        duration=4.0,
        interval=0.3,  # ~13 ticks over 4 s
        max_snapshots=5,
        snapshot_dir=snap_dir,
        keep_dir=True,
        edit_tick=0.05,
    )
    files = list(snap_dir.glob("*.snap.yaml"))
    assert len(files) <= 5, (
        f"ring buffer overflowed: {len(files)} files vs max_snapshots=5"
    )
    assert len(files) >= 3  # sanity — some snapshots did fire


# ────────────────────────────────────────────────────────────────────────────
# Test 8: simulate_crash wipes all editor state
# ────────────────────────────────────────────────────────────────────────────

def test_hello_autosave_simulate_crash_clears_state(demo):
    """After ``simulate_crash`` the editor is byte-identical to a fresh boot."""
    editor = demo.EditorState()
    editor.type_char("a")
    editor.type_char("b")
    editor.add_node("crate_0", (1.0, 2.0))
    assert editor.edits_since_boot == 2
    assert editor.notebook_text == "ab"
    assert len(editor.scene_nodes) == 1
    lost = demo.simulate_crash(editor)
    assert lost["edits_since_boot"] == 2
    assert lost["notebook_text"] == "ab"
    assert editor.notebook_text == ""
    assert editor.scene_nodes == []
    assert editor.edits_since_boot == 0
    assert editor.dirty is False
