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
        # CPU temporal-history state (mirror of GPU accum_color / accum_moments /
        # history_len textures). None until the first ``denoise_numpy`` frame.
        self._cpu_history: dict | None = None

    # ------------------------------------------------------------------ CPU path

    def reset_history(self) -> None:
        """Clear the CPU temporal-accumulation history.

        Forces the next ``denoise_numpy`` call to treat its input as the first
        frame (no prior color/moments to blend against). Mirrors the GPU
        history-reset that happens implicitly on camera cut or window resize.
        """
        self._cpu_history = None

    def denoise_numpy(
        self,
        noisy: np.ndarray,
        normal: np.ndarray,
        depth: np.ndarray,
    ) -> np.ndarray:
        """CPU reference implementation of the SVGF denoiser.

        Faithful NumPy mirror of the four WGSL passes (temporal accumulation →
        variance estimation → 5 à-trous wavelet iterations) used for tests,
        headless examples, and GPU-less fallbacks.

        Parameters
        ----------
        noisy : (H, W, 3) float32
            Noisy radiance estimate for the current frame.
        normal : (H, W, 3) float32
            World-space surface normals (used for edge-stopping).
        depth : (H, W) float32
            Linear depth (used for edge-stopping).

        Returns
        -------
        (H, W, 3) float32 denoised radiance.
        """
        noisy = np.asarray(noisy, dtype=np.float32)
        normal = np.asarray(normal, dtype=np.float32)
        depth = np.asarray(depth, dtype=np.float32)
        if noisy.ndim != 3 or noisy.shape[-1] != 3:
            raise ValueError(f"noisy must be (H, W, 3); got {noisy.shape}")
        H, W, _ = noisy.shape

        # ---- Pass 1: Temporal accumulation (EMA blend) ----------------------
        lum_weights = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
        new_lum = (noisy * lum_weights).sum(-1)

        hist = self._cpu_history
        valid = hist is not None and hist["color"].shape == noisy.shape
        if valid:
            alpha = TEMPORAL_ALPHA
            accum_color = hist["color"] * (1.0 - alpha) + noisy * alpha
            accum_m1 = hist["m1"] * (1.0 - alpha) + new_lum * alpha
            accum_m2 = hist["m2"] * (1.0 - alpha) + (new_lum * new_lum) * alpha
            hist_len = np.minimum(hist["len"] + 1.0, float(MAX_HISTORY))
        else:
            accum_color = noisy.copy()
            accum_m1 = new_lum.copy()
            accum_m2 = (new_lum * new_lum).astype(np.float32)
            hist_len = np.ones((H, W), dtype=np.float32)

        # ---- Pass 2: Per-pixel luminance variance ---------------------------
        variance = np.maximum(accum_m2 - accum_m1 * accum_m1, 0.0).astype(np.float32)

        # ---- Pass 3: 5 à-trous wavelet iterations with edge-stopping --------
        # Match svgf_wavelet.wgsl: 3x3 Gaussian kernel, edge-stops on
        # luminance (variance-guided), normal (cos^phi_normal), depth (exp).
        kernel = np.array(
            [1, 2, 1, 2, 4, 2, 1, 2, 1], dtype=np.float32
        ).reshape(3, 3) / 16.0
        normal_n = normal / (np.linalg.norm(normal, axis=-1, keepdims=True) + 1e-6)

        filtered = accum_color
        for iteration in range(5):
            step = 1 << iteration
            center_lum = (filtered * lum_weights).sum(-1)
            phi_l = SIGMA_LUM * np.sqrt(variance) + 1e-6
            num = np.zeros_like(filtered)
            den = np.zeros_like(center_lum)
            for ky in range(3):
                for kx in range(3):
                    dy = (ky - 1) * step
                    dx = (kx - 1) * step
                    s_color = np.roll(filtered, shift=(dy, dx), axis=(0, 1))
                    s_normal = np.roll(normal_n, shift=(dy, dx), axis=(0, 1))
                    s_depth = np.roll(depth, shift=(dy, dx), axis=(0, 1))
                    s_lum = (s_color * lum_weights).sum(-1)

                    w_lum = np.exp(-np.abs(center_lum - s_lum) / phi_l)
                    n_dot = np.clip((normal_n * s_normal).sum(-1), 0.0, 1.0)
                    w_normal = np.power(n_dot, PHI_NORMAL)
                    grad_d = np.abs(depth - s_depth)
                    w_depth = np.exp(-grad_d / (PHI_DEPTH * grad_d + 1e-6))

                    # Zero weights for samples that wrapped past an image edge.
                    valid_mask = np.ones((H, W), dtype=np.float32)
                    if dy > 0:
                        valid_mask[:dy, :] = 0.0
                    elif dy < 0:
                        valid_mask[dy:, :] = 0.0
                    if dx > 0:
                        valid_mask[:, :dx] = 0.0
                    elif dx < 0:
                        valid_mask[:, dx:] = 0.0

                    w = kernel[ky, kx] * w_lum * w_normal * w_depth * valid_mask
                    num += s_color * w[..., None]
                    den += w
            den_safe = np.where(den > 1e-6, den, 1.0)[..., None]
            filtered = np.where(
                (den > 1e-6)[..., None], num / den_safe, filtered
            ).astype(np.float32)

        # Persist temporal state for next frame.
        self._cpu_history = {
            "color": accum_color.astype(np.float32),
            "m1": accum_m1.astype(np.float32),
            "m2": accum_m2.astype(np.float32),
            "len": hist_len.astype(np.float32),
        }
        return filtered

    # ------------------------------------------------------------------ GPU path

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
