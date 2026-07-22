"""CI grep guard: no bare ``except: pass`` in pharos_editor (flaw #10).

Nova3D shipped 50+ silent exception swallows. Pharos bans them: all
broad catches must route through :func:`pharos_editor.errors.route`.
Any `except ...: pass` (or `except: pass`) is a CI failure.

Usage::

    py -3.13 scripts/errors_lint.py

Exit 0 = clean; exit 1 = violations listed on stderr. Add
``# noqa: pharos-errors-lint`` on the same line to whitelist a
deliberate suppression (rare — prefer route()).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


BAD_PATTERN = re.compile(r"^\s*except\b[^:]*:\s*pass\s*(#.*)?$")
WHITELIST = "noqa: pharos-errors-lint"


def scan(root: Path) -> list[tuple[Path, int, str]]:
    violations: list[tuple[Path, int, str]] = []
    for py in root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            lines = py.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for idx, line in enumerate(lines, start=1):
            if BAD_PATTERN.match(line) and WHITELIST not in line:
                violations.append((py, idx, line.strip()))
    return violations


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    editor = repo / "python" / "pharos_editor"
    if not editor.exists():
        print(f"errors_lint: editor tree missing at {editor}", file=sys.stderr)
        return 2
    violations = scan(editor)
    if not violations:
        print("errors_lint: clean (no bare 'except ... : pass' in pharos_editor)")
        return 0
    print(f"errors_lint: {len(violations)} violation(s):", file=sys.stderr)
    for path, lineno, line in violations:
        rel = path.relative_to(repo)
        print(f"  {rel}:{lineno}: {line}", file=sys.stderr)
    print(
        "\nHelp: route through pharos_editor.errors.route(exc, context) "
        "instead of swallowing. If suppression is truly intended, add "
        "'# noqa: pharos-errors-lint' on the same line.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
