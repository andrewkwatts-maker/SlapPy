"""Physics performance/quality profiles.

A *profile* is a coherent bundle of knobs that trades simulation fidelity
for runtime cost.  The four built-ins target broad hardware tiers:

* ``desktop``   — the historical default (matches ``config/physics.yml``).
* ``mobile``    — halve substeps, smaller pools, disable GPU + aggressive CCD.
* ``web``       — like mobile, but keep GPU (WebGPU) and disable the extra
                  boundary-exchange pass.
* ``high_end``  — double substeps, large pools, very aggressive CCD.

Profiles are applied by *overlaying* selected fields onto an existing
:class:`PhysicsYaml`; the input is never mutated.  ``ccd_speed_threshold`` is
not (yet) a field on :class:`PhysicsYaml`, so it is attached to the returned
object as an attribute (``yaml.ccd_speed_threshold``); callers that route
broadphase through :func:`predict_contact_pairs` can read it from there.

``profile.active`` may also be set inside ``config/physics.yml`` under a
top-level ``profile:`` section, and ``load_with_profile()`` will load+apply
in one call.  The special value ``"auto"`` triggers :func:`auto_detect_profile`.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Union

import yaml

from slappyengine.physics.world import PhysicsYaml, load_physics_config


@dataclass(frozen=True)
class PhysicsProfile:
    """A coherent bundle of performance/quality knobs."""

    name: str
    substeps: int
    initial_hull_capacity: int
    initial_cell_grid_capacity: int
    gpu_enabled: bool
    boundary_exchange_enabled: bool
    ccd_speed_threshold: float
    settle_frames: int


# -- Built-in profiles -----------------------------------------------------

PROFILE_DESKTOP = PhysicsProfile(
    name="desktop",
    substeps=4,
    initial_hull_capacity=256,
    initial_cell_grid_capacity=64,
    gpu_enabled=True,
    boundary_exchange_enabled=True,
    ccd_speed_threshold=50.0,
    settle_frames=30,
)

PROFILE_MOBILE = PhysicsProfile(
    name="mobile",
    substeps=2,                       # half of desktop
    initial_hull_capacity=64,
    initial_cell_grid_capacity=16,
    gpu_enabled=False,                # GPU startup cost not worth it on phones
    boundary_exchange_enabled=True,
    ccd_speed_threshold=100.0,        # less aggressive CCD
    settle_frames=15,
)

PROFILE_WEB = PhysicsProfile(
    name="web",
    substeps=2,
    initial_hull_capacity=64,
    initial_cell_grid_capacity=16,
    gpu_enabled=True,                 # WebGPU may be available
    boundary_exchange_enabled=False,  # skip the extra cross-seam pass on web
    ccd_speed_threshold=100.0,
    settle_frames=15,
)

PROFILE_HIGH_END = PhysicsProfile(
    name="high_end",
    substeps=8,
    initial_hull_capacity=4096,
    initial_cell_grid_capacity=512,
    gpu_enabled=True,
    boundary_exchange_enabled=True,
    ccd_speed_threshold=20.0,         # very aggressive CCD
    settle_frames=60,
)

BUILTIN_PROFILES: dict[str, PhysicsProfile] = {
    "desktop": PROFILE_DESKTOP,
    "mobile": PROFILE_MOBILE,
    "web": PROFILE_WEB,
    "high_end": PROFILE_HIGH_END,
}


# -- Lookup / apply --------------------------------------------------------

def get_profile(name: str) -> PhysicsProfile:
    """Lookup a built-in profile by name.

    Raises
    ------
    KeyError
        If ``name`` is not a registered profile.
    """
    try:
        return BUILTIN_PROFILES[name]
    except KeyError as exc:
        known = ", ".join(sorted(BUILTIN_PROFILES))
        raise KeyError(
            f"Unknown physics profile {name!r}. Known profiles: {known}"
        ) from exc


def apply_profile(
    physics_yaml: PhysicsYaml,
    profile_name_or_obj: Union[str, PhysicsProfile],
) -> PhysicsYaml:
    """Return a *new* :class:`PhysicsYaml` with the profile overlaid.

    The input ``physics_yaml`` is never mutated.  Fields with no
    corresponding profile entry retain their original value.  The chosen
    ``ccd_speed_threshold`` is attached as an attribute on the returned
    object (``out.ccd_speed_threshold``) since it is not yet a structured
    field on :class:`PhysicsYaml`.
    """
    if isinstance(profile_name_or_obj, str):
        profile = get_profile(profile_name_or_obj)
    else:
        profile = profile_name_or_obj

    out = copy.deepcopy(physics_yaml)
    out.world.substeps = int(profile.substeps)
    out.hull.initial_hull_capacity = int(profile.initial_hull_capacity)
    out.hull.initial_cell_grid_capacity = int(profile.initial_cell_grid_capacity)
    out.hull.settle_frames = int(profile.settle_frames)
    out.gpu.enabled = bool(profile.gpu_enabled)
    out.boundary_exchange.enabled = bool(profile.boundary_exchange_enabled)
    # ccd_speed_threshold has no dataclass home yet — attach as attribute.
    # Dataclasses without __slots__ accept arbitrary attribute writes.
    out.ccd_speed_threshold = float(profile.ccd_speed_threshold)
    # Stash the resolved profile name for debugging / introspection.
    out.active_profile = profile.name
    return out


# -- Auto detection --------------------------------------------------------

# Heuristic thresholds.  A device with <= MOBILE_CPU_MAX logical cores AND
# <= MOBILE_MEM_GB_MAX of total RAM is treated as constrained.  These are
# intentionally conservative: anything ambiguous falls back to "desktop".
MOBILE_CPU_MAX = 4
MOBILE_MEM_GB_MAX = 4.0


def _detect_total_memory_gb() -> float | None:
    """Best-effort total physical memory in GiB; ``None`` if unknown.

    We avoid hard-depending on ``psutil``.  Linux/Android exposes
    ``/proc/meminfo``; everything else returns ``None`` and the caller
    treats memory as "unknown" (i.e. does not down-rank the profile).
    """
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        try:
            with meminfo.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        # e.g. "MemTotal:        16384000 kB"
                        parts = line.split()
                        kb = float(parts[1])
                        return kb / (1024.0 * 1024.0)
        except (OSError, ValueError, IndexError):
            return None
    return None


def auto_detect_profile() -> PhysicsProfile:
    """Pick a profile based on the host environment.

    Heuristic (in order):

    1. ``SLAPPY_PHYSICS_PROFILE`` env var, if it names a known profile,
       wins outright — handy for CI overrides and emulator runs.
    2. If ``os.cpu_count() <= MOBILE_CPU_MAX`` AND total memory is known
       to be ``<= MOBILE_MEM_GB_MAX`` GiB, choose ``mobile``.
    3. Otherwise default to ``desktop``.

    We do **not** auto-select ``high_end``; opt-in only.  ``web`` is also
    opt-in because we can't reliably detect a browser host from Python.
    """
    env_override = os.environ.get("SLAPPY_PHYSICS_PROFILE", "").strip().lower()
    if env_override in BUILTIN_PROFILES:
        return BUILTIN_PROFILES[env_override]

    cpu = os.cpu_count() or 0
    mem_gb = _detect_total_memory_gb()

    constrained_cpu = 0 < cpu <= MOBILE_CPU_MAX
    constrained_mem = mem_gb is not None and mem_gb <= MOBILE_MEM_GB_MAX

    if constrained_cpu and constrained_mem:
        return PROFILE_MOBILE
    return PROFILE_DESKTOP


# -- Combined load + apply --------------------------------------------------

def _read_profile_section(path: str | Path | None) -> str:
    """Return the ``profile.active`` value from ``physics.yml``, or ``desktop``.

    Mirrors the search done by :func:`load_physics_config` so callers can
    pass ``None`` and have us find the same file.
    """
    if path is None:
        here = Path(__file__).resolve()
        for parent in here.parents:
            cand = parent / "config" / "physics.yml"
            if cand.exists():
                path = cand
                break
    if path is None or not Path(path).exists():
        return "desktop"
    try:
        with open(path, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except (OSError, yaml.YAMLError):
        return "desktop"
    section = raw.get("profile") or {}
    if not isinstance(section, dict):
        return "desktop"
    active = section.get("active", "desktop")
    return str(active).strip().lower() or "desktop"


def load_with_profile(
    profile_name: str | None = None,
    config_path: str | Path | None = None,
) -> PhysicsYaml:
    """Load physics config and apply a profile in one call.

    Resolution order for the active profile:

    1. Explicit ``profile_name`` argument, if given.
    2. ``profile.active`` from ``config/physics.yml``.
    3. Falls back to ``"desktop"``.

    The special value ``"auto"`` runs :func:`auto_detect_profile`.
    """
    base = load_physics_config(config_path)
    if profile_name is None:
        profile_name = _read_profile_section(config_path)

    if profile_name == "auto":
        profile = auto_detect_profile()
    else:
        profile = get_profile(profile_name)
    return apply_profile(base, profile)


__all__ = [
    "BUILTIN_PROFILES",
    "MOBILE_CPU_MAX",
    "MOBILE_MEM_GB_MAX",
    "PROFILE_DESKTOP",
    "PROFILE_HIGH_END",
    "PROFILE_MOBILE",
    "PROFILE_WEB",
    "PhysicsProfile",
    "apply_profile",
    "auto_detect_profile",
    "get_profile",
    "load_with_profile",
]
