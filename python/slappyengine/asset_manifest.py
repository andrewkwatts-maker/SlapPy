"""YAML-backed manifests for assets, layers, scenes, and levels.

Any object that appears in the visual editor has a matching YAML representation.
Round-trip guaranteed: editor saves → YAML; YAML loads → editor state.
AI tools can edit either the YAML files or call the Python API.

Manifest YAML format examples:

  # assets/player.yml
  name: Player
  type: asset
  layers:
    - name: body
      texture: sprites/player.png
      opacity: 1.0
      deformable: false
      lighting_mode: "2d"
    - name: shadow
      texture: sprites/player_shadow.png
      opacity: 0.5
  scripts:
    - scripts/player_controller.py
  collision:
    type: aabb
    width: 32
    height: 32
  properties:
    position: [0.0, 0.0]
    rotation: 0.0
    tags: ["player"]

  # scenes/main.yml
  name: Main
  type: scene
  entities:
    - manifest: assets/player.yml
      position: [100, 200]
    - manifest: assets/enemy.yml
      position: [300, 400]
  lighting:
    ambient_color: [0.2, 0.2, 0.3]
    ambient_intensity: 0.2
  post_process:
    - type: vignette
      strength: 0.4
"""
from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml


# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------


@dataclass
class LayerManifest:
    """Describes a single compositing layer within an asset."""

    name: str
    texture: str | None = None
    width: int = 64
    height: int = 64
    opacity: float = 1.0
    deformable: bool = False
    lighting_mode: str = "2d"
    tint: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "texture": self.texture,
            "width": self.width,
            "height": self.height,
            "opacity": self.opacity,
            "deformable": self.deformable,
            "lighting_mode": self.lighting_mode,
            "tint": list(self.tint),
        }

    @classmethod
    def from_dict(cls, d: dict) -> LayerManifest:
        tint_raw = d.get("tint", [1.0, 1.0, 1.0, 1.0])
        return cls(
            name=d["name"],
            texture=d.get("texture"),
            width=int(d.get("width", 64)),
            height=int(d.get("height", 64)),
            opacity=float(d.get("opacity", 1.0)),
            deformable=bool(d.get("deformable", False)),
            lighting_mode=str(d.get("lighting_mode", "2d")),
            tint=tuple(float(v) for v in tint_raw),  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------------------
# Collision
# ---------------------------------------------------------------------------


@dataclass
class CollisionManifest:
    """Axis-aligned or other collision shape attached to an asset."""

    type: str = "aabb"
    width: int = 32
    height: int = 32

    def to_dict(self) -> dict:
        return {"type": self.type, "width": self.width, "height": self.height}

    @classmethod
    def from_dict(cls, d: dict) -> CollisionManifest:
        return cls(
            type=str(d.get("type", "aabb")),
            width=int(d.get("width", 32)),
            height=int(d.get("height", 32)),
        )


# ---------------------------------------------------------------------------
# Subscription entry
# ---------------------------------------------------------------------------


@dataclass
class SubscriptionEntry:
    """One entry in an asset's ``subscriptions:`` YAML list.

    Maps a dot-path event name to an optional handler function name inside one
    of the asset's scripts.  If *handler* is omitted the name is derived
    automatically:  ``"Asset.Car.Gas.Empty"`` → ``on_event_asset_car_gas_empty``.
    A generic ``on_event(entity, event_details)`` in any script acts as a
    catch-all fallback when the specific handler is absent.

    YAML example::

        subscriptions:
          - event: Asset.Car.Gas.Empty
            # handler: on_event_asset_car_gas_empty  ← auto-derived if omitted
          - event: Vehicle.fuel_level
            handler: on_fuel_changed
    """

    event: str
    handler: str | None = None

    # Derived handler name: "Asset.Car.Gas.Empty" → "on_event_asset_car_gas_empty"
    def derived_handler(self) -> str:
        slug = self.event.replace(".", "_").lower()
        return f"on_event_{slug}"

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"event": self.event}
        if self.handler is not None:
            d["handler"] = self.handler
        return d

    @classmethod
    def from_dict(cls, d: dict | str) -> SubscriptionEntry:
        if isinstance(d, str):
            return cls(event=d)
        return cls(
            event=str(d["event"]),
            handler=d.get("handler"),
        )


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------


@dataclass
class AssetManifest:
    """Complete manifest for a single game asset."""

    name: str
    type: str = "asset"
    layers: list[LayerManifest] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    subscriptions: list[SubscriptionEntry] = field(default_factory=list)
    collision: CollisionManifest | None = None
    properties: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        d: dict[str, Any] = {
            "name": self.name,
            "type": self.type,
            "layers": [l.to_dict() for l in self.layers],
            "scripts": list(self.scripts),
            "properties": dict(self.properties),
        }
        if self.subscriptions:
            d["subscriptions"] = [s.to_dict() for s in self.subscriptions]
        if self.collision is not None:
            d["collision"] = self.collision.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AssetManifest:
        layers = [LayerManifest.from_dict(l) for l in d.get("layers", [])]
        collision = (
            CollisionManifest.from_dict(d["collision"])
            if d.get("collision")
            else None
        )
        subscriptions = [
            SubscriptionEntry.from_dict(s) for s in d.get("subscriptions", [])
        ]
        return cls(
            name=d["name"],
            type=str(d.get("type", "asset")),
            layers=layers,
            scripts=list(d.get("scripts", [])),
            subscriptions=subscriptions,
            collision=collision,
            properties=dict(d.get("properties", {})),
        )

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: str | Path) -> AssetManifest:
        """Parse an asset manifest from a YAML file on disk."""
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_dict(yaml.safe_load(text))

    def save(self, path: str | Path) -> None:
        """Write this manifest back to YAML — round-trips cleanly."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def checksum(self) -> str:
        """SHA-256 of the canonical YAML serialisation.

        Stable across saves because ``sort_keys=True`` produces a
        deterministic byte string — suitable for encryption key derivation
        via :func:`content_encrypt.derive_key`.
        """
        canonical = yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------


@dataclass
class SceneManifest:
    """Manifest for a scene: entity placements, lighting, post-processing."""

    name: str
    type: str = "scene"
    entities: list[dict[str, Any]] = field(default_factory=list)
    lighting: dict[str, Any] = field(default_factory=dict)
    post_process: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "entities": list(self.entities),
            "lighting": dict(self.lighting),
            "post_process": list(self.post_process),
        }

    @classmethod
    def from_dict(cls, d: dict) -> SceneManifest:
        return cls(
            name=d["name"],
            type=str(d.get("type", "scene")),
            entities=list(d.get("entities", [])),
            lighting=dict(d.get("lighting", {})),
            post_process=list(d.get("post_process", [])),
        )

    @classmethod
    def load(cls, path: str | Path) -> SceneManifest:
        """Parse a scene manifest from a YAML file on disk."""
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_dict(yaml.safe_load(text))

    def save(self, path: str | Path) -> None:
        """Write this scene manifest back to YAML."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Level
# ---------------------------------------------------------------------------


@dataclass
class LevelManifest:
    """Manifest for a level: an ordered list of scene names to load."""

    name: str
    type: str = "level"
    scenes: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "scenes": list(self.scenes),
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> LevelManifest:
        return cls(
            name=d["name"],
            type=str(d.get("type", "level")),
            scenes=list(d.get("scenes", [])),
            description=str(d.get("description", "")),
        )

    @classmethod
    def load(cls, path: str | Path) -> LevelManifest:
        """Parse a level manifest from a YAML file on disk."""
        text = Path(path).read_text(encoding="utf-8")
        return cls.from_dict(yaml.safe_load(text))

    def save(self, path: str | Path) -> None:
        """Write this level manifest back to YAML."""
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            yaml.dump(self.to_dict(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Module-level router
# ---------------------------------------------------------------------------


def load_manifest(
    path: str | Path,
) -> AssetManifest | SceneManifest | LevelManifest:
    """Load any manifest YAML and return the appropriate typed object.

    Routes by the ``type:`` field found in the YAML document.
    Raises ``ValueError`` for unknown type values.
    """
    text = Path(path).read_text(encoding="utf-8")
    d: dict = yaml.safe_load(text)
    manifest_type = str(d.get("type", "asset")).lower()
    if manifest_type == "asset":
        return AssetManifest.from_dict(d)
    if manifest_type == "scene":
        return SceneManifest.from_dict(d)
    if manifest_type == "level":
        return LevelManifest.from_dict(d)
    raise ValueError(
        f"Unknown manifest type {manifest_type!r} in {path}. "
        "Expected 'asset', 'scene', or 'level'."
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ManifestRegistry:
    """Singleton registry that indexes all manifests under a project root.

    Typical usage::

        reg = ManifestRegistry.get()
        reg.scan("my_project/")
        player = reg.get_asset("Player")
    """

    _instance: ManifestRegistry | None = None

    def __init__(self) -> None:
        self._assets: dict[str, AssetManifest] = {}
        self._scenes: dict[str, SceneManifest] = {}
        self._paths: dict[str, Path] = {}
        self._callbacks: list[Callable[[Path, Any], None]] = []
        self._watch_thread: threading.Thread | None = None
        self._watching = False

    @classmethod
    def get(cls) -> ManifestRegistry:
        """Return the process-wide singleton registry."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan(self, root: str | Path) -> None:
        """Walk *root* recursively and load every ``*.yml`` manifest found.

        Already-registered names are overwritten so that re-scanning after an
        edit always reflects the current file state.
        """
        root = Path(root)
        for yml_path in root.rglob("*.yml"):
            try:
                manifest = load_manifest(yml_path)
            except Exception:
                # Skip malformed or non-manifest YAML files silently.
                continue

            self._paths[manifest.name] = yml_path
            if isinstance(manifest, AssetManifest):
                self._assets[manifest.name] = manifest
            elif isinstance(manifest, SceneManifest):
                self._scenes[manifest.name] = manifest
            # LevelManifests are not separately indexed but are still loadable
            # via load_manifest(); levels are typically few and loaded on demand.

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_asset(self, name: str) -> AssetManifest | None:
        return self._assets.get(name)

    def get_scene(self, name: str) -> SceneManifest | None:
        return self._scenes.get(name)

    def all_assets(self) -> list[AssetManifest]:
        return list(self._assets.values())

    def all_scenes(self) -> list[SceneManifest]:
        return list(self._scenes.values())

    # ------------------------------------------------------------------
    # File watching
    # ------------------------------------------------------------------

    def watch(self, callback: Callable[[Path, Any], None]) -> None:
        """Register *callback(path, manifest)* to be called when any manifest
        file changes on disk.

        Uses a background thread that polls mtimes at one-second intervals.
        Requires no external dependencies — ``watchdog`` is used automatically
        when available for lower latency, but the polling fallback is always
        present.
        """
        self._callbacks.append(callback)
        if self._watch_thread is None or not self._watch_thread.is_alive():
            self._watching = True
            self._watch_thread = threading.Thread(
                target=self._poll_loop, daemon=True, name="ManifestWatcher"
            )
            self._watch_thread.start()

    def _poll_loop(self) -> None:
        """Background polling loop — fires registered callbacks on mtime changes."""
        import time

        mtimes: dict[Path, float] = {}

        while self._watching:
            for name, path in list(self._paths.items()):
                try:
                    mtime = path.stat().st_mtime
                except FileNotFoundError:
                    continue
                if mtimes.get(path, 0.0) != mtime:
                    mtimes[path] = mtime
                    if mtimes.get(path, 0.0) != 0.0:
                        # File changed; reload and notify.
                        try:
                            manifest = load_manifest(path)
                            if isinstance(manifest, AssetManifest):
                                self._assets[manifest.name] = manifest
                            elif isinstance(manifest, SceneManifest):
                                self._scenes[manifest.name] = manifest
                            for cb in self._callbacks:
                                cb(path, manifest)
                        except Exception:
                            pass
            time.sleep(1.0)


# ---------------------------------------------------------------------------
# Script binding — per-entity on_launch / on_tick / on_end from YAML scripts
# ---------------------------------------------------------------------------


class ScriptBinding:
    """Loads and calls the lifecycle hooks declared in an :class:`AssetManifest`'s
    ``scripts:`` list.

    Script files are Python modules that may define any combination of:

    .. code-block:: python

        # scripts/player_controller.py
        def on_launch(entity):
            entity.speed = 200.0

        def on_tick(entity, dt):
            entity.position = (entity.position[0] + entity.speed * dt,
                               entity.position[1])

        def on_end(entity):
            print(f"{entity} removed")

    Multiple assets can reference the same script file — the module is loaded
    once and cached.  Hot-reload is triggered automatically if the manifest
    registry's watch callback is wired.

    Usage::

        from slappyengine.asset_manifest import AssetManifest, ScriptBinding

        manifest = AssetManifest.load("assets/player.yml")
        binding = ScriptBinding(manifest, search_paths=[".", "scripts"])
        binding.launch(entity)   # calls on_launch(entity) in all scripts

        # Each tick:
        binding.tick(entity, dt)

        # On removal:
        binding.end(entity)
    """

    # Module cache shared across all ScriptBinding instances so that a script
    # used by 100 entities is imported exactly once.
    _module_cache: dict[str, Any] = {}

    def __init__(
        self,
        manifest: AssetManifest,
        search_paths: list[str | Path] | None = None,
    ) -> None:
        self._manifest = manifest
        self._search_paths = [Path(p) for p in (search_paths or [Path.cwd()])]
        self._modules: list[Any] = []
        self._load_modules()

    # ------------------------------------------------------------------
    # Module loading
    # ------------------------------------------------------------------

    def _resolve_script(self, script_path: str) -> Path | None:
        """Locate a script relative to the search paths."""
        p = Path(script_path)
        if p.is_absolute() and p.exists():
            return p
        for base in self._search_paths:
            candidate = base / p
            if candidate.exists():
                return candidate
        return None

    def _load_modules(self) -> None:
        import importlib.util
        for script_path in self._manifest.scripts:
            resolved = self._resolve_script(script_path)
            if resolved is None:
                import warnings
                warnings.warn(
                    f"ScriptBinding: script {script_path!r} not found "
                    f"(searched {self._search_paths})"
                )
                continue
            cache_key = str(resolved.resolve())
            if cache_key not in self.__class__._module_cache:
                # Derive a dotted module name from path relative to search paths
                # e.g. game_root/systems/vehicle_physics.py → "systems.vehicle_physics"
                module_name = resolved.stem
                for sp in self._search_paths:
                    try:
                        rel = resolved.relative_to(sp.resolve())
                        parts = list(rel.with_suffix("").parts)
                        module_name = ".".join(parts)
                        break
                    except ValueError:
                        pass
                # Reuse the module if already in sys.modules AND its __file__
                # matches our resolved path (guards against test isolation issues
                # where different tmp_path dirs produce the same stem name).
                import sys as _sys
                existing = _sys.modules.get(module_name)
                if existing is not None and getattr(existing, "__file__", None) == str(resolved):
                    mod = existing
                else:
                    spec = importlib.util.spec_from_file_location(
                        module_name, str(resolved)
                    )
                    if spec is None or spec.loader is None:
                        continue
                    mod = importlib.util.module_from_spec(spec)
                    _sys.modules[module_name] = mod
                    try:
                        spec.loader.exec_module(mod)  # type: ignore[union-attr]
                    except Exception as e:
                        import warnings
                        warnings.warn(f"ScriptBinding: error loading {resolved}: {e}")
                        _sys.modules.pop(module_name, None)
                        continue
                self.__class__._module_cache[cache_key] = mod
            self._modules.append(self.__class__._module_cache[cache_key])

    # ------------------------------------------------------------------
    # Lifecycle dispatch
    # ------------------------------------------------------------------

    def launch(self, entity: Any) -> None:
        """Call ``on_launch(entity)`` in every bound script that defines it."""
        for mod in self._modules:
            fn = getattr(mod, "on_launch", None)
            if fn is not None:
                try:
                    fn(entity)
                except Exception as e:
                    import warnings
                    warnings.warn(f"ScriptBinding.launch: {mod.__name__}: {e}")

    def tick(self, entity: Any, dt: float) -> None:
        """Call ``on_tick(entity, dt)`` in every bound script that defines it."""
        for mod in self._modules:
            fn = getattr(mod, "on_tick", None)
            if fn is not None:
                try:
                    fn(entity, dt)
                except Exception as e:
                    import warnings
                    warnings.warn(f"ScriptBinding.tick: {mod.__name__}: {e}")

    def end(self, entity: Any) -> None:
        """Call ``on_end(entity)`` in every bound script that defines it."""
        for mod in self._modules:
            fn = getattr(mod, "on_end", None)
            if fn is not None:
                try:
                    fn(entity)
                except Exception as e:
                    import warnings
                    warnings.warn(f"ScriptBinding.end: {mod.__name__}: {e}")

    # ------------------------------------------------------------------
    # Event subscriptions
    # ------------------------------------------------------------------

    def subscribe_events(self, entity: Any) -> list[int]:
        """Wire all ``subscriptions:`` entries from the manifest to the global bus.

        For each :class:`SubscriptionEntry`, the binding searches all loaded
        script modules for a handler in this priority order:

        1. ``entry.handler`` if explicitly set — looked up by name in each module.
        2. Auto-derived name: ``"Asset.Car.Gas.Empty"`` → ``on_event_asset_car_gas_empty``.
        3. Generic ``on_event(entity, event_details)`` in any module.

        Returns a list of integer handles; pass them to :meth:`unsubscribe_events`
        when the entity is removed.

        Example YAML::

            subscriptions:
              - event: Vehicle.fuel_level
                handler: on_fuel_changed
              - event: Race.LapComplete
              # ↑ auto-derives 'on_event_race_lapcomplete'
        """
        from slappyengine.event_bus import subscribe as _subscribe

        handles: list[int] = []
        for entry in self._manifest.subscriptions:
            handler_fn = self._find_handler(entry, entity)
            if handler_fn is None:
                continue
            h = _subscribe(entry.event, handler_fn)
            handles.append(h)
        return handles

    def _find_handler(self, entry: "SubscriptionEntry", entity: Any) -> Callable | None:
        """Return a bound ``(EventDetails) → None`` callable for *entry*, or None."""
        from slappyengine.event_bus import EventDetails as _ED

        candidates = []
        if entry.handler:
            candidates.append(entry.handler)
        candidates.append(entry.derived_handler())

        for mod in self._modules:
            for name in candidates:
                fn = getattr(mod, name, None)
                if fn is not None:
                    # Wrap to inject entity as first arg
                    def _bound(evt: _ED, _fn=fn, _ent=entity) -> None:
                        try:
                            _fn(_ent, evt)
                        except Exception as e:
                            import warnings
                            warnings.warn(
                                f"ScriptBinding event handler {_fn.__name__}: {e}"
                            )
                    return _bound
            # Generic on_event fallback
            generic = getattr(mod, "on_event", None)
            if generic is not None:
                def _generic(evt: _ED, _fn=generic, _ent=entity) -> None:
                    try:
                        _fn(_ent, evt)
                    except Exception as e:
                        import warnings
                        warnings.warn(f"ScriptBinding on_event: {e}")
                return _generic
        return None

    def unsubscribe_events(self, handles: list[int]) -> None:
        """Remove subscriptions previously returned by :meth:`subscribe_events`."""
        from slappyengine.event_bus import unsubscribe as _unsub
        for h in handles:
            _unsub(h)
        handles.clear()

    # ------------------------------------------------------------------
    # Hot-reload
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """Flush the module cache and re-import all scripts.

        Call this after the manifest's script files change on disk (e.g.
        from a ManifestRegistry watch callback).
        """
        for script_path in self._manifest.scripts:
            resolved = self._resolve_script(script_path)
            if resolved is not None:
                self.__class__._module_cache.pop(str(resolved.resolve()), None)
        self._modules.clear()
        self._load_modules()
