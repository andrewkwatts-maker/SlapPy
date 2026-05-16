from __future__ import annotations
from playslap.struct_registry import StructRegistry

class ShaderGen:
    def __init__(self, registry: StructRegistry):
        self._registry = registry

    def pixel_struct_wgsl(self, struct_name: str = "PixelData") -> str:
        try:
            from playslap import _core
            return _core.generate_wgsl_struct(struct_name, self._registry.channels)
        except ImportError:
            pass
        # Pure-Python fallback
        lines = [f"struct {struct_name} {{"]
        layout = self._registry._compute_layout()
        for name, typ in self._registry.channels:
            lines.append(f"    {name}: {typ},")
        lines.append("}")
        return "\n".join(lines)

    def inject_into_shader(self, wgsl_template: str,
                           struct_name: str = "PixelData") -> str:
        struct_src = self.pixel_struct_wgsl(struct_name)
        return wgsl_template.replace("{{PIXEL_STRUCT}}", struct_src)
