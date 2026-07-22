"""Multi-select model (Sprint 9 UI polish #4).

Nova3D shipped single-select in the outliner. Pharos ships:

- Ctrl+click: toggle one entity in the selection
- Shift+click: range-select from the anchor
- Click-in-empty: clear selection

The model is transport-agnostic — panels feed it click events + entity
IDs; it emits change notifications. Viewport gizmos + property
inspector subscribe to the model to know "what's selected right now".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable


@dataclass
class Selection:
    """Ordered set of currently-selected entity IDs."""

    order: list[str] = field(default_factory=list)
    anchor: str | None = None  # for shift-range

    def clear(self) -> None:
        self.order.clear()
        self.anchor = None

    def contains(self, eid: str) -> bool:
        return eid in self.order

    def add(self, eid: str) -> None:
        if eid not in self.order:
            self.order.append(eid)

    def remove(self, eid: str) -> None:
        if eid in self.order:
            self.order.remove(eid)

    def toggle(self, eid: str) -> None:
        if self.contains(eid):
            self.remove(eid)
        else:
            self.add(eid)

    def set_single(self, eid: str) -> None:
        self.order = [eid]
        self.anchor = eid

    def count(self) -> int:
        return len(self.order)


class MultiSelectModel:
    """Owner of the current selection + click-event dispatcher."""

    def __init__(self) -> None:
        self.selection = Selection()
        self._observers: list[Callable[[Selection], None]] = []

    # -- click events --

    def handle_click(
        self,
        entity_id: str,
        *,
        shift: bool,
        ctrl: bool,
        siblings: Iterable[str],
    ) -> None:
        """Process a click on ``entity_id`` given modifier state.

        ``siblings`` is the ordered list the panel is showing — needed
        for the shift-range selection to know what "between anchor and
        clicked" means.
        """
        if ctrl:
            self.selection.toggle(entity_id)
            self.selection.anchor = entity_id
        elif shift and self.selection.anchor:
            self._range_select(entity_id, siblings)
        else:
            self.selection.set_single(entity_id)
        self._notify()

    def handle_click_empty(self) -> None:
        self.selection.clear()
        self._notify()

    # -- range selection --

    def _range_select(self, entity_id: str, siblings: Iterable[str]) -> None:
        sibs = list(siblings)
        try:
            a = sibs.index(self.selection.anchor or "")
            b = sibs.index(entity_id)
        except ValueError:
            self.selection.set_single(entity_id)
            return
        lo, hi = min(a, b), max(a, b)
        for i in range(lo, hi + 1):
            self.selection.add(sibs[i])

    # -- observers --

    def observe(self, cb: Callable[[Selection], None]) -> None:
        self._observers.append(cb)

    def _notify(self) -> None:
        for cb in list(self._observers):
            try:
                cb(self.selection)
            except Exception as exc:
                from pharos_editor.errors import route
                route(exc, "multiselect.observer")


__all__ = ["Selection", "MultiSelectModel"]
