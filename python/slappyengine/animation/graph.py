from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Callable, Any

@dataclass
class AnimState:
    name: str
    clip_indices: list[int] = field(default_factory=list)
    loop: bool = True
    fps: float = 24.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError(
                f"AnimState.name must be a non-empty str; got {self.name!r}"
            )
        if not isinstance(self.clip_indices, list):
            raise TypeError(
                "AnimState.clip_indices must be a list; "
                f"got {type(self.clip_indices).__name__}"
            )
        if not all(isinstance(i, int) and not isinstance(i, bool) and i >= 0
                   for i in self.clip_indices):
            raise ValueError(
                "AnimState.clip_indices must contain non-negative ints"
            )
        if not isinstance(self.fps, (int, float)) or isinstance(self.fps, bool):
            raise TypeError(
                f"AnimState.fps must be numeric; got {type(self.fps).__name__}"
            )
        if not math.isfinite(self.fps) or self.fps <= 0:
            raise ValueError(
                f"AnimState.fps must be a finite > 0; got {self.fps!r}"
            )

@dataclass
class AnimTransition:
    from_state: str
    to_state: str
    condition: Callable[[], bool] = lambda: False

    def __post_init__(self) -> None:
        if not isinstance(self.from_state, str) or not self.from_state:
            raise ValueError(
                f"AnimTransition.from_state must be a non-empty str; "
                f"got {self.from_state!r}"
            )
        if not isinstance(self.to_state, str) or not self.to_state:
            raise ValueError(
                f"AnimTransition.to_state must be a non-empty str; "
                f"got {self.to_state!r}"
            )
        if not callable(self.condition):
            raise TypeError(
                "AnimTransition.condition must be callable; "
                f"got {type(self.condition).__name__}"
            )

@dataclass
class AnimUpdate:
    state_name: str
    frame_index: int
    blend_fraction: float  # 0.0–1.0 within frame interval

class AnimationGraph:
    def __init__(self):
        self._states: dict[str, AnimState] = {}
        self._transitions: list[AnimTransition] = []
        self._current: str | None = None
        self._frame_timer: float = 0.0
        self._current_frame: int = 0

    def add_state(self, state: AnimState) -> None:
        if not isinstance(state, AnimState):
            raise TypeError(
                "AnimationGraph.add_state: state must be AnimState; "
                f"got {type(state).__name__}"
            )
        self._states[state.name] = state

    def add_transition(self, t: AnimTransition) -> None:
        if not isinstance(t, AnimTransition):
            raise TypeError(
                "AnimationGraph.add_transition: t must be AnimTransition; "
                f"got {type(t).__name__}"
            )
        self._transitions.append(t)

    def set_initial(self, name: str) -> None:
        if not isinstance(name, str) or not name:
            raise ValueError(
                f"AnimationGraph.set_initial: name must be a non-empty str; "
                f"got {name!r}"
            )
        if name not in self._states:
            raise ValueError(
                f"AnimationGraph.set_initial: unknown state {name!r}. "
                f"Known: {sorted(self._states)}"
            )
        self._current = name

    def update(self, dt: float) -> AnimUpdate | None:
        if not isinstance(dt, (int, float)) or isinstance(dt, bool):
            raise TypeError(
                f"AnimationGraph.update: dt must be numeric; "
                f"got {type(dt).__name__}"
            )
        if not math.isfinite(dt) or dt < 0:
            raise ValueError(
                f"AnimationGraph.update: dt must be finite ≥ 0; got {dt!r}"
            )
        if self._current is None:
            return None
        for t in self._transitions:
            if t.from_state == self._current and t.condition():
                self._current = t.to_state
                self._current_frame = 0
                self._frame_timer = 0.0
                break

        state = self.current_state
        if state:
            fps = state.fps
            self._frame_timer += dt * fps
            total_frames = len(state.clip_indices) if state.clip_indices else 1
            elapsed = int(self._frame_timer)
            blend = self._frame_timer - elapsed
            if elapsed > 0:
                self._frame_timer -= elapsed
                if state.loop:
                    self._current_frame = (self._current_frame + elapsed) % total_frames
                else:
                    self._current_frame = min(self._current_frame + elapsed, total_frames - 1)
            if state.clip_indices:
                frame_idx = state.clip_indices[self._current_frame]
            else:
                frame_idx = self._current_frame
            return AnimUpdate(
                state_name=self._current,
                frame_index=frame_idx,
                blend_fraction=blend,
            )
        return AnimUpdate(state_name=self._current, frame_index=0, blend_fraction=0.0)

    def tick(self, dt: float) -> str | None:
        result = self.update(dt)
        return result.state_name if result else None

    @property
    def current_state(self) -> AnimState | None:
        return self._states.get(self._current) if self._current else None
