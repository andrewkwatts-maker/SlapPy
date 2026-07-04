"""Prefab library — registry + on-disk loader for :class:`Prefab` entries.

Mirrors the :class:`slappyengine.ui.theme.user_themes.UserThemeStore`
pattern:

* :attr:`PrefabLibrary.BAKED_DIR` — read-only ``*.prefab.yaml`` shipped
  inside the wheel at ``python/slappyengine/prefabs/baked/``.
* :attr:`PrefabLibrary.USER_DIR` — writable location under
  ``~/.slappyengine/prefabs/``. :meth:`PrefabLibrary.bake_defaults`
  copies every baked file into the user directory on first use so
  library consumers can edit prefabs without touching the installed
  package.

The runtime library keeps prefabs in memory. YAML is loaded lazily via
:meth:`load_from_dir` and merged into the in-memory registry so the
same instance can host both baked and user-authored prefabs.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable

from slappyengine._validation import (
    validate_non_empty_str,
    validate_path_like,
)

from .prefab import CATEGORIES, Prefab

_LOG = logging.getLogger(__name__)


class PrefabLibrary:
    """In-memory registry of named :class:`Prefab` entries."""

    #: File suffix — kept public so tools that scan directories reuse it.
    SUFFIX: str = ".prefab.yaml"

    #: Read-only baked directory shipped inside the wheel.
    BAKED_DIR: Path = Path(__file__).parent / "baked"

    #: User-writable directory for edited / project-authored prefabs.
    USER_DIR: Path = Path.home() / ".slappyengine" / "prefabs"

    def __init__(self) -> None:
        self._entries: dict[str, Prefab] = {}

    # ------------------------------------------------------------------
    # Registry basics
    # ------------------------------------------------------------------

    def register(self, prefab: Prefab) -> Prefab:
        """Add or replace a :class:`Prefab` in the registry.

        Returns the registered prefab (the same object, for chaining).

        Raises
        ------
        TypeError
            If *prefab* is not a :class:`Prefab`.
        """
        if not isinstance(prefab, Prefab):
            raise TypeError(
                f"PrefabLibrary.register: prefab must be a Prefab; got "
                f"{type(prefab).__name__}"
            )
        self._entries[prefab.name] = prefab
        return prefab

    def get(self, name: str) -> Prefab | None:
        """Return the prefab registered under *name*, or ``None``."""
        if not isinstance(name, str) or not name:
            return None
        return self._entries.get(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._entries

    def __len__(self) -> int:
        return len(self._entries)

    def __iter__(self) -> Iterable[Prefab]:  # type: ignore[override]
        return iter(self._entries.values())

    def list_all(self) -> list[Prefab]:
        """Return every registered prefab, sorted by name."""
        return [self._entries[n] for n in sorted(self._entries.keys())]

    def list_names(self) -> list[str]:
        """Return the sorted list of registered prefab names."""
        return sorted(self._entries.keys())

    def list_by_category(self, category: str) -> list[Prefab]:
        """Return every registered prefab whose category matches.

        Raises
        ------
        ValueError
            If *category* is not one of :data:`prefab.CATEGORIES`.
        """
        cat = validate_non_empty_str(
            "category", "PrefabLibrary.list_by_category", category,
        )
        if cat not in CATEGORIES:
            raise ValueError(
                f"PrefabLibrary.list_by_category: category must be one of "
                f"{list(CATEGORIES)}; got {category!r}"
            )
        return [
            self._entries[n]
            for n in sorted(self._entries.keys())
            if self._entries[n].category == cat
        ]

    def clear(self) -> None:
        """Drop every registered prefab (test / hot-reload helper)."""
        self._entries.clear()

    # ------------------------------------------------------------------
    # Directory loading
    # ------------------------------------------------------------------

    def load_from_dir(self, path: Path | str) -> list[str]:
        """Walk *path* recursively, loading every ``*.prefab.yaml`` file.

        Silent-drops (with a warning) files that fail to parse so a
        single broken YAML never poisons the rest of the load.

        Returns
        -------
        list[str]
            The names of every prefab registered during this call, in
            file-system iteration order.
        """
        p = Path(validate_path_like(
            "path", "PrefabLibrary.load_from_dir", path,
        ))
        if not p.is_dir():
            raise FileNotFoundError(
                f"PrefabLibrary.load_from_dir: {p} is not a directory"
            )
        loaded: list[str] = []
        for yaml_path in sorted(p.glob(f"**/*{self.SUFFIX}")):
            try:
                text = yaml_path.read_text(encoding="utf-8")
                prefab = Prefab.from_yaml(text)
            except Exception as exc:
                _LOG.warning(
                    "PrefabLibrary.load_from_dir: dropping %s (%s: %s)",
                    yaml_path, type(exc).__name__, exc,
                )
                continue
            self.register(prefab)
            loaded.append(prefab.name)
        return loaded

    # ------------------------------------------------------------------
    # Baked / user directory bootstrap
    # ------------------------------------------------------------------

    def bake_defaults(
        self,
        user_dir: Path | str | None = None,
        baked_dir: Path | str | None = None,
    ) -> list[Path]:
        """Copy every baked prefab into the user directory (idempotent).

        Mirrors :meth:`UserThemeStore.ensure_defaults_copied`: existing
        user files are never overwritten so hand-edits survive across
        engine upgrades. Missing files are re-copied.

        Parameters
        ----------
        user_dir:
            Override the default :attr:`USER_DIR` (test-only).
        baked_dir:
            Override the default :attr:`BAKED_DIR` (test-only).

        Returns
        -------
        list[Path]
            Every path written during this call (empty when the user
            directory was already fully populated).
        """
        udir = self.USER_DIR if user_dir is None else Path(validate_path_like(
            "user_dir", "PrefabLibrary.bake_defaults", user_dir,
        ))
        bdir = self.BAKED_DIR if baked_dir is None else Path(validate_path_like(
            "baked_dir", "PrefabLibrary.bake_defaults", baked_dir,
        ))
        if not bdir.is_dir():
            return []
        udir.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for src in sorted(bdir.glob(f"*{self.SUFFIX}")):
            dest = udir / src.name
            if dest.exists():
                continue
            _atomic_copy(src, dest)
            written.append(dest)
        return written

    def load_baked(self) -> list[str]:
        """Register every baked prefab straight from the wheel directory.

        Convenience for consumers that don't need the user-editable
        copy — the editor spawn menu can call this at boot to expose
        the shipping palette without touching the user's file system.
        """
        if not self.BAKED_DIR.is_dir():
            return []
        return self.load_from_dir(self.BAKED_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _atomic_copy(source: Path, dest: Path) -> None:
    """Copy *source* → *dest* via a same-directory temp file + rename."""
    text = source.read_text(encoding="utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{dest.name}.", suffix=".tmp", dir=str(dest.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        os.replace(tmp_path, dest)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


__all__ = ["PrefabLibrary"]
