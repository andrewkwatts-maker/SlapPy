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

    def __init__(self, themes_dir: Path | None = None,
                 user_themes_dir: Path | None = None) -> None:
        self._dir = themes_dir or Path(__file__).parent
        # Sprint 7 extension architecture: also scan `~/.pharos/themes/`
        # (or the caller-provided override) so user-installed / plugin
        # themes surface without touching the wheel.
        self._user_dir = user_themes_dir or (Path.home() / ".pharos" / "themes")
        self._themes: dict[str, Theme] = {}
        self.reload()

    def reload(self) -> None:
        """Re-scan the shipped + user theme directories.

        Called on startup + hot-reload. When a user theme has the same
        `name` as a shipped theme, the user copy wins — that's the
        override contract for extension authors.
        """
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise ImportError(
                "pharos_editor.themes requires PyYAML "
                "(pip install pharos-editor pulls it transitively)"
            ) from exc
        found: dict[str, Theme] = {}

        def _load_dir(directory: Path) -> None:
            if not directory.is_dir():
                return
            for path in sorted(directory.glob("*.yaml")):
                if path.name.startswith("_"):
                    continue
                try:
                    with path.open("r", encoding="utf-8") as fh:
                        raw = yaml.safe_load(fh)
                except Exception:
                    continue
                if not isinstance(raw, dict) or "name" not in raw:
                    continue
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

        _load_dir(self._dir)
        _load_dir(self._user_dir)
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


def list_theme_ids() -> list[str]:
    """Return every discoverable theme name (shipped + user).

    Called by :mod:`pharos_engine.net.http_bridge` for the
    ``GET /api/themes`` endpoint.
    """
    return ThemeCatalog().names()


__all__ = ["Theme", "ThemeCatalog", "list_theme_ids"]
