"""Headless screenshot harness for the notebook editor.

Boots the editor, lets it render N frames, calls
``dpg.output_frame_buffer(path)``, closes cleanly. Used by the polish
loop to compare visual output pass-over-pass.

Usage::

    python scripts/editor_screenshot.py out.png --frames 45
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from pathlib import Path


def _boot_editor(width: int = 1920, height: int = 1080):
    import dearpygui.dearpygui as dpg
    from pharos_engine.engine import Engine
    from pharos_editor.ui.editor.shell import EditorShell

    engine = Engine()
    shell = EditorShell(engine, width=width, height=height)
    # Suppress first-run welcome overlay for clean screenshots.
    try:
        shell._maybe_show_first_run_welcome = lambda: None  # type: ignore[assignment]
    except Exception:
        pass
    shell.setup()
    try:
        dpg.maximize_viewport()
    except Exception:
        pass
    return shell, dpg


def _screenshot_thread(dpg_mod, out_path: Path, frames_to_wait: int) -> None:
    import time as _t
    # DPG has to be running before output_frame_buffer works.
    while not dpg_mod.is_dearpygui_running():
        _t.sleep(0.02)
    # Let a few frames render so themes + panels resolve.
    for _ in range(frames_to_wait):
        dpg_mod.split_frame()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        dpg_mod.output_frame_buffer(file=str(out_path))
        print(f"[screenshot] saved {out_path}")
    except Exception as exc:  # pragma: no cover
        print(f"[screenshot] output_frame_buffer failed: {exc}")
    # Give the OS a moment to flush the PNG before we stop the loop.
    _t.sleep(0.4)
    dpg_mod.stop_dearpygui()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("out", type=Path)
    parser.add_argument("--frames", type=int, default=45,
                        help="Frames to render before capturing")
    args = parser.parse_args(argv)

    shell, dpg = _boot_editor()

    # Schedule the capture on a helper thread — the main thread runs the
    # DPG render loop and blocks until stop_dearpygui() fires.
    threading.Thread(
        target=_screenshot_thread,
        args=(dpg, args.out.resolve(), args.frames),
        daemon=True,
    ).start()
    shell.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
