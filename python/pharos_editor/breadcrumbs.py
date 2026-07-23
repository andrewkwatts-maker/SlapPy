"""Content-browser breadcrumb navigation (Sprint 9 UI polish #5).

Home / Back / Forward / Up + search + path bar. Nova3D shipped a flat
content pane with no navigation history; Pharos gives it the browser
model users expect from every DCC + file manager.

The model is UI-agnostic — the panel calls the model, the model
returns the resulting path, the panel refreshes.
"""
from __future__ import annotations

from pathlib import Path


class BreadcrumbHistory:
    """Back/forward stack + current path pointer."""

    def __init__(self, root: Path | None = None, initial: Path | None = None) -> None:
        # Defensive default: when the shell hasn't opened a project yet
        # (pharos-edit with no project path), fall back to the current
        # working directory so the content-browser still renders.
        if root is None:
            root = Path.cwd()
        self.root = root.resolve()
        current = (initial or root).resolve()
        # Store paths as absolute to avoid ambiguity.
        self._back: list[Path] = []
        self._forward: list[Path] = []
        self._current: Path = current

    def current(self) -> Path:
        return self._current

    def navigate(self, dest: Path) -> Path:
        """Move to ``dest``. Clears forward history."""
        target = dest.resolve()
        if target != self._current:
            self._back.append(self._current)
            self._current = target
            self._forward.clear()
        return self._current

    def go_back(self) -> Path:
        if not self._back:
            return self._current
        self._forward.append(self._current)
        self._current = self._back.pop()
        return self._current

    def go_forward(self) -> Path:
        if not self._forward:
            return self._current
        self._back.append(self._current)
        self._current = self._forward.pop()
        return self._current

    def go_up(self) -> Path:
        parent = self._current.parent.resolve()
        if parent == self._current or self._current == self.root:
            return self._current
        return self.navigate(parent)

    def go_home(self) -> Path:
        return self.navigate(self.root)

    def crumbs(self) -> list[Path]:
        """Return the crumb list from root to current, inclusive."""
        try:
            rel = self._current.relative_to(self.root)
        except ValueError:
            # If someone navigated outside the root, don't crash — just
            # return current as its own single crumb.
            return [self._current]
        parts = [self.root] + [self.root / Path(*rel.parts[: i + 1]) for i in range(len(rel.parts))]
        return parts

    def can_back(self) -> bool:
        return bool(self._back)

    def can_forward(self) -> bool:
        return bool(self._forward)


__all__ = ["BreadcrumbHistory"]
