"""Notebook-themed material editor — a "color story" page.

A presentation sibling of
:class:`slappyengine.ui.editor.material_editor.MaterialEditor` that
wraps the existing kind-discriminator contract in a field-journal page:

* a **top swatch row** showing the dominant colours of the material,
* a **mood line** in handwritten font ("Soft and squishy — bounces
  back when you press it."),
* a **sticker preview** in the top-right corner that matches the
  material vibe (heart for rubber, droplet for water, mountain for
  stone, etc.),
* a **96×96 px preview pane** rendering a radial-gradient swatch of
  the material's dominant colours, and
* the **editable fields** below the colour story — delegated to a
  reused :class:`NotebookInspector` so the dataclass dispatch table is
  never duplicated.

The editor supports the same three material kinds as the Nova3D
editor (auto-detected via :func:`_detect_kind`):

``material_map``
    A :class:`slappyengine.material.map.MaterialMap` — the top row
    renders the first :class:`MaterialDef`'s
    ``ColorRange.color_low`` / ``color_high`` as two side-by-side
    swatches with a horizontal gradient between them.

``softbody``
    A :class:`slappyengine.softbody.material.Material` dataclass — the
    swatch row shows ``render_color`` and ``damage_color``.

``fluid``
    A :class:`slappyengine.fluid.material.FluidMaterial` dataclass —
    the swatch row is a three-stop gradient built from heuristics over
    ``rest_density``, ``viscosity`` and ``surface_tension``.

The widget contract is the Nova3D ``build(parent_tag) -> None``
protocol; every ``dpg.*`` call is wrapped in ``try / except`` so the
editor still registers tags and call-log entries when ``dearpygui``
is missing or stubbed out.
"""
from __future__ import annotations

import dataclasses
from typing import Any

# Re-use the existing kind discriminator so the two editors can never
# drift apart on which target → which kind.
from slappyengine.ui.editor.material_editor import (
    KIND_FLUID,
    KIND_MATERIAL_MAP,
    KIND_SOFTBODY,
    _detect_kind,
)
from slappyengine.ui.editor.notebook_inspector import NotebookInspector


# ---------------------------------------------------------------------------
# Constants — sticker lookup tables and mood phrases.
# ---------------------------------------------------------------------------


# Sticker glyph per material kind.  The lookup runs against the
# material name (lower-cased) before falling back to a kind-level
# default.  Each value is a single emoji-style token surrounded by
# brackets so the headless add_text path still renders something
# readable when the theme can't load a PNG asset.
_STICKER_BY_NAME: dict[str, dict[str, str]] = {
    KIND_MATERIAL_MAP: {
        "stone":   "[mountain]",
        "rock":    "[mountain]",
        "wood":    "[leaf]",
        "metal":   "[gear]",
        "rubber":  "[heart]",
        "glass":   "[sparkle]",
        "water":   "[droplet]",
        "lava":    "[flame]",
        "ice":     "[snowflake]",
        "sand":    "[hourglass]",
        "dust":    "[cloud]",
    },
    KIND_SOFTBODY: {
        "rubber":  "[heart]",
        "wood":    "[leaf]",
        "stone":   "[mountain]",
        "glass":   "[sparkle]",
        "steel":   "[gear]",
        "metal":   "[gear]",
        "flesh":   "[droplet]",
        "cloth":   "[ribbon]",
    },
    KIND_FLUID: {
        "water":   "[droplet]",
        "lava":    "[flame]",
        "ice":     "[snowflake]",
        "stone":   "[mountain]",
        "sand":    "[hourglass]",
        "gravel":  "[mountain]",
        "dust":    "[cloud]",
        "oil":     "[droplet]",
        "blood":   "[heart]",
    },
}

# Fallback sticker per kind when the name isn't in the lookup.
_DEFAULT_STICKER: dict[str, str] = {
    KIND_MATERIAL_MAP: "[swatch]",
    KIND_SOFTBODY:     "[heart]",
    KIND_FLUID:        "[droplet]",
}


# Mood-line templates per kind.  ``{name}`` is substituted with the
# title-cased material name.  The empty-state mood is used when the
# editor has no target at all.
_MOOD_BY_KEYWORD: dict[str, str] = {
    "rubber":  "Soft and squishy — bounces back when you press it.",
    "stone":   "Solid and stubborn — won't budge for anyone.",
    "rock":    "Solid and stubborn — won't budge for anyone.",
    "mountain": "Tall and quiet — older than the trees.",
    "wood":    "Warm and grainy — smells like a workshop.",
    "metal":   "Cold and shiny — clinks when you tap it.",
    "steel":   "Cold and shiny — clinks when you tap it.",
    "glass":   "Clear and brittle — handle with care.",
    "water":   "Cool and rippling — slips between your fingers.",
    "lava":    "Hot and angry — keep your distance.",
    "ice":     "Cold and slippery — careful where you skate.",
    "sand":    "Loose and warm — runs like an hourglass.",
    "dust":    "Soft and drifting — settles on everything.",
    "cloth":   "Light and rumpled — folds like a napkin.",
    "flesh":   "Soft and yielding — has a heartbeat.",
}

_EMPTY_MOOD = "Pick a material to start the colour story."
_EMPTY_STICKER = "[swatch]"
_EMPTY_TITLE = "No material loaded"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_dpg() -> Any | None:
    """Return ``dearpygui.dearpygui`` or ``None`` when the extra is missing."""
    try:
        import dearpygui.dearpygui as dpg

        return dpg
    except Exception:
        return None


def _clamp_byte(v: float) -> int:
    """Clamp a float into ``0..255`` and return an int."""
    if v < 0:
        return 0
    if v > 255:
        return 255
    return int(v)


def _color_range_midpoint(cr: Any) -> tuple[int, int, int, int]:
    """Return the midpoint RGB of a :class:`ColorRange` as an RGBA tuple."""
    r = (cr.r[0] + cr.r[1]) // 2
    g = (cr.g[0] + cr.g[1]) // 2
    b = (cr.b[0] + cr.b[1]) // 2
    return (_clamp_byte(r), _clamp_byte(g), _clamp_byte(b), 255)


def _color_range_low(cr: Any) -> tuple[int, int, int, int]:
    """Return the ``color_low`` end of a :class:`ColorRange` as RGBA."""
    return (_clamp_byte(cr.r[0]), _clamp_byte(cr.g[0]),
            _clamp_byte(cr.b[0]), 255)


def _color_range_high(cr: Any) -> tuple[int, int, int, int]:
    """Return the ``color_high`` end of a :class:`ColorRange` as RGBA."""
    return (_clamp_byte(cr.r[1]), _clamp_byte(cr.g[1]),
            _clamp_byte(cr.b[1]), 255)


def _rgb_tuple_to_rgba(c: Any) -> tuple[int, int, int, int]:
    """Coerce a render/damage colour into RGBA byte tuple."""
    try:
        seq = list(c)
        r, g, b = seq[0], seq[1], seq[2]
        a = seq[3] if len(seq) > 3 else 255
        return (_clamp_byte(r), _clamp_byte(g), _clamp_byte(b), _clamp_byte(a))
    except Exception:
        return (180, 180, 180, 255)


def _fluid_stops(mat: Any) -> list[tuple[int, int, int, int]]:
    """Return a 3-stop gradient heuristic for a fluid material.

    The heuristic blends the (optional) ``render_color`` against
    ``halo_color`` and modulates the lightness by ``viscosity``
    (thicker fluids are darker) and ``surface_tension`` (high tension
    fluids get a brighter highlight).  Density biases the mid stop
    towards the render colour for heavier fluids.
    """
    render = _rgb_tuple_to_rgba(getattr(mat, "render_color", (60, 140, 220)))
    halo = _rgb_tuple_to_rgba(getattr(mat, "halo_color", (180, 220, 255)))

    visc = float(getattr(mat, "viscosity", 0.0) or 0.0)
    dens = float(getattr(mat, "rest_density", 1000.0) or 1000.0)
    st = float(getattr(mat, "surface_tension", 0.0) or 0.0)

    # Viscosity darkens the low stop; clamp to [0, 1].
    visc_factor = max(0.0, min(1.0, visc / 10.0))
    low = tuple(
        _clamp_byte(c * (1.0 - 0.4 * visc_factor)) for c in render[:3]
    ) + (255,)

    # Density-weighted mid: heavier fluid stays closer to the render
    # colour, lighter fluid drifts toward the halo.
    dens_factor = max(0.0, min(1.0, dens / 2000.0))
    mid = tuple(
        _clamp_byte(
            render[i] * dens_factor + halo[i] * (1.0 - dens_factor)
        )
        for i in range(3)
    ) + (255,)

    # Surface tension brightens the high stop.
    st_factor = max(0.0, min(1.0, st / 5.0))
    high = tuple(
        _clamp_byte(halo[i] + (255 - halo[i]) * 0.5 * st_factor)
        for i in range(3)
    ) + (255,)

    return [low, mid, high]


def _mood_for(name: str | None, kind: str) -> str:
    """Return a one-line mood description for *name* / *kind*."""
    if not name:
        return _EMPTY_MOOD
    low = name.lower()
    for kw, mood in _MOOD_BY_KEYWORD.items():
        if kw in low:
            return mood
    # Generic per-kind fallback.
    if kind == KIND_FLUID:
        return f"{name.title()} — flows in its own slow way."
    if kind == KIND_SOFTBODY:
        return f"{name.title()} — yields when the world leans on it."
    return f"{name.title()} — a pigment all its own."


def _sticker_for(name: str | None, kind: str) -> str:
    """Return the sticker token for *name* under *kind*."""
    if not name:
        return _EMPTY_STICKER
    low = name.lower()
    table = _STICKER_BY_NAME.get(kind, {})
    for kw, sticker in table.items():
        if kw in low:
            return sticker
    return _DEFAULT_STICKER.get(kind, _EMPTY_STICKER)


def _material_name(target: Any, kind: str) -> str | None:
    """Return a display name for *target* (or ``None`` when unknown)."""
    if target is None:
        return None
    if kind == KIND_MATERIAL_MAP:
        mats = getattr(target, "_materials", None) or []
        if mats:
            return getattr(mats[0], "name", None)
        return None
    return getattr(target, "name", None)


# ---------------------------------------------------------------------------
# NotebookMaterialEditor
# ---------------------------------------------------------------------------


class NotebookMaterialEditor:
    """Material editor themed as a colour-story page.

    Three kinds (per Nova3D's existing discriminator):

    * ``material_map``  — :class:`MaterialMap` with colour-range
      swatches.
    * ``softbody``      — :class:`softbody.Material` dataclass.
    * ``fluid``         — :class:`fluid.FluidMaterial` dataclass.

    Each kind reflects through :class:`NotebookInspector` but with a
    material-specific top section: a colour-palette swatch row at the
    top, then the editable fields below.

    Attributes
    ----------
    TITLE:
        Editor-shell title slot.
    """

    TITLE = "Material"

    # Movable-window minimums — picked up by ``MovablePanelWindow``.
    MIN_WIDTH: int = 280
    MIN_HEIGHT: int = 400

    # The colour-story page width — used by the preview pane and the
    # swatch row.  Kept as a class constant so tests can pin it.
    SWATCH_PX = 48
    PREVIEW_PX = 96

    def __init__(self, target: Any | None = None) -> None:
        self._target: Any = target
        self._kind: str = _detect_kind(target) if target is not None else KIND_MATERIAL_MAP

        self._panel_tag: str = f"notebook_material_editor_{id(self)}"
        self._story_tag: str = f"{self._panel_tag}_story"
        self._swatch_tag: str = f"{self._panel_tag}_swatch"
        self._mood_tag: str = f"{self._panel_tag}_mood"
        self._sticker_tag: str = f"{self._panel_tag}_sticker"
        self._preview_tag: str = f"{self._panel_tag}_preview"
        self._fields_tag: str = f"{self._panel_tag}_fields"
        self._empty_tag: str = f"{self._panel_tag}_empty"

        # Cached child inspector.  We construct one and rebind via
        # ``set_target`` when the material changes.
        self._inspector: NotebookInspector | None = None

        # Cached swatch colours (used by tests + the preview pane).
        self._swatch_stops: list[tuple[int, int, int, int]] = []
        self._mood: str = _EMPTY_MOOD
        self._sticker: str = _EMPTY_STICKER

        # Build lifecycle.
        self._built: bool = False
        self._parent_tag: str | int | None = None

        # Call history for headless-test assertions; one tuple per event.
        self.call_log: list[tuple[Any, ...]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def target(self) -> Any:
        """Return the currently bound target (or ``None``)."""
        return self._target

    @property
    def kind(self) -> str:
        """Return the kind string detected for the current target."""
        return self._kind

    @property
    def mood(self) -> str:
        """Return the cached mood line for the current target."""
        return self._mood

    @property
    def sticker(self) -> str:
        """Return the cached sticker token for the current target."""
        return self._sticker

    @property
    def swatch_stops(self) -> list[tuple[int, int, int, int]]:
        """Return the cached colour stops for the swatch row."""
        return list(self._swatch_stops)

    def set_material(self, material: Any) -> None:
        """Bind *material* as the editor target and rebuild the page.

        Equivalent to :meth:`set_target` — kept for the spec API.
        """
        self.set_target(material)

    def set_target(self, target: Any, kind: str | None = None) -> None:
        """Bind a new target and rebuild the colour-story page.

        Parameters
        ----------
        target:
            One of: :class:`MaterialMap`, softbody ``Material``, fluid
            ``FluidMaterial``, or ``None`` for the empty state.
        kind:
            Explicit kind override.  When ``None`` the kind is
            auto-detected via :func:`_detect_kind`.
        """
        self._target = target
        if target is None:
            self._kind = KIND_MATERIAL_MAP
        else:
            self._kind = kind if kind is not None else _detect_kind(target)
        self.call_log.append((
            "set_target",
            type(target).__name__ if target is not None else None,
            self._kind,
        ))
        self.refresh()

    def build(self, parent_tag: int | str) -> None:
        """Materialise the colour-story page under *parent_tag*.

        Safe to call when ``dearpygui`` is missing — every DPG call is
        guarded so the editor still registers its tags for tests.
        """
        self._parent_tag = parent_tag
        self._built = True
        self.call_log.append(("build", parent_tag))

        dpg = _safe_dpg()
        if dpg is None:
            return

        try:
            with dpg.child_window(
                tag=self._panel_tag,
                parent=parent_tag,
                border=False,
                autosize_x=True,
                height=-1,
            ):
                # Hand-written title row — the theme picks the font.
                try:
                    dpg.add_text("Colour Story", color=[40, 40, 60, 255])
                except Exception:
                    pass
        except Exception:
            # Stub-DPG without context-manager support — flat path.
            try:
                dpg.add_text(
                    "Colour Story",
                    parent=parent_tag,
                    tag=self._panel_tag,
                )
            except Exception:
                pass

        self._render_body(dpg)

    def refresh(self) -> None:
        """Tear down and rebuild the colour-story body.

        Safe to call before :meth:`build` — becomes a no-op in that
        case (the call is still logged).
        """
        self.call_log.append(("refresh",))
        if not self._built:
            return

        dpg = _safe_dpg()
        if dpg is None:
            return

        # Wipe the existing body so we can re-render.
        for tag in (
            self._story_tag,
            self._swatch_tag,
            self._mood_tag,
            self._sticker_tag,
            self._preview_tag,
            self._fields_tag,
            self._empty_tag,
        ):
            try:
                if dpg.does_item_exist(tag):
                    dpg.delete_item(tag)
            except Exception:
                pass

        # Drop the old inspector — a fresh one is built per target so
        # the nested ``_panel_tag`` (which embeds ``id(self)``) is
        # always unique.
        self._inspector = None

        self._render_body(dpg)

    # ------------------------------------------------------------------
    # Body renderer
    # ------------------------------------------------------------------

    def _render_body(self, dpg: Any) -> None:
        """Build either the empty state, or the colour-story sections."""
        # Cache the swatch stops / mood / sticker so tests + listeners
        # can introspect them without re-running the heuristics.
        self._swatch_stops = self._compute_swatch_stops()
        name = _material_name(self._target, self._kind)
        self._mood = _mood_for(name, self._kind)
        self._sticker = _sticker_for(name, self._kind)

        if self._target is None:
            self._render_empty_state(dpg)
            return

        # Top story row — sticker, mood, preview pane.
        self._render_story_header(dpg)
        # Swatch strip — the actual colour story.
        self._render_swatch_row(dpg)
        # Editable fields — delegated to NotebookInspector.
        self._render_fields(dpg)

    def _render_empty_state(self, dpg: Any) -> None:
        """Render the empty-state notice."""
        try:
            with dpg.group(parent=self._panel_tag, tag=self._empty_tag):
                dpg.add_text(self._sticker, color=[120, 80, 40, 255])
                dpg.add_text(self._mood, color=[120, 120, 140, 255])
        except Exception:
            try:
                dpg.add_text(
                    f"{self._sticker} {self._mood}",
                    parent=self._panel_tag,
                    tag=self._empty_tag,
                )
            except Exception:
                pass
        self.call_log.append(("empty_state",))

    # ------------------------------------------------------------------
    # Top story header — sticker / mood / preview pane.
    # ------------------------------------------------------------------

    def _render_story_header(self, dpg: Any) -> None:
        name = _material_name(self._target, self._kind) or _EMPTY_TITLE
        try:
            with dpg.group(parent=self._panel_tag, tag=self._story_tag, horizontal=True):
                # Sticker preview — small badge in the top-right.
                try:
                    dpg.add_text(
                        self._sticker,
                        tag=self._sticker_tag,
                        color=[200, 80, 120, 255],
                    )
                except Exception:
                    pass

                # Mood line in handwritten font.
                try:
                    dpg.add_text(
                        f"{name.title()} — {self._mood}",
                        tag=self._mood_tag,
                        color=[60, 50, 50, 255],
                    )
                except Exception:
                    pass

                # 96×96 preview pane — drawn as a placeholder text
                # block in headless mode; a real DPG context can paint
                # a radial gradient via ``add_drawlist`` later.
                try:
                    dpg.add_text(
                        f"[preview {self.PREVIEW_PX}x{self.PREVIEW_PX}]",
                        tag=self._preview_tag,
                        color=list(self._swatch_stops[-1])
                        if self._swatch_stops
                        else [200, 200, 200, 255],
                    )
                except Exception:
                    pass
        except Exception:
            # Stub-DPG flat path — emit each item individually so the
            # tags still register.
            for token, tag, colour in (
                (self._sticker, self._sticker_tag, [200, 80, 120, 255]),
                (f"{name.title()} — {self._mood}", self._mood_tag,
                 [60, 50, 50, 255]),
                (f"[preview {self.PREVIEW_PX}x{self.PREVIEW_PX}]",
                 self._preview_tag,
                 list(self._swatch_stops[-1]) if self._swatch_stops
                 else [200, 200, 200, 255]),
            ):
                try:
                    dpg.add_text(token, parent=self._panel_tag,
                                 tag=tag, color=colour)
                except Exception:
                    pass

        self.call_log.append(("story_header", self._kind, name))

    # ------------------------------------------------------------------
    # Swatch row — two side-by-side swatches with a gradient between.
    # ------------------------------------------------------------------

    def _render_swatch_row(self, dpg: Any) -> None:
        stops = self._swatch_stops
        if not stops:
            return

        try:
            with dpg.group(parent=self._panel_tag, tag=self._swatch_tag, horizontal=True):
                for i, c in enumerate(stops):
                    try:
                        dpg.add_color_edit(
                            label=f"swatch_{i}",
                            default_value=list(c),
                            no_inputs=True,
                            width=self.SWATCH_PX,
                            tag=f"{self._swatch_tag}_{i}",
                        )
                    except Exception:
                        # Fall back to a coloured text token so the
                        # tag still registers.
                        try:
                            dpg.add_text(
                                f"[swatch_{i}]",
                                parent=self._swatch_tag,
                                tag=f"{self._swatch_tag}_{i}",
                                color=list(c),
                            )
                        except Exception:
                            pass

                # Gradient strip between the two ends.  Rendered as a
                # text token in headless mode; the theme can repaint
                # it with a drawlist in a real DPG context.
                try:
                    dpg.add_text(
                        "================",
                        color=list(stops[0]),
                        tag=f"{self._swatch_tag}_grad",
                    )
                except Exception:
                    pass
        except Exception:
            # Stub-DPG flat path — emit each swatch individually.
            for i, c in enumerate(stops):
                try:
                    dpg.add_color_edit(
                        label=f"swatch_{i}",
                        default_value=list(c),
                        no_inputs=True,
                        width=self.SWATCH_PX,
                        parent=self._panel_tag,
                        tag=f"{self._swatch_tag}_{i}",
                    )
                except Exception:
                    try:
                        dpg.add_text(
                            f"[swatch_{i}]",
                            parent=self._panel_tag,
                            tag=f"{self._swatch_tag}_{i}",
                            color=list(c),
                        )
                    except Exception:
                        pass

        self.call_log.append(("swatch_row", self._kind, len(stops)))

    # ------------------------------------------------------------------
    # Editable-field section — delegated to NotebookInspector.
    # ------------------------------------------------------------------

    def _render_fields(self, dpg: Any) -> None:
        """Reflect every editable field on *target* via NotebookInspector.

        We give the inspector a fresh container child window so its
        own tag tree never collides with the parent editor's swatch
        widgets.
        """
        try:
            dpg.add_child_window(
                tag=self._fields_tag,
                parent=self._panel_tag,
                border=False,
                autosize_x=True,
                height=-1,
            )
        except Exception:
            # No real DPG — just continue; the inspector will degrade.
            pass

        target_for_inspector = self._inspector_target()
        if target_for_inspector is None:
            try:
                dpg.add_text(
                    "(no editable fields)",
                    parent=self._fields_tag,
                )
            except Exception:
                pass
            self.call_log.append(("fields", self._kind, 0))
            return

        try:
            inspector = NotebookInspector(target=target_for_inspector)
            inspector.build(self._fields_tag)
            self._inspector = inspector
        except Exception:
            inspector = None

        field_count = 0
        if dataclasses.is_dataclass(target_for_inspector) and not isinstance(
            target_for_inspector, type,
        ):
            field_count = len(dataclasses.fields(target_for_inspector))
        self.call_log.append(("fields", self._kind, field_count))

    # ------------------------------------------------------------------
    # Internal helpers — swatch + inspector target selection
    # ------------------------------------------------------------------

    def _compute_swatch_stops(self) -> list[tuple[int, int, int, int]]:
        """Return the colour stops appropriate for the current kind."""
        target = self._target
        if target is None:
            return []

        if self._kind == KIND_MATERIAL_MAP:
            mats = getattr(target, "_materials", None) or []
            if not mats:
                return []
            cr = getattr(mats[0], "color_range", None)
            if cr is None:
                return []
            return [
                _color_range_low(cr),
                _color_range_high(cr),
            ]

        if self._kind == KIND_SOFTBODY:
            return [
                _rgb_tuple_to_rgba(getattr(target, "render_color",
                                           (180, 180, 180))),
                _rgb_tuple_to_rgba(getattr(target, "damage_color",
                                           (40, 12, 8))),
            ]

        if self._kind == KIND_FLUID:
            return _fluid_stops(target)

        return []

    def _inspector_target(self) -> Any:
        """Return the dataclass-shaped object the inspector should reflect.

        For dataclass kinds (softbody / fluid) we just hand the target
        through.  For ``material_map`` we hand through the first
        :class:`MaterialDef` so the inspector can render its name,
        ``alpha_meaning``, behaviours and params — the swatch row
        already handles the colour range above.
        """
        if self._target is None:
            return None
        if self._kind == KIND_MATERIAL_MAP:
            mats = getattr(self._target, "_materials", None) or []
            return mats[0] if mats else None
        return self._target

    # ------------------------------------------------------------------
    # Theme integration — repaint hooks for the theme switcher.
    # ------------------------------------------------------------------

    def on_theme_change(self) -> None:
        """Refresh on active-theme change so palette tokens repaint."""
        self.call_log.append(("theme_change",))
        self.refresh()


__all__ = ["NotebookMaterialEditor"]
