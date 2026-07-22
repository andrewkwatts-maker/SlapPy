"""``ProjectRegistry`` — lightweight multi-project tracker.

This module implements a *simpler, more general* project registry than
:mod:`pharos_engine.projects.registry`. Where the latter is tightly
coupled to the ``project.slap_proj`` manifest format (walk-upward,
read/write scaffolded directory trees), this registry only cares about
the minimum surface a startup prompt needs:

* a display **name**,
* a **path** on disk (any directory the user chose),
* an ISO 8601 **last_opened** timestamp,
* the **engine_version** the project was last opened with,
* an optional free-form **notes** string.

The registry file lives at ``~/.pharos_engine/projects.yaml`` and is
autoritative for the "recent projects" list surfaced by the notebook
startup prompt + project-registry side panel. It is deliberately
kept separate from the ``ProjectRegistry`` singleton in
:mod:`pharos_engine.projects` so both layers can evolve independently
without a schema fight.

Persistence uses ``pyyaml`` when available, falling back to a JSON
encoder embedded in a YAML-ish wrapper so the file remains readable
under CI images that skip the ``[editor]`` extra.

The registry is designed to be resilient — a missing or corrupt file
is silently treated as an empty registry so the editor never fails to
boot because someone hand-edited the YAML.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_optional_str,
    validate_path_like,
    validate_positive_int,
)


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "ProjectRegistry",
    "RegisteredProject",
    "get_default_registry",
    "iso_utc_now",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _default_registry_path() -> Path:
    """Return the default on-disk location of the YAML file."""
    return Path.home() / ".pharos_engine" / "projects.yaml"


#: Backwards-compat constant — callers that want the default path
#: as a non-callable can import this. Resolved on first access.
DEFAULT_REGISTRY_PATH = _default_registry_path


def iso_utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string with ``Z`` suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _engine_version_default() -> str:
    """Return ``pharos_engine.__version__`` with graceful fallback."""
    try:
        import pharos_engine as _sp
        v = getattr(_sp, "__version__", None)
        if isinstance(v, str) and v:
            return v
    except Exception:
        pass
    return "unknown"


def _yaml_dumps(payload: dict) -> str:
    """Serialise *payload* to YAML text, falling back to JSON when pyyaml is absent."""
    try:
        import yaml  # type: ignore[import-not-found]
        return yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    except Exception:
        # JSON is a strict subset of YAML 1.2 so the fallback file is
        # still parseable by a real YAML reader later.
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)


def _yaml_loads(text: str) -> Any:
    """Deserialise *text* — YAML if pyyaml is available, else JSON."""
    try:
        import yaml  # type: ignore[import-not-found]
        return yaml.safe_load(text)
    except ImportError:
        try:
            return json.loads(text)
        except Exception:
            return None
    except Exception:
        # Malformed YAML — return None so caller falls back to empty.
        return None


def _sort_key_recent(project: "RegisteredProject") -> tuple[int, str]:
    """Return a sort key that orders newest-first.

    Malformed timestamps sink to the bottom (``0`` timestamp) and are
    then ordered lexicographically by name so the fallback ordering
    remains deterministic.
    """
    try:
        stamp = project.last_opened
        if stamp.endswith("Z"):
            stamp = stamp[:-1] + "+00:00"
        ts = datetime.fromisoformat(stamp)
        return (-int(ts.timestamp()), project.name)
    except (TypeError, ValueError, AttributeError):
        return (0, project.name)


# ---------------------------------------------------------------------------
# RegisteredProject dataclass
# ---------------------------------------------------------------------------


@dataclass
class RegisteredProject:
    """One row in a :class:`ProjectRegistry`.

    Attributes
    ----------
    name:
        Display name shown in the startup prompt + registry panel.
        Must be non-empty; case-preserved.
    path:
        Absolute path to the project directory. Passed through
        :class:`pathlib.Path` — callers may hand in strings and get
        proper ``Path`` values back.
    last_opened:
        ISO 8601 UTC timestamp (``YYYY-MM-DDTHH:MM:SSZ``). Defaults to
        :func:`iso_utc_now` so freshly-added entries sort to the top.
    engine_version:
        Version string the project was last opened with. Defaults to
        the current ``pharos_engine.__version__`` so callers rarely
        need to supply it explicitly.
    notes:
        Optional free-form description — surfaces as a tooltip on
        the registry panel row.
    """

    name: str
    path: Path
    last_opened: str = field(default_factory=iso_utc_now)
    engine_version: str = field(default_factory=_engine_version_default)
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        # Coerce path first so validation error messages reference
        # a proper Path, then confirm the name is non-empty.
        if not isinstance(self.path, Path):
            self.path = Path(self.path)
        validate_non_empty_str("name", "RegisteredProject", self.name)
        if not isinstance(self.last_opened, str) or not self.last_opened:
            self.last_opened = iso_utc_now()
        if not isinstance(self.engine_version, str) or not self.engine_version:
            self.engine_version = _engine_version_default()
        if self.notes is not None and not isinstance(self.notes, str):
            raise TypeError(
                "RegisteredProject: notes must be str or None; "
                f"got {type(self.notes).__name__}"
            )

    # ── Serialisation ────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Return a JSON/YAML-friendly dict representation."""
        return {
            "name": self.name,
            "path": str(self.path),
            "last_opened": self.last_opened,
            "engine_version": self.engine_version,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "RegisteredProject":
        """Construct a project from a decoded YAML/JSON dict.

        Raises
        ------
        TypeError, ValueError
            If *data* is not a dict or is missing required fields.
        """
        if not isinstance(data, dict):
            raise TypeError(
                "RegisteredProject.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        name = data.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                "RegisteredProject.from_dict: missing or empty 'name' field"
            )
        path_raw = data.get("path")
        if not isinstance(path_raw, str) or not path_raw:
            raise ValueError(
                "RegisteredProject.from_dict: missing or empty 'path' field"
            )
        return cls(
            name=name,
            path=Path(path_raw),
            last_opened=data.get("last_opened") or iso_utc_now(),
            engine_version=(
                data.get("engine_version") or _engine_version_default()
            ),
            notes=data.get("notes"),
        )


# ---------------------------------------------------------------------------
# ProjectRegistry
# ---------------------------------------------------------------------------


class ProjectRegistry:
    """Persistent list of user-registered projects.

    Behaves like a small database:

    * :meth:`add` inserts or updates by name.
    * :meth:`remove` drops a project by name.
    * :meth:`touch` bumps ``last_opened`` to *now*.
    * :meth:`list_all` returns everything (newest-first).
    * :meth:`list_recent` returns the top *N* newest.

    Persistence is via :meth:`save` / :meth:`load`; the constructor
    auto-loads on start so ``list_recent()`` works out of the box.

    Parameters
    ----------
    path:
        Optional override for the YAML store. Defaults to
        ``~/.pharos_engine/projects.yaml``.

    Notes
    -----
    Corrupt / missing YAML files are silently treated as *empty
    registry*. This keeps the editor's boot path resilient — a
    hand-edited YAML that no longer parses will drop the user's
    recents list, not their editor.
    """

    def __init__(self, path: Path | str | None = None) -> None:
        if path is None:
            self._store_path: Path = _default_registry_path()
        else:
            self._store_path = validate_path_like(
                "path", "ProjectRegistry", path,
            )
        self._projects: list[RegisteredProject] = []
        self._loaded: bool = False
        # Auto-load so callers can hit list_recent() immediately.
        self.load()

    # ── Public properties ────────────────────────────────────────────

    @property
    def store_path(self) -> Path:
        """The on-disk YAML file backing the registry."""
        return self._store_path

    def __len__(self) -> int:
        return len(self._projects)

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        return self._find(name) is not None

    def __iter__(self):
        return iter(list(self._projects))

    # ── Load / save ──────────────────────────────────────────────────

    def load(self) -> None:
        """Populate the registry from disk (idempotent).

        A missing file is treated as "empty registry" (no error). A
        corrupt or non-dict payload is silently discarded — the caller
        can call :meth:`save` afterwards to overwrite the bad file.
        """
        self._loaded = True
        self._projects = []
        try:
            if not self._store_path.is_file():
                return
        except OSError:
            return
        try:
            raw = self._store_path.read_text(encoding="utf-8")
        except OSError:
            return
        data = _yaml_loads(raw)
        if not isinstance(data, dict):
            return
        rows = data.get("projects")
        if not isinstance(rows, list):
            return
        for row in rows:
            try:
                self._projects.append(RegisteredProject.from_dict(row))
            except (TypeError, ValueError):
                # Skip individual malformed rows so one bad entry
                # doesn't wipe the whole recents list.
                continue

    def save(self) -> None:
        """Persist the registry to disk via atomic-rename.

        Creates the parent directory if missing. Writes to a ``.tmp``
        file first and swaps it into place so a crash mid-write never
        leaves a half-written YAML.
        """
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "projects": [p.to_dict() for p in self._projects],
        }
        text = _yaml_dumps(payload)
        tmp = self._store_path.with_suffix(self._store_path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._store_path)

    def reload(self) -> None:
        """Drop in-memory state and re-read from disk."""
        self._projects = []
        self._loaded = False
        self.load()

    # ── Mutations ────────────────────────────────────────────────────

    def add(self, project: RegisteredProject) -> RegisteredProject:
        """Add *project*, replacing any existing entry with the same name.

        Persists immediately. Returns the stored project (which may
        replace an older entry with the same name).
        """
        if not isinstance(project, RegisteredProject):
            raise TypeError(
                "ProjectRegistry.add: project must be a RegisteredProject; "
                f"got {type(project).__name__}"
            )
        existing = self._find(project.name)
        if existing is not None:
            self._projects.remove(existing)
        self._projects.append(project)
        self.save()
        return project

    def remove(self, name: str) -> bool:
        """Drop the entry named *name*. Persists immediately.

        Returns ``True`` iff an entry was removed.
        """
        validate_non_empty_str("name", "ProjectRegistry.remove", name)
        existing = self._find(name)
        if existing is None:
            return False
        self._projects.remove(existing)
        self.save()
        return True

    def touch(self, name: str) -> bool:
        """Bump ``last_opened`` on the entry named *name* to now.

        Persists immediately. Returns ``True`` iff an entry was found
        and updated.
        """
        validate_non_empty_str("name", "ProjectRegistry.touch", name)
        existing = self._find(name)
        if existing is None:
            return False
        existing.last_opened = iso_utc_now()
        self.save()
        return True

    def clear(self) -> None:
        """Drop every entry and persist the empty registry."""
        self._projects = []
        self.save()

    # ── Queries ──────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[RegisteredProject]:
        """Return the entry named *name*, or ``None`` if not found."""
        validate_non_empty_str("name", "ProjectRegistry.get", name)
        return self._find(name)

    def list_all(self) -> list[RegisteredProject]:
        """Return every entry in newest-first order."""
        return sorted(self._projects, key=_sort_key_recent)

    def list_recent(self, limit: int = 8) -> list[RegisteredProject]:
        """Return the top *limit* newest entries.

        Parameters
        ----------
        limit:
            Maximum entries to return. Must be a positive int.

        Raises
        ------
        TypeError, ValueError
            Propagated from ``validate_positive_int``.
        """
        limit = validate_positive_int(
            "limit", "ProjectRegistry.list_recent", limit,
        )
        return self.list_all()[:limit]

    # ── Internals ────────────────────────────────────────────────────

    def _find(self, name: str) -> Optional[RegisteredProject]:
        for p in self._projects:
            if p.name == name:
                return p
        return None


# ---------------------------------------------------------------------------
# Singleton accessor — mirrors ``pharos_engine.projects.get_default_registry``.
# ---------------------------------------------------------------------------

_default_registry: ProjectRegistry | None = None


def get_default_registry() -> ProjectRegistry:
    """Return the process-wide singleton :class:`ProjectRegistry`.

    Lazy-constructed on first call so importing this module doesn't
    touch the user's home directory (relevant for headless CI /
    sandboxed builds).
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = ProjectRegistry()
    return _default_registry


def _reset_default_registry_for_tests() -> None:
    """Clear the cached singleton. Test-only escape hatch."""
    global _default_registry
    _default_registry = None
