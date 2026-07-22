"""``EntityClipboard`` — copy/paste buffer for editor entities.

A tiny stateful holder that lets right-click context menus, keyboard
shortcuts (Ctrl+C / Ctrl+V), and the outliner all reference the same
"most recently copied entity" across panels. Not persisted to disk — the
buffer is process-lifetime only.

The clipboard stores a lightweight snapshot dict (dataclass fields,
transform, name) rather than the entity object itself; paste operations
construct a fresh entity from the snapshot and let the caller add it to
the world. The clipboard is single-slot but supports multi-entity
snapshots for the multi-select flow.

Design provenance: ``docs/sprint_plan_2026_06_03.md`` §5 (copy/paste).
"""
from __future__ import annotations

import copy
import dataclasses
from typing import Any

from pharos_engine._validation import validate_str


def snapshot_entity(entity: Any) -> dict[str, Any]:
    """Return a shallow-but-safe copy of *entity*'s public state.

    Handles three shapes:

    * dataclass instances — every field name / value pair.
    * plain objects — every non-underscore ``vars()`` attribute.
    * dict — copied as-is.

    Callable / module / class fields are stripped so the snapshot round-
    trips through pickle-free contexts (the editor's undo stack ships
    them across worker threads on Windows).
    """
    if entity is None:
        return {}
    if isinstance(entity, dict):
        return copy.deepcopy(entity)
    if dataclasses.is_dataclass(entity) and not isinstance(entity, type):
        out: dict[str, Any] = {}
        for f in dataclasses.fields(entity):
            val = getattr(entity, f.name, None)
            if callable(val):
                continue
            try:
                out[f.name] = copy.deepcopy(val)
            except Exception:
                out[f.name] = val
        # Preserve the concrete class so the paste-site can rebuild.
        out["__cls__"] = type(entity).__name__
        return out
    # Plain object with __dict__ — collect public attributes.
    snap: dict[str, Any] = {}
    for k, v in vars(entity).items():
        if k.startswith("_"):
            continue
        if callable(v):
            continue
        try:
            snap[k] = copy.deepcopy(v)
        except Exception:
            snap[k] = v
    snap["__cls__"] = type(entity).__name__
    return snap


class EntityClipboard:
    """Copy/paste buffer holding a list of entity snapshots.

    The clipboard supports:

    * :meth:`copy` — replace the buffer with fresh snapshots.
    * :meth:`cut` — snapshot + return an "erase" callback the caller
      chains into the world.
    * :meth:`paste` — return a deep-copy of the current snapshots.

    The buffer is not disk-persisted; a fresh editor session starts empty.
    Copy events increment :attr:`generation` so consumers (status bar,
    inspector) can flash a "copied" hint.
    """

    def __init__(self) -> None:
        self._snapshots: list[dict[str, Any]] = []
        self._generation: int = 0
        self._last_action: str = ""

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        return len(self._snapshots)

    def is_empty(self) -> bool:
        return not self._snapshots

    @property
    def generation(self) -> int:
        """Monotonic counter — bumped on every :meth:`copy` / :meth:`cut`."""
        return self._generation

    @property
    def last_action(self) -> str:
        """One of ``""`` / ``"copy"`` / ``"cut"`` / ``"paste"`` / ``"clear"``."""
        return self._last_action

    def snapshots(self) -> list[dict[str, Any]]:
        """Return a deep-copy of the stored snapshots."""
        return [copy.deepcopy(s) for s in self._snapshots]

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def copy(self, entities: list[Any] | Any) -> int:
        """Replace the buffer with snapshots of *entities*.

        Returns the number of snapshots stored.
        """
        if entities is None:
            self.clear()
            return 0
        if not isinstance(entities, (list, tuple)):
            entities = [entities]
        snapshots: list[dict[str, Any]] = []
        for ent in entities:
            snap = snapshot_entity(ent)
            if snap:
                snapshots.append(snap)
        self._snapshots = snapshots
        self._generation += 1
        self._last_action = "copy"
        return len(snapshots)

    def cut(self, entities: list[Any] | Any) -> int:
        """Snapshot *entities* + mark the action as ``cut``.

        The caller is still responsible for deleting the entities from
        the world — this method only stashes the copies.
        """
        count = self.copy(entities)
        self._last_action = "cut"
        return count

    def clear(self) -> None:
        self._snapshots.clear()
        self._generation += 1
        self._last_action = "clear"

    def paste(self, name_suffix: str = " (paste)") -> list[dict[str, Any]]:
        """Return deep-copies of the stored snapshots with names suffixed.

        The suffix is applied to any ``"name"`` field so the paste-site
        can tell copies from originals in the outliner.
        """
        validate_str(
            "name_suffix", "EntityClipboard.paste", name_suffix,
            allow_empty=True,
        )
        out: list[dict[str, Any]] = []
        for snap in self._snapshots:
            fresh = copy.deepcopy(snap)
            if isinstance(fresh.get("name"), str) and name_suffix:
                fresh["name"] = f"{fresh['name']}{name_suffix}"
            out.append(fresh)
        if out:
            self._last_action = "paste"
        return out


# ---------------------------------------------------------------------------
# Module-level singleton — the editor shell binds a single clipboard so
# every panel shares the same buffer.
# ---------------------------------------------------------------------------


_ACTIVE_CLIPBOARD: EntityClipboard | None = None


def get_active_clipboard() -> EntityClipboard:
    """Return the process-wide :class:`EntityClipboard` singleton.

    Constructs one lazily on first access. Tests can call
    :func:`reset_active_clipboard` to drop the buffer between runs.
    """
    global _ACTIVE_CLIPBOARD
    if _ACTIVE_CLIPBOARD is None:
        _ACTIVE_CLIPBOARD = EntityClipboard()
    return _ACTIVE_CLIPBOARD


def reset_active_clipboard() -> None:
    """Drop the singleton so the next call to :func:`get_active_clipboard` rebuilds."""
    global _ACTIVE_CLIPBOARD
    _ACTIVE_CLIPBOARD = None


__all__ = [
    "EntityClipboard",
    "get_active_clipboard",
    "reset_active_clipboard",
    "snapshot_entity",
]
