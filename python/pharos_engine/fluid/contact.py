from __future__ import annotations

from typing import Any

import numpy as np

from .world import FluidWorld


def _softbody_beam_endpoints(softbody) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    if softbody is None or softbody.beams.count == 0:
        return None
    a = softbody.beams.node_a.astype(np.int64, copy=False)
    b = softbody.beams.node_b.astype(np.int64, copy=False)
    not_broken = ~softbody.beams.broken
    if not np.any(not_broken):
        return None
    a = a[not_broken]; b = b[not_broken]
    pa = softbody.nodes.pos[a]
    pb = softbody.nodes.pos[b]
    return a, b, np.stack([pa, pb], axis=1)


def project_fluid_softbody_contacts(
    fluid: FluidWorld,
    softbody,
    sub_dt: float,
) -> None:
    if not bool(fluid.config["contact"]["enabled"]):
        return
    if softbody is None:
        return
    bundle = _softbody_beam_endpoints(softbody)
    if bundle is None:
        return
    a_nodes, b_nodes, ab = bundle
    pa = ab[:, 0, :]
    pb = ab[:, 1, :]

    p = fluid.particles
    if p.count == 0:
        return

    cfg = fluid.config["contact"]
    thickness = float(cfg["thickness"])
    stiffness = float(cfg["stiffness"])
    eps = float(fluid.config["velocity_epsilon"])

    n_parts = p.count
    n_beams = pa.shape[0]
    if n_beams == 0:
        return

    cell = max(thickness * 2.0, 1e-3)
    inv_cell = 1.0 / cell
    P1 = np.int64(73856093)
    P2 = np.int64(19349663)

    beam_min = np.minimum(pa, pb)
    beam_max = np.maximum(pa, pb)
    bx0 = np.floor(beam_min[:, 0] * inv_cell).astype(np.int64)
    by0 = np.floor(beam_min[:, 1] * inv_cell).astype(np.int64)
    bx1 = np.floor(beam_max[:, 0] * inv_cell).astype(np.int64)
    by1 = np.floor(beam_max[:, 1] * inv_cell).astype(np.int64)

    spans_x = (bx1 - bx0 + 1).astype(np.int64)
    spans_y = (by1 - by0 + 1).astype(np.int64)
    if spans_x.max() * spans_y.max() > 16:
        # Very long beams — degrade to per-particle nearest-beam brute force gather
        return _brute_force_contact(fluid, pa, pb, thickness, stiffness, sub_dt, eps)

    beam_ids: list[np.ndarray] = []
    beam_keys: list[np.ndarray] = []
    for dx in range(int(spans_x.max())):
        for dy in range(int(spans_y.max())):
            mask = (dx < spans_x) & (dy < spans_y)
            if not np.any(mask):
                continue
            ks = ((bx0[mask] + dx) * P1) ^ ((by0[mask] + dy) * P2)
            beam_keys.append(ks)
            beam_ids.append(np.nonzero(mask)[0].astype(np.int64))
    if not beam_ids:
        return
    beam_keys_arr = np.concatenate(beam_keys)
    beam_ids_arr = np.concatenate(beam_ids)
    order = np.argsort(beam_keys_arr, kind="stable")
    beam_keys_arr = beam_keys_arr[order]
    beam_ids_arr = beam_ids_arr[order]

    pix = np.floor(p.pos[:, 0] * inv_cell).astype(np.int64)
    piy = np.floor(p.pos[:, 1] * inv_cell).astype(np.int64)
    pkey = (pix * P1) ^ (piy * P2)
    lo = np.searchsorted(beam_keys_arr, pkey, side="left")
    hi = np.searchsorted(beam_keys_arr, pkey, side="right")
    counts = (hi - lo).astype(np.int64)
    total = int(counts.sum())
    if total == 0:
        return
    p_idx = np.repeat(np.arange(n_parts, dtype=np.int64), counts)
    starts = np.cumsum(counts) - counts
    local_idx = np.arange(total, dtype=np.int64) - np.repeat(starts, counts)
    base = np.repeat(lo, counts)
    b_local = base + local_idx
    b_id = beam_ids_arr[b_local]

    seen_key = p_idx * (n_beams + 1) + b_id
    unique_keys, unique_first = np.unique(seen_key, return_index=True)
    p_idx = p_idx[unique_first]
    b_id = b_id[unique_first]

    pa_q = pa[b_id]
    pb_q = pb[b_id]
    n_pos = p.pos[p_idx]
    ab_vec = pb_q - pa_q
    ab_len_sq = np.einsum("ij,ij->i", ab_vec, ab_vec)
    t = np.einsum("ij,ij->i", n_pos - pa_q, ab_vec) / np.maximum(ab_len_sq, eps)
    t = np.clip(t, 0.0, 1.0)
    closest = pa_q + ab_vec * t[:, None]
    delta = n_pos - closest
    dist = np.linalg.norm(delta, axis=1)
    contact_mask = dist < thickness
    if not np.any(contact_mask):
        return
    p_idx = p_idx[contact_mask]
    b_id = b_id[contact_mask]
    delta = delta[contact_mask]
    dist = dist[contact_mask]
    t = t[contact_mask]

    n_dir = delta / np.maximum(dist, eps)[:, None]
    c_vals = thickness - dist
    inv_dt2 = 1.0 / (sub_dt * sub_dt)
    alpha = inv_dt2 / max(stiffness, eps)

    a_local = a_nodes[b_id]
    b_local_n = b_nodes[b_id]
    w_p = p.inv_mass[p_idx]
    w_a = softbody.nodes.inv_mass[a_local] * (1.0 - t)
    w_b = softbody.nodes.inv_mass[b_local_n] * t
    denom = w_p + w_a + w_b + alpha
    dlambda = c_vals / np.maximum(denom, eps)

    corr_p = n_dir * (w_p * dlambda)[:, None]
    corr_a = -n_dir * (w_a * dlambda)[:, None]
    corr_b = -n_dir * (w_b * dlambda)[:, None]

    np.add.at(p.pos, p_idx, corr_p)
    np.add.at(softbody.nodes.pos, a_local, corr_a)
    np.add.at(softbody.nodes.pos, b_local_n, corr_b)


def _brute_force_contact(fluid, pa, pb, thickness, stiffness, sub_dt, eps):
    p = fluid.particles
    n_p = p.count
    n_b = pa.shape[0]
    if n_p == 0 or n_b == 0:
        return
    # Vectorised pairwise (only used when beams are huge; small softbody case)
    pp = p.pos[:, None, :]
    pA = pa[None, :, :]
    pB = pb[None, :, :]
    ab_vec = pB - pA
    ab_len_sq = np.einsum("ijk,ijk->ij", ab_vec, ab_vec)
    t = np.einsum("ijk,ijk->ij", pp - pA, ab_vec) / np.maximum(ab_len_sq, eps)
    t = np.clip(t, 0.0, 1.0)
    closest = pA + ab_vec * t[:, :, None]
    delta = pp - closest
    dist = np.linalg.norm(delta, axis=2)
    mask = dist < thickness
    if not np.any(mask):
        return
    # Take the closest beam per particle
    masked_dist = np.where(mask, dist, np.inf)
    nearest = np.argmin(masked_dist, axis=1)
    has = np.isfinite(masked_dist[np.arange(n_p), nearest])
    p_idx = np.nonzero(has)[0]
    if p_idx.size == 0:
        return
    b_id = nearest[p_idx]
    d = delta[p_idx, b_id]
    dist_v = dist[p_idx, b_id]
    n_dir = d / np.maximum(dist_v, eps)[:, None]
    corr = n_dir * (thickness - dist_v)[:, None]
    np.add.at(p.pos, p_idx, corr)


__all__ = ["project_fluid_softbody_contacts"]
