from __future__ import annotations
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass
class PostProcessPass:
    shader_path: str
    params: dict = None
    label: str = ""
    enabled: bool = True
    # Custom WGSL entry-point name; defaults to "main" for backward-compat.
    entry_point: str = "main"
    # Pre-packed uniform bytes.  When set, bypasses _make_params_buffer entirely.
    raw_params_bytes: bytes | None = None

    def __post_init__(self):
        if self.params is None:
            self.params = {}

class PostProcessChain:
    """Ordered chain of post-process compute passes. Fully wired in M10."""

    def __init__(self):
        self._passes: list[PostProcessPass] = []

    def add(self, pass_: PostProcessPass) -> None:
        self._passes.append(pass_)

    def remove(self, label: str) -> None:
        self._passes = [p for p in self._passes if p.label != label]

    def add_blur(self, radius: int = 2) -> PostProcessPass:
        p = PostProcessPass(
            shader_path="blur.wgsl",
            params={"radius": radius},
            label="blur",
        )
        self.add(p)
        return p

    def add_pixelate(self, block_size: int = 4) -> PostProcessPass:
        p = PostProcessPass(
            shader_path="pixelate.wgsl",
            params={"block_size": block_size},
            label="pixelate",
        )
        self.add(p)
        return p

    def add_outline(self, color=(1.0, 0.0, 0.0, 1.0), threshold=0.1) -> PostProcessPass:
        p = PostProcessPass(
            shader_path="outline.wgsl",
            params={
                "outline_r": color[0], "outline_g": color[1],
                "outline_b": color[2], "outline_a": color[3],
                "threshold": threshold,
            },
            label="outline",
        )
        self.add(p)
        return p

    def add_gravity_warp(self, center=(0.5, 0.5), strength=1.0, radius=0.3) -> PostProcessPass:
        p = PostProcessPass(
            shader_path="gravity_warp.wgsl",
            params={
                "center_x": center[0], "center_y": center[1],
                "strength": strength, "radius": radius,
            },
            label="gravity_warp",
        )
        self.add(p)
        return p

    def add_night_vision(
        self,
        gain: float = 3.0,
        grain_strength: float = 0.08,
        vignette_strength: float = 1.2,
        time: float = 0.0,
    ) -> PostProcessPass:
        """WP-2.8 Night-vision effect.

        Args:
            gain: Green-channel amplification factor (default 3.0).
            grain_strength: Amplitude of the per-pixel noise added to green
                (default 0.08; red/blue get 30 % of this).
            vignette_strength: Controls how aggressively edges are darkened
                (default 1.2).
            time: Seed for the time-varying grain hash.  Update each frame to
                animate the noise.
        """
        # Pack: gain(f32), grain_strength(f32), vignette_strength(f32), time(f32),
        #       width(u32), height(u32), _pad0(u32), _pad1(u32)
        # width/height are not known here; executor will splice them in when it
        # builds the buffer.  We store the f32 prefix and let the executor append.
        p = PostProcessPass(
            shader_path="nv_grain.wgsl",
            params={
                "gain": gain,
                "grain_strength": grain_strength,
                "vignette_strength": vignette_strength,
                "time": time,
            },
            label="night_vision",
            entry_point="nv_grain_main",
        )
        self.add(p)
        return p

    def add_vignette(
        self,
        strength: float = 1.0,
        inner_radius: float = 0.0,
        feather: float = 0.0,
    ) -> PostProcessPass:
        """Round-4 vignette pass with optional smoothstep falloff.

        Args:
            strength: Peak darkening factor at the outer edge (default 1.0).
            inner_radius: Normalised radius (0 = centre, 1 = nearest edge
                midpoint) at which falloff begins.  Ignored when
                ``feather <= 0`` (legacy hard-quadratic path).
            feather: Width of the smoothstep transition band.  Set to a
                positive value to opt into the smooth shoulder; leave at
                ``0.0`` to reproduce the pre-round-4 ``pow(d*s, 2)``
                curve bit-for-bit.
        """
        # Params struct layout (32 bytes): see executor._make_params_buffer.
        p = PostProcessPass(
            shader_path="vignette.wgsl",
            params={
                "strength": strength,
                "inner_radius": inner_radius,
                "feather": feather,
            },
            label="vignette",
        )
        self.add(p)
        return p

    def add_chromatic_aberration(
        self,
        strength: float = 0.005,
        center: tuple[float, float] = (0.5, 0.5),
    ) -> PostProcessPass:
        """WP-2.9 Chromatic aberration effect.

        Args:
            strength: Radial channel-split magnitude as a fraction of the
                distance from center (default 0.005).
            center: Normalised (x, y) origin of the aberration (default centre
                of screen).
        """
        # Pack: strength(f32), center_x(f32), center_y(f32), _pad(f32),
        #       width(u32), height(u32), _pad0(u32), _pad1(u32)
        p = PostProcessPass(
            shader_path="chromatic_aberration.wgsl",
            params={
                "strength": strength,
                "center_x": center[0],
                "center_y": center[1],
            },
            label="chromatic_aberration",
            entry_point="chromatic_aberration_main",
        )
        self.add(p)
        return p

    @property
    def passes(self) -> list[PostProcessPass]:
        return [p for p in self._passes if p.enabled]
