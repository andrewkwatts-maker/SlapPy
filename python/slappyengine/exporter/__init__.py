"""Cross-platform game exporter for SlapPyEngine (LL6).

This subpackage packages a scaffolded SlapPyEngine project into a
distributable ZIP + (optionally) a standalone binary via PyInstaller.

Public surface
--------------
* :class:`ZipBundler` — walks a project tree and writes a filtered ZIP.
* :class:`BinaryExporter` — PyInstaller-backed executable builder.
* :class:`ProjectManifest` — dataclass mirror of ``slappyproject.yaml``.
* :data:`TARGETS` — table of platform descriptors (windows / linux / macos).
* :class:`ExportResult` — unified return value for CLI / API callers.
* :func:`export_project` — convenience wrapper that dispatches on output
  filename (``.zip`` → ZipBundler, otherwise → BinaryExporter).

The corresponding CLI subcommand is registered in
:mod:`slappyengine.cli` as ``slap export``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .binary_exporter import BinaryExporter, BinaryExportResult, pyinstaller_available
from .manifest import MANIFEST_FILENAME, ProjectManifest, load_manifest
from .platform_targets import TARGETS, detect_current_platform, get_target
from .zip_bundler import BundleResult, DEFAULT_EXCLUDES, REQUIRED_FILES, ZipBundler


__all__ = [
    "BinaryExporter",
    "BinaryExportResult",
    "BundleResult",
    "DEFAULT_EXCLUDES",
    "ExportResult",
    "MANIFEST_FILENAME",
    "ProjectManifest",
    "REQUIRED_FILES",
    "TARGETS",
    "ZipBundler",
    "detect_current_platform",
    "export_project",
    "get_target",
    "load_manifest",
    "pyinstaller_available",
]


@dataclass
class ExportResult:
    """Unified return type for :func:`export_project` / CLI callers."""

    path: Path | None
    size_bytes: int = 0
    manifest: ProjectManifest | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    kind: str = "zip"                     # "zip" or "binary"
    included_files: list[str] = field(default_factory=list)
    python_bundled: bool = False
    pyinstaller_available: bool = False

    @property
    def succeeded(self) -> bool:
        return not self.errors and self.path is not None


def export_project(
    project_dir: str | Path,
    output: str | Path,
    *,
    platform: str = "auto",
    include_python: bool = False,
    icon: str | Path | None = None,
    console: bool = False,
    dry_run: bool = False,
) -> ExportResult:
    """Export *project_dir* to *output* — ZIP or PyInstaller binary.

    The dispatch rule is deliberately simple: if *output* ends with
    ``.zip`` we call :class:`ZipBundler`; otherwise :class:`BinaryExporter`.
    Callers that need finer-grained control should use the classes
    directly.
    """
    project_dir = Path(project_dir)
    output = Path(output)
    manifest = load_manifest(project_dir)

    result = ExportResult(
        path=None,
        manifest=manifest,
        pyinstaller_available=pyinstaller_available(),
    )

    if output.suffix.lower() == ".zip":
        result.kind = "zip"
        bundle = ZipBundler().bundle(
            project_dir,
            output,
            include_python=include_python,
            main_script=manifest.main_script,
        )
        result.path = bundle.zip_path
        result.size_bytes = bundle.size_bytes
        result.warnings.extend(bundle.warnings)
        result.included_files = list(bundle.included_files)
        result.python_bundled = bundle.python_bundled
        return result

    # Binary export
    result.kind = "binary"
    exp = BinaryExporter().export(
        project_dir,
        output,
        platform=platform,
        console=console,
        icon=icon,
        dry_run=dry_run,
        main_script=manifest.main_script,
        name=manifest.name,
    )
    result.path = exp.binary_path or exp.spec_path
    result.size_bytes = exp.size_bytes
    result.warnings.extend(exp.warnings)
    result.errors.extend(exp.errors)
    return result
