from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING
import numpy as np

from pharos_engine._validation import (
    validate_str,
    validate_positive_int,
    validate_positive_size_2tuple,
    validate_existing_file_path,
    validate_finite_float,
)
from pharos_engine._layer_validation import (
    validate_layer_mode,
    validate_struct_fields,
    validate_layer_arg,
)

if TYPE_CHECKING:
    from pharos_engine.entity import Entity


def _readback_texture(tex, w: int, h: int) -> "np.ndarray":
    """Read back a wgpu texture to a numpy uint8 RGBA array.

    Attempts a wgpu staging-buffer readback.  Falls back to a blank array on
    any failure so callers do not need to handle GPU-specific exceptions.
    """
    import numpy as np
    try:
        import wgpu
        device = tex._device if hasattr(tex, "_device") else None
        if device is None:
            return np.zeros((h, w, 4), dtype=np.uint8)

        bytes_per_row = w * 4
        # Align to wgpu's 256-byte row alignment requirement
        aligned_bpr = ((bytes_per_row + 255) // 256) * 256
        buf_size = aligned_bpr * h

        staging = device.create_buffer(size=buf_size,
                                       usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ)
        encoder = device.create_command_encoder()
        encoder.copy_texture_to_buffer(
            {"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
            {"buffer": staging, "offset": 0, "bytes_per_row": aligned_bpr, "rows_per_image": h},
            (w, h, 1),
        )
        device.queue.submit([encoder.finish()])
        staging.map_sync(wgpu.MapMode.READ)
        raw = staging.read_mapped()
        staging.unmap()

        # Strip alignment padding row by row
        rows = []
        for row in range(h):
            start = row * aligned_bpr
            rows.append(np.frombuffer(raw[start: start + bytes_per_row], dtype=np.uint8).copy())
        return np.stack(rows).reshape(h, w, 4)
    except Exception:
        return np.zeros((h, w, 4), dtype=np.uint8)


_VALID_BLEND_MODES = frozenset({"normal", "additive", "multiply", "alpha", "replace"})


class Layer:
    def __init__(self, name: str = "Layer", mode: str = "2D",
                 z_order: int = 0, blend_mode: str = "normal",
                 resolution: tuple[int, int] = (1280, 720),
                 clear_color: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)):
        validate_str("name", "Layer", name)
        validate_layer_mode("mode", "Layer", mode)
        if blend_mode not in _VALID_BLEND_MODES:
            raise ValueError(
                f"Layer: blend_mode must be one of {sorted(_VALID_BLEND_MODES)}; "
                f"got {blend_mode!r}"
            )
        self.name: str = name
        self.mode: str = mode
        self.entity: Entity | None = None

        # Visual texture (wgpu.Texture when GPU-resident, None otherwise)
        self.visual_texture: Any = None
        # Data storage buffer (wgpu.Buffer, stride = struct stride × width × height)
        self.data_buffer: Any = None

        # CPU-side image data (always available when RAM/GPU-resident)
        self._image_data: np.ndarray | None = None   # shape (H, W, 4) uint8
        self._data_array: np.ndarray | None = None   # shape (H, W, N) float32

        # DDD1 hybrid-layer state
        # render_target is a wgpu.Texture allocated by allocate_render_target();
        # None until the GPU device is available.
        self.render_target: Any = None
        self.depth_target: Any = None  # only populated for 3D layers
        self.z_order: int = int(z_order)
        self.blend_mode: str = blend_mode  # normal|additive|multiply|alpha|replace
        self.resolution: tuple[int, int] = tuple(resolution)  # type: ignore[assignment]
        self.clear_color: tuple[float, float, float, float] = tuple(clear_color)  # type: ignore[assignment]
        # Format string overridable by subclasses ("rgba8unorm" / "rgba16float").
        self._render_target_format: str = "rgba8unorm"
        # Depth format for 3D layers ("depth24plus"); 2D layers stay None.
        self._depth_format: str | None = None
        # Track the resolution the current render_target was allocated at
        # so allocate_render_target() can detect changes and recreate.
        self._allocated_resolution: tuple[int, int] | None = None

        self.alpha_threshold: float = 0.0
        self.visible: bool = True
        self.opacity: float = 1.0

        # Maps image channels to struct field names
        # Default: R→r, G→g, B→b, A→opacity
        self.channel_map: dict[str, str] = {
            "R": "visual_red",
            "G": "visual_green",
            "B": "visual_blue",
            "A": "opacity",
        }

        self._ram_pixel_data: Any = None  # structured pixel data (residency system)

        self.lighting: "LightingContext | None" = None
        # None = inherit scene-level LightingSystem (existing behaviour, no regression)

        self.mesh_geometry: "GpuMesh | None" = None
        self.mesh_material: "PbrMaterial | None" = None

        self._scripts: list = []
        self._post_process: list = []  # per-layer post-process chain (M10)

        # CPU-side reference to a MeshRenderer; set by the engine when 3D draw begins
        self._renderer = None

        if self.mode == "3D":
            self._ensure_3d_loaded()

    def _ensure_3d_loaded(self) -> None:
        if self.mode == "3D":
            try:
                from pharos_engine.gpu import mesh_pipeline  # noqa: F401
            except ImportError:
                pass  # 3D extra not installed — pipeline is None, will error on use

    @classmethod
    def from_image(cls, path: str | Path, name: str | None = None) -> "Layer":
        validate_existing_file_path("path", "Layer.from_image", path)
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        arr = np.asarray(img, dtype=np.uint8)
        inst = cls(name=name or Path(path).stem)
        inst._image_data = arr
        return inst

    @classmethod
    def blank(cls, width: int, height: int, name: str = "Layer", **kwargs) -> "Layer":
        validate_positive_int("width", "Layer.blank", width)
        validate_positive_int("height", "Layer.blank", height)
        inst = cls(name=name, **kwargs)
        inst._image_data = np.zeros((height, width, 4), dtype=np.uint8)
        return inst

    @property
    def size(self) -> tuple[int, int] | None:
        if self._image_data is not None:
            h, w = self._image_data.shape[:2]
            return (w, h)
        return None

    def tick(self, dt: float) -> None:
        for script in self._scripts:
            if hasattr(script, "on_tick"):
                script.on_tick(self, dt)

    def attach_script(self, script) -> None:
        self._scripts.append(script)

    # ------------------------------------------------------------------
    # WP-4.3  Cross-layer baking: 3D → 2D
    # ------------------------------------------------------------------

    def bake_to_2d(self, size: tuple[int, int], camera=None) -> "Layer":
        """Render this 3D layer to a new 2D Layer (RGBA texture).

        Returns a new Layer(mode="2D") containing the baked image.
        Requires this layer to have mode="3D" and a GPU context to be active.

        Args:
            size: (width, height) of the output texture.
            camera: optional camera override; defaults to orthographic front view.
        """
        size = validate_positive_size_2tuple("size", "Layer.bake_to_2d", size)
        if self.mode != "3D":
            raise ValueError("bake_to_2d() requires a 3D-mode Layer")

        w, h = size
        try:
            from pharos_engine.gpu.mesh_renderer import MeshRenderer  # noqa: F401
            if self._renderer is None:
                return Layer.blank(w, h, name=f"{self.name}_baked")
            tex = self._renderer.render_to_texture(w, h)
            data = _readback_texture(tex, w, h)
            baked = Layer.blank(w, h, name=f"{self.name}_baked")
            baked._image_data = data
            return baked
        except Exception:
            return Layer.blank(w, h, name=f"{self.name}_baked")

    # ------------------------------------------------------------------
    # WP-4.4  Cross-layer baking: 2D heightmap → 3D mesh displacement
    # ------------------------------------------------------------------

    def apply_heightmap(self, layer_2d: "Layer", scale: float = 1.0) -> None:
        """Use pixel luminance from a 2D layer to displace mesh vertex Z positions.

        Bright pixels → high Z; dark pixels → low Z.
        Modifies self.mesh_geometry.vertices in place (CPU-side).
        The mesh must be uploaded again (or the GPU buffers refreshed) after this call.

        Args:
            layer_2d: source 2D layer whose luminance drives displacement.
            scale: multiplier applied to the [0, 1] luminance before adding to Z.
        """
        validate_layer_arg("layer_2d", "Layer.apply_heightmap", layer_2d)
        validate_finite_float("scale", "Layer.apply_heightmap", scale)
        if self.mode != "3D":
            raise ValueError("apply_heightmap() requires a 3D-mode Layer")
        if self.mesh_geometry is None:
            return

        img = getattr(layer_2d, "_image_data", None)
        if img is None:
            return

        img_h, img_w = img.shape[:2]
        lum = (
            img[:, :, 0].astype(float) * 0.299
            + img[:, :, 1].astype(float) * 0.587
            + img[:, :, 2].astype(float) * 0.114
        ) / 255.0

        verts = self.mesh_geometry._vertices
        for v in verts:
            u, tex_v = v.uv
            px = min(int(u * img_w), img_w - 1)
            py = min(int(tex_v * img_h), img_h - 1)
            displacement = float(lum[py, px]) * scale
            x, y, z = v.position
            v.position = (x, y, z + displacement)

        # Invalidate GPU buffers so the next upload re-uploads updated data
        self.mesh_geometry._vertex_buf = None

    # ------------------------------------------------------------------
    # WP-4.5  Cross-layer baking: 2D image → 3D normal map
    # ------------------------------------------------------------------

    def apply_normal_map(self, layer_2d: "Layer") -> None:
        """Store a 2D layer as the normal map texture for this 3D layer's material.

        If mesh_material is None, creates a default PbrMaterial.
        Stores the layer's image data path in material.normal_map.

        Args:
            layer_2d: source 2D layer used as the normal map.
        """
        if self.mode != "3D":
            raise ValueError("apply_normal_map() requires a 3D-mode Layer")

        from pharos_engine.gpu.pbr_material import PbrMaterial
        if self.mesh_material is None:
            self.mesh_material = PbrMaterial()

        src = getattr(layer_2d, "_source_path", None)
        if src is not None:
            from pathlib import Path
            self.mesh_material.normal_map = Path(src)

    # ------------------------------------------------------------------
    # WP-4.6  Cross-layer baking: 2D image → 3D albedo texture
    # ------------------------------------------------------------------

    def apply_albedo(self, layer_2d: "Layer") -> None:
        """Store a 2D layer as the albedo texture for this 3D layer's material.

        If mesh_material is None, creates a default PbrMaterial.
        Stores the layer's image data path in material.albedo_texture.

        Args:
            layer_2d: source 2D layer used as the albedo (base colour) texture.
        """
        if self.mode != "3D":
            raise ValueError("apply_albedo() requires a 3D-mode Layer")

        from pharos_engine.gpu.pbr_material import PbrMaterial
        if self.mesh_material is None:
            self.mesh_material = PbrMaterial()

        src = getattr(layer_2d, "_source_path", None)
        if src is not None:
            from pathlib import Path
            self.mesh_material.albedo_texture = Path(src)

    # ------------------------------------------------------------------
    # DDD1  Hybrid 2D+3D layer stacking — render_target allocation
    # ------------------------------------------------------------------

    def allocate_render_target(self, device: Any) -> None:
        """Create a wgpu render-target texture (and depth target for 3D layers).

        The texture is bound with USAGE = TEXTURE_BINDING | RENDER_ATTACHMENT
        | COPY_SRC so it can be sampled by other layers (buffer sharing)
        and read back for verification.

        Idempotent — if a render_target already exists at the current
        ``resolution``, no work is done.  If ``resolution`` has changed since
        the last allocation, the texture is recreated.

        wgpu is soft-imported; when the ``wgpu`` package is unavailable this
        method delegates to the ``device`` mock (test / headless CI use).
        """
        if device is None:
            return

        # Idempotency check
        if (
            self.render_target is not None
            and self._allocated_resolution == self.resolution
        ):
            return

        w, h = self.resolution
        # Prefer wgpu enum constants when the module is available, falling
        # back to the string names understood by test doubles.
        try:
            import wgpu as _wgpu
            fmt_enum = getattr(_wgpu.TextureFormat, self._render_target_format,
                               self._render_target_format)
            usage = (
                _wgpu.TextureUsage.TEXTURE_BINDING
                | _wgpu.TextureUsage.RENDER_ATTACHMENT
                | _wgpu.TextureUsage.COPY_SRC
            )
            depth_fmt_enum = None
            if self._depth_format is not None:
                depth_fmt_enum = getattr(_wgpu.TextureFormat, self._depth_format,
                                         self._depth_format)
                depth_usage = (
                    _wgpu.TextureUsage.RENDER_ATTACHMENT
                    | _wgpu.TextureUsage.TEXTURE_BINDING
                )
            else:
                depth_usage = None
        except Exception:
            fmt_enum = self._render_target_format
            usage = (
                (1 << 2)  # TEXTURE_BINDING
                | (1 << 4)  # RENDER_ATTACHMENT
                | (1 << 0)  # COPY_SRC
            )
            depth_fmt_enum = self._depth_format
            depth_usage = (1 << 4) | (1 << 2) if self._depth_format else None

        self.render_target = device.create_texture(
            size=(w, h, 1),
            format=fmt_enum,
            usage=usage,
            label=f"{self.name}:render_target",
        )
        self._allocated_resolution = self.resolution

        if self._depth_format is not None:
            self.depth_target = device.create_texture(
                size=(w, h, 1),
                format=depth_fmt_enum,
                usage=depth_usage,
                label=f"{self.name}:depth_target",
            )

    def get_view_for_sampling(self) -> Any:
        """Return a wgpu.TextureView other layers can bind & sample from.

        Returns ``None`` if ``allocate_render_target`` has not been called.
        The view is the buffer-sharing hook that lets a 2D layer sample
        the output of a 3D layer (and vice versa).
        """
        if self.render_target is None:
            return None
        return self.render_target.create_view()

    # ------------------------------------------------------------------
    # DDD2  Cross-layer buffer sampling protocol
    # ------------------------------------------------------------------

    def sample_from(
        self,
        other_layer: "Layer",
        uniform_name: str = "u_source_layer",
        filter: str = "linear",
        address_mode: str = "clamp",
    ):
        """Build a :class:`LayerSampleBinding` letting this layer sample
        ``other_layer``'s render target inside a shader.

        Works both directions — ``layer_2d.sample_from(layer_3d)`` for a 2D
        post-process pass over a 3D scene, and ``layer_3d.sample_from(layer_2d)``
        for using a live 2D texture on a 3D mesh.
        """
        from pharos_engine.render.layer_sampling import make_layer_sample_binding

        return make_layer_sample_binding(
            layer=other_layer,
            uniform_name=uniform_name,
            filter=filter,
            address_mode=address_mode,
        )


class Layer2D(Layer):
    """Layer subclass for 2D pixel-art rendering. mode is always '2D'.

    Convenience wrapper around ``Layer(mode="2D")``.  Auto-configures:

    * An orthographic :class:`pharos_engine.camera.Camera` sized to the
      layer's pixel dimensions.
    * A ``rgba8unorm`` ``render_target`` format (allocated on first
      ``allocate_render_target(device)`` call).
    """
    def __init__(self, name: str = "layer", width: int = 64, height: int = 64,
                 z_order: int = 0, blend_mode: str = "normal"):
        validate_positive_int("width", "Layer2D", width)
        validate_positive_int("height", "Layer2D", height)
        super().__init__(
            name=name, mode="2D",
            z_order=z_order, blend_mode=blend_mode,
            resolution=(width, height),
        )
        # 8-bit LDR is the standard 2D pixel-art format
        self._render_target_format = "rgba8unorm"
        # Pre-allocate image data
        self._image_data = np.zeros((height, width, 4), dtype=np.uint8)
        # Orthographic 2D camera aligned with pixel resolution
        try:
            from pharos_engine.camera import Camera
            self.camera = Camera(position=(0.0, 0.0), zoom=1.0)
            self.camera._viewport_size = (width, height)
        except Exception:
            self.camera = None

    @classmethod
    def from_image(cls, path, name: str | None = None) -> "Layer2D":
        """Create a Layer2D from an image file."""
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        arr = np.asarray(img, dtype=np.uint8)
        h, w = arr.shape[:2]
        inst = cls(name=name or Path(path).stem, width=w, height=h)
        inst._image_data = arr
        return inst

    @classmethod
    def blank(cls, width: int, height: int, name: str = "layer") -> "Layer2D":
        return cls(name=name, width=width, height=height)

    # ------------------------------------------------------------------
    # DDD2  Post-process pattern: 2D layer samples another layer's target
    # ------------------------------------------------------------------

    def apply_post_process_from(
        self,
        source_layer: "Layer",
        shader_wgsl_path: str | Path | None = None,
        blend_mode: str = "alpha",
    ):
        """Register a post-process pass that samples ``source_layer``.

        Typical usage: ``layer_2d.apply_post_process_from(layer_3d, "outline.wgsl")``
        — the 2D layer samples the 3D scene render, runs a fullscreen shader
        over it, and writes into ``self.render_target``. This is the
        "sample 3D, draw 2D overlay on top" flow.
        """
        from pharos_engine.render.layer_sampling import apply_post_process_from as _apply

        return _apply(
            target_layer=self,
            source_layer=source_layer,
            shader_wgsl_path=shader_wgsl_path,
            blend_mode=blend_mode,
        )


@dataclass
class Camera3D:
    """Minimal 3D camera used by :class:`Layer3D` for its render pass.

    All values are floats.  ``position`` and ``look_at`` are XYZ world-space
    coordinates.  ``fov_deg`` is the vertical field of view in degrees.
    """
    position: tuple[float, float, float] = (0.0, 0.0, 5.0)
    look_at: tuple[float, float, float] = (0.0, 0.0, 0.0)
    fov_deg: float = 60.0
    near: float = 0.1
    far: float = 1000.0


class Layer3D(Layer):
    """Layer subclass for 3D mesh rendering. mode is always '3D'.

    Convenience wrapper around ``Layer(mode="3D")``.  Auto-configures:

    * A :class:`Camera3D` ``camera_3d`` (perspective).
    * A HDR ``rgba16float`` ``render_target`` format.
    * A ``depth24plus`` ``depth_target`` allocated alongside the colour
      target on ``allocate_render_target(device)``.
    * A ``bodies`` list of :class:`World3D` body handles that belong to
      this layer.
    """
    def __init__(self, name: str = "layer",
                 z_order: int = 0, blend_mode: str = "normal",
                 resolution: tuple[int, int] = (1280, 720)):
        super().__init__(
            name=name, mode="3D",
            z_order=z_order, blend_mode=blend_mode,
            resolution=resolution,
        )
        # HDR format so bright emissives + tonemapping downstream Just Work.
        self._render_target_format = "rgba16float"
        # Depth buffer format for 3D depth testing.
        self._depth_format = "depth24plus"
        # Camera & body list — DDD1 additions.
        self.camera_3d: Camera3D | None = Camera3D()
        self.bodies: list[int] = []  # World3D body_id handles
        # "unlit" | "lit" | "lit_with_gbuffer" — drives the renderer's
        # lighting pass. Default unlit so existing 3D layers behave as before.
        self.lighting_mode: str = "unlit"
        self._gbuffer_target: "Layer | None" = None

    @property
    def gbuffer_target(self) -> "Layer | None":
        return self._gbuffer_target

    @gbuffer_target.setter
    def gbuffer_target(self, layer) -> None:
        self._gbuffer_target = layer
        # Setting a target switches mode to defer_2d (2D lighting layer
        # receives the G-buffer data); a None target leaves the mode
        # untouched per existing-test contract.
        if layer is not None:
            self.lighting_mode = "defer_2d"

    @property
    def mesh(self):
        return self.mesh_geometry

    @mesh.setter
    def mesh(self, value):
        self.mesh_geometry = value

    @property
    def material(self):
        return self.mesh_material

    @material.setter
    def material(self, value):
        self.mesh_material = value

    # ------------------------------------------------------------------
    # DDD2  Live-2D-as-3D-texture pattern
    # ------------------------------------------------------------------

    def use_layer_as_texture(
        self,
        source_layer: "Layer",
        uniform_slot: str,
        filter: str = "linear",
        address_mode: str = "clamp",
    ):
        """Bind another layer's render target as a texture 3D meshes here can
        sample under WGSL binding ``uniform_slot``.

        Enables: "use a live 2D drawing as the texture on a 3D cube."
        Returns a :class:`LayerTextureBinding` that the renderer picks up
        when it builds the mesh material bind group.
        """
        from pharos_engine.render.layer_sampling import use_layer_as_texture as _use

        return _use(
            target_layer=self,
            source_layer=source_layer,
            uniform_slot=uniform_slot,
            filter=filter,
            address_mode=address_mode,
        )


class LayerDataBuffer(Layer2D):
    """Layer2D that also carries per-pixel struct data for compute shaders."""
    def __init__(self, name: str, width: int, height: int, struct_fields: list[str]):
        struct_fields = validate_struct_fields(
            "struct_fields", "LayerDataBuffer", struct_fields
        )
        super().__init__(name=name, width=width, height=height)
        self.struct_fields = struct_fields
        n = len(struct_fields)
        self._data_array = np.zeros((height, width, n), dtype=np.float32)

    def get_field(self, field: str):
        idx = self.struct_fields.index(field)
        return self._data_array[:, :, idx]

    def set_field(self, field: str, values):
        idx = self.struct_fields.index(field)
        self._data_array[:, :, idx] = values
