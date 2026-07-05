"""``SceneFile`` — atomic disk I/O for ``.scene.yaml`` files (FF3).

Wraps :class:`slappyengine.scenes.scene.Scene` with a stable disk contract:

* :meth:`SceneFile.read` — parse a ``.scene.yaml`` file; malformed input
  raises :class:`SceneValidationError` with the source line preserved
  when the YAML parser reports it.
* :meth:`SceneFile.write` — write via a temp file + ``os.replace`` so a
  crash mid-write can never leave the target half-populated. The
  previous file (if any) survives until the atomic rename swaps in
  the new one.
* :meth:`SceneFile.validate` — one-shot schema check that returns the
  list of problems found (empty when the scene is valid). Used by the
  editor to surface warnings without raising.

Design notes
~~~~~~~~~~~~
* Suffix is fixed at ``.scene.yaml`` so scene registry glob patterns can
  distinguish them from generic ``*.yaml`` config files.
* :meth:`write` fsyncs the temp file before renaming so the OS commits
  the bytes to disk before we swap. On Windows ``os.replace`` provides
  the same atomicity guarantee ``rename`` has on POSIX.
* :meth:`validate` never raises — it accumulates every issue it finds
  so the editor can render all of them in one pass instead of one
  fix / test cycle per bug.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from slappyengine._validation import validate_path_like

from .scene import (
    SCHEMA_VERSION,
    Scene,
    SceneValidationError,
    _KNOWN_KINDS,
)


#: Canonical suffix for scene files.
SCENE_SUFFIX: str = ".scene.yaml"


class SceneFile:
    """Static disk-I/O helper for scene YAML files.

    Every method is a ``@classmethod`` — the class holds no state. The
    class-based dispatch just keeps the public API discoverable
    (``SceneFile.read`` reads better than a bare ``scene_read``
    module-level function in editor autocomplete).
    """

    SUFFIX: str = SCENE_SUFFIX

    @classmethod
    def read(cls, path: Path | str) -> Scene:
        """Parse *path* and return a :class:`Scene`.

        Raises
        ------
        FileNotFoundError
            If *path* does not exist.
        SceneValidationError
            If the file suffix is wrong, the YAML is malformed, or the
            decoded payload does not match the scene schema. When the
            YAML parser reports a line number it is copied onto the
            exception's ``line`` attribute.
        """
        p = Path(validate_path_like("path", "SceneFile.read", path))
        if not cls._has_scene_suffix(p):
            raise SceneValidationError(
                f"SceneFile.read: path must end with {cls.SUFFIX!r}; "
                f"got {str(path)!r}"
            )
        if not p.exists():
            raise FileNotFoundError(f"SceneFile.read: {p} does not exist")
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise SceneValidationError(
                f"SceneFile.read: cannot read {p} ({exc})"
            ) from exc
        return Scene.from_yaml(text)

    @classmethod
    def write(cls, scene: Scene, path: Path | str) -> Path:
        """Serialise *scene* and write it to *path* atomically.

        Writes to a temp file in the same directory as *path*, fsyncs it,
        then renames over the target. If the process dies before the
        rename completes, the original file at *path* (if any) is
        untouched — the temp file is orphaned but never surfaces as
        *path*.

        Returns
        -------
        Path
            The final, resolved path the scene was written to.

        Raises
        ------
        TypeError
            If *scene* is not a :class:`Scene`.
        SceneValidationError
            If *path*'s suffix is not ``.scene.yaml``.
        OSError
            If the write, fsync, or rename fails.
        """
        if not isinstance(scene, Scene):
            raise TypeError(
                f"SceneFile.write: scene must be a Scene; "
                f"got {type(scene).__name__}"
            )
        p = Path(validate_path_like("path", "SceneFile.write", path))
        if not cls._has_scene_suffix(p):
            raise SceneValidationError(
                f"SceneFile.write: path must end with {cls.SUFFIX!r}; "
                f"got {str(path)!r}"
            )
        p.parent.mkdir(parents=True, exist_ok=True)
        text = scene.to_yaml()

        # Write to a sibling temp file, fsync, then atomic-rename.
        # ``delete=False`` so we can close it and hand the path to
        # ``os.replace`` — Windows can't rename an open file.
        tmp_fd, tmp_path = tempfile.mkstemp(
            prefix=p.stem + ".", suffix=".tmp", dir=str(p.parent),
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                try:
                    os.fsync(fh.fileno())
                except OSError:
                    # Some virtualised filesystems (e.g. tmpfs / WSL
                    # bind mounts) refuse fsync; the atomic-rename
                    # step still guarantees write-or-nothing.
                    pass
            os.replace(tmp_path, p)
        except Exception:
            # Best-effort cleanup so we don't leave the temp behind.
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return p

    @classmethod
    def validate(cls, scene: Scene) -> list[str]:
        """Return the list of problems found in *scene*.

        Empty list means the scene is valid. This is a schema-level
        pass — it checks structural invariants that :meth:`Scene.add_entity`
        also enforces, plus a few cross-entity invariants (unique ids,
        prefab_ref sanity) that only make sense at whole-scene scope.

        Never raises — that's the point of this helper. Editors call
        it to render every issue at once instead of piecemeal.
        """
        problems: list[str] = []
        if not isinstance(scene, Scene):
            problems.append(
                f"SceneFile.validate: scene must be a Scene; "
                f"got {type(scene).__name__}"
            )
            return problems
        if not isinstance(scene.name, str) or not scene.name:
            problems.append("scene.name must be a non-empty str")
        if not isinstance(scene.entities, list):
            problems.append("scene.entities must be a list")
            return problems
        seen_ids: set[str] = set()
        for i, ent in enumerate(scene.entities):
            path = f"entities[{i}]"
            if not isinstance(ent, dict):
                problems.append(f"{path}: not a dict")
                continue
            for key in ("id", "kind", "position", "params"):
                if key not in ent:
                    problems.append(f"{path}: missing required key {key!r}")
            eid = ent.get("id")
            if isinstance(eid, str) and eid:
                if eid in seen_ids:
                    problems.append(f"{path}: duplicate id {eid!r}")
                seen_ids.add(eid)
            kind = ent.get("kind")
            prefab_ref = ent.get("prefab_ref")
            if isinstance(kind, str) and kind:
                if kind not in _KNOWN_KINDS and not prefab_ref:
                    problems.append(
                        f"{path}: kind {kind!r} is not one of "
                        f"{list(_KNOWN_KINDS)} and no prefab_ref supplied"
                    )
            pos = ent.get("position")
            if pos is not None and (
                not hasattr(pos, "__len__") or len(pos) != 2
            ):
                problems.append(
                    f"{path}: position must be a 2-sequence; got {pos!r}"
                )
        if not isinstance(scene.layers, list):
            problems.append("scene.layers must be a list")
        if not isinstance(scene.metadata, dict):
            problems.append("scene.metadata must be a dict")
        return problems

    @classmethod
    def _has_scene_suffix(cls, path: Path) -> bool:
        """Return ``True`` if ``str(path)`` ends with :attr:`SUFFIX`."""
        return str(path).endswith(cls.SUFFIX)


__all__ = [
    "SCENE_SUFFIX",
    "SceneFile",
    "SCHEMA_VERSION",
]
