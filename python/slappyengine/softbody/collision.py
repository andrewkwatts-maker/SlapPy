from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .world import SoftBodyWorld

# Detect the Rust-backed broadphase once at import time. Mirrors the
# ``_HAS_NATIVE_SOLVER`` switch in :mod:`slappyengine.softbody.solver`.
# The native entry point is a direct port of :func:`build_contact_pairs`
# below; it falls back transparently to the numpy implementation when the
# extension isn't present.
try:
    from slappyengine import _core as _native_core  # type: ignore
    _HAS_NATIVE_SOLVER = hasattr(_native_core, "build_contact_pairs")
    # Step 3 contact-projection native fast-paths. The broadphase
    # (Step 2) and the per-pair projection (this flag) ship together in
    # the same wheel, so a single `_HAS_NATIVE_SOLVER` should imply both
    # — but be defensive in case an older partial build is installed.
    _HAS_NATIVE_CONTACT_PROJECT = (
        _HAS_NATIVE_SOLVER
        and hasattr(_native_core, "project_node_beam_contacts")
        and hasattr(_native_core, "project_node_node_pairs")
    )
except ImportError:  # pragma: no cover - exercised in pure-Python envs
    _native_core = None  # type: ignore
    _HAS_NATIVE_SOLVER = False
    _HAS_NATIVE_CONTACT_PROJECT = False


@dataclass
class SpatialHash:
    """Uniform-grid cell index over node positions.

    The current broadphase is fully vectorised inside
    :func:`build_contact_pairs` (packed int64 keys + ``searchsorted``) so
    this class is only retained as an introspection / unit-test handle.
    Cell size = ``broadphase_cell_factor * max(beam.rest_length)``; the hash
    is rebuilt once per substep on current positions (see
    ``docs/softbody_design.md``).
    """
    cell_size: float
    node_cells: np.ndarray = field(default_factory=lambda: np.empty((0, 2), dtype=np.int32))

    @classmethod
    def build(cls, positions: np.ndarray, cell_size: float) -> "SpatialHash":
        if positions.shape[0] == 0:
            return cls(cell_size=cell_size)
        inv = 1.0 / max(cell_size, 1e-12)
        ij = np.floor(positions * inv).astype(np.int32)
        return cls(cell_size=cell_size, node_cells=ij)


def _contact_params(world: SoftBodyWorld) -> dict[str, Any]:
    cfg = world.config
    contact = cfg.get("contact") if isinstance(cfg, dict) else None
    defaults = {
        "enabled": True,
        "default_thickness": 0.5,
        "default_stiffness": 1.0e9,
        "broadphase_cell_factor": 1.5,
    }
    if not isinstance(contact, dict):
        return defaults
    out = dict(defaults)
    for k in defaults:
        if k in contact:
            out[k] = contact[k]
    return out


_CELL_HASH_PRIME_I = np.int64(73856093)
_CELL_HASH_PRIME_J = np.int64(19349663)

# Module-level cell offset array (3x3 = 9 neighbour cells incl. self).
# Was reallocated on every ``build_contact_pairs`` call — measurable
# Python overhead at high call counts.
_CELL_OFFSETS_9 = np.array(
    [[di, dj] for di in (-1, 0, 1) for dj in (-1, 0, 1)],
    dtype=np.int64,
)   # (9, 2)


def _pack_cell_keys(ij: np.ndarray) -> np.ndarray:
    """Encode integer cell (i, j) into a single int64 (XOR-mixed)."""
    i = ij[..., 0].astype(np.int64)
    j = ij[..., 1].astype(np.int64)
    return (i * _CELL_HASH_PRIME_I) ^ (j * _CELL_HASH_PRIME_J)


def resolve_contacts(world: SoftBodyWorld, sub_dt: float, eps: float,
                     params: dict[str, Any] | None = None) -> None:
    """One-shot wrapper: build pairs from current positions and project once.

    The solver normally calls :func:`build_contact_pairs` once per substep
    and :func:`project_contact_pairs` each iteration to amortise broadphase
    cost. This wrapper does both in one call and is convenient for tests.
    """
    P, B, NN_A, NN_B, resolved_params = build_contact_pairs(world, params)
    project_contact_pairs(world, sub_dt, eps, P, B, NN_A, NN_B, resolved_params)


def _project_node_beam_contacts(pos: np.ndarray, inv_mass: np.ndarray,
                                beam_a: np.ndarray, beam_b: np.ndarray,
                                P: np.ndarray, B: np.ndarray,
                                thickness: float, stiffness: float,
                                sub_dt: float, eps: float) -> None:
    # Native fast-path: the Rust kernel mirrors the numpy logic below
    # exactly (same closest-point math, same three-pass scatter in
    # input-array order, division-based normalisation). The
    # `test_block_on_block_stacks` canary depends on this ordering.
    if _HAS_NATIVE_CONTACT_PROJECT and P.size > 0:
        # pos is a writable f32 (N, 2) view we mutate in place; pass
        # directly (no copy) so PyBuffer can write through.
        inv_mass_bytes = np.ascontiguousarray(inv_mass, dtype=np.float32).tobytes()
        beam_a_bytes = np.ascontiguousarray(beam_a, dtype=np.uint32).tobytes()
        beam_b_bytes = np.ascontiguousarray(beam_b, dtype=np.uint32).tobytes()
        p_bytes = np.ascontiguousarray(P, dtype=np.int64).tobytes()
        b_bytes = np.ascontiguousarray(B, dtype=np.int64).tobytes()
        _native_core.project_node_beam_contacts(
            pos, inv_mass_bytes, beam_a_bytes, beam_b_bytes,
            p_bytes, b_bytes,
            float(thickness), float(stiffness),
            float(sub_dt), float(eps),
        )
        return

    A_idx = beam_a[B]
    C_idx = beam_b[B]
    p_n = pos[P]
    p_a = pos[A_idx]
    p_c = pos[C_idx]
    seg = p_c - p_a
    seg_len_sq = np.einsum("ij,ij->i", seg, seg)
    safe_seg = np.maximum(seg_len_sq, eps * eps)
    t = np.einsum("ij,ij->i", p_n - p_a, seg) / safe_seg
    t = np.clip(t, 0.0, 1.0)
    closest = p_a + seg * t[:, None]
    delta = p_n - closest
    dist_sq = np.einsum("ij,ij->i", delta, delta)
    dist = np.sqrt(np.maximum(dist_sq, eps * eps))

    contact_radius = thickness
    violated = dist < contact_radius
    if not np.any(violated):
        return

    P = P[violated]
    A_idx = A_idx[violated]
    C_idx = C_idx[violated]
    t = t[violated]
    dist = dist[violated]
    delta = delta[violated]

    normal = delta / dist[:, None]
    C_val = contact_radius - dist

    w_n = inv_mass[P]
    w_a = inv_mass[A_idx] * (1.0 - t)
    w_c = inv_mass[C_idx] * t

    alpha = 1.0 / max(stiffness * sub_dt * sub_dt, eps)
    denom = w_n + w_a + w_c + alpha
    denom = np.where(denom < eps, 1.0, denom)
    dlambda = C_val / denom

    corr = normal * dlambda[:, None]
    np.add.at(pos, P, corr * w_n[:, None])
    np.add.at(pos, A_idx, -corr * w_a[:, None])
    np.add.at(pos, C_idx, -corr * w_c[:, None])


def build_contact_pairs(world: SoftBodyWorld, params: dict[str, Any] | None = None
                        ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Precompute (node, beam) contact candidate pairs once per substep.

    Returns ``(node_idx, beam_idx, node_node_a, node_node_b, params)``. The
    spatial hash is built on current positions; the pair list is reused
    across all XPBD iterations within the substep (per ``docs/softbody_design.md``).

    Broadphase is fully vectorised: cell coordinates are packed to int64
    hash keys, beam-endpoint entries are sorted once, and each node's nine
    neighbour cells are joined into the sorted beam table via
    :func:`numpy.searchsorted`.
    """
    if params is None:
        params = _contact_params(world)
    empty = (np.empty(0, dtype=np.int64),) * 4
    if not params.get("enabled", True):
        return (*empty, params)

    n = world.nodes
    b = world.beams
    if n.count == 0:
        return (*empty, params)

    thickness = float(params["default_thickness"])
    cell_factor = float(params["broadphase_cell_factor"])

    # Native fast-path. The Rust kernel mirrors the numpy logic below
    # (uniform-grid spatial hash, 9-cell gather, dedup) but runs entirely
    # in compiled code without numpy's per-call allocation overhead.
    if _HAS_NATIVE_SOLVER:
        pos_bytes = np.ascontiguousarray(n.pos, dtype=np.float32).tobytes()
        # body_id is u16 on the node SoA — promote to u32 for a fixed
        # contract on the Rust side (avoids a second dtype overload).
        body_id_u32 = n.body_id.astype(np.uint32, copy=False)
        body_id_bytes = np.ascontiguousarray(body_id_u32, dtype=np.uint32).tobytes()
        if b.count > 0:
            beam_a_bytes = np.ascontiguousarray(b.node_a, dtype=np.uint32).tobytes()
            beam_b_bytes = np.ascontiguousarray(b.node_b, dtype=np.uint32).tobytes()
            beam_body_bytes = np.ascontiguousarray(
                b.body_id.astype(np.uint32, copy=False), dtype=np.uint32
            ).tobytes()
            beam_rest_bytes = np.ascontiguousarray(b.rest_length, dtype=np.float32).tobytes()
            # numpy bool view → uint8 (1 byte per element) so the Rust
            # side sees a clean ``u8`` slice.
            beam_broken_bytes = np.ascontiguousarray(
                b.broken.view(np.uint8), dtype=np.uint8
            ).tobytes()
        else:
            beam_a_bytes = b""
            beam_b_bytes = b""
            beam_body_bytes = b""
            beam_rest_bytes = b""
            beam_broken_bytes = b""
        p_b, b_b, nna_b, nnb_b = _native_core.build_contact_pairs(
            pos_bytes, body_id_bytes, int(n.count),
            beam_a_bytes, beam_b_bytes, beam_body_bytes,
            beam_rest_bytes, beam_broken_bytes, int(b.count),
            float(thickness), float(cell_factor),
        )
        P = np.frombuffer(p_b, dtype=np.int64)
        B = np.frombuffer(b_b, dtype=np.int64)
        NN_A = np.frombuffer(nna_b, dtype=np.int64)
        NN_B = np.frombuffer(nnb_b, dtype=np.int64)
        return P, B, NN_A, NN_B, params

    pos = n.pos
    body_id_n = n.body_id.astype(np.int64, copy=False)

    if b.count > 0:
        max_rest = float(np.max(b.rest_length))
        beam_a = b.node_a.astype(np.int64, copy=False)
        beam_b = b.node_b.astype(np.int64, copy=False)
        beam_body = b.body_id.astype(np.int64, copy=False)
        not_broken = ~b.broken
    else:
        max_rest = thickness * 2.0
        beam_a = np.empty(0, dtype=np.int64)
        beam_b = np.empty(0, dtype=np.int64)
        beam_body = np.empty(0, dtype=np.int64)
        not_broken = np.empty(0, dtype=bool)
    cell_size = max(max_rest * cell_factor, thickness * 2.0, 1e-9)

    inv_cell = 1.0 / cell_size
    node_ij = np.floor(pos * inv_cell).astype(np.int64)
    node_keys = _pack_cell_keys(node_ij)

    P = np.empty(0, dtype=np.int64)
    B = np.empty(0, dtype=np.int64)
    nodes_with_beam_candidate = np.zeros(n.count, dtype=bool)

    if b.count > 0 and beam_a.size > 0:
        beam_keys_a = _pack_cell_keys(node_ij[beam_a])
        beam_keys_b = _pack_cell_keys(node_ij[beam_b])
        all_keys = np.concatenate([beam_keys_a, beam_keys_b])
        all_bidx = np.concatenate([beam_a * 0 + np.arange(beam_a.size, dtype=np.int64),
                                   beam_a * 0 + np.arange(beam_a.size, dtype=np.int64)])
        order = np.argsort(all_keys, kind="stable")
        sorted_keys = all_keys[order]
        sorted_bidx = all_bidx[order]

        # Batched 9-cell broadphase: build all (node, cell-offset) queries
        # into one (n, 9) array, do ONE searchsorted pair (was 18 separate
        # calls inside a Python double-loop). Adopts the fluid PBF pattern
        # from ``_build_neighbour_table`` — pure vectorisation, no float-
        # order changes.
        node_indices = np.arange(n.count, dtype=np.int64)
        query_ij_all = node_ij[:, None, :] + _CELL_OFFSETS_9[None, :, :]  # (n, 9, 2)
        qkey_all = (
            (query_ij_all[..., 0] * _CELL_HASH_PRIME_I)
            ^ (query_ij_all[..., 1] * _CELL_HASH_PRIME_J)
        )                                                                # (n, 9)
        lo_all = np.searchsorted(sorted_keys, qkey_all, side="left")    # (n, 9)
        hi_all = np.searchsorted(sorted_keys, qkey_all, side="right")
        counts_all = (hi_all - lo_all).astype(np.int64)                  # (n, 9)
        total_pairs = int(counts_all.sum())

        if total_pairs > 0:
            counts_flat = counts_all.ravel()                              # (n*9,)
            lo_flat = lo_all.ravel()
            # Repeat each (node, cell-offset) slot's node-index counts_flat times
            node_per_slot = np.broadcast_to(
                node_indices[:, None], (n.count, 9)).ravel()              # (n*9,)
            P_all = np.repeat(node_per_slot, counts_flat)
            starts = np.repeat(lo_flat, counts_flat)
            local_idx = np.arange(total_pairs, dtype=np.int64) - np.repeat(
                np.cumsum(counts_flat) - counts_flat, counts_flat
            )
            B_all = sorted_bidx[starts + local_idx]
            mask = not_broken[B_all]
            mask &= beam_body[B_all] != body_id_n[P_all]
            mask &= beam_a[B_all] != P_all
            mask &= beam_b[B_all] != P_all
            P = P_all[mask]
            B = B_all[mask]
            if P.size > 0:
                packed = P * (np.int64(b.count) + 1) + B
                _, unique_idx = np.unique(packed, return_index=True)
                P = P[unique_idx]
                B = B[unique_idx]
                nodes_with_beam_candidate[np.unique(P)] = True

    NN_A = np.empty(0, dtype=np.int64)
    NN_B = np.empty(0, dtype=np.int64)
    fallback_nodes = np.nonzero(~nodes_with_beam_candidate)[0].astype(np.int64)
    if fallback_nodes.size > 0:
        sorted_node_order = np.argsort(node_keys, kind="stable")
        sorted_node_keys = node_keys[sorted_node_order]
        sorted_nodes_by_cell = sorted_node_order
        # Batched 9-cell broadphase — same pattern as the beam pass above.
        # Collapses 18 searchsorted calls into 2.
        fb = fallback_nodes
        fb_ij = node_ij[fb]                                              # (m, 2)
        fb_qij_all = fb_ij[:, None, :] + _CELL_OFFSETS_9[None, :, :]      # (m, 9, 2)
        fb_qkey_all = (
            (fb_qij_all[..., 0] * _CELL_HASH_PRIME_I)
            ^ (fb_qij_all[..., 1] * _CELL_HASH_PRIME_J)
        )                                                                # (m, 9)
        lo_nn = np.searchsorted(sorted_node_keys, fb_qkey_all, side="left")
        hi_nn = np.searchsorted(sorted_node_keys, fb_qkey_all, side="right")
        cnt_nn = (hi_nn - lo_nn).astype(np.int64)
        total_nn = int(cnt_nn.sum())
        if total_nn > 0:
            cnt_flat = cnt_nn.ravel()
            lo_flat = lo_nn.ravel()
            fb_per_slot = np.broadcast_to(fb[:, None], (fb.size, 9)).ravel()
            A_all = np.repeat(fb_per_slot, cnt_flat)
            starts = np.repeat(lo_flat, cnt_flat)
            local_idx = np.arange(total_nn, dtype=np.int64) - np.repeat(
                np.cumsum(cnt_flat) - cnt_flat, cnt_flat
            )
            B_all = sorted_nodes_by_cell[starts + local_idx]
            mask = (body_id_n[A_all] != body_id_n[B_all]) & (A_all < B_all)
            NN_A = A_all[mask]
            NN_B = B_all[mask]
            if NN_A.size > 0:
                packed = NN_A * np.int64(n.count + 1) + NN_B
                _, unique_idx = np.unique(packed, return_index=True)
                NN_A = NN_A[unique_idx]
                NN_B = NN_B[unique_idx]

    return P, B, NN_A, NN_B, params


def project_contact_pairs(world: SoftBodyWorld, sub_dt: float, eps: float,
                          pair_node: np.ndarray, pair_beam: np.ndarray,
                          nn_a: np.ndarray, nn_b: np.ndarray,
                          params: dict[str, Any]) -> None:
    """Project precomputed contact pairs as XPBD position corrections.

    Called once per XPBD iteration; pair lists were built once per substep
    by :func:`build_contact_pairs`.
    """
    if not params.get("enabled", True):
        return
    n = world.nodes
    b = world.beams
    pos = n.pos
    inv_mass = n.inv_mass

    thickness = float(params["default_thickness"])
    stiffness = float(params["default_stiffness"])

    if pair_node.size > 0 and b.count > 0:
        beam_a = b.node_a.astype(np.int64, copy=False)
        beam_b = b.node_b.astype(np.int64, copy=False)
        _project_node_beam_contacts(pos, inv_mass, beam_a, beam_b,
                                    pair_node, pair_beam,
                                    thickness, stiffness, sub_dt, eps)

    if nn_a.size > 0:
        _project_node_node_pairs(pos, inv_mass, nn_a, nn_b,
                                 thickness, stiffness, sub_dt, eps)


def _project_node_node_pairs(pos: np.ndarray, inv_mass: np.ndarray,
                             A: np.ndarray, B: np.ndarray,
                             thickness: float, stiffness: float,
                             sub_dt: float, eps: float) -> None:
    if _HAS_NATIVE_CONTACT_PROJECT and A.size > 0:
        inv_mass_bytes = np.ascontiguousarray(inv_mass, dtype=np.float32).tobytes()
        a_bytes = np.ascontiguousarray(A, dtype=np.int64).tobytes()
        b_bytes = np.ascontiguousarray(B, dtype=np.int64).tobytes()
        _native_core.project_node_node_pairs(
            pos, inv_mass_bytes, a_bytes, b_bytes,
            float(thickness), float(stiffness),
            float(sub_dt), float(eps),
        )
        return

    contact_radius = 2.0 * thickness
    delta = pos[A] - pos[B]
    dist_sq = np.einsum("ij,ij->i", delta, delta)
    dist = np.sqrt(np.maximum(dist_sq, eps * eps))
    violated = dist < contact_radius
    if not np.any(violated):
        return
    A = A[violated]
    B = B[violated]
    delta = delta[violated]
    dist = dist[violated]
    normal = delta / dist[:, None]
    C_val = contact_radius - dist
    w_a = inv_mass[A]
    w_b = inv_mass[B]
    alpha = 1.0 / max(stiffness * sub_dt * sub_dt, eps)
    denom = w_a + w_b + alpha
    denom = np.where(denom < eps, 1.0, denom)
    dlambda = C_val / denom
    corr = normal * dlambda[:, None]
    np.add.at(pos, A, corr * w_a[:, None])
    np.add.at(pos, B, -corr * w_b[:, None])


__all__ = ["SpatialHash", "resolve_contacts", "build_contact_pairs",
           "project_contact_pairs"]
