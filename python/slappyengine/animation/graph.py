from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Any

@dataclass
class AnimState:
    name: str
    clip_indices: list[int] = field(default_factory=list)
    loop: bool = True
    fps: float = 24.0

@dataclass
class AnimTransition:
    from_state: str
    to_state: str
    condition: Callable[[], bool] = lambda: False

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
        self._states[state.name] = state

    def add_transition(self, t: AnimTransition) -> None:
        self._transitions.append(t)

    def set_initial(self, name: str) -> None:
        self._current = name

    def update(self, dt: float) -> AnimUpdate | None:
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
