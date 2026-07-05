"""``SceneRegistry`` — filesystem discovery + in-memory cache for scenes (FF3).

The registry mirrors :class:`slappyengine.prefabs.PrefabLibrary`'s
authoring pattern: a project directory holds ``*.scene.yaml`` files,
:meth:`discover` walks the tree, :meth:`load` and :meth:`save` do the
actual I/O via :class:`SceneFile`, and :meth:`list_all` returns the
in-memory registry sorted by name.

Design notes
~~~~~~~~~~~~
* :meth:`discover` returns absolute ``Path`` objects sorted for
  determinism. It never opens the files — it only walks the directory.
* :meth:`load` populates the in-memory dict so the editor can render
  the scene list without re-scanning the disk each frame.
* :meth:`save` mutates the in-memory dict, so subsequent
  :meth:`get` / :meth:`list_all` calls see the write immediately.
"""
from __future__ import annotations

import logging
from pathlib import Path

from slappyengine._validation import validate_path_like

from .scene import Scene, SceneValidationError
from .scene_file import SCENE_SUFFIX, SceneFile

_LOG = logging.getLogger(__name__)


class SceneRegistry:
    """In-memory registry of :class:`Scene` instances keyed by name.

    The registry is *not* a source of truth — the disk is. It caches
    what has been ``load``-ed so the editor can bulk-render scene lists
    without re-parsing every YAML file.
    """

    SUFFIX: str = SCENE_SUFFIX

    def __init__(self) -> None:
        self._entries: dict[str, Scene] = {}
        self._sources: dict[str, Path] = {}

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    @classmethod
    def discover(cls, scenes_dir: Path | str) -> list[Path]:
        """Return every ``*.scene.yaml`` under *scenes_dir*.

        Walks *scenes_dir* recursively. Paths are returned as absolute
        :class:`~pathlib.Path` objects sorted alphabetically for
        deterministic iteration order (matters for tests and CI-diffed
        editor snapshots).

        Raises
        ------
        FileNotFoundError
            If *scenes_dir* does not exist or is not a directory.
        """
        p = Path(validate_path_like(
            "scenes_dir", "SceneRegistry.discover", scenes_dir,
        ))
        if not p.exists():
            raise FileNotFoundError(
                f"SceneRegistry.discover: {p} does not exist"
            )
        if not p.is_dir():
            raise FileNotFoundError(
                f"SceneRegistry.discover: {p} is not a directory"
            )
        candidates: list[Path] = []
        for entry in p.rglob("*"):
            # ``str(entry).endswith(SUFFIX)`` handles the double-suffix
            # case (``foo.scene.yaml``) correctly — ``entry.suffix`` on
            # its own would only see ``.yaml``.
            if entry.is_file() and str(entry).endswith(cls.SUFFIX):
                candidates.append(entry.resolve())
        candidates.sort(key=lambda x: str(x))
        return candidates

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def load(self, path: Path | str) -> Scene:
        """Read a scene from *path* and register it under its ``name``.

        The registered entry replaces any previous scene with the same
        name — matches :class:`~slappyengine.prefabs.PrefabLibrary`'s
        semantics.

        Returns
        -------
        Scene
            The loaded scene (same object as ``registry.get(scene.name)``).

        Raises
        ------
        FileNotFoundError
            If *path* does not exist.
        SceneValidationError
            If the file cannot be parsed.
        """
        scene = SceneFile.read(path)
        self._entries[scene.name] = scene
        self._sources[scene.name] = Path(path).resolve()
        return scene

    def load_dir(self, scenes_dir: Path | str) -> list[str]:
        """Discover + load every scene under *scenes_dir*.

        Returns the names of every scene registered during this call
        (in discovery order). Malformed files are logged and skipped so
        one broken YAML never poisons the rest of the load.
        """
        loaded: list[str] = []
        for path in self.discover(scenes_dir):
            try:
                scene = self.load(path)
            except SceneValidationError as exc:
                _LOG.warning(
                    "SceneRegistry.load_dir: dropping %s (%s: %s)",
                    path, type(exc).__name__, exc,
                )
                continue
            loaded.append(scene.name)
        return loaded

    def save(self, scene: Scene, path: Path | str) -> Path:
        """Write *scene* to *path* atomically and register it.

        Returns the resolved on-disk path so callers can log or diff
        their writes without re-normalising.
        """
        if not isinstance(scene, Scene):
            raise TypeError(
                f"SceneRegistry.save: scene must be a Scene; "
                f"got {type(scene).__name__}"
            )
        final = SceneFile.write(scene, path)
        self._entries[scene.name] = scene
        self._sources[scene.name] = final.resolve()
        return final

    # ------------------------------------------------------------------
    # In-memory lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> Scene | None:
        """Return the scene registered under *name*, or ``None``."""
        if not isinstance(name, str) or not name:
            return None
        return self._entries.get(name)

    def source_of(self, name: str) -> Path | None:
        """Return the on-disk path *name* was loaded from, if any."""
        if not isinstance(name, str) or not name:
            return None
        return self._sources.get(name)

    def list_all(self) -> list[str]:
        """Return every registered scene name, sorted alphabetically."""
        return sorted(self._entries.keys())

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._entries

    def clear(self) -> None:
        """Drop every registered scene (test / hot-reload helper)."""
        self._entries.clear()
        self._sources.clear()


__all__ = ["SceneRegistry"]
