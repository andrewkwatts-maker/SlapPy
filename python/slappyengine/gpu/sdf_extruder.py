"""SdfExtruder — generates a GpuMesh from a 2D silhouette layer using sdf_3d_extrude.wgsl."""
from __future__ import annotations
from pathlib import Path
import numpy as np

SHADER_PATH = Path(__file__).parent.parent.parent.parent / "shaders" / "sdf_3d_extrude.wgsl"


class SdfExtruder:
    """Converts a 2D pixel mask into a GpuMesh using GPU extrusion.

    Falls back to CPU generation if GPU is not available.

    GPU path
    --------
    When a ``GpuContext`` (wgpu device) is passed at construction the
    extrusion is dispatched as a compute shader (``sdf_3d_extrude.wgsl``).
    The shader atomically claims slots in a pre-allocated storage buffer and
    writes packed f32 vertex data directly on the GPU.  After the dispatch,
    ``readback()`` maps the buffer and constructs a :class:`~SlapPyEngine.gpu.mesh.GpuMesh`
    from the returned bytes.  The GPU path is O(pixels) and fully parallel.

    CPU fallback
    ------------
    When no GPU context is available (``gpu=None``), :meth:`_extrude_cpu`
    iterates over the mask in Python/NumPy, emitting quads face-by-face.
    The algorithm is equivalent to the WGSL shader; see the comment block at
    the top of ``shaders/sdf_3d_extrude.wgsl`` for a detailed description.
    """

    def __init__(self, gpu=None) -> None:
        self._gpu = gpu  # GpuContext | None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def extrude(
        self,
        mask: np.ndarray,
        depth: float = 1.0,
        scale: float = 1.0,
        threshold: float = 0.5,
    ) -> "GpuMesh":
        """Generate a 3D slab mesh from a 2D alpha mask.

        Parameters
        ----------
        mask:
            2-D array of shape ``(H, W)`` — or 3-D ``(H, W, C)`` in which case
            channel 0 is used.  Values may be ``uint8`` (0–255) or ``float32``
            (0.0–1.0); both are normalised to ``[0.0, 1.0]`` before processing.
        depth:
            Z thickness (world units) of the extruded slab.  The slab is
            centred at Z = 0, so it spans ``[-depth/2, +depth/2]``.
        scale:
            World-unit size of each pixel in XY.  The whole slab is centred at
            the XY origin.
        threshold:
            Alpha value (in ``[0.0, 1.0]``) above which a pixel is considered
            solid.  Pixels at or below this value produce no geometry.

        Returns
        -------
        GpuMesh
            CPU-side mesh ready for ``upload(device)``.
        """
        # Normalise mask to float32 in [0, 1]
        if mask.dtype == np.uint8:
            mask_f = mask.astype(np.float32) / 255.0
        else:
            mask_f = np.asarray(mask, dtype=np.float32)

        # Collapse colour channels to a single alpha/luminance plane
        if mask_f.ndim == 3:
            if mask_f.shape[2] == 4:
                mask_f = mask_f[:, :, 3]   # RGBA — use alpha channel
            else:
                mask_f = mask_f[:, :, 0]   # any other — use first channel
        elif mask_f.ndim == 1:
            mask_f = mask_f[np.newaxis, :]  # degenerate single-row mask

        # GPU path (not yet wired to a specific backend — reserved for future use)
        if self._gpu is not None:
            return self._extrude_gpu(mask_f, depth, scale, threshold)

        return self._extrude_cpu(mask_f, depth, scale, threshold)

    # ------------------------------------------------------------------
    # CPU fallback
    # ------------------------------------------------------------------

    def _extrude_cpu(
        self,
        mask: np.ndarray,
        depth: float,
        scale: float,
        threshold: float,
    ) -> "GpuMesh":
        """CPU fallback — generates the mesh from the mask on the CPU.

        Mirrors the WGSL shader algorithm exactly so that results are
        byte-for-byte equivalent (modulo floating-point ordering).
        """
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex

        h, w = mask.shape[:2]
        vertices: list[MeshVertex] = []
        indices: list[int] = []

        def add_quad(
            v0: tuple, v1: tuple, v2: tuple, v3: tuple,
            normal: tuple,
            tangent: tuple = (1.0, 0.0, 0.0, 1.0),
        ) -> None:
            """Append 4 vertices + 6 indices for one quad (two CCW triangles)."""
            base = len(vertices)
            uvs = [(0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)]
            for pos, uv in zip([v0, v1, v2, v3], uvs):
                vertices.append(MeshVertex(position=pos, normal=normal, uv=uv, tangent=tangent))
            indices.extend([base, base + 1, base + 2, base, base + 2, base + 3])

        def solid(r: int, c: int) -> bool:
            if r < 0 or r >= h or c < 0 or c >= w:
                return False
            return float(mask[r, c]) >= threshold

        half_w = w / 2.0
        half_h = h / 2.0
        z_top = depth / 2.0
        z_bot = -depth / 2.0

        for r in range(h):
            for c in range(w):
                if not solid(r, c):
                    continue

                x0 = (c - half_w) * scale
                y0 = (r - half_h) * scale
                x1 = x0 + scale
                y1 = y0 + scale

                # Top face (z+, normal = +Z, tangent = +X)
                add_quad(
                    (x0, y0, z_top), (x1, y0, z_top),
                    (x1, y1, z_top), (x0, y1, z_top),
                    normal=(0.0, 0.0, 1.0),
                    tangent=(1.0, 0.0, 0.0, 1.0),
                )

                # Bottom face (z-, normal = -Z, tangent = -X)
                add_quad(
                    (x0, y1, z_bot), (x1, y1, z_bot),
                    (x1, y0, z_bot), (x0, y0, z_bot),
                    normal=(0.0, 0.0, -1.0),
                    tangent=(-1.0, 0.0, 0.0, 1.0),
                )

                # North face — row-1 is empty (normal = -Y, tangent = +X)
                if not solid(r - 1, c):
                    add_quad(
                        (x0, y0, z_bot), (x1, y0, z_bot),
                        (x1, y0, z_top), (x0, y0, z_top),
                        normal=(0.0, -1.0, 0.0),
                        tangent=(1.0, 0.0, 0.0, 1.0),
                    )

                # South face — row+1 is empty (normal = +Y, tangent = -X)
                if not solid(r + 1, c):
                    add_quad(
                        (x1, y1, z_bot), (x0, y1, z_bot),
                        (x0, y1, z_top), (x1, y1, z_top),
                        normal=(0.0, 1.0, 0.0),
                        tangent=(-1.0, 0.0, 0.0, 1.0),
                    )

                # West face — col-1 is empty (normal = -X, tangent = -Z)
                if not solid(r, c - 1):
                    add_quad(
                        (x0, y1, z_bot), (x0, y0, z_bot),
                        (x0, y0, z_top), (x0, y1, z_top),
                        normal=(-1.0, 0.0, 0.0),
                        tangent=(0.0, 0.0, -1.0, 1.0),
                    )

                # East face — col+1 is empty (normal = +X, tangent = +Z)
                if not solid(r, c + 1):
                    add_quad(
                        (x1, y0, z_bot), (x1, y1, z_bot),
                        (x1, y1, z_top), (x1, y0, z_top),
                        normal=(1.0, 0.0, 0.0),
                        tangent=(0.0, 0.0, 1.0, 1.0),
                    )

        return GpuMesh(vertices, indices)

    # ------------------------------------------------------------------
    # GPU path (stub — wires up when a real GpuContext is provided)
    # ------------------------------------------------------------------

    def _extrude_gpu(
        self,
        mask: np.ndarray,
        depth: float,
        scale: float,
        threshold: float,
    ) -> "GpuMesh":
        """GPU-accelerated extrusion via sdf_3d_extrude.wgsl.

        Requires ``self._gpu`` to expose:
          - ``device``       — wgpu GPUDevice
          - ``queue``        — wgpu GPUQueue
          - ``create_pipeline(shader_path, entry_point, bind_group_layout)``
        Falls back to CPU if the dispatch fails for any reason.
        """
        try:
            return self._extrude_gpu_impl(mask, depth, scale, threshold)
        except Exception:  # noqa: BLE001
            # Any GPU failure (missing extension, OOM, …) degrades gracefully.
            return self._extrude_cpu(mask, depth, scale, threshold)

    def _extrude_gpu_impl(
        self,
        mask: np.ndarray,
        depth: float,
        scale: float,
        threshold: float,
    ) -> "GpuMesh":
        import struct
        import wgpu
        from slappyengine.gpu.mesh import GpuMesh, MeshVertex

        device: wgpu.GPUDevice = self._gpu.device
        queue:  wgpu.GPUQueue  = self._gpu.queue

        h, w = mask.shape[:2]

        # Upload mask as an R32Float texture
        tex = device.create_texture(
            size=(w, h, 1),
            format=wgpu.TextureFormat.r32float,
            usage=wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.COPY_DST,
        )
        queue.write_texture(
            {"texture": tex, "mip_level": 0, "origin": (0, 0, 0)},
            mask.tobytes(),
            {"bytes_per_row": w * 4, "rows_per_image": h},
            (w, h, 1),
        )
        tex_view = tex.create_view()

        # Uniforms — 8 × f32 (32 bytes)
        uniforms_data = struct.pack(
            "2I6f",
            w, h,
            float(depth), float(scale), float(threshold),
            0.0, 0.0, 0.0,
        )
        uniforms_buf = device.create_buffer_with_data(
            data=uniforms_data,
            usage=wgpu.BufferUsage.UNIFORM,
        )

        # Output vertex buffer — worst case: every pixel emits 6 quads × 4 verts × 12 floats
        max_vertices = w * h * 6 * 4
        max_floats   = max_vertices * 12
        vertex_buf = device.create_buffer(
            size=max_floats * 4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC,
        )

        # Atomic vertex count (1 × u32)
        count_buf = device.create_buffer(
            size=4,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC,
        )

        # Load and compile the shader
        shader_src = SHADER_PATH.read_text(encoding="utf-8")
        shader_mod = device.create_shader_module(code=shader_src)

        # Build pipeline
        pipeline = device.create_compute_pipeline(
            layout="auto",
            compute={"module": shader_mod, "entry_point": "extrude_main"},
        )

        sampler = device.create_sampler()
        bind_group = device.create_bind_group(
            layout=pipeline.get_bind_group_layout(0),
            entries=[
                {"binding": 0, "resource": {"buffer": uniforms_buf}},
                {"binding": 1, "resource": tex_view},
                {"binding": 2, "resource": {"buffer": vertex_buf}},
                {"binding": 3, "resource": {"buffer": count_buf}},
            ],
        )

        # Dispatch
        dispatch_x = (w + 7) // 8
        dispatch_y = (h + 7) // 8
        encoder = device.create_command_encoder()
        pass_ = encoder.begin_compute_pass()
        pass_.set_pipeline(pipeline)
        pass_.set_bind_group(0, bind_group)
        pass_.dispatch_workgroups(dispatch_x, dispatch_y, 1)
        pass_.end()

        # Readback buffers
        rb_vertex = device.create_buffer(
            size=max_floats * 4,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
        )
        rb_count = device.create_buffer(
            size=4,
            usage=wgpu.BufferUsage.COPY_DST | wgpu.BufferUsage.MAP_READ,
        )
        encoder.copy_buffer_to_buffer(vertex_buf, 0, rb_vertex, 0, max_floats * 4)
        encoder.copy_buffer_to_buffer(count_buf,  0, rb_count,  0, 4)
        queue.submit([encoder.finish()])

        rb_count.map_sync(wgpu.MapMode.READ)
        vertex_count = struct.unpack("I", bytes(rb_count.read_mapped()))[0]
        rb_count.unmap()

        rb_vertex.map_sync(wgpu.MapMode.READ)
        raw = bytes(rb_vertex.read_mapped(0, vertex_count * 12 * 4))
        rb_vertex.unmap()

        # Decode raw float data into MeshVertex objects
        floats = struct.unpack(f"{vertex_count * 12}f", raw)
        vertices: list[MeshVertex] = []
        for i in range(vertex_count):
            base = i * 12
            vertices.append(MeshVertex(
                position=(floats[base],     floats[base + 1], floats[base + 2]),
                normal  =(floats[base + 3], floats[base + 4], floats[base + 5]),
                uv      =(floats[base + 6], floats[base + 7]),
                tangent =(floats[base + 8], floats[base + 9], floats[base + 10], floats[base + 11]),
            ))

        # Reconstruct indices: each group of 4 verts = one quad (two CCW triangles)
        indices: list[int] = []
        num_quads = vertex_count // 4
        for q in range(num_quads):
            b = q * 4
            indices.extend([b, b + 1, b + 2, b, b + 2, b + 3])

        return GpuMesh(vertices, indices)

    # ------------------------------------------------------------------
    # Convenience factory
    # ------------------------------------------------------------------

    @classmethod
    def from_layer(
        cls,
        layer_2d,
        depth: float = 1.0,
        scale: float = 1.0,
        threshold: float = 0.5,
        gpu=None,
    ) -> "GpuMesh":
        """Convenience: extrude directly from a 2D Layer's image data.

        Parameters
        ----------
        layer_2d:
            Any object with a ``_image_data`` attribute containing a NumPy
            array (H×W or H×W×C, uint8 or float32).  If the attribute is
            absent a unit quad is returned as a safe fallback.
        depth, scale, threshold:
            Forwarded to :meth:`extrude`.
        gpu:
            Optional ``GpuContext`` for the GPU code path.

        Returns
        -------
        GpuMesh
        """
        img = getattr(layer_2d, "_image_data", None)
        if img is None:
            from slappyengine.gpu.mesh import GpuMesh
            return GpuMesh.unit_quad()

        # Extract a single-channel mask
        if img.ndim == 3 and img.shape[2] == 4:
            mask = img[:, :, 3]          # RGBA — alpha channel
        elif img.ndim == 3:
            mask = img[:, :, 0]          # RGB / greyscale packed — red/luma
        else:
            mask = img                   # already 2-D

        extruder = cls(gpu=gpu)
        return extruder.extrude(mask, depth=depth, scale=scale, threshold=threshold)
