"""SlapPyEngine - Hello Autosave

Minimal demo of :class:`pharos_engine.autosave.AutosaveManager` (sprint Y6).

Simulates ~6 seconds of editor activity — a dirty-flag toggles on and
off as the user types, and a small dict of "unsaved" scene state
mutates every tick. Snapshots are written every second into a
temporary directory. Halfway through, the demo simulates a crash by
dropping the in-memory state, then invokes
:class:`pharos_engine.autosave.RecoveryPrompt` to find the newest
snapshot and restore it.

The demo is deliberately headless: no dear-pygui viewport, no live
window. It exercises the full autosave pipeline (timer, on-disk YAML
snapshots, atomic rename, ring-buffer prune, recovery prompt) so tests
can lock the behaviour end-to-end.

Run::

    PYTHONPATH=python python examples/hello_autosave.py
    PYTHONPATH=python python examples/hello_autosave.py --duration 3
    PYTHONPATH=python python examples/hello_autosave.py --dir /tmp/autosave_demo
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from pharos_engine.autosave import (
    AutosaveManager,
    AutosaveState,
    RecoveryOffer,
    RecoveryPrompt,
    default_snapshot_dir,
)


# ── Demo parameters ─────────────────────────────────────────────────────────
DEFAULT_DURATION: float = 6.0        # seconds of "edit activity" to simulate
DEFAULT_INTERVAL: float = 1.0        # autosave tick interval
DEFAULT_MAX_SNAPSHOTS: int = 5
EDIT_TICK: float = 0.25              # simulated edits every 250 ms
PROJECT_NAME: str = "hello_autosave_demo"


# ────────────────────────────────────────────────────────────────────────────
# Simulated editor state
# ────────────────────────────────────────────────────────────────────────────


class EditorState:
    """A stand-in for the real editor's dirty-tracked scene state.

    Keeps a small mutable dict that the autosave callback picks up on
    every tick. The demo drives it via :meth:`type_char` (append char +
    mark dirty), :meth:`commit_scene` (clear dirty), and
    :meth:`snapshot_payload` (serialisation hook the manager calls).
    """

    def __init__(self) -> None:
        self.notebook_text: str = ""
        self.scene_nodes: list[dict[str, Any]] = []
        self.dirty: bool = False
        self.edits_since_boot: int = 0

    def type_char(self, ch: str) -> None:
        """Simulate the user hitting a key in the notebook editor."""
        self.notebook_text += ch
        self.edits_since_boot += 1
        self.dirty = True

    def add_node(self, name: str, pos: tuple[float, float]) -> None:
        """Simulate the user dropping a prefab into the scene."""
        self.scene_nodes.append({"name": name, "pos": list(pos)})
        self.dirty = True

    def commit_scene(self) -> None:
        """Simulate File > Save — clears the dirty flag."""
        self.dirty = False

    def snapshot_payload(self) -> dict[str, Any]:
        """Return the payload the autosave manager will YAML-dump."""
        return {
            "notebook_text": self.notebook_text,
            "scene_nodes": [dict(n) for n in self.scene_nodes],
            "dirty": self.dirty,
            "edits_since_boot": self.edits_since_boot,
        }

    def restore_from(self, payload: dict[str, Any]) -> None:
        """Load a decoded snapshot payload back into the live state."""
        if not isinstance(payload, dict):
            raise TypeError(
                f"EditorState.restore_from: payload must be a dict; "
                f"got {type(payload).__name__}"
            )
        self.notebook_text = str(payload.get("notebook_text", ""))
        raw_nodes = payload.get("scene_nodes") or []
        self.scene_nodes = [
            {"name": str(n.get("name", "")), "pos": list(n.get("pos", [0.0, 0.0]))}
            for n in raw_nodes
            if isinstance(n, dict)
        ]
        self.dirty = bool(payload.get("dirty", False))
        self.edits_since_boot = int(payload.get("edits_since_boot", 0))


# ────────────────────────────────────────────────────────────────────────────
# Autosave wiring
# ────────────────────────────────────────────────────────────────────────────


def build_manager(
    snapshot_dir: Path,
    editor: EditorState,
    *,
    interval_seconds: float = DEFAULT_INTERVAL,
    max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
) -> AutosaveManager:
    """Wire an :class:`AutosaveManager` around *editor*.

    The manager writes ``.snap.yaml`` files under *snapshot_dir* every
    *interval_seconds* seconds, capping the ring buffer at
    *max_snapshots*.
    """
    state = AutosaveState(
        enabled=True,
        interval_seconds=float(interval_seconds),
        snapshot_dir=Path(snapshot_dir),
        max_snapshots=int(max_snapshots),
    )
    project = SimpleNamespace(name=PROJECT_NAME)
    return AutosaveManager(state, project, editor.snapshot_payload)


# ────────────────────────────────────────────────────────────────────────────
# Simulation script
# ────────────────────────────────────────────────────────────────────────────


def simulate_activity(
    editor: EditorState,
    duration: float,
    *,
    tick: float = EDIT_TICK,
) -> None:
    """Simulate ~*duration* seconds of user typing + scene edits.

    Every *tick* seconds a character is appended to the notebook and,
    every four ticks, a fresh scene node is dropped in. The dirty flag
    flips on with each edit; every whole-second boundary the "user"
    commits (clears dirty) to make the trace interesting.
    """
    typing_chars = "The quick brown fox jumps over the lazy dog. "
    deadline = time.time() + float(duration)
    idx = 0
    last_commit = time.time()
    while time.time() < deadline:
        ch = typing_chars[idx % len(typing_chars)]
        editor.type_char(ch)
        if idx % 4 == 0:
            editor.add_node(
                f"crate_{idx}",
                (float(idx % 10), float(idx // 10)),
            )
        # Every ~2 seconds the user "saves" — flips dirty off. Autosave
        # keeps snapshotting regardless so a crash still yields a
        # meaningful ring buffer.
        if time.time() - last_commit > 2.0:
            editor.commit_scene()
            last_commit = time.time()
        idx += 1
        time.sleep(tick)


# ────────────────────────────────────────────────────────────────────────────
# Crash + recovery
# ────────────────────────────────────────────────────────────────────────────


def simulate_crash(editor: EditorState) -> dict[str, Any]:
    """Simulate a hard crash by wiping the in-memory editor state.

    Returns the state that was lost so the caller can assert against
    the recovered payload later.
    """
    lost = editor.snapshot_payload()
    editor.notebook_text = ""
    editor.scene_nodes = []
    editor.dirty = False
    editor.edits_since_boot = 0
    return lost


def recover(
    snapshot_dir: Path,
    editor: EditorState,
    *,
    manager: AutosaveManager | None = None,
) -> RecoveryOffer | None:
    """Look for a newer-than-project snapshot and restore it if found.

    Uses :class:`RecoveryPrompt` with ``project_last_saved=None`` so any
    snapshot at all triggers an offer. Returns the ``RecoveryOffer``
    that was accepted (or ``None`` when the ring buffer is empty).
    """
    prompt = RecoveryPrompt(snapshot_dir, project_last_saved=None)
    offer = prompt.check()
    if offer is None:
        return None
    # If a manager is available use its full restore path; otherwise
    # roll our own via a small YAML reader so the demo can be driven
    # without ever spinning a timer thread.
    if manager is not None:
        manager.restore_snapshot(offer.snapshot_path, editor.restore_from)
    else:
        _load_snapshot(offer.snapshot_path, editor)
    return offer


def _load_snapshot(path: Path, editor: EditorState) -> None:
    """Direct snapshot-read fallback (uses the public read_snapshot API)."""
    document = AutosaveManager.read_snapshot(path)
    editor.restore_from(document["payload"])


# ────────────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────────────


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Autosave - SlapPyEngine demo")
    parser.add_argument(
        "--duration", type=float, default=DEFAULT_DURATION,
        help=f"seconds of simulated activity (default: {DEFAULT_DURATION})",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL,
        help=f"autosave interval in seconds (default: {DEFAULT_INTERVAL})",
    )
    parser.add_argument(
        "--max-snapshots", type=int, default=DEFAULT_MAX_SNAPSHOTS,
        help=f"ring buffer cap (default: {DEFAULT_MAX_SNAPSHOTS})",
    )
    parser.add_argument(
        "--dir", type=Path, default=None,
        help="snapshot directory (defaults to a fresh tempdir)",
    )
    parser.add_argument(
        "--keep-dir", action="store_true",
        help="don't delete the snapshot directory on exit",
    )
    return parser.parse_args(argv)


def main(
    duration: float = DEFAULT_DURATION,
    interval: float = DEFAULT_INTERVAL,
    max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
    snapshot_dir: Path | None = None,
    *,
    keep_dir: bool = False,
    edit_tick: float = EDIT_TICK,
) -> dict[str, Any]:
    """Run the demo end-to-end and return a summary dict for tests."""
    owned_tmp = False
    if snapshot_dir is None:
        snapshot_dir = Path(tempfile.mkdtemp(prefix="hello_autosave_"))
        owned_tmp = True
    snapshot_dir = Path(snapshot_dir)

    editor = EditorState()
    manager = build_manager(
        snapshot_dir,
        editor,
        interval_seconds=interval,
        max_snapshots=max_snapshots,
    )
    print(f"hello_autosave: snapshot dir = {snapshot_dir}")
    print(f"hello_autosave: interval={interval}s max_snapshots={max_snapshots}")

    try:
        manager.start()
        simulate_activity(editor, duration=duration, tick=edit_tick)
        manager.stop()

        snapshots = manager.list_snapshots()
        print(f"hello_autosave: {len(snapshots)} snapshot(s) written")
        for p in snapshots:
            print(f"    - {p.name}")

        pre_crash = editor.snapshot_payload()
        lost = simulate_crash(editor)
        print("hello_autosave: simulated crash (editor state cleared)")
        assert editor.notebook_text == ""
        assert editor.edits_since_boot == 0

        offer = recover(snapshot_dir, editor, manager=manager)
        recovered = offer is not None
        if offer is not None:
            print(
                f"hello_autosave: RecoveryPrompt returned "
                f"{offer.snapshot_path.name} (saved at "
                f"{offer.snapshot_saved:.1f})"
            )
            print(
                f"hello_autosave: restored notebook_text "
                f"({len(editor.notebook_text)} chars) + "
                f"{len(editor.scene_nodes)} scene node(s)"
            )
        else:
            print("hello_autosave: no snapshots to recover")

        latest = snapshots[0].name if snapshots else None
        return {
            "snapshot_dir": str(snapshot_dir),
            "snapshot_count": len(snapshots),
            "latest_snapshot": latest,
            "recovered": recovered,
            "offer_path": str(offer.snapshot_path) if offer is not None else None,
            "pre_crash_edits": int(pre_crash["edits_since_boot"]),
            "post_recovery_edits": int(editor.edits_since_boot),
            "post_recovery_notebook_len": len(editor.notebook_text),
            "lost_edits": int(lost["edits_since_boot"]),
        }
    finally:
        # If the manager somehow survived the try block, still tear it down.
        try:
            manager.stop()
        except Exception:
            pass
        if owned_tmp and not keep_dir:
            shutil.rmtree(snapshot_dir, ignore_errors=True)


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        summary = main(
            duration=args.duration,
            interval=args.interval,
            max_snapshots=args.max_snapshots,
            snapshot_dir=args.dir,
            keep_dir=args.keep_dir,
        )
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_autosave: error: {exc}", file=sys.stderr)
        return 1
    print()
    print("hello_autosave summary")
    print(f"  snapshot_count       : {summary['snapshot_count']}")
    print(f"  latest_snapshot      : {summary['latest_snapshot']}")
    print(f"  recovered            : {summary['recovered']}")
    print(f"  edits before crash   : {summary['pre_crash_edits']}")
    print(f"  edits after recovery : {summary['post_recovery_edits']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
