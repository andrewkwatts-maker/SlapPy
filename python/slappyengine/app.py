"""Ergonomic top-level application API — the "2-line pip install and render" surface.

The user's directive (2026-07-04 HH1 sprint):

    A developer should be able to ``pip install slappyengine`` and, in two or
    three lines of Python, spin up a window, display a 3D model, and drive it
    from lambdas or bind their own ``begin`` / ``tick`` / ``end`` callbacks.

This module fulfils that directive with three public classes and three
module-level convenience functions:

* :class:`App`         — the runtime shell (window, tick loop, hooks, handles).
* :class:`AppConfig`   — dataclass config with YAML round-trip.
* :class:`ModelHandle` — mutable transform + trace log for a loaded model.
* :class:`TextureHandle`  — asset handle for a bitmap/texture.
* :class:`LightHandle`    — spawned light entity handle.
* :class:`CameraHandle`   — active-camera handle.
* :func:`launch`       — one-shot module-level entry point.
* :func:`load_model` / :func:`load_texture` — implicit-global-app helpers.

Design goals
------------

* **No hard GPU dependency at import time.** The renderer is soft-imported;
  when unavailable (or when ``config.enable_gpu`` is ``False``), the tick
  loop runs *headless* — hooks still fire at ``target_fps``, the trace log
  still records transforms, tests still pass in CI.

* **Every option lives in YAML.** ``AppConfig`` obeys the user's cardinal
  rule ("YAML config for all numeric defaults"): every field has a default,
  ``to_yaml()`` / ``from_yaml()`` / ``from_yaml_file()`` are the canonical
  serialisation surface, and if the caller passes ``config_path=`` to a
  missing file, a fully-commented default YAML is written there.

* **Editor stays optional.** ``enable_editor=False`` by default. Python-only
  projects never touch DearPyGui.

The module is intentionally free of *any* import from the big subpackages
(``softbody``, ``fluid``, ``physics``, ``physics2``, ``ui``,
``visual_scripting``, ``post_process``) so it can be imported cheaply and
tested in isolation.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from typing import Any, Callable, Iterable

try:  # PyYAML is a runtime dep of the engine already (see config.py)
    import yaml as _yaml
    _HAS_YAML = True
except Exception:  # pragma: no cover - PyYAML is always installed in-repo
    _yaml = None
    _HAS_YAML = False


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Handles
# ---------------------------------------------------------------------------


@dataclass
class ModelHandle:
    """Mutable transform + trace log for a loaded model.

    Backed by :class:`App` — the app records every transform mutation into
    :attr:`App.trace` so headless tests can assert on movement without a
    live renderer.

    Attributes
    ----------
    path
        The original asset path passed to :meth:`App.load_model`.
    position
        ``(x, y, z)`` world position. Defaults to ``(0, 0, 0)``.
    rotation
        ``(rx, ry, rz)`` Euler radians (XYZ convention).
    scale
        ``(sx, sy, sz)``. Defaults to unit scale.
    visible
        Renderer skip flag when ``False``.
    id
        Monotonic id assigned by the owning app.
    """

    path: str = ""
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    visible: bool = True
    id: int = -1

    # HH1↔HH4↔HH5 integration payload. Populated by
    # :func:`slappyengine.app_integration.bridge_load_model`; stays
    # ``None`` for stub loads so existing HH1 tests never trip on it.
    mesh: Any = field(default=None, repr=False, compare=False)
    material: Any = field(default=None, repr=False, compare=False)
    bounding_box: tuple[tuple[float, float, float], tuple[float, float, float]] | None = field(
        default=None, repr=False, compare=False
    )

    # Owner ref — set by App.load_model. Not part of the public repr.
    _app: "App | None" = field(default=None, repr=False, compare=False)
    _destroyed: bool = field(default=False, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Transform mutation
    # ------------------------------------------------------------------
    def move_to(self, x: float, y: float, z: float) -> "ModelHandle":
        """Set absolute position. Returns ``self`` for chaining."""
        self.position = (float(x), float(y), float(z))
        self._log("move_to", self.position)
        return self

    def move_by(self, dx: float, dy: float, dz: float) -> "ModelHandle":
        """Translate by delta. Returns ``self``."""
        x, y, z = self.position
        self.position = (x + float(dx), y + float(dy), z + float(dz))
        self._log("move_by", self.position)
        return self

    def rotate_by(self, dx: float, dy: float, dz: float) -> "ModelHandle":
        """Rotate by Euler delta radians. Returns ``self``."""
        rx, ry, rz = self.rotation
        self.rotation = (rx + float(dx), ry + float(dy), rz + float(dz))
        self._log("rotate_by", self.rotation)
        return self

    def rotate_to(self, rx: float, ry: float, rz: float) -> "ModelHandle":
        """Set absolute Euler rotation. Returns ``self``."""
        self.rotation = (float(rx), float(ry), float(rz))
        self._log("rotate_to", self.rotation)
        return self

    def scale_to(self, sx: float, sy: float, sz: float) -> "ModelHandle":
        """Set absolute scale. Returns ``self``."""
        self.scale = (float(sx), float(sy), float(sz))
        self._log("scale_to", self.scale)
        return self

    def set_visible(self, visible: bool) -> "ModelHandle":
        """Toggle visibility. Returns ``self``."""
        self.visible = bool(visible)
        self._log("set_visible", self.visible)
        return self

    def destroy(self) -> None:
        """Remove from the owning app. Idempotent."""
        if self._destroyed:
            return
        self._destroyed = True
        if self._app is not None:
            self._app._remove_model(self)

    # ------------------------------------------------------------------
    def transform_matrix(self):
        """Return the 4x4 model matrix as a numpy float32 array.

        Delegates to :mod:`slappyengine.app_integration` so the app
        module stays free of a numpy import at the top level. Returns
        ``None`` on any soft-import failure.
        """
        try:
            from slappyengine.app_integration import handle_transform_matrix

            return handle_transform_matrix(self)
        except Exception:  # pragma: no cover - only hit in stripped envs
            return None

    # ------------------------------------------------------------------
    def _log(self, op: str, value: Any) -> None:
        if self._app is not None:
            self._app.trace.append(("model", self.id, op, value))


@dataclass
class TextureHandle:
    """Handle to a loaded texture / bitmap asset."""

    path: str = ""
    id: int = -1
    width: int = 0
    height: int = 0
    channels: int = 4

    _app: "App | None" = field(default=None, repr=False, compare=False)


@dataclass
class LightHandle:
    """Spawned light entity handle."""

    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    color: tuple[float, float, float] = (1.0, 1.0, 1.0)
    intensity: float = 1.0
    id: int = -1

    _app: "App | None" = field(default=None, repr=False, compare=False)

    def move_to(self, x: float, y: float, z: float) -> "LightHandle":
        self.position = (float(x), float(y), float(z))
        if self._app is not None:
            self._app.trace.append(("light", self.id, "move_to", self.position))
        return self

    def set_color(self, r: float, g: float, b: float) -> "LightHandle":
        self.color = (float(r), float(g), float(b))
        return self

    def set_intensity(self, intensity: float) -> "LightHandle":
        self.intensity = float(intensity)
        return self


@dataclass
class CameraHandle:
    """Active-camera handle."""

    position: tuple[float, float, float] = (0.0, 0.0, 5.0)
    look_at: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fov_deg: float = 60.0
    near: float = 0.1
    far: float = 1000.0
    id: int = -1

    _app: "App | None" = field(default=None, repr=False, compare=False)

    def move_to(self, x: float, y: float, z: float) -> "CameraHandle":
        self.position = (float(x), float(y), float(z))
        if self._app is not None:
            self._app.trace.append(("camera", self.id, "move_to", self.position))
        return self

    def aim_at(self, x: float, y: float, z: float) -> "CameraHandle":
        self.look_at = (float(x), float(y), float(z))
        return self


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class AppConfig:
    """Runtime configuration for :class:`App`.

    Every field carries a default so a bare ``AppConfig()`` is always
    valid. Serialise/deserialise via :meth:`to_yaml` / :meth:`from_yaml`.
    """

    # Window
    window_title: str = "SlapPyEngine"
    window_size: tuple[int, int] = (1280, 720)
    fullscreen: bool = False
    vsync: bool = True
    resizable: bool = True

    # Render loop
    target_fps: int = 60
    fixed_timestep: bool = False
    max_frames: int = 0          # 0 == unlimited
    clear_color: tuple[float, float, float, float] = (0.1, 0.1, 0.15, 1.0)
    msaa_samples: int = 4
    background_alpha: float = 1.0

    # GPU / renderer
    enable_gpu: bool = True
    renderer_backend: str = "auto"      # auto / wgpu / stub / headless
    power_preference: str = "high_performance"
    max_lights: int = 32
    shadow_map_resolution: int = 2048

    # Editor / tooling
    enable_editor: bool = False
    enable_hot_reload: bool = False
    enable_telemetry: bool = True
    enable_audio: bool = False

    # Paths
    project_root: Path | None = None
    assets_dir: str = "assets"
    log_level: str = "INFO"

    # Camera defaults (used when App.spawn_camera has no explicit args)
    default_camera_position: tuple[float, float, float] = (0.0, 0.0, 5.0)
    default_camera_look_at: tuple[float, float, float] = (0.0, 0.0, 0.0)
    default_fov_deg: float = 60.0
    default_near: float = 0.1
    default_far: float = 1000.0

    # ------------------------------------------------------------------
    # YAML round-trip
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict snapshot (paths → str, tuples → list)."""
        raw = asdict(self)
        # Path objects need string coercion for a clean YAML dump.
        if raw.get("project_root") is not None:
            raw["project_root"] = str(raw["project_root"])
        return raw

    def to_yaml(self) -> str:
        """Serialise to a YAML string."""
        if not _HAS_YAML:  # pragma: no cover
            raise RuntimeError("PyYAML is required for AppConfig.to_yaml()")
        return _yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "AppConfig":
        """Parse a YAML string.

        Missing keys fall back to dataclass defaults, unknown keys are ignored
        (with a warning), and tuple-shaped fields are re-tupled from lists.
        """
        if not _HAS_YAML:  # pragma: no cover
            raise RuntimeError("PyYAML is required for AppConfig.from_yaml()")
        raw = _yaml.safe_load(text) or {}
        return cls._from_dict(raw)

    @classmethod
    def from_yaml_file(cls, path: str | Path) -> "AppConfig":
        """Load YAML from a file path."""
        p = Path(path)
        return cls.from_yaml(p.read_text(encoding="utf-8"))

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> "AppConfig":
        allowed = {f.name for f in fields(cls)}
        cleaned: dict[str, Any] = {}
        for key, value in raw.items():
            if key not in allowed:
                logger.warning("AppConfig: ignoring unknown key %r", key)
                continue
            cleaned[key] = value
        # Coerce tuple-shaped fields back to tuple (YAML gives lists).
        for tuple_field in (
            "window_size",
            "clear_color",
            "default_camera_position",
            "default_camera_look_at",
        ):
            if tuple_field in cleaned and isinstance(cleaned[tuple_field], list):
                cleaned[tuple_field] = tuple(cleaned[tuple_field])
        # Coerce project_root to Path.
        if cleaned.get("project_root") is not None:
            cleaned["project_root"] = Path(cleaned["project_root"])
        return cls(**cleaned)

    # ------------------------------------------------------------------
    def write_commented_default(self, path: str | Path) -> Path:
        """Write a *fully commented* default YAML template to ``path``.

        Every field is prefixed with ``# `` so the file loads as an empty
        dict but each option is visible + editable inline.
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        default = type(self)()  # fresh defaults, don't leak caller mutations
        raw = default.to_dict()
        lines = [
            "# SlapPyEngine AppConfig — auto-generated defaults.",
            "# Uncomment and edit any field to override the built-in default.",
            "# Every field maps 1:1 to slappyengine.app.AppConfig.",
            "",
        ]
        for key, value in raw.items():
            rendered = _yaml.safe_dump({key: value}, sort_keys=False).rstrip()
            for sub in rendered.splitlines():
                lines.append(f"# {sub}")
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p


# ---------------------------------------------------------------------------
# Renderer stub — soft-imported so tests never require wgpu
# ---------------------------------------------------------------------------


class _StubRenderer:
    """Logging-only renderer used when GPU is unavailable or disabled.

    Matches the tiny surface :class:`App` calls into: ``begin_frame``,
    ``draw_model``, ``end_frame``, ``close``. The real wgpu renderer plugs
    in via HH4.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.frame_index = 0
        self.log: list[tuple[str, Any]] = []

    def begin_frame(self) -> None:
        self.log.append(("begin_frame", self.frame_index))

    def draw_model(self, handle: ModelHandle) -> None:
        self.log.append(
            (
                "draw_model",
                {
                    "id": handle.id,
                    "path": handle.path,
                    "position": handle.position,
                    "rotation": handle.rotation,
                    "scale": handle.scale,
                    "visible": handle.visible,
                },
            )
        )
        logger.debug(
            "would render model %s at %s",
            handle.path,
            handle.position,
        )

    def end_frame(self) -> None:
        self.log.append(("end_frame", self.frame_index))
        self.frame_index += 1

    def close(self) -> None:
        self.log.append(("close", None))


def _try_real_renderer(config: AppConfig):  # pragma: no cover
    """Soft-import the real renderer, fall back to stub on any failure.

    HH4 will wire the wgpu context here. Until then this always returns
    ``None`` and the caller uses :class:`_StubRenderer`.
    """
    if not config.enable_gpu:
        return None
    if config.renderer_backend in ("stub", "headless"):
        return None
    try:
        # Intentional soft-fail: the real backend is not yet wired.
        # HH4 will replace this with a real wgpu import.
        return None
    except Exception as exc:  # pragma: no cover
        logger.info("real renderer unavailable (%s); falling back to stub", exc)
        return None


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


# Loader dispatch — extension -> loader hook. HH2/HH3 will plug real
# importers in here; for now every extension returns a bare handle whose
# transform is trace-logged.
_MODEL_LOADERS: dict[str, Callable[[str], dict[str, Any]]] = {}


def register_model_loader(extension: str, loader: Callable[[str], dict[str, Any]]) -> None:
    """Register a loader hook for an asset extension (``".obj"`` etc).

    The loader receives the path string and returns a metadata dict merged
    into the returned :class:`ModelHandle` (currently we only accept
    ``position`` / ``rotation`` / ``scale`` / ``visible``).
    """
    _MODEL_LOADERS[extension.lower()] = loader


# Default supported extensions — each returns an empty metadata dict so
# the resulting handle keeps its dataclass defaults. When real importers
# land they simply re-register.
for _ext in (".obj", ".gltf", ".glb", ".fbx", ".ply", ".stl", ".dae"):
    _MODEL_LOADERS[_ext] = lambda _p: {}


class App:
    """Runtime shell: window + tick loop + hooks + asset handles.

    A single :class:`App` owns one process's window (or headless simulator)
    and a bag of :class:`ModelHandle` / :class:`LightHandle` /
    :class:`CameraHandle` / :class:`TextureHandle` instances. It is safe to
    construct more than one for testing.
    """

    _implicit: "App | None" = None

    def __init__(
        self,
        config: AppConfig | None = None,
        *,
        config_path: str | Path | None = None,
    ) -> None:
        if config_path is not None:
            p = Path(config_path)
            if not p.exists():
                # First run: write a fully-commented default template
                # and fall through to defaults so the app still boots.
                stub = AppConfig()
                stub.write_commented_default(p)
                logger.info(
                    "AppConfig: wrote commented default template to %s", p
                )
                config = config or AppConfig()
            else:
                config = AppConfig.from_yaml_file(p)
        self.config: AppConfig = config or AppConfig()

        # Handle collections
        self.models: list[ModelHandle] = []
        self.textures: list[TextureHandle] = []
        self.lights: list[LightHandle] = []
        self.cameras: list[CameraHandle] = []
        self.active_camera: CameraHandle | None = None

        # Trace log — every mutation + tick appends. Tests assert on this.
        self.trace: list[tuple] = []

        # Lifecycle hook lists (users can .append their own callables)
        self._before_tick: list[Callable[["App", float], None]] = []
        self._after_tick: list[Callable[["App", float], None]] = []
        self._before_frame_render: list[Callable[["App"], None]] = []

        # Renderer — try real, fall back to stub
        self._renderer = _try_real_renderer(self.config) or _StubRenderer(self.config)

        # State
        self._running = False
        self._closed = False
        self._frame_count = 0
        self._elapsed = 0.0
        self._id_counter = 0

        # MM2 HUD overlay — populated by :meth:`enable_hud` when the
        # caller opts in. Guaranteed to exist so downstream tooling
        # can duck-check with ``getattr(app, "_hud_overlay", None)``.
        self._hud_overlay: Any = None

        # OO6/QQ4 diagnostics collector — populated by
        # :meth:`enable_diagnostics`. ``None`` until opted in so
        # ``getattr(app, "_diagnostics", None)`` reflects state.
        self._diagnostics: Any = None

        logger.debug("App initialised (renderer=%s)", type(self._renderer).__name__)

    # ------------------------------------------------------------------
    # Implicit-global-app helpers
    # ------------------------------------------------------------------
    @classmethod
    def _get_implicit(cls) -> "App":
        if cls._implicit is None or cls._implicit._closed:
            cls._implicit = App()
        return cls._implicit

    @classmethod
    def _clear_implicit(cls) -> None:
        cls._implicit = None

    # ------------------------------------------------------------------
    # Hook registration
    # ------------------------------------------------------------------
    def add_before_tick(self, hook: Callable[["App", float], None]) -> None:
        """Append a ``(app, dt) -> None`` hook that fires before ``on_tick``."""
        self._before_tick.append(hook)

    def add_after_tick(self, hook: Callable[["App", float], None]) -> None:
        """Append a ``(app, dt) -> None`` hook that fires after ``on_tick``."""
        self._after_tick.append(hook)

    def add_before_frame_render(self, hook: Callable[["App"], None]) -> None:
        """Append a ``(app,) -> None`` hook that fires before draw calls."""
        self._before_frame_render.append(hook)

    # ------------------------------------------------------------------
    # Asset loading
    # ------------------------------------------------------------------
    def _next_id(self) -> int:
        i = self._id_counter
        self._id_counter += 1
        return i

    def load_model(self, path: str | Path) -> ModelHandle:
        """Load a 3D model asset and return a :class:`ModelHandle`.

        Preferred path: hand off to the HH5 asset importer via
        :func:`slappyengine.app_integration.bridge_load_model`. This
        returns a handle with a real :class:`slappyengine.render.mesh.Mesh`
        attached (see :meth:`_load_via_asset_importer`).

        Fallback path: dispatches on file extension via
        :func:`register_model_loader`. Unknown extensions still return a
        handle (with a warning) so prototypes never break on a typo.
        """
        p = Path(path)
        ext = p.suffix.lower()

        # HH5 preferred path — only when the asset actually exists on disk.
        # (Existing HH1 tests pass fake paths like "bunny.obj"; those keep
        # the historical stub behaviour.)
        if p.exists():
            imported = self._load_via_asset_importer(p)
            if imported is not None:
                return imported

        loader = _MODEL_LOADERS.get(ext)
        meta: dict[str, Any] = {}
        if loader is None:
            logger.warning("load_model: no loader for %r; returning bare handle", ext)
        else:
            try:
                meta = loader(str(p)) or {}
            except Exception as exc:
                logger.warning("load_model: loader %s raised %s", ext, exc)
                meta = {}

        handle = ModelHandle(
            path=str(p),
            id=self._next_id(),
            _app=self,
            position=tuple(meta.get("position", (0.0, 0.0, 0.0))),
            rotation=tuple(meta.get("rotation", (0.0, 0.0, 0.0))),
            scale=tuple(meta.get("scale", (1.0, 1.0, 1.0))),
            visible=bool(meta.get("visible", True)),
        )
        self.models.append(handle)
        self.trace.append(("load_model", handle.id, str(p), ext))
        return handle

    def _load_model_stub(self, path: str | Path) -> ModelHandle:
        """Legacy stub loader — extension dispatch, no asset_import.

        Public for the app_integration bridge fallback path so it can
        avoid recursion into :meth:`load_model` (which now tries HH5
        first). Behaviour matches the pre-HH1↔HH5 :meth:`load_model`.
        """
        p = Path(path)
        ext = p.suffix.lower()
        loader = _MODEL_LOADERS.get(ext)
        meta: dict[str, Any] = {}
        if loader is None:
            logger.warning("_load_model_stub: no loader for %r", ext)
        else:
            try:
                meta = loader(str(p)) or {}
            except Exception as exc:
                logger.warning("_load_model_stub: loader %s raised %s", ext, exc)
                meta = {}
        handle = ModelHandle(
            path=str(p),
            id=self._next_id(),
            _app=self,
            position=tuple(meta.get("position", (0.0, 0.0, 0.0))),
            rotation=tuple(meta.get("rotation", (0.0, 0.0, 0.0))),
            scale=tuple(meta.get("scale", (1.0, 1.0, 1.0))),
            visible=bool(meta.get("visible", True)),
        )
        self.models.append(handle)
        self.trace.append(("load_model", handle.id, str(p), ext))
        return handle

    def _load_via_asset_importer(self, path: str | Path) -> ModelHandle | None:
        """Soft-import ``slappyengine.app_integration`` and call the bridge.

        Returns
        -------
        ModelHandle
            When the bridge successfully produced a mesh-populated handle
            (``.mesh`` set, appended to ``self.models``).
        None
            When the bridge / asset_import / render subpackage is not
            available. Callers must then fall back to stub behaviour.
        """
        try:
            from slappyengine.app_integration import bridge_load_model
        except Exception as exc:
            logger.debug(
                "_load_via_asset_importer: app_integration unavailable (%s)", exc
            )
            return None
        try:
            handle = bridge_load_model(self, str(path))
        except Exception as exc:  # pragma: no cover - defensive
            logger.info(
                "_load_via_asset_importer: bridge_load_model raised %s", exc
            )
            return None
        if getattr(handle, "mesh", None) is None:
            # Bridge fell back to the stub loader (e.g. no importer for
            # ext). Caller may retry the local stub-only path.
            return None
        return handle

    def load_texture(self, path: str | Path) -> TextureHandle:
        """Load a texture and return a :class:`TextureHandle`."""
        p = Path(path)
        handle = TextureHandle(path=str(p), id=self._next_id(), _app=self)
        self.textures.append(handle)
        self.trace.append(("load_texture", handle.id, str(p)))
        return handle

    def spawn_light(
        self,
        position: tuple[float, float, float] = (0.0, 0.0, 0.0),
        color: tuple[float, float, float] = (1.0, 1.0, 1.0),
        intensity: float = 1.0,
    ) -> LightHandle:
        """Spawn a light and return its :class:`LightHandle`."""
        handle = LightHandle(
            position=tuple(position),
            color=tuple(color),
            intensity=float(intensity),
            id=self._next_id(),
            _app=self,
        )
        self.lights.append(handle)
        self.trace.append(("spawn_light", handle.id, handle.position))
        return handle

    def spawn_camera(
        self,
        position: tuple[float, float, float] | None = None,
        look_at: tuple[float, float, float] | None = None,
    ) -> CameraHandle:
        """Spawn a camera and mark it active."""
        pos = tuple(position) if position is not None else self.config.default_camera_position
        aim = tuple(look_at) if look_at is not None else self.config.default_camera_look_at
        handle = CameraHandle(
            position=pos,
            look_at=aim,
            fov_deg=self.config.default_fov_deg,
            near=self.config.default_near,
            far=self.config.default_far,
            id=self._next_id(),
            _app=self,
        )
        self.cameras.append(handle)
        self.active_camera = handle
        self.trace.append(("spawn_camera", handle.id, pos))
        return handle

    # ------------------------------------------------------------------
    def _remove_model(self, handle: ModelHandle) -> None:
        try:
            self.models.remove(handle)
            self.trace.append(("destroy_model", handle.id))
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------
    def run(
        self,
        *,
        on_begin: Callable[["App"], None] | None = None,
        on_tick: Callable[["App", float], None] | None = None,
        on_end: Callable[["App"], None] | None = None,
        max_frames: int | None = None,
    ) -> None:
        """Run the tick loop.

        Parameters
        ----------
        on_begin
            Called exactly once, before the loop starts. Signature ``(app,)``.
        on_tick
            Called once per frame with ``(app, dt_seconds)``.
        on_end
            Called exactly once after the loop exits. Signature ``(app,)``.
        max_frames
            Override the config-level frame cap (0 = unlimited). Tests set
            this to a small number (60) to keep runs bounded.
        """
        if self._closed:
            raise RuntimeError("App is closed; cannot run() again")

        cap = max_frames if max_frames is not None else self.config.max_frames
        target_fps = max(1, int(self.config.target_fps))
        dt = 1.0 / target_fps
        frame_budget = dt if self.config.fixed_timestep else 0.0

        self._running = True
        self.trace.append(("run_begin", cap, target_fps))

        try:
            if on_begin is not None:
                on_begin(self)
            self.trace.append(("on_begin_fired",))

            frame = 0
            while self._running:
                loop_start = time.perf_counter()

                for hook in self._before_tick:
                    hook(self, dt)

                if on_tick is not None:
                    on_tick(self, dt)

                for hook in self._after_tick:
                    hook(self, dt)

                # Render pass — stub logs draw_model; HH4 renderers get
                # the full submit_mesh / set_lights / set_camera path via
                # the integration bridge.
                if hasattr(self._renderer, "submit_mesh"):
                    # HH4 path — render_frame handles begin/end + hooks +
                    # bridge_submit_frame and increments _frame_count.
                    self.render_frame()
                else:
                    for hook in self._before_frame_render:
                        hook(self)
                    self._renderer.begin_frame()
                    for model in self.models:
                        if model.visible:
                            self._renderer.draw_model(model)
                    self._renderer.end_frame()
                    self._frame_count += 1

                self._elapsed += dt
                frame += 1

                if cap and frame >= cap:
                    self._running = False
                    break

                # Honour target_fps in real-time mode only. Tests run
                # with fixed_timestep=False and cap>0 so the sleep is a
                # nop unless the caller opts in.
                if frame_budget > 0.0:
                    spent = time.perf_counter() - loop_start
                    remaining = frame_budget - spent
                    if remaining > 0.0:
                        time.sleep(remaining)

            self.trace.append(("run_end", self._frame_count))
            if on_end is not None:
                on_end(self)
            self.trace.append(("on_end_fired",))
        finally:
            self._running = False

    # ------------------------------------------------------------------
    # HH1 ↔ HH4 integration helpers (bridge glue)
    # ------------------------------------------------------------------
    def render_frame(self) -> None:
        """Render one frame using whichever backend is bound.

        Preserves HH1's 2-line pattern: if ``self._renderer`` is still
        the logging :class:`_StubRenderer`, we drive the stub's tiny
        ``begin_frame`` / ``draw_model`` / ``end_frame`` surface exactly
        as :meth:`run` does. If the renderer has been swapped for a HH4
        :class:`Renderer` / :class:`NullRenderer` (via
        :func:`slappyengine.app_integration.promote_stub_renderer`),
        we route through :func:`bridge_submit_frame` instead so meshes,
        materials, lights, and the camera all flow through.
        """
        renderer = self._renderer
        # HH4 renderers expose ``submit_mesh``; the HH1 stub does not.
        if hasattr(renderer, "submit_mesh"):
            try:
                from slappyengine.app_integration import bridge_submit_frame
            except Exception as exc:  # pragma: no cover
                logger.info("render_frame: bridge unavailable (%s)", exc)
                return
            renderer.begin_frame()
            for hook in self._before_frame_render:
                hook(self)
            bridge_submit_frame(self, renderer)
            renderer.end_frame()
            self._frame_count += 1
            return

        # Stub path — unchanged HH1 behaviour.
        for hook in self._before_frame_render:
            hook(self)
        renderer.begin_frame()
        for model in self.models:
            if model.visible:
                renderer.draw_model(model)
        renderer.end_frame()
        self._frame_count += 1

    def get_bounding_box_of_all_models(
        self,
    ) -> tuple[tuple[float, float, float], tuple[float, float, float]]:
        """Return the axis-aligned bounding box enclosing all loaded models.

        Used by callers wanting to auto-frame a camera. Considers each
        handle's ``.bounding_box`` (populated by
        :func:`slappyengine.app_integration.bridge_load_model`) after
        transforming its 8 corners by :meth:`ModelHandle.transform_matrix`.

        Returns ``((0,0,0), (0,0,0))`` when there are no models with
        bounding boxes.
        """
        import numpy as _np  # local import — keep the module-top light

        mins: list[float] = []
        maxs: list[float] = []
        found_any = False
        for handle in self.models:
            bbox = getattr(handle, "bounding_box", None)
            if bbox is None:
                continue
            (mn_x, mn_y, mn_z), (mx_x, mx_y, mx_z) = bbox
            corners = _np.array(
                [
                    [mn_x, mn_y, mn_z, 1.0],
                    [mx_x, mn_y, mn_z, 1.0],
                    [mn_x, mx_y, mn_z, 1.0],
                    [mx_x, mx_y, mn_z, 1.0],
                    [mn_x, mn_y, mx_z, 1.0],
                    [mx_x, mn_y, mx_z, 1.0],
                    [mn_x, mx_y, mx_z, 1.0],
                    [mx_x, mx_y, mx_z, 1.0],
                ],
                dtype=_np.float32,
            )
            m = handle.transform_matrix()
            if m is None:
                world = corners[:, :3]
            else:
                world4 = corners @ m.T
                world = world4[:, :3]
            if not found_any:
                mins = world.min(axis=0).tolist()
                maxs = world.max(axis=0).tolist()
                found_any = True
            else:
                cur_min = world.min(axis=0)
                cur_max = world.max(axis=0)
                mins = [min(mins[i], float(cur_min[i])) for i in range(3)]
                maxs = [max(maxs[i], float(cur_max[i])) for i in range(3)]

        if not found_any:
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        return (
            (float(mins[0]), float(mins[1]), float(mins[2])),
            (float(maxs[0]), float(maxs[1]), float(maxs[2])),
        )

    def stop(self) -> None:
        """Signal the tick loop to exit at the top of the next iteration."""
        self._running = False
        self.trace.append(("stop",))

    def close(self) -> None:
        """Shut down the renderer and mark the app closed. Idempotent."""
        if self._closed:
            return
        self._running = False
        # HH4 renderers currently don't expose close(); guard for both
        # the stub (which does) and the real backend (which doesn't).
        _close = getattr(self._renderer, "close", None)
        if callable(_close):
            try:
                _close()
            except Exception as exc:  # pragma: no cover
                logger.warning("renderer.close() raised %s", exc)
        self._closed = True
        self.trace.append(("close",))
        if App._implicit is self:
            App._implicit = None

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def elapsed(self) -> float:
        return self._elapsed

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def is_headless(self) -> bool:
        """``True`` when the render backend is the stub."""
        return isinstance(self._renderer, _StubRenderer)

    # ------------------------------------------------------------------
    # MM2 — HUD integration (delegates to slappyengine.hud_bridge).
    # ------------------------------------------------------------------
    def enable_hud(
        self,
        widgets: Iterable[Any] | None = None,
        layout: str = "default",
    ) -> Any:
        """Mount an :class:`HUDOverlay` on this app and return it.

        A thin one-liner around :func:`slappyengine.hud_bridge.mount_hud`
        that stashes the overlay on ``self._hud_overlay`` and wires the
        HUD's begin/end/submit calls into the tick loop.

        Parameters
        ----------
        widgets:
            Iterable of pre-instantiated HUD widgets. When ``None`` the
            default game HUD (HealthBar / StaminaBar / AmmoCounter /
            Compass / Crosshair) is used.
        layout:
            Reserved for future named-layout dispatch (e.g. ``"minimal"``
            / ``"combat"``). Currently only ``"default"`` is honoured;
            other values are accepted and ignored so callers can pin the
            argument now and populate it later.

        Returns
        -------
        HUDOverlay
            The mounted overlay — also accessible via
            ``self._hud_overlay``.
        """
        from slappyengine.hud_bridge import mount_hud

        # ``layout`` is a forward-compat argument. Log a debug when an
        # unknown layout is requested so callers see it without spamming.
        if layout not in ("default", None):
            logger.debug("App.enable_hud: unknown layout %r; using default", layout)

        self._hud_overlay = mount_hud(self, widgets=widgets)
        return self._hud_overlay

    # ------------------------------------------------------------------
    # NN3 — Capture + render-toggle façade.
    #
    # Each method is a thin single-call surface over the LL2 / MM6 action
    # helpers so a user can ``pip install slappyengine`` and record /
    # screenshot / toggle SSAO / toggle shadows with one line, no ctx
    # dict, no router boilerplate. Callers wanting to bypass this
    # convenience layer (custom ctx, non-default renderer target, etc.)
    # can call the ``_core`` action helpers directly:
    # :mod:`slappyengine.actions.capture_actions` /
    # :mod:`slappyengine.actions.render_toggle_actions`.
    # ------------------------------------------------------------------
    def start_recording(
        self,
        path: str | None = None,
        fps: int = 60,
        resolution: tuple[int, int] | None = None,
    ) -> dict[str, Any]:
        """Start an MP4 recording of the current renderer.

        One-liner over
        :func:`slappyengine.actions.capture_actions.start_recording`.
        Recording state is stashed on ``self._capture_state`` so a
        subsequent :meth:`stop_recording` closes it out.

        Parameters
        ----------
        path:
            Optional output MP4 path. Default:
            ``recordings/capture_<timestamp>.mp4`` under the project root.
        fps:
            Playback frame rate for the encoded video. Defaults to 60.
        resolution:
            Optional ``(width, height)`` override. Falls back to the
            renderer's declared size and then ``(1280, 720)``.

        Returns
        -------
        dict
            Router-style status dict — see the ``start_recording``
            return contract in :mod:`capture_actions`.

        Notes
        -----
        Bypass hint: call
        ``slappyengine.actions.capture_actions.start_recording(ctx)``
        directly (``_core`` surface) when you need a custom renderer /
        codec / bitrate.
        """
        from slappyengine.actions.capture_actions import (
            start_recording as _core,
        )

        ctx: dict[str, Any] = {"shell": self, "renderer": self._renderer}
        if path is not None:
            ctx["path"] = path
        if fps is not None:
            ctx["fps"] = int(fps)
        if resolution is not None:
            ctx["resolution"] = resolution
        return _core(ctx)

    def stop_recording(self) -> dict[str, Any]:
        """Stop the MP4 recording session started by :meth:`start_recording`.

        One-liner over
        :func:`slappyengine.actions.capture_actions.stop_recording`.
        Safe to call when nothing is recording — returns
        ``{"status": "not_recording"}``.

        Returns
        -------
        dict
            Router-style status dict — see the ``stop_recording`` return
            contract in :mod:`capture_actions`.

        Notes
        -----
        Bypass hint: call
        ``slappyengine.actions.capture_actions.stop_recording(ctx)``
        directly (``_core`` surface) to close a session belonging to a
        different shell.
        """
        from slappyengine.actions.capture_actions import (
            stop_recording as _core,
        )

        return _core({"shell": self, "renderer": self._renderer})

    def take_screenshot(
        self,
        path: str | None = None,
        format: str = "png",
    ) -> dict[str, Any]:
        """Capture a one-shot screenshot of the current renderer.

        One-liner over
        :func:`slappyengine.actions.capture_actions.screenshot`. Does
        not touch any live recording session.

        Parameters
        ----------
        path:
            Optional output image path. Default:
            ``screenshots/capture_<timestamp>.png`` under the project
            root.
        format:
            Output image format (``"png"`` / ``"jpg"``). Only consulted
            when ``path`` is ``None`` — an explicit ``path`` picks the
            format from its suffix. Defaults to ``"png"``.

        Returns
        -------
        dict
            Router-style status dict — see the ``screenshot`` return
            contract in :mod:`capture_actions`.

        Notes
        -----
        Bypass hint: call
        ``slappyengine.actions.capture_actions.screenshot(ctx)``
        directly (``_core`` surface) for custom resolution / renderer.
        """
        from slappyengine.actions.capture_actions import (
            screenshot as _core,
        )

        ctx: dict[str, Any] = {"shell": self, "renderer": self._renderer}
        if path is not None:
            ctx["path"] = path
        elif format is not None:
            # Honour a bare ``format=`` when the caller didn't pass an
            # explicit path: mint a default under the project root with
            # the requested extension.
            ext = str(format).lower().lstrip(".")
            if ext and ext != "png":
                import time as _time
                from pathlib import Path as _Path

                stamp = _time.strftime("%Y%m%d_%H%M%S")
                root = getattr(self, "_project_root", None) or getattr(
                    self, "project_root", None,
                )
                base = _Path(root) if root is not None else _Path(".").resolve()
                ctx["path"] = str(
                    base / "screenshots" / f"capture_{stamp}.{ext}"
                )
        return _core(ctx)

    def enable_ssao(self, enabled: bool = True) -> dict[str, Any]:
        """Toggle the SSAO pass on the current renderer.

        One-liner over
        :func:`slappyengine.actions.render_toggle_actions.enable_ssao`.
        Headless-safe: when no renderer is bound, the flag is stored on
        the shell (``self._ssao_enabled``) so subsequent calls still
        round-trip.

        Parameters
        ----------
        enabled:
            The new state. Defaults to ``True`` so the common
            "just turn it on" call site is a bare
            ``app.enable_ssao()``.

        Returns
        -------
        dict
            Router-style status dict — see the ``enable_ssao`` return
            contract in :mod:`render_toggle_actions`.

        Notes
        -----
        Bypass hint: call
        ``slappyengine.actions.render_toggle_actions.enable_ssao(ctx)``
        directly (``_core`` surface) to omit ``enabled`` (i.e. flip
        the flag).
        """
        from slappyengine.actions.render_toggle_actions import (
            enable_ssao as _core,
        )

        return _core(
            {
                "shell": self,
                "renderer": self._renderer,
                "enabled": bool(enabled),
            }
        )

    def enable_shadows(self, enabled: bool = True) -> dict[str, Any]:
        """Toggle the CSM shadow-map pass on the current renderer.

        One-liner over
        :func:`slappyengine.actions.render_toggle_actions.enable_shadows`.
        Same headless-safe fallback as :meth:`enable_ssao`.

        Parameters
        ----------
        enabled:
            The new state. Defaults to ``True``.

        Returns
        -------
        dict
            Router-style status dict — see the ``enable_shadows`` return
            contract in :mod:`render_toggle_actions`.

        Notes
        -----
        Bypass hint: call
        ``slappyengine.actions.render_toggle_actions.enable_shadows(ctx)``
        directly (``_core`` surface) to omit ``enabled`` (i.e. flip
        the flag).
        """
        from slappyengine.actions.render_toggle_actions import (
            enable_shadows as _core,
        )

        return _core(
            {
                "shell": self,
                "renderer": self._renderer,
                "enabled": bool(enabled),
            }
        )

    # ------------------------------------------------------------------
    # QQ4 — diagnostics collector façade (OO6).
    #
    # Thin one-liners over :mod:`slappyengine.diagnostics`. Users wanting
    # to bypass this convenience layer (custom min_level per subsystem,
    # collector attached to a non-``slappyengine`` logger, etc.) can call
    # :func:`slappyengine.diagnostics.get_global_collector` directly
    # (the ``_core`` surface) and manage ``install()`` themselves.
    # ------------------------------------------------------------------
    def enable_diagnostics(
        self,
        min_level: str = "WARNING",
        max_events: int = 500,
    ) -> Any:
        """Install a :class:`DiagnosticsCollector` on this app.

        Instantiates a fresh collector, calls
        :meth:`~slappyengine.diagnostics.DiagnosticsCollector.install`
        so it subscribes to the ``slappyengine`` root logger, and stashes
        it on ``self._diagnostics``. Subsequent calls are idempotent and
        return the same collector.

        When a HUD is already mounted (``self._hud_overlay`` is not
        ``None``), a compact diagnostics readout widget is attached via
        :func:`slappyengine.hud_bridge.add_diagnostics_widget` so
        warnings + errors surface in-viewport without further wiring.

        Parameters
        ----------
        min_level:
            Minimum log level captured. Defaults to ``"WARNING"``.
        max_events:
            Ring-buffer capacity. Defaults to 500.

        Returns
        -------
        DiagnosticsCollector
            The installed collector — also accessible via
            :meth:`get_diagnostics`.

        Notes
        -----
        Bypass hint: call
        ``slappyengine.diagnostics.get_global_collector()`` directly
        (``_core`` surface) to share one collector across multiple apps
        or to manage ``install()`` timing yourself.
        """
        if self._diagnostics is not None:
            return self._diagnostics

        from slappyengine.diagnostics import DiagnosticsCollector

        collector = DiagnosticsCollector(
            max_events=int(max_events),
            min_level=str(min_level),
        )
        collector.install()
        self._diagnostics = collector

        # Mount the HUD widget when a HUD is already up.
        if getattr(self, "_hud_overlay", None) is not None:
            try:
                from slappyengine.hud_bridge import add_diagnostics_widget

                add_diagnostics_widget(self, collector)
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug(
                    "enable_diagnostics: add_diagnostics_widget failed: %s", exc
                )

        return collector

    def disable_diagnostics(self) -> dict[str, Any]:
        """Uninstall the diagnostics collector if one is bound.

        Calls
        :meth:`~slappyengine.diagnostics.DiagnosticsCollector.uninstall`
        on ``self._diagnostics`` and clears the slot.

        Returns
        -------
        dict
            ``{"status": "disabled"}`` when a collector was detached, or
            ``{"status": "not_enabled"}`` when nothing was bound.

        Notes
        -----
        Bypass hint: call the collector's
        :meth:`~slappyengine.diagnostics.DiagnosticsCollector.uninstall`
        directly (``_core`` surface) if you want to keep the collector
        for later inspection.
        """
        if self._diagnostics is None:
            return {"status": "not_enabled"}
        try:
            self._diagnostics.uninstall()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("disable_diagnostics: uninstall raised %s", exc)
        self._diagnostics = None
        return {"status": "disabled"}

    def get_diagnostics(self) -> Any:
        """Return the bound :class:`DiagnosticsCollector` or ``None``.

        Convenience accessor — equivalent to
        ``getattr(app, "_diagnostics", None)`` but explicit.

        Notes
        -----
        Bypass hint: use
        :func:`slappyengine.diagnostics.get_global_collector`
        (``_core`` surface) to reach the process-wide singleton
        instead of this app's collector.
        """
        return self._diagnostics

    def diagnostics_events(self) -> list[Any]:
        """Return the collector's buffered events (or ``[]`` when disabled).

        Convenience shim over
        :meth:`DiagnosticsCollector.events`.

        Notes
        -----
        Bypass hint: call ``collector.events()`` directly (``_core``
        surface) — this method just guards the ``None`` case.
        """
        if self._diagnostics is None:
            return []
        return self._diagnostics.events()

    def diagnostics_stats(self) -> dict[str, int]:
        """Return the collector's per-level/per-subsystem counts.

        Convenience shim over
        :meth:`DiagnosticsCollector.stats`. Returns an empty dict when
        diagnostics have not been enabled.

        Notes
        -----
        Bypass hint: call ``collector.stats()`` directly (``_core``
        surface) — this method just guards the ``None`` case.
        """
        if self._diagnostics is None:
            return {}
        return self._diagnostics.stats()

    def diagnostics_report(self, **kwargs: Any) -> str:
        """Render a Markdown problem-panel report for the current buffer.

        Convenience shim over
        :meth:`DiagnosticsCollector.render_markdown_report`. Returns an
        empty string when diagnostics have not been enabled.

        Parameters
        ----------
        **kwargs:
            Forwarded to
            :meth:`DiagnosticsCollector.render_markdown_report`
            (``max_events``, ``group_by``).

        Notes
        -----
        Bypass hint: call ``collector.render_markdown_report(...)``
        directly (``_core`` surface) — this method just guards the
        ``None`` case.
        """
        if self._diagnostics is None:
            return ""
        return self._diagnostics.render_markdown_report(**kwargs)

    def diagnostics_widget_summary(self) -> dict[str, Any]:
        """Return a small summary dict suitable for HUD label rendering.

        The result has the shape::

            {
                "total": int,
                "warnings": int,
                "errors": int,        # ERROR + CRITICAL
                "top_subsystem": str | None,
                "last_message": str | None,
            }

        Sourced from :meth:`DiagnosticsCollector.stats`,
        :meth:`DiagnosticsCollector.top_subsystems` (top 1) and the last
        buffered event's ``.message``. When diagnostics have not been
        enabled, returns empty defaults with ``total``/``warnings``/
        ``errors`` at ``0`` and both string slots ``None``.

        Notes
        -----
        Bypass hint: call ``collector.stats()`` + ``top_subsystems(1)``
        directly (``_core`` surface) — this method just packages them
        for a single HUD label.
        """
        empty: dict[str, Any] = {
            "total": 0,
            "warnings": 0,
            "errors": 0,
            "top_subsystem": None,
            "last_message": None,
        }
        if self._diagnostics is None:
            return empty
        stats = self._diagnostics.stats()
        top = self._diagnostics.top_subsystems(1)
        top_name: str | None = top[0][0] if top else None
        events = self._diagnostics.events()
        last_message: str | None = events[-1].message if events else None
        return {
            "total": int(stats.get("total", 0)),
            "warnings": int(stats.get("level:WARNING", 0)),
            "errors": int(stats.get("level:ERROR", 0))
            + int(stats.get("level:CRITICAL", 0)),
            "top_subsystem": top_name,
            "last_message": last_message,
        }


# ---------------------------------------------------------------------------
# Module-level convenience API
# ---------------------------------------------------------------------------


def launch(
    on_begin: Callable[[App], None] | None = None,
    on_tick: Callable[[App, float], None] | None = None,
    on_end: Callable[[App], None] | None = None,
    config: AppConfig | None = None,
    *,
    max_frames: int | None = None,
) -> App:
    """One-shot launcher for the 2-line render pattern.

    Example
    -------

    >>> import slappyengine
    >>> slappyengine.launch(
    ...     on_begin=lambda app: app.load_model("bunny.obj"),
    ...     max_frames=1,
    ... )  # doctest: +SKIP
    """
    app = App(config=config)
    App._implicit = app
    try:
        app.run(on_begin=on_begin, on_tick=on_tick, on_end=on_end, max_frames=max_frames)
    finally:
        # Do NOT auto-close — the caller may want to inspect state after
        # launch() returns (e.g. tests reading app.trace). close() is
        # explicit.
        pass
    return app


def load_model(path: str | Path) -> ModelHandle:
    """Load a model into the implicit global app (creates one if absent)."""
    return App._get_implicit().load_model(path)


def load_texture(path: str | Path) -> TextureHandle:
    """Load a texture into the implicit global app (creates one if absent)."""
    return App._get_implicit().load_texture(path)


__all__ = [
    "App",
    "AppConfig",
    "ModelHandle",
    "TextureHandle",
    "LightHandle",
    "CameraHandle",
    "launch",
    "load_model",
    "load_texture",
    "register_model_loader",
]
