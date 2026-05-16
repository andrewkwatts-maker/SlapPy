from playslap.entity import Entity
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from playslap.layer import Layer
    from playslap.post_process.chain import PostProcessChain

class RenderTarget(Entity):
    def __init__(self, name: str = "", position=(0.0, 0.0), size=(64, 64)):
        super().__init__(name=name, position=position)
        self.size: tuple[int, int] = size     # (width, height) in pixels
        self.layers: list["Layer"] = []
        self.visible: bool = True
        self.z_order: float = 0.0            # painter's order in scene
        self.post_process: "PostProcessChain | None" = None

    def add_layer(self, layer: "Layer") -> "Layer":
        layer.entity = self
        self.layers.append(layer)
        return layer

    def remove_layer(self, layer: "Layer") -> None:
        self.layers.remove(layer)

    def tick(self, dt: float) -> None:
        super().tick(dt)
        for layer in self.layers:
            layer.tick(dt)
