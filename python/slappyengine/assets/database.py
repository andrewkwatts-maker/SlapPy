"""
Central asset registry with hot-reload and extensible import handlers.

Usage:
    from slappyengine.assets.database import AssetDatabase

    db = AssetDatabase.instance()
    asset = db.load("Content/Assets/sprites/player.png")  # returns Layer2D
    db.register_handler(".tmx", my_tilemap_loader)         # extensible
"""
from __future__ import annotations
import os
import hashlib
import time
from pathlib import Path
from typing import Callable, Any


class AssetRecord:
    __slots__ = ("path", "asset", "asset_type", "size_bytes", "last_modified", "thumbnail_path")

    def __init__(self, path: str, asset: Any, asset_type: str):
        self.path = path
        self.asset = asset
        self.asset_type = asset_type
        stat = os.stat(path)
        self.size_bytes = stat.st_size
        self.last_modified = stat.st_mtime
        self.thumbnail_path: str | None = None


class AssetDatabase:
    """Singleton asset registry. Call AssetDatabase.instance() to get the shared instance."""

    _instance: "AssetDatabase | None" = None

    @classmethod
    def instance(cls) -> "AssetDatabase":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._registry: dict[str, AssetRecord] = {}   # abs path → record
        self._handlers: dict[str, Callable] = {}       # ext → loader fn
        self._watch_dirs: list[str] = []
        self._observer = None
        self._register_defaults()

    def _register_defaults(self):
        # Image → Layer2D
        for ext in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tga", ".webp"):
            self._handlers[ext] = self._load_image
        # Config → dict
        for ext in (".yml", ".yaml"):
            self._handlers[ext] = self._load_yaml
        # .slap → Asset
        self._handlers[".slap"] = self._load_slap

    # --- Public API ---

    def load(self, path: str | Path, force_reload: bool = False) -> Any:
        """Load asset at path. Returns cached result if up-to-date."""
        abs_path = str(Path(path).resolve())
        if not force_reload and abs_path in self._registry:
            rec = self._registry[abs_path]
            try:
                if os.stat(abs_path).st_mtime == rec.last_modified:
                    return rec.asset
            except OSError:
                pass
        return self._import(abs_path)

    def register_handler(self, ext: str, loader: Callable) -> None:
        """Register a custom loader for a file extension (e.g. '.tmx')."""
        self._handlers[ext.lower()] = loader

    def watch(self, directory: str | Path) -> None:
        """Watch a directory for changes and auto-reload assets."""
        directory = str(Path(directory).resolve())
        if directory not in self._watch_dirs:
            self._watch_dirs.append(directory)
            self._start_watcher(directory)

    def all_records(self) -> list[AssetRecord]:
        return list(self._registry.values())

    def get_record(self, path: str | Path) -> AssetRecord | None:
        return self._registry.get(str(Path(path).resolve()))

    # --- Internal ---

    def _import(self, abs_path: str) -> Any:
        ext = Path(abs_path).suffix.lower()
        loader = self._handlers.get(ext)
        if loader is None:
            raise ValueError(f"No asset handler for extension '{ext}'. "
                           f"Register one with AssetDatabase.instance().register_handler('{ext}', fn)")
        asset = loader(abs_path)
        asset_type = ext.lstrip(".")
        self._registry[abs_path] = AssetRecord(abs_path, asset, asset_type)
        return asset

    def _load_image(self, path: str):
        from slappyengine.layer import Layer
        return Layer.from_image(path)

    def _load_yaml(self, path: str) -> dict:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}

    def _load_slap(self, path: str):
        from slappyengine.asset import Asset
        return Asset.load(path) if hasattr(Asset, "load") else path

    def _start_watcher(self, directory: str):
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            db = self
            class _Handler(FileSystemEventHandler):
                def on_modified(self, event):
                    if not event.is_directory:
                        db._on_file_changed(event.src_path)

            if self._observer is None:
                self._observer = Observer()
                self._observer.daemon = True
                self._observer.start()
            self._observer.schedule(_Handler(), directory, recursive=True)
        except ImportError:
            pass  # watchdog optional

    def _on_file_changed(self, path: str):
        abs_path = str(Path(path).resolve())
        if abs_path in self._registry:
            try:
                self._import(abs_path)
            except Exception:
                pass
