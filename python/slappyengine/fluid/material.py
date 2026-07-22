"""Fluid material catalog.

This module only defines the :class:`FluidMaterial` dataclass and the
:func:`load_catalog` loader. All numeric defaults live in
``config/fluid.yml`` under the ``materials:`` section — that file is
the source of truth.

The module-level constants ``WATER``, ``LAVA``, ``ICE``, ``STONE``,
``SAND``, ``GRAVEL``, ``DUST`` are convenience aliases populated from
the loaded catalog (kept for backwards compatibility with existing
imports). New code should use ``MATERIALS["name"]`` instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class FluidMaterial:
    name: str
    rest_density: float
    kernel_radius: float
    relaxation_eps: float
    viscosity: float
    surface_tension: float
    surface_tension_n: float
    particle_mass: float = 1.0
    friction_coef: float = 0.0
    is_granular: bool = False
    render_color: tuple[int, int, int] = (60, 140, 220)
    halo_color: tuple[int, int, int] = (180, 220, 255)
    # Thermal coupling. ambient_temperature is the equilibrium temperature
    # this material relaxes to (e.g. water at 20C, lava at ~1000C). If
    # `freeze_to` is set, the particle switches to that material id once
    # its temperature drops below `freeze_temperature`; `melt_to` works
    # the same way going up past `melt_temperature`.
    thermal_conductivity: float = 0.0
    ambient_temperature: float = 20.0
    melt_temperature: float = 1.0e9
    freeze_temperature: float = -1.0e9
    melt_to: str = ""
    freeze_to: str = ""


def _config_path() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "fluid.yml"
        if candidate.is_file():
            return candidate
    return None


def _material_from_mapping(name: str, entry: Mapping[str, object]) -> FluidMaterial:
    """Build a FluidMaterial from a YAML mapping. The numeric required keys
    are explicit so a missing entry raises rather than silently using the
    dataclass default. Optional thermal / phase-change keys fall through to
    the dataclass defaults (no thermal coupling)."""
    rc = entry.get("render_color", (60, 140, 220))
    hc = entry.get("halo_color", (180, 220, 255))
    return FluidMaterial(
        name=name,
        rest_density=float(entry["rest_density"]),
        kernel_radius=float(entry["kernel_radius"]),
        relaxation_eps=float(entry["relaxation_eps"]),
        viscosity=float(entry["viscosity"]),
        surface_tension=float(entry["surface_tension"]),
        surface_tension_n=float(entry["surface_tension_n"]),
        particle_mass=float(entry.get("particle_mass", 1.0)),
        friction_coef=float(entry.get("friction_coef", 0.0)),
        is_granular=bool(entry.get("is_granular", False)),
        render_color=tuple(int(c) for c in rc),  # type: ignore[arg-type]
        halo_color=tuple(int(c) for c in hc),    # type: ignore[arg-type]
        thermal_conductivity=float(entry.get("thermal_conductivity", 0.0)),
        ambient_temperature=float(entry.get("ambient_temperature", 20.0)),
        melt_temperature=float(entry.get("melt_temperature", 1.0e9)),
        freeze_temperature=float(entry.get("freeze_temperature", -1.0e9)),
        melt_to=str(entry.get("melt_to", "")),
        freeze_to=str(entry.get("freeze_to", "")),
    )


def load_catalog(path: str | Path | None = None) -> dict[str, FluidMaterial]:
    """Return the fluid material catalog loaded from ``fluid.yml``.

    The ``materials:`` section in the YAML is the source of truth. If the
    file cannot be found or parsed, an empty catalog is returned so that
    downstream code raises a clear ``KeyError`` rather than silently
    picking up a stale hard-coded default.
    """
    # Local import so a missing yaml dependency doesn't break the dataclass.
    import yaml  # noqa: PLC0415

    p = Path(path) if path is not None else _config_path()
    if p is None or not p.is_file():
        return {}
    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except Exception:
        return {}
    section = raw.get("materials") or {}
    if not isinstance(section, Mapping):
        return {}
    catalog: dict[str, FluidMaterial] = {}
    for name, entry in section.items():
        if not isinstance(entry, Mapping):
            continue
        catalog[name] = _material_from_mapping(str(name), entry)
    return catalog


MATERIALS: dict[str, FluidMaterial] = load_catalog()

# Backwards-compatible module-level aliases. Populated from the catalog at
# import time. New code should use MATERIALS["name"].
WATER: FluidMaterial = MATERIALS["water"]
LAVA: FluidMaterial = MATERIALS["lava"]
ICE: FluidMaterial = MATERIALS["ice"]
STONE: FluidMaterial = MATERIALS["stone"]
SAND: FluidMaterial = MATERIALS["sand"]
GRAVEL: FluidMaterial = MATERIALS["gravel"]
DUST: FluidMaterial = MATERIALS["dust"]


__all__ = [
    "FluidMaterial",
    "WATER", "SAND", "GRAVEL", "DUST", "LAVA", "ICE", "STONE",
    "MATERIALS",
    "load_catalog",
]
