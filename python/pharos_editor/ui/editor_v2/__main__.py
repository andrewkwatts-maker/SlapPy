"""Entry point for ``pharos-edit-v2`` and ``python -m pharos_editor.ui.editor_v2``."""
from __future__ import annotations

import sys


def main() -> int:
    try:
        from pharos_editor.ui.editor_v2.shell import run
    except ImportError as exc:
        print(f"pharos-edit-v2: failed to import shell: {exc}", file=sys.stderr)
        print(
            "The v2 editor requires imgui-bundle. Install with:\n"
            "  pip install imgui-bundle",
            file=sys.stderr,
        )
        return 2
    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
