"""Material dataclass shared by the dynamics primitives.

A :class:`Material` carries the tuning knobs that the substrate solver and
renderers need: stiffness/damping defaults for new bonds, density used to
derive node masses, restitution/friction for contact, plus a free-form
``properties`` bag for game-specific extras.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Material:
    """Bulk physical parameters for a :class:`Body`.

    Defaults correspond to a generic rubbery solid (~1 t/m^3, soft beams).
    """
    name: str = "default"
    density: float = 1000.0          # kg / m^3 — converted to per-node mass by builders
    stiffness: float = 1.0e6         # default constraint stiffness
    damping: float = 0.05            # default constraint damping (XPBD beta)
    restitution: float = 0.2         # contact bounciness in [0, 1]
    friction: float = 0.5            # contact friction
    breaking_strain: float = float("inf")
    properties: dict[str, Any] = field(default_factory=dict)


__all__ = ["Material"]
