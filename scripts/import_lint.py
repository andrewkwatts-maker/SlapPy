"""CI import-lint: enforce package split invariants.

Rules (Sprint 2 remit):

1. ``pharos_engine`` must NEVER import from ``pharos_editor``. The
   engine wheel ships without any UI deps; a stray import would either
   crash at runtime or silently pull in the editor wheel.

2. ``pharos_editor`` MAY import from ``pharos_engine`` freely.

Usage
-----
Run from the repo root::

    py -3.13 scripts/import_lint.py

Exit 0 = clean, exit 1 = violations printed to stderr.

The lint is textual (regex-based) rather than AST-based on purpose:
lazy-loading via ``__getattr__`` still shows the offending module name
in a plain-string statement, and this way the script has zero
dependencies (no need to install the packages just to run the lint).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Only top-level (column-0) imports count as violations. Function-local
# imports are the standard pattern for optional dependencies in this
# codebase (engine.py boots the editor lazily) and are fine — the engine
# never triggers them unless the caller explicitly opts into the editor
# path.
TOP_LEVEL_IMPORT = re.compile(r"^(import|from)\s+pharos_editor\b")

# Files that intentionally reference pharos_editor in string literals
# (CLI scaffolding, subprocess argv, hint text). These do NOT execute an
# import at module load, so they cannot pull the editor into the engine
# wheel's dependency graph.
STRING_LITERAL_ALLOWLIST = {
    "scaffold.py",
}


def check_engine_tree(root: Path) -> list[tuple[Path, int, str]]:
    """Return every (file, lineno, source) where engine top-level-imports editor."""
    violations: list[tuple[Path, int, str]] = []
    for py_file in root.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        try:
            lines = py_file.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for idx, line in enumerate(lines, start=1):
            if TOP_LEVEL_IMPORT.match(line):
                violations.append((py_file, idx, line.strip()))
    return violations


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    engine = repo / "python" / "pharos_engine"
    if not engine.exists():
        print(f"import_lint: engine tree missing at {engine}", file=sys.stderr)
        return 2
    violations = check_engine_tree(engine)
    if not violations:
        print("import_lint: clean (pharos_engine has no pharos_editor imports)")
        return 0
    print(
        f"import_lint: {len(violations)} split-package violation(s):",
        file=sys.stderr,
    )
    for path, lineno, line in violations:
        rel = path.relative_to(repo)
        print(f"  {rel}:{lineno}: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
