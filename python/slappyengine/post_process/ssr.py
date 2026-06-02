"""SSRPass — screen-space reflection post-process pass."""
from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING

from ._ubo import UboField, pack_struct

if TYPE_CHECKING:
    import wgpu
    from slappyengine.gpu.context import GPUContext

_SHADER_NAME = "ssr.wgsl"
_ENTRY       = "main"

# SsrParams std140 layout (32 bytes).  width/height at offsets 0/4 are
# patched per dispatch (the executor passes the real resolution into
# ``_SSRApply.apply`` as ``width`` / ``height`` args).
_SSR_UBO_FIELDS = [
    UboField(name="width",            dtype="u32", offset=0),
    UboField(name="height",           dtype="u32", offset=4),
    UboField(name="max_steps",        dtype="u32", offset=8),
    UboField(name="stride",           dtype="f32", offset=12),
    UboField(name="thickness",        dtype="f32", offset=16),
    UboField(name="strength",         dtype="f32", offset=20),
    UboField(name="roughness_cutoff", dtype="f32", offset=24),
    UboField(name="_pad",             dtype="u32", offset=28),
]


class _SSRApply:
    """Holds compiled GPU resources and dispatches the SSR compute pass."""

    def __init__(
        self,
        pipeline,
        bgl,
        device,
        params: SSRPass,
    ) -> None:
        self._pipeline = pipeline
        self._bgl      = bgl
        self._device   = device
        self._params   = params

    def apply(self, encoder, gbuffer_pos, gbuffer_normal, scene_tex, depth_tex,
              output_tex, width: int, height: int) -> None:
        raw = pack_struct(
            _SSR_UBO_FIELDS,
            {
                "width":            int(width),
                "height":           int(height),
                "max_steps":        int(self._params.max_steps),
                "stride":           float(self._params.stride),
                "thickness":        float(self._params.thickness),
                "strength":         float(self._params.strength),
                "roughness_cutoff": float(self._params.roughness_cutoff),
                "_pad":             0,
            },
        )
        uniform_buf = self._device.create_buffer_with_data(
            data=raw,
            usage=0x40,  # UNIFORM
        )

        bg = self._device.create_bind_group(
            layout=self._bgl,
            entries=[
                {"binding": 0, "resource": {"buffer": uniform_buf}},
                {"binding": 1, "resource": gbuffer_pos.create_view()},
                {"binding": 2, "resource": gbuffer_normal.create_view()},
                {"binding": 3, "resource": scene_tex.create_view()},
                {"binding": 4, "resource": depth_tex.create_view()},
                {"binding": 5, "resource": self._device.create_sampler()},
                {"binding": 6, "resource": output_tex.create_view()},
            ],
        )

        cpass = encoder.begin_compute_pass()
        cpass.set_pipeline(self._pipeline)
        cpass.set_bind_group(0, bg)
        cpass.dispatch_workgroups(
            (width  + 7) // 8,
            (height + 7) // 8,
            1,
        )
        cpass.end()


class SSRPass:
    label = "ssr"

    def __init__(
        self,
        max_steps: int   = 16,
        stride: float    = 1.5,
        thickness: float = 0.5,
        strength: float  = 0.8,
        roughness_cutoff: float = 0.6,
    ) -> None:
        self.max_steps        = max_steps
        self.stride           = stride
        self.thickness        = thickness
        self.strength         = strength
        self.roughness_cutoff = roughness_cutoff

        # Lazily compiled; None until make_pass() is called.
        self._apply: _SSRApply | None = None

    @classmethod
    def from_config(cls, cfg) -> "SSRPass":
        s = cfg.rendering.ssr
        return cls(
            max_steps=s.max_steps,
            stride=s.stride,
            thickness=s.thickness,
            strength=s.strength,
            roughness_cutoff=s.roughness_cutoff,
        )

    def make_pass(
        self,
        gpu: "GPUContext",
        gbuffer_pos,
        gbuffer_normal,
        scene_tex,
        depth_tex,
    ) -> "_SSRApply | None":
        if self._apply is not None:
            return self._apply

        shader_path = (
            Path(__file__).parent.parent.parent.parent / "shaders" / _SHADER_NAME
        )
        if not shader_path.exists():
            return None

        try:
            import wgpu as _wgpu
        except ImportError:
            return None

        try:
            src    = shader_path.read_text(encoding="utf-8")
            device = gpu.device
            shader = device.create_shader_module(code=src)

            bgl = device.create_bind_group_layout(
                entries=[
                    # uniform params
                    {
                        "binding": 0,
                        "visibility": _wgpu.ShaderStage.COMPUTE,
                        "buffer": {"type": _wgpu.BufferBindingType.uniform},
                    },
                    # gbuffer_pos
                    {
                        "binding": 1,
                        "visibility": _wgpu.ShaderStage.COMPUTE,
                        "texture": {
                            "sample_type": _wgpu.TextureSampleType.float,
                            "view_dimension": _wgpu.TextureViewDimension.d2,
                        },
                    },
                    # gbuffer_normal
                    {
                        "binding": 2,
                        "visibility": _wgpu.ShaderStage.COMPUTE,
                        "texture": {
                            "sample_type": _wgpu.TextureSampleType.float,
                            "view_dimension": _wgpu.TextureViewDimension.d2,
                        },
                    },
                    # scene_color
                    {
                        "binding": 3,
                        "visibility": _wgpu.ShaderStage.COMPUTE,
                        "texture": {
                            "sample_type": _wgpu.TextureSampleType.float,
                            "view_dimension": _wgpu.TextureViewDimension.d2,
                        },
                    },
                    # depth_tex
                    {
                        "binding": 4,
                        "visibility": _wgpu.ShaderStage.COMPUTE,
                        "texture": {
                            "sample_type": _wgpu.TextureSampleType.unfilterable_float,
                            "view_dimension": _wgpu.TextureViewDimension.d2,
                        },
                    },
                    # sampler
                    {
                        "binding": 5,
                        "visibility": _wgpu.ShaderStage.COMPUTE,
                        "sampler": {"type": _wgpu.SamplerBindingType.filtering},
                    },
                    # ssr_out (storage write)
                    {
                        "binding": 6,
                        "visibility": _wgpu.ShaderStage.COMPUTE,
                        "storage_texture": {
                            "access": _wgpu.StorageTextureAccess.write_only,
                            "format": _wgpu.TextureFormat.rgba16float,
                            "view_dimension": _wgpu.TextureViewDimension.d2,
                        },
                    },
                ]
            )

            layout   = device.create_pipeline_layout(bind_group_layouts=[bgl])
            pipeline = device.create_compute_pipeline(
                layout=layout,
                compute={"module": shader, "entry_point": _ENTRY},
            )

            self._apply = _SSRApply(pipeline, bgl, device, self)
            return self._apply

        except Exception:
            # Any GPU or shader compile error degrades to no-op.
            return None
