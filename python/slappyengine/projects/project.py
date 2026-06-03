"""``Project`` + ``ProjectMetadata`` dataclasses.

The :class:`Project` is the in-memory handle the editor passes around
once a project has been opened. It owns the on-disk root directory and
the metadata loaded from ``project.slap_proj``. Mutating
``self.metadata`` and calling :meth:`Project.save` round-trips the
manifest YAML; :meth:`Project.reload` re-reads it from disk (useful
after external edits to the manifest).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from slappyengine._validation import (
    validate_non_empty_str,
    validate_path_like,
    validate_str,
)


__all__ = ["Project", "ProjectMetadata"]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default cosmetic theme for new projects. The notebook-editor theme
#: registry is consulted at editor-launch time; if this name is unknown
#: the editor falls back to ``teengirl_notebook`` silently.
DEFAULT_THEME = "teengirl_notebook"


def _iso_utc_now() -> str:
    """Return current UTC time as an ISO 8601 string with trailing ``Z``.

    Matches the format produced by ``datetime.utcnow().isoformat() + 'Z'``
    in the legacy code path while remaining timezone-aware (the new
    Python 3.12+ idiom deprecates ``utcnow``).
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    # Strip the ``+00:00`` suffix in favour of a literal ``Z`` so the
    # written YAML matches the example in docs/api/projects.md.
    return now.isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# ProjectMetadata
# ---------------------------------------------------------------------------


@dataclass
class ProjectMetadata:
    """Manifest fields written to ``project.slap_proj``.

    Every field is a plain Python primitive so the dataclass round-trips
    cleanly through ``yaml.safe_dump`` / ``yaml.safe_load`` without any
    custom representers. ``created_at`` and ``last_opened_at`` are
    ISO 8601 strings rather than ``datetime`` objects for the same
    reason (PyYAML's default ``datetime`` representer emits timezone
    info inconsistently across versions).

    Parameters
    ----------
    name:
        Human-readable project name.
    version:
        Engine version string the project was created with (e.g.
        ``"0.3.0b0"``). Used by the editor to flag potential
        compatibility breaks; never coerced to a semver tuple here.
    created_at, last_opened_at:
        ISO 8601 UTC strings. Use :func:`_iso_utc_now` to mint new
        values so the format stays uniform.
    description:
        Optional one-paragraph project blurb.
    icon:
        Path to a project icon **relative to the project root**. Empty
        string means "use the engine default icon".
    default_theme:
        Editor theme name applied on open. Defaults to
        ``"teengirl_notebook"``.
    """

    name: str
    version: str
    created_at: str
    last_opened_at: str
    description: str = ""
    icon: str = ""
    default_theme: str = DEFAULT_THEME

    def __post_init__(self) -> None:
        """Validate manifest fields at construction.

        Raises
        ------
        TypeError
            If any field is not a ``str``.
        ValueError
            If ``name`` or ``version`` is empty.
        """
        self.name = validate_non_empty_str("name", "ProjectMetadata", self.name)
        self.version = validate_non_empty_str(
            "version", "ProjectMetadata", self.version,
        )
        self.created_at = validate_non_empty_str(
            "created_at", "ProjectMetadata", self.created_at,
        )
        self.last_opened_at = validate_non_empty_str(
            "last_opened_at", "ProjectMetadata", self.last_opened_at,
        )
        self.description = validate_str(
            "description", "ProjectMetadata", self.description,
        )
        self.icon = validate_str("icon", "ProjectMetadata", self.icon)
        self.default_theme = validate_non_empty_str(
            "default_theme", "ProjectMetadata", self.default_theme,
        )

    def to_dict(self) -> dict:
        """Return a YAML-safe dict snapshot of the metadata."""
        return {
            "name": self.name,
            "version": self.version,
            "created_at": self.created_at,
            "last_opened_at": self.last_opened_at,
            "description": self.description,
            "icon": self.icon,
            "default_theme": self.default_theme,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProjectMetadata":
        """Construct from a YAML-loaded dict.

        Unknown keys are ignored (forwards-compat); missing optional
        keys fall back to dataclass defaults. ``name`` and ``version``
        are required and raise ``KeyError`` if absent.
        """
        if not isinstance(data, dict):
            raise TypeError(
                "ProjectMetadata.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        return cls(
            name=data["name"],
            version=data["version"],
            created_at=data.get("created_at") or _iso_utc_now(),
            last_opened_at=data.get("last_opened_at") or _iso_utc_now(),
            description=data.get("description", "") or "",
            icon=data.get("icon", "") or "",
            default_theme=data.get("default_theme", DEFAULT_THEME)
            or DEFAULT_THEME,
        )


# ---------------------------------------------------------------------------
# Project
# ---------------------------------------------------------------------------


@dataclass
class Project:
    """In-memory project handle.

    A ``Project`` binds the on-disk *root* directory (the one containing
    ``project.slap_proj``) to its loaded :class:`ProjectMetadata`. The
    ``scenes_dir`` / ``assets_dir`` / ``scripts_dir`` helpers return
    canonical subdirectories under the root; they are not asserted to
    exist (so callers can construct a fresh ``Project`` *before*
    scaffolding it).

    Parameters
    ----------
    path:
        Project root directory (the one containing the manifest file).
    metadata:
        Loaded manifest content. Mutate then :meth:`save` to persist.
    """

    path: Path
    metadata: ProjectMetadata = field(repr=False)

    def __post_init__(self) -> None:
        # Coerce to ``Path`` so callers can pass a ``str``.
        self.path = validate_path_like("path", "Project", self.path)

    # ── Constructor helpers ───────────────────────────────────────────────

    @classmethod
    def new(
        cls,
        root: Path | str,
        name: str,
        *,
        version: str | None = None,
        description: str = "",
        scaffold: bool = True,
    ) -> "Project":
        """Create a new project at *root* with the given *name*.

        Writes ``project.slap_proj`` and (by default) scaffolds the
        default directory tree via :func:`scaffold_project`. The
        ``created_at`` / ``last_opened_at`` fields are minted with
        :func:`_iso_utc_now`.

        Parameters
        ----------
        root:
            Directory that will become the project root. Created if
            missing.
        name:
            Project name written to the manifest.
        version:
            Engine version string. Defaults to the running
            ``slappyengine.__version__``.
        description:
            Optional manifest description.
        scaffold:
            If ``True`` (default), creates the default ``scenes/``,
            ``assets/``, ``scripts/`` subdirectories plus seed files.
            Set ``False`` for a manifest-only project (e.g. tests).

        Raises
        ------
        TypeError
            If *root* or *name* is the wrong type.
        ValueError
            If *name* is empty.
        """
        root = validate_path_like("root", "Project.new", root)
        name = validate_non_empty_str("name", "Project.new", name)
        if version is None:
            # Lazy import so projects.py doesn't pull all of slappyengine
            # at module load (avoids cycles during package init).
            from slappyengine import __version__ as _engine_version
            version = _engine_version

        now = _iso_utc_now()
        metadata = ProjectMetadata(
            name=name,
            version=version,
            created_at=now,
            last_opened_at=now,
            description=description,
            icon="icon.png",
        )
        proj = cls(path=root, metadata=metadata)
        root.mkdir(parents=True, exist_ok=True)

        if scaffold:
            from .scaffolding import scaffold_project
            scaffold_project(proj)

        proj.save()
        return proj

    # ── Path helpers ──────────────────────────────────────────────────────

    @property
    def slap_proj_path(self) -> Path:
        """Path to the ``project.slap_proj`` manifest file."""
        from .format import PROJECT_FILE_NAME
        return self.path / PROJECT_FILE_NAME

    @property
    def scenes_dir(self) -> Path:
        """Canonical ``scenes/`` subdirectory (not required to exist)."""
        return self.path / "scenes"

    @property
    def assets_dir(self) -> Path:
        """Canonical ``assets/`` subdirectory (not required to exist)."""
        return self.path / "assets"

    @property
    def scripts_dir(self) -> Path:
        """Canonical ``scripts/`` subdirectory (not required to exist)."""
        return self.path / "scripts"

    @property
    def icon_path(self) -> Path | None:
        """Absolute path to the project icon, or ``None`` if unset.

        Resolves ``metadata.icon`` (which is *relative* to the project
        root) against ``self.path``. Returns ``None`` for empty / unset
        values so callers can fall back to a default cleanly.
        """
        if not self.metadata.icon:
            return None
        return self.path / self.metadata.icon

    # ── Persistence ───────────────────────────────────────────────────────

    def save(self) -> None:
        """Write ``project.slap_proj`` to disk under :attr:`path`.

        Creates the project root directory if it does not yet exist.
        """
        from .format import write_project
        write_project(self)

    def reload(self) -> None:
        """Re-read manifest fields from disk, overwriting :attr:`metadata`.

        Raises
        ------
        FileNotFoundError
            If the manifest no longer exists at :attr:`slap_proj_path`.
        ProjectFormatError
            If the manifest is malformed.
        """
        from .format import read_project
        fresh = read_project(self.path)
        self.metadata = fresh.metadata

    def touch_last_opened(self) -> None:
        """Set ``metadata.last_opened_at`` to "now" and persist.

        Called by the registry whenever a project is opened so the
        recents list stays sorted by recency.
        """
        self.metadata.last_opened_at = _iso_utc_now()
        self.save()
