from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path
from typing import Mapping

import yaml


@dataclass(frozen=True)
class Material2:
    name: str
    id: int
    density: float
    stiffness: float
    viscosity: float
    plasticity_rate: float
    fracture_strain: float
    melt_temperature: float


_VACUUM = Material2(
    name="VACUUM",
    id=0,
    density=0.0,
    stiffness=0.0,
    viscosity=0.0,
    plasticity_rate=0.0,
    fracture_strain=1e9,
    melt_temperature=1.0,
)


def _config_path() -> Path:
    here = Path(__file__).resolve()
    for ancestor in [here.parent, *here.parents]:
        candidate = ancestor / "config" / "physics2.yml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("config/physics2.yml not found")


def load_catalog(path: str | Path | None = None) -> dict[str, Material2]:
    p = Path(path) if path is not None else _config_path()
    with p.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    section: Mapping[str, Mapping[str, float]] = raw.get("materials", {})
    catalog: dict[str, Material2] = {"VACUUM": _VACUUM}
    next_id = 1
    required = {f.name for f in fields(Material2)} - {"name", "id"}
    for name, params in section.items():
        missing = required - set(params)
        if missing:
            raise ValueError(f"Material {name} missing keys: {sorted(missing)}")
        catalog[name] = Material2(
            name=name,
            id=next_id,
            density=float(params["density"]),
            stiffness=float(params["stiffness"]),
            viscosity=float(params["viscosity"]),
            plasticity_rate=float(params["plasticity_rate"]),
            fracture_strain=float(params["fracture_strain"]),
            melt_temperature=float(params["melt_temperature"]),
        )
        next_id += 1
    return catalog


__all__ = ["Material2", "load_catalog"]
