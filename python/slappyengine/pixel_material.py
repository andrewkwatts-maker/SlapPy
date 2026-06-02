"""slappyengine.pixel_material — Per-pixel material property texture for deformable layers.

A PixelMaterialMap stores per-pixel material properties in a float32 RGBA texture.
When attached to a DeformableLayerComponent, the deform shader samples it to get
per-pixel elastic_threshold, strength, repair_rate, and material flags.

This replaces whole-asset material presets with per-pixel authored behavior.
Game code can:
  - Generate maps procedurally (weak edges, strong cockpit)
  - Load authored PNG maps (paint dark = weak, bright = strong)
  - Paint properties at runtime (repair area, damage zone)
"""
from __future__ import annotations
import enum
from pathlib import Path

import numpy as np


class MaterialFlags(enum.IntFlag):
    """Per-pixel material flags encoded in the alpha channel of PixelMaterialMap."""
    NONE         = 0
    STRUCTURAL   = 1    # load-bearing; double elastic_threshold
    GLASS        = 2    # instant plastic below threshold; radial crack
    ORGANIC      = 4    # slow elastic recovery; accumulating plastic
    NO_REPAIR    = 8    # pixel cannot be repaired (permanently destroyed area)
    ARMOR        = 16   # quadruple elastic_threshold; no crack propagation


class PixelMaterialMap:
    """Per-pixel material property texture.

    Parameters
    ----------
    width, height:
        Pixel dimensions. Must match the target deformable layer.
    threshold_range:
        (min, max) elastic_threshold values that R channel 0..1 maps to.
        Default: (5.0, 200.0) — 0.0=glass-weak, 1.0=armor-strong.
    """

    def __init__(
        self,
        width: int,
        height: int,
        threshold_range: tuple[float, float] = (5.0, 200.0),
    ) -> None:
        self._w = width
        self._h = height
        self.threshold_range = threshold_range
        # RGBA float32: R=threshold_norm, G=strength, B=repair_rate, A=flags
        self._data: np.ndarray = np.ones((height, width, 4), dtype=np.float32)
        # Default: all pixels at 50% threshold, normal strength, full repair, no flags
        self._data[:, :, 0] = 0.5   # mid-range elastic_threshold
        self._data[:, :, 1] = 1.0   # normal strength
        self._data[:, :, 2] = 1.0   # full repair rate
        self._data[:, :, 3] = 0.0   # no special flags

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def from_uniform(
        cls,
        width: int,
        height: int,
        elastic_threshold: float = 80.0,
        strength: float = 1.0,
        repair_rate: float = 1.0,
        flags: MaterialFlags = MaterialFlags.NONE,
        threshold_range: tuple[float, float] = (5.0, 200.0),
    ) -> "PixelMaterialMap":
        """Create a uniform map — same properties across all pixels."""
        m = cls(width, height, threshold_range)
        t_min, t_max = threshold_range
        norm = (elastic_threshold - t_min) / max(1.0, t_max - t_min)
        m._data[:, :, 0] = float(np.clip(norm, 0.0, 1.0))
        m._data[:, :, 1] = float(strength)
        m._data[:, :, 2] = float(repair_rate)
        m._data[:, :, 3] = float(int(flags)) / 255.0
        return m

    @classmethod
    def from_image(
        cls,
        path: str | Path,
        threshold_range: tuple[float, float] = (5.0, 200.0),
        channel_mapping: str = "RGBA",
    ) -> "PixelMaterialMap":
        """Load material map from an RGBA image file.

        Channel mapping (default RGBA):
          R → elastic_threshold_norm
          G → strength
          B → repair_rate
          A → flags (as float/255)

        For greyscale source: R channel drives threshold_norm; others default.
        """
        try:
            from PIL import Image
            img = Image.open(path).convert("RGBA")
            arr = np.array(img, dtype=np.float32) / 255.0
            h, w = arr.shape[:2]
            m = cls(w, h, threshold_range)
            m._data = arr
            return m
        except Exception as e:
            # Graceful degradation: return default map
            import warnings
            warnings.warn(f"PixelMaterialMap.from_image({path}): {e} — using defaults")
            m = cls(1, 1, threshold_range)
            return m

    # ------------------------------------------------------------------
    # Procedural painting — modify regions at runtime
    # ------------------------------------------------------------------

    def paint_rect(
        self,
        x: int, y: int, w: int, h: int,
        elastic_threshold: float | None = None,
        strength: float | None = None,
        repair_rate: float | None = None,
        flags: MaterialFlags | None = None,
    ) -> None:
        """Paint material properties onto a rectangular region."""
        x0 = max(0, x); y0 = max(0, y)
        x1 = min(self._w, x + w); y1 = min(self._h, y + h)
        if x1 <= x0 or y1 <= y0:
            return
        if elastic_threshold is not None:
            t_min, t_max = self.threshold_range
            norm = np.clip((elastic_threshold - t_min) / max(1.0, t_max - t_min), 0.0, 1.0)
            self._data[y0:y1, x0:x1, 0] = float(norm)
        if strength is not None:
            self._data[y0:y1, x0:x1, 1] = float(strength)
        if repair_rate is not None:
            self._data[y0:y1, x0:x1, 2] = float(repair_rate)
        if flags is not None:
            self._data[y0:y1, x0:x1, 3] = float(int(flags)) / 255.0

    def paint_radial(
        self,
        center_x: float,
        center_y: float,
        radius: float,
        elastic_threshold: float | None = None,
        strength: float | None = None,
        repair_rate: float | None = None,
        flags: MaterialFlags | None = None,
        falloff: bool = True,
    ) -> None:
        """Paint material properties within a circular region.

        Parameters
        ----------
        falloff:
            If True, apply cosine falloff so center gets full value and edge gets none.
            If False, uniform fill within radius.
        """
        cx, cy = float(center_x), float(center_y)
        r = max(1.0, float(radius))
        x0 = max(0, int(cx - r)); y0 = max(0, int(cy - r))
        x1 = min(self._w, int(cx + r) + 1); y1 = min(self._h, int(cy + r) + 1)
        if x1 <= x0 or y1 <= y0:
            return

        ys, xs = np.ogrid[y0:y1, x0:x1]
        dist = np.sqrt((xs - cx) ** 2 + (ys - cy) ** 2)
        mask = dist < r

        if falloff:
            t = 1.0 - dist / r
            weight = np.where(mask, t * t * (3.0 - 2.0 * t), 0.0)  # smoothstep
        else:
            weight = np.where(mask, 1.0, 0.0)

        region = self._data[y0:y1, x0:x1]
        if elastic_threshold is not None:
            t_min, t_max = self.threshold_range
            norm = float(np.clip((elastic_threshold - t_min) / max(1.0, t_max - t_min), 0.0, 1.0))
            region[:, :, 0] = region[:, :, 0] * (1.0 - weight) + norm * weight
        if strength is not None:
            region[:, :, 1] = region[:, :, 1] * (1.0 - weight) + float(strength) * weight
        if repair_rate is not None:
            region[:, :, 2] = region[:, :, 2] * (1.0 - weight) + float(repair_rate) * weight
        if flags is not None:
            region[:, :, 3] = float(int(flags)) / 255.0  # flags don't interpolate

    # ------------------------------------------------------------------
    # Per-pixel sampling (CPU side — GPU reads the raw _data texture)
    # ------------------------------------------------------------------

    def sample(self, x: int, y: int) -> dict:
        """Read material properties at pixel (x, y).

        Returns dict with keys: elastic_threshold, strength, repair_rate, flags.
        """
        px = max(0, min(self._w - 1, x))
        py = max(0, min(self._h - 1, y))
        t_min, t_max = self.threshold_range
        r, g, b, a = self._data[py, px]
        return {
            "elastic_threshold": float(t_min + r * (t_max - t_min)),
            "strength": float(g),
            "repair_rate": float(b),
            "flags": MaterialFlags(int(a * 255)),
        }

    def as_uint8_rgba(self) -> np.ndarray:
        """Return uint8 RGBA version for GPU texture upload or PIL save."""
        return np.clip(self._data * 255, 0, 255).astype(np.uint8)

    def save(self, path: str | Path) -> None:
        """Save material map as PNG for authoring/inspection."""
        try:
            from PIL import Image
            img = Image.fromarray(self.as_uint8_rgba(), "RGBA")
            img.save(path)
        except Exception:
            pass

    @property
    def width(self) -> int:
        return self._w

    @property
    def height(self) -> int:
        return self._h

    @property
    def data(self) -> np.ndarray:
        """Raw float32 RGBA array (h × w × 4). Direct GPU upload target."""
        return self._data
