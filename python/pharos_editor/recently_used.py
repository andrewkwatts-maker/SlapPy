"""Recently-used spawn cards (Sprint 9 UI polish #6).

Tracks the last 5 spawn actions per project so the spawn modal can
surface them at the top. Persists to
``~/.pharos/recent_spawns.json`` so it survives editor restarts.

Nova3D didn't remember spawn history; every open of the modal reset
the user to A-Z order. Pharos remembers.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path


DEFAULT_MAX_ITEMS: int = 5


class RecentSpawns:
    """Bounded per-project MRU list of spawn card IDs."""

    def __init__(self, path: Path | None = None, max_items: int = DEFAULT_MAX_ITEMS) -> None:
        self.path = path or (Path.home() / ".pharos" / "recent_spawns.json")
        self.max_items = max_items
        self._store: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        if not self.path.exists():
            return {}
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return {str(k): [str(x) for x in v][: self.max_items] for k, v in data.items()}
        except (OSError, ValueError):
            pass  # noqa: pharos-errors-lint (corrupt file -> start fresh)
        return {}

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._store, indent=2), encoding="utf-8")
        except OSError as exc:
            from pharos_editor.errors import route
            route(exc, "recent_spawns.save", level="warn")

    # -- API --

    def record(self, project: str, spawn_id: str) -> None:
        """Push ``spawn_id`` onto the MRU list for ``project``."""
        lst = self._store.setdefault(project, [])
        if spawn_id in lst:
            lst.remove(spawn_id)
        lst.insert(0, spawn_id)
        del lst[self.max_items :]
        self._save()

    def get(self, project: str) -> list[str]:
        return list(self._store.get(project, []))

    def clear(self, project: str) -> None:
        if project in self._store:
            self._store.pop(project)
            self._save()


__all__ = ["RecentSpawns", "DEFAULT_MAX_ITEMS"]
