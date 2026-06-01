from __future__ import annotations
import struct
from typing import Optional
from .chain import PostProcessPass
from ._validation import (
    validate_bool,
    validate_non_negative_float,
    validate_unit_interval,
)

_SHADER = "taa_resolve.wgsl"
_ENTRY  = "taa_resolve_main"

# TaaParams layout (48 bytes — round 5):
#   blend_factor                  : f32   offset  0
#   sharpening                    : f32   offset  4
#   width                         : u32   offset  8  — executor splices actual resolution at runtime
#   height                        : u32   offset 12
#   karis_weight                  : u32   offset 16  — 0 = legacy linear blend, 1 = Karis luminance-inverse weighting
#   tight_variance_clip           : u32   offset 20  — 0 = legacy min/max AABB, 1 = mean ± gamma*sigma (Salvi 2016)
#   variance_clip_gamma           : f32   offset 24  — AABB tightness in stddev units (typical 1.0 .. 1.5)
#   reject_on_depth_disocclusion  : u32   offset 28  — round 5: enable depth-break rejection (Andersson 2015)
#   depth_disocclusion_threshold  : f32   offset 32  — NDC |Δdepth| above which history is dropped
#   reject_on_normal_disocclusion : u32   offset 36  — round 5: enable normal-flip rejection (Karis 2014)
#   normal_disocclusion_threshold : f32   offset 40  — cos(angle) below which history is dropped
#   _pad                          : u32   offset 44  — keeps 16-byte uniform alignment (48 bytes total)
_TAA_PARAMS_FMT = "<ffIIIIfIfIfI"
_TAA_PARAMS_SIZE = 48

# Luminance coefficients (Rec. 709) used for the Karis weighting.
# Pre-computed at module level so the hot numpy path doesn't allocate a list.
_LUM_R = 0.2126
_LUM_G = 0.7152
_LUM_B = 0.0722


class TAAPass:
    label = "taa"

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
            instead of the legacy ``min/max`` envelope.  Massively
            reduces thin-geometry shimmer (single-pixel features) by
            ejecting stale history samples that the lax envelope would
            otherwise accept; the Sprint 3D measurement showed a 19.5%
            ghost reduction and +1 dB PSNR on disocclusion bands.  Pass
            ``False`` to restore the round-3 min/max envelope.
        sharpening
            Strength of the post-resolve unsharp pass.  Backward-compat
            default ``0.0`` matches rounds 1-3 (no sharpening).
        reject_on_depth_disocclusion
            Round 5 (Andersson INSIDE 2015): when ``True`` (default) the
            reprojected history sample is dropped if the depth read at
            the previous-frame location differs from the current depth
            by more than ``depth_disocclusion_threshold``.  The colour
            AABB cannot catch a stale sample whose colour happens to
            sit inside the current neighbourhood envelope — depth is
            the canonical secondary signal.
        depth_disocclusion_threshold
            NDC depth break above which the history sample is rejected.
            Default ``0.1`` is the Andersson 2015 recommendation for a
            ``[0, 1]`` NDC depth range; tighten to ``0.05`` for scenes
            with large depth complexity at close range.
        reject_on_normal_disocclusion
            Round 5 (Karis Siggraph 2014): when ``True`` (default) the
            history sample is dropped if the surface normal at the
            previous-frame location has flipped relative to the current
            normal.  Catches disocclusions on objects of similar depth
            (e.g. silhouette of a thin pole crossing a wall behind it).
        normal_disocclusion_threshold
            ``dot(prev_normal, current_normal)`` below this value
            triggers rejection.  Default ``0.9`` ≈ 26° tolerance, which
            is tight enough to catch genuine surface flips while
            forgiving smooth shading interpolation.

        Raises
        ------
        TypeError
            If any float param is not numeric, or ``karis_weight`` /
            ``tight_variance_clip`` /
            ``reject_on_depth_disocclusion`` /
            ``reject_on_normal_disocclusion`` is not a ``bool``.
        ValueError
            If ``alpha`` is outside ``[0, 1]``, or any non-negative float
            is negative / NaN / inf.
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
        # Normal threshold is a cosine in [-1, 1]; non-negative is the
        # only meaningful range (a negative threshold would never reject).
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

    def make_pass(self, frame_tex, history_tex, motion_tex) -> PostProcessPass:
        raw = struct.pack(
            _TAA_PARAMS_FMT,
            self.alpha,
            self.sharpening,
            0,                       # width  — executor fills these in
            0,                       # height
            1 if self.karis_weight else 0,
            1 if self.tight_variance_clip else 0,
            self.variance_clip_gamma,
            1 if self.reject_on_depth_disocclusion else 0,
            self.depth_disocclusion_threshold,
            1 if self.reject_on_normal_disocclusion else 0,
            self.normal_disocclusion_threshold,
            0,                       # _pad — keeps uniform 16-byte aligned
        )
        return PostProcessPass(
            shader_path=_SHADER,
            label=self.label,
            entry_point=_ENTRY,
            raw_params_bytes=raw,
            params={
                "frame_tex":   frame_tex,
                "history_tex": history_tex,
                "motion_tex":  motion_tex,
            },
        )

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
        # Pad with edge replication so the 3×3 window is well-defined.
        padded = np.pad(cur, ((1, 1), (1, 1), (0, 0)), mode="edge")
        y = 0.25 * padded[..., 0] + 0.5 * padded[..., 1] + 0.25 * padded[..., 2]
        co = 0.5 * padded[..., 0] - 0.5 * padded[..., 2]
        cg = -0.25 * padded[..., 0] + 0.5 * padded[..., 1] - 0.25 * padded[..., 2]
        # 3×3 min/max via a small loop — vectorised over pixels.
        tiles_y  = [y[i:i + h, j:j + w] for i in range(3) for j in range(3)]
        tiles_co = [co[i:i + h, j:j + w] for i in range(3) for j in range(3)]
        tiles_cg = [cg[i:i + h, j:j + w] for i in range(3) for j in range(3)]
        y_min  = np.minimum.reduce(tiles_y)
        y_max  = np.maximum.reduce(tiles_y)
        co_min = np.minimum.reduce(tiles_co)
        co_max = np.maximum.reduce(tiles_co)
        cg_min = np.minimum.reduce(tiles_cg)
        cg_max = np.maximum.reduce(tiles_cg)

        # Round 4: optional variance-based AABB tightening (Salvi 2016).
        # When enabled, the AABB shrinks to ``mean ± gamma * stddev``
        # which excludes single-pixel outliers from the neighbourhood
        # envelope — the canonical fix for thin-geometry shimmer.
        if self.tight_variance_clip:
            ty  = np.stack(tiles_y,  axis=0)
            tco = np.stack(tiles_co, axis=0)
            tcg = np.stack(tiles_cg, axis=0)
            mu_y,  mu_co,  mu_cg  = ty.mean(0),  tco.mean(0),  tcg.mean(0)
            # Population variance (n=9) — matches the shader's inv_n = 1/9.
            sy  = np.sqrt(np.maximum((ty  ** 2).mean(0) - mu_y  ** 2, 0.0))
            sco = np.sqrt(np.maximum((tco ** 2).mean(0) - mu_co ** 2, 0.0))
            scg = np.sqrt(np.maximum((tcg ** 2).mean(0) - mu_cg ** 2, 0.0))
            g = float(self.variance_clip_gamma)
            # Intersect with the legacy min/max envelope so the AABB
            # never *widens* beyond the safe legacy bounds.
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
        # Compare the current pixel's depth/normal to the values at the
        # reprojected previous-frame location.  When either gate trips
        # we drop the history entirely and fall back to ``cur`` — the
        # canonical first-frame recovery.
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
            # Replace rejected history pixels with the current frame, so
            # the downstream blend collapses to ``current_color`` at those
            # pixels (matches the shader's ``history_clipped = current_color``
            # branch).
            hist_clipped = np.where(
                rejection_mask[..., None], cur, hist_clipped,
            ).astype(np.float32)

        # ── 3. Temporal blend ────────────────────────────────────────────
        alpha = float(np.clip(self.alpha, 0.0, 1.0))
        if self.karis_weight:
            # Karis 2014 luminance-inverse weighting.  Bright transient
            # pixels (high luminance) get *smaller* weight in the running
            # average, so a one-frame firefly cannot drag the history toward
            # a stale brightness.  See "High Quality Temporal Supersampling"
            # for the original presentation.
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
            # Broadcast (H, W) weights over the 3 colour channels.
            num = cur * w_cur[..., None] + hist_clipped * w_hist[..., None]
            blended = num / denom[..., None]
        else:
            blended = (1.0 - alpha) * hist_clipped + alpha * cur

        out = np.maximum(blended, 0.0).astype(np.float32)
        if return_rejection_mask:
            return out, rejection_mask
        return out
