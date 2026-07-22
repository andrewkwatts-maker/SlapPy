"""``NotebookPanelDecor`` — the signature title-bar washi-tape decoration.

Every notebook-themed editor panel wears a small strip of washi tape
slapped over one corner of its title bar. The strip is:

* Rotated 4-8 degrees off-axis for the hand-placed feel — DPG has no
  image-rotation primitive so the tape is pre-rotated in numpy via
  :func:`pharos_editor.ui.theme.washi_tape.rotate_washi_tape` before it
  becomes a texture.
* Picked from one of four presets registered in
  :data:`pharos_editor.ui.theme.washi_tape.WASHI_TAPE_PRESETS`
  (``"pink_polka"``, ``"pastel_floral"``, ``"star_print"``, ``"plain"``).
* Assigned to each panel from a deterministic per-panel-name hash so
  the same panel always gets the same tape across editor restarts.

This module is additive: it does **not** replace the existing
:class:`pharos_editor.ui.editor.panel_decor.PanelDecor` (which handles
divider strokes + corner stickers on floating windows) or the
:class:`pharos_editor.ui.editor.panel_extras.ExtendedPanelDecorator`
(which handles washi that spills past the panel edge). It's a
lightweight *title-row* decoration slot that any notebook panel can
opt into with a single call.

Public surface
--------------

.. code-block:: python

    from pharos_editor.ui.editor.notebook_panel_decor import (
        NotebookPanelDecor,
        TitleTapeSpec,
        preset_for_panel,
    )

    decor = NotebookPanelDecor()
    tape = decor.title_tape("outliner")   # (H, W, 4) uint8 RGBA
    # blit *tape* onto the outliner's title-bar drawlist
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from pharos_editor.ui.theme.washi_tape import (
    WASHI_TAPE_PRESETS,
    render_washi_tape,
    rotate_washi_tape,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


DEFAULT_TAPE_SIZE_PX: tuple[int, int] = (120, 32)
"""Default ``(width, height)`` for a title-bar tape strip.

120 px wide × 32 px tall matches the sprint brief and reads clearly on
the notebook editor's ~28-px title row without stealing focus from the
panel title text underneath.
"""


_ROTATION_PHASES_DEG: tuple[float, ...] = (-7.0, -4.0, +4.0, +7.0)
"""The four allowed hand-placed rotation angles.

Every panel picks one deterministically from its name hash. The four
values were selected so no tape is ever axis-aligned (all four are
strictly non-zero) but every angle sits within the sprint's ±8-deg
budget.
"""


# ---------------------------------------------------------------------------
# Deterministic preset picker
# ---------------------------------------------------------------------------


_PRESET_ORDER: tuple[str, ...] = (
    "pink_polka",
    "pastel_floral",
    "star_print",
    "plain",
)


def preset_for_panel(panel_name: str) -> str:
    """Return the washi-tape preset id assigned to *panel_name*.

    The mapping is a deterministic hash so the outliner always gets
    (say) pink polka and the inspector always gets star print — no
    matter how many times the editor is relaunched.

    Parameters
    ----------
    panel_name:
        Non-empty identifier for the panel (e.g. ``"outliner"``,
        ``"inspector"``, ``"toolbar"``). Case-sensitive; the caller is
        expected to use snake_case.

    Returns
    -------
    str
        One of ``{"pink_polka", "pastel_floral", "star_print", "plain"}``.

    Raises
    ------
    ValueError
        If *panel_name* is not a non-empty string.
    """
    if not isinstance(panel_name, str) or not panel_name:
        raise ValueError(
            f"preset_for_panel: panel_name must be a non-empty str; "
            f"got {panel_name!r}"
        )
    # md5 → 4-byte int → index into the presets tuple. md5 is chosen for
    # stability across Python releases (unlike ``hash()`` which is salted
    # per-process).
    digest = hashlib.md5(panel_name.encode("utf-8")).digest()
    idx = digest[0] % len(_PRESET_ORDER)
    return _PRESET_ORDER[idx]


def rotation_for_panel(panel_name: str) -> float:
    """Return the deterministic rotation (deg) for *panel_name*'s tape."""
    if not isinstance(panel_name, str) or not panel_name:
        raise ValueError(
            f"rotation_for_panel: panel_name must be a non-empty str; "
            f"got {panel_name!r}"
        )
    digest = hashlib.md5(panel_name.encode("utf-8")).digest()
    return _ROTATION_PHASES_DEG[digest[1] % len(_ROTATION_PHASES_DEG)]


# ---------------------------------------------------------------------------
# TitleTapeSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TitleTapeSpec:
    """Resolved washi-tape strip descriptor for one panel title row.

    Parameters
    ----------
    panel_name:
        Which panel the tape belongs to (``"outliner"`` etc). Kept for
        debugging / telemetry — the renderer itself only reads
        :attr:`preset`, :attr:`size_px`, and :attr:`rotation_deg`.
    preset:
        Preset id — resolved via :func:`preset_for_panel` when the
        caller doesn't override it.
    size_px:
        Pre-rotation ``(width, height)`` in pixels. Rotation enlarges
        the output canvas so callers should offset the blit accordingly.
    rotation_deg:
        Angle in degrees; positive = counter-clockwise.
    corner:
        Which title-row corner the tape sits over — ``"TL"`` / ``"TR"``.
        BL / BR are not used because notebook panels have their title
        row at the *top* of the window.
    """

    panel_name: str
    preset: str
    size_px: tuple[int, int] = DEFAULT_TAPE_SIZE_PX
    rotation_deg: float = 0.0
    corner: str = "TL"

    def __post_init__(self) -> None:
        fn = "TitleTapeSpec"
        if not isinstance(self.panel_name, str) or not self.panel_name:
            raise ValueError(
                f"{fn}: panel_name must be a non-empty str; "
                f"got {self.panel_name!r}"
            )
        if self.preset not in WASHI_TAPE_PRESETS:
            raise ValueError(
                f"{fn}: preset {self.preset!r} not registered; "
                f"known: {sorted(WASHI_TAPE_PRESETS)}"
            )
        if (
            not isinstance(self.size_px, tuple)
            or len(self.size_px) != 2
            or not all(isinstance(v, int) and v > 0 for v in self.size_px)
        ):
            raise ValueError(
                f"{fn}: size_px must be a 2-tuple of positive ints; "
                f"got {self.size_px!r}"
            )
        if not isinstance(self.rotation_deg, (int, float)) or isinstance(
            self.rotation_deg, bool
        ):
            raise TypeError(
                f"{fn}: rotation_deg must be a number; "
                f"got {type(self.rotation_deg).__name__}"
            )
        if self.corner not in ("TL", "TR"):
            raise ValueError(
                f"{fn}: corner must be 'TL' or 'TR'; got {self.corner!r}"
            )


# ---------------------------------------------------------------------------
# NotebookPanelDecor
# ---------------------------------------------------------------------------


class NotebookPanelDecor:
    """Title-bar washi-tape decorator for the notebook editor panels.

    Every notebook panel (toolbar, outliner, inspector, code panel,
    content browser, …) registers its name here and receives one strip
    of washi tape blitted at the top-left corner of its title row.

    The rendered tape is cached per ``(panel_name, size_px)`` so
    repeated frames don't re-run the numpy renderer. Cache invalidation
    is intentionally trivial (no invalidation) — the tape is a fixed
    theme decoration; changing the theme replaces the whole decorator.

    Example
    -------
    ::

        decor = NotebookPanelDecor()
        rgba = decor.title_tape("outliner")
        # Upload rgba as a DPG texture and draw it at the panel corner.
    """

    def __init__(self) -> None:
        self._cache: dict[tuple[str, int, int], np.ndarray] = {}

    def specs(self, panel_names: Sequence[str]) -> list[TitleTapeSpec]:
        """Return one :class:`TitleTapeSpec` per name in *panel_names*.

        The specs use per-name deterministic preset + rotation picks so
        the caller can pre-plan layouts without rendering pixels.
        """
        if not isinstance(panel_names, (list, tuple)):
            raise TypeError(
                "NotebookPanelDecor.specs: panel_names must be a sequence; "
                f"got {type(panel_names).__name__}"
            )
        out: list[TitleTapeSpec] = []
        for name in panel_names:
            out.append(TitleTapeSpec(
                panel_name=name,
                preset=preset_for_panel(name),
                size_px=DEFAULT_TAPE_SIZE_PX,
                rotation_deg=rotation_for_panel(name),
                corner="TL",
            ))
        return out

    def title_tape(
        self,
        panel_name: str,
        size_px: tuple[int, int] | None = None,
        preset: str | None = None,
        rotation_deg: float | None = None,
    ) -> np.ndarray:
        """Return the rotated RGBA tape strip for *panel_name*.

        When *preset* / *rotation_deg* / *size_px* are ``None`` the
        deterministic per-name picks are used. Callers that want a
        fixed preset (e.g. the theming editor's preview surface) pass
        them explicitly.
        """
        if size_px is None:
            size_px = DEFAULT_TAPE_SIZE_PX
        preset_id = preset if preset is not None else preset_for_panel(panel_name)
        angle = (
            float(rotation_deg)
            if rotation_deg is not None
            else rotation_for_panel(panel_name)
        )
        # Cache pre-rotation renders so we can rotate on demand without
        # re-running the numpy patternfill — rotation is comparatively
        # cheap and the caller can freely tweak the angle.
        key = (preset_id, int(size_px[0]), int(size_px[1]))
        base = self._cache.get(key)
        if base is None:
            base = render_washi_tape(preset_id, size_px)
            self._cache[key] = base
        return rotate_washi_tape(base, angle)


__all__ = [
    "DEFAULT_TAPE_SIZE_PX",
    "NotebookPanelDecor",
    "TitleTapeSpec",
    "preset_for_panel",
    "rotation_for_panel",
]
