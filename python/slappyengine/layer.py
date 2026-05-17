from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TYPE_CHECKING
import numpy as np

if TYPE_CHECKING:
    from slappyengine.entity import Entity


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


class Layer:
    def __init__(self, name: str = "Layer", mode: str = "2D"):
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

        self.blend_mode: str = "normal"  # "normal"|"multiply"|"add"|"screen"
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
                from slappyengine.gpu import mesh_pipeline  # noqa: F401
            except ImportError:
                pass  # 3D extra not installed — pipeline is None, will error on use

    @classmethod
    def from_image(cls, path: str | Path, name: str | None = None) -> "Layer":
        from PIL import Image
        img = Image.open(path).convert("RGBA")
        arr = np.asarray(img, dtype=np.uint8)
        inst = cls(name=name or Path(path).stem)
        inst._image_data = arr
        return inst

    @classmethod
    def blank(cls, width: int, height: int, name: str = "Layer", **kwargs) -> "Layer":
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
        if self.mode != "3D":
            raise ValueError("bake_to_2d() requires a 3D-mode Layer")

        w, h = size
        try:
            from slappyengine.gpu.mesh_renderer import MeshRenderer  # noqa: F401
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

        from slappyengine.gpu.pbr_material import PbrMaterial
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

        from slappyengine.gpu.pbr_material import PbrMaterial
        if self.mesh_material is None:
            self.mesh_material = PbrMaterial()

        src = getattr(layer_2d, "_source_path", None)
        if src is not None:
            from pathlib import Path
            self.mesh_material.albedo_texture = Path(src)


class Layer2D(Layer):
    """Layer subclass for 2D pixel-art rendering. mode is always '2D'."""
    def __init__(self, name: str = "layer", width: int = 64, height: int = 64):
        super().__init__(name=name, mode="2D")
        # Pre-allocate image data
        self._image_data = np.zeros((height, width, 4), dtype=np.uint8)

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


class Layer3D(Layer):
    """Layer subclass for 3D mesh rendering. mode is always '3D'."""
    def __init__(self, name: str = "layer"):
        super().__init__(name=name, mode="3D")

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


class LayerDataBuffer(Layer2D):
    """Layer2D that also carries per-pixel struct data for compute shaders."""
    def __init__(self, name: str, width: int, height: int, struct_fields: list[str]):
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
