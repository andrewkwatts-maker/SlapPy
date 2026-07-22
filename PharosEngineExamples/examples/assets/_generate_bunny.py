"""_generate_bunny — procedural low-poly "bunny" mesh generator.

Emits :file:`bunny_low.obj` + :file:`bunny_low.mtl` next to this script so the
:mod:`hello_render_real` demo has a substantive 3D asset to render without
requiring a Stanford bunny fetch from the web.

Shape
-----
* **Body** — a UV-sphere (32 slices × 12 stacks) non-uniformly scaled to a
  pear (``x=1.0, y=1.2, z=1.4``). Anchored at world origin.
* **Head** — a smaller UV-sphere (16 slices × 8 stacks) at scale ``0.6``
  offset ``+y ≈ 1.3`` so it welds naturally to the top of the body.
* **Ears** — two 8-sided cones (radius 0.08, length 0.36) angled outward
  from the top of the head (``±20°`` on the ``x`` axis).

Vertex count target: ~250.  Triangle count target: ~500.  A real MTL file
with a warm diffuse fur tone is emitted alongside.

Run
---
>>> python _generate_bunny.py

The two output files are committed into the repo alongside this script;
regenerating them should be deterministic (no ``random`` calls anywhere).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]
Face = Tuple[int, int, int]  # 1-indexed vertex ids matching OBJ convention


@dataclass
class Mesh:
    """Accumulator for a triangle mesh being assembled from parts."""

    verts: List[Vec3]
    normals: List[Vec3]
    faces: List[Face]  # 1-indexed pointing into verts + normals

    def add_vertex(self, v: Vec3, n: Vec3) -> int:
        """Append a vertex + normal, return the 1-based OBJ index."""
        self.verts.append(v)
        self.normals.append(n)
        return len(self.verts)

    def add_face(self, a: int, b: int, c: int) -> None:
        self.faces.append((a, b, c))


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _normalize(v: Vec3) -> Vec3:
    x, y, z = v
    m = math.sqrt(x * x + y * y + z * z)
    if m == 0.0:
        return (0.0, 1.0, 0.0)
    return (x / m, y / m, z / m)


def _uv_sphere(
    mesh: Mesh,
    slices: int,
    stacks: int,
    center: Vec3,
    scale: Vec3,
) -> None:
    """Emit a UV-sphere into ``mesh``.

    Uses a per-vertex outward normal (analytic sphere normal, transformed
    by the diagonal scale so lighting matches the deformed pear shape).
    """
    cx, cy, cz = center
    sx, sy, sz = scale

    # Build the ring grid.  We keep vertex ids in a 2D array so face
    # emission is a straight lookup.
    ring_ids: List[List[int]] = []
    for i in range(stacks + 1):
        theta = math.pi * i / stacks  # 0..pi (colatitude)
        sin_t = math.sin(theta)
        cos_t = math.cos(theta)
        row: List[int] = []
        for j in range(slices):
            phi = 2.0 * math.pi * j / slices  # 0..2pi (longitude)
            sin_p = math.sin(phi)
            cos_p = math.cos(phi)
            nx = sin_t * cos_p
            ny = cos_t
            nz = sin_t * sin_p
            vx = cx + sx * nx
            vy = cy + sy * ny
            vz = cz + sz * nz
            # Scale the normal by (1/sx, 1/sy, 1/sz) so it stays correct
            # under the non-uniform scale, then re-normalise.
            n_scaled = _normalize((nx / sx, ny / sy, nz / sz))
            idx = mesh.add_vertex((vx, vy, vz), n_scaled)
            row.append(idx)
        ring_ids.append(row)

    # Triangulate — two tris per quad, poles collapse cleanly.
    for i in range(stacks):
        for j in range(slices):
            a = ring_ids[i][j]
            b = ring_ids[i][(j + 1) % slices]
            c = ring_ids[i + 1][j]
            d = ring_ids[i + 1][(j + 1) % slices]
            # Skip degenerate triangles at the poles.
            if i != 0:
                mesh.add_face(a, c, b)
            if i != stacks - 1:
                mesh.add_face(b, c, d)


def _cone(
    mesh: Mesh,
    radius: float,
    length: float,
    segments: int,
    base_center: Vec3,
    tip_offset: Vec3,
) -> None:
    """Emit a closed cone with base at ``base_center`` and tip at ``base + tip_offset``."""
    bcx, bcy, bcz = base_center
    tx, ty, tz = (bcx + tip_offset[0], bcy + tip_offset[1], bcz + tip_offset[2])

    # Choose an axis perpendicular to the cone direction to lay the base ring.
    axis = _normalize(tip_offset)
    # Pick a stable "up" that's not parallel to the axis.
    up = (0.0, 1.0, 0.0) if abs(axis[1]) < 0.9 else (1.0, 0.0, 0.0)
    # right = normalize(cross(axis, up))
    rx = axis[1] * up[2] - axis[2] * up[1]
    ry = axis[2] * up[0] - axis[0] * up[2]
    rz = axis[0] * up[1] - axis[1] * up[0]
    right = _normalize((rx, ry, rz))
    # forward = cross(axis, right)
    fx = axis[1] * right[2] - axis[2] * right[1]
    fy = axis[2] * right[0] - axis[0] * right[2]
    fz = axis[0] * right[1] - axis[1] * right[0]
    forward = _normalize((fx, fy, fz))

    # Base ring vertices.
    base_ids: List[int] = []
    for k in range(segments):
        angle = 2.0 * math.pi * k / segments
        cx = math.cos(angle) * radius
        sy = math.sin(angle) * radius
        vx = bcx + right[0] * cx + forward[0] * sy
        vy = bcy + right[1] * cx + forward[1] * sy
        vz = bcz + right[2] * cx + forward[2] * sy
        # Outward-pointing normal (side of cone).
        outward = _normalize((vx - bcx, vy - bcy, vz - bcz))
        base_ids.append(mesh.add_vertex((vx, vy, vz), outward))

    # Tip vertex.
    tip_id = mesh.add_vertex((tx, ty, tz), axis)
    # Base cap center.
    cap_id = mesh.add_vertex(base_center, (-axis[0], -axis[1], -axis[2]))

    # Side faces (base ring -> tip).
    for k in range(segments):
        a = base_ids[k]
        b = base_ids[(k + 1) % segments]
        mesh.add_face(a, b, tip_id)

    # Base cap (fan around cap center, wound the other way).
    for k in range(segments):
        a = base_ids[k]
        b = base_ids[(k + 1) % segments]
        mesh.add_face(cap_id, b, a)


# ---------------------------------------------------------------------------
# Bunny assembly
# ---------------------------------------------------------------------------


def build_bunny() -> Mesh:
    """Assemble the three-part bunny mesh and return it."""
    mesh = Mesh(verts=[], normals=[], faces=[])

    # Body: pear-shaped sphere.  12x9 puts us at ~150 verts on the body,
    # leaving room for the head + ears to bring the total near ~250 verts
    # / ~500 tris.  Non-uniform scale (1.0, 1.2, 1.4) per the task spec.
    _uv_sphere(
        mesh,
        slices=14,
        stacks=10,
        center=(0.0, 0.0, 0.0),
        scale=(1.0, 1.2, 1.4),
    )

    # Head: smaller sphere offset +y.
    _uv_sphere(
        mesh,
        slices=10,
        stacks=8,
        center=(0.0, 1.5, 0.4),
        scale=(0.6, 0.6, 0.6),
    )

    # Ears: two elongated cones angled outward from the crown of the head.
    ear_len = 0.7
    ear_r = 0.12
    ear_base_y = 1.9
    ear_base_z = 0.4
    _cone(
        mesh,
        radius=ear_r,
        length=ear_len,
        segments=12,
        base_center=(-0.15, ear_base_y, ear_base_z),
        tip_offset=(-0.25, 0.9, 0.0),
    )
    _cone(
        mesh,
        radius=ear_r,
        length=ear_len,
        segments=12,
        base_center=(0.15, ear_base_y, ear_base_z),
        tip_offset=(0.25, 0.9, 0.0),
    )

    return mesh


# ---------------------------------------------------------------------------
# OBJ / MTL emission
# ---------------------------------------------------------------------------


_MTL_TEXT = """# bunny_low.mtl — a warm cream-fur material for the low-poly bunny.
newmtl bunny_fur
Ka 0.20 0.18 0.16
Kd 0.85 0.78 0.65
Ks 0.10 0.10 0.10
Ns 32.0
d  1.0
illum 2
"""


def _write_obj(mesh: Mesh, path: Path) -> None:
    lines: List[str] = []
    lines.append("# bunny_low.obj — procedurally generated low-poly bunny.")
    lines.append("# Emitted by PharosEngineExamples/examples/assets/_generate_bunny.py.")
    lines.append("mtllib bunny_low.mtl")
    lines.append("o bunny_low")
    lines.append("usemtl bunny_fur")
    lines.append(f"# vertex count: {len(mesh.verts)}")
    lines.append(f"# triangle count: {len(mesh.faces)}")

    for v in mesh.verts:
        lines.append(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
    for n in mesh.normals:
        lines.append(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}")
    # No UVs — the demo material is untextured.  Emit face with v//n form.
    for a, b, c in mesh.faces:
        lines.append(f"f {a}//{a} {b}//{b} {c}//{c}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_mtl(path: Path) -> None:
    path.write_text(_MTL_TEXT, encoding="utf-8")


def emit_assets(target_dir: Path | None = None) -> tuple[Path, Path, Mesh]:
    """Build the bunny and write ``bunny_low.obj`` + ``bunny_low.mtl``.

    Returns
    -------
    (obj_path, mtl_path, mesh)
        Paths of the two files that were written and the in-memory
        :class:`Mesh` in case callers want counts / validation.
    """
    if target_dir is None:
        target_dir = Path(__file__).resolve().parent
    target_dir.mkdir(parents=True, exist_ok=True)
    obj_path = target_dir / "bunny_low.obj"
    mtl_path = target_dir / "bunny_low.mtl"

    mesh = build_bunny()
    _write_obj(mesh, obj_path)
    _write_mtl(mtl_path)
    return obj_path, mtl_path, mesh


if __name__ == "__main__":
    obj_path, mtl_path, mesh = emit_assets()
    print(f"wrote {obj_path}  ({len(mesh.verts)} verts, {len(mesh.faces)} tris)")
    print(f"wrote {mtl_path}")
