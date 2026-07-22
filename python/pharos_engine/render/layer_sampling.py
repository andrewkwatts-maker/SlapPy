"""Cross-layer buffer sampling protocol (DDD2).

Lets a :class:`~pharos_engine.layer.Layer2D` sample a
:class:`~pharos_engine.layer.Layer3D`'s render target (and vice versa) so
post-process passes and cross-layer materials work end-to-end.

The runtime protocol is duck-typed: any object exposing
``get_view_for_sampling()`` (usually returning a ``wgpu.TextureView``) and a
``render_target`` attribute can act as a source layer. This lets DDD2 land
whether or not DDD1's Layer.render_target surface has been merged yet.

Everything is a soft-import of wgpu. On headless boxes the module still
imports and every helper falls back to CPU-friendly stand-ins.

Public surface
--------------
* :data:`BLEND_MODES` — set of composite blend mode names understood by the
  companion WGSL shader ``shaders/cross_layer_composite.wgsl``.
* :class:`LayerSampleBinding` — record binding a source layer to a uniform
  slot with configurable sampler filter + address mode.
* :func:`make_layer_sample_binding` — factory used by ``Layer.sample_from``.
* :func:`bind_sampled_layers` — build a ``wgpu.BindGroup`` for a list of
  sample bindings.
* :func:`fallback_texture_view` — 1×1 transparent view returned when the
  source layer has not rendered this frame yet.
* :func:`apply_post_process_from` — post-process pattern used by
  :meth:`~pharos_engine.layer.Layer2D.apply_post_process_from`.
* :func:`use_layer_as_texture` — 3D-material pattern used by
  :meth:`~pharos_engine.layer.Layer3D.use_layer_as_texture`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:  # pragma: no cover - optional at import time
    import wgpu  # type: ignore

    _HAS_WGPU = True
except Exception:  # pragma: no cover
    wgpu = None  # type: ignore[assignment]
    _HAS_WGPU = False


# --------------------------------------------------------------------------
# Blend modes understood by the companion WGSL shader
# --------------------------------------------------------------------------
BLEND_MODES: frozenset[str] = frozenset({"add", "multiply", "alpha", "screen"})

_FILTER_MODES: frozenset[str] = frozenset({"linear", "nearest"})
_ADDRESS_MODES: frozenset[str] = frozenset({"clamp", "repeat", "mirror"})


# --------------------------------------------------------------------------
# LayerSampleBinding
# --------------------------------------------------------------------------
@dataclass
class LayerSampleBinding:
    """A single source-layer binding used by a cross-layer composite pass."""

    layer: Any
    """Any object with a ``get_view_for_sampling()`` method (the "source" layer)."""

    uniform_name: str = "u_source_layer"
    """WGSL uniform / texture binding name (matches the composite shader)."""

    filter: str = "linear"
    """Sampler magnification/minification filter — ``"linear"`` or ``"nearest"``."""

    address_mode: str = "clamp"
    """Sampler address mode — ``"clamp"`` / ``"repeat"`` / ``"mirror"``."""

    slot: int = 0
    """Bind-group binding slot the texture view goes into."""

    def __post_init__(self) -> None:
        if self.filter not in _FILTER_MODES:
            raise ValueError(
                f"LayerSampleBinding.filter must be one of {sorted(_FILTER_MODES)}, "
                f"got {self.filter!r}"
            )
        if self.address_mode not in _ADDRESS_MODES:
            raise ValueError(
                f"LayerSampleBinding.address_mode must be one of "
                f"{sorted(_ADDRESS_MODES)}, got {self.address_mode!r}"
            )
        if not isinstance(self.uniform_name, str) or not self.uniform_name:
            raise ValueError("LayerSampleBinding.uniform_name must be non-empty str")


def make_layer_sample_binding(
    layer: Any,
    uniform_name: str = "u_source_layer",
    filter: str = "linear",
    address_mode: str = "clamp",
    slot: int = 0,
) -> LayerSampleBinding:
    """Factory used by :meth:`Layer.sample_from` — validates + wraps."""
    return LayerSampleBinding(
        layer=layer,
        uniform_name=uniform_name,
        filter=filter,
        address_mode=address_mode,
        slot=slot,
    )


# --------------------------------------------------------------------------
# Duck-typed accessors
# --------------------------------------------------------------------------
def _layer_view(layer: Any) -> Any:
    """Best-effort resolution of a wgpu TextureView from a source layer.

    Prefers the DDD1 protocol ``get_view_for_sampling()``; falls back to
    ``render_target`` attribute + ``.create_view()``. Returns ``None`` if the
    source has not been rendered this frame.
    """
    if layer is None:
        return None
    getter = getattr(layer, "get_view_for_sampling", None)
    if callable(getter):
        try:
            return getter()
        except Exception:
            return None
    rt = getattr(layer, "render_target", None)
    if rt is None:
        return None
    creator = getattr(rt, "create_view", None)
    if callable(creator):
        try:
            return creator()
        except Exception:
            return None
    return rt


# --------------------------------------------------------------------------
# Fallback 1×1 transparent texture (used when source hasn't rendered yet)
# --------------------------------------------------------------------------
_FALLBACK_CACHE: dict[int, Any] = {}


def fallback_texture_view(device: Any = None) -> Any:
    """Return a 1×1 transparent-black texture view.

    Callers pass their live ``wgpu.Device``. On headless boxes a plain
    sentinel is returned so the fallback path still exercises normally in
    tests.
    """
    if device is None or not _HAS_WGPU:
        return _HeadlessFallbackView()

    key = id(device)
    cached = _FALLBACK_CACHE.get(key)
    if cached is not None:
        return cached

    tex = device.create_texture(
        size=(1, 1, 1),
        format=wgpu.TextureFormat.rgba8unorm,
        usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
    )
    # Upload a single transparent pixel
    try:
        device.queue.write_texture(
            {"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
            b"\x00\x00\x00\x00",
            {"offset": 0, "bytes_per_row": 4, "rows_per_image": 1},
            (1, 1, 1),
        )
    except Exception:
        pass
    view = tex.create_view()
    _FALLBACK_CACHE[key] = view
    return view


class _HeadlessFallbackView:
    """Sentinel returned when wgpu is unavailable — carries the transparent
    pixel data so CPU-only paths (tests, headless CI) can still assert on it."""

    def __init__(self) -> None:
        self.size = (1, 1)
        self.format = "rgba8unorm"
        self.data = b"\x00\x00\x00\x00"
        self.is_fallback = True

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return "<LayerSampleFallback 1x1 transparent>"


# --------------------------------------------------------------------------
# bind_sampled_layers
# --------------------------------------------------------------------------
def _make_sampler(device: Any, filter: str, address_mode: str) -> Any:
    if not _HAS_WGPU or device is None:
        return _HeadlessSampler(filter, address_mode)

    filter_wgpu = wgpu.FilterMode.linear if filter == "linear" else wgpu.FilterMode.nearest
    addr_map = {
        "clamp": wgpu.AddressMode.clamp_to_edge,
        "repeat": wgpu.AddressMode.repeat,
        "mirror": wgpu.AddressMode.mirror_repeat,
    }
    return device.create_sampler(
        mag_filter=filter_wgpu,
        min_filter=filter_wgpu,
        address_mode_u=addr_map[address_mode],
        address_mode_v=addr_map[address_mode],
    )


class _HeadlessSampler:
    def __init__(self, filter: str, address_mode: str) -> None:
        self.filter = filter
        self.address_mode = address_mode
        self.is_fallback = True

    def __repr__(self) -> str:  # pragma: no cover - debug aid
        return f"<LayerSampleSampler filter={self.filter} addr={self.address_mode}>"


@dataclass
class _HeadlessBindGroup:
    """Fallback bind-group description used when wgpu isn't available.

    Tests inspect ``entries`` to verify bindings were assembled correctly.
    """

    entries: list[dict] = field(default_factory=list)
    is_fallback: bool = True

    def __len__(self) -> int:
        return len(self.entries)


def bind_sampled_layers(
    pass_encoder: Any,
    sample_bindings: list[LayerSampleBinding],
    bind_group_layout: Any,
    device: Any = None,
) -> Any:
    """Build a ``wgpu.BindGroup`` from ``sample_bindings``.

    Each binding contributes two entries in the resulting bind group:
    the texture view (at ``binding = slot*2``) and the sampler
    (at ``binding = slot*2 + 1``). If the source layer's view is missing
    (layer not yet rendered this frame) a 1×1 transparent fallback view
    is substituted.

    ``pass_encoder`` is retained in the signature for future
    ``set_bind_group`` sugar; today the caller does the ``set_bind_group``
    themselves once we return.
    """
    entries: list[dict] = []
    for i, sb in enumerate(sample_bindings):
        view = _layer_view(sb.layer)
        if view is None:
            view = fallback_texture_view(device)
        sampler = _make_sampler(device, sb.filter, sb.address_mode)
        entries.append(
            {
                "binding": sb.slot * 2,
                "resource": view,
                "uniform_name": sb.uniform_name,
            }
        )
        entries.append(
            {
                "binding": sb.slot * 2 + 1,
                "resource": sampler,
                "uniform_name": sb.uniform_name + "_sampler",
            }
        )

    if not _HAS_WGPU or device is None or bind_group_layout is None:
        return _HeadlessBindGroup(entries=entries)

    return device.create_bind_group(layout=bind_group_layout, entries=entries)


# --------------------------------------------------------------------------
# High-level patterns (used by Layer2D.apply_post_process_from and
# Layer3D.use_layer_as_texture)
# --------------------------------------------------------------------------
_COMPOSITE_SHADER_PATH = Path(__file__).parent / "shaders" / "cross_layer_composite.wgsl"


def load_composite_shader() -> str:
    """Return the source of the cross-layer composite shader."""
    return _COMPOSITE_SHADER_PATH.read_text(encoding="utf-8")


@dataclass
class PostProcessDescriptor:
    """Records a queued post-process pass on a Layer2D.

    The actual GPU draw happens inside the renderer's frame loop; storing the
    descriptor here keeps ``Layer2D`` GPU-context-free.
    """

    source_layer: Any
    shader_wgsl_path: str
    binding: LayerSampleBinding
    blend_mode: str = "alpha"

    def __post_init__(self) -> None:
        if self.blend_mode not in BLEND_MODES:
            raise ValueError(
                f"PostProcessDescriptor.blend_mode must be one of "
                f"{sorted(BLEND_MODES)}, got {self.blend_mode!r}"
            )


def apply_post_process_from(
    target_layer: Any,
    source_layer: Any,
    shader_wgsl_path: str | Path | None = None,
    blend_mode: str = "alpha",
) -> PostProcessDescriptor:
    """Register a post-process pass that samples ``source_layer`` into
    ``target_layer.render_target``.

    Returns the queued :class:`PostProcessDescriptor`. The renderer walks
    ``target_layer._post_process`` each frame and issues the sample pass.
    """
    if shader_wgsl_path is None:
        shader_wgsl_path = _COMPOSITE_SHADER_PATH
    binding = make_layer_sample_binding(source_layer, uniform_name="u_source_layer")
    desc = PostProcessDescriptor(
        source_layer=source_layer,
        shader_wgsl_path=str(shader_wgsl_path),
        binding=binding,
        blend_mode=blend_mode,
    )
    if not hasattr(target_layer, "_post_process"):
        target_layer._post_process = []
    target_layer._post_process.append(desc)
    return desc


@dataclass
class LayerTextureBinding:
    """Records a live-2D-as-3D-texture binding on a Layer3D."""

    source_layer: Any
    uniform_slot: str
    binding: LayerSampleBinding


def use_layer_as_texture(
    target_layer: Any,
    source_layer: Any,
    uniform_slot: str,
    filter: str = "linear",
    address_mode: str = "clamp",
) -> LayerTextureBinding:
    """Register a source layer's render target as a texture that meshes in
    ``target_layer`` can sample under WGSL binding ``uniform_slot``.
    """
    binding = make_layer_sample_binding(
        source_layer,
        uniform_name=uniform_slot,
        filter=filter,
        address_mode=address_mode,
    )
    ltb = LayerTextureBinding(
        source_layer=source_layer,
        uniform_slot=uniform_slot,
        binding=binding,
    )
    if not hasattr(target_layer, "_sampled_layer_textures"):
        target_layer._sampled_layer_textures = {}
    target_layer._sampled_layer_textures[uniform_slot] = ltb
    return ltb


__all__ = [
    "BLEND_MODES",
    "LayerSampleBinding",
    "PostProcessDescriptor",
    "LayerTextureBinding",
    "make_layer_sample_binding",
    "bind_sampled_layers",
    "fallback_texture_view",
    "load_composite_shader",
    "apply_post_process_from",
    "use_layer_as_texture",
]
