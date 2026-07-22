"""Layout persistence schema (Nova3D flaw #1 remediation).

Nova3D leaked layout state into DearPyGui's internal docking store;
positions were lost across ImGui version bumps. Pharos serialises
layouts to a validated YAML file whose schema is framework-agnostic.

Storage lives at ``~/.pharos/layout.yaml``. The engine writes it on
shutdown and reads it on startup; a broken file is quarantined
(renamed ``layout.yaml.bad-<timestamp>``) rather than silently
discarded, so users can inspect what went wrong.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


LAYOUT_SCHEMA_VERSION: str = "1"


@dataclass
class PanelPosition:
    """A panel's location + dock state at serialisation time."""

    panel_id: str
    dock: str        # "floating" | "left" | "right" | "top" | "bottom" | "center"
    x: int = 0
    y: int = 0
    width: int = 320
    height: int = 240
    visible: bool = True
    z_order: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "panel_id": self.panel_id,
            "dock": self.dock,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "visible": self.visible,
            "z_order": self.z_order,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PanelPosition":
        # Explicit dict->dataclass rather than **d so an unexpected key
        # doesn't crash the load — schema forward-compatibility.
        return cls(
            panel_id=str(d["panel_id"]),
            dock=str(d.get("dock", "floating")),
            x=int(d.get("x", 0)),
            y=int(d.get("y", 0)),
            width=int(d.get("width", 320)),
            height=int(d.get("height", 240)),
            visible=bool(d.get("visible", True)),
            z_order=int(d.get("z_order", 0)),
        )


@dataclass
class Layout:
    schema_version: str = LAYOUT_SCHEMA_VERSION
    theme: str = "teengirl_notebook"
    window_width: int = 1400
    window_height: int = 900
    panels: list[PanelPosition] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "theme": self.theme,
            "window": {"width": self.window_width, "height": self.window_height},
            "panels": [p.to_dict() for p in self.panels],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Layout":
        window = d.get("window", {})
        panels_raw = d.get("panels", []) or []
        return cls(
            schema_version=str(d.get("schema_version", LAYOUT_SCHEMA_VERSION)),
            theme=str(d.get("theme", "teengirl_notebook")),
            window_width=int(window.get("width", 1400)),
            window_height=int(window.get("height", 900)),
            panels=[PanelPosition.from_dict(p) for p in panels_raw if "panel_id" in p],
        )


class LayoutStore:
    """Load / save / quarantine layouts on disk."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (Path.home() / ".pharos" / "layout.yaml")

    def load(self) -> Layout:
        if not self.path.exists():
            return Layout()
        try:
            import yaml  # type: ignore

            with self.path.open("r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh) or {}
        except Exception as exc:
            self._quarantine(reason=f"parse-failure: {exc}")
            return Layout()
        try:
            return Layout.from_dict(raw)
        except Exception as exc:
            self._quarantine(reason=f"schema-failure: {exc}")
            return Layout()

    def save(self, layout: Layout) -> None:
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            from pharos_editor.errors import route

            route(exc, "layout_store.save (PyYAML missing)")
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(layout.to_dict(), fh, sort_keys=False)

    def _quarantine(self, reason: str) -> None:
        stamp = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%S")
        bad = self.path.with_suffix(f".yaml.bad-{stamp}")
        try:
            self.path.rename(bad)
        except OSError:
            # If we can't even rename, dump the reason next to it and give up.
            log = self.path.with_suffix(".yaml.error")
            try:
                log.write_text(reason, encoding="utf-8")
            except OSError:
                pass  # noqa: pharos-errors-lint (nothing to recover to at this point)


__all__ = [
    "LAYOUT_SCHEMA_VERSION",
    "PanelPosition",
    "Layout",
    "LayoutStore",
]
