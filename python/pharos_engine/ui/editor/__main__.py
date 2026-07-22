"""``python -m pharos_engine.ui.editor [<project_dir>]`` entry point.

Boots the notebook editor shell on top of a headless :class:`~pharos_engine.engine.Engine`.
Referenced by :func:`pharos_engine.scaffold.launch_project` when the
``--editor`` flag is passed to ``slap launch``.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _load_project_if_any(project_dir: Path | None):
    """Best-effort project attach: returns a Project or None."""
    if project_dir is None:
        return None
    try:
        from pharos_engine.projects.project import Project
        return Project.load(project_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"[editor] project load failed ({exc}); starting empty", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    project_dir: Path | None = None
    if args and not args[0].startswith("-"):
        project_dir = Path(args[0]).resolve()

    try:
        import dearpygui.dearpygui  # noqa: F401
    except ImportError:
        print(
            "editor requires dearpygui — install with "
            "`pip install 'pharos-engine[editor]'`",
            file=sys.stderr,
        )
        return 2

    from pharos_engine.engine import Engine
    from pharos_engine.ui.editor.shell import EditorShell

    engine = Engine()
    shell = EditorShell(engine)

    project = _load_project_if_any(project_dir)
    if project is not None:
        try:
            shell.set_project(project)
        except Exception as exc:  # noqa: BLE001
            print(f"[editor] set_project failed ({exc})", file=sys.stderr)

    shell.setup()
    shell.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
