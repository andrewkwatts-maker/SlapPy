"""Theme catalog (Nova3D flaws #2 + #9 remediation).

Themes are YAML files under this directory (``*.yaml``). Every editor
palette is data; the ``ThemeCatalog`` loads them once at startup and
supports hot-reload — flip a theme at runtime without an editor
restart. Colour-blind safe + large-text themes ship in the default
set (Nova3D shipped a single hard-coded dark palette, no options).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Theme:
    name: str
    display_name: str
    description: str
    tags: list[str]
    palette: dict[str, list[int]]
    typography: dict[str, Any]
    geometry: dict[str, int]
    accessibility: dict[str, Any] = field(default_factory=dict)


class ThemeCatalog:
    """Discovers + loads all themes under this directory."""

    def __init__(self, themes_dir: Path | None = None) -> None:
        self._dir = themes_dir or Path(__file__).parent
        self._themes: dict[str, Theme] = {}
        self.reload()

    def reload(self) -> None:
        """Re-scan the directory. Called on startup + hot-reload."""
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pharos_editor.themes requires PyYAML "
                "(pip install pharos-editor pulls it transitively)"
            ) from exc
        found: dict[str, Theme] = {}
        for path in sorted(self._dir.glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            with path.open("r", encoding="utf-8") as fh:
                raw = yaml.safe_load(fh)
            found[raw["name"]] = Theme(
                name=raw["name"],
                display_name=raw.get("display_name", raw["name"]),
                description=raw.get("description", ""),
                tags=raw.get("tags", []),
                palette=raw.get("palette", {}),
                typography=raw.get("typography", {}),
                geometry=raw.get("geometry", {}),
                accessibility=raw.get("accessibility", {}),
            )
        self._themes = found

    def names(self) -> list[str]:
        return sorted(self._themes.keys())

    def get(self, name: str) -> Theme:
        return self._themes[name]

    def default(self) -> Theme:
        # teengirl_notebook is the Pharos default per the plan; fall
        # back to the first alphabetical name if that theme was removed
        # by the user.
        if "teengirl_notebook" in self._themes:
            return self._themes["teengirl_notebook"]
        return next(iter(self._themes.values()))


__all__ = ["Theme", "ThemeCatalog"]
