"""slap — SlapPyEngine command-line interface.

Entry point: main()
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _die(msg: str) -> None:
    """Print an error message and exit with code 1."""
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(1)


def _find_project_file(project_arg: str | None) -> Path:
    """Locate project.slap_proj starting from *project_arg* or cwd."""
    base = Path(project_arg).resolve() if project_arg else Path.cwd()
    candidate = base / "project.slap_proj"
    if candidate.is_file():
        return candidate
    # Also accept the file itself being passed directly
    if base.is_file() and base.suffix == ".slap_proj":
        return base
    _die(f"cannot find project.slap_proj in {base}")


# ---------------------------------------------------------------------------
# Sub-command implementations
# ---------------------------------------------------------------------------

def cmd_new(args: argparse.Namespace) -> None:
    name: str = args.name
    template: str = args.template
    dest = Path.cwd() / name

    if dest.exists():
        _die(f"directory already exists: {dest}")

    try:
        from slappyengine.build.scaffolder import scaffold_project
    except ImportError as exc:
        _die(f"scaffolder not available: {exc}")

    scaffold_project(name, dest, template)
    print(f"✓ Created {name}/  →  cd {name} && slap run")


def cmd_run(args: argparse.Namespace) -> None:
    proj_file = _find_project_file(args.project)
    proj_dir = proj_file.parent

    try:
        import yaml  # pyyaml is a core dependency
    except ImportError:
        _die("pyyaml is required — install slappyengine with its dependencies")

    with proj_file.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    entry_rel = data.get("entry", "Source/main.py")
    entry_path = proj_dir / entry_rel

    if not entry_path.is_file():
        _die(f"entry file not found: {entry_path}")

    result = subprocess.run([sys.executable, str(entry_path)], cwd=str(proj_dir))
    sys.exit(result.returncode)


def cmd_build(args: argparse.Namespace) -> None:
    target: str = args.target
    release: bool = args.release
    mode = "release" if release else "debug"
    print(f"[build] target={target!r} mode={mode!r}  (stub — not yet implemented)")


def cmd_check(args: argparse.Namespace) -> None:
    proj_file = _find_project_file(args.project)
    print(f"[check] {proj_file}  OK")


def cmd_info(_args: argparse.Namespace) -> None:
    try:
        from slappyengine import __version__ as engine_version
    except Exception:
        engine_version = "unknown"

    try:
        import wgpu
        wgpu_version = wgpu.__version__
    except Exception:
        wgpu_version = "not installed"

    print(f"SlapPyEngine {engine_version}")
    print(f"Python       {sys.version}")
    print(f"wgpu         {wgpu_version}")
    print(f"Platform     {sys.platform}")


def cmd_pack(args: argparse.Namespace) -> None:
    proj_file = _find_project_file(args.project)
    print(f"[pack] {proj_file.parent}  OK  (stub — asset bundling not yet implemented)")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slap",
        description="SlapPyEngine project toolchain",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")
    sub.required = True

    # slap new
    p_new = sub.add_parser("new", help="scaffold a new project")
    p_new.add_argument("name", help="project name (used as directory name)")
    p_new.add_argument(
        "--template",
        default="blank",
        choices=["blank", "2d", "2d-top-down", "3d"],
        help="project template (default: blank)",
    )

    # slap run
    p_run = sub.add_parser("run", help="run the project")
    p_run.add_argument("--project", default=None, metavar="PATH",
                       help="path containing project.slap_proj (default: cwd)")

    # slap build
    p_build = sub.add_parser("build", help="build/export the project")
    p_build.add_argument("--target", required=True, choices=["exe", "apk", "web"],
                         help="export target")
    p_build.add_argument("--release", action="store_true",
                         help="optimised release build")

    # slap check
    p_check = sub.add_parser("check", help="validate project structure")
    p_check.add_argument("--project", default=None, metavar="PATH",
                         help="path containing project.slap_proj (default: cwd)")

    # slap info
    sub.add_parser("info", help="print engine / environment info")

    # slap pack
    p_pack = sub.add_parser("pack", help="bundle project assets")
    p_pack.add_argument("--project", default=None, metavar="PATH",
                        help="path containing project.slap_proj (default: cwd)")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_COMMANDS = {
    "new":   cmd_new,
    "run":   cmd_run,
    "build": cmd_build,
    "check": cmd_check,
    "info":  cmd_info,
    "pack":  cmd_pack,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    handler = _COMMANDS[args.command]
    handler(args)


if __name__ == "__main__":
    main()
