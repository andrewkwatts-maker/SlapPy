"""SVGF denoiser — spatiotemporal variance-guided filtering for noisy GI."""
from __future__ import annotations
from pathlib import Path
import numpy as np

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"

# SVGF parameters (matching Nova3D svgf_*.comp defaults)
PHI_COLOR      = 10.0
PHI_NORMAL     = 128.0
PHI_DEPTH      = 1.0
SIGMA_LUM      = 4.0
TEMPORAL_ALPHA = 0.1   # blend weight for new frame (0.1 = keep 90% history)
MAX_HISTORY    = 32


class SVGFDenoiser:
    """5-pass SVGF: temporal → variance → wavelet×5 → modulate.

    Based on Nova3D svgf_temporal.comp, svgf_variance.comp, svgf_wavelet.comp,
    svgf_modulate.comp with standard à-trous parameters.
    """

    def __init__(self, width: int = 0, height: int = 0):
        self.width = width
        self.height = height
        self._initialized = False
        self._gpu = None

    def init_gpu(self, gpu, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self._gpu = gpu
        try:
            import wgpu
            tex_usage = (
                wgpu.TextureUsage.STORAGE_BINDING |
                wgpu.TextureUsage.TEXTURE_BINDING |
                wgpu.TextureUsage.COPY_SRC |
                wgpu.TextureUsage.COPY_DST
            )
            # Accumulated color + history for temporal pass
            self._accum_color = gpu.device.create_texture(
                size=(width, height, 1), format=wgpu.TextureFormat.rgba16float, usage=tex_usage)
            self._accum_moments = gpu.device.create_texture(
                size=(width, height, 1), format=wgpu.TextureFormat.rg32float, usage=tex_usage)
            self._history_len = gpu.device.create_texture(
                size=(width, height, 1), format=wgpu.TextureFormat.r16float, usage=tex_usage)
            # Variance texture
            self._variance = gpu.device.create_texture(
                size=(width, height, 1), format=wgpu.TextureFormat.r16float, usage=tex_usage)
            # Ping-pong for wavelet passes
            self._wavelet_a = gpu.device.create_texture(
                size=(width, height, 1), format=wgpu.TextureFormat.rgba16float, usage=tex_usage)
            self._wavelet_b = gpu.device.create_texture(
                size=(width, height, 1), format=wgpu.TextureFormat.rgba16float, usage=tex_usage)
            self._initialized = True
        except Exception as e:
            print(f"[SVGFDenoiser] GPU init failed: {e}")

    def denoise(self, encoder, noisy_color, gbuffer_pos, gbuffer_normal,
                gbuffer_depth, albedo, output_tex) -> None:
        """Run full SVGF denoising pipeline."""
        if not self._initialized:
            return
        try:
            self._pass_temporal(encoder, noisy_color, gbuffer_pos, gbuffer_normal, gbuffer_depth)
            self._pass_variance(encoder)
            # 5 à-trous wavelet passes with step widths 1, 2, 4, 8, 16
            wavelet_in = self._accum_color
            wavelet_out = self._wavelet_a
            for iteration in range(5):
                step_width = 1 << iteration  # 1, 2, 4, 8, 16
                self._pass_wavelet(encoder, wavelet_in, wavelet_out,
                                   gbuffer_pos, gbuffer_normal, gbuffer_depth,
                                   iteration, step_width)
                # Ping-pong
                wavelet_in = wavelet_out
                wavelet_out = self._wavelet_b if iteration % 2 == 0 else self._wavelet_a
            self._pass_modulate(encoder, wavelet_in, albedo, output_tex)
        except Exception as e:
            print(f"[SVGFDenoiser] denoise error: {e}")

    def _run_pass(self, encoder, shader_name: str, entries: list, wx: int, wy: int) -> None:
        shader_path = _SHADER_DIR / shader_name
        if not shader_path.exists():
            return
        try:
            import wgpu
            module = self._gpu.device.create_shader_module(
                code=shader_path.read_text(encoding="utf-8"))
            pipeline = self._gpu.device.create_compute_pipeline(
                layout="auto", compute={"module": module, "entry_point": "main"})
            bg = self._gpu.device.create_bind_group(
                layout=pipeline.get_bind_group_layout(0), entries=entries)
            cp = encoder.begin_compute_pass()
            cp.set_pipeline(pipeline)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups(wx, wy)
            cp.end()
        except Exception:
            pass

    def _make_svgf_uniforms(self, **kwargs) -> "wgpu.GPUBuffer":
        import wgpu
        data = np.array([
            kwargs.get("phi_color", PHI_COLOR),
            kwargs.get("phi_normal", PHI_NORMAL),
            kwargs.get("phi_depth", PHI_DEPTH),
            kwargs.get("sigma_lum", SIGMA_LUM),
            kwargs.get("temporal_alpha", TEMPORAL_ALPHA),
            kwargs.get("iteration", 0),
            kwargs.get("step_width", 1),
            0.0,  # padding
        ], dtype=np.float32)
        buf = self._gpu.device.create_buffer(
            size=data.nbytes,
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
        self._gpu.device.queue.write_buffer(buf, 0, data)
        return buf

    def _pass_temporal(self, encoder, noisy, pos, normal, depth):
        wx = (self.width + 7) // 8
        wy = (self.height + 7) // 8
        ub = self._make_svgf_uniforms()
        self._run_pass(encoder, "svgf_temporal.wgsl", [
            {"binding": 0, "resource": noisy.create_view()},
            {"binding": 1, "resource": pos.create_view()},
            {"binding": 2, "resource": normal.create_view()},
            {"binding": 3, "resource": depth.create_view()},
            {"binding": 4, "resource": self._accum_color.create_view()},
            {"binding": 5, "resource": self._accum_moments.create_view()},
            {"binding": 6, "resource": self._history_len.create_view()},
            {"binding": 7, "resource": {"buffer": ub, "offset": 0, "size": ub.size}},
        ], wx, wy)

    def _pass_variance(self, encoder):
        wx = (self.width + 7) // 8
        wy = (self.height + 7) // 8
        ub = self._make_svgf_uniforms()
        self._run_pass(encoder, "svgf_variance.wgsl", [
            {"binding": 0, "resource": self._accum_color.create_view()},
            {"binding": 1, "resource": self._accum_moments.create_view()},
            {"binding": 2, "resource": self._history_len.create_view()},
            {"binding": 3, "resource": self._variance.create_view()},
            {"binding": 4, "resource": {"buffer": ub, "offset": 0, "size": ub.size}},
        ], wx, wy)

    def _pass_wavelet(self, encoder, src, dst, pos, normal, depth, iteration, step_width):
        wx = (self.width + 7) // 8
        wy = (self.height + 7) // 8
        ub = self._make_svgf_uniforms(iteration=float(iteration), step_width=float(step_width))
        self._run_pass(encoder, "svgf_wavelet.wgsl", [
            {"binding": 0, "resource": src.create_view()},
            {"binding": 1, "resource": self._variance.create_view()},
            {"binding": 2, "resource": self._history_len.create_view()},
            {"binding": 3, "resource": pos.create_view()},
            {"binding": 4, "resource": normal.create_view()},
            {"binding": 5, "resource": depth.create_view()},
            {"binding": 6, "resource": dst.create_view()},
            {"binding": 7, "resource": {"buffer": ub, "offset": 0, "size": ub.size}},
        ], wx, wy)

    def _pass_modulate(self, encoder, filtered, albedo, output):
        wx = (self.width + 7) // 8
        wy = (self.height + 7) // 8
        self._run_pass(encoder, "svgf_modulate.wgsl", [
            {"binding": 0, "resource": filtered.create_view()},
            {"binding": 1, "resource": albedo.create_view()},
            {"binding": 2, "resource": output.create_view()},
        ], wx, wy)
