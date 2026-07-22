"""Entry point for the ``pharos-edit`` console script."""
from __future__ import annotations

import sys


def main() -> int:
    """Boot the notebook editor.

    Thin wrapper that defers to the editor shell in ``pharos_editor.ui.editor``.
    Sprint 2 stub — full wiring is completed alongside the Sprint 8+9 UI
    polish work.
    """
    try:
        from pharos_editor.ui.editor.__main__ import main as _shell_main
    except ImportError as exc:
        print(f"pharos-edit: failed to import editor shell: {exc}", file=sys.stderr)
        return 2
    return _shell_main() or 0


if __name__ == "__main__":
    raise SystemExit(main())
