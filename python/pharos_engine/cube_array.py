from pharos_engine.render_target import RenderTarget
from pharos_engine.animation.graph import AnimationGraph
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pharos_engine.layer import Layer

class CubeArray(RenderTarget):
    def __init__(self, name: str = "", position=(0.0, 0.0), size=(64, 64)):
        super().__init__(name=name, position=position, size=size)
        self.frame_count: int = 1
        self.current_frame: int = 0
        self.fps: float = 24.0
        self._frame_timer: float = 0.0
        self.loop: bool = True
        self.playing: bool = False
        self.animation_graph: AnimationGraph | None = None

    def play(self) -> None:
        self.playing = True

    def pause(self) -> None:
        self.playing = False

    def seek(self, frame: int) -> None:
        self.current_frame = max(0, min(frame, self.frame_count - 1))

    def tick(self, dt: float) -> None:
        super().tick(dt)
        if self.playing and self.frame_count > 1:
            self._frame_timer += dt
            frames_elapsed = int(self._frame_timer * self.fps)
            if frames_elapsed > 0:
                self._frame_timer -= frames_elapsed / self.fps
                next_frame = self.current_frame + frames_elapsed
                if self.loop:
                    self.current_frame = next_frame % self.frame_count
                else:
                    self.current_frame = min(next_frame, self.frame_count - 1)
                    if self.current_frame == self.frame_count - 1:
                        self.playing = False
        if self.animation_graph is not None:
            result = self.animation_graph.update(dt)
            if result is not None:
                self.current_frame = min(result.frame_index, len(self.layers) - 1) if self.layers else 0

    @classmethod
    def from_images(cls, paths: list[str], name: str = "", fps: float = 24.0) -> "CubeArray":
        from pharos_engine.layer import Layer
        inst = cls(name=name)
        inst.fps = fps
        for path in paths:
            layer = Layer.from_image(path)
            inst.add_layer(layer)
            if inst.size == (64, 64) and layer.size:
                inst.size = layer.size
        inst.frame_count = len(paths)
        return inst

    @classmethod
    def from_video(cls, path: str, name: str = "", use_as: str = "frames",
                   max_frames: int = 256, fps: float | None = None) -> "CubeArray":
        from pharos_engine.layer import Layer
        import numpy as np
        try:
            from pharos_engine.animation.video_import import extract_frames
            frame_arrays = extract_frames(path, max_frames=max_frames)
        except ImportError as e:
            raise ImportError(f"Video import requires pip install Pharos Engine[video]: {e}") from e
        inst = cls(name=name)
        for arr in frame_arrays:
            layer = Layer.blank(arr.shape[1], arr.shape[0])
            layer._image_data = arr
            inst.add_layer(layer)
        inst.frame_count = len(frame_arrays)
        if fps is not None:
            inst.fps = fps
        if frame_arrays and inst.size == (64, 64):
            h, w = frame_arrays[0].shape[:2]
            inst.size = (w, h)
        return inst
