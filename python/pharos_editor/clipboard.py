"""Entity clipboard (Sprint 9 UI polish #3).

Single JSON-serialised slot for Ctrl+C / Ctrl+V of scene entities.
Nova3D had no cross-panel clipboard; every panel rolled its own copy
buffer. Pharos centralises it so a copy in the outliner can paste in
the viewport, spawn menu, or another editor window.

Backing store is a class attribute so the whole editor process shares
one slot. A future extension can push into the OS clipboard for
inter-process paste; today's scope is intra-process only.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass
class ClipboardPayload:
    """One paste-able bundle."""

    kind: str            # "entity" | "transform" | "material" | ...
    schema_version: int
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps(
            {"kind": self.kind, "schema_version": self.schema_version, "payload": self.payload},
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> "ClipboardPayload":
        obj = json.loads(raw)
        return cls(
            kind=str(obj["kind"]),
            schema_version=int(obj.get("schema_version", 1)),
            payload=dict(obj.get("payload", {})),
        )


class Clipboard:
    """Process-wide single-slot clipboard for entities + transforms."""

    _slot: ClipboardPayload | None = None

    @classmethod
    def copy(cls, payload: ClipboardPayload) -> None:
        cls._slot = payload

    @classmethod
    def paste(cls) -> ClipboardPayload | None:
        return cls._slot

    @classmethod
    def clear(cls) -> None:
        cls._slot = None

    @classmethod
    def is_empty(cls) -> bool:
        return cls._slot is None

    @classmethod
    def kind(cls) -> str | None:
        return cls._slot.kind if cls._slot else None


__all__ = ["Clipboard", "ClipboardPayload"]
