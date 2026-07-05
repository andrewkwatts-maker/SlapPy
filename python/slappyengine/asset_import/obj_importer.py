"""Wavefront .obj parser — no third-party deps.

Handles the subset the HH4 renderer actually consumes:

* ``v x y z``   — vertex position (w component ignored)
* ``vn x y z``  — vertex normal
* ``vt u v``    — texture coordinate
* ``f a b c ...`` — face (n-gon auto-triangulated as a fan)
* ``mtllib file.mtl`` / ``usemtl name`` — recorded but not resolved

Face indices can be:

* ``v``          — position only
* ``v/vt``       — position + uv
* ``v//vn``      — position + normal
* ``v/vt/vn``    — position + uv + normal

.obj uses **1-based** indices; we convert to 0-based on load.
Negative indices (relative to the current list length) are also
supported per the .obj spec.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .import_result import ImportResult


def _parse_face_token(
    tok: str,
    n_pos: int,
    n_uv: int,
    n_nrm: int,
) -> tuple[int, int | None, int | None]:
    """Parse a single ``v/vt/vn`` face token.

    Returns ``(pos_idx, uv_idx_or_None, nrm_idx_or_None)`` all 0-based.
    """
    parts = tok.split("/")
    # position (required)
    pi_raw = int(parts[0])
    pi = pi_raw - 1 if pi_raw > 0 else n_pos + pi_raw
    ui: int | None = None
    ni: int | None = None
    if len(parts) >= 2 and parts[1] != "":
        ui_raw = int(parts[1])
        ui = ui_raw - 1 if ui_raw > 0 else n_uv + ui_raw
    if len(parts) >= 3 and parts[2] != "":
        ni_raw = int(parts[2])
        ni = ni_raw - 1 if ni_raw > 0 else n_nrm + ni_raw
    return pi, ui, ni


def _build_mesh(
    positions: list[tuple[float, float, float]],
    uvs: list[tuple[float, float]],
    normals: list[tuple[float, float, float]],
    faces: list[list[tuple[int, int | None, int | None]]],
) -> Any:
    """Build a GpuMesh (if importable) or a lightweight fallback dict."""
    # Deduplicate (pos, uv, nrm) tuples into a linear vertex buffer.
    # We keep it as a plain Python dict of tuple → index; for a few
    # thousand verts this is fast enough and avoids numpy overhead.
    vert_map: dict[tuple[int, int | None, int | None], int] = {}
    ordered_keys: list[tuple[int, int | None, int | None]] = []
    indices: list[int] = []

    for face in faces:
        # Triangulate n-gons as a fan: (v0, v1, v2), (v0, v2, v3), ...
        if len(face) < 3:
            continue
        idx_local: list[int] = []
        for key in face:
            if key not in vert_map:
                vert_map[key] = len(ordered_keys)
                ordered_keys.append(key)
            idx_local.append(vert_map[key])
        for i in range(1, len(idx_local) - 1):
            indices.append(idx_local[0])
            indices.append(idx_local[i])
            indices.append(idx_local[i + 1])

    # Try to build a real GpuMesh. If wgpu / _validation is not
    # importable in this environment (e.g. minimal test install), fall
    # back to a lightweight namedtuple-alike so tests can still inspect
    # counts.
    try:
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex  # noqa: PLC0415
    except Exception:  # pragma: no cover - only hit in stripped test env
        GpuMesh = None
        MeshVertex = None

    vertices: list[Any] = []
    for pi, ui, ni in ordered_keys:
        pos = positions[pi] if 0 <= pi < len(positions) else (0.0, 0.0, 0.0)
        uv = uvs[ui] if (ui is not None and 0 <= ui < len(uvs)) else (0.0, 0.0)
        nrm = (
            normals[ni]
            if (ni is not None and 0 <= ni < len(normals))
            else (0.0, 1.0, 0.0)
        )
        if MeshVertex is not None:
            vertices.append(MeshVertex(position=pos, normal=nrm, uv=uv))
        else:
            vertices.append({"position": pos, "normal": nrm, "uv": uv})

    if GpuMesh is not None:
        try:
            return GpuMesh(vertices, indices)
        except Exception:
            # Fallback if the vertex list contains only dicts (should not
            # happen given the branch above, but defensive nonetheless).
            pass

    # Fallback lightweight mesh — dict with the same essentials.
    return {
        "vertices": vertices,
        "indices": indices,
        "vertex_count": len(vertices),
        "triangle_count": len(indices) // 3,
    }


def import_obj(path: str | Path) -> ImportResult:
    """Parse a Wavefront .obj file into an :class:`ImportResult`.

    Parameters
    ----------
    path
        Path to the .obj file (str or ``pathlib.Path``).

    Returns
    -------
    ImportResult
        ``kind="mesh"``. ``meshes`` contains one entry per ``usemtl``
        group (or a single entry if the file has no material groups).
    """
    path = Path(path)
    t0 = time.perf_counter()
    text = path.read_text(encoding="utf-8", errors="replace")

    positions: list[tuple[float, float, float]] = []
    uvs: list[tuple[float, float]] = []
    normals: list[tuple[float, float, float]] = []

    # We keep faces per-group so ``usemtl`` breaks produce separate
    # meshes. Group 0 = "default" (any face before the first usemtl).
    groups: list[dict[str, Any]] = [
        {"material": None, "faces": []}
    ]

    mtllib: str | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v":
            if len(parts) >= 4:
                positions.append(
                    (float(parts[1]), float(parts[2]), float(parts[3]))
                )
        elif tag == "vt":
            # .obj UVs are (u, v[, w]); we take only u,v
            if len(parts) >= 3:
                uvs.append((float(parts[1]), float(parts[2])))
            elif len(parts) == 2:
                uvs.append((float(parts[1]), 0.0))
        elif tag == "vn":
            if len(parts) >= 4:
                normals.append(
                    (float(parts[1]), float(parts[2]), float(parts[3]))
                )
        elif tag == "f":
            face_tokens = parts[1:]
            face = [
                _parse_face_token(t, len(positions), len(uvs), len(normals))
                for t in face_tokens
            ]
            groups[-1]["faces"].append(face)
        elif tag == "mtllib":
            if len(parts) >= 2:
                mtllib = parts[1]
        elif tag == "usemtl":
            # Start a new group.
            mat = parts[1] if len(parts) >= 2 else None
            # If the current group is empty, just rename it; otherwise
            # push a fresh one.
            if not groups[-1]["faces"]:
                groups[-1]["material"] = mat
            else:
                groups.append({"material": mat, "faces": []})
        # o / g / s / other tags — ignored for now.

    meshes: list[Any] = []
    materials: list[dict[str, Any]] = []
    for g in groups:
        if not g["faces"]:
            continue
        mesh = _build_mesh(positions, uvs, normals, g["faces"])
        meshes.append(mesh)
        if g["material"] is not None:
            materials.append({"name": g["material"], "mtllib": mtllib})

    dt_ms = (time.perf_counter() - t0) * 1000.0
    return ImportResult(
        kind="mesh",
        meshes=meshes,
        materials=materials,
        metadata={
            "source_path": str(path),
            "importer_used": "import_obj",
            "load_ms": dt_ms,
            "position_count": len(positions),
            "uv_count": len(uvs),
            "normal_count": len(normals),
            "mesh_count": len(meshes),
            "mtllib": mtllib,
        },
    )
