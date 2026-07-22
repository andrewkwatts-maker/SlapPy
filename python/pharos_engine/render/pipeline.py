"""wgpu render pipeline compilation, caching, and buffer/uniform helpers.

Landed by JJ1 as part of the Nova3D Parity Sprint 1 push. Provides the
plumbing that lets :class:`pharos_engine.render.Renderer` actually issue
real ``draw_indexed`` calls when wgpu is up, while keeping the numpy /
:class:`~pharos_engine.render.null_renderer.NullRenderer` path
untouched.

Public objects
--------------
* :class:`VertexFormat` — dataclass describing a vertex attribute layout.
* :class:`PipelineCache` — memoises ``(shader_id, mesh_format, blend_mode)``
  → ``wgpu.RenderPipeline``.
* :func:`create_forward_pipeline` — Blinn-Phong / unlit 3D pipeline.
* :func:`create_sprite_pipeline` — 2D quad + texture bind.
* :func:`create_line_pipeline` — 3D debug lines (line-list topology).
* :class:`BufferUploader` — signature-keyed vertex/index/uniform buffer
  cache.
* :class:`UniformBufferPool` — per-frame ring of uniform buffers for
  camera / lights / model matrix / material blocks.

Every helper is a soft-import of wgpu: importing this module never fails
on a headless box. The wgpu-dependent helpers just raise ``RuntimeError``
if invoked without wgpu installed.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

try:  # pragma: no cover - optional at import time
    import wgpu  # type: ignore

    _HAS_WGPU = True
except Exception:  # pragma: no cover
    wgpu = None  # type: ignore[assignment]
    _HAS_WGPU = False


# ----------------------------------------------------------------------
# Vertex format descriptions
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class VertexAttribute:
    """One vertex attribute — matches ``@location(n)`` in WGSL."""

    location: int
    offset: int
    format: str  # wgpu vertex format string, e.g. "float32x3"

    @property
    def byte_size(self) -> int:
        return _FORMAT_BYTES[self.format]


@dataclass(frozen=True)
class VertexFormat:
    """Describe a whole vertex layout (stride + attribute list).

    Used both to build a ``wgpu.VertexBufferLayout`` and to validate that
    the numpy arrays we're about to upload match the shader's
    expectations.
    """

    name: str
    stride: int
    attributes: tuple[VertexAttribute, ...]

    @property
    def locations(self) -> tuple[int, ...]:
        return tuple(a.location for a in self.attributes)

    def as_wgpu_layout(self) -> dict:
        return {
            "array_stride": self.stride,
            "step_mode": "vertex",
            "attributes": [
                {
                    "shader_location": a.location,
                    "offset": a.offset,
                    "format": a.format,
                }
                for a in self.attributes
            ],
        }


_FORMAT_BYTES: dict[str, int] = {
    "float32": 4,
    "float32x2": 8,
    "float32x3": 12,
    "float32x4": 16,
    "uint32": 4,
    "uint32x2": 8,
    "uint32x3": 12,
    "uint32x4": 16,
}


# Canonical vertex layouts matching the WGSL stock in shader_stock.py.
VERTEX_FORMAT_POS3_UV2 = VertexFormat(
    name="pos3_uv2",
    stride=20,  # 3+2 floats
    attributes=(
        VertexAttribute(location=0, offset=0, format="float32x3"),
        VertexAttribute(location=1, offset=12, format="float32x2"),
    ),
)

VERTEX_FORMAT_POS3_NRM3_UV2 = VertexFormat(
    name="pos3_nrm3_uv2",
    stride=32,  # 3+3+2 floats
    attributes=(
        VertexAttribute(location=0, offset=0, format="float32x3"),
        VertexAttribute(location=1, offset=12, format="float32x3"),
        VertexAttribute(location=2, offset=24, format="float32x2"),
    ),
)

VERTEX_FORMAT_POS2_UV2 = VertexFormat(
    name="pos2_uv2",
    stride=16,
    attributes=(
        VertexAttribute(location=0, offset=0, format="float32x2"),
        VertexAttribute(location=1, offset=8, format="float32x2"),
    ),
)

VERTEX_FORMAT_POS3_COL4 = VertexFormat(
    name="pos3_col4",
    stride=28,
    attributes=(
        VertexAttribute(location=0, offset=0, format="float32x3"),
        VertexAttribute(location=1, offset=12, format="float32x4"),
    ),
)


VERTEX_FORMATS: dict[str, VertexFormat] = {
    "pos3_uv2": VERTEX_FORMAT_POS3_UV2,
    "pos3_nrm3_uv2": VERTEX_FORMAT_POS3_NRM3_UV2,
    "pos2_uv2": VERTEX_FORMAT_POS2_UV2,
    "pos3_col4": VERTEX_FORMAT_POS3_COL4,
}


# ----------------------------------------------------------------------
# Blend modes
# ----------------------------------------------------------------------
BLEND_MODES = frozenset({"opaque", "alpha", "additive"})


def _blend_desc(mode: str) -> dict | None:
    if mode == "opaque":
        return None
    if mode == "alpha":
        return {
            "color": {
                "src_factor": "src-alpha",
                "dst_factor": "one-minus-src-alpha",
                "operation": "add",
            },
            "alpha": {
                "src_factor": "one",
                "dst_factor": "one-minus-src-alpha",
                "operation": "add",
            },
        }
    if mode == "additive":
        return {
            "color": {
                "src_factor": "src-alpha",
                "dst_factor": "one",
                "operation": "add",
            },
            "alpha": {
                "src_factor": "one",
                "dst_factor": "one",
                "operation": "add",
            },
        }
    raise ValueError(f"Unknown blend mode {mode!r}; expected one of {sorted(BLEND_MODES)}")


# ----------------------------------------------------------------------
# Pipeline cache
# ----------------------------------------------------------------------
@dataclass
class _PipelineKey:
    shader_id: str
    mesh_format: str
    blend_mode: str
    msaa: int
    color_format: str
    depth_format: str
    topology: str

    def as_tuple(self) -> tuple:
        return (
            self.shader_id,
            self.mesh_format,
            self.blend_mode,
            self.msaa,
            self.color_format,
            self.depth_format,
            self.topology,
        )


class PipelineCache:
    """Memoises compiled ``wgpu.RenderPipeline`` objects.

    Keyed by ``(shader_id, mesh_format, blend_mode, msaa, color_format,
    depth_format, topology)``. Callers pass the wgpu device once (or per
    call — the cache doesn't care as long as the device outlives the
    cached pipelines).
    """

    def __init__(self) -> None:
        self._cache: dict[tuple, Any] = {}
        self._shader_modules: dict[str, Any] = {}

    def __contains__(self, key: tuple) -> bool:
        return key in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()
        self._shader_modules.clear()

    # ------------------------------------------------------------------
    def _shader_module(self, device: Any, shader_id: str, wgsl: str) -> Any:
        cache_key = f"{shader_id}:{hashlib.sha1(wgsl.encode('utf-8')).hexdigest()[:12]}"
        mod = self._shader_modules.get(cache_key)
        if mod is None:
            mod = device.create_shader_module(label=shader_id, code=wgsl)
            self._shader_modules[cache_key] = mod
        return mod

    # ------------------------------------------------------------------
    def get_or_create(
        self,
        device: Any,
        *,
        shader_id: str,
        wgsl: str,
        vertex_format: VertexFormat,
        bind_group_layouts: list[Any],
        color_format: str,
        depth_format: str,
        msaa: int = 1,
        blend_mode: str = "opaque",
        topology: str = "triangle-list",
        cull_mode: str = "back",
        depth_write: bool = True,
        depth_compare: str = "less",
    ) -> Any:
        key = _PipelineKey(
            shader_id=shader_id,
            mesh_format=vertex_format.name,
            blend_mode=blend_mode,
            msaa=int(msaa),
            color_format=color_format,
            depth_format=depth_format,
            topology=topology,
        ).as_tuple()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if not _HAS_WGPU:
            raise RuntimeError("PipelineCache.get_or_create requires wgpu")
        module = self._shader_module(device, shader_id, wgsl)
        layout = device.create_pipeline_layout(
            label=f"{shader_id}_layout",
            bind_group_layouts=bind_group_layouts,
        )
        color_target: dict = {"format": color_format, "write_mask": 0xF}
        blend = _blend_desc(blend_mode)
        if blend is not None:
            color_target["blend"] = blend
        pipeline = device.create_render_pipeline(
            label=f"{shader_id}_pipeline",
            layout=layout,
            vertex={
                "module": module,
                "entry_point": "vs_main",
                "buffers": [vertex_format.as_wgpu_layout()],
            },
            primitive={
                "topology": topology,
                "cull_mode": cull_mode if topology == "triangle-list" else "none",
                "front_face": "ccw",
            },
            depth_stencil={
                "format": depth_format,
                "depth_write_enabled": bool(depth_write),
                "depth_compare": depth_compare,
            },
            multisample={"count": int(msaa), "mask": 0xFFFFFFFF, "alpha_to_coverage_enabled": False},
            fragment={
                "module": module,
                "entry_point": "fs_main",
                "targets": [color_target],
            },
        )
        self._cache[key] = pipeline
        return pipeline


# ----------------------------------------------------------------------
# Pipeline factories — one per stock shader
# ----------------------------------------------------------------------
def _require_wgpu() -> None:
    if not _HAS_WGPU:
        raise RuntimeError("wgpu is not available in this interpreter")


def _forward_bind_group_layouts(device: Any, *, phong: bool) -> list[Any]:
    """Build the standard forward-shader bind group layouts.

    Group 0: camera (+ lights if phong)
    Group 1: per-model uniforms (Model matrix + color)
    """
    entries_g0 = [
        {
            "binding": 0,
            "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
            "buffer": {"type": "uniform"},
        },
    ]
    if phong:
        entries_g0.append(
            {
                "binding": 1,
                "visibility": wgpu.ShaderStage.FRAGMENT,
                "buffer": {"type": "uniform"},
            }
        )
    bgl0 = device.create_bind_group_layout(label="cam_lights", entries=entries_g0)
    bgl1 = device.create_bind_group_layout(
        label="model",
        entries=[
            {
                "binding": 0,
                "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
                "buffer": {"type": "uniform"},
            }
        ],
    )
    return [bgl0, bgl1]


def _sprite_bind_group_layouts(device: Any) -> list[Any]:
    bgl0 = device.create_bind_group_layout(
        label="cam2d",
        entries=[
            {
                "binding": 0,
                "visibility": wgpu.ShaderStage.VERTEX,
                "buffer": {"type": "uniform"},
            }
        ],
    )
    bgl1 = device.create_bind_group_layout(
        label="sprite",
        entries=[
            {
                "binding": 0,
                "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
                "buffer": {"type": "uniform"},
            },
            {
                "binding": 1,
                "visibility": wgpu.ShaderStage.FRAGMENT,
                "texture": {"sample_type": "float", "view_dimension": "2d"},
            },
            {
                "binding": 2,
                "visibility": wgpu.ShaderStage.FRAGMENT,
                "sampler": {"type": "filtering"},
            },
        ],
    )
    return [bgl0, bgl1]


def _line_bind_group_layouts(device: Any) -> list[Any]:
    bgl0 = device.create_bind_group_layout(
        label="cam3d_line",
        entries=[
            {
                "binding": 0,
                "visibility": wgpu.ShaderStage.VERTEX,
                "buffer": {"type": "uniform"},
            }
        ],
    )
    return [bgl0]


def create_forward_pipeline(
    device: Any,
    *,
    shader_id: str = "phong_3d",
    msaa_samples: int = 1,
    color_format: str = "rgba8unorm",
    depth_format: str = "depth24plus",
    cache: PipelineCache | None = None,
    blend_mode: str = "opaque",
) -> Any:
    """Compile the Blinn-Phong / unlit forward pipeline.

    Uses :data:`VERTEX_FORMAT_POS3_NRM3_UV2` for phong, and
    :data:`VERTEX_FORMAT_POS3_UV2` for unlit.
    """
    _require_wgpu()
    from .shader_stock import get_shader

    src = get_shader(shader_id)
    phong = shader_id == "phong_3d"
    vf = VERTEX_FORMAT_POS3_NRM3_UV2 if phong else VERTEX_FORMAT_POS3_UV2
    bgls = _forward_bind_group_layouts(device, phong=phong)
    if cache is None:
        cache = PipelineCache()
    return cache.get_or_create(
        device,
        shader_id=shader_id,
        wgsl=src.wgsl,
        vertex_format=vf,
        bind_group_layouts=bgls,
        color_format=color_format,
        depth_format=depth_format,
        msaa=msaa_samples,
        blend_mode=blend_mode,
        topology="triangle-list",
    )


def create_sprite_pipeline(
    device: Any,
    *,
    msaa_samples: int = 1,
    color_format: str = "rgba8unorm",
    depth_format: str = "depth24plus",
    cache: PipelineCache | None = None,
    blend_mode: str = "alpha",
) -> Any:
    _require_wgpu()
    from .shader_stock import SPRITE_2D_WGSL

    bgls = _sprite_bind_group_layouts(device)
    if cache is None:
        cache = PipelineCache()
    return cache.get_or_create(
        device,
        shader_id="sprite_2d",
        wgsl=SPRITE_2D_WGSL,
        vertex_format=VERTEX_FORMAT_POS2_UV2,
        bind_group_layouts=bgls,
        color_format=color_format,
        depth_format=depth_format,
        msaa=msaa_samples,
        blend_mode=blend_mode,
        topology="triangle-list",
        depth_write=False,
        depth_compare="always",
    )


def create_line_pipeline(
    device: Any,
    *,
    msaa_samples: int = 1,
    color_format: str = "rgba8unorm",
    depth_format: str = "depth24plus",
    cache: PipelineCache | None = None,
) -> Any:
    _require_wgpu()
    from .shader_stock import LINE_3D_WGSL

    bgls = _line_bind_group_layouts(device)
    if cache is None:
        cache = PipelineCache()
    return cache.get_or_create(
        device,
        shader_id="line_3d",
        wgsl=LINE_3D_WGSL,
        vertex_format=VERTEX_FORMAT_POS3_COL4,
        bind_group_layouts=bgls,
        color_format=color_format,
        depth_format=depth_format,
        msaa=msaa_samples,
        blend_mode="alpha",
        topology="line-list",
        cull_mode="none",
        depth_write=False,
        depth_compare="less-equal",
    )


# ----------------------------------------------------------------------
# BufferUploader — signature-keyed vertex/index/uniform buffer cache
# ----------------------------------------------------------------------
def _array_signature(arr: np.ndarray) -> str:
    """Content-hashed signature. Same bytes → same key."""
    b = np.ascontiguousarray(arr).tobytes()
    h = hashlib.sha1(b).hexdigest()[:16]
    return f"{arr.dtype.str}:{arr.shape}:{h}"


class BufferUploader:
    """Cache-numpy-to-wgpu buffer uploads keyed by content signature.

    Callers ask for a buffer of a given usage (``vertex`` / ``index`` /
    ``uniform``). If the identical numpy bytes were uploaded before,
    the cached ``wgpu.Buffer`` is returned; otherwise a new buffer is
    created and written.
    """

    def __init__(self, device: Any | None = None) -> None:
        self._device = device
        self._cache: dict[tuple[str, str], Any] = {}

    @property
    def device(self) -> Any | None:
        return self._device

    def set_device(self, device: Any) -> None:
        self._device = device
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)

    def clear(self) -> None:
        self._cache.clear()

    # ------------------------------------------------------------------
    def upload(
        self,
        arr: np.ndarray,
        *,
        usage: str = "vertex",
    ) -> tuple[Any, int]:
        """Upload ``arr`` and return ``(buffer, byte_size)``.

        ``usage`` is one of ``"vertex" | "index" | "uniform"``.
        """
        if not _HAS_WGPU:
            raise RuntimeError("BufferUploader.upload requires wgpu")
        if self._device is None:
            raise RuntimeError("BufferUploader.set_device must be called first")
        arr = np.ascontiguousarray(arr)
        sig = _array_signature(arr)
        key = (usage, sig)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        usage_flag = _USAGE_FLAGS[usage]
        buf = self._device.create_buffer(
            label=f"upload:{usage}:{sig[:8]}",
            size=arr.nbytes,
            usage=usage_flag | wgpu.BufferUsage.COPY_DST,
            mapped_at_creation=False,
        )
        self._device.queue.write_buffer(buf, 0, arr.tobytes())
        self._cache[key] = (buf, arr.nbytes)
        return self._cache[key]

    def contains(self, arr: np.ndarray, *, usage: str = "vertex") -> bool:
        return (usage, _array_signature(np.ascontiguousarray(arr))) in self._cache


_USAGE_FLAGS: dict[str, int] = {}


def _init_usage_flags() -> None:
    if not _HAS_WGPU:
        return
    _USAGE_FLAGS.update(
        {
            "vertex": wgpu.BufferUsage.VERTEX,
            "index": wgpu.BufferUsage.INDEX,
            "uniform": wgpu.BufferUsage.UNIFORM,
            "storage": wgpu.BufferUsage.STORAGE,
        }
    )


_init_usage_flags()


# ----------------------------------------------------------------------
# UniformBufferPool — round-robin uniform block allocator
# ----------------------------------------------------------------------
@dataclass
class _PoolSlot:
    buffer: Any
    size: int
    in_use: bool = False


class UniformBufferPool:
    """Simple ring of uniform buffers sized by block.

    A "block" is a fixed byte size (defaults to 256 B, which matches the
    minUniformBufferOffsetAlignment on desktop). Requesting a block
    hands back an existing free slot or allocates a new one.

    ``write_mat4`` is a convenience for the common camera / model case.
    """

    def __init__(self, device: Any | None = None, *, block_size: int = 256) -> None:
        self._device = device
        self.block_size = int(block_size)
        self._slots: list[_PoolSlot] = []

    @property
    def device(self) -> Any | None:
        return self._device

    def set_device(self, device: Any) -> None:
        self._device = device
        self._slots.clear()

    def __len__(self) -> int:
        return len(self._slots)

    def reset(self) -> None:
        """Mark every slot free — call at ``begin_frame``."""
        for slot in self._slots:
            slot.in_use = False

    def acquire(self, size: int | None = None) -> Any:
        """Return a wgpu ``Buffer`` at least ``size`` bytes."""
        if not _HAS_WGPU:
            raise RuntimeError("UniformBufferPool.acquire requires wgpu")
        if self._device is None:
            raise RuntimeError("UniformBufferPool.set_device must be called first")
        want = int(size or self.block_size)
        for slot in self._slots:
            if not slot.in_use and slot.size >= want:
                slot.in_use = True
                return slot.buffer
        buf = self._device.create_buffer(
            label=f"ubo:{len(self._slots)}",
            size=max(want, self.block_size),
            usage=wgpu.BufferUsage.UNIFORM
            | wgpu.BufferUsage.COPY_DST
            | wgpu.BufferUsage.COPY_SRC,
            mapped_at_creation=False,
        )
        self._slots.append(_PoolSlot(buffer=buf, size=max(want, self.block_size), in_use=True))
        return buf

    def write(self, buffer: Any, data: bytes | np.ndarray) -> None:
        if not _HAS_WGPU:
            raise RuntimeError("UniformBufferPool.write requires wgpu")
        if self._device is None:
            raise RuntimeError("UniformBufferPool.set_device must be called first")
        if isinstance(data, np.ndarray):
            data = np.ascontiguousarray(data).tobytes()
        self._device.queue.write_buffer(buffer, 0, data)

    def write_mat4(self, buffer: Any, mat: np.ndarray) -> None:
        """Write a 4x4 float32 matrix (64 B) into the buffer."""
        m = np.ascontiguousarray(mat, dtype=np.float32)
        if m.shape != (4, 4):
            raise ValueError(f"write_mat4 expects (4,4), got {m.shape}")
        self.write(buffer, m)


# ----------------------------------------------------------------------
# WGSL parsing helper — used by tests to verify @location alignment
# ----------------------------------------------------------------------
def parse_wgsl_vs_locations(wgsl: str) -> dict[int, str]:
    """Return ``{location: type}`` for every ``@location(n)`` in a WGSL VSIn.

    Best-effort parser — enough for the stock shaders in
    :mod:`shader_stock`. Handles the format::

        struct VSIn {
            @location(0) position: vec3<f32>,
            @location(1) uv: vec2<f32>,
        };
    """
    import re

    out: dict[int, str] = {}
    # Match ``@location(N) name : TYPE`` where TYPE ends at a comma or the
    # end of the block. We append a sentinel comma so the last field on a
    # single-line struct (no trailing comma) still matches.
    pattern = re.compile(
        r"@location\((\d+)\)\s+\w+\s*:\s*([\w<>]+)",
        re.DOTALL,
    )
    # Restrict to the block after "struct VSIn" to avoid catching VSOut.
    m = re.search(r"struct\s+VSIn\s*\{([^}]*)\}", wgsl, re.DOTALL)
    block = m.group(1) if m else wgsl
    for match in pattern.finditer(block):
        loc = int(match.group(1))
        typ = match.group(2).strip()
        out[loc] = typ
    return out


__all__ = [
    "BLEND_MODES",
    "BufferUploader",
    "PipelineCache",
    "UniformBufferPool",
    "VertexAttribute",
    "VertexFormat",
    "VERTEX_FORMATS",
    "VERTEX_FORMAT_POS2_UV2",
    "VERTEX_FORMAT_POS3_COL4",
    "VERTEX_FORMAT_POS3_NRM3_UV2",
    "VERTEX_FORMAT_POS3_UV2",
    "create_forward_pipeline",
    "create_line_pipeline",
    "create_sprite_pipeline",
    "parse_wgsl_vs_locations",
]
