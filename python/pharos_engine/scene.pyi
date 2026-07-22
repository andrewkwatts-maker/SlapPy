from __future__ import annotations

from typing import Any

from pharos_engine.entity import Entity

__all__: list[str] = ["Scene", "SceneComputeAPI", "DecalSystem"]

class Scene:
    name: str
    camera: Any | None  # Camera | None
    post_process: list[Any]
    post_process_chain: Any | None
    compute: SceneComputeAPI | None
    decals: DecalSystem | None
    region_effects: list[Any]
    landscape: Any | None
    collision: Any  # CollisionManager
    strata: Any | None  # StrataWorld | None
    fluid: Any | None  # GlobalFluidSim | None
    bus: Any  # EventBus
    events: Any  # EventBus

    def __init__(self, name: str = "Scene") -> None: ...

    def add(self, entity: Entity) -> Entity: ...
    def remove(self, entity: Entity) -> None: ...
    def get(self, entity_id: str) -> Entity | None: ...

    def find_by_name(self, name: str) -> list[Entity]: ...
    def find_by_tag(self, tag: str) -> list[Entity]: ...

    def add_z_layer(self, layer: Any) -> None: ...
    def remove_z_layer(self, layer: Any) -> None: ...

    def save(self, path: str) -> None: ...
    def load(self, path: str, *, clear: bool = True) -> None: ...

    async def simulate(
        self,
        steps: int = 1,
        dt: float | None = None,
    ) -> None: ...

    @property
    def entities(self) -> list[Entity]: ...
    @property
    def z_layers(self) -> list[Any]: ...

    def __len__(self) -> int: ...


class SceneComputeAPI:
    def __init__(self, scene: Scene, ctx: Any) -> None: ...
    def run(self, shader_name: str, assets: list[Any] | None = None) -> None: ...


class DecalSystem:
    def __init__(
        self,
        ctx: Any,
        registry: Any | None = None,
        tex_mgr: Any = None,
    ) -> None: ...

    def paint(
        self,
        *,
        target: Any,
        decal_texture: str,
        uv_center: tuple[float, float],
        radius: float,
        blend: str = "normal",
        channel_writes: dict[str, Any] | None = None,
    ) -> None: ...
