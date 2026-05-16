"""RenderChannelCompositor — multi-pass render channels with blend modes.

Supports: lerp, additive, multiply, screen blends between named render passes.
Used for: night vision, strata layer transitions, thermal vision, etc.
"""
from __future__ import annotations
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from slappyengine.gpu.context import GPUContext


@dataclass
class RenderPass:
    """A named render channel with its own lighting overrides and blend settings."""
    name: str
    tint: tuple[float, float, float] = (1.0, 1.0, 1.0)
    gain: float = 1.0
    noise_strength: float = 0.0
    blend_mode: str = "lerp"        # "lerp" | "additive" | "multiply" | "screen" | "replace"
    blend_alpha: float = 0.0        # 0=invisible, 1=fully blended
    lighting_overrides: dict = field(default_factory=dict)
    post_shaders: list[str] = field(default_factory=list)


# Pre-built pass definitions
NightVisionPass = RenderPass(
    name="night_vision",
    tint=(0.1, 1.0, 0.1),
    gain=4.0,
    noise_strength=0.04,
    blend_mode="replace",
    blend_alpha=0.0,
    lighting_overrides={"ambient_intensity": 3.0},
    post_shaders=["nv_grain"],
)

ThermalPass = RenderPass(
    name="thermal",
    tint=(1.0, 0.3, 0.0),
    gain=1.5,
    noise_strength=0.01,
    blend_mode="replace",
    blend_alpha=0.0,
    lighting_overrides={"ambient_intensity": 0.0},
)


class RenderChannelCompositor:
    """
    Manages N named render channels (RenderPass objects).
    A compositor shader blends active channels onto the base frame each frame.
    """

    def __init__(self, gpu: "GPUContext", width: int, height: int):
        self._gpu = gpu
        self._width = width
        self._height = height
        self._passes: dict[str, RenderPass] = {}
        self._transitions: dict[str, dict] = {}  # name → {target, speed, current}
        self._pipeline_blend = None
        self._blend_shader_dir = Path(__file__).parent.parent.parent / "shaders"

    def add_channel(self, pass_def: "RenderPass | str") -> RenderPass:
        """Register a render pass. Accepts a RenderPass or a name string."""
        if isinstance(pass_def, str):
            p = RenderPass(name=pass_def)
        else:
            p = pass_def
        self._passes[p.name] = p
        return p

    def set_mix(self, channel_name: str, alpha: float) -> None:
        """Immediately set a channel's blend alpha (0=off, 1=fully on)."""
        if channel_name in self._passes:
            self._passes[channel_name].blend_alpha = max(0.0, min(1.0, alpha))

    def lerp_to(self, channel_name: str, target: float,
                duration: float = 0.3) -> None:
        """Smoothly lerp a channel's blend alpha to target over duration seconds."""
        if channel_name not in self._passes:
            return
        self._transitions[channel_name] = {
            "target": target,
            "speed": 1.0 / max(duration, 0.001),
            "current": self._passes[channel_name].blend_alpha,
        }

    def tick(self, dt: float) -> None:
        """Advance all active transitions."""
        done = []
        for name, t in self._transitions.items():
            p = self._passes.get(name)
            if p is None:
                done.append(name)
                continue
            diff = t["target"] - p.blend_alpha
            step = t["speed"] * dt
            if abs(diff) <= step:
                p.blend_alpha = t["target"]
                done.append(name)
            else:
                p.blend_alpha += step if diff > 0 else -step
        for name in done:
            del self._transitions[name]

    def dispatch(self, encoder, base_tex, out_tex) -> None:
        """Composite all active passes onto base_tex → out_tex."""
        import wgpu  # deferred import — avoids hard failure in headless mode

        active = self.active_passes
        if not active:
            return

        # Lazy pipeline initialisation — compile compositor_blend.wgsl once.
        if self._pipeline_blend is None:
            shader_file = self._blend_shader_dir / "compositor_blend.wgsl"
            src = shader_file.read_text(encoding="utf-8")
            device = self._gpu.device
            shader_mod = device.create_shader_module(code=src)
            self._pipeline_blend = device.create_compute_pipeline(
                layout="auto",
                compute={"module": shader_mod, "entry_point": "main"},
            )

        device = self._gpu.device
        width = self._width
        height = self._height

        _BLEND_MODE: dict[str, int] = {
            "lerp": 0,
            "additive": 1,
            "multiply": 2,
            "screen": 3,
            "replace": 4,
        }

        base_view = base_tex.create_view()
        out_view = out_tex.create_view(
            format="rgba8unorm",
            usage=wgpu.TextureUsage.STORAGE_BINDING,
        )

        for rp in active:
            tint_r, tint_g, tint_b = rp.tint
            blend_mode_u32 = _BLEND_MODE.get(rp.blend_mode, 0)

            # Params layout (std140-compatible, all f32/u32):
            # tint_r, tint_g, tint_b, gain  (4 × f32)
            # blend_alpha                    (1 × f32)
            # blend_mode                     (1 × u32)
            # width, height                  (2 × u32)
            data = struct.pack(
                "<4f f I 2I",
                tint_r, tint_g, tint_b, rp.gain,
                rp.blend_alpha,
                blend_mode_u32,
                width, height,
            )
            params_buf = device.create_buffer(
                size=len(data),
                usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST,
                label=f"compositor_params_{rp.name}",
            )
            device.queue.write_buffer(params_buf, 0, data)

            bg = device.create_bind_group(
                layout=self._pipeline_blend.get_bind_group_layout(0),
                entries=[
                    {"binding": 0, "resource": {"buffer": params_buf}},
                    {"binding": 1, "resource": base_view},
                    {"binding": 2, "resource": out_view},
                ],
            )

            cp = encoder.begin_compute_pass(label=f"compositor_{rp.name}")
            cp.set_pipeline(self._pipeline_blend)
            cp.set_bind_group(0, bg)
            cp.dispatch_workgroups((width + 7) // 8, (height + 7) // 8, 1)
            cp.end()

    @property
    def active_passes(self) -> list[RenderPass]:
        return [p for p in self._passes.values() if p.blend_alpha > 0.001]
