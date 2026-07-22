"""SDF text mesh builder + WGSL fragment shader.

The renderer emits one quad per glyph (two triangles, four vertices) into
a shared vertex/index stream. The fragment shader samples the atlas'
signed distance field and uses ``smoothstep`` around the 0.5 boundary
for a screen-space anti-aliased edge.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import numpy as np

if TYPE_CHECKING:  # pragma: no cover
    from .atlas import SDFGlyphAtlas


# ---------------------------------------------------------------------------
# WGSL — kept intentionally compact (~800 B budget).
# ---------------------------------------------------------------------------

SDF_TEXT_WGSL: str = """// pharos_engine sdf_text
struct VSIn { @location(0) pos: vec2<f32>, @location(1) uv: vec2<f32> };
struct VSOut { @builtin(position) clip: vec4<f32>, @location(0) uv: vec2<f32> };
struct Uni { screen: vec2<f32>, color: vec4<f32>, smoothing: f32, _pad: f32 };

@group(0) @binding(0) var<uniform> u: Uni;
@group(0) @binding(1) var atlas: texture_2d<f32>;
@group(0) @binding(2) var samp: sampler;

@vertex
fn vs_main(v: VSIn) -> VSOut {
    var o: VSOut;
    let ndc = vec2<f32>(v.pos.x / u.screen.x * 2.0 - 1.0,
                        1.0 - v.pos.y / u.screen.y * 2.0);
    o.clip = vec4<f32>(ndc, 0.0, 1.0);
    o.uv = v.uv;
    return o;
}

@fragment
fn fs_main(o: VSOut) -> @location(0) vec4<f32> {
    let d = textureSample(atlas, samp, o.uv).r;
    let a = smoothstep(0.5 - u.smoothing, 0.5 + u.smoothing, d);
    return vec4<f32>(u.color.rgb, u.color.a * a);
}
"""


# ---------------------------------------------------------------------------
# Mesh builder
# ---------------------------------------------------------------------------


@dataclass
class TextMesh:
    """Per-string mesh returned by :meth:`SDFTextRenderer.build_text_mesh`."""

    positions: np.ndarray  # (N, 2) float32 — pixel-space vertex positions
    uvs: np.ndarray        # (N, 2) float32 — atlas UVs
    indices: np.ndarray    # (M,)  uint32   — triangle-list indices
    width_px: float
    height_px: float


class SDFTextRenderer:
    """Turns a string + atlas into GPU-ready vertex/index buffers."""

    def build_text_mesh(
        self,
        text: str,
        position_px: tuple[float, float],
        size_px: float,
        atlas: "SDFGlyphAtlas",
    ) -> TextMesh:
        """Build a triangle-list mesh for ``text``.

        Parameters
        ----------
        text:
            The UTF-8 string to lay out.
        position_px:
            Pen position (top-left of the first glyph) in pixels.
        size_px:
            Requested nominal size in pixels; glyph sizes are scaled by
            ``size_px / atlas.size_px``.
        atlas:
            A generated :class:`SDFGlyphAtlas`.

        Returns
        -------
        A :class:`TextMesh` with 4 vertices per character (missing glyphs
        emit a zero-area quad so the vertex count invariant tested by
        the suite always holds).

        Raises
        ------
        TypeError
            If *text* is not a ``str`` or *atlas* is ``None``.
        ValueError
            If *size_px* is not positive or *position_px* is not a
            2-sequence.
        """
        if not isinstance(text, str):
            raise TypeError(
                f"build_text_mesh: text must be str; got {type(text).__name__}"
            )
        if atlas is None:
            raise TypeError("build_text_mesh: atlas must not be None")
        if not hasattr(atlas, "generate") or not hasattr(atlas, "get_glyph"):
            raise TypeError(
                "build_text_mesh: atlas must expose generate() and "
                f"get_glyph(); got {type(atlas).__name__}"
            )
        if not hasattr(position_px, "__len__") or len(position_px) != 2:
            raise ValueError(
                f"build_text_mesh: position_px must be a 2-sequence; "
                f"got {position_px!r}"
            )
        if not isinstance(size_px, (int, float)) or size_px <= 0:
            raise ValueError(
                f"build_text_mesh: size_px must be > 0; got {size_px!r}"
            )
        if not text:
            return TextMesh(
                positions=np.zeros((0, 2), dtype=np.float32),
                uvs=np.zeros((0, 2), dtype=np.float32),
                indices=np.zeros((0,), dtype=np.uint32),
                width_px=0.0,
                height_px=0.0,
            )

        # Make sure the atlas has been generated so glyph tables exist.
        atlas.generate()

        scale = float(size_px) / float(atlas.size_px)
        pen_x, pen_y = float(position_px[0]), float(position_px[1])

        positions = np.zeros((4 * len(text), 2), dtype=np.float32)
        uvs = np.zeros((4 * len(text), 2), dtype=np.float32)
        indices = np.zeros((6 * len(text),), dtype=np.uint32)

        max_h = 0.0
        for i, ch in enumerate(text):
            g = atlas.get_glyph(ord(ch))
            if g is None:
                # Advance the pen with a default width so text_bounds()
                # matches; emit a degenerate quad at the pen position.
                pen_x += (atlas.size_px // 2) * scale
                v = 4 * i
                positions[v:v + 4] = ((pen_x, pen_y),) * 4
                # UVs left as zero — samples will hit the padding pixel.
                indices[6 * i:6 * i + 6] = (v, v + 1, v + 2, v, v + 2, v + 3)
                continue

            gw, gh = g.size_px
            bx, by = g.bearing
            x0 = pen_x + bx * scale
            y0 = pen_y - by * scale + atlas.size_px * scale
            x1 = x0 + gw * scale
            y1 = y0 + gh * scale
            u0, v0, u1, v1 = g.atlas_uv

            v = 4 * i
            positions[v + 0] = (x0, y0)
            positions[v + 1] = (x1, y0)
            positions[v + 2] = (x1, y1)
            positions[v + 3] = (x0, y1)
            uvs[v + 0] = (u0, v0)
            uvs[v + 1] = (u1, v0)
            uvs[v + 2] = (u1, v1)
            uvs[v + 3] = (u0, v1)

            indices[6 * i + 0] = v + 0
            indices[6 * i + 1] = v + 1
            indices[6 * i + 2] = v + 2
            indices[6 * i + 3] = v + 0
            indices[6 * i + 4] = v + 2
            indices[6 * i + 5] = v + 3

            pen_x += g.advance_px * scale
            max_h = max(max_h, gh * scale)

        width = pen_x - float(position_px[0])
        return TextMesh(
            positions=positions,
            uvs=uvs,
            indices=indices,
            width_px=float(width),
            height_px=float(max_h if max_h > 0 else atlas.size_px * scale),
        )
