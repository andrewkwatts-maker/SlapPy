from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class ControlPoint:
    name: str
    uv: tuple[float, float]       # position on asset texture (0–1)
    parent: str | None = None     # parent control point name
    constraint: str = "free"      # "free" | "hinge" | "slider"
    min_angle: float = -180.0
    max_angle: float = 180.0

class ProceduralRig:
    """Dot-based procedural rigging. IK solver implemented in M7 (Rust)."""

    def __init__(self):
        self._points: dict[str, ControlPoint] = {}

    def add_point(self, cp: ControlPoint) -> None:
        self._points[cp.name] = cp

    def remove_point(self, name: str) -> None:
        self._points.pop(name, None)

    def get_chain(self, root_name: str, tip_name: str) -> list[ControlPoint]:
        chain = []
        current = self._points.get(tip_name)
        while current is not None:
            chain.append(current)
            if current.name == root_name:
                break
            current = self._points.get(current.parent) if current.parent else None
        chain.reverse()
        return chain

    def solve_ik(self, target_positions: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
        try:
            from pharos_engine import _core
            has_core = True
        except ImportError:
            has_core = False

        result: dict[str, tuple[float, float]] = {}
        for name, cp in self._points.items():
            result[name] = cp.uv

        for tip_name, target_uv in target_positions.items():
            if tip_name not in self._points:
                continue
            root = self._find_root(tip_name)
            if root is None:
                continue
            chain = self.get_chain(root, tip_name)
            if len(chain) < 2:
                continue

            positions = [result.get(cp.name, cp.uv) for cp in chain]

            if has_core:
                lengths = _core.compute_bone_lengths(positions)
                solved = _core.solve_ik(positions, target_uv, lengths)
            else:
                solved = self._simple_stretch(positions, target_uv)

            for cp, pos in zip(chain, solved):
                result[cp.name] = pos

        return result

    def _find_root(self, tip_name: str) -> str | None:
        visited = set()
        current = self._points.get(tip_name)
        while current is not None:
            if current.name in visited:
                return None  # cycle
            visited.add(current.name)
            if current.parent is None or current.parent not in self._points:
                return current.name
            current = self._points.get(current.parent)
        return None

    def _simple_stretch(self, positions: list[tuple], target: tuple) -> list[tuple]:
        if not positions:
            return positions
        result = list(positions)
        result[-1] = target
        return result

    def apply_to(self, cube_array, pose: dict[str, tuple[float, float]]) -> None:
        for name, uv in pose.items():
            if name in self._points:
                self._points[name].uv = uv

    @property
    def points(self) -> list[ControlPoint]:
        return list(self._points.values())
