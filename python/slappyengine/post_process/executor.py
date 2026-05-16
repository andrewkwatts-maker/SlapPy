from __future__ import annotations
import struct
import wgpu
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.gpu.context import GPUContext
    from slappyengine.post_process.chain import PostProcessChain, PostProcessPass

_SHADER_DIR = Path(__file__).parent.parent.parent.parent / "shaders"


class PostProcessExecutor:

    def __init__(self, ctx: "GPUContext"):
        self._ctx = ctx
        self._pipeline_cache: dict[str, wgpu.GPUComputePipeline] = {}
        self._ping: wgpu.GPUTexture | None = None
        self._pong: wgpu.GPUTexture | None = None
        self._width: int = 0
        self._height: int = 0

    def _ensure_buffers(self, width: int, height: int) -> None:
        if self._ping is not None and self._width == width and self._height == height:
            return
        for t in [self._ping, self._pong]:
            if t is not None:
                t.destroy()
        usage = (
            wgpu.TextureUsage.TEXTURE_BINDING
            | wgpu.TextureUsage.STORAGE_BINDING
            | wgpu.TextureUsage.COPY_DST
            | wgpu.TextureUsage.COPY_SRC
        )

        def make_tex() -> wgpu.GPUTexture:
            return self._ctx.device.create_texture(
                size=(width, height, 1),
                format=wgpu.TextureFormat.rgba8unorm,
                usage=usage,
                mip_level_count=1,
                sample_count=1,
            )

        self._ping = make_tex()
        self._pong = make_tex()
        self._width = width
        self._height = height

    def _get_pipeline(self, pass_: "PostProcessPass") -> wgpu.GPUComputePipeline | None:
        # Cache key includes the entry point so different entry points on the
        # same shader file get distinct pipelines (uncommon but safe).
        cache_key = f"{pass_.shader_path}::{pass_.entry_point}"
        if cache_key in self._pipeline_cache:
            return self._pipeline_cache[cache_key]
        shader_file = _SHADER_DIR / pass_.shader_path
        if not shader_file.exists():
            return None
        src = shader_file.read_text(encoding="utf-8")
        shader = self._ctx.device.create_shader_module(code=src)
        pipeline = self._ctx.device.create_compute_pipeline(
            layout="auto",
            compute={"module": shader, "entry_point": pass_.entry_point},
        )
        self._pipeline_cache[cache_key] = pipeline
        return pipeline

    def _make_params_buffer(self, pass_: "PostProcessPass", w: int, h: int) -> wgpu.GPUBuffer:
        params = pass_.params or {}

        if pass_.raw_params_bytes is not None:
            # Caller pre-packed everything; just upload as-is.
            data = pass_.raw_params_bytes
        elif pass_.shader_path == "nv_grain.wgsl":
            # Params struct layout (32 bytes):
            #   gain(f32), grain_strength(f32), vignette_strength(f32), time(f32),
            #   width(u32), height(u32), _pad0(u32), _pad1(u32)
            data = struct.pack(
                "<ffffIIII",
                float(params.get("gain", 3.0)),
                float(params.get("grain_strength", 0.08)),
                float(params.get("vignette_strength", 1.2)),
                float(params.get("time", 0.0)),
                w, h, 0, 0,
            )
        elif pass_.shader_path == "chromatic_aberration.wgsl":
            # Params struct layout (32 bytes):
            #   strength(f32), center_x(f32), center_y(f32), _pad(f32),
            #   width(u32), height(u32), _pad0(u32), _pad1(u32)
            data = struct.pack(
                "<ffffIIII",
                float(params.get("strength", 0.005)),
                float(params.get("center_x", 0.5)),
                float(params.get("center_y", 0.5)),
                0.0,  # _pad
                w, h, 0, 0,
            )
        elif pass_.shader_path == "tonemap.wgsl":
            # Params struct layout (56 bytes):
            #   exposure_ev(f32), mode(u32), saturation(f32), contrast(f32),
            #   lift_r(f32), lift_g(f32), lift_b(f32),
            #   gain_r(f32), gain_g(f32), gain_b(f32),
            #   gamma(f32), _pad(f32), width(u32), height(u32)
            # Format: f, I, f, f, f, f, f, f, f, f, f, f, I, I
            #         = 11 f32 + 3 u32 = 44 + 12 = 56 bytes
            data = struct.pack(
                "<fIffffffffffII",
                float(params.get("exposure_ev", 0.0)),
                int(params.get("mode", 0)),
                float(params.get("saturation", 1.0)),
                float(params.get("contrast", 1.0)),
                float(params.get("lift_r", 0.0)),
                float(params.get("lift_g", 0.0)),
                float(params.get("lift_b", 0.0)),
                float(params.get("gain_r", 1.0)),
                float(params.get("gain_g", 1.0)),
                float(params.get("gain_b", 1.0)),
                float(params.get("gamma", 1.0)),
                0.0,  # _pad
                w, h,
            )
        else:
            # Legacy layout: param(u32), width(u32), height(u32), _pad(u32)
            # blur.wgsl uses "radius"; pixelate.wgsl uses "block_size"
            p0 = int(params.get("radius", params.get("block_size", 0)))
            data = struct.pack("<IIII", p0, w, h, 0)

        buf = self._ctx.device.create_buffer(
            size=len(data),
            usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
            label=f"pp_params_{pass_.label}",
        )
        self._ctx.device.queue.write_buffer(buf, 0, data)
        return buf

    def execute(
        self,
        chain: "PostProcessChain",
        source_texture: wgpu.GPUTexture,
        width: int,
        height: int,
    ) -> wgpu.GPUTexture:
        active = chain.passes
        if not active:
            return source_texture

        self._ensure_buffers(width, height)
        device = self._ctx.device

        encoder = device.create_command_encoder(label="pp_copy_in")
        encoder.copy_texture_to_texture(
            {"texture": source_texture, "mip_level": 0, "origin": (0, 0, 0)},
            {"texture": self._ping, "mip_level": 0, "origin": (0, 0, 0)},
            (width, height, 1),
        )
        device.queue.submit([encoder.finish()])

        current_in = self._ping
        current_out = self._pong

        for pass_ in active:
            pipeline = self._get_pipeline(pass_)
            if pipeline is None:
                continue

            params_buf = self._make_params_buffer(pass_, width, height)

            in_view = current_in.create_view()
            out_view = current_out.create_view(
                format="rgba8unorm",
                usage=wgpu.TextureUsage.STORAGE_BINDING,
            )

            bg = device.create_bind_group(
                layout=pipeline.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": in_view},
                    {"binding": 1, "resource": out_view},
                    {"binding": 2, "resource": {"buffer": params_buf}},
                ],
            )

            enc = device.create_command_encoder(label=f"pp_{pass_.label}")
            cp = enc.begin_compute_pass()
            cp.set_pipeline(pipeline)
            cp.set_bind_group(0, bg)
            wg_x = (width + 7) // 8
            wg_y = (height + 7) // 8
            cp.dispatch_workgroups(wg_x, wg_y, 1)
            cp.end()
            device.queue.submit([enc.finish()])

            current_in, current_out = current_out, current_in

        return current_in
