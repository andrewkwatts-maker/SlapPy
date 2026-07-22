"""``ProjectSceneBridge`` — glue between V2 project_registry and FF3 scenes.

Both :mod:`pharos_engine.project_registry` (V2, a lightweight recents list
of :class:`RegisteredProject` rows) and :mod:`pharos_engine.scenes` (FF3,
a YAML scene serialisation layer with :class:`Scene`, :class:`SceneFile`
and :class:`SceneRegistry`) predate this bridge and are treated as
read-only sibling modules. This module composes them without editing
either.

The bridge exposes a small API purpose-built for the notebook editor:

* :class:`ProjectSceneIndex` — an immutable snapshot of a project's
  scene directory (name -> path, plus default_scene / last_opened).
* :class:`ProjectSceneBridge` — the workhorse: index / save / load /
  list / delete + default scene marker persisted in the project's
  ``project.yaml``.
* :func:`create_project_with_scene` — factory that hands the caller a
  registered project *plus* an initial saved scene in one shot.

Layout on disk for one project::

    <project_path>/
        project.yaml             # V2 project manifest (default_scene lives here)
        scenes/
            level_1.scene.yaml   # FF3 SceneFile format
            boss.scene.yaml

Design notes
~~~~~~~~~~~~
* ``project.yaml`` is *this bridge's* manifest — it is not the same
  file as :mod:`pharos_engine.projects`' ``project.slap_proj`` (that lives
  in the other project subsystem). We only touch a couple of keys
  (``default_scene``, ``last_opened_scene``) so we never conflict with
  hand-authored top-level fields.
* Scene collisions on :meth:`save_scene` are resolved silently by
  appending ``_N`` before the ``.scene.yaml`` suffix. The final on-disk
  name is available via the returned ``Path.stem.split('.')[0]``.
* The bridge does *not* mutate the underlying V2 registry — it only
  reads the :class:`RegisteredProject` path. Callers who want the
  scene write to be reflected in the recents list should call
  :meth:`ProjectRegistry.touch` themselves.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from pharos_engine._validation import validate_non_empty_str
from pharos_engine.project_registry import (
    ProjectRegistry,
    RegisteredProject,
    get_default_registry,
)
from pharos_engine.scenes import (
    SCENE_SUFFIX,
    Scene,
    SceneFile,
    SceneRegistry,
)


__all__ = [
    "PROJECT_MANIFEST_NAME",
    "SCENES_SUBDIR",
    "ProjectSceneBridge",
    "ProjectSceneIndex",
    "create_project_with_scene",
]


#: Manifest file inside a project directory holding bridge-owned keys.
PROJECT_MANIFEST_NAME: str = "project.yaml"

#: Subdirectory (relative to the project path) where scene YAML lives.
SCENES_SUBDIR: str = "scenes"


# ---------------------------------------------------------------------------
# ProjectSceneIndex
# ---------------------------------------------------------------------------


@dataclass
class ProjectSceneIndex:
    """Snapshot of a project's scene directory + manifest cursor.

    Attributes
    ----------
    project_name:
        Display name of the underlying :class:`RegisteredProject`.
    scenes:
        Mapping of scene *stem name* (the filename minus the
        ``.scene.yaml`` suffix) to its resolved absolute path.
    default_scene:
        Stem name recorded as the project's default in ``project.yaml``,
        or ``None`` if unset. Not guaranteed to be a key in
        :attr:`scenes` — a deleted scene can leave a dangling default
        that :meth:`ProjectSceneBridge.get_default_scene` gracefully
        returns ``None`` for.
    last_opened:
        Stem name of the most-recently-opened scene, or ``None``. This
        is a bridge-side breadcrumb; callers may safely ignore it.
    """

    project_name: str
    scenes: dict[str, Path] = field(default_factory=dict)
    default_scene: Optional[str] = None
    last_opened: Optional[str] = None

    def __len__(self) -> int:
        return len(self.scenes)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self.scenes

    def names(self) -> list[str]:
        """Return sorted scene stem names."""
        return sorted(self.scenes.keys())


# ---------------------------------------------------------------------------
# YAML I/O — piggy-back on project_registry's fallback logic
# ---------------------------------------------------------------------------


def _yaml_dumps(payload: dict) -> str:
    """Serialise *payload* to YAML text with JSON as a fallback."""
    try:
        import yaml  # type: ignore[import-not-found]

        return yaml.safe_dump(
            payload,
            sort_keys=False,
            allow_unicode=True,
            default_flow_style=False,
        )
    except Exception:
        return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False)


def _yaml_loads(text: str) -> object:
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
        return None


def _stem_of(path: Path) -> str:
    """Return the scene name (drop ``.scene.yaml``) for *path*."""
    fname = path.name
    if fname.endswith(SCENE_SUFFIX):
        return fname[: -len(SCENE_SUFFIX)]
    # Best-effort fallback: strip whatever the last suffix happens to be.
    return path.stem


# ---------------------------------------------------------------------------
# ProjectSceneBridge
# ---------------------------------------------------------------------------


class ProjectSceneBridge:
    """Bridge one :class:`RegisteredProject` to its FF3 scene directory.

    Instances are cheap — the constructor only touches disk to read the
    project manifest and cache the default / last-opened scene name.

    Parameters
    ----------
    project:
        The V2 :class:`RegisteredProject` whose ``path`` we treat as the
        project root. The ``scenes/`` subdirectory is created lazily on
        the first :meth:`save_scene` call, so freshly-registered
        projects don't need any pre-existing layout.

    Notes
    -----
    * :meth:`index_scenes` re-walks the directory each call — it is the
      canonical source of truth. In-memory state on the bridge itself
      is limited to the default/last-opened cursors read from
      ``project.yaml``.
    * :meth:`save_scene` writes through :class:`SceneFile` so the
      file layout matches what the FF3 :class:`SceneRegistry` expects.
    """

    def __init__(self, project: RegisteredProject) -> None:
        if not isinstance(project, RegisteredProject):
            raise TypeError(
                "ProjectSceneBridge: project must be a RegisteredProject; "
                f"got {type(project).__name__}"
            )
        self._project: RegisteredProject = project
        self._project_path: Path = Path(project.path)
        self._scenes_dir: Path = self._project_path / SCENES_SUBDIR
        self._manifest_path: Path = self._project_path / PROJECT_MANIFEST_NAME
        self._default_scene: Optional[str] = None
        self._last_opened: Optional[str] = None
        self._read_manifest()

    # ── Properties ────────────────────────────────────────────────────

    @property
    def project(self) -> RegisteredProject:
        """The underlying :class:`RegisteredProject`."""
        return self._project

    @property
    def project_path(self) -> Path:
        """The on-disk project root."""
        return self._project_path

    @property
    def scenes_dir(self) -> Path:
        """The ``<project>/scenes/`` directory (may not exist yet)."""
        return self._scenes_dir

    @property
    def manifest_path(self) -> Path:
        """The ``<project>/project.yaml`` file (may not exist yet)."""
        return self._manifest_path

    # ── Manifest I/O ─────────────────────────────────────────────────

    def _read_manifest(self) -> None:
        """Populate the default / last-opened cursors from disk.

        Missing / malformed manifests are treated as "no cursor set" —
        we never raise from the constructor because the notebook
        editor's boot path opens every registered project's bridge on
        startup.
        """
        self._default_scene = None
        self._last_opened = None
        try:
            if not self._manifest_path.is_file():
                return
        except OSError:
            return
        try:
            raw = self._manifest_path.read_text(encoding="utf-8")
        except OSError:
            return
        data = _yaml_loads(raw)
        if not isinstance(data, dict):
            return
        d = data.get("default_scene")
        if isinstance(d, str) and d:
            self._default_scene = d
        lo = data.get("last_opened_scene")
        if isinstance(lo, str) and lo:
            self._last_opened = lo

    def _write_manifest(self, extra: Optional[dict] = None) -> None:
        """Persist the manifest atomically, preserving unknown keys.

        Reads the current manifest (if any), merges the bridge-owned
        keys into whatever the caller has stashed there, and writes the
        result via a temp file + ``Path.replace``. That way projects
        that carry extra top-level metadata (e.g. an author's rendering
        preset) don't lose it on the next :meth:`set_default_scene`
        call.
        """
        payload: dict = {}
        # Read current manifest so we preserve unknown keys.
        try:
            if self._manifest_path.is_file():
                raw = self._manifest_path.read_text(encoding="utf-8")
                data = _yaml_loads(raw)
                if isinstance(data, dict):
                    payload = dict(data)
        except OSError:
            payload = {}
        if self._default_scene is not None:
            payload["default_scene"] = self._default_scene
        elif "default_scene" in payload:
            del payload["default_scene"]
        if self._last_opened is not None:
            payload["last_opened_scene"] = self._last_opened
        if extra:
            for k, v in extra.items():
                payload[k] = v
        self._project_path.mkdir(parents=True, exist_ok=True)
        text = _yaml_dumps(payload)
        tmp = self._manifest_path.with_suffix(
            self._manifest_path.suffix + ".tmp"
        )
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self._manifest_path)

    # ── Discovery ────────────────────────────────────────────────────

    def index_scenes(self) -> ProjectSceneIndex:
        """Walk the ``scenes/`` subdirectory and return a fresh index.

        A missing ``scenes/`` directory is treated as "empty project" —
        we return an empty index rather than raising, matching the
        FF3 :class:`SceneRegistry` behaviour of "no scenes here".
        """
        scenes: dict[str, Path] = {}
        if self._scenes_dir.exists() and self._scenes_dir.is_dir():
            try:
                paths = SceneRegistry.discover(self._scenes_dir)
            except FileNotFoundError:
                paths = []
            for p in paths:
                stem = _stem_of(p)
                scenes[stem] = p.resolve()
        return ProjectSceneIndex(
            project_name=self._project.name,
            scenes=scenes,
            default_scene=self._default_scene,
            last_opened=self._last_opened,
        )

    def list_scene_names(self) -> list[str]:
        """Return the scene stem names, sorted alphabetically."""
        return self.index_scenes().names()

    # ── Save / load ──────────────────────────────────────────────────

    def _resolve_collision(self, name: str) -> str:
        """Return an unused stem based on *name* (append ``_N`` on collision)."""
        base = name
        candidate = base
        counter = 1
        # Scan existing files, not the in-memory index — collision must
        # be resolved against the actual filesystem to avoid overwriting
        # a scene written by another process between index passes.
        while (self._scenes_dir / f"{candidate}{SCENE_SUFFIX}").exists():
            candidate = f"{base}_{counter}"
            counter += 1
        return candidate

    def save_scene(self, scene: Scene, name: Optional[str] = None) -> Path:
        """Write *scene* under ``scenes/<name>.scene.yaml`` and return its path.

        If *name* is ``None`` the bridge uses ``scene.name``. When the
        target file already exists a ``_N`` suffix is appended to
        avoid clobbering — the write always succeeds under a fresh
        stem. The scene object itself is left untouched (in particular
        its ``.name`` attribute is *not* rewritten to match the
        collision-resolved stem — that would violate the caller's
        expectation that ``scene.name`` is stable).

        Raises
        ------
        TypeError
            If *scene* is not a :class:`Scene`.
        ValueError
            If *name* is provided but empty / not a string.
        """
        if not isinstance(scene, Scene):
            raise TypeError(
                "ProjectSceneBridge.save_scene: scene must be a Scene; "
                f"got {type(scene).__name__}"
            )
        if name is None:
            stem_input = scene.name
        else:
            stem_input = validate_non_empty_str(
                "name", "ProjectSceneBridge.save_scene", name,
            )
        stem_input = _sanitise_stem(stem_input)
        self._scenes_dir.mkdir(parents=True, exist_ok=True)
        final_stem = self._resolve_collision(stem_input)
        target = self._scenes_dir / f"{final_stem}{SCENE_SUFFIX}"
        written = SceneFile.write(scene, target)
        # Track the write as the last-opened scene for convenience.
        self._last_opened = final_stem
        try:
            self._write_manifest()
        except OSError:
            # A failing manifest write shouldn't invalidate the scene
            # write itself — the caller can retry set_default_scene()
            # later if the disk was momentarily full.
            pass
        return written

    def load_scene(self, name: str) -> Scene:
        """Load the scene stored under ``scenes/<name>.scene.yaml``.

        Updates the ``last_opened`` cursor in ``project.yaml`` on
        success. Raises :class:`FileNotFoundError` if no such scene
        exists so callers can distinguish "not found" from
        "corrupt" (which surfaces as
        :class:`~pharos_engine.scenes.SceneValidationError`).
        """
        validate_non_empty_str("name", "ProjectSceneBridge.load_scene", name)
        target = self._scenes_dir / f"{name}{SCENE_SUFFIX}"
        if not target.exists():
            raise FileNotFoundError(
                f"ProjectSceneBridge.load_scene: no scene {name!r} "
                f"at {target}"
            )
        scene = SceneFile.read(target)
        self._last_opened = name
        try:
            self._write_manifest()
        except OSError:
            pass
        return scene

    def delete_scene(self, name: str) -> bool:
        """Remove ``scenes/<name>.scene.yaml``; returns ``True`` if it existed.

        Also clears the default / last-opened cursors when they point
        at the freshly-deleted scene so the manifest never dangles.
        """
        validate_non_empty_str(
            "name", "ProjectSceneBridge.delete_scene", name,
        )
        target = self._scenes_dir / f"{name}{SCENE_SUFFIX}"
        if not target.exists():
            return False
        try:
            target.unlink()
        except OSError:
            return False
        changed = False
        if self._default_scene == name:
            self._default_scene = None
            changed = True
        if self._last_opened == name:
            self._last_opened = None
            changed = True
        if changed:
            try:
                self._write_manifest()
            except OSError:
                pass
        return True

    # ── Default scene ────────────────────────────────────────────────

    def set_default_scene(self, name: str) -> None:
        """Persist *name* as the project's default scene in ``project.yaml``.

        The name is not required to exist on disk — callers can pre-
        assign a default before creating the scene (useful when a
        template pipeline writes the manifest before the scene YAML).
        """
        validate_non_empty_str(
            "name", "ProjectSceneBridge.set_default_scene", name,
        )
        self._default_scene = name
        self._write_manifest()

    def clear_default_scene(self) -> None:
        """Drop the recorded default scene, if any."""
        self._default_scene = None
        self._write_manifest()

    def get_default_scene(self) -> Optional[Scene]:
        """Load the recorded default scene, or ``None`` when unavailable.

        Returns ``None`` when no default is set *or* when the recorded
        default no longer exists on disk (the manifest can dangle if
        the file was deleted by hand). Any other error propagates so
        callers see corruption immediately.
        """
        if self._default_scene is None:
            return None
        target = self._scenes_dir / f"{self._default_scene}{SCENE_SUFFIX}"
        if not target.exists():
            return None
        return SceneFile.read(target)

    @property
    def default_scene_name(self) -> Optional[str]:
        """Return the recorded default scene stem, or ``None``."""
        return self._default_scene

    @property
    def last_opened_scene_name(self) -> Optional[str]:
        """Return the last-opened scene stem, or ``None``."""
        return self._last_opened


# ---------------------------------------------------------------------------
# Stem sanitisation
# ---------------------------------------------------------------------------


_INVALID_STEM_CHARS = re.compile(r"[^A-Za-z0-9_.\-]+")


def _sanitise_stem(name: str) -> str:
    """Coerce *name* into a filesystem-safe scene stem.

    * Replaces runs of forbidden characters with an underscore.
    * Strips leading dots so ``.scene.yaml`` never accidentally
      becomes a hidden file.
    * Guarantees a non-empty result — falls back to ``"scene"`` when
      the coerced string collapses to empty.
    """
    if not isinstance(name, str):
        raise TypeError(
            "ProjectSceneBridge: scene name must be a str; "
            f"got {type(name).__name__}"
        )
    cleaned = _INVALID_STEM_CHARS.sub("_", name).strip("._")
    if not cleaned:
        return "scene"
    return cleaned


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_project_with_scene(
    project: RegisteredProject,
    initial_scene: Scene,
    *,
    registry: Optional[ProjectRegistry] = None,
    set_as_default: bool = True,
) -> ProjectSceneBridge:
    """Register *project*, save *initial_scene*, and return a bridge.

    Convenience factory for the notebook editor's "new project" flow:
    it (1) hands the project row to the V2 :class:`ProjectRegistry`
    (creating the singleton on demand when *registry* is omitted), (2)
    writes *initial_scene* into the project's ``scenes/`` directory,
    and (3) records that scene as the project's default when
    ``set_as_default=True`` (the default).

    Parameters
    ----------
    project:
        The :class:`RegisteredProject` row to register. Its ``path``
        must exist — the caller is responsible for :func:`Path.mkdir`
        before invoking this helper.
    initial_scene:
        The starter :class:`Scene` to persist under ``scenes/``.
    registry:
        Optional :class:`ProjectRegistry` to insert into. When ``None``
        the process-wide singleton returned by
        :func:`get_default_registry` is used.
    set_as_default:
        When ``True`` (default) the freshly-written scene stem is
        recorded as the project's default in ``project.yaml``.

    Returns
    -------
    ProjectSceneBridge
        A ready-to-use bridge already pointing at the initial scene.
    """
    if not isinstance(project, RegisteredProject):
        raise TypeError(
            "create_project_with_scene: project must be a RegisteredProject; "
            f"got {type(project).__name__}"
        )
    if not isinstance(initial_scene, Scene):
        raise TypeError(
            "create_project_with_scene: initial_scene must be a Scene; "
            f"got {type(initial_scene).__name__}"
        )
    reg = registry if registry is not None else get_default_registry()
    reg.add(project)
    bridge = ProjectSceneBridge(project)
    written = bridge.save_scene(initial_scene)
    if set_as_default:
        stem = _stem_of(written)
        bridge.set_default_scene(stem)
    return bridge
