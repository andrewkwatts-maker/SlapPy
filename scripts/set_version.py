"""Set the engine version consistently across pyproject.toml, Cargo.toml,
and python/slappyengine/__init__.py.

Usage:
    python scripts/set_version.py 0.3.0
    python scripts/set_version.py 0.3.0a1
    python scripts/set_version.py 0.4.0-rc.1   # SemVer ↔ PEP 440 normaliser handles both

Called by ``SetVersion.bat <ver>`` on Windows.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path


_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _ROOT / "pyproject.toml"
_CARGO = _ROOT / "Cargo.toml"
_INIT = _ROOT / "python" / "slappyengine" / "__init__.py"


def _to_pep440(v: str) -> str:
    """SemVer pre-release tag → PEP 440 (e.g. ``0.3.0-rc.1`` → ``0.3.0rc1``)."""
    # 0.3.0-rc.1 → 0.3.0rc1, 0.3.0-alpha.0 → 0.3.0a0, 0.3.0-beta.2 → 0.3.0b2
    return (
        v.replace("-alpha.", "a")
         .replace("-beta.", "b")
         .replace("-rc.", "rc")
         .replace("-", "")
    )


def _to_semver(v: str) -> str:
    """PEP 440 pre-release tag → SemVer (e.g. ``0.3.0a1`` → ``0.3.0-alpha.1``)."""
    m = re.match(r"^(\d+\.\d+\.\d+)(a|b|rc)(\d+)$", v)
    if m:
        base, kind, num = m.groups()
        spelt = {"a": "alpha", "b": "beta", "rc": "rc"}[kind]
        return f"{base}-{spelt}.{num}"
    return v


def _patch(path: Path, pattern: str, replacement: str) -> bool:
    text = path.read_text(encoding="utf-8")
    new_text, n = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if n == 0:
        print(f"  WARN {path.name}: no match for pattern; nothing written")
        return False
    if new_text == text:
        print(f"  unchanged {path.name}")
        return False
    path.write_text(new_text, encoding="utf-8")
    print(f"  updated  {path.name}")
    return True


def main(version: str) -> int:
    version = version.strip().lstrip("v")
    if not re.match(r"^\d+\.\d+\.\d+", version):
        print(f"ERROR: expected M.N.P or M.N.P-prerelease; got {version!r}")
        return 2

    pep440 = _to_pep440(version)
    semver = _to_semver(version)

    print(f"setting engine version to {version!r}")
    print(f"  PEP 440 (Python): {pep440}")
    print(f"  SemVer  (Cargo):  {semver}")

    changed = 0
    changed += _patch(
        _PYPROJECT,
        r'^version\s*=\s*"[^"]*"',
        f'version = "{pep440}"',
    )
    changed += _patch(
        _CARGO,
        r'^version\s*=\s*"[^"]*"',
        f'version = "{semver}"',
    )
    changed += _patch(
        _INIT,
        r'^__version__\s*=\s*"[^"]*"',
        f'__version__ = "{pep440}"',
    )
    print(f"done. {changed} file(s) updated.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python scripts/set_version.py <version>")
        print("  e.g.  python scripts/set_version.py 0.3.0")
        print("        python scripts/set_version.py 0.3.0a1")
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
