"""Per-platform export target descriptors (LL6).

Each entry in :data:`TARGETS` describes:

* ``executable_ext`` — filename suffix for produced binaries
  (``".exe"`` on Windows, ``""`` elsewhere).
* ``launcher_ext`` — filename suffix for the shell launcher script that
  ships alongside a python-bundled ZIP.
* ``launcher_template`` — text of the launcher, templated with the
  project's main script filename.
* ``pyinstaller_flags`` — extra flags passed to ``PyInstaller`` when
  targeting this OS.
* ``requires_native`` — True if the target can only be produced on a
  matching host (PyInstaller does not cross-compile).
"""
from __future__ import annotations

import sys
from typing import Any


__all__ = ["TARGETS", "detect_current_platform", "get_target"]


_WINDOWS_LAUNCHER = """\
@echo off
REM Auto-generated launcher — runs the bundled project with the local Python.
setlocal
set "PROJECT_DIR=%~dp0"
if exist "%PROJECT_DIR%python\\python.exe" (
    "%PROJECT_DIR%python\\python.exe" "%PROJECT_DIR%${main_script}" %*
) else (
    python "%PROJECT_DIR%${main_script}" %*
)
endlocal & exit /b %ERRORLEVEL%
"""


_POSIX_LAUNCHER = """\
#!/usr/bin/env bash
# Auto-generated launcher — runs the bundled project with the local Python.
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -x "$PROJECT_DIR/python/bin/python3" ]; then
    exec "$PROJECT_DIR/python/bin/python3" "$PROJECT_DIR/${main_script}" "$@"
else
    exec python3 "$PROJECT_DIR/${main_script}" "$@"
fi
"""


TARGETS: dict[str, dict[str, Any]] = {
    "windows": {
        "executable_ext": ".exe",
        "launcher_ext": ".bat",
        "launcher_template": _WINDOWS_LAUNCHER,
        "pyinstaller_flags": ["--onefile"],
        "requires_native": True,
    },
    "linux": {
        "executable_ext": "",
        "launcher_ext": ".sh",
        "launcher_template": _POSIX_LAUNCHER,
        "pyinstaller_flags": ["--onefile", "--strip"],
        "requires_native": True,
    },
    "macos": {
        "executable_ext": "",
        "launcher_ext": ".sh",
        "launcher_template": _POSIX_LAUNCHER,
        "pyinstaller_flags": ["--onefile", "--windowed"],
        "requires_native": True,
    },
}


def detect_current_platform() -> str:
    """Return the ``TARGETS`` key that matches the current host OS."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def get_target(name: str) -> dict[str, Any]:
    """Return the target descriptor for *name* (``"auto"`` resolves to host)."""
    if name == "auto":
        name = detect_current_platform()
    key = name.lower()
    if key not in TARGETS:
        raise ValueError(
            f"unknown platform target {name!r} — valid: {sorted(TARGETS)}"
        )
    return TARGETS[key]
