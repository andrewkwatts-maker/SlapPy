"""GTAO ambient-occlusion post-process pass (Jimenez 2016)."""
from __future__ import annotations

import math
from typing import Any

from ._pass_base import PostProcessPassBase
from ._ubo import UboField
from ._validation import (
    validate_bool,
    validate_mat4_tuple,
    validate_non_negative_float,
    validate_positive_float,
    validate_positive_int,
    validate_unit_interval,
)

_SHADER = "ao_gtao.wgsl"
_ENTRY  = "ao_gtao_main"

_IDENTITY_MAT4 = (
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
)


# GtaoParams layout — 112 bytes.  The mat4 is encoded as 4 successive vec4f
# fields so the std140 packer can place it at offset 0 without bespoke
# matrix support.  width/height stay at offsets 88/92 for executor splice.
_GTAO_UBO_FIELDS = [
    UboField(name="inv_proj_r0",      dtype="vec4f", offset=0),
    UboField(name="inv_proj_r1",      dtype="vec4f", offset=16),
    UboField(name="inv_proj_r2",      dtype="vec4f", offset=32),
    UboField(name="inv_proj_r3",      dtype="vec4f", offset=48),
    UboField(name="radius",           dtype="f32",   offset=64),
    UboField(name="max_pixel_radius", dtype="f32",   offset=68),
    UboField(name="num_directions",   dtype="u32",   offset=72),
    UboField(name="num_steps",        dtype="u32",   offset=76),
    UboField(name="power",            dtype="f32",   offset=80),
    UboField(name="bias",             dtype="f32",   offset=84),
    UboField(name="width",            dtype="u32",   offset=88),
    UboField(name="height",           dtype="u32",   offset=92),
    UboField(name="depth_falloff",    dtype="f32",   offset=96),
    UboField(name="min_radius_scale", dtype="f32",   offset=100),
    UboField(name="multibounce",      dtype="u32",   offset=104),
    UboField(name="_pad0",            dtype="u32",   offset=108),
]


def compute_adaptive_radius(
    world_radius: float,
    view_depth: float,
    depth_falloff: float,
    min_radius_scale: float = 0.25,
    max_radius_scale: float = 1.0,
) -> float:
    """Return a per-pixel adapted AO radius (Jimenez 2016).

    The trick: at very close range we want a *small* radius so we capture fine
    crevices and contact shadows; at far range we want a *large* radius so we
    capture broad ambient occlusion without aliasing.  The scale follows

        scale = clamp(1 - exp(-depth_falloff * view_depth), min_scale, max_scale)

    so a falloff of 0 yields the legacy behaviour (no adaptation).
    """
    if depth_falloff <= 0.0:
        return float(world_radius)

    z = max(0.0, float(view_depth))
    raw_scale = 1.0 - math.exp(-depth_falloff * z)
    scale = min(max_radius_scale, max(min_radius_scale, raw_scale))
    return float(world_radius) * scale


def multibounce_visibility(
    visibility: float,
    albedo: float,
) -> float:
    """Jimenez 2016 §2.3 multibounce AO approximation.

    Approximates indirect light bouncing off a coloured surface back into the
    occluded crevices.  Single-bounce GTAO only attenuates the *direct* ambient
    term; the cubic-polynomial fit brightens crevice visibility per channel to
    model indirect bounce light.  See :mod:`taa` and the cited paper for the
    exact constants used here.
    """
    v = float(visibility)
    al = float(albedo)
    a = 2.0404 * al - 0.3324
    b = -4.7951 * al + 0.6417
    c = 2.7552 * al + 0.6903
    poly = (a * v + b) * v + c
    bounced = v * poly
    blended = v + (bounced - v) * al
    return max(v, blended)


class GTAOPass(PostProcessPassBase):
    label = "gtao"

    # ----- PostProcessPassBase declarative schema -----
    SHADER = _SHADER
    ENTRY = _ENTRY
    PARAMS_LAYOUT = _GTAO_UBO_FIELDS
    EXTRA_BINDINGS = ("depth_tex", "normal_tex", "albedo_tex")
    BLOB_SIZE = 112

    def __init__(
        self,
        num_directions: int = 8,
        num_steps: int = 4,
        radius: float = 2.0,
        intensity: float = 1.0,
        bias: float = 0.05,
        max_pixel_radius: float = 64.0,
        inv_proj: tuple = _IDENTITY_MAT4,
        depth_falloff: float = 0.0,
        min_radius_scale: float = 0.25,
        multibounce: bool = True,
    ) -> None:
        """Construct a GTAO ambient-occlusion pass.

        Raises
        ------
        TypeError
            If any numeric kwarg is the wrong type (bools/strings refused).
        ValueError
            If any positive-only kwarg is ≤ 0, ``bias`` / ``depth_falloff``
            are negative or NaN/inf, ``min_radius_scale`` is outside
            ``[0, 1]``, or ``inv_proj`` is not a 16-element matrix.
        """
        validate_positive_int("num_directions", "GTAOPass", num_directions)
        validate_positive_int("num_steps", "GTAOPass", num_steps)
        validate_positive_float("radius", "GTAOPass", radius)
        validate_positive_float("intensity", "GTAOPass", intensity)
        validate_non_negative_float("bias", "GTAOPass", bias)
        validate_positive_float(
            "max_pixel_radius", "GTAOPass", max_pixel_radius,
        )
        validate_mat4_tuple("inv_proj", "GTAOPass", inv_proj)
        validate_non_negative_float(
            "depth_falloff", "GTAOPass", depth_falloff,
        )
        validate_unit_interval(
            "min_radius_scale", "GTAOPass", min_radius_scale,
        )
        validate_bool("multibounce", "GTAOPass", multibounce)

        self.num_directions = num_directions
        self.num_steps = num_steps
        self.radius = radius
        # intensity → power exponent so higher intensity darkens AO faster.
        self.power = 1.0 / max(intensity, 1e-6)
        self.bias = bias
        self.max_pixel_radius = max_pixel_radius
        self.inv_proj = inv_proj
        self.depth_falloff = float(depth_falloff)
        self.min_radius_scale = float(min_radius_scale)
        self.multibounce = bool(multibounce)

    @classmethod
    def from_config(cls, cfg) -> "GTAOPass":
        ao = cfg.rendering.gtao
        return cls(
            num_directions=ao.num_directions,
            num_steps=ao.num_steps,
            radius=ao.radius,
            intensity=ao.intensity,
            bias=ao.bias,
            depth_falloff=getattr(ao, "depth_falloff", 0.0),
            min_radius_scale=getattr(ao, "min_radius_scale", 0.25),
            multibounce=bool(getattr(ao, "multibounce", True)),
        )

    def adaptive_radius(self, view_depth: float) -> float:
        """Return the per-pixel world-space radius at a given view-space depth."""
        return compute_adaptive_radius(
            self.radius,
            view_depth,
            self.depth_falloff,
            self.min_radius_scale,
        )

    def make_pass(self, depth_tex=None, normal_tex=None, albedo_tex=None):
        """Build a :class:`PostProcessPass` for the GTAO resolve.

        ``albedo_tex`` is optional (None) for headless / no-G-buffer
        callers — the shader falls back to neutral albedo for the
        multibounce term in that case.
        """
        return super().make_pass(
            depth_tex=depth_tex,
            normal_tex=normal_tex,
            albedo_tex=albedo_tex,
        )

    # ----- UBO field-value adapter -----
    def _field_values(self) -> dict[str, Any]:
        m = self.inv_proj
        return {
            "inv_proj_r0":      (float(m[0]),  float(m[1]),  float(m[2]),  float(m[3])),
            "inv_proj_r1":      (float(m[4]),  float(m[5]),  float(m[6]),  float(m[7])),
            "inv_proj_r2":      (float(m[8]),  float(m[9]),  float(m[10]), float(m[11])),
            "inv_proj_r3":      (float(m[12]), float(m[13]), float(m[14]), float(m[15])),
            "radius":           float(self.radius),
            "max_pixel_radius": float(self.max_pixel_radius),
            "num_directions":   int(self.num_directions),
            "num_steps":        int(self.num_steps),
            "power":            float(self.power),
            "bias":             float(self.bias),
            # width/height filled by executor splice at dispatch time.
            "width":            0,
            "height":           0,
            "depth_falloff":    float(self.depth_falloff),
            "min_radius_scale": float(self.min_radius_scale),
            "multibounce":      1 if self.multibounce else 0,
            "_pad0":            0,
        }
