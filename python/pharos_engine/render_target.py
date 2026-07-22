from pharos_engine.entity import Entity
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from pharos_engine.layer import Layer
    from pharos_engine.post_process.chain import PostProcessChain

class RenderTarget(Entity):
    def __init__(self, name: str = "", position=(0.0, 0.0), size=(64, 64)):
        super().__init__(name=name, position=position)
        self.size: tuple[int, int] = size     # (width, height) in pixels
        self.layers: list["Layer"] = []
        self.visible: bool = True
        self.z_order: float = 0.0            # painter's order in scene
        self.post_process: "PostProcessChain | None" = None

    def add_layer(self, layer: "Layer") -> "Layer":
        # Defensive: if a subclass with an unusual MRO (e.g. Observable mixin
        # short-circuiting the cooperative chain in older engine builds) skips
        # RenderTarget.__init__ but still calls add_layer, materialise the
        # backing list on first touch rather than raising AttributeError.
        if not hasattr(self, "layers"):
            self.layers = []
        layer.entity = self
        self.layers.append(layer)
        return layer

    def remove_layer(self, layer: "Layer") -> None:
        if not hasattr(self, "layers"):
            self.layers = []
        self.layers.remove(layer)

    def tick(self, dt: float) -> None:
        super().tick(dt)
        for layer in self.layers:
            layer.tick(dt)
