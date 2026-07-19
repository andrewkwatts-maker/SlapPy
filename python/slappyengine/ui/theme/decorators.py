"""Theme decorators — panel-level overlay compositors.

The most important entry point here is :class:`PanelDecorator`. It
combines the primitive procedural assets (edge strokes, page linings,
washi tape, nine-slice) into ready-to-stamp overlay images for a single
editor panel.

Only :class:`PanelDecorator` is required by the notebook theme sprint —
the class applies :func:`~slappyengine.ui.theme.edge_strokes.render_edge_stroke`
as a 4-tile overlay (top / bottom / left / right strips) around a panel
rectangle. The overlay is a single ``(H, W, 4)`` RGBA ``uint8`` array
whose interior alpha is ``0`` so the panel content shows through.

Design notes
------------
The decorator is pure numpy — no DPG dependency — so headless tests can
call :meth:`PanelDecorator.build_edge_overlay` directly. The DPG bridge
consumes the returned array via ``dpg.add_raw_texture``; that plumbing
lives in :mod:`slappyengine.ui.theme.dpg_bridge`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from slappyengine._validation import (
    validate_non_empty_str,
    validate_positive_int,
)

from .edge_strokes import EDGE_STROKE_PRESETS, render_edge_stroke


# ---------------------------------------------------------------------------
# PanelDecorator
# ---------------------------------------------------------------------------


@dataclass
class PanelDecorator:
    """Compose the four edge strips into a single panel-overlay image.

    Parameters
    ----------
    edge_stroke_preset:
        A key from :data:`~slappyengine.ui.theme.edge_strokes.EDGE_STROKE_PRESETS`.
        Defaults to ``"ink_thin"`` — the least visually intrusive.
    stroke_thickness_px:
        Border thickness in pixels. Defaults to ``3``.
    ink_rgba:
        Optional ink-colour override. If ``None`` the preset's default
        is used.
    """

    edge_stroke_preset: str = "ink_thin"
    stroke_thickness_px: int = 3
    ink_rgba: tuple[int, int, int, int] | None = None

    def __post_init__(self) -> None:
        validate_non_empty_str(
            "edge_stroke_preset", "PanelDecorator", self.edge_stroke_preset
        )
        if self.edge_stroke_preset not in EDGE_STROKE_PRESETS:
            available = ", ".join(sorted(EDGE_STROKE_PRESETS)) or "(none)"
            raise KeyError(
                f"PanelDecorator: unknown edge_stroke_preset "
                f"{self.edge_stroke_preset!r}; available: {available}"
            )
        self.stroke_thickness_px = int(
            validate_positive_int(
                "stroke_thickness_px", "PanelDecorator", self.stroke_thickness_px
            )
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_edge_overlay(
        self,
        panel_width: int,
        panel_height: int,
    ) -> np.ndarray:
        """Render a single panel-sized RGBA overlay.

        The returned array has shape ``(panel_height, panel_width, 4)``
        ``uint8`` with alpha ``0`` in the interior and stroke pixels in
        a border ``stroke_thickness_px`` thick around all four edges.

        Corners are painted twice (once by the horizontal strip and once
        by the vertical). The vertical wins — this keeps corner alpha
        consistent across presets that stack multiple sub-rows.
        """
        w = validate_positive_int(
            "panel_width", "PanelDecorator.build_edge_overlay", int(panel_width)
        )
        h = validate_positive_int(
            "panel_height", "PanelDecorator.build_edge_overlay", int(panel_height)
        )
        t = self.stroke_thickness_px
        overlay = np.zeros((h, w, 4), dtype=np.uint8)

        # Horizontal strip: (t, w, 4). The preset renderer paints both
        # edges when we ask for a "wide, short" strip.
        horizontal_strip_h = min(t, max(1, h // 2))
        h_strip_full = render_edge_stroke(
            self.edge_stroke_preset,
            w,
            horizontal_strip_h,
            ink_rgba=self.ink_rgba,
        )
        # h_strip_full has the top rows painted and (if the strip is
        # thick enough) the bottom rows too. Copy top rows onto the
        # panel top and reversed rows onto the panel bottom.
        overlay[:horizontal_strip_h, :, :] = h_strip_full
        overlay[-horizontal_strip_h:, :, :] = h_strip_full[::-1]

        # Vertical strip: (h, t, 4). Same trick, oriented tall + narrow.
        vertical_strip_w = min(t, max(1, w // 2))
        v_strip_full = render_edge_stroke(
            self.edge_stroke_preset,
            vertical_strip_w,
            h,
            ink_rgba=self.ink_rgba,
        )
        overlay[:, :vertical_strip_w, :] = v_strip_full
        overlay[:, -vertical_strip_w:, :] = v_strip_full[:, ::-1]

        return overlay

    def build_edge_tiles(
        self,
        panel_width: int,
        panel_height: int,
    ) -> dict[str, np.ndarray]:
        """Return the four edge strips separately.

        Same content as :meth:`build_edge_overlay` but split into a
        ``{"top", "bottom", "left", "right"}`` dict — matches the shape
        the DPG bridge historically consumes for
        :func:`~slappyengine.ui.theme.edge_strokes.render_stroke_border`.
        """
        overlay = self.build_edge_overlay(panel_width, panel_height)
        t = self.stroke_thickness_px
        h_strip_h = min(t, max(1, panel_height // 2))
        v_strip_w = min(t, max(1, panel_width // 2))
        return {
            "top": overlay[:h_strip_h, :, :].copy(),
            "bottom": overlay[-h_strip_h:, :, :].copy(),
            "left": overlay[:, :v_strip_w, :].copy(),
            "right": overlay[:, -v_strip_w:, :].copy(),
        }


__all__ = ["PanelDecorator"]
