"""LayerCompositor -- walk hybrid 2D+3D layers by z_order and composite them.

DDD3 sprint: build the composition pipeline that ties DDD1's hybrid
``Layer2D`` / ``Layer3D`` classes and DDD2's cross-layer sampling
protocols (``sample_from`` / ``apply_post_process_from`` /
``use_layer_as_texture``) into a single rendering surface.

Contract:

* One :class:`LayerCompositor` owns a wgpu device (soft-imported) plus a
  final RGBA composite texture the caller reads back to CPU / uploads to
  DPG.
* :meth:`render_scene` walks ``scene.layers`` in ascending ``z_order``.
  For each layer it (a) asks the layer to allocate its render target,
  (b) dispatches the layer's own render callback into that target, and
  (c) records ``layer_render`` / ``layer_composite`` events on the
  scene's event bus so tests + the debug HUD can watch the frame.
* If wgpu is missing / a device isn't available, the compositor falls
  back to a pure-numpy composite so downstream code (tests, headless CI,
  the 3D viewport placeholder path) always sees a valid final image.
* Cross-layer sampling is discovered by duck-typing: any layer with an
  attribute ``_sampled_layers`` (a list of other Layer objects), a
  ``sample_source`` reference, or ``material.diffuse_layer`` counts as a
  binding for reporting purposes. This keeps the compositor decoupled
  from whichever exact DDD2 protocol name lands.

Design notes:

* Blend modes match ``Layer.blend_mode`` from DDD1 -- ``normal`` (source
  over), ``additive`` (add, clamp), ``multiply`` (per-channel product),
  ``alpha`` (straight alpha copy), ``replace`` (overwrite regardless of
  source alpha).
* Layers with ``visible=False`` are skipped entirely.
* When a layer's ``render_target`` is a wgpu texture we read it back to
  CPU before compositing -- the wgpu pipeline is per-layer, the final
  compose pass is CPU-side numpy to keep DDD3 self-contained. A follow-up
  sprint can migrate the compose pass into a fullscreen WGSL shader.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, List, Sequence

import numpy as np

# wgpu is soft-imported -- the compositor works in numpy-only mode when
# wgpu isn't available (headless CI, wgpu adapter unavailable).
try:  # pragma: no cover -- optional dep
    import wgpu as _wgpu  # type: ignore[import-not-found]
    import wgpu.utils as _wgpu_utils  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    _wgpu = None  # type: ignore[assignment]
    _wgpu_utils = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Public trace type -- surfaced back to tests so they don't have to
# subscribe to the event bus themselves.
# ---------------------------------------------------------------------------


@dataclass
class LayerTraceEvent:
    """Single ``layer_render`` or ``layer_composite`` trace entry."""

    kind: str            # "layer_render" | "layer_composite" | "layer_alloc"
    layer_name: str
    z_order: int
    blend_mode: str
    frame: int


@dataclass
class CompositeStats:
    """Rollup returned from :meth:`LayerCompositor.render_scene`."""

    layers_walked: int = 0
    layers_rendered: int = 0
    layers_composited: int = 0
    cross_layer_binding_count: int = 0
    center_pixel: tuple[int, int, int, int] = (0, 0, 0, 0)
    events: List[LayerTraceEvent] = field(default_factory=list)
    frame_index: int = 0


# ---------------------------------------------------------------------------
# Duck-type helpers -- DDD2 has not finalised names as of DDD3, so we
# accept several protocol shapes.
# ---------------------------------------------------------------------------


def _iter_cross_layer_bindings(layer: Any) -> Iterable[Any]:
    """Yield every other layer *layer* samples / uses as a texture.

    Recognised protocols (any of):

    * ``layer._sampled_layers`` -- list populated by ``sample_from``.
    * ``layer._post_process_source`` -- populated by
      ``apply_post_process_from``.
    * ``layer._use_layer_as_texture_source`` -- populated by
      ``use_layer_as_texture``.
    * ``layer.material.diffuse_layer`` / ``.albedo_layer`` -- material
      channels that reference another layer directly.
    """
    seen: set[int] = set()
    for attr in (
        "_sampled_layers",
        "sampled_layers",
        "_post_process_sources",
        "post_process_sources",
    ):
        val = getattr(layer, attr, None)
        if val:
            for other in val:
                if id(other) not in seen:
                    seen.add(id(other))
                    yield other
    for attr in (
        "_post_process_source",
        "_use_layer_as_texture_source",
        "sample_source",
        "diffuse_layer_source",
        "_diffuse_layer",
    ):
        other = getattr(layer, attr, None)
        if other is not None and id(other) not in seen:
            seen.add(id(other))
            yield other

    # DDD2 real protocol -- Layer2D.apply_post_process_from populates
    # ``layer._post_process`` with PostProcessDescriptor objects; each has
    # a ``source_layer`` pointing at the sampled layer.
    for desc in getattr(layer, "_post_process", []) or []:
        src = getattr(desc, "source_layer", None)
        if src is not None and id(src) not in seen:
            seen.add(id(src))
            yield src

    # DDD2 real protocol -- Layer3D.use_layer_as_texture populates
    # ``layer._sampled_layer_textures`` with LayerTextureBinding objects
    # keyed by uniform slot.
    tex_bindings = getattr(layer, "_sampled_layer_textures", None)
    if isinstance(tex_bindings, dict):
        for ltb in tex_bindings.values():
            src = getattr(ltb, "source_layer", None)
            if src is not None and id(src) not in seen:
                seen.add(id(src))
                yield src

    mat = getattr(layer, "material", None) or getattr(layer, "mesh_material", None)
    if mat is not None:
        for attr in ("diffuse_layer", "albedo_layer", "texture_layer"):
            other = getattr(mat, attr, None)
            if other is not None and id(other) not in seen:
                seen.add(id(other))
                yield other


def _layer_render_target_pixels(layer: Any, width: int, height: int) -> np.ndarray:
    """Return an ``(H, W, 4)`` uint8 view of *layer*'s render output.

    Order of precedence:

    1. ``layer._image_data`` when it has content -- the CPU-side RGBA cache
       covers headless / numpy-render paths and matches the compositor's
       fallback pipeline.
    2. ``layer.render_target`` -- a wgpu texture (when the layer's real
       GPU pass rendered into it). We ask the layer for its
       ``_readback()`` if it exposes one, otherwise fall back to
       :func:`pharos_engine.layer._readback_texture`.
    3. A ``layer.clear_color`` filled buffer if neither has content.

    The precedence flip (image_data before render_target) is important:
    DDD1 allocates a wgpu texture up-front for every layer, but until
    the layer's own render pass writes into it that texture is a blank
    RGBA zero buffer. Preferring ``_image_data`` when it carries content
    lets numpy-driven demos + CI runs sample the right pixels.
    """
    img = getattr(layer, "_image_data", None)
    has_image = (
        isinstance(img, np.ndarray)
        and img.ndim == 3
        and img.size > 0
        and bool(np.any(img != 0))
    )
    if has_image:
        return _ensure_shape(img, height, width)

    tex = getattr(layer, "render_target", None)
    if tex is not None:
        readback = getattr(layer, "_readback", None)
        if callable(readback):
            try:
                arr = readback()
                if isinstance(arr, np.ndarray) and arr.dtype == np.uint8:
                    return _ensure_shape(arr, height, width)
            except Exception:
                pass
        try:  # pragma: no cover -- gpu path
            from pharos_engine.layer import _readback_texture
            arr = _readback_texture(tex, width, height)
            if isinstance(arr, np.ndarray):
                return _ensure_shape(arr, height, width)
        except Exception:
            pass

    # Even a zero-valued image_data is still a valid contribution -- fall
    # back to it before the clear-colour default.
    if isinstance(img, np.ndarray) and img.ndim == 3 and img.size > 0:
        return _ensure_shape(img, height, width)

    # Clear-color fallback -- so a freshly-created hybrid layer that hasn't
    # rendered yet still contributes its clear colour to the composite.
    clear = getattr(layer, "clear_color", (0.0, 0.0, 0.0, 0.0))
    r = int(np.clip(clear[0] * 255.0, 0.0, 255.0))
    g = int(np.clip(clear[1] * 255.0, 0.0, 255.0))
    b = int(np.clip(clear[2] * 255.0, 0.0, 255.0))
    a = int(np.clip(clear[3] * 255.0, 0.0, 255.0))
    out = np.empty((height, width, 4), dtype=np.uint8)
    out[..., 0] = r
    out[..., 1] = g
    out[..., 2] = b
    out[..., 3] = a
    return out


def _ensure_shape(arr: np.ndarray, h: int, w: int) -> np.ndarray:
    """Coerce *arr* to ``(H, W, 4) uint8`` -- resize by nearest neighbour."""
    if arr.dtype != np.uint8:
        arr = np.clip(arr, 0.0, 255.0).astype(np.uint8)
    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr, np.full_like(arr, 255)], axis=-1)
    if arr.shape[-1] == 3:
        alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
        arr = np.concatenate([arr, alpha], axis=-1)
    if arr.shape[0] == h and arr.shape[1] == w:
        return arr
    # Cheap nearest-neighbour resize -- no PIL required.
    ys = np.linspace(0, arr.shape[0] - 1, h).astype(np.int64)
    xs = np.linspace(0, arr.shape[1] - 1, w).astype(np.int64)
    return arr[ys[:, None], xs[None, :], :]


# ---------------------------------------------------------------------------
# Composite kernels (CPU / numpy)
# ---------------------------------------------------------------------------


def _composite_kernel(
    dst: np.ndarray,
    src: np.ndarray,
    blend_mode: str,
    opacity: float,
) -> np.ndarray:
    """Blend *src* onto *dst* by ``blend_mode`` scaled by ``opacity``.

    Both inputs are uint8 RGBA of identical shape. Returns *dst* mutated
    in place for API friendliness with the composite loop.
    """
    dst_f = dst.astype(np.float32)
    src_f = src.astype(np.float32)
    # Effective source alpha in [0, 1], further scaled by layer opacity.
    a = (src_f[..., 3:4] / 255.0) * float(opacity)

    if blend_mode == "additive":
        out_rgb = dst_f[..., :3] + src_f[..., :3] * a
    elif blend_mode == "multiply":
        norm = src_f[..., :3] / 255.0
        # Lerp toward the multiplied colour by the effective alpha so a
        # fully-transparent source is a no-op.
        blended = dst_f[..., :3] * norm
        out_rgb = dst_f[..., :3] * (1.0 - a) + blended * a
    elif blend_mode == "replace":
        out_rgb = dst_f[..., :3] * (1.0 - float(opacity)) + src_f[..., :3] * float(opacity)
    elif blend_mode == "alpha":
        out_rgb = dst_f[..., :3] * (1.0 - a) + src_f[..., :3] * a
    else:  # normal (source-over premultiplied result)
        out_rgb = dst_f[..., :3] * (1.0 - a) + src_f[..., :3] * a

    out_a = dst_f[..., 3:4] + (255.0 - dst_f[..., 3:4]) * a
    dst[..., :3] = np.clip(out_rgb, 0.0, 255.0).astype(np.uint8)
    dst[..., 3:4] = np.clip(out_a, 0.0, 255.0).astype(np.uint8)
    return dst


# ---------------------------------------------------------------------------
# LayerCompositor
# ---------------------------------------------------------------------------


class LayerCompositor:
    """Walk hybrid 2D+3D layers by z_order and composite them.

    Parameters
    ----------
    width, height
        Output composite resolution. Layer render targets that don't
        match are nearest-neighbour resampled during composite.
    device
        Optional pre-existing wgpu device. When ``None`` the compositor
        soft-imports wgpu and asks for the default device; failure just
        falls through to the numpy path.
    clear_color
        Background RGBA tuple in [0, 1]. Applied every frame before the
        first layer is composited.
    """

    def __init__(
        self,
        width: int = 512,
        height: int = 384,
        *,
        device: Any = None,
        clear_color: tuple[float, float, float, float] = (0.05, 0.05, 0.08, 1.0),
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.clear_color = clear_color

        # Device bring-up is best-effort. On failure we stay on the numpy
        # composite path -- the pipeline never crashes.
        self.device: Any = device
        if self.device is None and _wgpu is not None and _wgpu_utils is not None:
            try:  # pragma: no cover -- GPU-dependent
                self.device = _wgpu_utils.get_default_device()
            except Exception:
                self.device = None
        self.queue: Any = getattr(self.device, "queue", None) if self.device else None

        # Final composite target. When wgpu is up we also allocate a real
        # rgba8unorm texture so callers can pass ``output_view`` around;
        # otherwise it stays None and we hand back the CPU buffer.
        self.output_texture: Any = None
        if self.device is not None:  # pragma: no cover -- GPU-dependent
            try:
                self.output_texture = self.device.create_texture(
                    size=(self.width, self.height, 1),
                    format=_wgpu.TextureFormat.rgba8unorm,
                    usage=(
                        _wgpu.TextureUsage.RENDER_ATTACHMENT
                        | _wgpu.TextureUsage.COPY_DST
                        | _wgpu.TextureUsage.COPY_SRC
                        | _wgpu.TextureUsage.TEXTURE_BINDING
                    ),
                )
            except Exception:
                self.output_texture = None

        # CPU-side composite buffer -- always available.
        self.output_buffer: np.ndarray = self._make_clear_buffer()
        self._frame_count = 0
        # Public trace list of the most recent frame's events.
        self.last_events: List[LayerTraceEvent] = []

    # ------------------------------------------------------------------
    # Buffer helpers
    # ------------------------------------------------------------------

    def _make_clear_buffer(self) -> np.ndarray:
        buf = np.empty((self.height, self.width, 4), dtype=np.uint8)
        buf[..., 0] = int(np.clip(self.clear_color[0] * 255.0, 0.0, 255.0))
        buf[..., 1] = int(np.clip(self.clear_color[1] * 255.0, 0.0, 255.0))
        buf[..., 2] = int(np.clip(self.clear_color[2] * 255.0, 0.0, 255.0))
        buf[..., 3] = int(np.clip(self.clear_color[3] * 255.0, 0.0, 255.0))
        return buf

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render_scene(
        self,
        scene: Any,
        output_view: Any = None,
    ) -> CompositeStats:
        """Render + composite every layer of *scene*.

        Layers are read from ``scene.layers`` when present, otherwise from
        ``getattr(scene, "_layers", [])``. Each layer is dispatched via
        one of these protocols, in order:

        1. ``layer.render(compositor)`` -- caller-controlled path.
        2. ``layer.dispatch_render_pass(device, queue)`` -- DDD2 shape.
        3. ``layer.render_target`` already populated -- the compositor
           just samples it.

        The final composite pass runs on the CPU-side ``output_buffer``
        which is copied into ``output_view`` (a wgpu texture view) when
        supplied and wgpu is up.
        """
        self._frame_count += 1
        stats = CompositeStats(frame_index=self._frame_count)
        events: List[LayerTraceEvent] = []
        self.last_events = events

        bus = _scene_bus(scene)

        # Reset the composite buffer to the clear colour so previous
        # frames don't leak through in blend_mode="normal".
        self.output_buffer = self._make_clear_buffer()

        layers = _scene_layers(scene)
        # Layers are walked in ascending z_order -- ties break by
        # insertion order (Python's sort is stable).
        sorted_layers = sorted(
            layers,
            key=lambda l: (int(getattr(l, "z_order", 0)), getattr(l, "name", "")),
        )
        stats.layers_walked = len(sorted_layers)

        # First pass: give every layer a chance to allocate its render
        # target + dispatch its render pass. Cross-layer bindings need
        # every render target to exist BEFORE any sampling happens, so
        # we double-walk: allocate all first, then render.
        for layer in sorted_layers:
            if not getattr(layer, "visible", True):
                continue
            self._allocate(layer)
            events.append(LayerTraceEvent(
                kind="layer_alloc",
                layer_name=str(getattr(layer, "name", "layer")),
                z_order=int(getattr(layer, "z_order", 0)),
                blend_mode=str(getattr(layer, "blend_mode", "normal")),
                frame=self._frame_count,
            ))

        # Render each layer's contents into its own render target.
        for layer in sorted_layers:
            if not getattr(layer, "visible", True):
                continue
            self._dispatch_render(layer)
            stats.layers_rendered += 1
            event = LayerTraceEvent(
                kind="layer_render",
                layer_name=str(getattr(layer, "name", "layer")),
                z_order=int(getattr(layer, "z_order", 0)),
                blend_mode=str(getattr(layer, "blend_mode", "normal")),
                frame=self._frame_count,
            )
            events.append(event)
            if bus is not None:
                try:
                    bus.publish(
                        "layer_render",
                        layer_name=event.layer_name,
                        z_order=event.z_order,
                        blend_mode=event.blend_mode,
                        frame=self._frame_count,
                    )
                except Exception:
                    pass

        # Composite pass -- CPU-side numpy blend. This runs even on the
        # wgpu path so the final output_buffer stays authoritative and
        # tests can look at the centre pixel without a readback.
        for layer in sorted_layers:
            if not getattr(layer, "visible", True):
                continue
            src = _layer_render_target_pixels(layer, self.width, self.height)
            _composite_kernel(
                self.output_buffer,
                src,
                blend_mode=str(getattr(layer, "blend_mode", "normal")),
                opacity=float(getattr(layer, "opacity", 1.0)),
            )
            stats.layers_composited += 1
            event = LayerTraceEvent(
                kind="layer_composite",
                layer_name=str(getattr(layer, "name", "layer")),
                z_order=int(getattr(layer, "z_order", 0)),
                blend_mode=str(getattr(layer, "blend_mode", "normal")),
                frame=self._frame_count,
            )
            events.append(event)
            if bus is not None:
                try:
                    bus.publish(
                        "layer_composite",
                        layer_name=event.layer_name,
                        z_order=event.z_order,
                        blend_mode=event.blend_mode,
                        frame=self._frame_count,
                    )
                except Exception:
                    pass

        # Cross-layer binding tally -- reported once per frame so tests
        # can assert on it.
        binding_count = 0
        for layer in sorted_layers:
            binding_count += sum(1 for _ in _iter_cross_layer_bindings(layer))
        stats.cross_layer_binding_count = binding_count

        # Upload the final composite to the output texture / caller-
        # supplied view when wgpu is up.
        if self.queue is not None and self.output_texture is not None:  # pragma: no cover
            try:
                bpr = self.width * 4
                self.queue.write_texture(
                    {"texture": self.output_texture, "mip_level": 0, "origin": (0, 0, 0)},
                    self.output_buffer.tobytes(),
                    {"offset": 0, "bytes_per_row": bpr, "rows_per_image": self.height},
                    (self.width, self.height, 1),
                )
            except Exception:
                pass
        if output_view is not None and hasattr(output_view, "texture") and self.queue is not None:
            try:  # pragma: no cover
                tex = output_view.texture
                bpr = self.width * 4
                self.queue.write_texture(
                    {"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
                    self.output_buffer.tobytes(),
                    {"offset": 0, "bytes_per_row": bpr, "rows_per_image": self.height},
                    (self.width, self.height, 1),
                )
            except Exception:
                pass

        # Record centre-pixel for quick health-check.
        cy = self.height // 2
        cx = self.width // 2
        rgba = self.output_buffer[cy, cx]
        stats.center_pixel = (int(rgba[0]), int(rgba[1]), int(rgba[2]), int(rgba[3]))
        stats.events = list(events)
        return stats

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _allocate(self, layer: Any) -> None:
        """Ask *layer* to allocate its GPU render target if it has such a hook."""
        alloc = getattr(layer, "allocate_render_target", None)
        if callable(alloc):
            try:
                alloc(self.device)
                return
            except Exception:
                pass
        # DDD1 lets layers store their own render_target directly; if
        # they have neither the method nor the attribute we just leave
        # things alone -- the composite still reads _image_data.

    def _dispatch_render(self, layer: Any) -> None:
        """Run *layer*'s render callback -- best-effort duck-type dispatch."""
        for attr, args in (
            ("render", (self,)),
            ("dispatch_render_pass", (self.device, self.queue)),
            ("render_into_target", ()),
            ("draw", ()),
        ):
            fn = getattr(layer, attr, None)
            if callable(fn):
                try:
                    fn(*args)
                    return
                except TypeError:
                    # Signature mismatch -- try the next protocol shape.
                    continue
                except Exception:
                    return
        # No render method -- the layer's _image_data (if any) or clear
        # colour will still be sampled during composite.


# ---------------------------------------------------------------------------
# Scene helpers -- duck-typed so both the DDD1 Scene shape and a plain
# list-of-layers can be passed in.
# ---------------------------------------------------------------------------


def _scene_layers(scene: Any) -> Sequence[Any]:
    """Return the list of layers from *scene* using duck-typing."""
    if isinstance(scene, (list, tuple)):
        return list(scene)
    for attr in ("layers", "_layers", "hybrid_layers"):
        val = getattr(scene, attr, None)
        if val is not None:
            return list(val)
    return []


def _scene_bus(scene: Any) -> Any:
    """Return the scene's :class:`EventBus` (or the process default)."""
    for attr in ("bus", "events", "event_bus"):
        val = getattr(scene, attr, None)
        if val is not None and hasattr(val, "publish"):
            return val
    try:
        from pharos_engine import event_bus as _eb
        return _eb._DEFAULT_BUS
    except Exception:
        return None


__all__ = [
    "CompositeStats",
    "LayerCompositor",
    "LayerTraceEvent",
]
