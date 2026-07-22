"""Soft-import stubs for .fbx / .ply / .stl.

The engine does not (yet) ship first-party parsers for these formats.
We try optional libraries — trimesh for .ply/.stl, FBX SDK / ufbx for
.fbx — and, if none are available, return an empty
:class:`ImportResult` plus a helpful log message. This lets user code
call :func:`pharos_engine.asset_import.import_asset` without crashing
when a file happens to be one of these formats.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np

from .import_result import ImportResult

log = logging.getLogger("pharos_engine.asset_import")


def _try_trimesh(path: Path) -> Any | None:
    """Return a trimesh.Trimesh if trimesh is installed, else None."""
    try:
        import trimesh  # noqa: PLC0415
    except ImportError:
        return None
    try:
        return trimesh.load(str(path), force="mesh")
    except Exception as e:
        log.warning("trimesh failed to load %s: %s", path, e)
        return None


def _mesh_from_trimesh(tm: Any) -> Any:
    """Convert a trimesh.Trimesh into a GpuMesh-compatible object."""
    try:
        from pharos_engine.gpu.mesh import GpuMesh, MeshVertex  # noqa: PLC0415
    except Exception:
        GpuMesh = None
        MeshVertex = None

    positions = np.asarray(tm.vertices, dtype=np.float32)
    faces = np.asarray(tm.faces, dtype=np.int64)
    try:
        normals = np.asarray(tm.vertex_normals, dtype=np.float32)
    except Exception:
        normals = np.zeros_like(positions)
        normals[:, 1] = 1.0

    verts: list[Any] = []
    for i in range(positions.shape[0]):
        pos = tuple(float(x) for x in positions[i])
        nrm = tuple(float(x) for x in normals[i])
        if MeshVertex is not None:
            verts.append(MeshVertex(position=pos, normal=nrm, uv=(0.0, 0.0)))
        else:
            verts.append({"position": pos, "normal": nrm, "uv": (0.0, 0.0)})

    idx = [int(x) for x in faces.flatten()]
    if GpuMesh is not None:
        try:
            return GpuMesh(verts, idx)
        except Exception:
            pass
    return {
        "vertices": verts,
        "indices": idx,
        "vertex_count": len(verts),
        "triangle_count": len(idx) // 3,
    }


def _empty_result(path: Path, importer: str, reason: str) -> ImportResult:
    log.warning(
        "%s: no parser available for %s (%s). "
        "Install with: pip install pharos_engine[assets]",
        importer, path.suffix, reason,
    )
    return ImportResult(
        kind="mesh",
        meshes=[],
        metadata={
            "source_path": str(path),
            "importer_used": importer,
            "load_ms": 0.0,
            "stub": True,
            "reason": reason,
        },
    )


def import_ply(path: str | Path) -> ImportResult:
    """Load a .ply file via trimesh (if installed) or return an empty stub."""
    path = Path(path)
    t0 = time.perf_counter()
    tm = _try_trimesh(path)
    if tm is None:
        return _empty_result(path, "import_ply", "trimesh not installed")
    mesh = _mesh_from_trimesh(tm)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    return ImportResult(
        kind="mesh",
        meshes=[mesh],
        metadata={
            "source_path": str(path),
            "importer_used": "import_ply",
            "load_ms": dt_ms,
            "backend": "trimesh",
        },
    )


def import_stl(path: str | Path) -> ImportResult:
    """Load a .stl file via trimesh (if installed) or return an empty stub."""
    path = Path(path)
    t0 = time.perf_counter()
    tm = _try_trimesh(path)
    if tm is None:
        return _empty_result(path, "import_stl", "trimesh not installed")
    mesh = _mesh_from_trimesh(tm)
    dt_ms = (time.perf_counter() - t0) * 1000.0
    return ImportResult(
        kind="mesh",
        meshes=[mesh],
        metadata={
            "source_path": str(path),
            "importer_used": "import_stl",
            "load_ms": dt_ms,
            "backend": "trimesh",
        },
    )


def import_fbx(path: str | Path) -> ImportResult:
    """Load a .fbx file — currently soft-import only.

    ``ufbx`` and the Autodesk FBX SDK are both optional. Absent either,
    we return an empty result with a helpful log line so the caller
    can decide whether to error or fall back to another format.
    """
    path = Path(path)
    # Try ufbx first (small pure-C library, no license restrictions).
    try:
        import ufbx  # noqa: F401, PLC0415
        # ufbx has minimal Python bindings — for now we just accept
        # that the presence of ufbx enables .fbx loading conceptually.
        # A future PR wires the actual mesh extraction; for this sprint
        # we return an empty-but-not-stubbed result.
        return ImportResult(
            kind="mesh",
            meshes=[],
            metadata={
                "source_path": str(path),
                "importer_used": "import_fbx",
                "load_ms": 0.0,
                "backend": "ufbx",
                "note": "ufbx detected but mesh extraction not yet wired",
            },
        )
    except ImportError:
        pass
    return _empty_result(path, "import_fbx", "no fbx parser installed")
