"""User-editable theme storage — baked vs user directories.

Pharos Engine ships every built-in :class:`ThemeSpec` as a YAML file
baked into the wheel (``python/pharos_engine/ui/theme/themes/_baked/``).
On first launch a :class:`UserThemeStore` copies each baked file into
``~/.pharos_engine/themes/`` so users can open, edit, and save the YAML
freely without touching the installed package.

The user directory *wins*: :meth:`UserThemeStore.load_theme` prefers the
user-side file over the baked file when both exist. Missing baked
themes are re-copied on every launch (never overwriting existing user
files) so nothing goes missing after ``pip install --upgrade``.

Two-line usage::

    store = UserThemeStore()
    store.ensure_defaults_copied()          # idempotent — safe on every boot
    theme = store.load_theme("teengirl_notebook")  # user file preferred

File format
-----------
Each file is ``<name>.theme.yaml`` and contains the output of
:meth:`pharos_editor.ui.theme.ThemeSpec.to_yaml`. Round-trip is
lossless (palette, semantic tokens, spacing / radius / transition /
z-index scales, fonts, panel frames, panel decor, background shader,
metadata) so users edit the same fields the engine ships.

Safety
------
* :meth:`save_theme` uses temp-file + atomic rename — a crash mid-write
  never leaves a partially-written YAML for the next launch to trip on.
* :meth:`ensure_defaults_copied` and :meth:`revert_to_baked` also route
  through the atomic path so shared network drives and antivirus
  scanners see complete files only.
* Corrupt YAML on the user side raises :class:`UserThemeError` with the
  offending path — the caller can surface a "reset to default" dialog
  instead of silently falling back.
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from pharos_engine._validation import (
    validate_non_empty_str,
    validate_path_like,
)

from .theme_spec import ThemeSpec


class UserThemeError(Exception):
    """Raised when a user-side theme file is missing, corrupt, or malformed."""


class UserThemeStore:
    """Manages user-editable theme files under ``~/.pharos_engine/themes/``.

    Themes live in two locations:

    1. **Baked** (read-only):
       ``python/pharos_engine/ui/theme/themes/_baked/`` — shipped inside
       the wheel; the canonical source of every built-in theme.
    2. **User** (read/write):
       ``~/.pharos_engine/themes/`` — copied from baked on first launch.
       Users edit files here to customise the shipping themes.

    Instances are cheap; a fresh :class:`UserThemeStore` per boot is
    the intended usage.

    Parameters
    ----------
    user_dir:
        Override the default ``~/.pharos_engine/themes/`` location — used
        by tests to isolate the on-disk state per case.
    baked_dir:
        Override the packaged baked directory (also test-only; production
        code always accepts the class default).
    """

    #: The user-editable directory. Users may edit any file inside.
    USER_DIR: Path = Path.home() / ".pharos_engine" / "themes"

    #: The read-only baked directory shipped inside the wheel.
    BAKED_DIR: Path = Path(__file__).parent / "themes" / "_baked"

    #: File-name suffix; kept as a public constant so the CLI can reuse it.
    SUFFIX: str = ".theme.yaml"

    def __init__(
        self,
        user_dir: Path | str | None = None,
        baked_dir: Path | str | None = None,
    ) -> None:
        if user_dir is None:
            self._user_dir = self.USER_DIR
        else:
            self._user_dir = Path(validate_path_like(
                "user_dir", "UserThemeStore", user_dir,
            ))
        if baked_dir is None:
            self._baked_dir = self.BAKED_DIR
        else:
            self._baked_dir = Path(validate_path_like(
                "baked_dir", "UserThemeStore", baked_dir,
            ))

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    @property
    def user_dir(self) -> Path:
        """Return the resolved user directory."""
        return self._user_dir

    @property
    def baked_dir(self) -> Path:
        """Return the resolved baked directory."""
        return self._baked_dir

    # ------------------------------------------------------------------
    # First-launch bootstrap
    # ------------------------------------------------------------------

    def ensure_defaults_copied(self) -> list[str]:
        """Copy every baked theme into the user directory if missing.

        Called on every engine boot. Creates :attr:`user_dir` when it
        does not exist. Never overwrites an existing user file — the
        user's edits are always sacrosanct. Missing baked themes on
        the user side (e.g. after a wheel upgrade that added a new
        built-in) are re-copied.

        Returns
        -------
        list[str]
            The names of themes copied during this call (in insertion
            order). Empty when every user file was already present.
        """
        self._user_dir.mkdir(parents=True, exist_ok=True)
        copied: list[str] = []
        for baked_path in self._iter_baked_paths():
            user_path = self._user_dir / baked_path.name
            if user_path.exists():
                continue
            self._atomic_copy(baked_path, user_path)
            copied.append(self._name_from_path(baked_path))
        return copied

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_baked(self) -> list[str]:
        """Return the sorted names of every baked theme."""
        return sorted(self._name_from_path(p) for p in self._iter_baked_paths())

    def list_user(self) -> list[str]:
        """Return the sorted names of every user-side theme.

        Returns an empty list when :attr:`user_dir` does not exist —
        this is the pre-first-launch state and the caller should follow
        up with :meth:`ensure_defaults_copied`.
        """
        if not self._user_dir.is_dir():
            return []
        return sorted(
            self._name_from_path(p) for p in self._iter_user_paths()
        )

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load_theme(self, name: str) -> ThemeSpec:
        """Return the :class:`ThemeSpec` for *name*.

        The user-side file is preferred; when it is missing the baked
        file is used. Raises :class:`UserThemeError` when neither
        exists or when the on-disk YAML is malformed.
        """
        theme_name = validate_non_empty_str(
            "name", "UserThemeStore.load_theme", name,
        )
        user_path = self._user_path_for(theme_name)
        if user_path.exists():
            return self._load_yaml(user_path)
        baked_path = self._baked_path_for(theme_name)
        if baked_path.exists():
            return self._load_yaml(baked_path)
        raise UserThemeError(
            f"UserThemeStore.load_theme: no theme named {theme_name!r} "
            f"(searched {user_path} and {baked_path})"
        )

    def save_theme(self, theme: ThemeSpec, name: str | None = None) -> Path:
        """Write *theme* to the user directory as ``<name>.theme.yaml``.

        Parameters
        ----------
        theme:
            The :class:`ThemeSpec` to serialise.
        name:
            Override the on-disk name. Defaults to ``theme.name`` which
            is the common case; supply this when the user has renamed
            the theme in a save-as flow.

        Returns
        -------
        pathlib.Path
            The path of the newly-written YAML file.
        """
        if not isinstance(theme, ThemeSpec):
            raise TypeError(
                "UserThemeStore.save_theme: theme must be a ThemeSpec; "
                f"got {type(theme).__name__}"
            )
        theme_name = name if name is not None else theme.name
        theme_name = validate_non_empty_str(
            "name", "UserThemeStore.save_theme", theme_name,
        )
        self._user_dir.mkdir(parents=True, exist_ok=True)
        user_path = self._user_path_for(theme_name)
        payload = theme.to_yaml()
        self._atomic_write_text(user_path, payload)
        return user_path

    # ------------------------------------------------------------------
    # Reset + edit-detection
    # ------------------------------------------------------------------

    def revert_to_baked(self, name: str) -> Path:
        """Overwrite the user file for *name* with the baked version.

        Raises :class:`UserThemeError` when no baked file exists for
        that name (e.g. the theme was authored by the user and never
        shipped in the wheel).
        """
        theme_name = validate_non_empty_str(
            "name", "UserThemeStore.revert_to_baked", name,
        )
        baked_path = self._baked_path_for(theme_name)
        if not baked_path.exists():
            raise UserThemeError(
                f"UserThemeStore.revert_to_baked: no baked theme named "
                f"{theme_name!r} (looked at {baked_path})"
            )
        self._user_dir.mkdir(parents=True, exist_ok=True)
        user_path = self._user_path_for(theme_name)
        self._atomic_copy(baked_path, user_path)
        return user_path

    def is_edited(self, name: str) -> bool:
        """Return ``True`` when the user file differs from the baked file.

        Comparison is byte-for-byte on the raw YAML — a whitespace-only
        edit still registers as edited. Returns ``False`` when the user
        file is missing (the baked file is the effective content).
        Returns ``False`` when the baked file is missing (a user-authored
        theme has no baked baseline to diverge from).
        """
        theme_name = validate_non_empty_str(
            "name", "UserThemeStore.is_edited", name,
        )
        user_path = self._user_path_for(theme_name)
        baked_path = self._baked_path_for(theme_name)
        if not user_path.exists() or not baked_path.exists():
            return False
        try:
            user_bytes = user_path.read_bytes()
            baked_bytes = baked_path.read_bytes()
        except OSError:
            return False
        return user_bytes != baked_bytes

    # ------------------------------------------------------------------
    # Optional file watcher
    # ------------------------------------------------------------------

    def watch_user_dir(
        self, on_change: Callable[[Path], None] | None = None,
    ) -> Any:
        """Watch :attr:`user_dir` for edits, calling *on_change* per event.

        Requires the ``watchdog`` extra (``pip install watchdog``).
        When watchdog is missing this returns ``None`` — the caller
        should treat that as "watch not available" and skip live reload.

        Returns
        -------
        watchdog.observers.Observer | None
            A *started* observer. The caller is responsible for calling
            ``observer.stop()`` / ``observer.join()`` at shutdown.
        """
        try:
            from watchdog.events import FileSystemEventHandler  # type: ignore[import-not-found]
            from watchdog.observers import Observer  # type: ignore[import-not-found]
        except ImportError:
            return None

        self._user_dir.mkdir(parents=True, exist_ok=True)

        class _Handler(FileSystemEventHandler):  # type: ignore[misc]
            def __init__(self, cb: Callable[[Path], None] | None) -> None:
                super().__init__()
                self._cb = cb

            def on_modified(self, event: Any) -> None:  # noqa: D401
                if getattr(event, "is_directory", False):
                    return
                src = getattr(event, "src_path", None)
                if src is None or not str(src).endswith(UserThemeStore.SUFFIX):
                    return
                if self._cb is not None:
                    try:
                        self._cb(Path(src))
                    except Exception:
                        pass

            on_created = on_modified

        observer = Observer()
        observer.schedule(_Handler(on_change), str(self._user_dir), recursive=False)
        observer.start()
        return observer

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _iter_baked_paths(self) -> list[Path]:
        """Return every ``*.theme.yaml`` under :attr:`baked_dir`, sorted."""
        if not self._baked_dir.is_dir():
            return []
        return sorted(
            p for p in self._baked_dir.iterdir()
            if p.is_file() and p.name.endswith(self.SUFFIX)
        )

    def _iter_user_paths(self) -> list[Path]:
        """Return every ``*.theme.yaml`` under :attr:`user_dir`, sorted."""
        if not self._user_dir.is_dir():
            return []
        return sorted(
            p for p in self._user_dir.iterdir()
            if p.is_file() and p.name.endswith(self.SUFFIX)
        )

    def _name_from_path(self, path: Path) -> str:
        """Return the bare theme name from ``foo.theme.yaml``."""
        stem = path.name
        if stem.endswith(self.SUFFIX):
            return stem[: -len(self.SUFFIX)]
        return path.stem

    def _user_path_for(self, name: str) -> Path:
        return self._user_dir / f"{name}{self.SUFFIX}"

    def _baked_path_for(self, name: str) -> Path:
        return self._baked_dir / f"{name}{self.SUFFIX}"

    def _load_yaml(self, path: Path) -> ThemeSpec:
        """Read and parse a single ``*.theme.yaml`` file into a ThemeSpec."""
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise UserThemeError(
                f"UserThemeStore: unable to read {path}: {exc}"
            ) from exc
        try:
            return ThemeSpec.from_yaml(text)
        except Exception as exc:
            raise UserThemeError(
                f"UserThemeStore: corrupt theme file {path}: {exc}"
            ) from exc

    @staticmethod
    def _atomic_write_text(target: Path, text: str) -> None:
        """Write *text* to *target* atomically (temp + rename)."""
        target.parent.mkdir(parents=True, exist_ok=True)
        # Use a NamedTemporaryFile in the same directory so os.replace
        # is guaranteed atomic on POSIX + Windows (same filesystem).
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    # fsync is best-effort on some networked filesystems.
                    pass
            os.replace(tmp_path, target)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @classmethod
    def _atomic_copy(cls, source: Path, dest: Path) -> None:
        """Copy *source* → *dest* atomically via a temp file in dest.parent."""
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as exc:
            raise UserThemeError(
                f"UserThemeStore: unable to read baked theme {source}: {exc}"
            ) from exc
        cls._atomic_write_text(dest, text)


def bake_default_themes(baked_dir: Path | str | None = None) -> list[Path]:
    """Serialise every diary-family theme into the baked directory.

    Used at build time (or once-off during development) to regenerate
    the ``_baked/`` YAML files. Safe to call at runtime too — the write
    path is atomic and the baked directory is only read by
    :class:`UserThemeStore`, so re-baking during a running editor is a
    no-op for the active theme.

    Parameters
    ----------
    baked_dir:
        Override the destination (test-only; production leaves this
        ``None`` so the shipping ``_baked/`` directory is targeted).

    Returns
    -------
    list[pathlib.Path]
        The paths of every written file (in insertion order matching the
        diary-family rollout in :mod:`pharos_editor.ui.theme.themes`).
    """
    # Local import so this module does not force the theme content to
    # load whenever ``UserThemeStore`` is imported.
    from .themes import (
        BULLET_JOURNAL,
        COTTAGECORE_GARDEN,
        COZY_DIARY,
        KAWAII_PLANNER,
        SCRAPBOOK_SUMMER,
        TEENGIRL_NOTEBOOK,
    )

    if baked_dir is None:
        target = UserThemeStore.BAKED_DIR
    else:
        target = Path(validate_path_like(
            "baked_dir", "bake_default_themes", baked_dir,
        ))
    target.mkdir(parents=True, exist_ok=True)

    themes: tuple[ThemeSpec, ...] = (
        TEENGIRL_NOTEBOOK,
        COZY_DIARY,
        BULLET_JOURNAL,
        SCRAPBOOK_SUMMER,
        COTTAGECORE_GARDEN,
        KAWAII_PLANNER,
    )

    written: list[Path] = []
    for theme in themes:
        path = target / f"{theme.name}{UserThemeStore.SUFFIX}"
        UserThemeStore._atomic_write_text(path, theme.to_yaml())
        written.append(path)
    return written


__all__ = [
    "UserThemeError",
    "UserThemeStore",
    "bake_default_themes",
]
