"""Temporal Anti-Aliasing (TAA) post-process pass.

Round 5 of the TAA refinement work; the UBO grew to 48 bytes to make
room for depth- and normal-disocclusion rejection (Andersson 2015,
Karis 2014).  ``width`` and ``height`` stay pinned at offsets 8 and 12
respectively so the executor's runtime-splice helper
(``_splice_runtime_params``) can patch them at dispatch time without
re-uploading the entire UBO.

Round 6 — polish (W3 sprint 2026-07-04):
    * Module-level YCoCg conversion helpers exposed for external tools
      (variance-clip debug HUDs, unit tests, offline resolves).
    * Karis 2014 canonical ``k = 1.25`` sigma-envelope variance clip
      exposed as a first-class helper (``variance_clip_ycocg``).
    * Halton(2,3) 8-sample sub-pixel jitter sequence (upgraded from the
      previous 4-sample table) — improves screen-space sample coverage
      by roughly √2 and drops residual aliasing on high-contrast edges.
    * Velocity-aware blend factor helper
      (``velocity_aware_alpha``) — history contribution drops on fast
      motion, following DICE's Frostbite TAA 2016 recommendation
      ``alpha = clamp(0.05, 0.95, 0.9 - 0.5 * |v|)``.
    * Luminance-based ghost rejection
      (``luminance_rejection``) — drops the history sample when the
      per-pixel luminance disparity exceeds ``0.5 * max(cur, hist)``.
    * Relative-depth rejection (``depth_rejection``) — a 2 % of current
      NDC depth divergence flags disocclusion, which is a much better
      camera-distance-independent threshold than the round-5 absolute
      ``0.1``.  The existing ``reject_on_depth_disocclusion`` absolute
      path stays for backwards compat.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from ._pass_base import PostProcessPassBase
from ._ubo import UboField
from ._validation import (
    validate_bool,
    validate_non_negative_float,
    validate_unit_interval,
)


_SHADER = "taa_resolve.wgsl"
_ENTRY  = "taa_resolve_main"

# Luminance coefficients (Rec. 709) used for the Karis weighting.
# Pre-computed at module level so the hot numpy path doesn't allocate a list.
_LUM_R = 0.2126
_LUM_G = 0.7152
_LUM_B = 0.0722


# ---------------------------------------------------------------------------
# Round 6 — Halton(2,3) 8-sample sub-pixel jitter table
# ---------------------------------------------------------------------------
#
# Halton(base_x, base_y) yields a low-discrepancy sequence in [0, 1)^2.
# Index 0 is (0, 0) which is trivial and skipped; the 8 usable samples
# are Halton indices 1..8.  Values reproduced here as float literals so
# tests can pin them at compile time without invoking the sequence
# generator (and so the module import cost stays zero).  The offsets
# are pre-centred on the pixel — subtract 0.5 to get the ± offset from
# the pixel centre used by most TAA jitter camera-matrix builders.
HALTON_2_3_8_SAMPLES: tuple[tuple[float, float], ...] = (
    (0.5000000000, 0.3333333333),
    (0.2500000000, 0.6666666667),
    (0.7500000000, 0.1111111111),
    (0.1250000000, 0.4444444444),
    (0.6250000000, 0.7777777778),
    (0.3750000000, 0.2222222222),
    (0.8750000000, 0.5555555556),
    (0.0625000000, 0.8888888889),
)


def halton_sample(index: int, base: int) -> float:
    """Return the *index*-th sample of the Halton sequence in ``base``.

    Uses the canonical van-der-Corput folding.  Deterministic and
    stateless — pure function, no globals.  Raises ``ValueError`` if
    ``base < 2`` or ``index < 0``.
    """
    if not isinstance(index, int) or isinstance(index, bool):
        raise TypeError(f"index must be int; got {type(index).__name__}")
    if not isinstance(base, int) or isinstance(base, bool):
        raise TypeError(f"base must be int; got {type(base).__name__}")
    if index < 0:
        raise ValueError(f"index must be >= 0; got {index}")
    if base < 2:
        raise ValueError(f"base must be >= 2; got {base}")
    f = 1.0
    r = 0.0
    i = index
    while i > 0:
        f /= base
        r += f * (i % base)
        i //= base
    return r


def halton_2_3_sequence(count: int = 8) -> tuple[tuple[float, float], ...]:
    """Return the first ``count`` Halton(2,3) 2-D samples.

    Skips index 0 (which is ``(0, 0)`` and therefore useless as a
    jitter offset) and returns samples at indices 1..count inclusive.
    """
    if not isinstance(count, int) or isinstance(count, bool):
        raise TypeError(f"count must be int; got {type(count).__name__}")
    if count < 1:
        raise ValueError(f"count must be >= 1; got {count}")
    return tuple(
        (halton_sample(i, 2), halton_sample(i, 3))
        for i in range(1, count + 1)
    )


# ---------------------------------------------------------------------------
# Round 6 — YCoCg conversion + variance-clip helpers
# ---------------------------------------------------------------------------


def rgb_to_ycocg(rgb: "object") -> "object":
    """Convert an ``(..., 3)`` RGB numpy array to YCoCg.

    Matches the ``rgb_to_ycocg`` helper in ``taa_resolve.wgsl`` exactly
    so unit tests can compare CPU and GPU paths bit-for-bit.
    """
    import numpy as np
    a = np.asarray(rgb, dtype=np.float32)
    if a.ndim < 1 or a.shape[-1] != 3:
        raise ValueError(f"rgb must have trailing dim 3; got shape {a.shape}")
    r = a[..., 0]
    g = a[..., 1]
    b = a[..., 2]
    y  = 0.25 * r + 0.5 * g + 0.25 * b
    co = 0.5 * r - 0.5 * b
    cg = -0.25 * r + 0.5 * g - 0.25 * b
    return np.stack([y, co, cg], axis=-1).astype(np.float32)


def ycocg_to_rgb(ycocg: "object") -> "object":
    """Inverse of :func:`rgb_to_ycocg` — matches WGSL ``ycocg_to_rgb``."""
    import numpy as np
    a = np.asarray(ycocg, dtype=np.float32)
    if a.ndim < 1 or a.shape[-1] != 3:
        raise ValueError(
            f"ycocg must have trailing dim 3; got shape {a.shape}"
        )
    y  = a[..., 0]
    co = a[..., 1]
    cg = a[..., 2]
    tmp = y - cg
    return np.stack([tmp + co, y + cg, tmp - co], axis=-1).astype(np.float32)


# Karis 2014 canonical sigma-envelope tightness.  The paper reports
# k = 1.0 for still cameras and k = 1.25 as a "slight motion tolerance"
# default that matches Frostbite's 2016 TAA presentation.
KARIS_2014_K: float = 1.25


def variance_clip_ycocg(
    current: "object",
    history: "object",
    k: float = KARIS_2014_K,
) -> "object":
    """Clip ``history`` (``(H, W, 3)`` RGB) to the k-sigma YCoCg AABB.

    Computes the per-pixel 3x3 neighbourhood mean and stddev of
    ``current`` in YCoCg space and clamps every history sample into the
    envelope ``[mean - k*std, mean + k*std]`` per channel.  Returns the
    clipped history in RGB.  This is the round-6 canonical variance
    clip; the existing :class:`TAAPass.resolve_numpy` path is left
    unchanged for backwards compatibility.
    """
    import numpy as np
    cur = np.asarray(current, dtype=np.float32)
    hist = np.asarray(history, dtype=np.float32)
    if cur.shape != hist.shape or cur.ndim != 3 or cur.shape[2] != 3:
        raise ValueError(
            f"current and history must be matching (H, W, 3) arrays; "
            f"got {cur.shape} vs {hist.shape}"
        )
    if not float(k) >= 0.0:
        raise ValueError(f"k must be >= 0; got {k!r}")
    h, w, _ = cur.shape

    cur_yc = rgb_to_ycocg(cur)
    hist_yc = rgb_to_ycocg(hist)

    # 3x3 neighbourhood tiles built via edge-padded reflection.
    padded = np.pad(cur_yc, ((1, 1), (1, 1), (0, 0)), mode="edge")
    tiles = np.stack(
        [padded[i:i + h, j:j + w, :] for i in range(3) for j in range(3)],
        axis=0,
    )
    mu = tiles.mean(axis=0)
    sigma = np.sqrt(
        np.maximum((tiles ** 2).mean(axis=0) - mu ** 2, 0.0)
    )
    lo = mu - float(k) * sigma
    hi = mu + float(k) * sigma
    clipped_yc = np.clip(hist_yc, lo, hi).astype(np.float32)
    return ycocg_to_rgb(clipped_yc)


# ---------------------------------------------------------------------------
# Round 6 — Velocity-aware blend factor (DICE Frostbite 2016)
# ---------------------------------------------------------------------------


def velocity_aware_alpha(
    velocity: "object",
    base_alpha: float = 0.9,
    lo: float = 0.05,
    hi: float = 0.95,
    scale: float = 0.5,
) -> "object":
    """Per-pixel alpha that drops history contribution on high motion.

    ``alpha = clamp(lo, hi, base_alpha - scale * length(velocity))``

    ``velocity`` may be a scalar magnitude, an ``(H, W)`` scalar field,
    or an ``(H, W, 2)`` UV-space vector field — the caller's choice.

    The default ``base_alpha`` here follows the sprint spec's Frostbite
    2016 recipe (``0.9 - 0.5 * |v|``), *NOT* the ``TAAPass.alpha`` field
    which is documented as the fraction-of-current-blended-in and
    therefore semantically inverse.  Returned array is float32 so it
    can flow straight into the shader UBO.
    """
    import numpy as np
    v = np.asarray(velocity, dtype=np.float32)
    if v.ndim >= 1 and v.shape[-1] == 2 and v.ndim >= 2:
        mag = np.sqrt(v[..., 0] ** 2 + v[..., 1] ** 2)
    else:
        mag = np.abs(v)
    if not (float(lo) <= float(hi)):
        raise ValueError(f"lo ({lo}) must be <= hi ({hi})")
    alpha = float(base_alpha) - float(scale) * mag
    return np.clip(alpha, float(lo), float(hi)).astype(np.float32)


# ---------------------------------------------------------------------------
# Round 6 — Luminance rejection (Karis 2014 ghosting suppression)
# ---------------------------------------------------------------------------


def _luminance(rgb: "object") -> "object":
    """Rec. 709 luminance for a numpy ``(H, W, 3)`` array."""
    import numpy as np
    a = np.asarray(rgb, dtype=np.float32)
    return (
        _LUM_R * a[..., 0]
        + _LUM_G * a[..., 1]
        + _LUM_B * a[..., 2]
    ).astype(np.float32)


def luminance_rejection(
    current: "object",
    history: "object",
    threshold: float = 0.5,
) -> "object":
    """Bool mask: ``True`` where history should be rejected.

    Karis 2014 §5.4: a per-pixel ghost mask fires when
    ``|lum(cur) - lum(hist)| > threshold * max(lum(cur), lum(hist))``.
    The default ``0.5`` matches the ``UE4`` production value.
    """
    import numpy as np
    lc = _luminance(current)
    lh = _luminance(history)
    diff = np.abs(lc - lh)
    m = np.maximum(lc, lh)
    return (diff > float(threshold) * m).astype(bool)


# ---------------------------------------------------------------------------
# Round 6 — Relative depth rejection
# ---------------------------------------------------------------------------


def depth_rejection(
    current_depth: "object",
    previous_depth: "object",
    relative_threshold: float = 0.02,
) -> "object":
    """Bool mask: ``True`` where relative depth divergence exceeds threshold.

    ``reject = |prev - cur| > relative_threshold * cur``

    Camera-distance-independent — a 2 % divergence corresponds to a
    10 mm plane break at 0.5 m eye depth (roughly hand-in-front-of-face
    distance), scaling smoothly to a 2 cm break at 1 m and 20 cm at
    10 m.  This is the sprint W3 spec's ``0.02 * curr_depth`` rule.
    """
    import numpy as np
    cd = np.asarray(current_depth, dtype=np.float32)
    pd = np.asarray(previous_depth, dtype=np.float32)
    if cd.shape != pd.shape:
        raise ValueError(
            f"current_depth and previous_depth shapes differ: "
            f"{cd.shape} vs {pd.shape}"
        )
    if not float(relative_threshold) >= 0.0:
        raise ValueError(
            f"relative_threshold must be >= 0; got {relative_threshold!r}"
        )
    diff = np.abs(pd - cd)
    return (diff > float(relative_threshold) * np.abs(cd)).astype(bool)


# TaaParams std140 layout — explicit offsets pin width/height at 8 and 12
# so the executor's runtime splice helper can locate them by absolute
# byte offset without having to re-pack the whole UBO each frame.
_TAA_UBO_FIELDS = [
    UboField(name="alpha",                         dtype="f32", offset=0),
    UboField(name="sharpening",                    dtype="f32", offset=4),
    UboField(name="width",                         dtype="u32", offset=8),
    UboField(name="height",                        dtype="u32", offset=12),
    UboField(name="karis_weight",                  dtype="u32", offset=16),
    UboField(name="tight_variance_clip",           dtype="u32", offset=20),
    UboField(name="variance_clip_gamma",           dtype="f32", offset=24),
    UboField(name="reject_on_depth_disocclusion",  dtype="u32", offset=28),
    UboField(name="depth_disocclusion_threshold",  dtype="f32", offset=32),
    UboField(name="reject_on_normal_disocclusion", dtype="u32", offset=36),
    UboField(name="normal_disocclusion_threshold", dtype="f32", offset=40),
    UboField(name="_pad",                          dtype="u32", offset=44),
]


class TAAPass(PostProcessPassBase):
    label = "taa"

    # ----- PostProcessPassBase declarative schema -----
    SHADER = _SHADER
    ENTRY = _ENTRY
    PARAMS_LAYOUT = _TAA_UBO_FIELDS
    EXTRA_BINDINGS = ("frame_tex", "history_tex", "motion_tex")
    BLOB_SIZE = 48

    def __init__(
        self,
        alpha: float = 0.1,
        variance_clip_gamma: float = 1.0,
        motion_weight: float = 1.0,
        karis_weight: bool = False,
        tight_variance_clip: bool = True,
        sharpening: float = 0.0,
        reject_on_depth_disocclusion: bool = True,
        depth_disocclusion_threshold: float = 0.1,
        reject_on_normal_disocclusion: bool = True,
        normal_disocclusion_threshold: float = 0.9,
    ) -> None:
        """Construct a temporal anti-aliasing pass.

        Parameters
        ----------
        alpha
            Fraction of the current frame blended into the history each
            frame (``0.1`` ≈ 10%).
        variance_clip_gamma
            AABB tightness in stddev units, used by the round-4
            variance-based neighbourhood clip (Salvi 2016).  ``1.0`` is
            the canonical 1-sigma envelope; ``1.25`` trades some flicker
            suppression for ghosting tolerance.  Ignored when
            ``tight_variance_clip`` is ``False``.
        motion_weight
            Reserved — currently baked into the reprojection.
        karis_weight
            Karis 2014 luminance-inverse temporal blend (round 3).
        tight_variance_clip
            Round 4: when ``True`` (default since v0.3.1) the 3x3 YCoCg
            AABB is tightened to ``mean ± variance_clip_gamma * stddev``
            instead of the legacy ``min/max`` envelope.
        sharpening
            Strength of the post-resolve unsharp pass.  Default ``0.0``
            matches rounds 1-3 (no sharpening).
        reject_on_depth_disocclusion
            Round 5 (Andersson INSIDE 2015): when ``True`` (default) the
            reprojected history sample is dropped if the depth read at
            the previous-frame location differs from the current depth
            by more than ``depth_disocclusion_threshold``.
        depth_disocclusion_threshold
            NDC depth break above which the history sample is rejected.
        reject_on_normal_disocclusion
            Round 5 (Karis 2014): when ``True`` (default) the history
            sample is dropped if the surface normal at the previous-frame
            location has flipped relative to the current normal.
        normal_disocclusion_threshold
            ``dot(prev_normal, current_normal)`` below this value
            triggers rejection.

        Raises
        ------
        TypeError
            If any float param is not numeric, or any boolean flag is
            not a ``bool``.
        ValueError
            If ``alpha`` is outside ``[0, 1]``, or any non-negative
            float is negative / NaN / inf.
        """
        self.alpha = validate_unit_interval("alpha", "TAAPass", alpha)
        self.variance_clip_gamma = validate_non_negative_float(
            "variance_clip_gamma", "TAAPass", variance_clip_gamma,
        )
        self.sharpening = validate_non_negative_float(
            "sharpening", "TAAPass", sharpening,
        )
        self.motion_weight = validate_non_negative_float(
            "motion_weight", "TAAPass", motion_weight,
        )
        validate_bool("karis_weight", "TAAPass", karis_weight)
        self.karis_weight = bool(karis_weight)
        validate_bool("tight_variance_clip", "TAAPass", tight_variance_clip)
        self.tight_variance_clip = bool(tight_variance_clip)
        validate_bool(
            "reject_on_depth_disocclusion", "TAAPass",
            reject_on_depth_disocclusion,
        )
        self.reject_on_depth_disocclusion = bool(reject_on_depth_disocclusion)
        self.depth_disocclusion_threshold = validate_non_negative_float(
            "depth_disocclusion_threshold", "TAAPass",
            depth_disocclusion_threshold,
        )
        validate_bool(
            "reject_on_normal_disocclusion", "TAAPass",
            reject_on_normal_disocclusion,
        )
        self.reject_on_normal_disocclusion = bool(reject_on_normal_disocclusion)
        self.normal_disocclusion_threshold = validate_non_negative_float(
            "normal_disocclusion_threshold", "TAAPass",
            normal_disocclusion_threshold,
        )

    @classmethod
    def from_config(cls, cfg) -> "TAAPass":
        taa = cfg.rendering.taa
        return cls(
            alpha=taa.alpha,
            variance_clip_gamma=taa.variance_clip_gamma,
            motion_weight=taa.motion_weight,
            karis_weight=getattr(taa, "karis_weight", False),
            tight_variance_clip=getattr(taa, "tight_variance_clip", True),
            sharpening=getattr(taa, "sharpening", 0.0),
            reject_on_depth_disocclusion=getattr(
                taa, "reject_on_depth_disocclusion", True,
            ),
            depth_disocclusion_threshold=getattr(
                taa, "depth_disocclusion_threshold", 0.1,
            ),
            reject_on_normal_disocclusion=getattr(
                taa, "reject_on_normal_disocclusion", True,
            ),
            normal_disocclusion_threshold=getattr(
                taa, "normal_disocclusion_threshold", 0.9,
            ),
        )

    def make_pass(self, frame_tex=None, history_tex=None, motion_tex=None):
        """Build a :class:`PostProcessPass` wired to the TAA bindings.

        Accepts the legacy positional ``frame_tex, history_tex, motion_tex``
        triple so existing callers (and the ``test_postprocess_spline_sdf``
        regression suite) keep working unchanged.
        """
        return super().make_pass(
            frame_tex=frame_tex,
            history_tex=history_tex,
            motion_tex=motion_tex,
        )

    # ----- UBO field-value adapter -----
    def _field_values(self) -> dict[str, Any]:
        """Coerce booleans to u32 + pin width/height at zero for splice."""
        return {
            "alpha":                          float(self.alpha),
            "sharpening":                     float(self.sharpening),
            # width/height are spliced at dispatch time; ship 0/0 in the blob.
            "width":                          0,
            "height":                         0,
            "karis_weight":                   1 if self.karis_weight else 0,
            "tight_variance_clip":            1 if self.tight_variance_clip else 0,
            "variance_clip_gamma":            float(self.variance_clip_gamma),
            "reject_on_depth_disocclusion":   1 if self.reject_on_depth_disocclusion else 0,
            "depth_disocclusion_threshold":   float(self.depth_disocclusion_threshold),
            "reject_on_normal_disocclusion":  1 if self.reject_on_normal_disocclusion else 0,
            "normal_disocclusion_threshold":  float(self.normal_disocclusion_threshold),
            "_pad":                           0,
        }

    # ── Headless resolve (pure numpy, CPU only) ─────────────────────────────
    #
    # Mirrors the WGSL `taa_resolve_main` blend so unit tests can verify the
    # Karis vs legacy behaviour without a GPU.  This is the single source of
    # truth for the *temporal blend* step; the WGSL shader implements the
    # same arithmetic on the GPU side.
    #
    # All inputs are float32 arrays in [0, 1].  `motion_uv` is None for a
    # zero-motion case (history sampled at the same pixel).

    def resolve_numpy(
        self,
        current: "object",          # numpy.ndarray (H, W, 3) float32 in [0, 1]
        history: "object",          # numpy.ndarray (H, W, 3) float32 in [0, 1]
        motion_uv: Optional["object"] = None,  # (H, W, 2) float32 NDC offsets
        current_depth: Optional["object"] = None,    # (H, W) float32 NDC depth
        history_depth: Optional["object"] = None,    # (H, W) float32 NDC depth
        current_normal: Optional["object"] = None,   # (H, W, 3) float32 unit normals
        history_normal: Optional["object"] = None,   # (H, W, 3) float32 unit normals
        return_rejection_mask: bool = False,
    ) -> "object":
        """Pure-numpy reference of the temporal resolve step.

        Mirrors the WGSL shader except sharpening (which only affects the
        spatial pass and is orthogonal to the temporal blend under test).
        Returns an `(H, W, 3)` float32 array.  When
        ``return_rejection_mask`` is ``True`` returns ``(blended, mask)``
        where ``mask`` is an ``(H, W)`` bool array — ``True`` at pixels
        where the motion-vector-aware disocclusion test dropped the
        history sample.
        """
        import numpy as np

        cur = np.asarray(current, dtype=np.float32)
        hist = np.asarray(history, dtype=np.float32)
        if cur.shape != hist.shape or cur.ndim != 3 or cur.shape[2] != 3:
            raise ValueError(
                f"current and history must be matching (H, W, 3) arrays; "
                f"got {cur.shape} vs {hist.shape}"
            )

        h, w, _ = cur.shape

        # ── 1. Reproject the history through the motion vectors ──────────
        if motion_uv is not None:
            mv = np.asarray(motion_uv, dtype=np.float32)
            if mv.shape != (h, w, 2):
                raise ValueError(
                    f"motion_uv must be ({h}, {w}, 2); got {mv.shape}"
                )
            ys, xs = np.indices((h, w), dtype=np.float32)
            src_x_f = xs + 0.5 - mv[..., 0] * w
            src_y_f = ys + 0.5 - mv[..., 1] * h
            src_x = np.clip(src_x_f.astype(np.int32), 0, w - 1)
            src_y = np.clip(src_y_f.astype(np.int32), 0, h - 1)
            hist_reproj = hist[src_y, src_x]
        else:
            src_x = None
            src_y = None
            hist_reproj = hist

        # ── 2. YCoCg neighbourhood AABB clip (matches shader) ────────────
        padded = np.pad(cur, ((1, 1), (1, 1), (0, 0)), mode="edge")
        y = 0.25 * padded[..., 0] + 0.5 * padded[..., 1] + 0.25 * padded[..., 2]
        co = 0.5 * padded[..., 0] - 0.5 * padded[..., 2]
        cg = -0.25 * padded[..., 0] + 0.5 * padded[..., 1] - 0.25 * padded[..., 2]
        tiles_y  = [y[i:i + h, j:j + w] for i in range(3) for j in range(3)]
        tiles_co = [co[i:i + h, j:j + w] for i in range(3) for j in range(3)]
        tiles_cg = [cg[i:i + h, j:j + w] for i in range(3) for j in range(3)]
        y_min  = np.minimum.reduce(tiles_y)
        y_max  = np.maximum.reduce(tiles_y)
        co_min = np.minimum.reduce(tiles_co)
        co_max = np.maximum.reduce(tiles_co)
        cg_min = np.minimum.reduce(tiles_cg)
        cg_max = np.maximum.reduce(tiles_cg)

        if self.tight_variance_clip:
            ty  = np.stack(tiles_y,  axis=0)
            tco = np.stack(tiles_co, axis=0)
            tcg = np.stack(tiles_cg, axis=0)
            mu_y,  mu_co,  mu_cg  = ty.mean(0),  tco.mean(0),  tcg.mean(0)
            sy  = np.sqrt(np.maximum((ty  ** 2).mean(0) - mu_y  ** 2, 0.0))
            sco = np.sqrt(np.maximum((tco ** 2).mean(0) - mu_co ** 2, 0.0))
            scg = np.sqrt(np.maximum((tcg ** 2).mean(0) - mu_cg ** 2, 0.0))
            g = float(self.variance_clip_gamma)
            y_min  = np.maximum(y_min,  mu_y  - g * sy)
            y_max  = np.minimum(y_max,  mu_y  + g * sy)
            co_min = np.maximum(co_min, mu_co - g * sco)
            co_max = np.minimum(co_max, mu_co + g * sco)
            cg_min = np.maximum(cg_min, mu_cg - g * scg)
            cg_max = np.minimum(cg_max, mu_cg + g * scg)

        hr = hist_reproj[..., 0]
        hg = hist_reproj[..., 1]
        hb = hist_reproj[..., 2]
        hy = 0.25 * hr + 0.5 * hg + 0.25 * hb
        hco = 0.5 * hr - 0.5 * hb
        hcg = -0.25 * hr + 0.5 * hg - 0.25 * hb
        hy = np.clip(hy, y_min, y_max)
        hco = np.clip(hco, co_min, co_max)
        hcg = np.clip(hcg, cg_min, cg_max)
        tmp = hy - hcg
        hist_clipped = np.stack(
            [tmp + hco, hy + hcg, tmp - hco],
            axis=-1,
        )

        # ── 2b. Round 5: motion-vector-aware disocclusion rejection ──────
        rejection_mask = np.zeros((h, w), dtype=bool)
        if self.reject_on_depth_disocclusion and current_depth is not None and history_depth is not None:
            cd = np.asarray(current_depth, dtype=np.float32)
            hd = np.asarray(history_depth, dtype=np.float32)
            if cd.shape != (h, w) or hd.shape != (h, w):
                raise ValueError(
                    f"current_depth / history_depth must be ({h}, {w}); "
                    f"got {cd.shape} and {hd.shape}"
                )
            if src_x is not None:
                hd_reproj = hd[src_y, src_x]
            else:
                hd_reproj = hd
            depth_break = np.abs(hd_reproj - cd) > float(
                self.depth_disocclusion_threshold
            )
            rejection_mask |= depth_break
        if (
            self.reject_on_normal_disocclusion
            and current_normal is not None
            and history_normal is not None
        ):
            cn = np.asarray(current_normal, dtype=np.float32)
            hn = np.asarray(history_normal, dtype=np.float32)
            if cn.shape != (h, w, 3) or hn.shape != (h, w, 3):
                raise ValueError(
                    f"current_normal / history_normal must be ({h}, {w}, 3); "
                    f"got {cn.shape} and {hn.shape}"
                )
            if src_x is not None:
                hn_reproj = hn[src_y, src_x]
            else:
                hn_reproj = hn
            dot = np.sum(cn * hn_reproj, axis=-1)
            normal_break = dot < float(self.normal_disocclusion_threshold)
            rejection_mask |= normal_break
        if rejection_mask.any():
            hist_clipped = np.where(
                rejection_mask[..., None], cur, hist_clipped,
            ).astype(np.float32)

        # ── 3. Temporal blend ────────────────────────────────────────────
        alpha = float(np.clip(self.alpha, 0.0, 1.0))
        if self.karis_weight:
            lum_cur = (
                _LUM_R * cur[..., 0]
                + _LUM_G * cur[..., 1]
                + _LUM_B * cur[..., 2]
            )
            lum_hist = (
                _LUM_R * hist_clipped[..., 0]
                + _LUM_G * hist_clipped[..., 1]
                + _LUM_B * hist_clipped[..., 2]
            )
            w_cur = alpha / (1.0 + lum_cur)
            w_hist = (1.0 - alpha) / (1.0 + lum_hist)
            denom = w_cur + w_hist
            num = cur * w_cur[..., None] + hist_clipped * w_hist[..., None]
            blended = num / denom[..., None]
        else:
            blended = (1.0 - alpha) * hist_clipped + alpha * cur

        out = np.maximum(blended, 0.0).astype(np.float32)
        if return_rejection_mask:
            return out, rejection_mask
        return out
