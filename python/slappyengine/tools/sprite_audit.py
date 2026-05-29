"""Sprite audit & regenerate tooling — generic counterpart of
``docs/sprite_audit_recipe.md``.

The recipe doc captures the human-readable procedure that was used to fix
Ochema Circuit's washed-out vehicle topdown sprite. This module lifts the
repeatable mechanics out of the doc into a programmatic API so any downstream
game can:

  * inventory a folder of sprites and dump a markdown table of metrics
  * walk a fallback chain and identify which sprite is actually loading
  * render a sprite at N× nearest-neighbour zoom for visual inspection
  * produce a side-by-side OLD | NEW comparison image
  * score a sprite against simple "is this washed out / too small" heuristics

All operations are headless and depend only on Pillow.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

from ._sprite_audit_validation import (
    validate_inventory_entry,
    validate_pathlike,
    validate_pattern_list,
    validate_positive_int,
    validate_rgba_tuple,
)

__all__ = [
    "SpriteInventoryEntry",
    "inventory_sprites",
    "write_inventory_markdown",
    "first_hit",
    "render_zoom",
    "make_before_after",
    "assess_quality",
    # Threshold constants — exported for callers who want to override.
    "ALPHA_COVERAGE_CUTOFF",
    "SATURATION_CUTOFF",
    "MIN_DIMENSION_CUTOFF",
]


# ---------------------------------------------------------------------------
# Quality-heuristic thresholds (single source of truth — exported above)
# ---------------------------------------------------------------------------

#: Below this fraction of opaque pixels we flag the sprite as having holes
#: in its body (classic chroma-key-bled-into-foreground failure mode).
ALPHA_COVERAGE_CUTOFF: float = 0.55

#: Below this saturation (computed as max(R,G,B) - min(R,G,B) on opaque
#: pixels, in 0-255) we flag the sprite as washed-out / desaturated.
SATURATION_CUTOFF: int = 60

#: Below this dimension on either axis we flag the sprite as too small to
#: read at typical UI scale.
MIN_DIMENSION_CUTOFF: int = 64


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class SpriteInventoryEntry:
    """Single row in the inventory table.

    ``mean_rgb`` is computed across **opaque** pixels only so that a wide
    transparent margin does not dilute the average colour.
    ``alpha_coverage`` is the fraction of pixels with alpha > 0 (range [0, 1]).
    """

    path: Path
    width: int
    height: int
    has_alpha: bool
    mean_rgb: tuple[int, int, int]
    alpha_coverage: float
    file_size_bytes: int


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def _measure_sprite(path: Path) -> SpriteInventoryEntry:
    """Open ``path`` with Pillow + numpy and compute the inventory metrics."""
    from PIL import Image
    import numpy as np

    img = Image.open(path)
    mode = img.mode
    has_alpha = ("A" in mode) or (mode == "P" and "transparency" in img.info)
    img = img.convert("RGBA")
    arr = np.asarray(img)  # (H, W, 4)
    h, w = arr.shape[:2]

    alpha = arr[..., 3]
    opaque_mask = alpha > 0
    coverage = float(opaque_mask.mean()) if opaque_mask.size else 0.0

    if opaque_mask.any():
        rgb = arr[..., :3][opaque_mask]
        mean = rgb.mean(axis=0)
        mean_rgb = (int(mean[0]), int(mean[1]), int(mean[2]))
    else:
        mean_rgb = (0, 0, 0)

    size = path.stat().st_size

    return SpriteInventoryEntry(
        path=path,
        width=int(w),
        height=int(h),
        has_alpha=bool(has_alpha),
        mean_rgb=mean_rgb,
        alpha_coverage=coverage,
        file_size_bytes=int(size),
    )


def inventory_sprites(
    root: Path,
    patterns: list[str],
) -> list[SpriteInventoryEntry]:
    """Walk ``root`` (recursively), match files against any of ``patterns``
    (glob syntax — e.g. ``"vehicle_*.png"``), open each with Pillow, and
    return inventory entries sorted by ``alpha_coverage`` descending.

    Files that fail to open are silently skipped — broken images should not
    abort the whole audit.

    Raises
    ------
    TypeError
        If ``root`` is not str / os.PathLike, or ``patterns`` is not a list
        of strings.
    """
    root = validate_pathlike("root", "inventory_sprites", root)
    validate_pattern_list("patterns", "inventory_sprites", patterns)
    if not root.is_dir():
        return []

    matched: set[Path] = set()
    for pat in patterns:
        for hit in root.rglob(pat):
            if hit.is_file():
                matched.add(hit.resolve())

    entries: list[SpriteInventoryEntry] = []
    for p in sorted(matched):
        try:
            entries.append(_measure_sprite(p))
        except Exception:
            # Corrupt PNG / unsupported mode — skip rather than abort.
            continue

    entries.sort(key=lambda e: e.alpha_coverage, reverse=True)
    return entries


def write_inventory_markdown(
    entries: list[SpriteInventoryEntry],
    output: Path,
) -> None:
    """Write a markdown table — one row per sprite, columns matching the
    dataclass fields. Creates parent dirs if needed.
    """
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)

    header = (
        "| path | width | height | has_alpha | mean_rgb | alpha_coverage | "
        "file_size_bytes |"
    )
    sep = (
        "| --- | --- | --- | --- | --- | --- | --- |"
    )

    rows: list[str] = []
    for e in entries:
        rgb = f"({e.mean_rgb[0]}, {e.mean_rgb[1]}, {e.mean_rgb[2]})"
        rows.append(
            f"| {e.path} | {e.width} | {e.height} | {e.has_alpha} | "
            f"{rgb} | {e.alpha_coverage:.3f} | {e.file_size_bytes} |"
        )

    body = "\n".join([header, sep, *rows]) + "\n"
    output.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# Fallback-chain resolution
# ---------------------------------------------------------------------------

def first_hit(
    fallback_chain: list[str],
    search_dirs: list[Path],
) -> Path | None:
    """Replicate the "first existing file in the candidate list wins" pattern
    used by typical sprite loaders (e.g. menu.py-style fallbacks).

    For each filename in ``fallback_chain``, try each directory in
    ``search_dirs`` in order. Return the first path that exists, or ``None``
    if nothing matches.
    """
    for name in fallback_chain:
        for d in search_dirs:
            candidate = Path(d) / name
            if candidate.is_file():
                return candidate
    return None


# ---------------------------------------------------------------------------
# Visualisation helpers
# ---------------------------------------------------------------------------

def render_zoom(
    image_path: Path,
    zoom: int,
    output: Path,
    bg_color: tuple[int, int, int, int] = (10, 14, 20, 255),
) -> None:
    """Paste the sprite over ``bg_color`` and upscale by ``zoom`` using
    nearest-neighbour so individual pixels stay crisp. Save to ``output``.

    Raises
    ------
    TypeError
        If ``image_path`` / ``output`` are not str / os.PathLike, ``zoom``
        is not an int, or ``bg_color`` is not a 4-sequence of ints.
    ValueError
        If ``zoom < 1``, ``bg_color`` is not length 4, or any
        ``bg_color`` channel is outside ``[0, 255]``.
    """
    image_path = validate_pathlike("image_path", "render_zoom", image_path)
    output = validate_pathlike("output", "render_zoom", output)
    validate_positive_int("zoom", "render_zoom", zoom)
    bg_color = validate_rgba_tuple("bg_color", "render_zoom", bg_color)
    from PIL import Image

    output.parent.mkdir(parents=True, exist_ok=True)

    sprite = Image.open(image_path).convert("RGBA")
    bg = Image.new("RGBA", sprite.size, bg_color)
    bg.alpha_composite(sprite)

    w, h = bg.size
    zoomed = bg.resize((w * zoom, h * zoom), Image.NEAREST)
    zoomed.save(output)


def _label_strip(text: str, width: int, height: int = 24) -> "Any":
    """Render a small text label at the top of the strip."""
    from PIL import Image, ImageDraw

    strip = Image.new("RGBA", (width, height), (10, 14, 20, 255))
    draw = ImageDraw.Draw(strip)
    # Default Pillow font — always available, no external dependency.
    draw.text((4, 4), text, fill=(255, 190, 40, 255))
    return strip


def make_before_after(
    old_path: Path,
    new_path: Path,
    output: Path,
    zoom: int = 4,
) -> None:
    """Side-by-side OLD | NEW comparison: labelled OLD strip + old sprite at
    ``zoom``, a small gap, then labelled NEW strip + new sprite at ``zoom``.
    Useful for change verification.

    Raises
    ------
    TypeError
        If any of ``old_path``, ``new_path``, ``output`` is not str /
        os.PathLike, or ``zoom`` is not an int.
    ValueError
        If ``zoom < 1``.
    """
    old_path = validate_pathlike("old_path", "make_before_after", old_path)
    new_path = validate_pathlike("new_path", "make_before_after", new_path)
    output = validate_pathlike("output", "make_before_after", output)
    validate_positive_int("zoom", "make_before_after", zoom)
    from PIL import Image

    output.parent.mkdir(parents=True, exist_ok=True)

    bg = (10, 14, 20, 255)
    gap = 16

    old_sprite = Image.open(old_path).convert("RGBA")
    new_sprite = Image.open(new_path).convert("RGBA")

    def _compose(sprite: "Image.Image") -> "Image.Image":
        w, h = sprite.size
        base = Image.new("RGBA", (w, h), bg)
        base.alpha_composite(sprite)
        return base.resize((w * zoom, h * zoom), Image.NEAREST)

    old_zoom = _compose(old_sprite)
    new_zoom = _compose(new_sprite)

    panel_w = max(old_zoom.width, new_zoom.width)
    label_h = 24
    old_label = _label_strip("OLD", panel_w, label_h)
    new_label = _label_strip("NEW", panel_w, label_h)

    def _stack(label, img):
        h = label_h + img.height
        col = Image.new("RGBA", (panel_w, h), bg)
        col.alpha_composite(label, (0, 0))
        col.alpha_composite(img, ((panel_w - img.width) // 2, label_h))
        return col

    left = _stack(old_label, old_zoom)
    right = _stack(new_label, new_zoom)

    total_w = left.width + gap + right.width
    total_h = max(left.height, right.height)
    out = Image.new("RGBA", (total_w, total_h), bg)
    out.alpha_composite(left, (0, 0))
    out.alpha_composite(right, (left.width + gap, 0))

    out.save(output)


# ---------------------------------------------------------------------------
# Quality assessment
# ---------------------------------------------------------------------------

def _saturation_of(rgb: tuple[int, int, int]) -> int:
    """Cheap chromatic-spread metric: max(R,G,B) - min(R,G,B) on 0-255 scale.

    A neutral grey returns 0; a fully saturated primary returns 255.
    """
    return int(max(rgb) - min(rgb))


def assess_quality(entry: SpriteInventoryEntry) -> dict[str, Any]:
    """Heuristic quality score for a single sprite inventory entry.

    Returns::

        {
            "score": float in [0, 1],
            "flags": list[str],     # subset of {"low_alpha_coverage",
                                    # "desaturated", "tiny"}
            "recommendation": "OK" | "consider_re_extraction" | "critical",
        }

    The thresholds are exported as module constants
    (:data:`ALPHA_COVERAGE_CUTOFF`, :data:`SATURATION_CUTOFF`,
    :data:`MIN_DIMENSION_CUTOFF`) so downstream games can monkey-patch them
    if their art style needs different tolerances.

    Raises
    ------
    TypeError
        If ``entry`` is not a :class:`SpriteInventoryEntry` (or a
        duck-compatible object exposing ``alpha_coverage``, ``mean_rgb``,
        ``width``, ``height``).
    """
    validate_inventory_entry("assess_quality", entry)
    flags: list[str] = []

    if entry.alpha_coverage < ALPHA_COVERAGE_CUTOFF:
        flags.append("low_alpha_coverage")
    if _saturation_of(entry.mean_rgb) < SATURATION_CUTOFF:
        flags.append("desaturated")
    if entry.width < MIN_DIMENSION_CUTOFF or entry.height < MIN_DIMENSION_CUTOFF:
        flags.append("tiny")

    # Score: each flag costs 1/3 of the total. Two or more flags drops below
    # 0.5 and triggers re-extraction; all three is critical.
    score = max(0.0, 1.0 - len(flags) / 3.0)

    if len(flags) >= 3:
        recommendation = "critical"
    elif len(flags) >= 1:
        recommendation = "consider_re_extraction"
    else:
        recommendation = "OK"

    return {
        "score": float(score),
        "flags": flags,
        "recommendation": recommendation,
    }
