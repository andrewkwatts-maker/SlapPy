"""``ProjectRegistry`` — persistent "recently opened projects" tracker.

The registry stores a per-user list of recently opened projects so the
editor's welcome screen can restore the user's session across launches.
It is persisted as a single YAML document at
``~/.slappyengine/projects.yaml``:

.. code-block:: yaml

    recent:
      - path: "/home/me/games/MyFirstGame"
        last_opened_at: "2026-06-03T14:15:00Z"
        name: "My First Game"
      - path: "/home/me/games/PixelArcade"
        last_opened_at: "2026-06-02T09:00:00Z"
        name: "Pixel Arcade"

The ``name`` is a denormalised copy of the project's manifest name —
keeping it in the registry lets the welcome screen render a project
list without opening every manifest, and lets the registry recover
gracefully from projects whose disk entry has been moved / deleted.

The registry is *not* the canonical project record — the manifest file
inside each project directory is. The registry only tracks discovery
state, not project data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml

from slappyengine._validation import (
    validate_path_like,
    validate_positive_int,
)

from .format import find_project_root, read_project, write_project
from .project import Project, ProjectMetadata, _iso_utc_now


__all__ = [
    "ProjectRegistry",
    "RegistryEntry",
    "get_default_registry",
    "DEFAULT_REGISTRY_PATH",
]


#: Default on-disk location of the registry YAML. Resolved lazily at
#: registry construction time so test code can override
#: ``HOME`` / ``USERPROFILE`` cleanly.
def _default_store_path() -> Path:
    """Return the default registry YAML path (``~/.slappyengine/projects.yaml``)."""
    return Path.home() / ".slappyengine" / "projects.yaml"


#: Backwards-compat constant — callers that want the default location
#: as a non-callable can import this. Resolved on first access.
DEFAULT_REGISTRY_PATH = _default_store_path


# ---------------------------------------------------------------------------
# RegistryEntry
# ---------------------------------------------------------------------------


@dataclass
class RegistryEntry:
    """One row in the registry's recents list.

    ``path`` is the absolute path to the project root (the directory
    containing ``project.slap_proj``). ``last_opened_at`` is an ISO 8601
    UTC string mirroring the manifest's ``last_opened_at`` field.
    ``name`` is a denormalised copy of the manifest name so the welcome
    screen can render a list without opening every manifest.
    """

    path: str
    last_opened_at: str
    name: str = ""

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "last_opened_at": self.last_opened_at,
            "name": self.name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "RegistryEntry":
        if not isinstance(data, dict):
            raise TypeError(
                "RegistryEntry.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        path = data.get("path")
        if not isinstance(path, str) or not path:
            raise ValueError(
                "RegistryEntry.from_dict: missing or empty 'path' field"
            )
        return cls(
            path=path,
            last_opened_at=data.get("last_opened_at") or _iso_utc_now(),
            name=data.get("name") or "",
        )


# ---------------------------------------------------------------------------
# ProjectRegistry
# ---------------------------------------------------------------------------


def _sort_key(entry: RegistryEntry) -> tuple[int, str]:
    """Sort registry entries newest-first.

    Falls back to lexicographic order when the ISO string is malformed
    so a single bad row never breaks sorting for the rest.
    """
    try:
        ts = datetime.fromisoformat(
            entry.last_opened_at.rstrip("Z").rstrip()
        )
        # Negate so descending sort goes oldest-last.
        return (-int(ts.timestamp()), entry.path)
    except (ValueError, TypeError):
        return (0, entry.path)


class ProjectRegistry:
    """Persistent recents tracker for projects opened by the editor.

    The registry lives at ``~/.slappyengine/projects.yaml`` by default;
    pass ``store_path`` to redirect it (tests / sandboxing). All writes
    are atomic via :func:`Path.replace`.

    A fresh registry is empty — :meth:`register` adds entries,
    :meth:`open` updates ``last_opened_at`` on each call, and
    :meth:`list_recent` returns the most-recently-opened projects.

    Parameters
    ----------
    store_path:
        Absolute path to the registry YAML. Defaults to
        ``~/.slappyengine/projects.yaml``.
    """

    def __init__(self, store_path: Path | str | None = None) -> None:
        if store_path is None:
            self.store_path: Path = _default_store_path()
        else:
            self.store_path = validate_path_like(
                "store_path", "ProjectRegistry", store_path,
            )
        self._entries: list[RegistryEntry] = []
        self._loaded: bool = False
        # Load on construction so .list_recent() works out of the box.
        self._load_if_present()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load_if_present(self) -> None:
        """Populate :attr:`_entries` from disk if the YAML exists.

        Silently treats a missing store as "fresh registry"; a malformed
        store falls back to an empty registry (the caller can call
        :meth:`save` to overwrite the bad file). This keeps the editor
        bootstrap path resilient — a corrupt recents list should never
        prevent the editor from starting.
        """
        if self._loaded:
            return
        self._loaded = True
        if not self.store_path.is_file():
            return
        try:
            raw = self.store_path.read_text(encoding="utf-8")
        except OSError:
            return
        try:
            data = yaml.safe_load(raw) or {}
        except yaml.YAMLError:
            return
        if not isinstance(data, dict):
            return
        recent = data.get("recent") or []
        if not isinstance(recent, list):
            return
        entries: list[RegistryEntry] = []
        for row in recent:
            try:
                entries.append(RegistryEntry.from_dict(row))
            except (TypeError, ValueError):
                continue
        self._entries = entries

    def save(self) -> None:
        """Persist the current recents list to :attr:`store_path`.

        Creates the parent directory if missing and uses an atomic
        rename so a crash mid-write never leaves a half-written YAML.
        """
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = yaml.safe_dump(
            {"recent": [e.to_dict() for e in self._entries]},
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
        tmp = self.store_path.with_suffix(self.store_path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(self.store_path)

    def reload(self) -> None:
        """Discard in-memory state and re-read from disk."""
        self._entries = []
        self._loaded = False
        self._load_if_present()

    # ── Queries ──────────────────────────────────────────────────────────

    def list_recent(self, limit: int = 10) -> list[RegistryEntry]:
        """Return up to *limit* most-recently-opened entries.

        Entries are returned newest-first; entries with malformed
        timestamps land at the end.

        Parameters
        ----------
        limit:
            Maximum number of entries to return. Must be ≥ 1.

        Raises
        ------
        TypeError
            If *limit* is not an int.
        ValueError
            If *limit* is < 1.
        """
        limit = validate_positive_int("limit", "list_recent", limit)
        return sorted(self._entries, key=_sort_key)[:limit]

    def entries(self) -> list[RegistryEntry]:
        """Return all entries (newest-first) without truncation."""
        return sorted(self._entries, key=_sort_key)

    def find(self, path: Path | str) -> Optional[RegistryEntry]:
        """Return the entry for *path*, or ``None`` if not registered."""
        target = self._canonical(path)
        for e in self._entries:
            if e.path == target:
                return e
        return None

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, path: object) -> bool:
        if not isinstance(path, (str, Path)):
            return False
        return self.find(path) is not None

    # ── Mutations ────────────────────────────────────────────────────────

    def register(self, project: Project) -> RegistryEntry:
        """Add or update the entry for *project*. Persists immediately.

        If the project is already registered (by canonical path), the
        existing entry's ``last_opened_at`` and ``name`` are refreshed
        in place. Otherwise a new entry is appended.

        Returns
        -------
        RegistryEntry
            The created or updated entry.
        """
        if not isinstance(project, Project):
            raise TypeError(
                f"register: expected Project; got {type(project).__name__}"
            )
        target = self._canonical(project.path)
        for e in self._entries:
            if e.path == target:
                e.last_opened_at = project.metadata.last_opened_at
                e.name = project.metadata.name
                self.save()
                return e
        entry = RegistryEntry(
            path=target,
            last_opened_at=project.metadata.last_opened_at,
            name=project.metadata.name,
        )
        self._entries.append(entry)
        self.save()
        return entry

    def unregister(self, path: Path | str) -> bool:
        """Drop the entry matching *path*. Persists immediately.

        Returns ``True`` iff an entry was removed.
        """
        target = self._canonical(path)
        before = len(self._entries)
        self._entries = [e for e in self._entries if e.path != target]
        removed = len(self._entries) != before
        if removed:
            self.save()
        return removed

    def clear(self) -> None:
        """Drop every entry and persist the empty list."""
        self._entries = []
        self.save()

    # ── High-level workflows ────────────────────────────────────────────

    def open(self, path: Path | str) -> Project:
        """Open the project at *path*, refresh its ``last_opened_at``.

        Walks upward via :func:`find_project_root` so *path* may point
        at any file or subdirectory inside the project. The opened
        project is then re-registered (or registered for the first
        time) and persisted.

        Raises
        ------
        FileNotFoundError
            If no project root can be located from *path*.
        ProjectFormatError
            If the manifest is malformed.
        """
        target = validate_path_like("path", "ProjectRegistry.open", path)
        root = find_project_root(target)
        if root is None:
            raise FileNotFoundError(
                f"ProjectRegistry.open: no project found at or above {target}"
            )
        project = read_project(root)
        project.touch_last_opened()
        self.register(project)
        return project

    def new(
        self,
        root: Path | str,
        name: str,
        *,
        description: str = "",
        scaffold: bool = True,
    ) -> Project:
        """Create a new project at *root* and register it.

        Thin wrapper around :meth:`Project.new` followed by
        :meth:`register`.
        """
        project = Project.new(
            root, name, description=description, scaffold=scaffold,
        )
        self.register(project)
        return project

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _canonical(path: Path | str) -> str:
        """Return the canonical absolute string form of *path*."""
        p = validate_path_like("path", "ProjectRegistry", path)
        try:
            return str(p.resolve(strict=False))
        except OSError:
            return str(p.absolute())


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_default_registry: ProjectRegistry | None = None


def get_default_registry() -> ProjectRegistry:
    """Return the process-wide singleton :class:`ProjectRegistry`.

    Lazy-constructed on first call so importing
    :mod:`slappyengine.projects` does not touch the user's home
    directory (relevant for headless CI / sandboxed builds). Tests
    that need a fresh registry should construct one directly with
    a temp ``store_path`` rather than mutating the singleton.
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ProjectRegistry()
    return _default_registry


def _reset_default_registry_for_tests() -> None:
    """Clear the cached singleton. Test-only escape hatch."""
    global _default_registry
    _default_registry = None
