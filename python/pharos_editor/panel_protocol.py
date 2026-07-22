"""Formal panel lifecycle protocol (Nova3D flaws #1 + #4 remediation).

Nova3D shipped panels with an implicit ``build(parent_tag)`` contract
and no formal lifecycle. Layout state leaked into DearPyGui's internal
docking store; panel redraw costs were unprofiled.

Pharos formalises the contract:

    setup(context)      # once, cheap; register slots
    build(parent_tag)   # UI widgets created
    tick(dt)            # per-frame; MUST emit telemetry
    destroy()           # tear-down; explicit resource release

Every panel implements ``Panel`` (a runtime-checkable ``typing.Protocol``
so existing panels adopt gradually). ``PanelHost`` measures ``tick(dt)``
cost and emits a telemetry event when it exceeds
``BUDGET_WARN_MS`` (default 5.0 ms) for two consecutive frames.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


BUDGET_WARN_MS: float = 5.0
BUDGET_WARN_STREAK: int = 2


@runtime_checkable
class Panel(Protocol):
    """Every editor panel implements this shape."""

    #: Stable identifier, used for layout persistence + telemetry keying.
    panel_id: str

    def setup(self, context: dict[str, Any]) -> None: ...
    def build(self, parent_tag: str) -> None: ...
    def tick(self, dt: float) -> None: ...
    def destroy(self) -> None: ...


@dataclass
class PanelStats:
    """Rolling frame-time record for one panel."""

    panel_id: str
    last_tick_ms: float = 0.0
    peak_tick_ms: float = 0.0
    total_ticks: int = 0
    over_budget_streak: int = 0


class PanelHost:
    """Owns a set of panels + measures their tick cost.

    Wraps every ``panel.tick(dt)`` with a wall-clock timer, tracks a
    rolling peak, and emits telemetry when a panel exceeds the budget
    for ``BUDGET_WARN_STREAK`` consecutive frames.
    """

    def __init__(self) -> None:
        self._panels: list[Panel] = []
        self._stats: dict[str, PanelStats] = {}

    def register(self, panel: Panel) -> None:
        if not isinstance(panel, Panel):
            raise TypeError(
                f"{type(panel).__name__} does not implement pharos_editor.Panel"
            )
        self._panels.append(panel)
        self._stats[panel.panel_id] = PanelStats(panel_id=panel.panel_id)

    def tick_all(self, dt: float) -> None:
        for p in self._panels:
            stats = self._stats[p.panel_id]
            t0 = time.perf_counter()
            try:
                p.tick(dt)
            except Exception as exc:
                # Never let one panel's tick take down the frame.
                from pharos_editor.errors import route

                route(exc, f"panel.{p.panel_id}.tick")
                continue
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            stats.last_tick_ms = elapsed_ms
            stats.peak_tick_ms = max(stats.peak_tick_ms, elapsed_ms)
            stats.total_ticks += 1
            if elapsed_ms > BUDGET_WARN_MS:
                stats.over_budget_streak += 1
                if stats.over_budget_streak >= BUDGET_WARN_STREAK:
                    self._emit_budget_warning(p.panel_id, elapsed_ms)
            else:
                stats.over_budget_streak = 0

    def stats(self, panel_id: str) -> PanelStats | None:
        return self._stats.get(panel_id)

    def all_stats(self) -> list[PanelStats]:
        return list(self._stats.values())

    def _emit_budget_warning(self, panel_id: str, elapsed_ms: float) -> None:
        try:
            from pharos_engine.telemetry import emit as _emit

            _emit(
                "pharos.editor.panel.slow",
                {"panel_id": panel_id, "tick_ms": elapsed_ms, "budget_ms": BUDGET_WARN_MS},
            )
        except Exception:
            # Telemetry may not be loaded in stripped-down test envs.
            pass  # noqa: pharos-errors-lint (deliberate: telemetry is best-effort)


__all__ = ["Panel", "PanelHost", "PanelStats", "BUDGET_WARN_MS", "BUDGET_WARN_STREAK"]
