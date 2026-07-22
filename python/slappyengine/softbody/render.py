"""Forward-splat renderer for :class:`SoftBodyWorld`.

Reads node + beam state and produces an (H, W, 4) uint8 RGBA frame that
goes through a small bloom + Reinhard tonemap chain so output looks
consistent with :mod:`slappyengine.physics.render`. All defaults live in
``config/softbody.yml`` under ``render:``; per-material colours live on
:class:`Material` (``render_color``, ``damage_color``).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .material import MATERIALS, Material
from .world import BodyMeta, SoftBodyWorld


_EPS = 1e-9

# Detect the Rust-backed raster kernels once at import time. Falls back to
# the pure-numpy paths if `_core` is absent or the symbols aren't present
# (older _core builds without ``raster.rs``).
try:
    from slappyengine import _core as _native_core  # type: ignore
    _HAS_NATIVE_RASTER = (
        hasattr(_native_core, "rasterize_lines")
        and hasattr(_native_core, "rasterize_circles")
        and hasattr(_native_core, "box_blur_rgb")
    )
    _HAS_NATIVE_TEXTURE = hasattr(_native_core, "rasterize_textured_triangles")
except ImportError:  # pragma: no cover - exercised in pure-Python envs
    _native_core = None  # type: ignore
    _HAS_NATIVE_RASTER = False
    _HAS_NATIVE_TEXTURE = False


def _yaml_render_cfg() -> dict[str, Any]:
    import yaml
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "config" / "softbody.yml"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as fh:
                    raw = yaml.safe_load(fh) or {}
                section = raw.get("render") or {}
                return dict(section) if isinstance(section, dict) else {}
            except Exception:
                return {}
    return {}


@dataclass
class SoftBodyRenderConfig:
    width: int = 320
    height: int = 240
    bg_top: tuple[int, int, int] = (8, 8, 22)
    bg_bottom: tuple[int, int, int] = (24, 28, 52)
    floor_color: tuple[int, int, int] = (80, 80, 90)
    world_view: tuple[float, float, float, float] = (-1.0, -1.0, 1.0, 1.0)
    beam_thickness: float = 1.6
    node_radius: float = 1.4
    broken_beam_dim: float = 0.25
    draw_broken: bool = True
    # ``draw_nodes`` is the legacy back-compat alias for ``debug_show_nodes``.
    # The semantic name is ``debug_show_nodes`` (renderer pulls from
    # whichever is non-default; see ``__post_init__``). Both default to
    # False so production output is debug-overlay-free.
    draw_nodes: bool = False
    draw_skin_fill: bool = True
    # Debug overlays — beam wireframe + per-node dots. Default OFF so
    # production renders only show the body's "skin"; tests that need
    # the old wireframe look opt-in via from_yaml({"debug_show_beams":
    # True, "debug_show_nodes": True}).
    debug_show_beams: bool = False
    debug_show_nodes: bool = False
    # Texture-deform mode: warp a source PNG to follow the outermost
    # skin polygon of each body. Falls back to ``_draw_skin_fills``
    # (flat-color polygon) when False or the image fails to load.
    texture_deform: bool = False
    texture_image_path: str | None = None
    damage_break_count_max: int = 6
    damage_skin_strain_max: float = 0.25
    light_dir: tuple[float, float] = (-0.6, -0.8)
    light_ambient: float = 0.45
    light_diffuse: float = 0.55
    bloom_threshold: float = 0.85
    bloom_radius: int = 2
    bloom_strength: float = 0.55
    tonemap_exposure: float = 1.05
    tonemap_gamma: float = 2.2

    def __post_init__(self) -> None:
        # Back-compat: if the caller passed the legacy ``draw_nodes=True``
        # but did not explicitly set ``debug_show_nodes``, treat it as
        # the latter so existing call sites that rely on the old default
        # still work.
        if self.draw_nodes and not self.debug_show_nodes:
            self.debug_show_nodes = True
        elif self.debug_show_nodes and not self.draw_nodes:
            self.draw_nodes = True

    @classmethod
    def from_yaml(cls, overrides: dict[str, Any] | None = None) -> "SoftBodyRenderConfig":
        data = _yaml_render_cfg()
        if overrides:
            data.update(overrides)
        return cls(
            width=int(data.get("width", cls.width)),
            height=int(data.get("height", cls.height)),
            bg_top=tuple(data.get("bg_top", cls.bg_top)),
            bg_bottom=tuple(data.get("bg_bottom", cls.bg_bottom)),
            floor_color=tuple(data.get("floor_color", cls.floor_color)),
            world_view=tuple(data.get("world_view", cls.world_view)),
            beam_thickness=float(data.get("beam_thickness", cls.beam_thickness)),
            node_radius=float(data.get("node_radius", cls.node_radius)),
            broken_beam_dim=float(data.get("broken_beam_dim", cls.broken_beam_dim)),
            draw_broken=bool(data.get("draw_broken", cls.draw_broken)),
            draw_nodes=bool(data.get("draw_nodes", cls.draw_nodes)),
            draw_skin_fill=bool(data.get("draw_skin_fill", cls.draw_skin_fill)),
            debug_show_beams=bool(data.get("debug_show_beams", cls.debug_show_beams)),
            debug_show_nodes=bool(data.get("debug_show_nodes", cls.debug_show_nodes)),
            texture_deform=bool(data.get("texture_deform", cls.texture_deform)),
            texture_image_path=(
                str(data["texture_image_path"])
                if data.get("texture_image_path") is not None
                else cls.texture_image_path
            ),
            damage_break_count_max=int(data.get("damage_break_count_max", cls.damage_break_count_max)),
            damage_skin_strain_max=float(data.get("damage_skin_strain_max", cls.damage_skin_strain_max)),
            light_dir=tuple(data.get("light_dir", cls.light_dir)),
            light_ambient=float(data.get("light_ambient", cls.light_ambient)),
            light_diffuse=float(data.get("light_diffuse", cls.light_diffuse)),
            bloom_threshold=float(data.get("bloom_threshold", cls.bloom_threshold)),
            bloom_radius=int(data.get("bloom_radius", cls.bloom_radius)),
            bloom_strength=float(data.get("bloom_strength", cls.bloom_strength)),
            tonemap_exposure=float(data.get("tonemap_exposure", cls.tonemap_exposure)),
            tonemap_gamma=float(data.get("tonemap_gamma", cls.tonemap_gamma)),
        )


def _auto_view(world: SoftBodyWorld, pad: float = 0.15) -> tuple[float, float, float, float]:
    if world.nodes.count == 0:
        return (-1.0, -1.0, 1.0, 1.0)
    pos = world.nodes.pos
    x0 = float(pos[:, 0].min()); x1 = float(pos[:, 0].max())
    y0 = float(pos[:, 1].min()); y1 = float(world.floor_y)
    w = max(x1 - x0, 1e-3); h = max(y1 - y0, 1e-3)
    return (x0 - w * pad, y0 - h * pad, x1 + w * pad, y1 + h * pad)


class SoftBodyRenderer:
    def __init__(self, config: SoftBodyRenderConfig | None = None,
                 materials: dict[str, Material] | None = None) -> None:
        self.config = config or SoftBodyRenderConfig.from_yaml()
        self.materials = dict(MATERIALS)
        if materials:
            self.materials.update(materials)
        self._body_materials: dict[int, Material] = {}
        # Cache material → cached numpy color arrays. ``id(mat)`` keys
        # because Material may not be hashable. Saves ~1500 asarray
        # calls per frame at the cost of a small dict lookup each.
        self._mat_color_cache: dict[int, tuple[np.ndarray, np.ndarray, float]] = {}
        # Version counters for cache invalidation. Bumped by mutating
        # methods (``bind_body``, materials updates) so per-frame cache
        # keys can detect staleness without recomputing the full state.
        self._materials_version: int = 0
        self._body_materials_version: int = 0
        # --- Step 7 cache slots (all invalidate on the relevant version
        # counter change so mid-stream config / world mutation is safe).
        # _per_beam_material cache (cleared when body roster, materials,
        # or per-body bindings change).
        self._per_beam_cache_key: tuple[Any, ...] | None = None
        self._per_beam_cache_val: tuple[np.ndarray | None, list[Material]] | None = None
        # Cached material-color stack used in _draw_beams. Stored as a
        # tuple of (mat_id_tuple, base_lut, dmg_lut, break_lut) so the
        # numpy stack is rebuilt only when the set of unique materials
        # actually changes.
        self._mat_lut_cache_key: tuple[int, ...] | None = None
        self._mat_lut_cache_val: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None
        # _layer_material lookup cache. Cleared on materials version bump.
        self._layer_mat_cache: dict[int, Material] = {}
        self._layer_mat_cache_version: int = -1
        # Pre-computed disk offsets for _draw_nodes. Rebuilt when the
        # node_radius config value changes.
        self._disk_offsets_cache: tuple[float, np.ndarray, np.ndarray] | None = None
        # Pre-computed normalised light direction; rebuilt when the
        # configured light_dir tuple changes.
        self._light_unit_cache: tuple[tuple[float, float], float, float] | None = None

    def _mat_arrays(self, mat: Material) -> tuple[np.ndarray, np.ndarray, float]:
        cached = self._mat_color_cache.get(id(mat))
        if cached is not None:
            return cached
        v = (
            np.asarray(mat.render_color, dtype=np.float32),
            np.asarray(mat.damage_color, dtype=np.float32),
            float(mat.break_strain * 2.0),
        )
        self._mat_color_cache[id(mat)] = v
        return v

    def _layer_material_cached(self, layer: int, fallback: Material) -> Material:
        # Cheap memoisation around _layer_material — rebuilt when the
        # materials registry changes (registered via the version bump
        # below). The cache key is the integer layer alone since
        # ``self.materials`` is the only other input and is captured by
        # the version check.
        if self._layer_mat_cache_version != self._materials_version:
            self._layer_mat_cache.clear()
            self._layer_mat_cache_version = self._materials_version
        cached = self._layer_mat_cache.get(layer)
        if cached is not None:
            return cached
        mat = self._layer_material(layer, fallback)
        self._layer_mat_cache[layer] = mat
        return mat

    def _light_unit(self) -> tuple[float, float]:
        # Returns the pre-normalised light direction; recomputes lazily
        # only when ``cfg.light_dir`` changes.
        cfg = self.config
        lx, ly = cfg.light_dir
        cached = self._light_unit_cache
        if cached is not None and cached[0] == (lx, ly):
            return cached[1], cached[2]
        ll = float(np.hypot(lx, ly)) or 1.0
        nx, ny = float(lx) / ll, float(ly) / ll
        self._light_unit_cache = ((lx, ly), nx, ny)
        return nx, ny

    def _disk_offsets(self) -> tuple[np.ndarray, np.ndarray]:
        # Returns (oy, ox) integer offset arrays for the filled-disk
        # rasteriser. Cached on ``cfg.node_radius``; an in-memory rebuild
        # costs ~30 µs which is no longer per-frame.
        cfg = self.config
        r = max(int(round(cfg.node_radius)), 1)
        cached = self._disk_offsets_cache
        if cached is not None and cached[0] == r:
            return cached[1], cached[2]
        dy_g, dx_g = np.mgrid[-r:r + 1, -r:r + 1].astype(np.float32)
        disk_mask = (dx_g * dx_g + dy_g * dy_g) <= float(r * r) + 0.5
        oy, ox = np.nonzero(disk_mask)
        oy = (oy - r).astype(np.int32)
        ox = (ox - r).astype(np.int32)
        self._disk_offsets_cache = (r, oy, ox)
        return oy, ox

    def _bump_materials_version(self) -> None:
        self._materials_version += 1
        # Force the material-color stack cache to rebuild — its key is
        # only id() so a registry swap could collide otherwise.
        self._mat_lut_cache_key = None
        self._mat_lut_cache_val = None

    def bind_body(self, body_id: int, material: str | Material) -> None:
        mat = material if isinstance(material, Material) else self.materials[material]
        self._body_materials[int(body_id)] = mat
        self._body_materials_version += 1
        # Invalidate the per-beam material cache: a body binding change
        # may affect which Material an existing beam resolves to.
        self._per_beam_cache_key = None
        self._per_beam_cache_val = None

    def render(self, world: SoftBodyWorld,
               view_box: tuple[float, float, float, float] | None = None) -> np.ndarray:
        cfg = self.config
        if view_box is None:
            view_box = self._infer_view_box(world)
        cfg.world_view = view_box

        # Native fast path: keep the entire pipeline (background, floor,
        # skin_fills, beams, nodes, post-process) on a shared u8 RGB
        # buffer. Skin fills are composited via a Rust alpha-blend kernel
        # instead of the full-frame numpy multiply. This eliminates ~5
        # full-frame float allocations + ~3 full-frame numpy ops per
        # frame on the test scene.
        if _HAS_NATIVE_RASTER and hasattr(_native_core, "post_process_rgb"):
            H, W = cfg.height, cfg.width
            # Build the u8 background by reusing a persistent bytearray
            # and copying the cached u8 bg into it via slice assignment
            # (single memcpy, no extra alloc).
            bg = self._background_u8()
            buf = getattr(self, "_u8_buf_persistent", None)
            if buf is None or len(buf) != len(bg):
                buf = bytearray(len(bg))
                self._u8_buf_persistent = buf
            buf[:] = bg
            self._u8_buf = buf
            # Floor + skin_fills + draw_* all operate on the u8 buffer.
            self._draw_floor_u8(world)
            hdr = None  # noqa: F841 — kept for fallback path API compatibility
            if world.beams.count > 0:
                # Texture-deform draws first so debug overlays sit on top
                # when enabled. Falls back to the flat-color skin fill if
                # texture mode is off or the image fails to load.
                drew_texture = False
                if cfg.texture_deform:
                    drew_texture = self._draw_texture_deform(hdr, world)
                if not drew_texture:
                    self._draw_skin_fills(hdr, world)
                if cfg.debug_show_beams:
                    self._draw_beams(hdr, world)
            if cfg.debug_show_nodes and world.nodes.count > 0:
                self._draw_nodes(hdr, world)
            _native_core.post_process_rgb(
                self._u8_buf,
                int(W), int(H),
                int(cfg.bloom_radius),
                float(cfg.bloom_strength),
                float(cfg.bloom_threshold),
                float(cfg.tonemap_exposure),
                float(cfg.tonemap_gamma),
            )
            # Build the final RGBA without a redundant rgb copy: directly
            # interleave the u8 buffer into the (H, W, 4) output.
            out = np.empty((H, W, 4), dtype=np.uint8)
            out[..., :3] = np.frombuffer(self._u8_buf, dtype=np.uint8).reshape(H, W, 3)
            out[..., 3] = 255
            self._u8_buf = None
            return out

        hdr = self._background()
        self._draw_floor(hdr, world)
        if world.beams.count > 0:
            drew_texture = False
            if cfg.texture_deform:
                drew_texture = self._draw_texture_deform(hdr, world)
            if not drew_texture:
                self._draw_skin_fills(hdr, world)
            if cfg.debug_show_beams:
                self._draw_beams(hdr, world)
        if cfg.debug_show_nodes and world.nodes.count > 0:
            self._draw_nodes(hdr, world)
        rgb = self._post_process(hdr)
        out = np.zeros((cfg.height, cfg.width, 4), dtype=np.uint8)
        out[..., :3] = rgb
        out[..., 3] = 255
        return out

    def render_sequence(self, world: SoftBodyWorld, frame_count: int,
                        step_fn, steps_per_frame: int = 1,
                        view_box: tuple[float, float, float, float] | None = None
                        ) -> Iterable[np.ndarray]:
        for _ in range(frame_count):
            for _ in range(steps_per_frame):
                step_fn(world)
            yield self.render(world, view_box=view_box)

    def save_gif(self, frames: Sequence[np.ndarray], path: str | Path, fps: int = 30) -> Path:
        from PIL import Image
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        imgs = [Image.fromarray(f, mode="RGBA").convert("P", palette=Image.ADAPTIVE) for f in frames]
        imgs[0].save(path, save_all=True, append_images=imgs[1:],
                     duration=int(1000 / max(fps, 1)), loop=0, optimize=True)
        return path

    def _infer_view_box(self, world: SoftBodyWorld) -> tuple[float, float, float, float]:
        return _auto_view(world)

    def _background(self) -> np.ndarray:
        # Background is a static gradient — generate once, return a copy
        # per frame so callers can mutate freely. ``_bg_cache`` invalidates
        # when width/height/colors change.
        cfg = self.config
        h, w = cfg.height, cfg.width
        cache_key = (h, w, cfg.bg_top, cfg.bg_bottom)
        cached = getattr(self, "_bg_cache", None)
        if cached is None or cached[0] != cache_key:
            top = np.asarray(cfg.bg_top, dtype=np.float32)
            bot = np.asarray(cfg.bg_bottom, dtype=np.float32)
            t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
            col = top[None, None, :] * (1.0 - t) + bot[None, None, :] * t
            bg = np.broadcast_to(col, (h, w, 3)).astype(np.float32).copy()
            self._bg_cache = (cache_key, bg)
            cached = self._bg_cache
        return cached[1].copy()

    def _background_u8(self) -> bytes:
        """Return the cached u8 background bytes (read-only).

        Skips the float intermediate that the public ``_background``
        emits — the native pipeline writes directly into a u8 bytearray
        so we just need the immutable starting state.
        """
        cfg = self.config
        h, w = cfg.height, cfg.width
        key = (h, w, cfg.bg_top, cfg.bg_bottom)
        cached_u8 = getattr(self, "_bg_u8_cache", None)
        if cached_u8 is None or cached_u8[0] != key:
            top = np.asarray(cfg.bg_top, dtype=np.float32)
            bot = np.asarray(cfg.bg_bottom, dtype=np.float32)
            t = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None, None]
            col = top[None, None, :] * (1.0 - t) + bot[None, None, :] * t
            bg = np.broadcast_to(col, (h, w, 3))
            bg_u8 = np.clip(bg, 0.0, 255.0).astype(np.uint8).tobytes()
            self._bg_u8_cache = (key, bg_u8)
            cached_u8 = self._bg_u8_cache
        return cached_u8[1]

    def _draw_floor_u8(self, world: SoftBodyWorld) -> None:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        fy = world.floor_y
        if not (wy0 <= fy <= wy1):
            return
        _, sy = self._world_to_screen(np.zeros(1, dtype=np.float32),
                                      np.full(1, fy, dtype=np.float32))
        y = int(np.clip(float(sy[0]), 0, cfg.height - 1))
        # Stamp one floor-coloured row directly into the u8 buffer.
        row_off = y * cfg.width * 3
        r, g, b = (int(x) & 0xff for x in cfg.floor_color)
        floor_row = bytes([r, g, b]) * cfg.width
        self._u8_buf[row_off:row_off + cfg.width * 3] = floor_row

    def _world_to_screen(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        sx = (x - wx0) / max(wx1 - wx0, _EPS) * cfg.width
        sy = (y - wy0) / max(wy1 - wy0, _EPS) * cfg.height
        return sx.astype(np.float32), sy.astype(np.float32)

    def _draw_floor(self, hdr: np.ndarray, world: SoftBodyWorld) -> None:
        cfg = self.config
        wx0, wy0, wx1, wy1 = cfg.world_view
        fy = world.floor_y
        if not (wy0 <= fy <= wy1):
            return
        _, sy = self._world_to_screen(np.zeros(1, dtype=np.float32),
                                      np.full(1, fy, dtype=np.float32))
        y = int(np.clip(float(sy[0]), 0, cfg.height - 1))
        hdr[y, :, :] = np.asarray(cfg.floor_color, dtype=np.float32)

    def _resolve_material(self, body_id: int, fallback: Material | None = None) -> Material:
        mat = self._body_materials.get(int(body_id))
        if mat is not None:
            return mat
        if fallback is not None:
            return fallback
        return next(iter(self.materials.values()))

    def _per_beam_material(self, world: SoftBodyWorld) -> list[Material]:
        idx_arr, unique = self._per_beam_material_indexed(world)
        if idx_arr is None:
            return []
        return [unique[i] for i in idx_arr.tolist()]

    def _per_beam_material_indexed(
        self, world: SoftBodyWorld
    ) -> tuple[np.ndarray | None, list[Material]]:
        """Same as _per_beam_material but returns (per_beam_idx, unique_mats).

        Letting callers consume the index + LUT directly avoids a 780-
        iter Python ``list[unique_mats[i]]`` rebuild followed by another
        780-iter dedupe in ``_draw_beams``. The two passes are now one.

        Caches the result keyed by (bodies snapshot, beam count,
        materials version, body-bindings version). For a static scene
        the per-beam mapping never changes so the entire body of this
        function reduces to a dict lookup + key comparison.
        """
        beams = world.beams
        n_beams = int(beams.count)
        # Build a cheap cache key. Body identity + node_slice + name
        # changes are caught by the (id(b), node_slice, beam_slice)
        # snapshot; per-body material bindings are caught by the
        # ``_body_materials_version`` counter; registry-level material
        # swaps by the ``_materials_version`` counter.
        bodies_key = tuple(
            (id(b), b.body_id, b.node_slice, b.beam_slice)
            for b in world.bodies
            if isinstance(b, BodyMeta)
        )
        cache_key = (
            bodies_key,
            n_beams,
            self._materials_version,
            self._body_materials_version,
        )
        if self._per_beam_cache_key == cache_key and self._per_beam_cache_val is not None:
            return self._per_beam_cache_val

        nodes = world.nodes
        fallback = next(iter(self.materials.values()))
        body_mat: dict[int, Material | None] = {}
        for b in world.bodies:
            if not isinstance(b, BodyMeta):
                continue
            ns, ne = b.node_slice
            if ne > ns:
                layers = nodes.layer[ns:ne]
                lmin = int(layers.min())
                lmax = int(layers.max())
            else:
                lmin = 0; lmax = 0
            if lmin != lmax:
                body_mat[int(b.body_id)] = None  # mixed-layer body
            else:
                bound = self._body_materials.get(int(b.body_id))
                if bound is not None:
                    body_mat[int(b.body_id)] = bound
                else:
                    # Resolve from the body's single layer once.
                    body_mat[int(b.body_id)] = self._layer_material_cached(lmax, fallback)
        if n_beams == 0:
            result: tuple[np.ndarray | None, list[Material]] = (None, [])
            self._per_beam_cache_key = cache_key
            self._per_beam_cache_val = result
            return result
        bid_arr = np.asarray(beams.body_id, dtype=np.int64)
        mixed_bids = {bid for bid, m in body_mat.items() if m is None}
        if mixed_bids:
            # Slow path with per-beam layer lookup. Rare in practice.
            layer_a_arr = np.asarray(nodes.layer)[np.asarray(beams.node_a, dtype=np.int64)]
            bid_list = bid_arr.tolist()
            layer_list = layer_a_arr.tolist()
            mat_to_idx: dict[int, int] = {}
            unique_mats: list[Material] = []
            out_idx = np.empty(n_beams, dtype=np.int32)
            for i in range(n_beams):
                mat = body_mat.get(bid_list[i])
                if mat is None:
                    mat = self._layer_material_cached(layer_list[i], fallback)
                mid = id(mat)
                ix = mat_to_idx.get(mid)
                if ix is None:
                    ix = len(unique_mats)
                    mat_to_idx[mid] = ix
                    unique_mats.append(mat)
                out_idx[i] = ix
            result = (out_idx, unique_mats)
            self._per_beam_cache_key = cache_key
            self._per_beam_cache_val = result
            return result
        # Fast path: all bodies have a fixed material.
        unique_bids = np.unique(bid_arr)
        unique_mats = []
        for u in unique_bids.tolist():
            m = body_mat.get(u, fallback) or fallback
            unique_mats.append(m)
        beam_mat_idx = np.searchsorted(unique_bids, bid_arr).astype(np.int32)
        result = (beam_mat_idx, unique_mats)
        self._per_beam_cache_key = cache_key
        self._per_beam_cache_val = result
        return result

    def _layer_material(self, layer: int, fallback: Material) -> Material:
        layer_map = {0: "bone", 1: "muscle", 2: "skin", 3: "steel"}
        name = layer_map.get(layer)
        if name and name in self.materials:
            return self.materials[name]
        return fallback

    def _draw_beams(self, hdr: np.ndarray, world: SoftBodyWorld) -> None:
        cfg = self.config
        beams = world.beams
        nodes = world.nodes

        # Cache the int64 endpoint indices + the reciprocal of rest
        # lengths (used for strain normalisation). Both are invariant
        # for a body of fixed topology, so this avoids two ``astype``
        # casts + one ``np.maximum`` divide every frame.
        n_beams_cur = int(beams.count) if hasattr(beams, "count") else 0
        topo_key = (id(beams.node_a), id(beams.node_b),
                    id(beams.rest_length), n_beams_cur)
        topo_cached = getattr(self, "_beam_topo_cache", None)
        if topo_cached is not None and topo_cached[0] == topo_key:
            a_idx, b_idx, rest_inv = topo_cached[1], topo_cached[2], topo_cached[3]
            rest = topo_cached[4]
        else:
            a_idx = beams.node_a.astype(np.int64)
            b_idx = beams.node_b.astype(np.int64)
            rest = beams.rest_length
            rest_inv = np.float32(1.0) / np.maximum(rest, _EPS)
            self._beam_topo_cache = (topo_key, a_idx, b_idx, rest_inv, rest)
        pa = nodes.pos[a_idx]
        pb = nodes.pos[b_idx]
        sxa, sya = self._world_to_screen(pa[:, 0], pa[:, 1])
        sxb, syb = self._world_to_screen(pb[:, 0], pb[:, 1])
        cur_len = np.linalg.norm(pb - pa, axis=1)
        strain = np.abs(cur_len - rest) * rest_inv
        per_beam_mat_idx, unique_mats = self._per_beam_material_indexed(world)

        from PIL import Image, ImageDraw

        n_beams = int(beams.count) if hasattr(beams, "count") else 0
        if n_beams == 0 or per_beam_mat_idx is None:
            return
        # Build (M, 3) LUTs for unique materials, then expand by index.
        # Cache the stacked arrays keyed by the tuple of ``id(mat)`` —
        # rebuilt only when ``unique_mats`` (or the material registry)
        # changes. Saves three np.stack calls per frame on a static scene.
        lut_key = tuple(id(m) for m in unique_mats)
        if self._mat_lut_cache_key == lut_key and self._mat_lut_cache_val is not None:
            base_lut, dmg_lut, break_lut = self._mat_lut_cache_val
        else:
            mat_arrays = [self._mat_arrays(m) for m in unique_mats]
            base_lut = np.stack([a[0] for a in mat_arrays], axis=0)
            dmg_lut = np.stack([a[1] for a in mat_arrays], axis=0)
            break_lut = np.maximum(
                np.asarray([a[2] for a in mat_arrays], dtype=np.float32), _EPS
            )
            self._mat_lut_cache_key = lut_key
            self._mat_lut_cache_val = (base_lut, dmg_lut, break_lut)
        base_cols = base_lut[per_beam_mat_idx]
        dmg_cols = dmg_lut[per_beam_mat_idx]
        break_x2 = break_lut[per_beam_mat_idx]
        s_blend = np.minimum(strain / break_x2, 1.0)[:, None]
        base_colors = base_cols * (1.0 - s_blend) + dmg_cols * s_blend

        # Lighting attenuation: per-beam ndotl from beam orientation.
        dx_s = sxb - sxa
        dy_s = syb - sya
        lengths = np.maximum(np.hypot(dx_s, dy_s), _EPS)
        nx_s = -dy_s / lengths    # normal to beam
        ny_s = dx_s / lengths
        lx, ly = self._light_unit()
        ndotl = np.abs(nx_s * lx + ny_s * ly)
        light_atten = (cfg.light_ambient + cfg.light_diffuse * ndotl)[:, None]
        lit_colors = (base_colors * light_atten).clip(0.0, 255.0)

        # Per-beam dim + ghost cull for broken beams.
        broken_arr = beams.broken.astype(bool)
        ghost_cull = broken_arr & (cur_len > rest * 2.5)
        if not cfg.draw_broken or cfg.broken_beam_dim <= 0.0:
            keep_mask = ~broken_arr
        else:
            keep_mask = ~ghost_cull
        # For broken (kept) beams, blend toward damage color and dim.
        broken_blend = broken_arr & keep_mask
        if np.any(broken_blend):
            final_cols = lit_colors.copy()
            mix = (lit_colors[broken_blend] * 0.5
                    + dmg_cols[broken_blend] * 0.5) * cfg.broken_beam_dim
            final_cols[broken_blend] = mix.clip(0.0, 255.0)
        else:
            final_cols = lit_colors

        # Fully vectorised line rasterisation — no per-beam Python loop.
        # For each kept beam, sample N points along the segment, round to
        # screen pixels, and scatter into the HDR buffer. ``np.unique`` on
        # the flat (y*W + x) index keeps duplicate pixels from compounding
        # within a single beam pass. Targets 1k+ fps by collapsing the
        # entire ``for beam in order:`` loop into a handful of numpy
        # operations.
        H, W = cfg.height, cfg.width
        beam_mask = keep_mask
        if not np.any(beam_mask):
            return
        kept = np.nonzero(beam_mask)[0]
        xa_f = sxa[kept]
        ya_f = sya[kept]
        xb_f = sxb[kept]
        yb_f = syb[kept]
        cols_kept = final_cols[kept].clip(0.0, 255.0)

        # Native Rust fast-path: stamp directly into the shared u8
        # bytearray populated by ``render()``. The kernel does Bresenham
        # + bounds clipping + thickness. Same "last-writer-wins"
        # semantics as the numpy scatter below.
        if _HAS_NATIVE_RASTER and getattr(self, "_u8_buf", None) is not None:
            thickness = max(int(round(cfg.beam_thickness)), 1)
            cols_u8 = np.ascontiguousarray(cols_kept, dtype=np.uint8).tobytes()
            _native_core.rasterize_lines(
                self._u8_buf,
                int(W), int(H),
                np.ascontiguousarray(xa_f, dtype=np.float32).tobytes(),
                np.ascontiguousarray(ya_f, dtype=np.float32).tobytes(),
                np.ascontiguousarray(xb_f, dtype=np.float32).tobytes(),
                np.ascontiguousarray(yb_f, dtype=np.float32).tobytes(),
                cols_u8,
                int(thickness),
            )
            return
        # Sample count per beam: roughly Chebyshev distance + 1 (covers
        # all pixels along the line). One global N for simplicity — we
        # mask-clip out-of-bounds pixels anyway.
        seg_len = np.maximum(np.abs(xb_f - xa_f), np.abs(yb_f - ya_f))
        n_samples = int(np.ceil(seg_len.max())) + 1 if seg_len.size else 1
        n_samples = max(n_samples, 2)
        t = np.linspace(0.0, 1.0, n_samples, dtype=np.float32)[:, None]   # (S, 1)
        # Shape (S, B):
        xs = xa_f[None, :] * (1.0 - t) + xb_f[None, :] * t
        ys = ya_f[None, :] * (1.0 - t) + yb_f[None, :] * t
        xs_i = np.round(xs).astype(np.int32)
        ys_i = np.round(ys).astype(np.int32)
        # In-bounds mask
        ok = (xs_i >= 0) & (xs_i < W) & (ys_i >= 0) & (ys_i < H)
        # Per-sample color: broadcast (B, 3) across S
        b_idx = np.broadcast_to(np.arange(kept.size)[None, :], (n_samples, kept.size))
        flat_x = xs_i[ok]
        flat_y = ys_i[ok]
        flat_b = b_idx[ok]
        flat_cols = cols_kept[flat_b]
        # Direct scatter — last writer wins, which is fine for beams
        # since they're the same color along their length. For thickness
        # > 1, draw three parallel lines (offset by perpendicular pixel).
        thickness = max(int(round(cfg.beam_thickness)), 1)
        if thickness == 1:
            hdr[flat_y, flat_x] = flat_cols
        else:
            # Perpendicular pixel offsets — for thickness=3 use (-1,0,+1).
            half = thickness // 2
            for off in range(-half, half + 1):
                # Perpendicular direction per beam
                dx_p = -dy_s[kept]
                dy_p = dx_s[kept]
                norm = np.maximum(np.hypot(dx_p, dy_p), _EPS)
                pxo = (dx_p / norm * off)
                pyo = (dy_p / norm * off)
                xs2 = np.round(xs + pxo[None, :]).astype(np.int32)
                ys2 = np.round(ys + pyo[None, :]).astype(np.int32)
                ok2 = (xs2 >= 0) & (xs2 < W) & (ys2 >= 0) & (ys2 < H)
                fx2 = xs2[ok2]; fy2 = ys2[ok2]; fb2 = b_idx[ok2]
                hdr[fy2, fx2] = cols_kept[fb2]

    def _draw_nodes(self, hdr: np.ndarray, world: SoftBodyWorld) -> None:
        cfg = self.config
        nodes = world.nodes
        if nodes.count == 0:
            return
        sx, sy = self._world_to_screen(nodes.pos[:, 0], nodes.pos[:, 1])
        # bincount (was 2x np.add.at) for the per-node broken-beam degree.
        broken_count = np.zeros(nodes.count, dtype=np.int32)
        if world.beams.count > 0:
            a = world.beams.node_a.astype(np.int64)
            b = world.beams.node_b.astype(np.int64)
            br = world.beams.broken.astype(np.int32)
            broken_count = (np.bincount(a, weights=br, minlength=nodes.count)
                             + np.bincount(b, weights=br,
                                            minlength=nodes.count)).astype(np.int32)
        # Pre-compute per-node color vectorised, then rasterise via PIL.
        from PIL import Image, ImageDraw
        layers_arr = nodes.layer.astype(np.int64, copy=False)
        # Resolve material per layer via the memoised cache (no per-call
        # _layer_material rebuild when the layer set is unchanged).
        default_mat = next(iter(self.materials.values()))
        unique_layers = np.unique(layers_arr)
        layer_to_mat: dict[int, Material] = {
            int(L): self._layer_material_cached(int(L), default_mat)
            for L in unique_layers
        }
        # Reuse the cached (render_color, damage_color, break_x2) arrays
        # from _mat_arrays so we avoid the per-frame np.asarray loop.
        base_lut = np.stack(
            [self._mat_arrays(layer_to_mat[int(L)])[0] for L in unique_layers],
            axis=0,
        )
        dmg_lut = np.stack(
            [self._mat_arrays(layer_to_mat[int(L)])[1] for L in unique_layers],
            axis=0,
        )
        layer_idx_lookup = np.searchsorted(unique_layers, layers_arr)
        base_n = base_lut[layer_idx_lookup]
        dmg_n = dmg_lut[layer_idx_lookup]
        t_blend = np.minimum(
            broken_count / max(cfg.damage_break_count_max, 1),
            1.0,
        )[:, None]
        node_cols = (base_n * (1.0 - t_blend) + dmg_n * t_blend).clip(0.0, 255.0)
        node_cols_u8 = node_cols.astype(np.uint8)

        H, W = cfg.height, cfg.width
        r = max(int(round(cfg.node_radius)), 1)

        # Native Rust fast-path: stamp directly into the shared u8
        # bytearray populated by ``render()``. No float round-trip.
        if _HAS_NATIVE_RASTER and getattr(self, "_u8_buf", None) is not None:
            _native_core.rasterize_circles(
                self._u8_buf,
                int(W), int(H),
                np.ascontiguousarray(sx, dtype=np.float32).tobytes(),
                np.ascontiguousarray(sy, dtype=np.float32).tobytes(),
                node_cols_u8.tobytes(),
                int(r),
            )
            return

        # Fully vectorised disk rasterisation — same pattern as the beam
        # line rasteriser but writing a small filled square then masking
        # to a circle. For typical radius 1-3 this is ~10x faster than
        # PIL per-node ellipse dispatch.
        sx_i = sx.astype(np.int32)
        sy_i = sy.astype(np.int32)
        # Precompute disk offsets at config-load time and cache them on
        # the renderer — radius only changes when cfg.node_radius does.
        oy, ox = self._disk_offsets()
        # Broadcast: per (node n, pixel k) compute final (y, x)
        all_y = sy_i[:, None] + oy[None, :]          # (N, K)
        all_x = sx_i[:, None] + ox[None, :]          # (N, K)
        in_bounds = (all_x >= 0) & (all_x < W) & (all_y >= 0) & (all_y < H)
        # Color per pixel = node color
        col_b = np.broadcast_to(
            node_cols_u8[:, None, :], (nodes.count, oy.size, 3))
        fy = all_y[in_bounds]
        fx = all_x[in_bounds]
        fcol = col_b[in_bounds]
        # Last-writer-wins scatter; pixels overlap between nearby nodes
        # but node colours are similar so this looks correct.
        hdr[fy, fx] = fcol.astype(np.float32)

    def _draw_skin_fills(self, hdr: np.ndarray, world: SoftBodyWorld) -> None:
        cfg = self.config
        if not cfg.draw_skin_fill:
            return
        nodes = world.nodes
        layer = nodes.layer
        if layer.size == 0:
            return
        max_layer = int(layer.max()) if layer.size > 0 else 0
        if max_layer == 0:
            return
        try:
            from PIL import Image, ImageDraw
        except ImportError:
            return
        # Render ALL body polygons into a single RGBA image, then blend
        # once. Previously each body allocated a full-screen L mask,
        # ran a polygon draw, converted to float, and blended — 5
        # full-frame allocations + 5 blends per frame at 5 bodies.
        # Now: one full-frame allocation, one PIL polygon draw per
        # body (cheap), one composite. ~5x faster for typical scenes.
        H, W = cfg.height, cfg.width
        # Reuse a persistent PIL skin image — cheaper than allocating
        # a 307 KB RGBA buffer every frame. ``Image.paste`` with the
        # zero colour clears it.
        cached_img = getattr(self, "_skin_img", None)
        if cached_img is None or cached_img.size != (W, H):
            self._skin_img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        else:
            cached_img.paste((0, 0, 0, 0), (0, 0, W, H))
        skin_layer_img = self._skin_img
        skin_draw = ImageDraw.Draw(skin_layer_img)
        any_polygons = False

        default_mat = next(iter(self.materials.values()))
        # Cache per-body outer-layer index lookup. Topology is static
        # for a registered body (node_slice and the layer assignment do
        # not change after registration), so the (idx, outer_layer)
        # mapping is invariant. Key by id(body) + node_slice so a
        # re-registered body invalidates correctly.
        skin_idx_cache: dict[tuple[int, tuple[int, int]],
                              tuple[np.ndarray, int] | None] = getattr(
            self, "_skin_idx_cache", {})
        self._skin_idx_cache = skin_idx_cache
        for body in world.bodies:
            if not isinstance(body, BodyMeta):
                continue
            ns, ne = body.node_slice
            if ne - ns <= 0:
                continue
            cache_key = (id(body), (ns, ne))
            cached = skin_idx_cache.get(cache_key)
            if cached is None:
                body_layers = nodes.layer[ns:ne]
                outer_layer = int(body_layers.max())
                if outer_layer == 0:
                    skin_idx_cache[cache_key] = (np.empty(0, np.int64), 0)
                    continue
                mask = body_layers == outer_layer
                idx = np.nonzero(mask)[0]
                skin_idx_cache[cache_key] = (idx, outer_layer)
            else:
                idx, outer_layer = cached
                if outer_layer == 0:
                    continue
            if idx.size < 3:
                continue
            pts = nodes.pos[ns + idx]
            cx_w = float(pts[:, 0].mean()); cy_w = float(pts[:, 1].mean())
            ang = np.arctan2(pts[:, 1] - cy_w, pts[:, 0] - cx_w)
            order = np.argsort(ang)
            poly = pts[order]
            sx, sy = self._world_to_screen(poly[:, 0], poly[:, 1])
            # Use the cached layer-material lookup + cached numpy color
            # arrays (avoids two np.asarray calls per body per frame).
            mat = self._layer_material_cached(outer_layer, default_mat)
            base, dmg, _br = self._mat_arrays(mat)
            bs, be = body.beam_slice
            broken_frac = (float(world.beams.broken[bs:be].mean())
                            if be - bs > 0 else 0.0)
            t = float(min(broken_frac / max(cfg.damage_skin_strain_max, _EPS), 1.0))
            fill_color = (base * (1.0 - 0.35 * t) + dmg * (0.35 * t)) * 0.7
            fc = np.clip(fill_color, 0.0, 255.0).astype(np.uint8)
            # PIL accepts a flat interleaved [x1, y1, x2, y2, …] list,
            # which avoids allocating N tuple objects per body.
            flat_xy = np.empty(sx.size * 2, dtype=np.float32)
            flat_xy[0::2] = sx
            flat_xy[1::2] = sy
            skin_draw.polygon(
                flat_xy.tolist(),
                fill=(int(fc[0]), int(fc[1]), int(fc[2]), 216),
            )
            any_polygons = True

        if not any_polygons:
            return
        # Native composite path: blend RGBA polygon image directly into
        # the u8 hdr buffer (Rust kernel does fixed-point alpha mix).
        # Skips two full-frame float allocations + the per-pixel
        # divide-multiply chain that dominated this function.
        if (
            _HAS_NATIVE_RASTER
            and hasattr(_native_core, "alpha_composite_rgb")
            and getattr(self, "_u8_buf", None) is not None
        ):
            rgba_bytes = skin_layer_img.tobytes()
            _native_core.alpha_composite_rgb(self._u8_buf, rgba_bytes, int(W), int(H))
            return
        skin_rgba = np.asarray(skin_layer_img, dtype=np.float32)
        alpha = skin_rgba[..., 3:4] / 255.0
        hdr[:] = hdr * (1.0 - alpha) + skin_rgba[..., :3] * alpha

    # ────────────────────────────────────────────────────────────────
    # Texture-deform path
    # ────────────────────────────────────────────────────────────────

    def _default_texture_path(self) -> str | None:
        """Locate ``examples/textures/softbody_default.png`` relative to the
        repo root by walking up from this file. Returns ``None`` if no
        ``examples`` directory is found in any ancestor.
        """
        cached = getattr(self, "_default_tex_path_cache", "__unset__")
        if cached != "__unset__":
            return cached  # type: ignore[return-value]
        here = Path(__file__).resolve()
        result: str | None = None
        for parent in here.parents:
            candidate = parent / "examples" / "textures" / "softbody_default.png"
            if candidate.is_file():
                result = str(candidate)
                break
        self._default_tex_path_cache = result
        return result

    def _load_texture(self, path: str | None) -> np.ndarray | None:
        """Load a texture from ``path`` (or the default checkerboard PNG
        if ``path`` is None). Cached per-path on the renderer so repeated
        ``render()`` calls don't re-decode the PNG.
        """
        cache = getattr(self, "_tex_cache", None)
        if cache is None:
            cache = {}
            self._tex_cache = cache
        effective = path or self._default_texture_path()
        if effective is None:
            return None
        cached = cache.get(effective)
        if cached is not None:
            return cached
        try:
            from PIL import Image
            img = Image.open(effective).convert("RGB")
            arr = np.asarray(img, dtype=np.uint8)
        except Exception:
            cache[effective] = None  # type: ignore[assignment]
            return None
        cache[effective] = arr
        return arr

    def _rest_uvs_for_body(self, body: BodyMeta, nodes_pos: np.ndarray
                            ) -> np.ndarray | None:
        """Rest-state UVs (one per node in this body) computed once when
        the body is first rendered. Keyed by ``id(body)`` + node_slice so
        re-registration invalidates correctly.
        """
        cache = getattr(self, "_rest_uv_cache", None)
        if cache is None:
            cache = {}
            self._rest_uv_cache = cache
        ns, ne = body.node_slice
        key = (id(body), ns, ne)
        cached = cache.get(key)
        if cached is not None:
            return cached
        if ne - ns <= 0:
            return None
        pts = nodes_pos[ns:ne]
        xmin = float(pts[:, 0].min())
        xmax = float(pts[:, 0].max())
        ymin = float(pts[:, 1].min())
        ymax = float(pts[:, 1].max())
        # Pad by an epsilon to avoid 0/0 on degenerate rest geometry.
        ext_x = max(xmax - xmin, 1e-6)
        ext_y = max(ymax - ymin, 1e-6)
        u = (pts[:, 0] - xmin) / ext_x
        # Flip v so that the texture's top row maps to the body's
        # minimum-y row (PIL image origin is top-left, world y is
        # bottom-up after world_to_screen).
        v = (pts[:, 1] - ymin) / ext_y
        uvs = np.stack([u.astype(np.float32), v.astype(np.float32)], axis=1)
        cache[key] = uvs
        return uvs

    def _body_triangulation(self, body: BodyMeta, world: SoftBodyWorld
                            ) -> np.ndarray | None:
        """Return an (T, 3) int32 array of node-local indices forming the
        body's surface triangulation. Layered creatures use the outermost
        ring's polygon fan-triangulated from its centroid. Lattice bodies
        triangulate the regular grid into 2 triangles per cell. Other
        topologies fall back to a centroid fan over the convex hull
        ordered by angle (same as ``_draw_skin_fills``).
        """
        cache = getattr(self, "_tri_cache", None)
        if cache is None:
            cache = {}
            self._tri_cache = cache
        ns, ne = body.node_slice
        key = (id(body), ns, ne)
        cached = cache.get(key)
        if cached is not None:
            return cached
        if ne - ns <= 0:
            cache[key] = None
            return None
        params = body.parameters or {}
        topology = params.get("topology")
        tris: np.ndarray | None = None

        if topology == "lattice":
            wc = int(params.get("width_cells", 0))
            hc = int(params.get("height_cells", 0))
            nx = wc + 1
            ny = hc + 1
            if nx * ny == (ne - ns) and wc >= 1 and hc >= 1:
                # Two triangles per cell: (i,j)-(i+1,j)-(i+1,j+1) and
                # (i,j)-(i+1,j+1)-(i,j+1). Local indices into the body's
                # node block.
                ix = np.arange(nx, dtype=np.int32)
                iy = np.arange(ny, dtype=np.int32)
                gj, gi = np.meshgrid(iy, ix, indexing="ij")
                # Note: lattice builder uses iy * nx + ix indexing.
                gidx = (gj * nx + gi).astype(np.int32)
                tl = gidx[:-1, :-1].ravel()
                tr = gidx[:-1, 1:].ravel()
                bl = gidx[1:, :-1].ravel()
                br = gidx[1:, 1:].ravel()
                tri_a = np.stack([tl, tr, br], axis=1)
                tri_b = np.stack([tl, br, bl], axis=1)
                tris = np.concatenate([tri_a, tri_b], axis=0).astype(np.int32)

        if tris is None and topology == "layered_creature":
            ring_counts = params.get("ring_counts") or []
            if ring_counts:
                # The texture must "warp coherently with the outer skin".
                # We triangulate the outermost ring as a fan from a
                # virtual centroid (computed from the same ring's nodes
                # each frame — captured in the renderer at draw time, not
                # here). For the index list we treat the centroid as a
                # synthetic vertex with index ``n_outer`` (i.e. one past
                # the last ring node); ``_draw_texture_deform`` injects
                # the centroid into the per-frame vertex array before
                # consuming this index list.
                # Cumulative offsets into the body's node block:
                offsets = [0]
                for k in ring_counts:
                    offsets.append(offsets[-1] + int(k))
                outer = int(ring_counts[-1])
                outer_start = offsets[-2]
                # Local indices of the outer ring:
                ring_idx = (np.arange(outer, dtype=np.int32)
                            + np.int32(outer_start))
                next_idx = np.roll(ring_idx, -1)
                # Centroid index = the appended synthetic node; the
                # draw method knows to extend the vertex array by 1.
                centroid_local = np.int32(ne - ns)  # one past last body node
                centroid_arr = np.full(outer, centroid_local, dtype=np.int32)
                tris = np.stack([centroid_arr, ring_idx, next_idx], axis=1)

        if tris is None:
            # Fallback: angle-ordered fan around the centroid over the
            # outermost layer (matches ``_draw_skin_fills`` semantics).
            body_layers = world.nodes.layer[ns:ne]
            outer_layer = int(body_layers.max())
            if outer_layer == 0:
                # Pure lattice (layer 3 all), but no topology info — use
                # all nodes.
                mask = np.ones(ne - ns, dtype=bool)
            else:
                mask = body_layers == outer_layer
            idx_local = np.nonzero(mask)[0].astype(np.int32)
            if idx_local.size < 3:
                cache[key] = None
                return None
            # Order by angle around centroid (rest positions). Compute
            # once now since topology is invariant.
            pts = world.nodes.pos[ns + idx_local]
            cx = float(pts[:, 0].mean()); cy = float(pts[:, 1].mean())
            ang = np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx)
            order = np.argsort(ang)
            ordered = idx_local[order]
            k = ordered.size
            next_ordered = np.roll(ordered, -1)
            centroid_local = np.int32(ne - ns)
            centroid_arr = np.full(k, centroid_local, dtype=np.int32)
            tris = np.stack([centroid_arr, ordered, next_ordered], axis=1)

        cache[key] = tris
        return tris

    def _draw_texture_deform(self, hdr: np.ndarray | None,
                              world: SoftBodyWorld) -> bool:
        """Warp the source texture along each body's deformed mesh and
        composite into the frame buffer. Returns True if any pixels were
        drawn (so the caller can suppress the flat-colour fallback).

        Topology assumptions (see ``_body_triangulation``):
          * Lattice bodies — regular ``(width_cells + 1) × (height_cells
            + 1)`` grid, split into 2 triangles per cell.
          * Layered creatures — texture is mapped to the outermost ring
            as a centroid fan (the visible "skin"). Inner layers (bone,
            muscle) move under the same skin and don't get their own
            texture pass; the deformed skin warps coherently with them.
          * Anything else — angle-ordered fan around the body's centroid
            over the outermost layer, matching ``_draw_skin_fills``.
        """
        cfg = self.config
        tex = self._load_texture(cfg.texture_image_path)
        if tex is None:
            return False
        tex_h, tex_w = tex.shape[:2]
        if tex_h == 0 or tex_w == 0:
            return False
        nodes = world.nodes
        if nodes.count == 0:
            return False

        H, W = cfg.height, cfg.width
        # Native fast path: collect all per-triangle (3 vertex screen
        # positions, 3 UVs) tuples into flat (T, 3, 2) arrays and call
        # the Rust rasteriser directly against the persistent ``_u8_buf``.
        # This bypasses the Python numpy fallback entirely (~50 us/tri
        # → ~3 us/tri at the same fidelity).
        use_native = (
            _HAS_NATIVE_TEXTURE
            and hdr is None
            and getattr(self, "_u8_buf", None) is not None
        )
        if use_native:
            return self._draw_texture_deform_native(world, tex, H, W)

        # Scratch buffer per frame — uint8 RGB + bool coverage so the
        # composite stays in 8-bit space (cuts the dominant scatter
        # cost roughly in half vs float32). The buffers are pooled on
        # the renderer (``_tex_scratch_rgb`` / ``_tex_scratch_cov``) so
        # repeat render() calls don't re-allocate the ~300 KB pair.
        scratch = getattr(self, "_tex_scratch", None)
        if (scratch is None or scratch[0].shape[:2] != (H, W)):
            out_rgb = np.zeros((H, W, 3), dtype=np.uint8)
            out_cov = np.zeros((H, W), dtype=bool)
            self._tex_scratch = (out_rgb, out_cov)
        else:
            out_rgb, out_cov = scratch
            out_cov.fill(False)
            # out_rgb pixels are only consulted where out_cov is True,
            # so we don't need to zero them — saves ~100 us/frame.
        drew_any = False

        for body in world.bodies:
            if not isinstance(body, BodyMeta):
                continue
            ns, ne = body.node_slice
            if ne - ns < 3:
                continue
            tris_local = self._body_triangulation(body, world)
            if tris_local is None or tris_local.size == 0:
                continue
            rest_uvs = self._rest_uvs_for_body(body, nodes.pos)
            if rest_uvs is None:
                continue
            # World-space body vertices (this frame). If the
            # triangulation references the "centroid index" (one past
            # the body's last node), we synthesise it from the current
            # outermost ring.
            body_pts = nodes.pos[ns:ne]
            centroid_idx = ne - ns
            need_centroid = bool((tris_local == centroid_idx).any())
            if need_centroid:
                params = body.parameters or {}
                topology = params.get("topology")
                if topology == "layered_creature":
                    ring_counts = params.get("ring_counts") or []
                    offsets = [0]
                    for k in ring_counts:
                        offsets.append(offsets[-1] + int(k))
                    outer_start = offsets[-2]
                    outer_end = offsets[-1]
                    outer_pts = body_pts[outer_start:outer_end]
                else:
                    body_layers = nodes.layer[ns:ne]
                    outer_layer = int(body_layers.max())
                    mask = (body_layers == outer_layer
                            if outer_layer > 0
                            else np.ones(ne - ns, dtype=bool))
                    outer_pts = body_pts[mask]
                cx = float(outer_pts[:, 0].mean())
                cy = float(outer_pts[:, 1].mean())
                centroid_pt = np.asarray([[cx, cy]], dtype=np.float32)
                body_pts_ext = np.concatenate([body_pts, centroid_pt], axis=0)
                # Centroid UV = mean of outer-ring UVs (matches centroid
                # of the rest-state outer polygon).
                if rest_uvs.shape[0] >= outer_pts.shape[0]:
                    if (body.parameters or {}).get("topology") == "layered_creature":
                        outer_uvs = rest_uvs[outer_start:outer_end]
                    else:
                        outer_uvs = rest_uvs[mask]
                else:
                    outer_uvs = rest_uvs
                centroid_uv = np.asarray(
                    [[float(outer_uvs[:, 0].mean()),
                      float(outer_uvs[:, 1].mean())]],
                    dtype=np.float32,
                )
                uvs_ext = np.concatenate([rest_uvs, centroid_uv], axis=0)
            else:
                body_pts_ext = body_pts
                uvs_ext = rest_uvs

            sx, sy = self._world_to_screen(body_pts_ext[:, 0], body_pts_ext[:, 1])
            screen_verts = np.stack([sx, sy], axis=1).astype(np.float32)
            # Rasterise every triangle in one vectorised numpy pass.
            self._rasterize_textured_triangles(
                tris_local, screen_verts, uvs_ext, tex,
                out_rgb, out_cov,
            )
            drew_any = True

        if not drew_any:
            return False

        # Composite via boolean masking: at every pixel where the texture
        # rasterizer wrote (out_cov == True), overwrite the framebuffer
        # with the sampled texel; elsewhere leave the existing background
        # untouched. Pure-numpy and ~5x faster than the alpha-blend form.
        if hdr is not None:
            hdr[out_cov] = out_rgb[out_cov].astype(np.float32)
        else:
            buf = getattr(self, "_u8_buf", None)
            if buf is None:
                return False
            existing = np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 3)
            # Make a writeable copy of the buffer (np.frombuffer returns
            # a read-only view). Cheap because we'd be writing to the
            # same memory anyway via bytearray slice-assign.
            writeable = existing.copy()
            writeable[out_cov] = out_rgb[out_cov]
            buf[:] = writeable.tobytes()
        return True

    def _draw_texture_deform_native(self, world: SoftBodyWorld,
                                     tex: np.ndarray, H: int, W: int) -> bool:
        """Rust-backed implementation of ``_draw_texture_deform``.

        Builds flat ``(T, 3, 2) float32`` arrays of screen-space triangle
        vertices and rest-state UVs across every body, then dispatches
        to ``_native_core.rasterize_textured_triangles``. The Rust
        kernel writes directly into ``self._u8_buf`` (last-writer-wins
        on triangle overlap, matching the numpy fallback).
        """
        nodes = world.nodes
        tri_verts_list: list[np.ndarray] = []
        tri_uvs_list: list[np.ndarray] = []
        for body in world.bodies:
            if not isinstance(body, BodyMeta):
                continue
            ns, ne = body.node_slice
            if ne - ns < 3:
                continue
            tris_local = self._body_triangulation(body, world)
            if tris_local is None or tris_local.size == 0:
                continue
            rest_uvs = self._rest_uvs_for_body(body, nodes.pos)
            if rest_uvs is None:
                continue
            body_pts = nodes.pos[ns:ne]
            centroid_idx = ne - ns
            need_centroid = bool((tris_local == centroid_idx).any())
            if need_centroid:
                params = body.parameters or {}
                topology = params.get("topology")
                if topology == "layered_creature":
                    ring_counts = params.get("ring_counts") or []
                    offsets = [0]
                    for k in ring_counts:
                        offsets.append(offsets[-1] + int(k))
                    outer_start = offsets[-2]
                    outer_end = offsets[-1]
                    outer_pts = body_pts[outer_start:outer_end]
                else:
                    body_layers = nodes.layer[ns:ne]
                    outer_layer = int(body_layers.max())
                    mask = (body_layers == outer_layer
                            if outer_layer > 0
                            else np.ones(ne - ns, dtype=bool))
                    outer_pts = body_pts[mask]
                cx = float(outer_pts[:, 0].mean())
                cy = float(outer_pts[:, 1].mean())
                centroid_pt = np.asarray([[cx, cy]], dtype=np.float32)
                body_pts_ext = np.concatenate([body_pts, centroid_pt], axis=0)
                if rest_uvs.shape[0] >= outer_pts.shape[0]:
                    if (body.parameters or {}).get("topology") == "layered_creature":
                        outer_uvs = rest_uvs[outer_start:outer_end]
                    else:
                        outer_uvs = rest_uvs[mask]
                else:
                    outer_uvs = rest_uvs
                centroid_uv = np.asarray(
                    [[float(outer_uvs[:, 0].mean()),
                      float(outer_uvs[:, 1].mean())]],
                    dtype=np.float32,
                )
                uvs_ext = np.concatenate([rest_uvs, centroid_uv], axis=0)
            else:
                body_pts_ext = body_pts
                uvs_ext = rest_uvs

            sx, sy = self._world_to_screen(body_pts_ext[:, 0], body_pts_ext[:, 1])
            screen_verts = np.stack([sx, sy], axis=1).astype(np.float32)
            # Fancy-index the per-triangle vertices/UVs to produce
            # (T, 3, 2) float32 arrays expected by the Rust kernel.
            tris_idx = tris_local.astype(np.int32, copy=False)
            tri_verts_list.append(screen_verts[tris_idx])
            tri_uvs_list.append(uvs_ext.astype(np.float32, copy=False)[tris_idx])

        if not tri_verts_list:
            return False
        if len(tri_verts_list) == 1:
            tri_verts = tri_verts_list[0]
            tri_uvs = tri_uvs_list[0]
        else:
            tri_verts = np.concatenate(tri_verts_list, axis=0)
            tri_uvs = np.concatenate(tri_uvs_list, axis=0)

        # Ensure contiguous float32 — Rust expects packed 3*2*f32 per tri.
        tri_verts = np.ascontiguousarray(tri_verts, dtype=np.float32)
        tri_uvs = np.ascontiguousarray(tri_uvs, dtype=np.float32)
        tex_arr = np.ascontiguousarray(tex, dtype=np.uint8)
        tex_h, tex_w = tex_arr.shape[:2]

        _native_core.rasterize_textured_triangles(
            self._u8_buf,
            int(W), int(H),
            tri_verts.tobytes(),
            tri_uvs.tobytes(),
            tex_arr.tobytes(),
            int(tex_w), int(tex_h),
        )
        return True

    # Cached precomputed coord row [0, 1, ..., MAX-1] used by the
    # rasteriser. Wider than any plausible triangle bbox; slicing is
    # ~50x cheaper than rebuilding an mgrid every triangle.
    _COORD_ROW: np.ndarray | None = None

    @classmethod
    def _coord_row(cls, n: int) -> np.ndarray:
        row = cls._COORD_ROW
        if row is None or row.shape[0] < n:
            cls._COORD_ROW = np.arange(max(n, 1024), dtype=np.float32)
            row = cls._COORD_ROW
        return row

    @staticmethod
    def _rasterize_textured_triangles(
        tris_local: np.ndarray,
        screen_verts: np.ndarray,
        uvs: np.ndarray,
        tex: np.ndarray,
        out_rgb: np.ndarray,
        out_cov: np.ndarray,
    ) -> None:
        """Vectorised per-triangle barycentric texture sampler.

        For each triangle we compute its screen-space bounding box, take
        2-D slices of a precomputed coordinate row (avoiding the per-tri
        ``np.mgrid`` cost — that one call alone was ~10 us/tri at the
        bbox sizes we care about), evaluate barycentric coords in one
        fused numpy expression, then nearest-neighbour sample the
        texture using bary-interpolated UVs.

        ``out_rgb`` is allocated as uint8 by the caller so the final
        composite stays in 8-bit space; this halves the bandwidth of
        the inner scatter and bypasses the float->uint8 conversion at
        composite time.
        """
        H, W, _ = out_rgb.shape
        tex_h, tex_w = tex.shape[:2]
        # Texture stays in its native dtype (uint8 for PNGs); we sample
        # with integer indices and the result is whatever ``tex.dtype``
        # is. The caller's composite handles the type promotion.
        tex_h_m1 = tex_h - 1
        tex_w_m1 = tex_w - 1
        # Hoist the precomputed coord row outside the loop. Slicing is
        # the cheapest path to per-bbox float32 axis arrays.
        max_dim = max(W, H)
        ROW = SoftBodyRenderer._coord_row(max_dim)
        for tri in tris_local:
            v0 = int(tri[0]); v1 = int(tri[1]); v2 = int(tri[2])
            p0x = float(screen_verts[v0, 0]); p0y = float(screen_verts[v0, 1])
            p1x = float(screen_verts[v1, 0]); p1y = float(screen_verts[v1, 1])
            p2x = float(screen_verts[v2, 0]); p2y = float(screen_verts[v2, 1])
            uv0u = float(uvs[v0, 0]); uv0v = float(uvs[v0, 1])
            uv1u = float(uvs[v1, 0]); uv1v = float(uvs[v1, 1])
            uv2u = float(uvs[v2, 0]); uv2v = float(uvs[v2, 1])
            # Triangle screen bbox, clipped to the framebuffer.
            xmin_f = p0x if p0x < p1x else p1x
            if p2x < xmin_f: xmin_f = p2x
            xmax_f = p0x if p0x > p1x else p1x
            if p2x > xmax_f: xmax_f = p2x
            ymin_f = p0y if p0y < p1y else p1y
            if p2y < ymin_f: ymin_f = p2y
            ymax_f = p0y if p0y > p1y else p1y
            if p2y > ymax_f: ymax_f = p2y
            xmin = int(xmin_f) if xmin_f > 0.0 else 0
            ymin = int(ymin_f) if ymin_f > 0.0 else 0
            xmax_i = int(xmax_f) + 1
            ymax_i = int(ymax_f) + 1
            if xmax_i > W: xmax_i = W
            if ymax_i > H: ymax_i = H
            if xmax_i <= xmin or ymax_i <= ymin:
                continue
            # Edge function denom — signed twice the triangle area.
            denom = (p1x - p0x) * (p2y - p0y) - (p2x - p0x) * (p1y - p0y)
            if -1e-6 < denom < 1e-6:
                continue
            inv_denom = 1.0 / denom
            # Per-bbox 1-D axis vectors via slicing the precomputed
            # ROW; broadcasting against each other replaces ``mgrid``.
            gy = ROW[ymin:ymax_i, None]                 # (h, 1)
            gx = ROW[None, xmin:xmax_i]                 # (1, w)
            # Barycentric weights of (gx, gy) w.r.t. p0, p1, p2.
            w1 = ((p2x - p1x) * (gy - p1y)
                  - (p2y - p1y) * (gx - p1x)) * inv_denom
            w2 = ((p0x - p2x) * (gy - p2y)
                  - (p0y - p2y) * (gx - p2x)) * inv_denom
            w0 = 1.0 - w1 - w2
            mask = (w0 >= 0.0) & (w1 >= 0.0) & (w2 >= 0.0)
            u = w0 * uv0u + w1 * uv1u + w2 * uv2u
            v = w0 * uv0v + w1 * uv1v + w2 * uv2v
            # Apply the in-triangle mask BEFORE indexing the texture
            # so we never sample with out-of-range UVs (those would
            # IndexError). Inside the triangle, barys are non-negative
            # and sum to 1, so the resulting u/v also lie in [0, 1].
            u_in = u[mask]
            v_in = v[mask]
            tx = (u_in * tex_w_m1).astype(np.int32)
            ty = (v_in * tex_h_m1).astype(np.int32)
            sampled = tex[ty, tx]
            # Scatter into the output buffer (overwrite — last-writer
            # wins on triangle overlap, which is fine for a manifold mesh).
            out_rgb[ymin:ymax_i, xmin:xmax_i][mask] = sampled
            out_cov[ymin:ymax_i, xmin:xmax_i][mask] = True

    def _apply_lighting(self, base: np.ndarray, dx: float, dy: float) -> np.ndarray:
        cfg = self.config
        ln = float(np.hypot(dx, dy))
        if ln < _EPS:
            return base * (cfg.light_ambient + cfg.light_diffuse * 0.5)
        nx, ny = -dy / ln, dx / ln
        lx, ly = self._light_unit()
        ndotl = abs(nx * lx + ny * ly)
        return base * (cfg.light_ambient + cfg.light_diffuse * ndotl)

    def _splat_capsule(self, hdr: np.ndarray, x0: float, y0: float,
                       x1: float, y1: float, color: np.ndarray, thickness: float) -> None:
        cfg = self.config
        H, W = cfg.height, cfg.width
        r = max(thickness, 0.5)
        xmin = int(np.clip(np.floor(min(x0, x1) - r), 0, W - 1))
        xmax = int(np.clip(np.ceil(max(x0, x1) + r), 0, W - 1))
        ymin = int(np.clip(np.floor(min(y0, y1) - r), 0, H - 1))
        ymax = int(np.clip(np.ceil(max(y0, y1) + r), 0, H - 1))
        if xmax <= xmin or ymax <= ymin:
            return
        ys, xs = np.mgrid[ymin:ymax + 1, xmin:xmax + 1].astype(np.float32)
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy + _EPS
        t = ((xs - x0) * dx + (ys - y0) * dy) / L2
        t = np.clip(t, 0.0, 1.0)
        px = x0 + t * dx; py = y0 + t * dy
        d = np.sqrt((xs - px) ** 2 + (ys - py) ** 2)
        alpha = np.clip(1.0 - (d - (r - 1.0)) / 1.5, 0.0, 1.0)
        alpha = alpha[..., None]
        region = hdr[ymin:ymax + 1, xmin:xmax + 1]
        region[:] = region * (1.0 - alpha) + color[None, None, :] * alpha

    def _splat_dot(self, hdr: np.ndarray, x: float, y: float,
                   color: np.ndarray, radius: float) -> None:
        cfg = self.config
        H, W = cfg.height, cfg.width
        r = max(radius, 0.5)
        xmin = int(np.clip(np.floor(x - r), 0, W - 1))
        xmax = int(np.clip(np.ceil(x + r), 0, W - 1))
        ymin = int(np.clip(np.floor(y - r), 0, H - 1))
        ymax = int(np.clip(np.ceil(y + r), 0, H - 1))
        if xmax <= xmin or ymax <= ymin:
            return
        ys, xs = np.mgrid[ymin:ymax + 1, xmin:xmax + 1].astype(np.float32)
        d = np.sqrt((xs - x) ** 2 + (ys - y) ** 2)
        alpha = np.clip(1.0 - (d - (r - 1.0)) / 1.2, 0.0, 1.0)[..., None]
        region = hdr[ymin:ymax + 1, xmin:xmax + 1]
        region[:] = region * (1.0 - alpha) + color[None, None, :] * alpha

    def _post_process(self, hdr: np.ndarray) -> np.ndarray:
        cfg = self.config
        # Operate directly in [0, 255] uint16 space to skip the
        # float32/255 divide-multiply round-trip; only the gamma pow
        # needs a normalised path.
        if cfg.bloom_radius > 0 and cfg.bloom_strength > 0.0:
            x = hdr.astype(np.float32) * (1.0 / 255.0)
            # Luminance via dot — single fused op
            lum = x @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
            bright = np.maximum(lum - cfg.bloom_threshold, 0.0)
            bright_rgb = x * bright[..., None]
            blurred = _box_blur(bright_rgb, cfg.bloom_radius)
            x += blurred * cfg.bloom_strength
        else:
            x = hdr * (1.0 / 255.0)

        # Reinhard tonemap + gamma in fused ops.
        np.multiply(x, cfg.tonemap_exposure, out=x)
        x = x / (1.0 + x)
        inv_gamma = 1.0 / max(cfg.tonemap_gamma, _EPS)
        # ``np.power`` with array input is heavy; for the typical gamma
        # 2.2 (inv ≈ 0.4545) ``np.cbrt(x)^(1.36)`` etc isn't a clean
        # closed form. Stick with power but guard the clip + nan once.
        np.clip(x, 0.0, 1.0, out=x)
        if abs(inv_gamma - 1.0) > 1e-3:
            np.power(x, inv_gamma, out=x)
        np.multiply(x, 255.0, out=x)
        np.clip(x, 0.0, 255.0, out=x)
        return x.astype(np.uint8)


def _box_blur(img: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return img
    # Native Rust path: separable sliding-window sum on a u8 buffer.
    # Matches the cumsum semantics of the numpy fallback while keeping
    # the cache footprint tiny (no full-image float intermediates).
    if _HAS_NATIVE_RASTER:
        h, w, _ = img.shape
        scale = 255.0 if img.dtype == np.float32 and img.max() <= 1.0 + 1e-3 else 1.0
        if scale != 1.0:
            arr = (img * scale).clip(0.0, 255.0).astype(np.uint8, copy=False)
        else:
            arr = img.astype(np.uint8, copy=False)
        buf = bytearray(arr.tobytes())
        _native_core.box_blur_rgb(buf, int(w), int(h), int(radius))
        out = np.frombuffer(bytes(buf), dtype=np.uint8).reshape(h, w, 3).astype(np.float32)
        if scale != 1.0:
            out = out / scale
        return out
    # PIL's GaussianBlur is SIMD-optimised C; for typical bloom radii
    # (~3-8 px) it's 5-10x faster than the pure-numpy cumsum approach.
    # We accept either float [0,1] or uint8 [0,255] input by scaling at
    # boundaries.
    try:
        from PIL import Image, ImageFilter
        scale = 255.0 if img.dtype == np.float32 and img.max() <= 1.0 + 1e-3 else 1.0
        if scale != 1.0:
            arr = (img * scale).clip(0.0, 255.0).astype(np.uint8)
        else:
            arr = img.astype(np.uint8, copy=False)
        # PIL gaussian sigma ≈ radius / 2 visually matches a box blur of
        # the same radius for bloom-style content; the difference is
        # imperceptible in a halo and dramatically faster.
        blurred = Image.fromarray(arr, "RGB").filter(
            ImageFilter.GaussianBlur(radius=float(radius))
        )
        out = np.asarray(blurred, dtype=np.float32)
        if scale != 1.0:
            out = out / scale
        return out
    except Exception:
        # Fallback to original cumsum if PIL is unavailable / fails.
        k = 2 * radius + 1
        pad = radius
        padded = np.pad(img, ((pad + 1, pad), (pad + 1, pad), (0, 0)), mode="edge")
        cs_y = np.cumsum(padded, axis=0)
        band = cs_y[k:, :, :] - cs_y[:-k, :, :]
        cs_x = np.cumsum(band, axis=1)
        box = cs_x[:, k:, :] - cs_x[:, :-k, :]
        return box / float(k * k)


def render_world_gif(world: SoftBodyWorld, out_path: str | Path, *,
                     step_fn=None, frame_count: int = 90, fps: int = 30,
                     steps_per_frame: int = 1,
                     config: SoftBodyRenderConfig | None = None,
                     view_box: tuple[float, float, float, float] | None = None) -> Path:
    if step_fn is None:
        from .solver import step
        step_fn = step
    r = SoftBodyRenderer(config=config)
    frames = list(r.render_sequence(world, frame_count, step_fn,
                                    steps_per_frame=steps_per_frame, view_box=view_box))
    return r.save_gif(frames, out_path, fps=fps)


__all__ = [
    "SoftBodyRenderConfig",
    "SoftBodyRenderer",
    "render_world_gif",
]
