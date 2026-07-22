from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from .kernels import poly6_coefficient
from .material import MATERIALS, WATER, FluidMaterial
from .particle import ParticleSoA


def _config_path() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "fluid.yml"
        if candidate.is_file():
            return candidate
    return None


def _load_world_config() -> dict[str, Any]:
    world_defaults: dict[str, Any] = {
        "gravity": (0.0, 9.81),
        "default_dt": 1.0 / 60.0,
        "substeps": 4,
        "iters": 4,
        "floor_y": 5.0,
        "wall_x_min": -10.0,
        "wall_x_max": 10.0,
        "ceiling_y": -10.0,
        "velocity_epsilon": 1.0e-9,
        "max_velocity": 40.0,
        "water_density": 1000.0,
    }
    solver_defaults: dict[str, Any] = {
        "particle_spacing": 0.075,
        "s_corr_dq_scale": 0.3,
        "vorticity_eps": 0.0,
        "xsph_enabled": True,
        "density_floor_factor": 0.0,
    }
    contact_defaults: dict[str, Any] = {
        "enabled": True,
        "thickness": 0.05,
        "stiffness": 1.0e6,
        "broadphase_cell_factor": 1.5,
    }
    granular_defaults: dict[str, Any] = {
        "enabled": True,
        "contact_radius_factor": 0.55,
        "friction_dt_scale": 1.0,
        "tangential_velocity_eps": 1.0e-6,
    }
    thermal_defaults: dict[str, Any] = {
        "enabled": True,
        "diffusion_rate": 5.0,
        "ambient_rate": 0.2,
    }
    out: dict[str, Any] = dict(world_defaults)
    out["solver"] = dict(solver_defaults)
    out["contact"] = dict(contact_defaults)
    out["granular"] = dict(granular_defaults)
    out["thermal"] = dict(thermal_defaults)

    p = _config_path()
    if p is None:
        return out
    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:
        return out
    world_section = raw.get("world") or {}
    if isinstance(world_section, dict):
        for k in world_defaults:
            if k in world_section:
                out[k] = world_section[k]
    solver_section = raw.get("solver") or {}
    if isinstance(solver_section, dict):
        for k in solver_defaults:
            if k in solver_section:
                out["solver"][k] = solver_section[k]
    contact_section = raw.get("contact") or {}
    if isinstance(contact_section, dict):
        for k in contact_defaults:
            if k in contact_section:
                out["contact"][k] = contact_section[k]
    granular_section = raw.get("granular") or {}
    if isinstance(granular_section, dict):
        for k in granular_defaults:
            if k in granular_section:
                out["granular"][k] = granular_section[k]
    thermal_section = raw.get("thermal") or {}
    if isinstance(thermal_section, dict):
        for k in thermal_defaults:
            if k in thermal_section:
                out["thermal"][k] = thermal_section[k]
    return out


@dataclass
class FluidWorld:
    particles: ParticleSoA = field(default_factory=ParticleSoA)
    materials: list[FluidMaterial] = field(default_factory=lambda: [WATER])
    config: dict[str, Any] = field(default_factory=_load_world_config)

    @property
    def gravity(self) -> np.ndarray:
        g = self.config["gravity"]
        return np.asarray([float(g[0]), float(g[1])], dtype=np.float32)

    @property
    def floor_y(self) -> float:
        return float(self.config["floor_y"])

    @property
    def wall_x_min(self) -> float:
        return float(self.config["wall_x_min"])

    @property
    def wall_x_max(self) -> float:
        return float(self.config["wall_x_max"])

    @property
    def ceiling_y(self) -> float:
        return float(self.config["ceiling_y"])

    def _mass_for_rest_density(self, mat: FluidMaterial, spacing: float) -> float:
        h = float(mat.kernel_radius)
        sp = float(spacing)
        R = int(np.ceil(h / max(sp, 1e-6))) + 1
        offsets = np.arange(-R, R + 1, dtype=np.float64) * sp
        gx, gy = np.meshgrid(offsets, offsets, indexing="xy")
        r2 = (gx * gx + gy * gy).ravel()
        valid = r2 < h * h
        diff = np.maximum(h * h - r2[valid], 0.0)
        w_sum = float(poly6_coefficient(h) * np.power(diff, 3).sum())
        if w_sum <= 0.0:
            return float(mat.particle_mass)
        return float(mat.rest_density) / w_sum

    def add_block_of_particles(
        self,
        material: str | FluidMaterial,
        nx: int,
        ny: int,
        spacing: float | None = None,
        origin: tuple[float, float] = (0.0, 0.0),
        velocity: tuple[float, float] = (0.0, 0.0),
        jitter: float = 0.0,
        mass: float | None = None,
        temperature: float | None = None,
    ) -> int:
        mat = material if isinstance(material, FluidMaterial) else MATERIALS[material]
        if mat not in self.materials:
            self.materials.append(mat)
        material_id = self.materials.index(mat)
        if spacing is None:
            spacing = float(self.config["solver"]["particle_spacing"])
        spacing = float(spacing)
        if mass is None:
            mass = self._mass_for_rest_density(mat, spacing)
        if temperature is None:
            temperature = float(getattr(mat, "ambient_temperature", 20.0))
        ox, oy = float(origin[0]), float(origin[1])
        xs = ox + np.arange(nx, dtype=np.float32) * spacing
        ys = oy + np.arange(ny, dtype=np.float32) * spacing
        gx, gy = np.meshgrid(xs, ys, indexing="xy")
        pts = np.stack([gx.ravel(), gy.ravel()], axis=1).astype(np.float32)
        if jitter > 0.0:
            rng = np.random.default_rng(seed=int((ox * 1000 + oy * 7 + nx * 13 + ny * 31)) & 0xFFFFFFFF)
            pts += (rng.random(pts.shape, dtype=np.float32) - 0.5) * (2.0 * jitter * spacing)
        v = np.broadcast_to(np.asarray(velocity, dtype=np.float32), (pts.shape[0], 2)).astype(np.float32, copy=True)
        return self.particles.append(pts, mass=float(mass), material_id=material_id,
                                     vel=v, temperature=float(temperature))

    def emit_stream(
        self,
        material: str | FluidMaterial,
        count: int,
        origin: tuple[float, float],
        velocity: tuple[float, float],
        spacing: float | None = None,
        across: int = 1,
        mass: float | None = None,
        temperature: float | None = None,
    ) -> int:
        mat = material if isinstance(material, FluidMaterial) else MATERIALS[material]
        if mat not in self.materials:
            self.materials.append(mat)
        material_id = self.materials.index(mat)
        if spacing is None:
            spacing = float(self.config["solver"]["particle_spacing"])
        spacing = float(spacing)
        if mass is None:
            mass = self._mass_for_rest_density(mat, spacing)
        if temperature is None:
            temperature = float(getattr(mat, "ambient_temperature", 20.0))
        ox, oy = float(origin[0]), float(origin[1])
        vx, vy = float(velocity[0]), float(velocity[1])
        speed = float(np.hypot(vx, vy)) or 1.0
        tx, ty = -vy / speed, vx / speed
        rows = max(1, int(np.ceil(count / max(across, 1))))
        cols = max(1, across)
        ks = np.arange(rows, dtype=np.float32)
        js = np.arange(cols, dtype=np.float32) - (cols - 1) * 0.5
        Ks, Js = np.meshgrid(ks, js, indexing="xy")
        K = Ks.ravel()[:count]
        J = Js.ravel()[:count]
        px = ox + K * spacing * (-vx / speed) + J * spacing * tx
        py = oy + K * spacing * (-vy / speed) + J * spacing * ty
        pts = np.stack([px, py], axis=1).astype(np.float32)
        v = np.broadcast_to(np.asarray((vx, vy), dtype=np.float32), (pts.shape[0], 2)).astype(np.float32, copy=True)
        return self.particles.append(pts, mass=float(mass), material_id=material_id,
                                     vel=v, temperature=float(temperature))


__all__ = ["FluidWorld"]
