"""Image-Based Lighting — SH irradiance + split-sum specular (pre-filtered cubemap + BRDF LUT)."""
from __future__ import annotations
from pathlib import Path
from typing import Optional
import numpy as np

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"


class IBLSystem:
    """Manages IBL pre-integration: irradiance SH, pre-filtered env map, BRDF LUT.

    Diffuse IBL:  9-coefficient SH L2 irradiance (projected from HDR equirectangular)
    Specular IBL: Split-sum — pre-filtered env cubemap (mip per roughness) + BRDF LUT

    Usage:
        ibl = IBLSystem()
        ibl.init_gpu(gpu_ctx, width=1280, height=720)
        ibl.load_hdri("sky.hdr")   # optional — uses neutral sky if not provided
        # Each frame, bind ibl.irradiance_sh_buf + ibl.prefilter_tex + ibl.brdf_lut_tex
    """

    SH_COEFFS = 9          # L2 SH
    BRDF_LUT_SIZE = 512    # 512×512 split-sum BRDF LUT
    PREFILTER_MIPS = 8     # 256px base, 8 mip levels

    def __init__(self):
        self._gpu = None
        self._initialized = False
        # SH irradiance buffer: 9 × vec4 (RGB + pad) = 144 bytes
        self.irradiance_sh_buf = None
        # Pre-filtered env cubemap
        self.prefilter_tex = None
        # BRDF integration LUT
        self.brdf_lut_tex = None
        # Default neutral sky SH (flat white irradiance)
        self._default_sh = np.zeros(9 * 4, dtype=np.float32)
        self._default_sh[0] = 0.282095   # L0 Y0,0 constant

    def init_gpu(self, gpu, width: int, height: int) -> None:
        self._gpu = gpu
        try:
            import wgpu
            tex_usage = wgpu.TextureUsage.TEXTURE_BINDING | wgpu.TextureUsage.STORAGE_BINDING | wgpu.TextureUsage.COPY_DST
            # SH buffer: 9 coefficients × vec4 (float3 + pad)
            self.irradiance_sh_buf = gpu.device.create_buffer(
                size=self._default_sh.nbytes,
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            )
            gpu.device.queue.write_buffer(self.irradiance_sh_buf, 0, self._default_sh)
            # BRDF LUT: rg16float (GGX integration F0 scale + bias)
            self.brdf_lut_tex = gpu.device.create_texture(
                size=(self.BRDF_LUT_SIZE, self.BRDF_LUT_SIZE, 1),
                format=wgpu.TextureFormat.rg16float,
                mip_level_count=1,
                usage=tex_usage,
            )
            # Pre-filtered env: rgba16float, cube (6 faces), PREFILTER_MIPS mip levels
            self.prefilter_tex = gpu.device.create_texture(
                size=(256, 256, 6),
                format=wgpu.TextureFormat.rgba16float,
                mip_level_count=self.PREFILTER_MIPS,
                usage=tex_usage,
            )
            self._initialized = True
            # Bake the BRDF LUT immediately (only done once)
            self._bake_brdf_lut()
        except Exception as e:
            print(f"[IBLSystem] GPU init failed: {e}")

    def _bake_brdf_lut(self) -> None:
        """Dispatch brdf_lut.wgsl once to pre-compute split-sum BRDF LUT."""
        if not self._initialized:
            return
        shader_path = _SHADER_DIR / "brdf_lut.wgsl"
        if not shader_path.exists():
            return
        try:
            import wgpu
            module = self._gpu.device.create_shader_module(
                code=shader_path.read_text(encoding="utf-8"))
            pipeline = self._gpu.device.create_compute_pipeline(
                layout="auto",
                compute={"module": module, "entry_point": "main"},
            )
            bgl = pipeline.get_bind_group_layout(0)
            bg = self._gpu.device.create_bind_group(
                layout=bgl,
                entries=[
                    {"binding": 0, "resource": self.brdf_lut_tex.create_view()},
                ],
            )
            enc = self._gpu.device.create_command_encoder()
            cp = enc.begin_compute_pass()
            cp.set_pipeline(pipeline)
            cp.set_bind_group(0, bg)
            wx = (self.BRDF_LUT_SIZE + 7) // 8
            wy = (self.BRDF_LUT_SIZE + 7) // 8
            cp.dispatch_workgroups(wx, wy)
            cp.end()
            self._gpu.device.queue.submit([enc.finish()])
        except Exception:
            pass

    def load_hdri(self, path: str) -> None:
        """Load HDR equirectangular image, project to SH, pre-filter cubemap.

        Falls back to neutral sky if file not found or Pillow/numpy unavailable.
        """
        if not self._initialized:
            return
        try:
            from PIL import Image
            img = np.array(Image.open(path).convert("RGB"), dtype=np.float32) / 255.0
            # Project equirectangular to SH L2 (9 coefficients)
            sh = self._project_sh(img)
            self._gpu.device.queue.write_buffer(
                self.irradiance_sh_buf, 0,
                sh.astype(np.float32))
            # Prefilter env map (simplified: just write average color per mip)
            self._prefilter_env(img)
        except Exception as e:
            print(f"[IBLSystem] HDRI load failed ({e}), using neutral sky")

    def _project_sh(self, equirect: np.ndarray) -> np.ndarray:
        """Project equirectangular HDR image to SH L2 (9×4 floats)."""
        h, w = equirect.shape[:2]
        sh = np.zeros((9, 4), dtype=np.float64)
        # Sample spherical harmonics basis for each pixel
        for py in range(0, h, 4):  # stride for speed
            theta = np.pi * (py + 0.5) / h
            sin_theta = np.sin(theta)
            cos_theta = np.cos(theta)
            for px in range(0, w, 4):
                phi = 2.0 * np.pi * px / w
                x = sin_theta * np.cos(phi)
                y = sin_theta * np.sin(phi)
                z = cos_theta
                rgb = equirect[py, px].astype(np.float64)
                # SH L0
                sh[0, :3] += rgb * 0.282095 * sin_theta
                # SH L1
                sh[1, :3] += rgb * 0.488603 * y * sin_theta
                sh[2, :3] += rgb * 0.488603 * z * sin_theta
                sh[3, :3] += rgb * 0.488603 * x * sin_theta
                # SH L2
                sh[4, :3] += rgb * 1.092548 * x * y * sin_theta
                sh[5, :3] += rgb * 1.092548 * y * z * sin_theta
                sh[6, :3] += rgb * 0.315392 * (3*z*z - 1) * sin_theta
                sh[7, :3] += rgb * 1.092548 * x * z * sin_theta
                sh[8, :3] += rgb * 0.546274 * (x*x - y*y) * sin_theta
        # Normalize by pixel count and pi
        pixel_count = (h * w) / 16  # stride of 4
        sh[:, :3] *= (4.0 * np.pi / pixel_count)
        return sh.flatten().astype(np.float32)

    def _prefilter_env(self, equirect: np.ndarray) -> None:
        """Simple pre-filter: write average color to each mip level."""
        # Full cubemap prefilter requires the ibl_prefilter.wgsl shader
        # For now, write average color as fallback
        avg = equirect.mean(axis=(0, 1))
        data = np.zeros((256, 256, 4), dtype=np.float16)
        data[..., :3] = avg.astype(np.float16)
        data[..., 3] = 1.0
        if self.prefilter_tex is not None:
            try:
                self._gpu.device.queue.write_texture(
                    {"texture": self.prefilter_tex, "mip_level": 0, "origin": (0, 0, 0)},
                    data.tobytes(),
                    {"bytes_per_row": 256 * 8, "rows_per_image": 256},
                    (256, 256, 1),
                )
            except Exception:
                pass
