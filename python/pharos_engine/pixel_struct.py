"""
PixelStruct — maps a GPU texel layout to named Python/WGSL fields.
CPU and GPU both see the same struct. Used by Layer2D, SimField, and any
compute pass that needs typed pixel access.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import numpy as np


DTYPE_TO_CHANNELS = {
    "f32": 1, "vec2": 2, "vec3": 3, "vec4": 4,
    "u32": 1, "i32": 1,
}

DTYPE_TO_NP = {
    "f32": np.float32, "vec2": np.float32, "vec3": np.float32, "vec4": np.float32,
    "u32": np.uint32, "i32": np.int32,
}


@dataclass
class FieldDef:
    name: str
    dtype: str           # "f32", "vec2", "vec3", "vec4", "u32", "i32"
    offset: int = 0      # channel offset within the pixel (computed on build)


class PixelStruct:
    """
    Defines the typed layout of a pixel (texel).

    Example:
        track = PixelStruct({
            "albedo":    "vec4",
            "roughness": "f32",
            "puddle":    "f32",
            "damage":    "f32",
        })
        # Total channels = 4+1+1+1 = 7, stored as float32 array with shape (H, W, 7)

    CPU side: read_pixel(arr, x, y) → dict
    WGSL side: to_wgsl_struct() → WGSL struct string
    """

    def __init__(self, fields: dict[str, str]):
        self._fields: list[FieldDef] = []
        self._name_to_field: dict[str, FieldDef] = {}
        offset = 0
        for name, dtype in fields.items():
            if dtype not in DTYPE_TO_CHANNELS:
                raise ValueError(f"Unknown dtype '{dtype}' for field '{name}'")
            f = FieldDef(name=name, dtype=dtype, offset=offset)
            self._fields.append(f)
            self._name_to_field[name] = f
            offset += DTYPE_TO_CHANNELS[dtype]
        self._total_channels = offset

    @property
    def total_channels(self) -> int:
        return self._total_channels

    @property
    def field_names(self) -> list[str]:
        return [f.name for f in self._fields]

    def empty_array(self, height: int, width: int) -> np.ndarray:
        """Return a zero-initialised (H, W, total_channels) float32 array."""
        return np.zeros((height, width, self._total_channels), dtype=np.float32)

    def read_pixel(self, array: np.ndarray, x: int, y: int) -> dict[str, Any]:
        """Read a pixel at (x, y) from an (H, W, C) array → named dict."""
        result = {}
        row = array[y, x]
        for f in self._fields:
            n = DTYPE_TO_CHANNELS[f.dtype]
            if n == 1:
                result[f.name] = float(row[f.offset])
            else:
                result[f.name] = tuple(float(v) for v in row[f.offset:f.offset + n])
        return result

    def write_pixel(self, array: np.ndarray, x: int, y: int,
                    values: dict[str, Any]) -> None:
        """Write named field values into array at (x, y)."""
        for name, value in values.items():
            if name not in self._name_to_field:
                continue
            f = self._name_to_field[name]
            n = DTYPE_TO_CHANNELS[f.dtype]
            if n == 1:
                array[y, x, f.offset] = float(value)
            else:
                for i, v in enumerate(value):
                    if f.offset + i < array.shape[2]:
                        array[y, x, f.offset + i] = float(v)

    def to_wgsl_struct(self, struct_name: str = "Pixel") -> str:
        """Generate the WGSL struct definition for this pixel layout."""
        lines = [f"struct {struct_name} {{"]
        for f in self._fields:
            lines.append(f"    {f.name}: {f.dtype},")
        lines.append("}")
        return "\n".join(lines)

    def slice_field(self, array: np.ndarray, field_name: str) -> np.ndarray:
        """Return a view of a single field's channels: (H, W) or (H, W, N)."""
        f = self._name_to_field[field_name]
        n = DTYPE_TO_CHANNELS[f.dtype]
        if n == 1:
            return array[:, :, f.offset]
        return array[:, :, f.offset:f.offset + n]

    def to_rgb_view(
        self,
        array: np.ndarray,
        channels: "tuple[str, str, str]",
        ranges: "tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None" = None,
    ) -> np.ndarray:
        """Render any 3 named scalar fields as an (H, W, 3) uint8 RGB image.

        Lets game code pick any three properties from this PixelStruct for a
        debug visualisation, without having to write a custom shader for each
        view.  Multi-channel fields (vec2/vec3/vec4) use their first channel.

        Parameters
        ----------
        array:
            ``(H, W, total_channels)`` float32 array conforming to this struct.
        channels:
            Three field names to map to (R, G, B).
        ranges:
            Optional per-channel ``(min, max)`` for normalisation.  Defaults
            to ``(0.0, 1.0)`` per channel.  Values outside the range are
            clamped.

        Returns
        -------
        numpy.ndarray
            ``(H, W, 3)`` uint8 array ready for PIL/save.
        """
        if len(channels) != 3:
            raise ValueError("to_rgb_view() requires exactly 3 field names")
        if ranges is None:
            ranges = ((0.0, 1.0), (0.0, 1.0), (0.0, 1.0))
        if len(ranges) != 3:
            raise ValueError("to_rgb_view() requires 3 (min, max) pairs in ranges")

        h, w = array.shape[:2]
        out = np.zeros((h, w, 3), dtype=np.uint8)
        for i, (name, (lo, hi)) in enumerate(zip(channels, ranges)):
            slice_arr = self.slice_field(array, name)
            if slice_arr.ndim == 3:
                # Multi-channel — take first channel
                slice_arr = slice_arr[..., 0]
            denom = (hi - lo) if (hi - lo) != 0 else 1.0
            normed = np.clip((slice_arr - lo) / denom, 0.0, 1.0)
            out[..., i] = (normed * 255.0).astype(np.uint8)
        return out

    def __repr__(self) -> str:
        fields_str = ", ".join(f"{f.name}:{f.dtype}" for f in self._fields)
        return f"PixelStruct({fields_str})"
