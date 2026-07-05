"""ZIP bundling for the SlapPyEngine exporter (LL6).

Walks a scaffolded project tree and produces a distributable ZIP that
contains only the files an end-user needs to run the game.

Exclusion policy
----------------
Always excluded (regardless of caller):

* ``.git/`` and any nested ``.git`` directory
* ``__pycache__/`` and any ``*.pyc`` bytecode
* ``.venv/`` / ``venv/`` / ``env/`` (developer virtualenvs)
* ``build/`` and ``dist/`` (previous export artefacts)
* ``.slappy/temp/`` (engine-managed temp state)
* ``*.log`` files (developer noise)

Always included when present:

* ``main.py`` / ``begin.py`` / ``tick.py`` / ``end.py``
* ``config.yaml``
* ``slappyproject.yaml`` (manifest)
* ``assets/`` and ``scenes/`` subtrees
* Launcher scripts (``launch.*``) if the project scaffolded them

Callers can extend the exclude list via *exclude_patterns*
(``fnmatch``-style, matched against POSIX-style relative paths).

The ``include_python`` flag adds a launcher script and, when a
compatible embeddable interpreter can be located on the host, drops it
into ``python/`` inside the archive.  When no interpreter is available
we still emit the launcher and add a ``PYTHON_SETUP.txt`` explaining how
the end user should install Python themselves.
"""
from __future__ import annotations

import fnmatch
import os
import sys
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from string import Template
from typing import Iterable


__all__ = [
    "ZipBundler",
    "BundleResult",
    "DEFAULT_EXCLUDES",
    "REQUIRED_FILES",
]


DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git",
    ".git/*",
    "*/.git",
    "*/.git/*",
    "__pycache__",
    "*/__pycache__",
    "*/__pycache__/*",
    "__pycache__/*",
    "*.pyc",
    "*.pyo",
    ".venv",
    ".venv/*",
    "venv",
    "venv/*",
    "env/lib/*",
    "build",
    "build/*",
    "dist",
    "dist/*",
    ".slappy/temp",
    ".slappy/temp/*",
    "*.log",
    ".DS_Store",
    "*/.DS_Store",
)


REQUIRED_FILES: tuple[str, ...] = (
    "main.py",
    "begin.py",
    "tick.py",
    "end.py",
    "config.yaml",
)


@dataclass
class BundleResult:
    """Return value from :meth:`ZipBundler.bundle`."""

    zip_path: Path
    size_bytes: int = 0
    included_files: list[str] = field(default_factory=list)
    excluded_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    python_bundled: bool = False


class ZipBundler:
    """Produce a distributable ZIP from a scaffolded project directory."""

    def __init__(self, *, compression: int = zipfile.ZIP_DEFLATED) -> None:
        self.compression = compression

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def bundle(
        self,
        project_dir: str | Path,
        output_zip: str | Path,
        *,
        include_python: bool = False,
        exclude_patterns: Iterable[str] | None = None,
        main_script: str = "main.py",
    ) -> BundleResult:
        project_dir = Path(project_dir).resolve()
        output_zip = Path(output_zip).resolve()

        if not project_dir.is_dir():
            raise FileNotFoundError(f"project directory does not exist: {project_dir}")

        excludes = list(DEFAULT_EXCLUDES)
        if exclude_patterns:
            excludes.extend(exclude_patterns)

        output_zip.parent.mkdir(parents=True, exist_ok=True)

        result = BundleResult(zip_path=output_zip)

        with zipfile.ZipFile(output_zip, "w", self.compression) as zf:
            for path in self._walk(project_dir):
                rel = path.relative_to(project_dir)
                posix_rel = rel.as_posix()
                if _is_excluded(posix_rel, excludes):
                    result.excluded_files.append(posix_rel)
                    continue
                zf.write(path, arcname=posix_rel)
                result.included_files.append(posix_rel)

            # Sanity check — warn (do not fail) if required files missing
            existing = set(result.included_files)
            for req in REQUIRED_FILES:
                if req not in existing and not (project_dir / req).is_file():
                    result.warnings.append(f"required file missing from project: {req}")

            if include_python:
                bundled = self._bundle_python(zf, project_dir, main_script)
                result.python_bundled = bundled
                if not bundled:
                    result.warnings.append(
                        "include_python=True but no embeddable interpreter found; "
                        "wrote PYTHON_SETUP.txt with install instructions instead"
                    )

        result.size_bytes = output_zip.stat().st_size
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _walk(self, root: Path) -> Iterable[Path]:
        for dirpath, dirnames, filenames in os.walk(root):
            # Prune obviously-excluded dirs up-front so we don't recurse
            dirnames[:] = [d for d in dirnames if d not in {
                ".git", "__pycache__", ".venv", "venv", "build", "dist",
            }]
            for name in filenames:
                yield Path(dirpath) / name

    def _bundle_python(
        self,
        zf: zipfile.ZipFile,
        project_dir: Path,
        main_script: str,
    ) -> bool:
        """Attempt to embed a Python interpreter; return True on success."""
        from . import platform_targets

        target = platform_targets.get_target("auto")
        launcher_ext = target["launcher_ext"]
        launcher_body = Template(target["launcher_template"]).safe_substitute(
            main_script=main_script
        )
        # Use a distinct name from the scaffolder's launch.bat/sh to avoid
        # duplicate-name warnings and to make the export-shipped launcher
        # discoverable independently.
        launcher_name = f"run_game{launcher_ext}"
        zf.writestr(launcher_name, launcher_body)

        # We do not ship binary python interpreters from within the engine
        # wheel — instead we emit a helpful setup note.  If the host has
        # a python-build-standalone archive at SLAPPY_EMBED_PYTHON, copy
        # it into python/ so power-users can opt-in.
        embed_dir = os.environ.get("SLAPPY_EMBED_PYTHON")
        if embed_dir and Path(embed_dir).is_dir():
            embed_root = Path(embed_dir)
            for p in embed_root.rglob("*"):
                if p.is_file():
                    arc = PurePosixPath("python") / p.relative_to(embed_root).as_posix()
                    zf.write(p, arcname=str(arc))
            return True

        zf.writestr(
            "PYTHON_SETUP.txt",
            (
                "This bundle expects a Python 3.10+ interpreter on the host.\n"
                "Install Python from https://python.org/ then run:\n"
                f"    python {main_script}\n"
                "or double-click the shipped launcher script.\n"
            ),
        )
        return False


def _is_excluded(posix_rel: str, patterns: Iterable[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(posix_rel, pat):
            return True
        # Also match dir-anchored patterns (e.g. ``__pycache__`` should also
        # kill ``foo/__pycache__/bar.pyc``)
        if "/" not in pat and pat in posix_rel.split("/"):
            return True
    return False
