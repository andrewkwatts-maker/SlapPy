"""YAML-backed configuration loader for SlapPyEngine.

Finds ``config/engine.yml`` (and optionally ``config/materials.yml``) relative
to the package root, or at the directory given by the ``SLAPPY_CONFIG_DIR``
environment variable.  The resulting :class:`Config` object is a module-level
singleton; call :func:`engine_config` to retrieve it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Typed sub-configs (all values come from engine.yml — nothing is hard-coded)
# ---------------------------------------------------------------------------


@dataclass
class WindowConfig:
    title: str
    width: int
    height: int
    clear_color: tuple[float, float, float, float]
    vsync: bool


@dataclass
class RenderingConfig:
    max_layers_per_asset: int
    max_frames_per_animation: int
    texture_format: str
    backend: str = "auto"
    power_preference: str = "high_performance"


@dataclass
class ResidencyConfig:
    streaming_radius_gpu: int = 500
    streaming_radius_ram: int = 2000
    vram_budget_mb: int = 512
    ram_budget_mb: int = 2048
    tile_cache_size: int = 64
    save_dir: str = "."


@dataclass
class ComputeConfig:
    workgroup_size_x: int = 16
    workgroup_size_y: int = 16
    max_readback_buffers: int = 8


@dataclass
class PhysicsConfig:
    default_dt: float = 0.016667
    substeps: int = 1


@dataclass
class TagsConfig:
    max_bits: int = 64


@dataclass
class MaterialsConfig:
    auto_dispatch: bool = True
    max_materials: int = 64
    dispatch_frequency: int = 1


@dataclass
class ZHeightConfig:
    default_z: float = 0.0
    cloud_z: float = 500.0
    shadow_z_scale: float = 0.002
    parallax_enabled: bool = True


@dataclass
class PixelPhysicsConfig:
    gravity: float = 98.0
    melt_temp: float = 100.0
    boil_temp: float = 300.0
    max_vel: float = 500.0


@dataclass
class FluidSimConfig:
    enabled: bool = False
    pad_pixels: int = 64
    lod_mode: str = "exp"
    lod_zones: int = 4
    viscosity: float = 0.1
    diffusion: float = 0.02
    buoyancy: float = 0.0
    gravity: float = 0.0
    density_decay: float = 0.995
    velocity_decay: float = 0.99
    init_mode: str = "noise"
    noise_type: str = "fbm"
    noise_scale: float = 0.003
    noise_seed: int = 42
    god_rays: bool = True
    caustics: bool = False
    force_strength: float = 50.0
    render_tint: tuple[float, float, float] = field(default_factory=lambda: (0.8, 0.9, 1.0))
    render_alpha_scale: float = 1.0


@dataclass
class NetConfig:
    enabled: bool = False
    tick_rate: int = 30
    timeout_ms: int = 100
    max_players: int = 8
    use_lan_discovery: bool = True
    use_dht_discovery: bool = True
    udp_port: int = 0


@dataclass
class LightingConfig:
    enabled: bool = True
    ambient_color: tuple[float, float, float] = field(default_factory=lambda: (0.15, 0.15, 0.20))
    ambient_intensity: float = 0.15
    max_point_lights: int = 16
    max_cone_lights: int = 8
    max_flash_lights: int = 16
    max_shape_lights: int = 4
    max_gravity_sources: int = 4
    radiance_cascades: bool = False
    radiance_probes_spacing: int = 8
    radiance_rays: int = 64
    radiance_num_cascades: int = 4
    shadow_softness: int = 1
    blackbody_emission: bool = True
    emission_threshold_k: float = 800.0
    emission_max_k: float = 6000.0
    emission_scale: float = 1.5
    geodesic_warping: bool = True
    max_render_channels: int = 4
    clustered_lighting: bool = True
    cluster_tile_size: int = 8
    max_lights_per_tile: int = 64


@dataclass
class InputConfig:
    default_player0: str = "wasd"
    default_player1: str = "arrows"


@dataclass
class SplitScreenConfig:
    enabled: bool = False
    border_px: int = 2
    border_color: tuple[int, int, int] = field(default_factory=lambda: (30, 30, 30))


# Backwards-compat: ``DeformConfig`` was the legacy per-frame deform block on
# the root Config. Ochema Circuit's ``tests/test_deform_config.py`` asserts
# every field, and ``vehicle.py`` reads ``engine_config().deform`` at scene
# init. Defaults mirror the legacy YAML block that shipped with the F1 beta.
# DO NOT REMOVE without a v1.0 deprecation cycle.
@dataclass
class DeformConfig:
    sim_mode: str = "collision_triggered"
    decay_mode: str = "curve"
    spring_decay: float = 0.94
    decay_curve: list = field(default_factory=lambda: [
        [0.0, 0.94],
        [0.25, 0.97],
        [0.5, 0.99],
        [1.0, 1.0],
    ])
    settle_threshold: float = 0.5
    settling_ramp_rate: float = 4.0
    material_preset: str = "metal"
    crack_mode: str = "none"
    crack_count: int = 6
    crack_length_px: float = 40.0
    crack_jitter: float = 0.3
    destroy_mode: str = "persist"
    physics_coupling: str = "isolated"
    repair_mode: str = "event_only"
    repair_rate: float = 1.0
    sim_frequency: str = "every_frame"
    n_frames_skip: int = 4
    budget_ms_per_frame: float = 2.0
    emit_events: list = field(default_factory=lambda: [
        "Deform.Impact",
        "Deform.Destroyed",
        "Deform.CrackAdded",
        "Deform.Repair",
        "Deform.Settled",
        "Deform.CriticalDamage",
    ])
    critical_damage_threshold: float = 0.3


@dataclass
class Config:
    """Root configuration object loaded from ``engine.yml``."""

    window: WindowConfig
    rendering: RenderingConfig
    residency: ResidencyConfig
    compute: ComputeConfig
    physics: PhysicsConfig
    tags: TagsConfig
    materials: MaterialsConfig = field(default_factory=MaterialsConfig)
    z_height: ZHeightConfig = field(default_factory=ZHeightConfig)
    pixel_physics: PixelPhysicsConfig = field(default_factory=PixelPhysicsConfig)
    fluid_sim: FluidSimConfig = field(default_factory=FluidSimConfig)
    net: NetConfig = field(default_factory=NetConfig)
    lighting: LightingConfig = field(default_factory=LightingConfig)
    input: InputConfig = field(default_factory=InputConfig)
    split_screen: SplitScreenConfig = field(default_factory=SplitScreenConfig)
    # Backwards-compat: legacy deform block, see ``DeformConfig`` above.
    deform: DeformConfig = field(default_factory=DeformConfig)


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def _find_config_dir() -> Path:
    """Return the directory that contains ``engine.yml``.

    Search order:
    1. ``SLAPPY_CONFIG_DIR`` environment variable (absolute or relative to cwd).
    2. ``config/`` directory at the repository root, discovered by walking up
       from this file's location until a directory containing ``engine.yml``
       is found.
    """
    env_dir = os.environ.get("SLAPPY_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        if not p.is_absolute():
            p = Path.cwd() / p
        if (p / "engine.yml").exists():
            return p
        raise FileNotFoundError(
            f"SLAPPY_CONFIG_DIR={env_dir!r} does not contain engine.yml"
        )

    # Walk up from the package file looking for a sibling config/ dir
    candidate = Path(__file__).resolve().parent
    for _ in range(10):  # bounded search
        config_dir = candidate / "config"
        if (config_dir / "engine.yml").exists():
            return config_dir
        parent = candidate.parent
        if parent == candidate:
            break
        candidate = parent

    raise FileNotFoundError(
        "Cannot locate engine.yml. Set SLAPPY_CONFIG_DIR or ensure the "
        "config/ directory is present in the repository root."
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_window(raw: dict) -> WindowConfig:
    cc = raw["clear_color"]
    return WindowConfig(
        title=str(raw["title"]),
        width=int(raw["width"]),
        height=int(raw["height"]),
        clear_color=(float(cc[0]), float(cc[1]), float(cc[2]), float(cc[3])),
        vsync=bool(raw["vsync"]),
    )


def _parse_rendering(raw: dict) -> RenderingConfig:
    return RenderingConfig(
        max_layers_per_asset=int(raw["max_layers_per_asset"]),
        max_frames_per_animation=int(raw["max_frames_per_animation"]),
        texture_format=str(raw["texture_format"]),
        backend=str(raw.get("backend", "auto")),
        power_preference=str(raw.get("power_preference", "high_performance")),
    )


def _parse_residency(raw: dict) -> ResidencyConfig:
    return ResidencyConfig(
        streaming_radius_gpu=int(raw["streaming_radius_gpu"]),
        streaming_radius_ram=int(raw["streaming_radius_ram"]),
        vram_budget_mb=int(raw["vram_budget_mb"]),
        ram_budget_mb=int(raw["ram_budget_mb"]),
        tile_cache_size=int(raw["tile_cache_size"]),
        save_dir=str(raw.get("save_dir", ".")),
    )


def _parse_compute(raw: dict) -> ComputeConfig:
    return ComputeConfig(
        workgroup_size_x=int(raw["workgroup_size_x"]),
        workgroup_size_y=int(raw["workgroup_size_y"]),
        max_readback_buffers=int(raw["max_readback_buffers"]),
    )


def _parse_physics(raw: dict) -> PhysicsConfig:
    return PhysicsConfig(
        default_dt=float(raw["default_dt"]),
        substeps=int(raw["substeps"]),
    )


def _parse_tags(raw: dict) -> TagsConfig:
    return TagsConfig(
        max_bits=int(raw["max_bits"]),
    )


def _parse_materials(raw: dict) -> MaterialsConfig:
    return MaterialsConfig(
        auto_dispatch=bool(raw.get("auto_dispatch", True)),
        max_materials=int(raw.get("max_materials", 64)),
        dispatch_frequency=int(raw.get("dispatch_frequency", 1)),
    )


def _parse_z_height(raw: dict) -> ZHeightConfig:
    return ZHeightConfig(
        default_z=float(raw.get("default_z", 0.0)),
        cloud_z=float(raw.get("cloud_z", 500.0)),
        shadow_z_scale=float(raw.get("shadow_z_scale", 0.002)),
        parallax_enabled=bool(raw.get("parallax_enabled", True)),
    )


def _parse_pixel_physics(raw: dict) -> PixelPhysicsConfig:
    return PixelPhysicsConfig(
        gravity=float(raw.get("gravity", 98.0)),
        melt_temp=float(raw.get("melt_temp", 100.0)),
        boil_temp=float(raw.get("boil_temp", 300.0)),
        max_vel=float(raw.get("max_vel", 500.0)),
    )


def _parse_fluid_sim(raw: dict) -> FluidSimConfig:
    tint = raw.get("render_tint", [0.8, 0.9, 1.0])
    return FluidSimConfig(
        enabled=bool(raw.get("enabled", False)),
        pad_pixels=int(raw.get("pad_pixels", 64)),
        lod_mode=str(raw.get("lod_mode", "exp")),
        lod_zones=int(raw.get("lod_zones", 4)),
        viscosity=float(raw.get("viscosity", 0.1)),
        diffusion=float(raw.get("diffusion", 0.02)),
        buoyancy=float(raw.get("buoyancy", 0.0)),
        gravity=float(raw.get("gravity", 0.0)),
        density_decay=float(raw.get("density_decay", 0.995)),
        velocity_decay=float(raw.get("velocity_decay", 0.99)),
        init_mode=str(raw.get("init_mode", "noise")),
        noise_type=str(raw.get("noise_type", "fbm")),
        noise_scale=float(raw.get("noise_scale", 0.003)),
        noise_seed=int(raw.get("noise_seed", 42)),
        god_rays=bool(raw.get("god_rays", True)),
        caustics=bool(raw.get("caustics", False)),
        force_strength=float(raw.get("force_strength", 50.0)),
        render_tint=(float(tint[0]), float(tint[1]), float(tint[2])),
        render_alpha_scale=float(raw.get("render_alpha_scale", 1.0)),
    )


def _parse_net(raw: dict) -> NetConfig:
    return NetConfig(
        enabled=bool(raw.get("enabled", False)),
        tick_rate=int(raw.get("tick_rate", 30)),
        timeout_ms=int(raw.get("timeout_ms", 100)),
        max_players=int(raw.get("max_players", 8)),
        use_lan_discovery=bool(raw.get("use_lan_discovery", True)),
        use_dht_discovery=bool(raw.get("use_dht_discovery", True)),
        udp_port=int(raw.get("udp_port", 0)),
    )


def _parse_lighting(raw: dict) -> LightingConfig:
    ac = raw.get("ambient_color", [0.15, 0.15, 0.20])
    return LightingConfig(
        enabled=bool(raw.get("enabled", True)),
        ambient_color=(float(ac[0]), float(ac[1]), float(ac[2])),
        ambient_intensity=float(raw.get("ambient_intensity", 0.15)),
        max_point_lights=int(raw.get("max_point_lights", 16)),
        max_cone_lights=int(raw.get("max_cone_lights", 8)),
        max_flash_lights=int(raw.get("max_flash_lights", 16)),
        max_shape_lights=int(raw.get("max_shape_lights", 4)),
        max_gravity_sources=int(raw.get("max_gravity_sources", 4)),
        radiance_cascades=bool(raw.get("radiance_cascades", False)),
        radiance_probes_spacing=int(raw.get("radiance_probes_spacing", 8)),
        radiance_rays=int(raw.get("radiance_rays", 64)),
        radiance_num_cascades=int(raw.get("radiance_num_cascades", 4)),
        shadow_softness=int(raw.get("shadow_softness", 1)),
        blackbody_emission=bool(raw.get("blackbody_emission", True)),
        emission_threshold_k=float(raw.get("emission_threshold_k", 800.0)),
        emission_max_k=float(raw.get("emission_max_k", 6000.0)),
        emission_scale=float(raw.get("emission_scale", 1.5)),
        geodesic_warping=bool(raw.get("geodesic_warping", True)),
        max_render_channels=int(raw.get("max_render_channels", 4)),
        clustered_lighting=bool(raw.get("clustered_lighting", True)),
        cluster_tile_size=int(raw.get("cluster_tile_size", 8)),
        max_lights_per_tile=int(raw.get("max_lights_per_tile", 64)),
    )


def _parse_input(raw: dict) -> InputConfig:
    return InputConfig(
        default_player0=str(raw.get("default_player0", "wasd")),
        default_player1=str(raw.get("default_player1", "arrows")),
    )


def _parse_deform(raw: dict) -> DeformConfig:
    """Backwards-compat: parse a raw deform: YAML block into a :class:`DeformConfig`.

    Missing keys fall back to :class:`DeformConfig` field defaults. Used by
    downstream game code (Ochema Circuit's per-vehicle deform config loader)
    to hydrate a DeformConfig from a plain dict without reaching for
    ``dataclasses.replace``.
    DO NOT REMOVE without a v1.0 deprecation cycle.
    """
    defaults = DeformConfig()
    return DeformConfig(
        sim_mode=str(raw.get("sim_mode", defaults.sim_mode)),
        decay_mode=str(raw.get("decay_mode", defaults.decay_mode)),
        spring_decay=float(raw.get("spring_decay", defaults.spring_decay)),
        decay_curve=list(raw.get("decay_curve", defaults.decay_curve)),
        settle_threshold=float(raw.get("settle_threshold", defaults.settle_threshold)),
        settling_ramp_rate=float(raw.get("settling_ramp_rate", defaults.settling_ramp_rate)),
        material_preset=str(raw.get("material_preset", defaults.material_preset)),
        crack_mode=str(raw.get("crack_mode", defaults.crack_mode)),
        crack_count=int(raw.get("crack_count", defaults.crack_count)),
        crack_length_px=float(raw.get("crack_length_px", defaults.crack_length_px)),
        crack_jitter=float(raw.get("crack_jitter", defaults.crack_jitter)),
        destroy_mode=str(raw.get("destroy_mode", defaults.destroy_mode)),
        physics_coupling=str(raw.get("physics_coupling", defaults.physics_coupling)),
        repair_mode=str(raw.get("repair_mode", defaults.repair_mode)),
        repair_rate=float(raw.get("repair_rate", defaults.repair_rate)),
        sim_frequency=str(raw.get("sim_frequency", defaults.sim_frequency)),
        n_frames_skip=int(raw.get("n_frames_skip", defaults.n_frames_skip)),
        budget_ms_per_frame=float(raw.get("budget_ms_per_frame", defaults.budget_ms_per_frame)),
        emit_events=list(raw.get("emit_events", defaults.emit_events)),
        critical_damage_threshold=float(raw.get("critical_damage_threshold", defaults.critical_damage_threshold)),
    )


def _parse_split_screen(raw: dict) -> SplitScreenConfig:
    bc = raw.get("border_color", [30, 30, 30])
    return SplitScreenConfig(
        enabled=bool(raw.get("enabled", False)),
        border_px=int(raw.get("border_px", 2)),
        border_color=(int(bc[0]), int(bc[1]), int(bc[2])),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_config_cache: Optional[Config] = None


def load_config(path: str | None = None) -> Config:
    """Load and return a :class:`Config` from *path* (an ``engine.yml`` file).

    If *path* is ``None`` the file is discovered automatically via
    :func:`_find_config_dir`.  The result is **not** cached — use
    :func:`engine_config` when you want the shared singleton.
    """
    if path is not None:
        yml_path = Path(path)
    else:
        yml_path = _find_config_dir() / "engine.yml"

    with yml_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)

    return Config(
        window=_parse_window(raw["window"]),
        rendering=_parse_rendering(raw["rendering"]),
        residency=_parse_residency(raw["residency"]) if "residency" in raw else ResidencyConfig(),
        compute=_parse_compute(raw["compute"]) if "compute" in raw else ComputeConfig(),
        physics=_parse_physics(raw["physics"]) if "physics" in raw else PhysicsConfig(),
        tags=_parse_tags(raw["tags"]) if "tags" in raw else TagsConfig(),
        materials=_parse_materials(raw["materials"]) if "materials" in raw else MaterialsConfig(),
        z_height=_parse_z_height(raw["z_height"]) if "z_height" in raw else ZHeightConfig(),
        pixel_physics=_parse_pixel_physics(raw["pixel_physics"]) if "pixel_physics" in raw else PixelPhysicsConfig(),
        fluid_sim=_parse_fluid_sim(raw["fluid_sim"]) if "fluid_sim" in raw else FluidSimConfig(),
        net=_parse_net(raw["net"]) if "net" in raw else NetConfig(),
        lighting=_parse_lighting(raw["lighting"]) if "lighting" in raw else LightingConfig(),
        input=_parse_input(raw["input"]) if "input" in raw else InputConfig(),
        split_screen=_parse_split_screen(raw["split_screen"]) if "split_screen" in raw else SplitScreenConfig(),
        deform=_parse_deform(raw["deform"]) if "deform" in raw else DeformConfig(),
    )


def load_engine_config(path: str | None = None) -> Config:
    """Alias for :func:`load_config`; loads a fresh (non-cached) :class:`Config`.

    Prefer this name when writing engine-startup code or tests.
    """
    return load_config(path)


def engine_config(path: str | None = None) -> Config:
    """Return the module-level singleton :class:`Config`.

    On the first call the YAML file is read and parsed.  Subsequent calls
    return the cached instance regardless of *path*.  Pass *path* only during
    initialisation (e.g. inside :class:`~SlapPyEngine.engine.Engine.__init__`).
    """
    global _config_cache
    if _config_cache is None:
        _config_cache = load_config(path)
    return _config_cache


# ---------------------------------------------------------------------------
# Config hot-reload
# ---------------------------------------------------------------------------


class ConfigManager:
    """Watches engine.yml and calls registered callbacks on change.

    Requires watchdog: pip install watchdog
    Falls back to no-op if watchdog is not installed.
    """

    _RESTART_REQUIRED = {"window.width", "window.height", "window.title"}

    def __init__(self, config_path: str):
        self._path = config_path
        self._callbacks: list = []
        self._observer = None
        self._last_config = self._load()

    def _load(self) -> dict:
        import yaml
        try:
            with open(self._path) as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    def watch(self, callback) -> None:
        """Register callback(changed_keys: dict) called on config change."""
        self._callbacks.append(callback)
        if self._observer is None:
            self._start_watcher()

    def _start_watcher(self):
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            mgr = self
            class _Handler(FileSystemEventHandler):
                def on_modified(self, event):
                    if event.src_path.endswith(mgr._path.split("/")[-1]):
                        mgr._on_file_changed()

            import os
            self._observer = Observer()
            self._observer.schedule(_Handler(), os.path.dirname(self._path) or ".", recursive=False)
            self._observer.daemon = True
            self._observer.start()
        except ImportError:
            pass  # watchdog not installed — silent no-op

    def _on_file_changed(self):
        new_config = self._load()
        diff = self._diff(self._last_config, new_config)
        if not diff:
            return
        restart_needed = [k for k in diff if k in self._RESTART_REQUIRED]
        if restart_needed:
            import warnings
            warnings.warn(f"Config keys {restart_needed} require engine restart to take effect.")
        # Fire callbacks only for hot-reloadable keys
        hot_diff = {k: v for k, v in diff.items() if k not in self._RESTART_REQUIRED}
        if hot_diff:
            for cb in self._callbacks:
                try:
                    cb(hot_diff)
                except Exception:
                    pass
        self._last_config = new_config

    def _diff(self, old: dict, new: dict, prefix: str = "") -> dict:
        """Flat diff of nested dicts. Returns {dotted.key: new_value}."""
        result = {}
        for k in set(list(old.keys()) + list(new.keys())):
            full_key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            ov, nv = old.get(k), new.get(k)
            if isinstance(ov, dict) and isinstance(nv, dict):
                result.update(self._diff(ov, nv, full_key))
            elif ov != nv:
                result[full_key] = nv
        return result

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
