"""``type_router`` — CCC3: file-extension → importer dispatch for the editor.

The existing :class:`AssetImportDispatcher` covers meshes, textures and
material libraries but the editor drop panel needs a wider net that also
routes:

* ``.hdr`` / ``.exr``          → texture (HDR)
* ``.ktx2``                    → cubemap (or fallback to texture)
* ``.wgsl``                    → shader source handle
* ``.yaml`` / ``.yml``         → material / prefab / scene by top-level keys
* ``.py``                      → script module descriptor

… plus a *never-raise* fallback so a mixed drop of 10 files can partly
succeed instead of taking the whole batch down.

This module deliberately does not reimplement any importer — every
supported extension is delegated to an existing helper in the
:mod:`pharos_engine.asset_import` package (or a small in-module handler
for the new formats).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .import_result import ImportResult, TextureData

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public result type — a lightweight envelope returned by
# :func:`import_by_extension`. Keeps the panel decoupled from the
# specific handle types (TextureData / GpuMesh / ImportResult / …).
# ---------------------------------------------------------------------------


@dataclass
class ImportRouteResult:
    """Uniform envelope returned by :func:`import_by_extension`.

    Attributes
    ----------
    kind:
        One of ``"texture"``, ``"hdr_texture"``, ``"cubemap"``,
        ``"shader"``, ``"mesh"``, ``"scene"``, ``"material"``,
        ``"material_library"``, ``"prefab"``, ``"script"``,
        ``"unsupported"``, ``"error"``.
    handle:
        The importer-specific handle. For textures a
        :class:`TextureData`; for meshes/scenes an
        :class:`ImportResult`; for shaders a :class:`ShaderHandle`; for
        YAML the parsed dict; for scripts a :class:`ScriptHandle`.
    path:
        The source file path (as :class:`pathlib.Path`).
    thumbnail:
        Optional ``(128, 128, 4)`` uint8 ndarray. May be ``None`` when
        the route couldn't produce a preview (e.g. unsupported /
        errored imports).
    error:
        Empty string on success. Non-empty when the router captured an
        exception (kind is ``"error"``) or the extension is unknown
        (kind is ``"unsupported"``).
    """

    kind: str
    handle: Any
    path: Path
    thumbnail: np.ndarray | None = None
    error: str = ""


# ---------------------------------------------------------------------------
# Lightweight handle wrappers for shaders + scripts. They intentionally
# stay dataclass-shaped so the panel can display metadata without
# poking at the importer internals.
# ---------------------------------------------------------------------------


@dataclass
class ShaderHandle:
    """A loaded shader source (WGSL by default)."""

    path: Path
    source: str
    stage: str = "wgsl"
    entry_points: list[str] = field(default_factory=list)


@dataclass
class ScriptHandle:
    """A referenced Python script — kept as a path + source snapshot."""

    path: Path
    source: str
    module_name: str = ""


# ---------------------------------------------------------------------------
# Thumbnail helpers — pure numpy so tests never require wgpu / PIL.
# ---------------------------------------------------------------------------


THUMBNAIL_SIZE: int = 128


def _blank_thumbnail(fill: tuple[int, int, int, int] = (250, 246, 235, 255)) -> np.ndarray:
    """Return a paper-cream ``(128, 128, 4)`` uint8 canvas."""
    thumb = np.zeros((THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4), dtype=np.uint8)
    thumb[..., 0] = fill[0]
    thumb[..., 1] = fill[1]
    thumb[..., 2] = fill[2]
    thumb[..., 3] = fill[3]
    return thumb


def _downsample_to_thumbnail(pixels: np.ndarray) -> np.ndarray:
    """Downsample ``pixels`` (H, W, C) to a 128x128 RGBA uint8 thumbnail.

    Uses nearest-neighbour indexing (fast; independent of PIL). Alpha
    channel is preserved when present; otherwise filled with 255.
    """
    if pixels.ndim == 2:
        pixels = pixels[..., None]
    h, w = pixels.shape[:2]
    if h == 0 or w == 0:
        return _blank_thumbnail((30, 30, 30, 255))

    ys = np.linspace(0, h - 1, THUMBNAIL_SIZE).astype(np.int64)
    xs = np.linspace(0, w - 1, THUMBNAIL_SIZE).astype(np.int64)
    sampled = pixels[ys[:, None], xs[None, :]]

    thumb = np.zeros((THUMBNAIL_SIZE, THUMBNAIL_SIZE, 4), dtype=np.uint8)
    if sampled.dtype != np.uint8:
        # HDR / float — normalise into 8-bit for the preview only.
        f = sampled.astype(np.float32)
        m = float(f.max()) if f.size else 1.0
        if m <= 0.0:
            m = 1.0
        f = np.clip(f / m * 255.0, 0, 255).astype(np.uint8)
        sampled = f

    ch = sampled.shape[-1]
    if ch == 1:
        thumb[..., 0] = sampled[..., 0]
        thumb[..., 1] = sampled[..., 0]
        thumb[..., 2] = sampled[..., 0]
        thumb[..., 3] = 255
    elif ch == 3:
        thumb[..., :3] = sampled
        thumb[..., 3] = 255
    else:
        thumb[...] = sampled[..., :4]
    return thumb


def texture_thumbnail(tex: TextureData | np.ndarray) -> np.ndarray:
    """Build a 128x128 RGBA thumbnail from a texture or ndarray."""
    if isinstance(tex, TextureData):
        return _downsample_to_thumbnail(tex.pixels)
    if isinstance(tex, np.ndarray):
        return _downsample_to_thumbnail(tex)
    return _blank_thumbnail()


def mesh_thumbnail(mesh_result: ImportResult) -> np.ndarray:
    """Render a 128x128 orthographic wireframe of the mesh bounding box.

    Uses vectorised numpy line rasterisation — no wgpu required. The
    bounding box is derived from the *first* mesh's ``positions`` /
    ``vertices`` attribute if available; otherwise a placeholder box is
    drawn so the panel still renders a distinguishable card.
    """
    thumb = _blank_thumbnail((248, 243, 226, 255))
    mesh = mesh_result.primary_mesh if isinstance(mesh_result, ImportResult) else None

    # Try to pull vertex positions from whatever primary_mesh happens
    # to be. GpuMesh instances expose ``vertices`` (Nx3+); the dict
    # fallback stores them under ``vertices``.
    positions: np.ndarray | None = None
    if mesh is not None:
        for attr in ("positions", "vertices"):
            v = getattr(mesh, attr, None)
            if v is None and isinstance(mesh, dict):
                v = mesh.get(attr)
            if v is not None:
                try:
                    a = np.asarray(v, dtype=np.float32)
                    if a.ndim >= 2 and a.shape[-1] >= 3:
                        positions = a.reshape(-1, a.shape[-1])[:, :3]
                        break
                except Exception:  # noqa: BLE001
                    pass

    if positions is None or positions.size == 0:
        # Unit cube placeholder so the thumbnail still shows a box.
        positions = np.array(
            [[-1, -1, -1], [1, 1, 1]], dtype=np.float32,
        )

    lo = positions.min(axis=0)
    hi = positions.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    # Orthographic XY projection with 8-pixel margin.
    margin = 8
    span_xy = np.array([span[0], span[1]], dtype=np.float32)
    scale = (THUMBNAIL_SIZE - 2 * margin) / max(float(span_xy[0]), float(span_xy[1]))
    cx = (lo[0] + hi[0]) * 0.5
    cy = (lo[1] + hi[1]) * 0.5

    def _proj(x: float, y: float) -> tuple[int, int]:
        px = int(round(THUMBNAIL_SIZE * 0.5 + (x - cx) * scale))
        py = int(round(THUMBNAIL_SIZE * 0.5 - (y - cy) * scale))
        return px, py

    # 8 bounding-box corners → 12 edges.
    corners = np.array(
        [
            [lo[0], lo[1], lo[2]],
            [hi[0], lo[1], lo[2]],
            [hi[0], hi[1], lo[2]],
            [lo[0], hi[1], lo[2]],
            [lo[0], lo[1], hi[2]],
            [hi[0], lo[1], hi[2]],
            [hi[0], hi[1], hi[2]],
            [lo[0], hi[1], hi[2]],
        ],
        dtype=np.float32,
    )
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),  # bottom face
        (4, 5), (5, 6), (6, 7), (7, 4),  # top face
        (0, 4), (1, 5), (2, 6), (3, 7),  # verticals
    ]
    ink = np.array([70, 55, 30, 255], dtype=np.uint8)
    for a, b in edges:
        p0 = _proj(float(corners[a, 0]), float(corners[a, 1]))
        p1 = _proj(float(corners[b, 0]), float(corners[b, 1]))
        _raster_line(thumb, p0, p1, ink)
    return thumb


def _raster_line(
    img: np.ndarray,
    p0: tuple[int, int],
    p1: tuple[int, int],
    color: np.ndarray,
) -> None:
    """Vectorised Bresenham-ish line into an RGBA canvas."""
    x0, y0 = p0
    x1, y1 = p1
    n = max(abs(x1 - x0), abs(y1 - y0)) + 1
    xs = np.linspace(x0, x1, n).astype(np.int64)
    ys = np.linspace(y0, y1, n).astype(np.int64)
    mask = (xs >= 0) & (xs < img.shape[1]) & (ys >= 0) & (ys < img.shape[0])
    img[ys[mask], xs[mask]] = color


def shader_thumbnail(text: str = "WGSL") -> np.ndarray:
    """Render a code-page thumbnail: cream background + label + code lines."""
    thumb = _blank_thumbnail((235, 228, 208, 255))
    # Vertical rule to suggest a code editor gutter.
    thumb[:, 12:14, :3] = (140, 110, 60)
    # A stack of faint horizontal lines to suggest code.
    line_color = np.array([120, 100, 60, 255], dtype=np.uint8)
    rng = np.random.RandomState(seed=len(text) if text else 0)
    for i, y in enumerate(range(16, THUMBNAIL_SIZE - 12, 10)):
        length = 60 + int(rng.randint(0, 40))
        thumb[y : y + 2, 20 : 20 + length] = line_color
    # A dark badge in the corner labels this as a shader.
    thumb[6:22, 22:98, :3] = (60, 40, 20)
    thumb[6:22, 22:98, 3] = 255
    return thumb


def material_thumbnail(color: tuple[float, float, float] | None) -> np.ndarray:
    """Render a solid-colour swatch thumbnail for a material."""
    if color is None:
        rgb = (196, 176, 138)
    else:
        rgb = tuple(int(np.clip(c * 255.0 if c <= 1.0 else c, 0, 255)) for c in color[:3])
    thumb = _blank_thumbnail((rgb[0], rgb[1], rgb[2], 255))
    # Draw a thin border so the swatch reads as a card.
    thumb[0:2, :, :3] = (30, 20, 10)
    thumb[-2:, :, :3] = (30, 20, 10)
    thumb[:, 0:2, :3] = (30, 20, 10)
    thumb[:, -2:, :3] = (30, 20, 10)
    return thumb


def generic_thumbnail(label: str = "?") -> np.ndarray:
    """Placeholder thumbnail for unsupported / errored routes."""
    thumb = _blank_thumbnail((200, 195, 180, 255))
    thumb[4:12, :, :3] = (140, 60, 60)
    thumb[-12:-4, :, :3] = (140, 60, 60)
    return thumb


# ---------------------------------------------------------------------------
# Extension routing table
# ---------------------------------------------------------------------------


TEXTURE_EXTS: frozenset[str] = frozenset(
    {".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp"}
)
HDR_EXTS: frozenset[str] = frozenset({".hdr", ".exr"})
CUBEMAP_EXTS: frozenset[str] = frozenset({".ktx2"})
SHADER_EXTS: frozenset[str] = frozenset({".wgsl"})
MESH_OBJ_EXTS: frozenset[str] = frozenset({".obj"})
MESH_GLTF_EXTS: frozenset[str] = frozenset({".gltf", ".glb"})
MATERIAL_MTL_EXTS: frozenset[str] = frozenset({".mtl"})
YAML_EXTS: frozenset[str] = frozenset({".yaml", ".yml"})
SCRIPT_EXTS: frozenset[str] = frozenset({".py"})

SUPPORTED_EXTS: frozenset[str] = (
    TEXTURE_EXTS
    | HDR_EXTS
    | CUBEMAP_EXTS
    | SHADER_EXTS
    | MESH_OBJ_EXTS
    | MESH_GLTF_EXTS
    | MATERIAL_MTL_EXTS
    | YAML_EXTS
    | SCRIPT_EXTS
)


# ---------------------------------------------------------------------------
# Per-kind route handlers.
# ---------------------------------------------------------------------------


def _route_texture(path: Path) -> ImportRouteResult:
    from .texture_importer import import_texture

    res = import_texture(path)
    tex = res.primary_texture
    thumb = texture_thumbnail(tex) if tex is not None else generic_thumbnail()
    return ImportRouteResult(kind="texture", handle=tex, path=path, thumbnail=thumb)


def _route_hdr_texture(path: Path) -> ImportRouteResult:
    """HDR / EXR — soft-import via imageio, fall back to a placeholder.

    We never raise here; a missing imageio just falls through to a
    generic thumbnail so the editor doesn't die on hostile drops.
    """
    pixels: np.ndarray | None = None
    try:  # pragma: no cover - imageio is an optional dep
        import imageio.v3 as iio  # noqa: PLC0415

        pixels = np.asarray(iio.imread(str(path)))
    except Exception as exc:  # noqa: BLE001
        _LOG.info("HDR import fell back to placeholder for %s: %s", path.name, exc)
    if pixels is None:
        thumb = generic_thumbnail()
        tex = None
    else:
        # Normalise into a TextureData wrapper so downstream can display it.
        if pixels.ndim == 2:
            channels = 1
            fmt = "grayscale"
        elif pixels.shape[-1] == 4:
            channels = 4
            fmt = "RGBA"
        else:
            channels = 3
            fmt = "RGB"
        tex = TextureData(
            pixels=pixels,
            width=int(pixels.shape[1]),
            height=int(pixels.shape[0]),
            channels=channels,
            format=fmt,
        )
        thumb = _downsample_to_thumbnail(pixels)
    return ImportRouteResult(kind="hdr_texture", handle=tex, path=path, thumbnail=thumb)


def _route_cubemap(path: Path) -> ImportRouteResult:
    """``.ktx2`` — attempt cubemap import; fall back to placeholder."""
    handle: Any = None
    try:  # pragma: no cover - depends on optional readers
        from .cubemap_importer import import_cubemap  # noqa: PLC0415

        handle = import_cubemap(path)
    except Exception as exc:  # noqa: BLE001
        _LOG.info("Cubemap import fell back to placeholder for %s: %s", path.name, exc)
    thumb = generic_thumbnail()
    return ImportRouteResult(
        kind="cubemap" if handle is not None else "cubemap",
        handle=handle,
        path=path,
        thumbnail=thumb,
    )


def _route_shader(path: Path) -> ImportRouteResult:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ImportRouteResult(
            kind="error", handle=None, path=path,
            thumbnail=generic_thumbnail(), error=str(exc),
        )
    # Scan for @vertex / @fragment / @compute entry points so the panel
    # can hint at what the shader provides.
    entry_points: list[str] = []
    for tok in ("@vertex", "@fragment", "@compute"):
        if tok in source:
            entry_points.append(tok[1:])
    handle = ShaderHandle(path=path, source=source, entry_points=entry_points)
    return ImportRouteResult(
        kind="shader", handle=handle, path=path,
        thumbnail=shader_thumbnail("WGSL"),
    )


def _route_obj(path: Path) -> ImportRouteResult:
    from .obj_importer import import_obj

    res = import_obj(path)
    thumb = mesh_thumbnail(res)
    return ImportRouteResult(kind="mesh", handle=res, path=path, thumbnail=thumb)


def _route_gltf(path: Path) -> ImportRouteResult:
    from .gltf_importer import import_gltf

    res = import_gltf(path)
    thumb = mesh_thumbnail(res)
    return ImportRouteResult(kind="scene", handle=res, path=path, thumbnail=thumb)


def _route_mtl(path: Path) -> ImportRouteResult:
    from .mtl_resolver import mtl_to_material, parse_mtl

    defs = parse_mtl(path)
    materials = {name: mtl_to_material(d) for name, d in defs.items()}
    # Pull first diffuse for the swatch.
    diffuse: tuple[float, float, float] | None = None
    for m in materials.values():
        base = m.get("baseColor") if isinstance(m, dict) else None
        if base is not None:
            diffuse = (float(base[0]), float(base[1]), float(base[2]))
            break
    thumb = material_thumbnail(diffuse)
    return ImportRouteResult(
        kind="material_library", handle=materials, path=path, thumbnail=thumb,
    )


def _route_yaml(path: Path) -> ImportRouteResult:
    """Classify a YAML file by its top-level keys.

    Recognised shapes:
      * ``kind: material`` / ``baseColor: [...]`` → material
      * ``prefab:`` / ``entities:`` at top-level → prefab / scene
      * anything else → generic YAML dict
    """
    import yaml

    try:
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        return ImportRouteResult(
            kind="error", handle=None, path=path,
            thumbnail=generic_thumbnail(), error=str(exc),
        )
    kind = "yaml"
    if isinstance(data, dict):
        top = {str(k).lower() for k in data.keys()}
        if data.get("kind") == "material" or "basecolor" in top or "material" in top:
            kind = "material"
        elif "prefab" in top or path.name.endswith(".prefab.yaml"):
            kind = "prefab"
        elif "entities" in top or "scene" in top or path.name.endswith(".scene.yaml"):
            kind = "scene"
    diffuse = None
    if isinstance(data, dict):
        base = data.get("baseColor") or data.get("basecolor") or data.get("diffuse")
        if isinstance(base, (list, tuple)) and len(base) >= 3:
            diffuse = (float(base[0]), float(base[1]), float(base[2]))
    thumb = material_thumbnail(diffuse) if kind == "material" else generic_thumbnail()
    return ImportRouteResult(kind=kind, handle=data, path=path, thumbnail=thumb)


def _route_script(path: Path) -> ImportRouteResult:
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return ImportRouteResult(
            kind="error", handle=None, path=path,
            thumbnail=generic_thumbnail(), error=str(exc),
        )
    handle = ScriptHandle(
        path=path, source=source, module_name=path.stem,
    )
    return ImportRouteResult(
        kind="script", handle=handle, path=path,
        thumbnail=shader_thumbnail("PY"),
    )


# Extension → route callable.
_ROUTES: dict[str, Callable[[Path], ImportRouteResult]] = {}
for _e in TEXTURE_EXTS:
    _ROUTES[_e] = _route_texture
for _e in HDR_EXTS:
    _ROUTES[_e] = _route_hdr_texture
for _e in CUBEMAP_EXTS:
    _ROUTES[_e] = _route_cubemap
for _e in SHADER_EXTS:
    _ROUTES[_e] = _route_shader
for _e in MESH_OBJ_EXTS:
    _ROUTES[_e] = _route_obj
for _e in MESH_GLTF_EXTS:
    _ROUTES[_e] = _route_gltf
for _e in MATERIAL_MTL_EXTS:
    _ROUTES[_e] = _route_mtl
for _e in YAML_EXTS:
    _ROUTES[_e] = _route_yaml
for _e in SCRIPT_EXTS:
    _ROUTES[_e] = _route_script


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def import_by_extension(path: str | Path) -> ImportRouteResult:
    """Dispatch ``path`` to the correct importer based on file extension.

    Returns
    -------
    ImportRouteResult
        A :class:`ImportRouteResult` regardless of success. The
        ``kind`` field is ``"unsupported"`` for unknown extensions and
        ``"error"`` when a routed importer raised.
    """
    p = Path(path)
    ext = p.suffix.lower()
    route = _ROUTES.get(ext)
    if route is None:
        return ImportRouteResult(
            kind="unsupported", handle=None, path=p,
            thumbnail=generic_thumbnail(),
            error=f"unsupported extension {ext!r}",
        )
    try:
        return route(p)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning(
            "import_by_extension: %s importer raised for %s (%s: %s)",
            ext, p.name, type(exc).__name__, exc,
        )
        return ImportRouteResult(
            kind="error", handle=None, path=p,
            thumbnail=generic_thumbnail(),
            error=f"{type(exc).__name__}: {exc}",
        )


def supported_extensions() -> tuple[str, ...]:
    """Return the sorted tuple of extensions the router recognises."""
    return tuple(sorted(SUPPORTED_EXTS))


__all__ = [
    "HDR_EXTS",
    "CUBEMAP_EXTS",
    "ImportRouteResult",
    "MATERIAL_MTL_EXTS",
    "MESH_GLTF_EXTS",
    "MESH_OBJ_EXTS",
    "SCRIPT_EXTS",
    "SHADER_EXTS",
    "SUPPORTED_EXTS",
    "ScriptHandle",
    "ShaderHandle",
    "TEXTURE_EXTS",
    "THUMBNAIL_SIZE",
    "YAML_EXTS",
    "generic_thumbnail",
    "import_by_extension",
    "material_thumbnail",
    "mesh_thumbnail",
    "shader_thumbnail",
    "supported_extensions",
    "texture_thumbnail",
]
