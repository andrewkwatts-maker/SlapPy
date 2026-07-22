"""On-frame debug HUD overlay for a :class:`PhysicsWorld`.

Renders scene metrics (frame index, body count, contact count, total
mass, kinetic energy, accumulated heat, last sub-step count) as ASCII
text in the top-left corner of an RGBA frame.  Uses PIL's default
bitmap font so no external font files are required and the output is
purely English (no Unicode emoji, no special glyphs).

The HUD never mutates the world; it reads ``world.bodies`` /
``world._last_substeps`` / cell heat fields.  Bodies whose ``cells``
attribute is ``None`` (T0/T1 placeholder hulls) are skipped for the
heat sum.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


# Cell channel index for the heat field.  Mirrors render.py / cell.py.
_HEAT_CHANNEL = 12


@dataclass
class DebugHUD:
    """Overlay scene metrics on an RGBA frame.

    All ``show_*`` toggles default to ``True``.  When *every* toggle is
    ``False``, :meth:`render` still draws the background panel (so the
    HUD remains visually present and callers can detect that it ran).
    """
    show_frame_number: bool = True
    show_body_count: bool = True
    show_contact_count: bool = True
    show_mass: bool = True
    show_energy: bool = True
    show_heat: bool = True
    show_substeps: bool = True
    position: tuple[int, int] = (8, 8)
    text_color: tuple[int, int, int] = (255, 255, 255)
    background_color: tuple[int, int, int, int] = (0, 0, 0, 128)
    # Pixel padding around the text inside the background panel.
    padding: int = 4
    # Vertical pixels per text line (matches PIL default font height + gap).
    line_height: int = 12

    # --- public API ---------------------------------------------------------

    def render(
        self,
        frame: np.ndarray,
        world: Any,
        frame_idx: int = 0,
        contact_count: int = 0,
    ) -> np.ndarray:
        """Draw the HUD onto ``frame`` and return the modified array.

        ``frame`` may be ``(H, W, 3)`` or ``(H, W, 4)`` ``uint8``.  The
        return value is always RGBA.  The input array is modified in
        place when it is already RGBA; otherwise a new RGBA copy is
        returned.
        """
        from PIL import Image, ImageDraw, ImageFont

        if frame.ndim != 3 or frame.shape[2] not in (3, 4):
            raise ValueError(
                f"frame must be (H, W, 3) or (H, W, 4); got {frame.shape}"
            )
        if frame.dtype != np.uint8:
            frame = np.clip(frame, 0, 255).astype(np.uint8)
        if frame.shape[2] == 3:
            h, w, _ = frame.shape
            rgba = np.empty((h, w, 4), dtype=np.uint8)
            rgba[..., :3] = frame
            rgba[..., 3] = 255
        else:
            rgba = frame

        lines = self._build_lines(world, frame_idx, contact_count)
        font = ImageFont.load_default()

        # Compute panel size.  We always draw at least a 1-line tall
        # panel so toggling everything off still shows the background.
        text_w = 0
        for line in lines:
            try:
                bbox = font.getbbox(line)
                lw = bbox[2] - bbox[0]
            except AttributeError:
                lw = font.getsize(line)[0]  # type: ignore[attr-defined]
            text_w = max(text_w, lw)
        n_lines = max(1, len(lines))
        panel_w = text_w + 2 * self.padding if lines else 80
        panel_h = n_lines * self.line_height + 2 * self.padding

        img = Image.fromarray(rgba, mode="RGBA")
        # Use a separate RGBA layer for the semi-transparent panel so the
        # alpha actually composites with the source frame.
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        x, y = self.position
        draw.rectangle(
            [x, y, x + panel_w, y + panel_h],
            fill=tuple(self.background_color),
        )
        text_x = x + self.padding
        text_y = y + self.padding
        for i, line in enumerate(lines):
            draw.text(
                (text_x, text_y + i * self.line_height),
                line,
                fill=tuple(self.text_color),
                font=font,
            )
        composed = Image.alpha_composite(img, overlay)
        return np.array(composed, dtype=np.uint8)

    # --- helpers ------------------------------------------------------------

    def _build_lines(
        self,
        world: Any,
        frame_idx: int,
        contact_count: int,
    ) -> list[str]:
        """Compose the list of text lines based on the toggles + metrics."""
        bodies = list(getattr(world, "bodies", []) or [])
        lines: list[str] = []

        if self.show_frame_number:
            lines.append(f"frame: {int(frame_idx)}")
        if self.show_body_count:
            lines.append(f"bodies: {len(bodies)}")
        if self.show_contact_count:
            lines.append(f"contacts: {int(contact_count)}")
        if self.show_mass:
            lines.append(f"mass: {self._total_mass(bodies):.2f}")
        if self.show_energy:
            lines.append(f"energy: {self._total_kinetic_energy(bodies):.2f}")
        if self.show_heat:
            lines.append(f"heat: {self._total_heat(bodies):.2f}")
        if self.show_substeps:
            substeps = int(getattr(world, "_last_substeps", 0) or 0)
            lines.append(f"substeps: {substeps}")
        return lines

    @staticmethod
    def _total_mass(bodies: list[Any]) -> float:
        total = 0.0
        for b in bodies:
            try:
                total += float(b.mass)
            except Exception:
                continue
        return total

    @staticmethod
    def _total_kinetic_energy(bodies: list[Any]) -> float:
        total = 0.0
        for b in bodies:
            try:
                m = float(b.mass)
                vx, vy = b.velocity
                total += 0.5 * m * (float(vx) ** 2 + float(vy) ** 2)
            except Exception:
                continue
        return total

    @staticmethod
    def _total_heat(bodies: list[Any]) -> float:
        total = 0.0
        for b in bodies:
            cells = getattr(b, "cells", None)
            if cells is None:
                continue
            try:
                if cells.ndim == 3 and cells.shape[2] > _HEAT_CHANNEL:
                    total += float(cells[..., _HEAT_CHANNEL].sum())
            except Exception:
                continue
        return total


__all__ = ["DebugHUD"]
