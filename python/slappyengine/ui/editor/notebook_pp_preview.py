"""Diary-themed live post-process chain preview panel — sprint EE6.

The :class:`NotebookPPPreviewPanel` gives the editor a small
scrapbook-style **before / after** viewer that shows a fixed
128 x 128 test image with the current
:class:`~slappyengine.post_process.chain_manifest.ChainManifest`
applied.  Its purpose is workflow feedback: the artist tweaks a preset
YAML on disk, hits *Refresh*, and can immediately eyeball the tonemap
/ bloom / dither difference without booting a scene.

Panel anatomy
-------------

Header row
    * Preset **dropdown** — populated from a bound
      :class:`~slappyengine.post_process.chain_baker.ChainBaker`.  When
      the dropdown value changes, :meth:`load_preset` loads that
      baked manifest and marks the preview dirty.
    * **Refresh** :class:`StickerButton` — re-runs the manifest against
      the current test image and pushes both raw + processed frames
      back into the DPG texture registry.
    * **Save Screenshot** :class:`StickerButton` — writes the processed
      image to ``~/pp_preview_<timestamp>.png``.

Body
    Two 128 x 128 previews sit side-by-side inside hand-drawn
    :class:`WashiPanel` frames with scrapbook-style labels
    ("raw" / "with chain applied") stamped above them.  A single
    :class:`HighlighterSlider` beneath drives the split ratio — the
    processed image is drawn as a wipe over the raw image so the
    artist can drag the seam left-right for a proper before/after
    comparison.

Chain manifest editor
    Below the previews a scrollable list shows every pass in the
    active manifest.  Each row has:
        * A :class:`HeartCheckbox` bound to ``PassSpec.enabled``.
        * A pencil-styled remove button.
    A trailing row hosts a **kind dropdown** + Add-pass button so
    the user can extend the manifest inline.

Auto-refresh
    Any mutation to the manifest schedules a *dirty* flag; the panel
    re-runs :func:`apply_manifest` on the next call to :meth:`tick`
    (throttled to 4 Hz so a burst of edits doesn't lock the UI).

Placeholder mode
    When no :class:`ChainBaker` is bound, the preset dropdown collapses
    to ``("<no baker>",)`` and the panel falls back to
    :data:`DEFAULT_CHAIN` — every other feature still works so
    embedding shells can start empty and attach a baker later.

Every DPG call is funnelled through ``_safe_dpg`` so the panel imports
and builds under a stub DPG in headless CI.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

import numpy as np

from slappyengine._validation import (
    validate_callable,
    validate_non_empty_str,
    validate_non_negative_int,
    validate_str,
)
from slappyengine.post_process.chain_manifest import (
    DEFAULT_CHAIN,
    KNOWN_KINDS,
    ChainManifest,
    ChainManifestError,
    PassSpec,
    apply_manifest,
)
from slappyengine.ui.widgets.doodle_separator import DoodleSeparator
from slappyengine.ui.widgets.heart_checkbox import HeartCheckbox
from slappyengine.ui.widgets.notebook_theme import (
    register_theme_listener,
    resolve_theme,
    unregister_theme_listener,
)
from slappyengine.ui.widgets.sticker_button import StickerButton


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg
        return dpg
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------


TEST_IMAGE_SIZE: int = 128
"""Side length of the reference test image (square)."""


REFRESH_INTERVAL_MS: int = 250
"""Auto-refresh throttle floor — 250 ms == 4 Hz."""


SPLIT_MIN: int = 0
SPLIT_MAX: int = 100
SPLIT_DEFAULT: int = 50
"""Split slider bounds (percentage 0..100 — left edge to right edge)."""


PLACEHOLDER_PRESET_NAME: str = "<no baker>"
"""Value inserted into the preset dropdown when no baker is bound."""


# ---------------------------------------------------------------------------
# Test image builder
# ---------------------------------------------------------------------------


def _draw_filled_circle(
    img: np.ndarray, cx: int, cy: int, radius: int, colour: Sequence[float],
) -> None:
    """Rasterise a filled circle at (*cx*, *cy*) into *img* — pure numpy."""
    h, w = img.shape[:2]
    yy, xx = np.ogrid[:h, :w]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius * radius
    img[mask] = np.array(colour, dtype=np.float32)


def _draw_filled_square(
    img: np.ndarray, x: int, y: int, size: int, colour: Sequence[float],
) -> None:
    """Rasterise a solid axis-aligned square into *img*."""
    h, w = img.shape[:2]
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(w, x + size)
    y1 = min(h, y + size)
    img[y0:y1, x0:x1] = np.array(colour, dtype=np.float32)


def _draw_filled_triangle(
    img: np.ndarray,
    p1: tuple[int, int],
    p2: tuple[int, int],
    p3: tuple[int, int],
    colour: Sequence[float],
) -> None:
    """Rasterise a filled triangle using barycentric sign tests."""
    h, w = img.shape[:2]
    ax, ay = p1
    bx, by = p2
    cx, cy = p3
    y0 = max(0, min(ay, by, cy))
    y1 = min(h, max(ay, by, cy) + 1)
    x0 = max(0, min(ax, bx, cx))
    x1 = min(w, max(ax, bx, cx) + 1)
    if y1 <= y0 or x1 <= x0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]

    def _side(px, py, qx, qy, rx, ry) -> np.ndarray:
        return (rx - qx) * (py - qy) - (ry - qy) * (px - qx)

    d1 = _side(xx, yy, ax, ay, bx, by)
    d2 = _side(xx, yy, bx, by, cx, cy)
    d3 = _side(xx, yy, cx, cy, ax, ay)
    has_neg = (d1 < 0) | (d2 < 0) | (d3 < 0)
    has_pos = (d1 > 0) | (d2 > 0) | (d3 > 0)
    mask = ~(has_neg & has_pos)
    tile = img[y0:y1, x0:x1]
    tile[mask] = np.array(colour, dtype=np.float32)
    img[y0:y1, x0:x1] = tile


def build_test_image(size: int = TEST_IMAGE_SIZE) -> np.ndarray:
    """Return the deterministic ``(size, size, 3)`` float32 test image.

    Composition:

    * A diagonal gradient across the whole canvas (red rising left-to-right,
      green rising top-to-bottom, a small constant blue) — gives tonemap
      passes something rich to compress.
    * A **red square** in the top-left quadrant.
    * A **green circle** in the top-right quadrant.
    * A **blue triangle** in the bottom-left quadrant.
    * A **white noise patch** in the bottom-right quadrant — seeded so
      every regeneration is bit-identical (needed for pixel-diff tests).

    The image is float32 in ``[0.0, 1.0]``.  Downstream passes (bloom,
    tonemap, dither) may briefly exceed 1.0 but the panel clamps before
    upload to the DPG texture registry.
    """
    if not isinstance(size, int) or size <= 0:
        raise ValueError(
            f"build_test_image: size must be a positive int; got {size!r}"
        )
    xs = np.linspace(0.0, 1.0, size, dtype=np.float32)[None, :]
    ys = np.linspace(0.0, 1.0, size, dtype=np.float32)[:, None]
    img = np.zeros((size, size, 3), dtype=np.float32)
    img[..., 0] = xs
    img[..., 1] = ys
    img[..., 2] = 0.15

    q = size // 4
    # Red square (top-left quadrant).
    _draw_filled_square(img, q // 2, q // 2, q, (1.0, 0.05, 0.05))
    # Green circle (top-right quadrant).
    _draw_filled_circle(
        img, cx=3 * q, cy=q, radius=q // 2, colour=(0.05, 1.0, 0.1),
    )
    # Blue triangle (bottom-left quadrant).
    _draw_filled_triangle(
        img,
        p1=(q // 2, 3 * q + q // 2),
        p2=(q + q // 2, 3 * q + q // 2),
        p3=(q, 3 * q - q // 2),
        colour=(0.05, 0.05, 1.0),
    )
    # White noise patch (bottom-right quadrant) — seeded RNG.
    noise = np.random.default_rng(1337).random(
        (q, q, 3), dtype=np.float32,
    )
    y0 = 3 * q - q // 2
    x0 = 3 * q - q // 2
    img[y0:y0 + q, x0:x0 + q] = noise
    return np.clip(img, 0.0, 1.0)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------


class NotebookPPPreviewPanel:
    """Live post-process chain preview panel.

    Parameters
    ----------
    baker:
        Optional :class:`~slappyengine.post_process.chain_baker.ChainBaker`.
        When provided, its baked presets populate the dropdown.  When
        omitted the panel runs in *placeholder mode* on
        :data:`DEFAULT_CHAIN`.
    refresh_interval_ms:
        Auto-refresh throttle floor in milliseconds.  Clamped to be
        ``>= 1``; the default is 250 ms (4 Hz).
    """

    TITLE = "Post-Process Preview"
    MIN_WIDTH: int = 320
    MIN_HEIGHT: int = 420

    _ROOT_TAG = "notebook_pp_preview_root"
    _RAW_TEX_TAG = "notebook_pp_preview_raw_tex"
    _PROC_TEX_TAG = "notebook_pp_preview_proc_tex"
    _RAW_IMG_TAG = "notebook_pp_preview_raw_img"
    _PROC_IMG_TAG = "notebook_pp_preview_proc_img"
    _PRESET_COMBO_TAG = "notebook_pp_preview_preset_combo"
    _SPLIT_SLIDER_TAG = "notebook_pp_preview_split"
    _PASS_LIST_TAG = "notebook_pp_preview_pass_list"
    _ADD_KIND_TAG = "notebook_pp_preview_add_kind"

    def __init__(
        self,
        *,
        baker: Any | None = None,
        refresh_interval_ms: int = REFRESH_INTERVAL_MS,
    ) -> None:
        validate_non_negative_int(
            "refresh_interval_ms", "NotebookPPPreviewPanel",
            refresh_interval_ms,
        )
        # State ---------------------------------------------------------
        self._baker: Any | None = baker
        self._refresh_interval_ms: int = max(1, int(refresh_interval_ms))
        self._test_image: np.ndarray = build_test_image()
        self._processed_image: np.ndarray = np.zeros_like(self._test_image)
        self._manifest: ChainManifest = self._clone_default()
        self._active_preset: str = PLACEHOLDER_PRESET_NAME
        self._presets: list[str] = self._collect_preset_names()
        self._split_ratio: int = SPLIT_DEFAULT
        self._dirty: bool = True
        self._elapsed_ms: float = 0.0
        self._last_refresh_at: float = 0.0
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Theme ---------------------------------------------------------
        self._theme = resolve_theme()
        register_theme_listener(self._on_theme_changed)

        # Call log (mirrors sibling panels for test assertions).
        self.call_log: list[tuple[str, Any]] = []

        # First refresh so accessors return sensible data immediately.
        try:
            self._processed_image = self._apply()
        except Exception:
            self._processed_image = self._test_image.copy()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def manifest(self) -> ChainManifest:
        return self._manifest

    @property
    def baker(self) -> Any | None:
        return self._baker

    @property
    def presets(self) -> list[str]:
        return list(self._presets)

    @property
    def active_preset(self) -> str:
        return self._active_preset

    @property
    def split_ratio(self) -> int:
        return self._split_ratio

    @property
    def refresh_interval_ms(self) -> int:
        return self._refresh_interval_ms

    @property
    def dirty(self) -> bool:
        return self._dirty

    def get_test_image(self) -> np.ndarray:
        """Return the current 128 x 128 reference image."""
        return self._test_image.copy()

    def get_processed_image(self) -> np.ndarray:
        """Return the most recent processed frame."""
        return self._processed_image.copy()

    def is_placeholder_mode(self) -> bool:
        """Return ``True`` when no :class:`ChainBaker` is bound."""
        return self._baker is None

    # ------------------------------------------------------------------
    # Setters
    # ------------------------------------------------------------------

    def set_test_image(self, image_np: np.ndarray) -> None:
        """Swap the reference image and mark the preview dirty."""
        if not isinstance(image_np, np.ndarray):
            raise TypeError(
                "NotebookPPPreviewPanel.set_test_image: image_np must be a "
                f"numpy array; got {type(image_np).__name__}"
            )
        if image_np.ndim != 3 or image_np.shape[-1] not in (3, 4):
            raise ValueError(
                "NotebookPPPreviewPanel.set_test_image: image must be "
                f"(H, W, 3|4); got shape {image_np.shape!r}"
            )
        img = np.asarray(image_np, dtype=np.float32)
        if img.shape[-1] == 4:
            img = img[..., :3]
        self._test_image = img
        self._dirty = True
        self.call_log.append(("set_test_image", img.shape))

    def set_chain_baker(self, baker: Any | None) -> None:
        """Bind (or clear) the :class:`ChainBaker` used as preset source."""
        self._baker = baker
        self._presets = self._collect_preset_names()
        self._active_preset = self._presets[0] if self._presets else PLACEHOLDER_PRESET_NAME
        self.call_log.append(("set_chain_baker", type(baker).__name__ if baker else None))
        # Reset dropdown value if the panel is already built.
        dpg = _safe_dpg()
        if dpg is not None and self._built:
            try:
                if dpg.does_item_exist(self._PRESET_COMBO_TAG):
                    dpg.configure_item(
                        self._PRESET_COMBO_TAG, items=self._presets,
                    )
                    dpg.set_value(self._PRESET_COMBO_TAG, self._active_preset)
            except Exception:
                pass
        self._dirty = True

    def set_split_ratio(self, ratio: int | float) -> int:
        """Set the split slider percentage; returns the clamped value."""
        try:
            r = int(round(float(ratio)))
        except (TypeError, ValueError) as exc:
            raise TypeError(
                "NotebookPPPreviewPanel.set_split_ratio: ratio must be "
                f"numeric; got {ratio!r}"
            ) from exc
        r = max(SPLIT_MIN, min(SPLIT_MAX, r))
        self._split_ratio = r
        self.call_log.append(("split_ratio", r))
        dpg = _safe_dpg()
        if dpg is not None and self._built:
            try:
                if dpg.does_item_exist(self._SPLIT_SLIDER_TAG):
                    dpg.set_value(self._SPLIT_SLIDER_TAG, r)
            except Exception:
                pass
        return r

    # ------------------------------------------------------------------
    # Preset loading
    # ------------------------------------------------------------------

    def _collect_preset_names(self) -> list[str]:
        if self._baker is None:
            return [PLACEHOLDER_PRESET_NAME]
        try:
            names = list(self._baker.list_baked())
        except Exception:
            names = []
        if not names:
            names = [PLACEHOLDER_PRESET_NAME]
        return names

    def load_preset(self, name: str) -> ChainManifest:
        """Load *name* from the bound baker and swap it in as active."""
        validate_non_empty_str(
            "name", "NotebookPPPreviewPanel.load_preset", name,
        )
        if self._baker is None:
            raise RuntimeError(
                "NotebookPPPreviewPanel.load_preset: no ChainBaker bound"
            )
        manifest = self._baker.load(name)
        if not isinstance(manifest, ChainManifest):
            raise TypeError(
                "NotebookPPPreviewPanel.load_preset: baker returned "
                f"{type(manifest).__name__} — expected ChainManifest"
            )
        self._manifest = manifest
        self._active_preset = name
        self._dirty = True
        self.call_log.append(("load_preset", name))
        return manifest

    # ------------------------------------------------------------------
    # Manifest mutation
    # ------------------------------------------------------------------

    def add_pass(
        self,
        kind: str,
        name: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> PassSpec:
        """Append a new :class:`PassSpec` of *kind* to the manifest."""
        validate_non_empty_str("kind", "NotebookPPPreviewPanel.add_pass", kind)
        if kind not in KNOWN_KINDS:
            raise ChainManifestError(
                f"NotebookPPPreviewPanel.add_pass: unknown kind {kind!r}; "
                f"expected one of {KNOWN_KINDS!r}"
            )
        # Auto-name to keep manifest.validate happy on repeat inserts.
        existing = {p.name for p in self._manifest.passes}
        base_name = name if isinstance(name, str) and name else kind
        candidate = base_name
        suffix = 1
        while candidate in existing:
            suffix += 1
            candidate = f"{base_name}_{suffix}"
        spec = PassSpec(
            name=candidate,
            kind=kind,
            enabled=True,
            params=dict(params or {}),
        )
        self._manifest.passes.append(spec)
        self._dirty = True
        self.call_log.append(("add_pass", (candidate, kind)))
        return spec

    def remove_pass(self, name: str) -> bool:
        """Remove the pass with *name* from the manifest.

        Also strips *name* from every remaining pass's ``depends_on`` list
        so :meth:`ChainManifest.validate` doesn't raise afterwards.
        Returns ``True`` when a pass was removed.
        """
        validate_non_empty_str(
            "name", "NotebookPPPreviewPanel.remove_pass", name,
        )
        for i, p in enumerate(self._manifest.passes):
            if p.name == name:
                self._manifest.passes.pop(i)
                # Purge stale depends_on entries.
                for other in self._manifest.passes:
                    other.depends_on = [
                        d for d in other.depends_on if d != name
                    ]
                self._dirty = True
                self.call_log.append(("remove_pass", name))
                return True
        return False

    def set_pass_enabled(self, name: str, enabled: bool) -> bool:
        """Toggle ``enabled`` on the pass named *name*; returns success."""
        validate_non_empty_str(
            "name", "NotebookPPPreviewPanel.set_pass_enabled", name,
        )
        if not isinstance(enabled, bool):
            raise TypeError(
                "NotebookPPPreviewPanel.set_pass_enabled: enabled must be "
                f"bool; got {type(enabled).__name__}"
            )
        for p in self._manifest.passes:
            if p.name == name:
                p.enabled = enabled
                self._dirty = True
                self.call_log.append(("set_pass_enabled", (name, enabled)))
                return True
        return False

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh(self) -> np.ndarray:
        """Re-run :func:`apply_manifest` and push new frames to DPG."""
        processed = self._apply()
        self._processed_image = processed
        self._dirty = False
        self._last_refresh_at = time.perf_counter()
        self.call_log.append(("refresh", None))
        self._upload_textures()
        return processed

    def _apply(self) -> np.ndarray:
        """Run the manifest against the current test image (safe)."""
        try:
            self._manifest.validate()
        except ChainManifestError:
            # Refuse to run a structurally invalid manifest — leave the
            # previous processed image visible so the user can fix the
            # error without the panel going blank.
            return self._processed_image.copy()
        try:
            out = apply_manifest(self._test_image, self._manifest)
        except Exception:
            # Handler missing / raise — surface the raw image so the
            # panel stays alive.  A UX toast layer above may surface the
            # error separately.
            return self._test_image.copy()
        return np.asarray(out, dtype=np.float32)

    def tick(self, dt_seconds: float) -> bool:
        """Advance the throttle clock; refresh at most every ``interval_ms``.

        Returns ``True`` iff a refresh actually ran on this tick.
        """
        if not isinstance(dt_seconds, (int, float)) or isinstance(dt_seconds, bool):
            raise TypeError(
                "NotebookPPPreviewPanel.tick: dt_seconds must be a number; "
                f"got {type(dt_seconds).__name__}"
            )
        if dt_seconds < 0:
            raise ValueError(
                "NotebookPPPreviewPanel.tick: dt_seconds must be >= 0; "
                f"got {dt_seconds!r}"
            )
        self._elapsed_ms += float(dt_seconds) * 1000.0
        if self._elapsed_ms < self._refresh_interval_ms:
            return False
        self._elapsed_ms = 0.0
        if not self._dirty:
            return False
        self.refresh()
        return True

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------

    def save_screenshot(self, path: str | Path) -> Path:
        """Write the current processed image to *path* as PNG.

        Uses PIL when available; falls back to a simple numpy .npy dump
        (with a ``.png`` extension coerced to ``.npy``) when the imaging
        extra is missing so headless CI never crashes.
        """
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        arr = np.clip(self._processed_image, 0.0, 1.0)
        rgb8 = (arr * 255.0 + 0.5).astype(np.uint8)
        try:
            from PIL import Image
        except Exception:
            fallback = target.with_suffix(".npy")
            np.save(fallback, rgb8)
            self.call_log.append(("save_screenshot", str(fallback)))
            return fallback
        Image.fromarray(rgb8, mode="RGB").save(target)
        self.call_log.append(("save_screenshot", str(target)))
        return target

    # ------------------------------------------------------------------
    # Theme listener
    # ------------------------------------------------------------------

    def _on_theme_changed(self, _theme: Any) -> None:
        self._theme = resolve_theme()
        self.call_log.append(("theme_changed", None))

    # ------------------------------------------------------------------
    # Build / destroy
    # ------------------------------------------------------------------

    def build(self, parent_tag: str | int) -> None:
        """Render the panel under *parent_tag*."""
        dpg = _safe_dpg()
        self._parent_tag = parent_tag

        if dpg is None:
            self._built = True
            return

        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        washi = list(self._theme.color("washi", (180, 200, 230, 255)))
        accent = list(self._theme.color("accent", (220, 120, 160, 255)))

        try:
            with dpg.group(tag=self._ROOT_TAG, parent=parent_tag):
                try:
                    dpg.add_text(self.TITLE, color=ink)
                except Exception:
                    pass
                try:
                    dpg.add_text("~~~~~~~~~~~~~~~~~~~~~~~", color=washi)
                except Exception:
                    pass

                # ── Header row --------------------------------------
                try:
                    with dpg.group(horizontal=True):
                        try:
                            dpg.add_combo(
                                items=self._presets,
                                default_value=self._active_preset,
                                callback=self._on_preset_changed,
                                tag=self._PRESET_COMBO_TAG,
                                width=140,
                                label="preset",
                            )
                        except Exception:
                            pass
                        try:
                            StickerButton(
                                label="Refresh",
                                sticker_icon="fox",
                                callback=self._on_refresh_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                        try:
                            StickerButton(
                                label="Save Screenshot",
                                sticker_icon="butterfly",
                                callback=self._on_screenshot_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                except Exception:
                    pass

                try:
                    DoodleSeparator("wavy").build(self._ROOT_TAG)
                except Exception:
                    pass

                # ── Preview textures --------------------------------
                # Register the raw + processed textures inside a texture
                # registry so the ``add_image`` widgets below have targets
                # to bind against.
                try:
                    with dpg.texture_registry(show=False):
                        try:
                            dpg.add_dynamic_texture(
                                TEST_IMAGE_SIZE,
                                TEST_IMAGE_SIZE,
                                self._flatten(self._test_image),
                                tag=self._RAW_TEX_TAG,
                            )
                        except Exception:
                            pass
                        try:
                            dpg.add_dynamic_texture(
                                TEST_IMAGE_SIZE,
                                TEST_IMAGE_SIZE,
                                self._flatten(self._processed_image),
                                tag=self._PROC_TEX_TAG,
                            )
                        except Exception:
                            pass
                except Exception:
                    pass

                # ── Two-image side-by-side --------------------------
                try:
                    with dpg.group(horizontal=True):
                        try:
                            with dpg.group():
                                try:
                                    dpg.add_text("raw", color=accent)
                                except Exception:
                                    pass
                                try:
                                    dpg.add_image(
                                        self._RAW_TEX_TAG,
                                        width=TEST_IMAGE_SIZE,
                                        height=TEST_IMAGE_SIZE,
                                        tag=self._RAW_IMG_TAG,
                                    )
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        try:
                            with dpg.group():
                                try:
                                    dpg.add_text("with chain", color=accent)
                                except Exception:
                                    pass
                                try:
                                    dpg.add_image(
                                        self._PROC_TEX_TAG,
                                        width=TEST_IMAGE_SIZE,
                                        height=TEST_IMAGE_SIZE,
                                        tag=self._PROC_IMG_TAG,
                                    )
                                except Exception:
                                    pass
                        except Exception:
                            pass
                except Exception:
                    pass

                # ── Split slider ------------------------------------
                try:
                    dpg.add_slider_int(
                        label="split %",
                        default_value=self._split_ratio,
                        min_value=SPLIT_MIN,
                        max_value=SPLIT_MAX,
                        callback=self._on_split_changed,
                        tag=self._SPLIT_SLIDER_TAG,
                        width=260,
                    )
                except Exception:
                    pass

                try:
                    DoodleSeparator("dotted").build(self._ROOT_TAG)
                except Exception:
                    pass

                # ── Manifest editor ---------------------------------
                try:
                    dpg.add_text("passes", color=ink)
                except Exception:
                    pass
                try:
                    with dpg.group(tag=self._PASS_LIST_TAG):
                        self._build_pass_rows()
                except Exception:
                    self._build_pass_rows()

                # ── Add-pass row ------------------------------------
                try:
                    with dpg.group(horizontal=True):
                        try:
                            dpg.add_combo(
                                items=list(KNOWN_KINDS),
                                default_value=KNOWN_KINDS[0],
                                tag=self._ADD_KIND_TAG,
                                width=110,
                                label="kind",
                            )
                        except Exception:
                            pass
                        try:
                            StickerButton(
                                label="Add pass",
                                sticker_icon="bunny",
                                callback=self._on_add_pass_clicked,
                            ).build(self._ROOT_TAG)
                        except Exception:
                            pass
                except Exception:
                    pass

        except Exception:
            try:
                dpg.add_text(self.TITLE, parent=parent_tag)
            except Exception:
                pass

        self._built = True

    def destroy(self) -> None:
        """Detach the theme listener + clear built flag."""
        try:
            unregister_theme_listener(self._on_theme_changed)
        except Exception:
            pass
        self._built = False

    # ------------------------------------------------------------------
    # MovablePanelWindow helper
    # ------------------------------------------------------------------

    def wrap_in_window(self, **kwargs: Any) -> Any:
        """Return a :class:`MovablePanelWindow` around this panel."""
        from slappyengine.ui.editor.movable_panel import MovablePanelWindow
        return MovablePanelWindow(self, title=self.TITLE, **kwargs)

    # ------------------------------------------------------------------
    # Row rendering
    # ------------------------------------------------------------------

    def _build_pass_rows(self) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        if not self._manifest.passes:
            try:
                dpg.add_text("(empty manifest)")
            except Exception:
                pass
            return
        for spec in list(self._manifest.passes):
            self._build_pass_row(spec)

    def _build_pass_row(self, spec: PassSpec) -> None:
        dpg = _safe_dpg()
        if dpg is None:
            return
        ink = list(self._theme.color("ink", (40, 40, 60, 255)))
        try:
            with dpg.group(horizontal=True):
                try:
                    HeartCheckbox(
                        default_value=spec.enabled,
                        callback=lambda s, v, u, n=spec.name: self._on_enable_toggle(n, v),
                    ).build(self._PASS_LIST_TAG)
                except Exception:
                    pass
                try:
                    dpg.add_text(f"{spec.name} ({spec.kind})", color=ink)
                except Exception:
                    pass
                try:
                    StickerButton(
                        label="x",
                        sticker_icon="fox",
                        callback=lambda s=None, a=None, u=None, n=spec.name: self._on_remove_clicked(n),
                    ).build(self._PASS_LIST_TAG)
                except Exception:
                    pass
        except Exception:
            pass

    def _rebuild_pass_list(self) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if not dpg.does_item_exist(self._PASS_LIST_TAG):
                return
            for child in list(dpg.get_item_children(self._PASS_LIST_TAG, slot=1) or []):
                try:
                    dpg.delete_item(child)
                except Exception:
                    pass
            with dpg.group(parent=self._PASS_LIST_TAG):
                self._build_pass_rows()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_preset_changed(
        self, sender: Any, app_data: Any, user_data: Any,
    ) -> None:
        if not isinstance(app_data, str) or app_data == PLACEHOLDER_PRESET_NAME:
            return
        try:
            self.load_preset(app_data)
        except Exception:
            return
        self._rebuild_pass_list()
        try:
            self.refresh()
        except Exception:
            pass

    def _on_refresh_clicked(self, *_a: Any, **_kw: Any) -> None:
        try:
            self.refresh()
        except Exception:
            pass

    def _on_screenshot_clicked(self, *_a: Any, **_kw: Any) -> None:
        try:
            target = Path.home() / f"pp_preview_{int(time.time())}.png"
            self.save_screenshot(target)
        except Exception:
            pass

    def _on_split_changed(
        self, sender: Any, app_data: Any, user_data: Any,
    ) -> None:
        try:
            self.set_split_ratio(int(app_data))
        except Exception:
            pass

    def _on_add_pass_clicked(self, *_a: Any, **_kw: Any) -> None:
        dpg = _safe_dpg()
        kind = KNOWN_KINDS[0]
        if dpg is not None:
            try:
                if dpg.does_item_exist(self._ADD_KIND_TAG):
                    val = dpg.get_value(self._ADD_KIND_TAG)
                    if isinstance(val, str) and val:
                        kind = val
            except Exception:
                pass
        try:
            self.add_pass(kind)
        except Exception:
            return
        self._rebuild_pass_list()

    def _on_remove_clicked(self, name: str) -> None:
        self.remove_pass(name)
        self._rebuild_pass_list()

    def _on_enable_toggle(self, name: str, value: Any) -> None:
        try:
            self.set_pass_enabled(name, bool(value))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Texture upload
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten(image: np.ndarray) -> list[float]:
        """Return a flat RGBA float32 buffer for the DPG texture registry."""
        arr = np.asarray(image, dtype=np.float32)
        h, w = arr.shape[:2]
        rgba = np.ones((h, w, 4), dtype=np.float32)
        rgba[..., :3] = np.clip(arr, 0.0, 1.0)
        return rgba.reshape(-1).tolist()

    def _upload_textures(self) -> None:
        dpg = _safe_dpg()
        if dpg is None or not self._built:
            return
        try:
            if dpg.does_item_exist(self._RAW_TEX_TAG):
                dpg.set_value(self._RAW_TEX_TAG, self._flatten(self._test_image))
        except Exception:
            pass
        try:
            if dpg.does_item_exist(self._PROC_TEX_TAG):
                dpg.set_value(self._PROC_TEX_TAG, self._flatten(self._processed_image))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    @staticmethod
    def _clone_default() -> ChainManifest:
        """Return a mutable copy of :data:`DEFAULT_CHAIN`."""
        return ChainManifest(
            passes=[
                PassSpec(
                    name=p.name,
                    kind=p.kind,
                    enabled=p.enabled,
                    params=dict(p.params),
                    depends_on=list(p.depends_on),
                )
                for p in DEFAULT_CHAIN.passes
            ]
        )


__all__ = [
    "NotebookPPPreviewPanel",
    "PLACEHOLDER_PRESET_NAME",
    "REFRESH_INTERVAL_MS",
    "SPLIT_DEFAULT",
    "SPLIT_MAX",
    "SPLIT_MIN",
    "TEST_IMAGE_SIZE",
    "build_test_image",
]
