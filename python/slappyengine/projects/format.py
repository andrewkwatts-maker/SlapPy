"""On-disk format for ``project.slap_proj`` (YAML).

A project manifest is a small YAML document at the root of the project
directory. The shape is:

.. code-block:: yaml

    name: "My First Game"
    version: "0.3.0b0"
    created_at: "2026-06-03T10:30:00Z"
    last_opened_at: "2026-06-03T14:15:00Z"
    description: "A platformer with bouncy physics."
    icon: "icon.png"
    default_theme: "teengirl_notebook"

Functions
---------

* :func:`read_project` — load a :class:`Project` from a directory.
* :func:`write_project` — atomically write a project's manifest.
* :func:`is_project_dir` — ``True`` iff *path* contains a manifest.
* :func:`find_project_root` — walk upward from *path* looking for one.

Errors
------

All format-related I/O raises :class:`ProjectFormatError` (a
``ValueError`` subclass) on malformed YAML or missing required fields.
``FileNotFoundError`` propagates from the underlying read if the
directory or file is missing.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from slappyengine._validation import validate_path_like


if TYPE_CHECKING:
    from .project import Project


__all__ = [
    "PROJECT_FILE_NAME",
    "ProjectFormatError",
    "read_project",
    "write_project",
    "is_project_dir",
    "find_project_root",
]


#: Canonical manifest filename. Used everywhere — the engine never
#: tries alternates (no ``.yaml`` / ``.yml`` ambiguity, no case folding).
PROJECT_FILE_NAME = "project.slap_proj"


class ProjectFormatError(ValueError):
    """Raised when ``project.slap_proj`` is malformed or missing fields.

    Subclasses :class:`ValueError` so callers that broadly catch
    ``ValueError`` for config validation still see it.
    """


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def read_project(path: Path | str) -> "Project":
    """Load a :class:`Project` from a directory containing the manifest.

    Parameters
    ----------
    path:
        Project root directory (the one containing ``project.slap_proj``).

    Returns
    -------
    Project
        Fully populated :class:`Project` with metadata loaded.

    Raises
    ------
    TypeError
        If *path* is not a ``str`` / ``Path``.
    FileNotFoundError
        If *path* or the manifest file does not exist.
    ProjectFormatError
        If the manifest YAML is malformed or missing ``name`` /
        ``version``.
    """
    from .project import Project, ProjectMetadata

    root = validate_path_like("path", "read_project", path)
    if not root.exists():
        raise FileNotFoundError(
            f"read_project: project directory not found: {root}"
        )
    if not root.is_dir():
        raise FileNotFoundError(
            f"read_project: not a directory: {root}"
        )

    manifest = root / PROJECT_FILE_NAME
    if not manifest.is_file():
        raise FileNotFoundError(
            f"read_project: manifest not found: {manifest}"
        )

    try:
        raw = manifest.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectFormatError(
            f"read_project: failed to read {manifest}: {exc}"
        ) from exc

    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ProjectFormatError(
            f"read_project: malformed YAML in {manifest}: {exc}"
        ) from exc

    if data is None:
        raise ProjectFormatError(
            f"read_project: empty manifest at {manifest}"
        )
    if not isinstance(data, dict):
        raise ProjectFormatError(
            f"read_project: manifest at {manifest} must be a YAML mapping; "
            f"got {type(data).__name__}"
        )

    try:
        metadata = ProjectMetadata.from_dict(data)
    except KeyError as exc:
        raise ProjectFormatError(
            f"read_project: missing required field {exc.args[0]!r} "
            f"in {manifest}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise ProjectFormatError(
            f"read_project: invalid manifest at {manifest}: {exc}"
        ) from exc

    return Project(path=root, metadata=metadata)


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def write_project(project: "Project") -> None:
    """Write *project*'s manifest to disk atomically.

    The manifest is rendered with ``yaml.safe_dump`` and written through
    a temp file + rename so a crash mid-write never leaves a partially
    serialised manifest on disk. The project root directory is created
    if missing.

    Parameters
    ----------
    project:
        The :class:`Project` whose ``metadata`` should be persisted.

    Raises
    ------
    OSError
        If the directory cannot be created or the manifest cannot be
        written / renamed.
    """
    # Import here to dodge the project ↔ format circular at module load.
    from .project import Project

    if not isinstance(project, Project):
        raise TypeError(
            f"write_project: expected Project; got {type(project).__name__}"
        )

    root = project.path
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / PROJECT_FILE_NAME

    payload = yaml.safe_dump(
        project.metadata.to_dict(),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )

    tmp = manifest.with_suffix(manifest.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    # ``Path.replace`` is the atomic rename on every supported OS.
    tmp.replace(manifest)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def is_project_dir(path: Path | str) -> bool:
    """Return ``True`` iff *path* is a directory containing the manifest.

    Pure filesystem check — does not attempt to parse the manifest, so
    a corrupt project still answers ``True`` here. Callers that need a
    parsing check should use :func:`read_project` instead.
    """
    try:
        p = validate_path_like("path", "is_project_dir", path)
    except (TypeError, ValueError):
        return False
    if not p.is_dir():
        return False
    return (p / PROJECT_FILE_NAME).is_file()


def find_project_root(path: Path | str) -> Path | None:
    """Walk upward from *path* looking for a project root.

    Returns the first ancestor (or *path* itself) that contains
    ``project.slap_proj``. Returns ``None`` if no project root is found
    before reaching the filesystem root.

    Parameters
    ----------
    path:
        Starting directory (or file inside a project).

    Raises
    ------
    TypeError
        If *path* is not a ``str`` / ``Path``.
    """
    start = validate_path_like("path", "find_project_root", path)

    # If we were handed a file path, walk up from its parent.
    if start.exists() and start.is_file():
        cur = start.parent
    else:
        cur = start

    # ``cur.parent == cur`` is the filesystem root sentinel — works on
    # both POSIX (``/`` → ``/``) and Windows (``C:\`` → ``C:\``).
    seen: set[Path] = set()
    while True:
        try:
            cur_resolved = cur.resolve()
        except OSError:
            cur_resolved = cur
        if cur_resolved in seen:
            return None
        seen.add(cur_resolved)
        if (cur / PROJECT_FILE_NAME).is_file():
            return cur
        parent = cur.parent
        if parent == cur:
            return None
        cur = parent
