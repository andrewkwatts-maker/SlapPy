from __future__ import annotations

from typing import Any

__all__: list[str] = ["Engine"]

class Engine:
    camera: Any  # pharos_engine.camera.Camera

    def __init__(
        self,
        config_path: str | None = None,
        **overrides: Any,
    ) -> None: ...

    def load_scene(self, scene: Any) -> None: ...
    def register_module(self, module: Any) -> None: ...
    def register_tags(self, tag_registry: Any) -> None: ...

    def run(self) -> None: ...
    def run_editor(self) -> None: ...
    def open_project_manager(self) -> str: ...
    def launch(self) -> None: ...

    def add_player(self, action_map: Any) -> int: ...

    def enable_split_screen(
        self,
        num_players: int,
        cameras: list[Any] | None = None,
    ) -> Any: ...  # returns SplitScreenManager

    async def host_game(
        self,
        player_id: int = 0,
        cfg: Any | None = None,
    ) -> Any: ...  # returns GameSession

    async def join_game(
        self,
        room_code: str,
        player_id: int = 1,
        cfg: Any | None = None,
    ) -> Any: ...  # returns GameSession

    def enable_fluid_sim(self, cfg: Any | None = None) -> Any: ...  # returns GlobalFluidSim
    def enable_ibl(self, hdri_path: str | None = None) -> None: ...
    def enable_sdf(self) -> None: ...
    def enable_cluster_3d(self) -> None: ...

    def profile_frame(self) -> dict[str, float]: ...
    def profile_gpu(self) -> dict[str, str]: ...

    @property
    def mouse_pos(self) -> tuple[float, float]: ...
    @property
    def scene(self) -> Any | None: ...  # Scene | None
    @property
    def device(self) -> Any: ...  # wgpu.GPUDevice
    @property
    def post_executor(self) -> Any: ...
    @property
    def lighting(self) -> Any | None: ...  # LightingSystem | None
    @property
    def compositor(self) -> Any | None: ...  # RenderChannelCompositor | None
    @property
    def residency(self) -> Any | None: ...  # ResidencyManager | None
    @property
    def config(self) -> Any: ...  # Config
    @property
    def input(self) -> Any | None: ...  # InputManager | None
    @property
    def audio(self) -> Any | None: ...  # AudioManager | None
    @property
    def fluid(self) -> Any | None: ...  # GlobalFluidSim | None
    @property
    def input_maps(self) -> list[Any]: ...
    @property
    def split_screen(self) -> Any | None: ...  # SplitScreenManager | None
    @property
    def net(self) -> Any | None: ...  # GameSession | None
    @property
    def ibl(self) -> Any | None: ...  # IBLSystem | None
    @property
    def sdf(self) -> Any | None: ...  # SdfRenderer | None
    @property
    def cluster_3d(self) -> Any | None: ...  # Cluster3DSystem | None
