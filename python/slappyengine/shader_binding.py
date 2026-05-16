"""ShaderBinding — connect per-pixel struct fields to shader parameters via transform curves."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ShaderBinding:
    """
    Links a per-pixel struct field to a shader uniform or texture parameter.

    The ShaderGen system reads these bindings and auto-generates WGSL fetch + transform code.

    Example — temperature drives emission:
        ShaderBinding(
            source_module="pixel_physics",
            source_field="temperature",
            target_shader="lighting_emission",
            target_param="emission_intensity",
            transform="planck",
            input_range=(800.0, 6000.0),
            output_range=(0.0, 3.0),
        )
    """
    source_module: str              # StructModule name, e.g. "pixel_physics"
    source_field: str               # field name within the struct, e.g. "temperature"
    target_shader: str              # shader name (without .wgsl), e.g. "lighting_emission"
    target_param: str               # uniform parameter name in the shader
    transform: str = "linear"       # "linear" | "pow2" | "sqrt" | "planck" | "custom_wgsl"
    custom_wgsl: str = ""           # inline WGSL expression using variable `val`
    input_range: tuple[float, float] = (0.0, 1.0)
    output_range: tuple[float, float] = (0.0, 1.0)
    clamp: bool = True

    def evaluate(self, val: float) -> float:
        """Python-side evaluation for preview / editor display."""
        import math
        lo_in, hi_in = self.input_range
        lo_out, hi_out = self.output_range

        if hi_in == lo_in:
            t = 0.0
        else:
            t = (val - lo_in) / (hi_in - lo_in)

        if self.clamp:
            t = max(0.0, min(1.0, t))

        if self.transform == "pow2":
            t = t * t
        elif self.transform == "sqrt":
            t = math.sqrt(max(0.0, t))
        elif self.transform == "planck":
            # Approximate: peak emission at t=1.0 (6000K), dim at t=0.0 (800K)
            t = t ** 0.5
        # "linear" and "custom_wgsl" use t as-is in Python

        result = lo_out + t * (hi_out - lo_out)
        if self.clamp:
            result = max(min(lo_out, hi_out), min(max(lo_out, hi_out), result))
        return result

    def to_wgsl_expr(self) -> str:
        """Generate WGSL expression for the transform. `val` is the input variable name."""
        lo_in, hi_in = self.input_range
        lo_out, hi_out = self.output_range
        clamp_s = f"clamp(val, {lo_in}, {hi_in})" if self.clamp else "val"
        t = f"({clamp_s} - {lo_in}) / {hi_in - lo_in}"
        if self.transform == "pow2":
            t = f"pow({t}, 2.0)"
        elif self.transform == "sqrt":
            t = f"sqrt(max(0.0, {t}))"
        elif self.transform == "planck":
            t = f"sqrt(max(0.0, {t}))"
        elif self.transform == "custom_wgsl":
            t = self.custom_wgsl.replace("val", clamp_s)
        return f"{lo_out} + ({t}) * {hi_out - lo_out}"
