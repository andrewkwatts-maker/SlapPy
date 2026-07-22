"""slap — Pharos Engine command-line interface.

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
        from pharos_engine.build.scaffolder import scaffold_project
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
        _die("pyyaml is required — install pharos_engine with its dependencies")

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
        from pharos_engine import __version__ as engine_version
    except Exception:
        engine_version = "unknown"

    try:
        import wgpu
        wgpu_version = wgpu.__version__
    except Exception:
        wgpu_version = "not installed"

    print(f"Pharos Engine {engine_version}")
    print(f"Python       {sys.version}")
    print(f"wgpu         {wgpu_version}")
    print(f"Platform     {sys.platform}")


def cmd_pack(args: argparse.Namespace) -> None:
    proj_file = _find_project_file(args.project)
    print(f"[pack] {proj_file.parent}  OK  (stub — asset bundling not yet implemented)")


# ---------------------------------------------------------------------------
# HH2 sub-commands (scaffolder / launcher / config regen)
# ---------------------------------------------------------------------------

def cmd_launch(args: argparse.Namespace) -> None:
    """Launch a scaffolded project — or spin up a temp project when no path.

    ``pharos launch``          → new temp project in ~/.pharos_engine/temp_projects
    ``pharos launch PATH``     → launch that project
    ``pharos launch --editor`` → open the editor instead of main.py
    """
    from pharos_engine import scaffold

    if args.path is None:
        proj = scaffold.create_temp_project(editor=args.editor)
        print(f"scaffolded temp project at {proj}")
    else:
        proj = Path(args.path).resolve()
        if not scaffold.is_project_dir(proj):
            _die(f"not a Pharos Engine project: {proj}")

    if args.dry_run:
        cmd = scaffold.launch_project(proj, editor=args.editor, dry_run=True)
        print(" ".join(str(c) for c in cmd))
        return

    result = scaffold.launch_project(proj, editor=args.editor)
    if hasattr(result, "returncode"):
        sys.exit(result.returncode)


def cmd_dev(args: argparse.Namespace) -> None:
    """Launch with hot-reload watching begin.py/tick.py/end.py.

    When ``watchdog`` is not installed the command falls back to a plain
    launch and prints a hint to install the dev extra.
    """
    from pharos_engine import scaffold

    proj = Path(args.path).resolve() if args.path else Path.cwd().resolve()
    if not scaffold.is_project_dir(proj):
        _die(f"not a Pharos Engine project: {proj}")

    try:
        import watchdog  # noqa: F401
    except ImportError:
        print("watchdog not installed — hot-reload disabled. "
              "Install with: pip install 'pharos-engine[dev]'", file=sys.stderr)

    if args.dry_run:
        cmd = scaffold.launch_project(proj, dry_run=True)
        print("dev-mode command: " + " ".join(str(c) for c in cmd))
        return

    # Set an env var main.py can consult to enable engine-side hot reload,
    # then hand off to the standard launch path.
    env = {"SLAPPY_HOT_RELOAD": "1"}
    result = scaffold.launch_project(proj, env=env)
    if hasattr(result, "returncode"):
        sys.exit(result.returncode)


def cmd_config(args: argparse.Namespace) -> None:
    """Regenerate config.yaml, preserving user values, filling missing keys."""
    from pharos_engine import scaffold

    proj = Path(args.path).resolve() if args.path else Path.cwd().resolve()
    if not proj.is_dir():
        _die(f"not a directory: {proj}")
    cfg = scaffold.regenerate_config(proj, preserve=not args.reset)
    action = "reset" if args.reset else "reconciled"
    print(f"{action} {cfg}")


def cmd_export(args: argparse.Namespace) -> None:
    """Bundle a project into a distributable ZIP or PyInstaller binary.

    Dispatches on the ``--output`` extension: ``.zip`` triggers the ZIP
    bundler; anything else routes to the PyInstaller binary exporter.
    """
    from pharos_engine import exporter

    proj_raw = Path(args.path).resolve() if args.path else Path.cwd().resolve()
    if not proj_raw.exists():
        _die(f"project directory does not exist: {proj_raw}")
    if not proj_raw.is_dir():
        _die(f"project path is not a directory: {proj_raw}")
    has_main = (proj_raw / "main.py").is_file()
    has_manifest = (proj_raw / "pharosproject.yaml").is_file()
    if not has_main and not has_manifest:
        _die(
            f"not a Pharos Engine project: {proj_raw} "
            f"(needs main.py or pharosproject.yaml)"
        )
    proj = proj_raw

    output = Path(args.output).resolve()

    # Resolve --target -> concrete list for the manifest.  ``all`` fans
    # out to every known target so downstream tooling can see the intent.
    if args.target == "all":
        manifest_targets = list(exporter.TARGETS.keys())
    else:
        manifest_targets = [args.target]

    result = exporter.export_project(
        proj,
        output,
        platform=args.platform,
        include_python=args.include_python,
        icon=args.icon,
        console=args.console,
        dry_run=args.dry_run,
        verbose=args.verbose,
        exclude_patterns=list(args.exclude or []),
        manifest_targets=manifest_targets,
    )

    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    for e in result.errors:
        print(f"error: {e}", file=sys.stderr)

    if result.errors:
        sys.exit(1)

    if args.dry_run and result.kind == "zip":
        print(f"[dry-run] would export zip -> {output}")
        print(f"[dry-run] {len(result.included_files)} files would be bundled")
        return

    if result.path is not None:
        size_kb = result.size_bytes / 1024.0
        print(f"exported {result.kind} -> {result.path} ({size_kb:.1f} KiB)")
    else:
        # Binary export skipped (PyInstaller missing) - spec was still written
        print("export produced no binary (see warnings above)")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slap",
        description="Pharos Engine project toolchain",
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

    # slap launch — HH2 scaffolder launcher
    p_launch = sub.add_parser(
        "launch",
        help="launch a scaffolded project (or a fresh temp project)",
    )
    p_launch.add_argument("path", nargs="?", default=None,
                          help="project directory (default: create a temp project)")
    p_launch.add_argument("--editor", action="store_true",
                          help="launch the editor instead of main.py")
    p_launch.add_argument("--dry-run", action="store_true",
                          help="print the launch command without executing it")

    # slap dev — hot-reload launcher
    p_dev = sub.add_parser(
        "dev",
        help="launch with begin.py/tick.py/end.py hot-reload",
    )
    p_dev.add_argument("path", nargs="?", default=None,
                       help="project directory (default: cwd)")
    p_dev.add_argument("--dry-run", action="store_true",
                       help="print the launch command without executing it")

    # slap config — regenerate config.yaml with defaults
    p_config = sub.add_parser(
        "config",
        help="regenerate config.yaml with defaults for missing keys",
    )
    p_config.add_argument("path", nargs="?", default=None,
                          help="project directory (default: cwd)")
    p_config.add_argument("--reset", action="store_true",
                          help="discard user values and write pristine defaults")

    # slap export — bundle to zip or PyInstaller binary
    p_export = sub.add_parser(
        "export",
        help="export a project to a distributable ZIP or standalone binary",
    )
    p_export.add_argument("path", nargs="?", default=None,
                          help="project directory (default: cwd)")
    p_export.add_argument("--output", required=True, metavar="PATH",
                          help="output file (.zip) or directory (binary export)")
    p_export.add_argument(
        "--platform",
        default="auto",
        choices=["auto", "windows", "linux", "macos"],
        help="target platform (default: auto = host OS)",
    )
    p_export.add_argument("--include-python", action="store_true",
                          help="bundle a launcher script (and interpreter if available)")
    p_export.add_argument("--icon", default=None, metavar="PATH",
                          help="path to icon file for binary export")
    p_export.add_argument("--console", action="store_true",
                          help="binary export: attach a console window (default: off)")
    p_export.add_argument("--dry-run", action="store_true",
                          help="validate + list files without writing the zip (or, for binary "
                               "export, write spec only and skip PyInstaller)")
    p_export.add_argument("--verbose", "-v", action="store_true",
                          help="print each file as it is added to the bundle")
    p_export.add_argument("--exclude", action="append", metavar="PATTERN", default=None,
                          help="extra fnmatch-style exclude pattern (repeatable) — added on top "
                               "of built-in excludes (__pycache__, *.pyc, .git, *.log, ...)")
    p_export.add_argument("--target", default="all",
                          choices=["all", "windows", "linux", "macos"],
                          help="platform target(s) recorded in the bundle manifest.json "
                               "(default: all)")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_COMMANDS = {
    "new":    cmd_new,
    "run":    cmd_run,
    "build":  cmd_build,
    "check":  cmd_check,
    "info":   cmd_info,
    "pack":   cmd_pack,
    "launch": cmd_launch,
    "dev":    cmd_dev,
    "config": cmd_config,
    "export": cmd_export,
}


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    handler = _COMMANDS[args.command]
    handler(args)


if __name__ == "__main__":
    main()
