"""Per-substep thermal pass for PBF particles.

Two coupled phenomena:

* **Heat diffusion** — neighbour-averaging of `temperature` weighted by
  the per-material `thermal_conductivity`. Uses the same neighbour
  table the PBF solver already builds, so this is a cheap add-on
  pass.
* **Ambient relaxation** — Newton's-law cooling toward each material's
  `ambient_temperature`. Implicit-Euler form for unconditional
  stability.
* **Phase change** — when a particle's temperature crosses
  `melt_temperature` (rising) or `freeze_temperature` (falling), its
  `material_id` flips to the configured `melt_to` / `freeze_to`. Mass
  is conserved; the new material's catalog entry decides the new
  behaviour for subsequent substeps.

Calling convention: invoked by the PBF solver inside its substep loop
after the density-projection iteration. Heat does not back-affect the
density constraint this tick — phase change updates `material_id` for
the *next* substep, so the current frame is consistent.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from .world import FluidWorld

# Detect the Rust-backed thermal kernel once at import time. Mirrors the
# pattern in ``solver.py`` (``_HAS_NATIVE_PBF``). Falls back to the
# pure-numpy path if `_core` is absent or the symbol isn't present.
try:
    from pharos_engine import _core as _native_core  # type: ignore
    _HAS_NATIVE_THERMAL = hasattr(_native_core, "thermal_step_rs")
except ImportError:  # pragma: no cover
    _native_core = None  # type: ignore
    _HAS_NATIVE_THERMAL = False


__all__ = ["thermal_step"]


def _material_arrays(world: "FluidWorld") -> dict[str, np.ndarray]:
    """Build per-material parameter arrays indexed by material_id."""
    n_mats = len(world.materials)
    cond = np.zeros(n_mats, dtype=np.float32)
    ambient = np.zeros(n_mats, dtype=np.float32)
    melt_t = np.full(n_mats, 1.0e9, dtype=np.float32)
    freeze_t = np.full(n_mats, -1.0e9, dtype=np.float32)
    melt_to_id = np.full(n_mats, -1, dtype=np.int32)
    freeze_to_id = np.full(n_mats, -1, dtype=np.int32)

    # Map material names to indices for melt_to / freeze_to resolution.
    name_to_id = {mat.name: i for i, mat in enumerate(world.materials)}

    for i, mat in enumerate(world.materials):
        cond[i] = float(getattr(mat, "thermal_conductivity", 0.0))
        ambient[i] = float(getattr(mat, "ambient_temperature", 20.0))
        melt_t[i] = float(getattr(mat, "melt_temperature", 1.0e9))
        freeze_t[i] = float(getattr(mat, "freeze_temperature", -1.0e9))
        melt_to = getattr(mat, "melt_to", "")
        if melt_to and melt_to in name_to_id:
            melt_to_id[i] = name_to_id[melt_to]
        freeze_to = getattr(mat, "freeze_to", "")
        if freeze_to and freeze_to in name_to_id:
            freeze_to_id[i] = name_to_id[freeze_to]

    return {
        "cond": cond,
        "ambient": ambient,
        "melt_t": melt_t,
        "freeze_t": freeze_t,
        "melt_to_id": melt_to_id,
        "freeze_to_id": freeze_to_id,
    }


def thermal_step(
    world: "FluidWorld",
    i_idx: np.ndarray,
    j_idx: np.ndarray,
    sub_dt: float,
    diffusion_rate: float = 5.0,
    ambient_rate: float = 0.2,
) -> int:
    """Run one substep of thermal diffusion + ambient relaxation + phase change.

    Parameters
    ----------
    world
        The fluid world whose particles get updated.
    i_idx, j_idx
        Particle neighbour pair indices from the PBF solver's existing
        neighbour table (we don't rebuild it here).
    sub_dt
        Substep duration in seconds.
    diffusion_rate
        Scale on neighbour-averaged thermal exchange (units: 1/s; higher
        = faster mixing). Multiplied by the harmonic-mean conductivity
        of each pair.
    ambient_rate
        Newton's-law cooling rate toward each particle's material
        `ambient_temperature` (units: 1/s).

    Returns
    -------
    n_phase_changes
        Count of particles that flipped material_id this substep.
    """
    p = world.particles
    if p.count == 0:
        return 0

    mats = _material_arrays(world)
    cond = mats["cond"]
    ambient = mats["ambient"]
    melt_t = mats["melt_t"]
    freeze_t = mats["freeze_t"]
    melt_to_id = mats["melt_to_id"]
    freeze_to_id = mats["freeze_to_id"]

    if _HAS_NATIVE_THERMAL:
        # Fast path: Rust scatters heat exchange + ambient relaxation +
        # phase-change classification in a single pass over the pair list.
        # Temperature and material_id are bytearray-backed so the kernel
        # mutates them in place, mirroring the numpy bincount pattern.
        n_p = p.count
        # temperature: writable bytearray view → assign back to p.temperature.
        t_buf = bytearray(np.ascontiguousarray(p.temperature,
                                                dtype=np.float32).tobytes())
        t_view = np.frombuffer(t_buf, dtype=np.float32)
        # material_id: writable bytearray for phase-change flips.
        m_buf = bytearray(np.ascontiguousarray(p.material_id,
                                                dtype=np.uint8).tobytes())
        m_view = np.frombuffer(m_buf, dtype=np.uint8)
        mass_bytes = np.ascontiguousarray(p.mass, dtype=np.float32).tobytes()
        i_bytes = np.ascontiguousarray(i_idx, dtype=np.int64).tobytes()
        j_bytes = np.ascontiguousarray(j_idx, dtype=np.int64).tobytes()
        n_changes = int(_native_core.thermal_step_rs(
            t_buf, m_buf, mass_bytes, i_bytes, j_bytes,
            cond.tobytes(), ambient.tobytes(),
            melt_t.tobytes(), freeze_t.tobytes(),
            melt_to_id.tobytes(), freeze_to_id.tobytes(),
            float(sub_dt), float(diffusion_rate), float(ambient_rate),
        ))
        p.temperature = np.array(t_view[:n_p], dtype=np.float32, copy=True)
        p.material_id = np.array(m_view[:n_p], dtype=np.uint8, copy=True)
        return n_changes

    ids = p.material_id.astype(np.int64)
    T = p.temperature.astype(np.float32, copy=True)

    # ── 1) Pairwise heat exchange (mass-weighted; harmonic mean conductivity)
    if i_idx.size > 0:
        ka = cond[ids[i_idx]]
        kb = cond[ids[j_idx]]
        active = (ka > 0.0) & (kb > 0.0)
        if np.any(active):
            ii = i_idx[active]
            jj = j_idx[active]
            ka = ka[active]
            kb = kb[active]
            k_harm = (2.0 * ka * kb / np.maximum(ka + kb, 1.0e-9)).astype(np.float32)

            ta = T[ii]
            tb = T[jj]
            ma = p.mass[ii]
            mb = p.mass[jj]
            # Flux q (units: temperature·mass) from i to j over sub_dt.
            q = k_harm * (ta - tb) * (diffusion_rate * sub_dt)
            # Clamp to equalisation flux to prevent overshoot.
            m_eff = 1.0 / (1.0 / np.maximum(ma, 1.0e-9) + 1.0 / np.maximum(mb, 1.0e-9))
            q_eq = (ta - tb) * m_eff
            pos_mask = q_eq >= 0.0
            q = np.where(pos_mask,
                         np.minimum(np.maximum(q, 0.0), q_eq),
                         np.maximum(np.minimum(q, 0.0), q_eq))
            # Apply: ti -= q/ma, tj += q/mb
            np.subtract.at(T, ii, q / np.maximum(ma, 1.0e-9))
            np.add.at(T, jj, q / np.maximum(mb, 1.0e-9))

    # ── 2) Ambient relaxation (implicit Euler)
    if ambient_rate > 0.0 and sub_dt > 0.0:
        amb_per_p = ambient[ids]
        denom = 1.0 + ambient_rate * sub_dt
        T = ((T + (ambient_rate * sub_dt) * amb_per_p) / denom).astype(np.float32)

    p.temperature = T

    # ── 3) Phase change
    n_changes = 0
    melt_t_per_p = melt_t[ids]
    freeze_t_per_p = freeze_t[ids]
    melt_target_per_p = melt_to_id[ids]
    freeze_target_per_p = freeze_to_id[ids]

    melt_mask = (T > melt_t_per_p) & (melt_target_per_p >= 0)
    freeze_mask = (T < freeze_t_per_p) & (freeze_target_per_p >= 0)

    if np.any(melt_mask):
        new_ids = melt_target_per_p[melt_mask]
        p.material_id[melt_mask] = new_ids.astype(np.uint8)
        n_changes += int(melt_mask.sum())
    if np.any(freeze_mask):
        new_ids = freeze_target_per_p[freeze_mask]
        p.material_id[freeze_mask] = new_ids.astype(np.uint8)
        n_changes += int(freeze_mask.sum())

    return n_changes
