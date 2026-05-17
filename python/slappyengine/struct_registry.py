from __future__ import annotations
from dataclasses import dataclass, field
from typing import ClassVar

# WGSL type sizes and alignment (must match WGSL spec)
WGSL_TYPE_INFO: dict[str, tuple[int, int]] = {
    # type → (size_bytes, align_bytes)
    "f32":   (4, 4),
    "u32":   (4, 4),
    "i32":   (4, 4),
    "vec2f": (8, 8),
    "vec3f": (12, 16),   # vec3 pads to 16-byte alignment in structs
    "vec4f": (16, 16),
}

class StructModule:
    """Base class for pixel struct extension modules."""
    name: ClassVar[str] = ""
    channels: ClassVar[list[tuple[str, str]]] = []     # [("health", "f32"), ...]
    compute_passes: ClassVar[list[str]] = []            # shader file names required
    default_values: ClassVar[dict[str, float]] = {}     # channel → initial value

class StructRegistry:
    def __init__(self):
        # Always-present color channel (vec4f, slot 0)
        self._modules: list[type[StructModule]] = []
        self._all_channels: list[tuple[str, str]] = [("color", "vec4f")]
        self._locked: bool = False
        self._layout_cache: dict[str, int] | None = None

    def register(self, module: type[StructModule]) -> None:
        if self._locked:
            raise RuntimeError("StructRegistry is locked — cannot register after shaders are compiled")
        for name, _ in module.channels:
            if any(n == name for n, _ in self._all_channels):
                raise ValueError(f"Channel '{name}' already registered by another module")
        self._modules.append(module)
        self._all_channels.extend(module.channels)
        self._layout_cache = None  # invalidate

    @property
    def channels(self) -> list[tuple[str, str]]:
        return list(self._all_channels)

    def lock(self) -> None:
        self._locked = True

    def _compute_layout(self) -> dict[str, int]:
        if self._layout_cache is not None:
            return self._layout_cache
        try:
            from slappyengine import _core
            layout = _core.compute_layout(self._all_channels)
            self._layout_cache = layout
            return layout
        except ImportError:
            pass
        # Pure-Python fallback
        layout: dict[str, int] = {}
        offset = 0
        for name, typ in self._all_channels:
            size, align = WGSL_TYPE_INFO[typ]
            # Align offset
            if offset % align != 0:
                offset += align - (offset % align)
            layout[name] = offset
            offset += size
        # stride = next multiple of 16
        if offset % 16 != 0:
            offset += 16 - (offset % 16)
        layout["stride"] = offset
        self._layout_cache = layout
        return layout

    def channel_offset(self, name: str) -> int:
        return self._compute_layout()[name]

    def stride_bytes(self) -> int:
        return self._compute_layout()["stride"]

    def default_for_channel(self, name: str) -> float:
        for mod in self._modules:
            if name in mod.default_values:
                return mod.default_values[name]
        return 0.0

    def required_compute_passes(self) -> list[str]:
        passes = []
        for mod in self._modules:
            for p in mod.compute_passes:
                if p not in passes:
                    passes.append(p)
        return passes
