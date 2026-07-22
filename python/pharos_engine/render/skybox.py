"""Skybox rendering — cubemap-backed environment sphere (KK4).

Sprint 11 of the Nova3D parity plan. The skybox draws once per frame as
a full-screen cube whose vertices are pushed to the far plane (``z = 1``
in NDC). It samples a cubemap keyed by the fragment's world-space
direction, so it renders behind every other geometry and moves with the
camera (translation stripped from the view matrix).

Public surface
--------------
* :class:`CubeFace`             — enum of the six cube faces.
* :class:`CubemapData`          — CPU-side cubemap (six HxWx4 uint8 faces).
* :class:`Skybox`               — bindable skybox pass.
* :data:`SKYBOX_WGSL`           — vertex + fragment WGSL source.
* :func:`sample_direction_from_cubemap` — CPU-side sampler for tests /
  numpy fallback path.
* :func:`procedural_gradient_sky` — build a gradient cubemap at runtime
  (no texture files required).

Cube-face conventions
---------------------
We follow the standard cubemap convention (Direct3D / glTF / most
engines):

===========  ==========  ===============  ====================
 CubeFace     axis        u across         v down
===========  ==========  ===============  ====================
 POSX         +X          -Z               -Y
 NEGX         -X          +Z               -Y
 POSY         +Y          +X               +Z
 NEGY         -Y          +X               -Z
 POSZ         +Z          +X               -Y
 NEGZ         -Z          -X               -Y
===========  ==========  ===============  ====================

For sampling, we pick the face whose axis has the largest absolute
component in the incoming direction, then divide the other two
components by that axis to get UV in [0, 1].
"""
from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

_LOG = logging.getLogger(__name__)
_SKYBOX_SUBMIT_WARNED: set[int] = set()


# ----------------------------------------------------------------------
# Face enum
# ----------------------------------------------------------------------
class CubeFace(enum.IntEnum):
    """Six faces of a cubemap, in the standard GPU order."""

    POSX = 0  # +X
    NEGX = 1  # -X
    POSY = 2  # +Y
    NEGY = 3  # -Y
    POSZ = 4  # +Z
    NEGZ = 5  # -Z


ALL_FACES: tuple[CubeFace, ...] = (
    CubeFace.POSX,
    CubeFace.NEGX,
    CubeFace.POSY,
    CubeFace.NEGY,
    CubeFace.POSZ,
    CubeFace.NEGZ,
)


# ----------------------------------------------------------------------
# CubemapData
# ----------------------------------------------------------------------
def _blank_face(resolution: int) -> np.ndarray:
    return np.zeros((resolution, resolution, 4), dtype=np.uint8)


def _default_faces() -> dict[CubeFace, np.ndarray]:
    return {face: _blank_face(1) for face in ALL_FACES}


@dataclass
class CubemapData:
    """Six-face cubemap texture, one HxWx4 uint8 array per face.

    Attributes
    ----------
    faces
        Mapping from :class:`CubeFace` to a ``(H, W, 4)`` ``uint8`` array.
        All six entries must be present; each array must be square with
        side ``resolution``.
    resolution
        Side length of each face in pixels. Power-of-two is preferred
        so downstream mip generation works; not enforced here.
    format
        Pixel format tag — always ``"rgba8"`` for now.
    """

    faces: dict[CubeFace, np.ndarray] = field(default_factory=_default_faces)
    resolution: int = 1
    format: str = "rgba8"

    def __post_init__(self) -> None:
        # Normalise: allow callers to pass a subset; fill missing faces
        # with a black square of the declared resolution. When callers
        # only pass a resolution (no faces), auto-scale the placeholders
        # from the default 1x1 to the declared size.
        res = int(self.resolution)
        if res <= 0:
            raise ValueError(f"CubemapData resolution must be positive, got {res}")
        self.resolution = res
        for face in ALL_FACES:
            if face not in self.faces:
                self.faces[face] = _blank_face(res)
                continue
            arr = np.asarray(self.faces[face])
            if arr.ndim != 3 or arr.shape[2] != 4:
                raise ValueError(
                    f"CubemapData face {face.name} must be HxWx4, got shape {arr.shape}"
                )
            if arr.shape[0] != arr.shape[1]:
                raise ValueError(
                    f"CubemapData face {face.name} must be square, got {arr.shape[:2]}"
                )
            if arr.shape[0] != res:
                # Auto-resize blank placeholders (all-zero 1x1) so callers
                # can construct a cubemap by resolution alone.
                if arr.shape == (1, 1, 4) and not arr.any():
                    self.faces[face] = _blank_face(res)
                    continue
                raise ValueError(
                    f"CubemapData face {face.name} shape {arr.shape[:2]} "
                    f"doesn't match resolution {res}"
                )
            if arr.dtype != np.uint8:
                arr = arr.astype(np.uint8)
            self.faces[face] = arr
        if self.format != "rgba8":
            raise ValueError(f"CubemapData only supports 'rgba8', got {self.format!r}")

    @property
    def is_power_of_two(self) -> bool:
        r = self.resolution
        return r > 0 and (r & (r - 1)) == 0

    def face(self, face: CubeFace) -> np.ndarray:
        return self.faces[CubeFace(face)]


# ----------------------------------------------------------------------
# WGSL — vertex+fragment for the skybox pass
# ----------------------------------------------------------------------
SKYBOX_WGSL = """// pharos_engine skybox
struct SkyCam { vt: mat4x4<f32>, p: mat4x4<f32> };
@group(0) @binding(0) var<uniform> cam: SkyCam;
@group(1) @binding(0) var st: texture_cube<f32>;
@group(1) @binding(1) var ss: sampler;
struct VIn  { @location(0) position: vec3<f32> };
struct VOut { @builtin(position) clip: vec4<f32>, @location(0) dir: vec3<f32> };
@vertex
fn vs_main(i: VIn) -> VOut {
    var o: VOut;
    o.dir = i.position;
    var c = cam.p * cam.vt * vec4<f32>(i.position, 1.0);
    c.z = c.w;
    o.clip = c;
    return o;
}
@fragment
fn fs_main(i: VOut) -> @location(0) vec4<f32> {
    return textureSample(st, ss, normalize(i.dir));
}
"""


# ----------------------------------------------------------------------
# CPU-side direction → cubemap sample
# ----------------------------------------------------------------------
def _face_and_uv(direction: tuple[float, float, float]) -> tuple[CubeFace, float, float]:
    """Return (face, u, v) for a direction vector using standard convention.

    UVs are in [0, 1] with (0, 0) = top-left of the face image.
    """
    x, y, z = float(direction[0]), float(direction[1]), float(direction[2])
    ax, ay, az = abs(x), abs(y), abs(z)
    # Pick major axis.
    if ax >= ay and ax >= az:
        if ax < 1e-20:
            return CubeFace.POSX, 0.5, 0.5
        if x > 0.0:
            # +X face: u = -z/ax, v = -y/ax
            u = 0.5 * (-z / ax + 1.0)
            v = 0.5 * (-y / ax + 1.0)
            return CubeFace.POSX, u, v
        else:
            # -X face: u = +z/ax, v = -y/ax
            u = 0.5 * (z / ax + 1.0)
            v = 0.5 * (-y / ax + 1.0)
            return CubeFace.NEGX, u, v
    elif ay >= ax and ay >= az:
        if ay < 1e-20:
            return CubeFace.POSY, 0.5, 0.5
        if y > 0.0:
            # +Y face: u = +x/ay, v = +z/ay
            u = 0.5 * (x / ay + 1.0)
            v = 0.5 * (z / ay + 1.0)
            return CubeFace.POSY, u, v
        else:
            # -Y face: u = +x/ay, v = -z/ay
            u = 0.5 * (x / ay + 1.0)
            v = 0.5 * (-z / ay + 1.0)
            return CubeFace.NEGY, u, v
    else:
        if az < 1e-20:
            return CubeFace.POSZ, 0.5, 0.5
        if z > 0.0:
            # +Z face: u = +x/az, v = -y/az
            u = 0.5 * (x / az + 1.0)
            v = 0.5 * (-y / az + 1.0)
            return CubeFace.POSZ, u, v
        else:
            # -Z face: u = -x/az, v = -y/az
            u = 0.5 * (-x / az + 1.0)
            v = 0.5 * (-y / az + 1.0)
            return CubeFace.NEGZ, u, v


def sample_direction_from_cubemap(
    direction: tuple[float, float, float],
    cubemap: CubemapData,
) -> tuple[float, float, float, float]:
    """CPU-side nearest-texel sample of ``cubemap`` along ``direction``.

    Returns an RGBA tuple with components in ``[0, 1]``.
    """
    face, u, v = _face_and_uv(direction)
    img = cubemap.face(face)
    h, w, _ = img.shape
    ix = min(max(int(u * w), 0), w - 1)
    iy = min(max(int(v * h), 0), h - 1)
    px = img[iy, ix]
    return (
        float(px[0]) / 255.0,
        float(px[1]) / 255.0,
        float(px[2]) / 255.0,
        float(px[3]) / 255.0,
    )


# ----------------------------------------------------------------------
# Procedural gradient sky (top / horizon / ground)
# ----------------------------------------------------------------------
def _lerp3(a: tuple[float, float, float],
           b: tuple[float, float, float],
           t: float) -> tuple[float, float, float]:
    t = max(0.0, min(1.0, t))
    return (a[0] + (b[0] - a[0]) * t,
            a[1] + (b[1] - a[1]) * t,
            a[2] + (b[2] - a[2]) * t)


def _rgb_to_u8(rgb: tuple[float, float, float]) -> tuple[int, int, int]:
    return (
        int(round(max(0.0, min(1.0, rgb[0])) * 255)),
        int(round(max(0.0, min(1.0, rgb[1])) * 255)),
        int(round(max(0.0, min(1.0, rgb[2])) * 255)),
    )


def procedural_gradient_sky(
    top_color: tuple[float, float, float] = (0.35, 0.55, 0.90),
    horizon_color: tuple[float, float, float] = (0.85, 0.90, 0.98),
    ground_color: tuple[float, float, float] = (0.18, 0.15, 0.12),
    resolution: int = 256,
) -> CubemapData:
    """Build a three-stop gradient skybox — no texture files required.

    The gradient is computed per fragment as a function of the world-space
    Y component of the direction vector. y=+1 → ``top_color``, y=0 →
    ``horizon_color``, y=-1 → ``ground_color``. All faces are generated
    consistently by inverting the cubemap sampling equations, so a
    subsequent :func:`sample_direction_from_cubemap` call will read back
    the expected gradient.
    """
    if resolution <= 0:
        raise ValueError(f"resolution must be positive, got {resolution}")
    r = int(resolution)
    # Grid of UVs in [-1, 1] with (0, 0) at face centre.
    xs = (np.arange(r, dtype=np.float32) + 0.5) / r * 2.0 - 1.0
    ys = (np.arange(r, dtype=np.float32) + 0.5) / r * 2.0 - 1.0
    u_grid, v_grid = np.meshgrid(xs, ys)  # each (r, r)

    faces: dict[CubeFace, np.ndarray] = {}

    # Build per-face direction fields matching the sampling convention.
    #   POSX: dir = ( +1, -v, -u )
    #   NEGX: dir = ( -1, -v, +u )
    #   POSY: dir = ( +u, +1, +v )
    #   NEGY: dir = ( +u, -1, -v )
    #   POSZ: dir = ( +u, -v, +1 )
    #   NEGZ: dir = ( -u, -v, -1 )
    one = np.ones_like(u_grid)
    dir_by_face = {
        CubeFace.POSX: np.stack([+one, -v_grid, -u_grid], axis=-1),
        CubeFace.NEGX: np.stack([-one, -v_grid, +u_grid], axis=-1),
        CubeFace.POSY: np.stack([+u_grid, +one, +v_grid], axis=-1),
        CubeFace.NEGY: np.stack([+u_grid, -one, -v_grid], axis=-1),
        CubeFace.POSZ: np.stack([+u_grid, -v_grid, +one], axis=-1),
        CubeFace.NEGZ: np.stack([-u_grid, -v_grid, -one], axis=-1),
    }

    top = np.asarray(top_color, dtype=np.float32)
    hor = np.asarray(horizon_color, dtype=np.float32)
    gnd = np.asarray(ground_color, dtype=np.float32)

    for face, d in dir_by_face.items():
        n = d / np.maximum(np.linalg.norm(d, axis=-1, keepdims=True), 1e-8)
        y = n[..., 1]
        # Above horizon: lerp horizon -> top by y.
        # Below horizon: lerp horizon -> ground by |y|.
        above = np.clip(y, 0.0, 1.0)[..., None]
        below = np.clip(-y, 0.0, 1.0)[..., None]
        rgb = hor + (top - hor) * above + (gnd - hor) * below
        rgb_u8 = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
        rgba = np.concatenate([rgb_u8, np.full((r, r, 1), 255, dtype=np.uint8)], axis=-1)
        faces[face] = rgba

    return CubemapData(faces=faces, resolution=r, format="rgba8")


# ----------------------------------------------------------------------
# Skybox class — bindable pass
# ----------------------------------------------------------------------
def _unit_cube_vertices() -> np.ndarray:
    """36 vertex positions (12 tris) for a unit cube around origin."""
    # Cube corners.
    p = np.array([
        [-1.0, -1.0, -1.0],
        [+1.0, -1.0, -1.0],
        [+1.0, +1.0, -1.0],
        [-1.0, +1.0, -1.0],
        [-1.0, -1.0, +1.0],
        [+1.0, -1.0, +1.0],
        [+1.0, +1.0, +1.0],
        [-1.0, +1.0, +1.0],
    ], dtype=np.float32)
    # Face triangles (CCW from inside — we render the inside of the cube).
    faces_idx = [
        (0, 2, 1), (0, 3, 2),  # -Z
        (4, 5, 6), (4, 6, 7),  # +Z
        (0, 5, 4), (0, 1, 5),  # -Y
        (3, 6, 2), (3, 7, 6),  # +Y  (fixed: was mis-ordered)
        (0, 4, 7), (0, 7, 3),  # -X
        (1, 2, 6), (1, 6, 5),  # +X
    ]
    tris = np.array(faces_idx, dtype=np.int32)
    return p[tris.reshape(-1)]


@dataclass
class Skybox:
    """A skybox pass — geometry + cubemap + shader."""

    cubemap: CubemapData
    camera: Optional[object] = None  # Camera3D; kept Optional for tests
    depth_write: bool = False
    depth_test: str = "less_equal"

    SKYBOX_WGSL: str = SKYBOX_WGSL

    def __post_init__(self) -> None:
        self._vertices = _unit_cube_vertices()

    # ------------------------------------------------------------------
    # Introspection helpers used by tests / editor UI
    # ------------------------------------------------------------------
    @property
    def vertices(self) -> np.ndarray:
        return self._vertices

    @property
    def triangle_count(self) -> int:
        return int(self._vertices.shape[0] // 3)

    def view_matrix_no_translation(self, camera=None) -> np.ndarray:
        """Return the camera's view matrix with translation stripped.

        This is what the skybox binds so the cube stays centred on the
        camera and only the direction (rotation) matters when sampling
        the cubemap.
        """
        cam = camera or self.camera
        if cam is None:
            return np.eye(4, dtype=np.float32)
        v = np.asarray(cam.view_matrix(), dtype=np.float32).copy()
        v[0, 3] = 0.0
        v[1, 3] = 0.0
        v[2, 3] = 0.0
        return v

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------
    def render(self, renderer, camera=None) -> None:
        """Submit the skybox as a draw call to ``renderer``.

        Uses the renderer's generic ``submit_lines`` / ``submit_mesh`` API
        for the null path (recorded in :attr:`NullRenderer.draw_log` as a
        ``"skybox"`` entry) so tests can assert the pass happened without
        needing a real cubemap binding.

        Raises
        ------
        TypeError
            If *renderer* is ``None``.
        """
        if renderer is None:
            raise TypeError("Skybox.render: renderer must not be None")
        cam = camera or self.camera
        view_no_trans = self.view_matrix_no_translation(cam)

        # NullRenderer: append a synthetic draw call. For a real GPU
        # renderer, this method would be overridden or intercepted by
        # the pipeline; the base class just records the intent.
        log = getattr(renderer, "draw_log", None)
        if log is not None:
            from .null_renderer import DrawCall
            log.append(
                DrawCall(
                    "skybox",
                    {
                        "triangle_count": self.triangle_count,
                        "resolution": self.cubemap.resolution,
                        "view_no_trans": view_no_trans.copy(),
                        "format": self.cubemap.format,
                        "depth_write": self.depth_write,
                        "depth_test": self.depth_test,
                    },
                )
            )
            return

        # Real renderer path — try a couple of hooks in preference order.
        for method_name in ("submit_skybox", "draw_skybox"):
            fn = getattr(renderer, method_name, None)
            if callable(fn):
                fn(self.cubemap, view_no_trans)
                return

        # Last-ditch fallback: renderer doesn't support skyboxes yet.
        # Warn once per renderer instance so the caller can trace missed
        # submissions but the warning doesn't spam the log per-frame.
        r_id = id(renderer)
        if r_id not in _SKYBOX_SUBMIT_WARNED:
            _SKYBOX_SUBMIT_WARNED.add(r_id)
            _LOG.warning(
                "Skybox.render: renderer %s exposes no draw_log / submit_skybox "
                "/ draw_skybox; skipping skybox pass",
                type(renderer).__name__,
            )


__all__ = [
    "ALL_FACES",
    "CubeFace",
    "CubemapData",
    "SKYBOX_WGSL",
    "Skybox",
    "procedural_gradient_sky",
    "sample_direction_from_cubemap",
]
