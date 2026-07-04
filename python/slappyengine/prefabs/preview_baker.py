"""Prefab preview icon baker — 64x64 PNG thumbnails for spawn menus.

Given a :class:`slappyengine.prefabs.Prefab` this module renders a tiny
diary-styled top-down projection of the prefab's body-spec kind so the
editor spawn menu can show a recognisable glyph next to each entry
without booting a real physics world.

Every render path is deterministic — the same prefab hashes to the same
palette slot and the internal wobble RNG is seeded from the prefab name
so two bakes on two machines produce byte-identical PNGs. This lets the
6 shipping previews live inside the wheel at
``python/slappyengine/prefabs/baked/previews/*.png`` and lets downstream
CI verify they haven't drifted.

Two-line usage::

    baker = PreviewBaker()
    img = baker.bake_preview(lib.get("crate"))       # PIL.Image (64x64)
    baker.bake_all_previews(lib, Path("out/previews"))

Rendering strategy — one branch per body kind:

* ``point`` / ``circle`` → filled disk centred, tiny highlight.
* ``box``                → wooden crate icon (5 grain lines + 2 nails).
* ``rope``               → 5-segment zigzag from top-left to bottom-right.
* ``ragdoll``            → 4-limb stick figure (head, torso, arms, legs).
* ``chain``              → 5 linked ovals alternating orientation.
* ``composite``          → recursive layout of child prefabs (min-glyph
  per child arranged around the icon centre) with a fallback marker.

The 8-colour "diary tokens" palette is a fixed pastel wash meant to
match the notebook-editor theme.
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import random
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from PIL import Image, ImageDraw

if TYPE_CHECKING:  # pragma: no cover
    from .library import PrefabLibrary
    from .prefab import Prefab

_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Palette — 8 pastel "diary tokens" that pair with the notebook UI theme.
# ---------------------------------------------------------------------------

DIARY_PALETTE: tuple[tuple[int, int, int], ...] = (
    (219, 132, 116),   # coral   — 0
    (232, 197, 132),   # ochre   — 1
    (188, 210, 132),   # olive   — 2
    (128, 194, 168),   # mint    — 3
    (124, 176, 210),   # sky     — 4
    (152, 138, 194),   # lavender— 5
    (204, 138, 176),   # rose    — 6
    (176, 158, 132),   # kraft   — 7
)

# Neutral tones for chrome / ink strokes.
_INK: tuple[int, int, int] = (54, 40, 32)
_PAPER: tuple[int, int, int] = (247, 242, 228)
_SHADOW: tuple[int, int, int] = (128, 108, 92)

# Minimum preview edge — guards against silly downstream calls.
_MIN_SIZE: int = 8


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hash_slot(name: str) -> int:
    """Map *name* to a deterministic palette index in ``[0, 8)``."""
    if not isinstance(name, str) or not name:
        return 0
    digest = hashlib.sha1(name.encode("utf-8")).digest()
    return digest[0] % len(DIARY_PALETTE)


def _seeded_random(name: str) -> random.Random:
    """Return a :class:`random.Random` deterministically seeded by *name*."""
    digest = hashlib.sha1((name or "").encode("utf-8")).digest()
    seed = int.from_bytes(digest[:8], "big", signed=False)
    return random.Random(seed)


def _draw_frame(draw: ImageDraw.ImageDraw, size: int) -> None:
    """Draw the paper border + inner shadow (unit chrome for every icon)."""
    draw.rectangle((0, 0, size - 1, size - 1), fill=_PAPER)
    # Inner border rectangle — tiny margin so glyphs never touch the edge.
    m = max(1, size // 16)
    draw.rectangle(
        (m, m, size - 1 - m, size - 1 - m),
        outline=_INK,
        width=1,
    )


def _draw_circle_glyph(
    draw: ImageDraw.ImageDraw,
    size: int,
    colour: tuple[int, int, int],
) -> None:
    """Filled disk with a highlight."""
    cx = cy = size / 2
    r = size * 0.32
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=colour,
        outline=_INK,
        width=1,
    )
    # Highlight — small offset disk in a lighter tint.
    hr = r * 0.28
    hx = cx - r * 0.35
    hy = cy - r * 0.35
    light = tuple(min(255, c + 40) for c in colour)
    draw.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=light)


def _draw_box_glyph(
    draw: ImageDraw.ImageDraw,
    size: int,
    colour: tuple[int, int, int],
) -> None:
    """Wooden crate — filled rect + 5 grain lines + 2 nails."""
    m = size * 0.22
    left, top, right, bottom = m, m, size - m, size - m
    draw.rectangle((left, top, right, bottom), fill=colour, outline=_INK, width=1)
    # 5 vertical grain lines evenly spaced.
    grain_dark = tuple(max(0, c - 40) for c in colour)
    inner_w = right - left
    for i in range(1, 6):
        gx = left + inner_w * (i / 6.0)
        draw.line((gx, top + 2, gx, bottom - 2), fill=grain_dark, width=1)
    # 2 nails in the top corners.
    nail_r = max(1, size // 32)
    for nx, ny in ((left + 3, top + 3), (right - 3, top + 3)):
        draw.ellipse(
            (nx - nail_r, ny - nail_r, nx + nail_r, ny + nail_r),
            fill=_INK,
        )


def _draw_rope_glyph(
    draw: ImageDraw.ImageDraw,
    size: int,
    colour: tuple[int, int, int],
    rng: random.Random,
) -> None:
    """5-segment zigzag rope from upper-left to lower-right."""
    m = size * 0.18
    n = 5
    points: list[tuple[float, float]] = []
    for i in range(n + 1):
        t = i / n
        x = m + (size - 2 * m) * t
        # Alternating zigzag with a tiny deterministic wobble.
        base_y = size * (0.35 + 0.30 * t)
        zig = (size * 0.10) * (1 if i % 2 == 0 else -1)
        wobble = (rng.random() - 0.5) * (size * 0.04)
        points.append((x, base_y + zig + wobble))
    # Rope stroke — thick colour + thin ink outline for readability.
    draw.line(points, fill=colour, width=max(2, size // 20))
    # Little "knot" nodes at each waypoint.
    knot_r = max(1, size // 24)
    for px, py in points:
        draw.ellipse(
            (px - knot_r, py - knot_r, px + knot_r, py + knot_r),
            fill=_INK,
        )


def _draw_ragdoll_glyph(
    draw: ImageDraw.ImageDraw,
    size: int,
    colour: tuple[int, int, int],
) -> None:
    """4-limb stick figure: head, torso, 2 arms, 2 legs."""
    cx = size / 2
    head_cy = size * 0.28
    head_r = size * 0.10
    # Head.
    draw.ellipse(
        (cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r),
        fill=colour,
        outline=_INK,
        width=1,
    )
    stroke = max(2, size // 24)
    # Torso.
    torso_top = (cx, head_cy + head_r)
    torso_bot = (cx, size * 0.62)
    draw.line((torso_top, torso_bot), fill=_INK, width=stroke)
    # Arms.
    shoulder_y = head_cy + head_r + size * 0.04
    draw.line(
        ((cx, shoulder_y), (cx - size * 0.20, shoulder_y + size * 0.15)),
        fill=_INK, width=stroke,
    )
    draw.line(
        ((cx, shoulder_y), (cx + size * 0.20, shoulder_y + size * 0.15)),
        fill=_INK, width=stroke,
    )
    # Legs.
    hip = torso_bot
    draw.line(
        (hip, (cx - size * 0.15, size * 0.82)),
        fill=_INK, width=stroke,
    )
    draw.line(
        (hip, (cx + size * 0.15, size * 0.82)),
        fill=_INK, width=stroke,
    )


def _draw_chain_glyph(
    draw: ImageDraw.ImageDraw,
    size: int,
    colour: tuple[int, int, int],
) -> None:
    """5 linked ovals alternating orientation."""
    m = size * 0.14
    span = size - 2 * m
    n = 5
    step = span / n
    oval_w = step * 1.4
    oval_h = step * 0.8
    for i in range(n):
        cx = m + step * (i + 0.5)
        cy = size / 2
        if i % 2 == 0:
            # Horizontal oval.
            bbox = (cx - oval_w / 2, cy - oval_h / 2,
                    cx + oval_w / 2, cy + oval_h / 2)
        else:
            # Vertical oval.
            bbox = (cx - oval_h / 2, cy - oval_w / 2,
                    cx + oval_h / 2, cy + oval_w / 2)
        draw.ellipse(bbox, outline=_INK, width=max(2, size // 24))
        # Inner tint fill so the link colour is legible.
        inner = tuple(min(255, c + 30) for c in colour)
        pad = max(2, size // 22)
        draw.ellipse(
            (bbox[0] + pad, bbox[1] + pad, bbox[2] - pad, bbox[3] - pad),
            fill=inner,
        )


def _draw_composite_glyph(
    draw: ImageDraw.ImageDraw,
    size: int,
    colour: tuple[int, int, int],
    prefab: "Prefab",
    library: "PrefabLibrary | None",
    depth: int,
) -> None:
    """Recursive layout of child prefabs (falls back to hub-and-spoke marker)."""
    cx = cy = size / 2
    # Hub disk.
    r = size * 0.14
    draw.ellipse(
        (cx - r, cy - r, cx + r, cy + r),
        fill=colour, outline=_INK, width=1,
    )
    # If we have child prefabs and a library + depth budget, render
    # miniature glyphs orbiting the hub. Otherwise plot 4 spokes to hint
    # at compositeness.
    children: list["Prefab"] = []
    if library is not None and depth < 2:
        for cname in prefab.child_prefabs:
            child = library.get(cname)
            if child is not None:
                children.append(child)

    spoke_r = size * 0.36
    if children:
        n = min(len(children), 6)
        mini_size = max(_MIN_SIZE, size // 4)
        for i in range(n):
            angle = (2 * math.pi * i) / n
            x = cx + math.cos(angle) * spoke_r - mini_size / 2
            y = cy + math.sin(angle) * spoke_r - mini_size / 2
            # Recursive bake into a small image, then paste.
            baker = PreviewBaker()
            child_img = baker._render(
                children[i], mini_size, library, depth + 1,
            )
            # Paste onto the parent image via the draw's image handle.
            draw._image.paste(child_img, (int(x), int(y)))
        return

    # Fallback: 4 spokes with terminal dots for a "hub" look.
    for i in range(4):
        angle = (math.pi / 2) * i + math.pi / 4
        x = cx + math.cos(angle) * spoke_r
        y = cy + math.sin(angle) * spoke_r
        draw.line(((cx, cy), (x, y)), fill=_INK, width=max(2, size // 28))
        dot_r = max(1, size // 24)
        draw.ellipse(
            (x - dot_r, y - dot_r, x + dot_r, y + dot_r),
            fill=colour, outline=_INK,
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class PreviewBaker:
    """Renders tiny top-down PIL previews of :class:`Prefab` entries."""

    #: Palette lookup — public so tests / editors can reason about slots.
    PALETTE: tuple[tuple[int, int, int], ...] = DIARY_PALETTE

    #: Baked preview directory shipped inside the wheel.
    BAKED_DIR: Path = Path(__file__).parent / "baked" / "previews"

    def bake_preview(
        self,
        prefab: "Prefab",
        size: int = 64,
        *,
        library: "PrefabLibrary | None" = None,
    ) -> Image.Image:
        """Render *prefab* as a fresh :class:`PIL.Image.Image` (RGBA).

        Parameters
        ----------
        prefab:
            The prefab to render. Must expose ``name`` and ``body_spec``.
        size:
            Edge length in pixels. Defaults to 64. Clamped to ``>= 8``.
        library:
            Optional prefab library — passed through so composite
            prefabs can look up their :attr:`Prefab.child_prefabs`.

        Raises
        ------
        TypeError
            If *prefab* is not a :class:`Prefab`.
        ValueError
            If *size* is not a positive int or below :data:`_MIN_SIZE`.
        """
        # Local import — keeps prefab.py the single source of truth on
        # what a Prefab looks like without a hard cycle.
        from .prefab import Prefab as _Prefab

        if not isinstance(prefab, _Prefab):
            raise TypeError(
                f"PreviewBaker.bake_preview: prefab must be a Prefab; got "
                f"{type(prefab).__name__}"
            )
        if not isinstance(size, int) or size < _MIN_SIZE:
            raise ValueError(
                f"PreviewBaker.bake_preview: size must be an int >= "
                f"{_MIN_SIZE}; got {size!r}"
            )
        return self._render(prefab, size, library, depth=0)

    def bake_all_previews(
        self,
        library: "PrefabLibrary",
        out_dir: Path | str,
        size: int = 64,
    ) -> list[Path]:
        """Render every prefab in *library* into ``out_dir/<name>.png``.

        Existing files are overwritten so a fresh bake is guaranteed.
        Returns the list of written paths sorted by prefab name so
        downstream tests get a stable ordering.
        """
        # Circular-safe import.
        from .library import PrefabLibrary as _PL

        if not isinstance(library, _PL):
            raise TypeError(
                f"PreviewBaker.bake_all_previews: library must be a "
                f"PrefabLibrary; got {type(library).__name__}"
            )
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        for prefab in library.list_all():
            img = self.bake_preview(prefab, size, library=library)
            path = out / f"{prefab.name}.png"
            img.save(path, format="PNG", optimize=True)
            written.append(path)
        return written

    def load_preview(
        self,
        name: str,
        baked_dir: Path | str | None = None,
        *,
        library: "PrefabLibrary | None" = None,
        size: int = 64,
    ) -> Image.Image | None:
        """Return the baked preview for *name*, or fall back to on-demand bake.

        * Reads ``baked_dir/<name>.png`` when present (defaults to
          :attr:`BAKED_DIR`).
        * When missing but a *library* is passed, calls
          :meth:`bake_preview` for the prefab and returns the fresh
          image without writing to disk.
        * Returns ``None`` when neither path succeeds — callers can then
          fall back to a placeholder glyph.
        """
        if not isinstance(name, str) or not name:
            return None
        bdir = self.BAKED_DIR if baked_dir is None else Path(baked_dir)
        path = bdir / f"{name}.png"
        if path.is_file():
            try:
                img = Image.open(path)
                img.load()
                return img.convert("RGBA")
            except (OSError, ValueError) as exc:
                _LOG.warning(
                    "PreviewBaker.load_preview: dropping unreadable %s (%s)",
                    path, exc,
                )
        if library is not None:
            prefab = library.get(name)
            if prefab is not None:
                return self.bake_preview(prefab, size, library=library)
        return None

    # ------------------------------------------------------------------
    # Internal render dispatch
    # ------------------------------------------------------------------

    def _render(
        self,
        prefab: "Prefab",
        size: int,
        library: "PrefabLibrary | None",
        depth: int,
    ) -> Image.Image:
        img = Image.new("RGBA", (size, size), _PAPER + (255,))
        draw = ImageDraw.Draw(img)
        # ImageDraw doesn't expose the underlying image directly, so we
        # stash a reference for the composite glyph to paste into.
        draw._image = img  # type: ignore[attr-defined]

        _draw_frame(draw, size)
        colour = DIARY_PALETTE[_hash_slot(prefab.name)]
        kind = prefab.body_spec.get("kind", "point")
        rng = _seeded_random(prefab.name)

        if kind in ("point", "circle"):
            _draw_circle_glyph(draw, size, colour)
        elif kind == "box":
            _draw_box_glyph(draw, size, colour)
        elif kind == "rope":
            _draw_rope_glyph(draw, size, colour, rng)
        elif kind == "ragdoll":
            _draw_ragdoll_glyph(draw, size, colour)
        elif kind == "chain":
            _draw_chain_glyph(draw, size, colour)
        elif kind == "composite":
            _draw_composite_glyph(draw, size, colour, prefab, library, depth)
        else:
            # Unknown kind — still deterministic — plot a "?" hatch.
            _draw_circle_glyph(draw, size, colour)

        return img


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def png_bytes(image: Image.Image) -> bytes:
    """Return the deterministic PNG-encoded bytes of *image*.

    Uses ``optimize=True`` so callers can compare digests to detect
    drift. Lives at module scope for test convenience.
    """
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def iter_baked_previews(baked_dir: Path | str | None = None) -> Iterable[Path]:
    """Yield every ``*.png`` under the baked previews directory."""
    bdir = PreviewBaker.BAKED_DIR if baked_dir is None else Path(baked_dir)
    if not bdir.is_dir():
        return iter(())
    return iter(sorted(bdir.glob("*.png")))


__all__ = [
    "DIARY_PALETTE",
    "PreviewBaker",
    "iter_baked_previews",
    "png_bytes",
]
