from __future__ import annotations

from typing import Any

__all__: list[str] = ["Entity"]

class Entity:
    id: str
    name: str
    position: tuple[float, float]
    rotation: float
    scale: float
    tags: set[str]
    residency: str
    collision_shape: Any | None
    strata_layer: int
    z_height: float
    z_layer: Any | None  # ZLayer | None
    z_collision_shape: Any | None  # ZAABBShape | None
    data: Any | None  # DataComponent | None

    def __init__(
        self,
        name: str = "",
        position: tuple[float, float] = (0.0, 0.0),
    ) -> None: ...

    @classmethod
    def on_compile(cls) -> None: ...

    def on_create(self) -> None: ...
    def on_destroy(self) -> None: ...
    def on_spawn(self) -> None: ...
    def on_despawn(self) -> None: ...

    def tick(self, dt: float) -> None: ...
    def bind(self, when: Any, then: Any, once: bool = True) -> None: ...

    def attach_script(self, script: Any) -> None: ...
    def add_emitter(self, emitter: Any) -> None: ...

    def add_component(self, component: Any) -> Any: ...  # Component -> Component
    def get_component(self, component_type: type) -> Any | None: ...
    def remove_component(self, component_type: type) -> None: ...
