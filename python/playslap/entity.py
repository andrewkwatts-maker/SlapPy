import uuid
from dataclasses import dataclass, field
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from playslap.z_height import ZLayer, ZAABBShape
    from playslap.angle_sprite import AngleSpriteMap
    from playslap.data_component import DataComponent

class Entity:
    def __init__(self, name: str = "", position: tuple[float,float] = (0.0, 0.0)):
        self.id: str = str(uuid.uuid4())
        self.name: str = name
        self.position: tuple[float, float] = position
        self.tags: set[str] = set()
        self.residency: str = "disk"  # promoted by residency manager
        self._scripts: list = []
        self._emitters: list = []
        self.rotation: float = 0.0   # degrees, clockwise
        self.scale: float = 1.0
        self.collision_shape = None  # set to AABBShape or CircleShape to participate in collision
        self.strata_layer: int = 0   # which parallel dimension layer this entity belongs to
        self.z_height: float = 0.0                  # explicit Z position in world units
        self.z_layer: "ZLayer | None" = None        # which depth layer this entity belongs to
        self.z_collision_shape: "ZAABBShape | None" = None  # 3D AABB for Z filtering
        self._shader_bindings: list = []             # ShaderBinding list (for later)
        self._angle_map: "AngleSpriteMap | None" = None
        self._angle_sprite_state: str = ""   # current state tag ("", "damaged", "boosting", etc.)
        self.data: "DataComponent | None" = None    # generic key-value data store

    def tick(self, dt: float) -> None:
        for script in self._scripts:
            if hasattr(script, "on_tick"):
                script.on_tick(self, dt)
        if self.data is not None:
            self.data.tick()

    @classmethod
    def on_compile(cls) -> None:
        """Called once when this entity class is first used by the engine.

        Override in subclasses to perform one-time class-level setup.
        """

    def on_create(self) -> None:
        """Called when the entity is added to a scene.

        Delegates to scripts that implement on_spawn for backward compatibility.
        """
        for script in self._scripts:
            if hasattr(script, "on_spawn"):
                script.on_spawn(self)

    def on_destroy(self) -> None:
        """Called when the entity is removed from a scene.

        Delegates to scripts that implement on_despawn for backward compatibility.
        """
        for script in self._scripts:
            if hasattr(script, "on_despawn"):
                script.on_despawn(self)

    # Keep legacy names as aliases so existing code continues to work.
    def on_spawn(self) -> None:
        self.on_create()

    def on_despawn(self) -> None:
        self.on_destroy()

    def bind(self, when, then, once: bool = True) -> None:
        """Shorthand: entity.bind(...) → entity.data.bind(...).

        Initialises an empty DataComponent automatically if data is None.
        """
        if self.data is None:
            from playslap.data_component import DataComponent
            self.data = DataComponent()
        self.data.bind(when, then, once)

    def attach_script(self, script) -> None:
        self._scripts.append(script)

    def add_emitter(self, emitter) -> None:
        self._emitters.append(emitter)
