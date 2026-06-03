"""slappyengine.projects — Nova3D-style multi-project management.

A *project* is a directory tree owned by an end-user game (or other
authoring artefact) and pinned by a YAML manifest file
(``project.slap_proj``) at its root. The :class:`Project` dataclass is
the in-memory representation of that manifest plus its on-disk layout
(``scenes/``, ``assets/``, ``scripts/`` + ``icon.png``). The
:class:`ProjectRegistry` persists the "recently opened projects" list
to ``~/.slappyengine/projects.yaml`` so the editor's welcome screen can
restore the user's session across launches.

Public surface
--------------

* :class:`Project` / :class:`ProjectMetadata` — in-memory project state.
* :class:`ProjectRegistry` + :func:`get_default_registry` — singleton
  recents tracker, persisted as YAML.
* :func:`read_project` / :func:`write_project` — on-disk format I/O
  (``project.slap_proj`` is YAML).
* :func:`is_project_dir` / :func:`find_project_root` — directory-walk
  helpers for resolving a project root from an arbitrary cwd.
* :func:`scaffold_project` — create the default project directory
  tree (``scenes/main.scene.yaml``, ``assets/README.md``,
  ``scripts/main.py``, ``icon.png``) on disk.
* :data:`PROJECT_FILE_NAME` — canonical filename (``project.slap_proj``).

Example
-------

>>> from slappyengine.projects import Project, get_default_registry
>>> registry = get_default_registry()
>>> proj = registry.new("/tmp/my_game", "My First Game")  # doctest: +SKIP
>>> proj.scenes_dir.exists()  # doctest: +SKIP
True
"""
from __future__ import annotations

from .format import (
    PROJECT_FILE_NAME,
    ProjectFormatError,
    find_project_root,
    is_project_dir,
    read_project,
    write_project,
)
from .project import Project, ProjectMetadata
from .registry import ProjectRegistry, get_default_registry
from .scaffolding import scaffold_project


__all__ = [
    # core dataclasses
    "Project",
    "ProjectMetadata",
    # registry
    "ProjectRegistry",
    "get_default_registry",
    # format I/O
    "read_project",
    "write_project",
    "is_project_dir",
    "find_project_root",
    "ProjectFormatError",
    "PROJECT_FILE_NAME",
    # scaffolding
    "scaffold_project",
]
