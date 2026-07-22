"""Soft-body material catalog.

This module only defines the :class:`Material` dataclass and the
:func:`load_catalog` loader. All numeric defaults live in
``config/softbody.yml`` under the ``materials:`` section — that file is
the source of truth.

Stiffness values in the YAML are tuned for stability at substeps=8,
iters=4 with dt=1/60. They are scaled down from physical SI values
(e.g. real steel ~ 2e11 Pa) because XPBD compliance is unitless under
the chosen mass scale; the relative ordering glass>steel>stone>wood>rubber
is what governs gameplay behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml


@dataclass(frozen=True)
class Material:
    name: str
    density: float          # kg/m^2 (2D — node mass = density * area_around_node)
    stiffness: float        # Pa  (XPBD compliance alpha = 1 / (stiffness * dt^2))
    damping: float          # 0..1 multiplier applied to velocity per substep
    break_strain: float     # |length - rest_length| / rest_length above which a beam breaks
    yield_strain: float     # fraction below which the beam is purely elastic
    plasticity_rate: float  # 1/s — exponential decay rate; blend = 1 - exp(-rate * dt_sub)
    contact_thickness: float = 0.5  # capsule half-thickness for body-body contact (m)
    contact_stiffness: float = 1.0e9  # XPBD contact compliance (Pa); larger ~ more rigid
    render_color: tuple[int, int, int] = (180, 180, 180)
    damage_color: tuple[int, int, int] = (40, 12, 8)


def _config_path() -> Path | None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "softbody.yml"
        if candidate.is_file():
            return candidate
    return None


def _material_from_mapping(name: str, entry: Mapping[str, object]) -> Material:
    """Build a Material from a YAML mapping. Required keys are explicit so
    that a missing default in the YAML raises rather than silently using
    the dataclass default."""
    rc = entry.get("render_color", (180, 180, 180))
    dc = entry.get("damage_color", (40, 12, 8))
    return Material(
        name=name,
        density=float(entry["density"]),
        stiffness=float(entry["stiffness"]),
        damping=float(entry["damping"]),
        break_strain=float(entry["break_strain"]),
        yield_strain=float(entry["yield_strain"]),
        plasticity_rate=float(entry["plasticity_rate"]),
        contact_thickness=float(entry.get("contact_thickness", 0.5)),
        contact_stiffness=float(entry.get("contact_stiffness", 1.0e9)),
        render_color=tuple(int(c) for c in rc),  # type: ignore[arg-type]
        damage_color=tuple(int(c) for c in dc),  # type: ignore[arg-type]
    )


def load_catalog(path: str | Path | None = None) -> dict[str, Material]:
    """Return the material catalog loaded from ``softbody.yml``.

    The ``materials:`` section in the YAML is the source of truth. If the
    file cannot be found or parsed, an empty catalog is returned so that
    downstream code raises a clear ``KeyError`` for the missing material
    rather than silently picking up a stale hard-coded default.
    """
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
    catalog: dict[str, Material] = {}
    for name, entry in section.items():
        if not isinstance(entry, Mapping):
            continue
        catalog[name] = _material_from_mapping(str(name), entry)
    return catalog


MATERIALS: dict[str, Material] = load_catalog()


__all__ = ["Material", "MATERIALS", "load_catalog"]
