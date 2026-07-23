"""Build + install the pharos_engine wheel into the local venv.

On Windows the historical workaround here is required — the Windows
Store Python-launcher shim at
``C:\\Users\\Andrew\\AppData\\Local\\Microsoft\\WindowsApps\\python.exe``
prevents ``maturin develop`` from working (Access is denied when
maturin probes the shim for sysconfig metadata), so we build a
wheel with ``maturin build --interpreter <real python>`` and pip-
install it into the venv.

On non-Windows platforms the script uses the current interpreter
(``sys.executable``) as both the wheel target and the venv seed.

Usage::

    py -3.13 scripts/build_wheel.py           # release build (Windows)
    python3   scripts/build_wheel.py           # release build (Linux/macOS)
    python3   scripts/build_wheel.py --debug   # unoptimised build
    python3   scripts/build_wheel.py --no-install  # build-only

The script is idempotent — running twice re-builds + re-installs the
wheel. Cargo caches keep incremental rebuilds under 10 seconds after
the first build.
"""
from __future__ import annotations

import argparse
import glob
import os
import platform
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
WHEEL_DIR = REPO_ROOT / "target" / "wheels"

_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    REAL_PYTHON = Path(r"C:\Users\Andrew\AppData\Local\Programs\Python\Python313\python.exe")
    VENV_PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
else:
    REAL_PYTHON = Path(sys.executable)
    VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"


def ensure_venv() -> Path:
    """Create the .venv if missing; return the venv python path."""
    if VENV_PYTHON.exists():
        return VENV_PYTHON
    if not REAL_PYTHON.exists():
        print(
            f"error: real Python interpreter not found at {REAL_PYTHON}",
            file=sys.stderr,
        )
        sys.exit(2)
    print(f"creating venv at {VENV_PYTHON.parent.parent} ...")
    subprocess.check_call([str(REAL_PYTHON), "-m", "venv", str(VENV_PYTHON.parent.parent)])
    subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "--quiet", "maturin"])
    return VENV_PYTHON


def build_wheel(*, release: bool) -> Path:
    """Build the pharos_engine wheel via maturin. Returns wheel path."""
    ensure_venv()
    cmd = [
        str(VENV_PYTHON),
        "-m",
        "maturin",
        "build",
        "--interpreter",
        str(REAL_PYTHON),
    ]
    if release:
        cmd.append("--release")
    print(">>", " ".join(cmd))
    subprocess.check_call(cmd, cwd=REPO_ROOT)

    # maturin drops the wheel under target/wheels/. Pick the newest.
    wheels = sorted(
        glob.glob(str(WHEEL_DIR / "pharos_engine-*.whl")),
        key=os.path.getmtime,
    )
    if not wheels:
        print("error: maturin succeeded but no wheel found under target/wheels/", file=sys.stderr)
        sys.exit(3)
    return Path(wheels[-1])


def install_wheel(wheel: Path) -> None:
    print(f">> pip install --force-reinstall {wheel.name}")
    subprocess.check_call(
        [str(VENV_PYTHON), "-m", "pip", "install", "--force-reinstall", str(wheel)]
    )


def smoke_test() -> None:
    print(">> smoke test")
    r = subprocess.run(
        [
            str(VENV_PYTHON),
            "-c",
            (
                "import pharos_engine, sys; "
                "print('version:', pharos_engine.__version__); "
                "print('HAS_NATIVE:', pharos_engine.HAS_NATIVE); "
                "sys.exit(0 if pharos_engine.HAS_NATIVE else 1)"
            ),
        ],
        capture_output=True,
        text=True,
    )
    print(r.stdout.strip())
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(r.returncode)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--debug", action="store_true", help="unoptimised build (faster iteration)")
    ap.add_argument("--no-install", action="store_true", help="build only, skip install + smoke test")
    args = ap.parse_args()

    wheel = build_wheel(release=not args.debug)
    print(f"built: {wheel}")
    if args.no_install:
        return 0
    install_wheel(wheel)
    smoke_test()
    print("OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
