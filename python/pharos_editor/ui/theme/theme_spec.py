"""Declarative theme specification dataclasses.

A :class:`ThemeSpec` is a pure-data description of a UI theme: palette
entries, semantic design tokens, font records, nine-slice borders, SVG
icons, design-system scales (spacing / radius / transitions / z-index),
and an optional procedural background shader. It carries no rendering
state of its own — themes are *registered* and *applied* through
``pharos_editor.ui.theme``.

The dataclasses defined here are deliberately small so themes round-trip
cleanly through YAML / JSON. Heavier rasterisation work lives in the
sibling modules (:mod:`nine_slice`, :mod:`svg_icon`, :mod:`shader_effects`).

Design provenance
-----------------
The semantic-token layer (:class:`SemanticTokens`) plus the four design
scales (:class:`SpacingScale`, :class:`RadiusScale`,
:class:`TransitionScale`, :class:`ZIndexScale`) draw their structure from
the **EyesOfAzrael** Firebase-themes CSS architecture
(``css/firebase-themes.css``). That stylesheet treats raw palette
colours as *implementation* and a stable named token surface
(``--theme-primary``, ``--glass-bg``, ``--radius-md`` …) as the
*contract* every component renders against. Pharos Engine adopts the
same split: :attr:`ThemeSpec.palette` is the raw bag of authored
colours; :attr:`ThemeSpec.semantic` is the named contract widget code
binds to.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

from pharos_engine._validation import (
    validate_finite_float,
    validate_non_empty_str,
    validate_non_negative_float,
    validate_non_negative_int,
    validate_positive_float,
    validate_positive_int,
    validate_str,
    validate_unit_float,
)


# ---------------------------------------------------------------------------
# Colour
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Color:
    """An sRGB colour with 8-bit per-channel + unit alpha.

    Parameters
    ----------
    r, g, b:
        Channels in ``[0, 255]``.
    a:
        Alpha in ``[0.0, 1.0]``. Float-valued so themes can author
        translucent surfaces without re-scaling to 0..255.
    """

    r: int = 0
    g: int = 0
    b: int = 0
    a: float = 1.0

    def __post_init__(self) -> None:
        fn = "Color"
        r = validate_non_negative_int("r", fn, self.r)
        g = validate_non_negative_int("g", fn, self.g)
        b = validate_non_negative_int("b", fn, self.b)
        for name, value in (("r", r), ("g", g), ("b", b)):
            if value > 255:
                raise ValueError(f"{fn}: {name} must be <= 255; got {value}")
        a = validate_unit_float("a", fn, self.a)
        # frozen=True so we have to use object.__setattr__ to normalise.
        object.__setattr__(self, "r", int(r))
        object.__setattr__(self, "g", int(g))
        object.__setattr__(self, "b", int(b))
        object.__setattr__(self, "a", float(a))

    def as_rgba_tuple(self) -> tuple[int, int, int, int]:
        """Return ``(r, g, b, a)`` with alpha scaled to ``[0, 255]``."""
        return (self.r, self.g, self.b, int(round(self.a * 255)))

    def as_float_tuple(self) -> tuple[float, float, float, float]:
        """Return ``(r, g, b, a)`` with every channel in ``[0, 1]``."""
        return (self.r / 255.0, self.g / 255.0, self.b / 255.0, self.a)


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------


@dataclass
class Palette:
    """A named bag of :class:`Color` entries.

    The keys are arbitrary semantic role names ("primary", "surface",
    "accent", …). A palette is just a typed dict so it survives YAML
    round-trips without custom loaders.
    """

    name: str = "default"
    entries: dict[str, Color] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "Palette"
        self.name = validate_non_empty_str("name", fn, self.name)
        if not isinstance(self.entries, dict):
            raise TypeError(
                f"{fn}: entries must be a dict; got {type(self.entries).__name__}"
            )
        for key, value in self.entries.items():
            validate_non_empty_str("entries key", fn, key)
            if not isinstance(value, Color):
                raise TypeError(
                    f"{fn}: entries[{key!r}] must be a Color; "
                    f"got {type(value).__name__}"
                )

    def get(self, role: str, default: Color | None = None) -> Color | None:
        return self.entries.get(role, default)


# ---------------------------------------------------------------------------
# Font
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Font:
    """A font record — family name, point size, weight.

    No rasterisation is implied; the theme just *names* a font and
    leaves resolution to the renderer (DPG, PIL, browser, …).
    """

    family: str = "sans-serif"
    size: int = 14
    weight: str = "regular"

    def __post_init__(self) -> None:
        fn = "Font"
        object.__setattr__(
            self, "family", validate_non_empty_str("family", fn, self.family)
        )
        object.__setattr__(
            self, "size", validate_positive_int("size", fn, self.size)
        )
        object.__setattr__(
            self, "weight", validate_non_empty_str("weight", fn, self.weight)
        )


# ---------------------------------------------------------------------------
# Design-system scales (EyesOfAzrael CSS custom-property analogue)
# ---------------------------------------------------------------------------
#
# EyesOfAzrael's ``firebase-themes.css`` exposes spacing / radius /
# transition / z-index as CSS custom properties so every component reads
# from one source of truth. Pharos Engine mirrors that with four small
# dataclasses below. Each is a *frozen* dataclass so themes can share
# instances safely, and each validates its values in ``__post_init__``.


@dataclass(frozen=True)
class SpacingScale:
    """Eight-step spacing scale, values in DPG pixels.

    Defaults track the EyesOfAzrael CSS spacing scale (xs=0.25rem,
    sm=0.5rem, …) translated to pixel values that read well in a
    Dear PyGui editor at 1× DPI. Custom themes may override any field.

    Every value must be a non-negative finite number; zero is permitted
    (some layouts genuinely want a 0-pixel gap step).
    """

    xs: float = 4.0
    sm: float = 8.0
    md: float = 16.0
    lg: float = 24.0
    xl: float = 32.0
    xxl: float = 48.0

    def __post_init__(self) -> None:
        fn = "SpacingScale"
        for name in ("xs", "sm", "md", "lg", "xl", "xxl"):
            v = validate_non_negative_float(name, fn, getattr(self, name))
            object.__setattr__(self, name, float(v))


@dataclass(frozen=True)
class RadiusScale:
    """Five-step border-radius scale, values in DPG pixels.

    ``pill`` defaults to ``999`` so callers can use it interchangeably
    with CSS-style ``border-radius: 9999px`` for fully-rounded pills.

    Every value must be a non-negative finite number.
    """

    sm: float = 4.0
    md: float = 8.0
    lg: float = 12.0
    xl: float = 16.0
    pill: float = 999.0

    def __post_init__(self) -> None:
        fn = "RadiusScale"
        for name in ("sm", "md", "lg", "xl", "pill"):
            v = validate_non_negative_float(name, fn, getattr(self, name))
            object.__setattr__(self, name, float(v))


@dataclass(frozen=True)
class TransitionScale:
    """Three-step transition-duration scale, values in seconds.

    Mirrors EyesOfAzrael's ``--transition-fast / --transition-normal /
    --transition-slow``. Every value must be a *positive* finite number
    (a zero-duration transition is a no-op and almost always a bug at
    the boundary).
    """

    fast: float = 0.15
    normal: float = 0.25
    slow: float = 0.5

    def __post_init__(self) -> None:
        fn = "TransitionScale"
        for name in ("fast", "normal", "slow"):
            v = validate_positive_float(name, fn, getattr(self, name))
            object.__setattr__(self, name, float(v))


@dataclass(frozen=True)
class ZIndexScale:
    """Four-tier z-index scale.

    The defaults match the EyesOfAzrael layering convention
    (``--z-base / --z-dropdown / --z-modal / --z-toast``) and rise
    monotonically — overlapping tiers are rejected at construction
    time so a typo cannot silently shuffle a toast under a modal.
    """

    base: int = 1
    dropdown: int = 100
    modal: int = 1000
    toast: int = 2000

    def __post_init__(self) -> None:
        fn = "ZIndexScale"
        for name in ("base", "dropdown", "modal", "toast"):
            v = validate_non_negative_int(name, fn, getattr(self, name))
            object.__setattr__(self, name, int(v))
        if not (self.base <= self.dropdown <= self.modal <= self.toast):
            raise ValueError(
                f"{fn}: tiers must rise monotonically "
                f"(base <= dropdown <= modal <= toast); got "
                f"({self.base}, {self.dropdown}, {self.modal}, {self.toast})"
            )


# ---------------------------------------------------------------------------
# Gradient
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Gradient:
    """A two-stop linear gradient with an angle.

    Parameters
    ----------
    start, end:
        Endpoint :class:`Color` instances.
    angle_deg:
        Gradient direction in degrees. ``135.0`` (top-left → bottom-right)
        is the EyesOfAzrael convention for ``--theme-gradient``.
    """

    start: "Color"
    end: "Color"
    angle_deg: float = 135.0

    def __post_init__(self) -> None:
        fn = "Gradient"
        if not isinstance(self.start, Color):
            raise TypeError(
                f"{fn}: start must be a Color; got {type(self.start).__name__}"
            )
        if not isinstance(self.end, Color):
            raise TypeError(
                f"{fn}: end must be a Color; got {type(self.end).__name__}"
            )
        angle = validate_finite_float("angle_deg", fn, self.angle_deg)
        object.__setattr__(self, "angle_deg", float(angle))

    def sample(self, t: float) -> "Color":
        """Return the gradient colour at parameter *t* in ``[0, 1]``.

        Interpolation is linear per-channel in sRGB space (matches the
        EyesOfAzrael CSS ``linear-gradient`` behaviour). ``t=0`` returns
        :attr:`start`, ``t=1`` returns :attr:`end`, ``t=0.5`` returns
        the midpoint.
        """
        t_clamped = validate_unit_float("t", "Gradient.sample", t)
        r = int(round(self.start.r + (self.end.r - self.start.r) * t_clamped))
        g = int(round(self.start.g + (self.end.g - self.start.g) * t_clamped))
        b = int(round(self.start.b + (self.end.b - self.start.b) * t_clamped))
        a = self.start.a + (self.end.a - self.start.a) * t_clamped
        return Color(r=r, g=g, b=b, a=a)


# ---------------------------------------------------------------------------
# SemanticTokens (the named contract widget code binds to)
# ---------------------------------------------------------------------------


@dataclass
class SemanticTokens:
    """A named layer above the raw palette.

    Widget code should read from this layer rather than from
    :attr:`Palette.entries` directly — that way switching themes only
    requires rebinding the token surface, not rewriting widgets.

    Field names track the EyesOfAzrael ``--theme-*`` / ``--glass-*``
    custom-property vocabulary so the cognitive load of moving between
    the web and editor surfaces is minimised.

    Attributes
    ----------
    primary, secondary, accent:
        The three brand colours.
    primary_gradient:
        The hero gradient (typically a 135° sweep from ``primary`` into
        a lighter or darker neighbour).
    background, surface, surface_hover:
        Page background, raised-card surface, and hover-state surface.
    border:
        Default 1 px component border.
    text_primary, text_secondary, text_disabled:
        Three text strengths.
    success, warning, error, info:
        Status colours.
    focus_ring:
        Keyboard-focus outline.
    glass_bg, glass_blur_px:
        Glassmorphism translucent panel colour + backdrop-blur sigma
        in pixels (EyesOfAzrael ``--glass-bg`` / ``--glass-blur``).
    """

    primary: "Color"
    primary_gradient: "Gradient"
    secondary: "Color"
    accent: "Color"
    background: "Color"
    surface: "Color"
    surface_hover: "Color"
    border: "Color"
    text_primary: "Color"
    text_secondary: "Color"
    text_disabled: "Color"
    success: "Color"
    warning: "Color"
    error: "Color"
    info: "Color"
    focus_ring: "Color"
    glass_bg: "Color"
    glass_blur_px: float

    # ``ClassVar`` keeps this off the dataclass field list — purely a
    # name index used by ``__post_init__`` / ``to_dict`` / ``from_dict``.
    _COLOR_FIELDS: ClassVar[tuple[str, ...]] = (
        "primary",
        "secondary",
        "accent",
        "background",
        "surface",
        "surface_hover",
        "border",
        "text_primary",
        "text_secondary",
        "text_disabled",
        "success",
        "warning",
        "error",
        "info",
        "focus_ring",
        "glass_bg",
    )

    def __post_init__(self) -> None:
        fn = "SemanticTokens"
        for name in self._COLOR_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, Color):
                raise TypeError(
                    f"{fn}: {name} must be a Color; "
                    f"got {type(value).__name__}"
                )
        if not isinstance(self.primary_gradient, Gradient):
            raise TypeError(
                f"{fn}: primary_gradient must be a Gradient; "
                f"got {type(self.primary_gradient).__name__}"
            )
        blur = validate_non_negative_float(
            "glass_blur_px", fn, self.glass_blur_px
        )
        self.glass_blur_px = float(blur)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a YAML/JSON-safe dict."""
        out: dict[str, Any] = {}
        for name in self._COLOR_FIELDS:
            c: Color = getattr(self, name)
            out[name] = [c.r, c.g, c.b, c.a]
        out["primary_gradient"] = {
            "start": [
                self.primary_gradient.start.r,
                self.primary_gradient.start.g,
                self.primary_gradient.start.b,
                self.primary_gradient.start.a,
            ],
            "end": [
                self.primary_gradient.end.r,
                self.primary_gradient.end.g,
                self.primary_gradient.end.b,
                self.primary_gradient.end.a,
            ],
            "angle_deg": self.primary_gradient.angle_deg,
        }
        out["glass_blur_px"] = self.glass_blur_px
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SemanticTokens":
        """Rebuild a :class:`SemanticTokens` from :meth:`to_dict` output."""
        if not isinstance(data, dict):
            raise TypeError(
                f"SemanticTokens.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )

        def _color(key: str) -> Color:
            raw = data.get(key)
            if isinstance(raw, Color):
                return raw
            if isinstance(raw, (list, tuple)) and len(raw) == 4:
                return Color(int(raw[0]), int(raw[1]), int(raw[2]), float(raw[3]))
            raise TypeError(
                f"SemanticTokens.from_dict: {key!r} must be Color or "
                f"4-sequence; got {type(raw).__name__}"
            )

        grad_raw = data.get("primary_gradient")
        if isinstance(grad_raw, Gradient):
            gradient = grad_raw
        elif isinstance(grad_raw, dict):
            start_raw = grad_raw.get("start")
            end_raw = grad_raw.get("end")
            if isinstance(start_raw, (list, tuple)) and len(start_raw) == 4:
                start = Color(
                    int(start_raw[0]),
                    int(start_raw[1]),
                    int(start_raw[2]),
                    float(start_raw[3]),
                )
            elif isinstance(start_raw, Color):
                start = start_raw
            else:
                raise TypeError(
                    "SemanticTokens.from_dict: primary_gradient.start "
                    "must be Color or 4-sequence"
                )
            if isinstance(end_raw, (list, tuple)) and len(end_raw) == 4:
                end = Color(
                    int(end_raw[0]),
                    int(end_raw[1]),
                    int(end_raw[2]),
                    float(end_raw[3]),
                )
            elif isinstance(end_raw, Color):
                end = end_raw
            else:
                raise TypeError(
                    "SemanticTokens.from_dict: primary_gradient.end "
                    "must be Color or 4-sequence"
                )
            gradient = Gradient(
                start=start,
                end=end,
                angle_deg=float(grad_raw.get("angle_deg", 135.0)),
            )
        else:
            raise TypeError(
                "SemanticTokens.from_dict: primary_gradient must be "
                f"Gradient or dict; got {type(grad_raw).__name__}"
            )

        return cls(
            primary=_color("primary"),
            primary_gradient=gradient,
            secondary=_color("secondary"),
            accent=_color("accent"),
            background=_color("background"),
            surface=_color("surface"),
            surface_hover=_color("surface_hover"),
            border=_color("border"),
            text_primary=_color("text_primary"),
            text_secondary=_color("text_secondary"),
            text_disabled=_color("text_disabled"),
            success=_color("success"),
            warning=_color("warning"),
            error=_color("error"),
            info=_color("info"),
            focus_ring=_color("focus_ring"),
            glass_bg=_color("glass_bg"),
            glass_blur_px=float(data.get("glass_blur_px", 0.0)),
        )


# ---------------------------------------------------------------------------
# Forward declarations — concrete classes live in sibling modules
# ---------------------------------------------------------------------------
#
# ``NineSlice``, ``SVGIcon``, and ``ShaderEffect`` are re-exported from
# the package ``__init__`` so the theme module is a single import target.
# We declare them here only as the type names ThemeSpec quotes; the real
# implementations sit in ``nine_slice.py`` / ``svg_icon.py`` /
# ``shader_effects.py`` so this module stays cheap to import.


@dataclass
class ShaderEffect:
    """A named procedural-texture recipe.

    A ``ShaderEffect`` is just a record: a callable name plus a kwargs
    bag that callers feed into a renderer-side dispatcher
    (typically one of the helpers in :mod:`shader_effects`).

    Parameters
    ----------
    name:
        Identifier of the effect (matches a function name in
        :mod:`shader_effects`, e.g. ``"ruled_paper"``).
    params:
        Plain-Python kwargs bag — numbers, strings, :class:`Color`
        instances. YAML-safe.
    """

    name: str
    params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "ShaderEffect"
        self.name = validate_non_empty_str("name", fn, self.name)
        if not isinstance(self.params, dict):
            raise TypeError(
                f"{fn}: params must be a dict; got {type(self.params).__name__}"
            )


# ---------------------------------------------------------------------------
# Background-shader serialisation helpers
# ---------------------------------------------------------------------------
#
# The ``background_shader`` field on :class:`ThemeSpec` accepts either
# the CPU-side :class:`ShaderEffect` or the GPU-side
# :class:`~.wgsl_backgrounds.WGSLShaderSpec`. Both round-trip through
# YAML via these helpers — a ``"kind"`` tag disambiguates the two on
# reload. Legacy dicts without a ``"kind"`` tag are treated as
# ``ShaderEffect`` for backwards compatibility.


def _serialise_background_shader(shader: Any) -> Any:
    """Serialise a ThemeSpec.background_shader to a YAML-safe dict.

    Returns ``None`` when *shader* is ``None``. :class:`ShaderEffect`
    serialises to ``{"kind": "shader_effect", "name": ..., "params": ...}``
    and :class:`WGSLShaderSpec` to
    ``{"kind": "wgsl", "source": ..., ...}`` so :meth:`ThemeSpec.from_dict`
    can pick the correct constructor on reload without introspecting
    each field.
    """
    if shader is None:
        return None
    # Delayed import to keep the theme_spec module cheap to import.
    from .wgsl_backgrounds import WGSLShaderSpec as _WGSLSpec
    if isinstance(shader, str):
        # Page-lining id — tagged so from_dict can pick the right arm.
        return {"kind": "lining", "style_id": shader}
    if isinstance(shader, _WGSLSpec):
        payload = shader.to_dict()
        payload["kind"] = "wgsl"
        return payload
    if isinstance(shader, ShaderEffect):
        return {
            "kind": "shader_effect",
            "name": shader.name,
            "params": dict(shader.params),
        }
    raise TypeError(
        "_serialise_background_shader: shader must be ShaderEffect, "
        f"WGSLShaderSpec, page-lining id str, or None; "
        f"got {type(shader).__name__}"
    )


def _deserialise_background_shader(raw: Any) -> Any:
    """Rebuild a background shader from :func:`_serialise_background_shader`.

    Accepts ``None`` (returns ``None``), a live :class:`ShaderEffect`
    / :class:`~.wgsl_backgrounds.WGSLShaderSpec` (passes through), or
    a dict produced by :func:`_serialise_background_shader`. Dicts
    without a ``"kind"`` tag default to ``ShaderEffect`` so legacy
    YAML files keep loading.
    """
    if raw is None:
        return None
    from .wgsl_backgrounds import WGSLShaderSpec as _WGSLSpec
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (ShaderEffect, _WGSLSpec)):
        return raw
    if isinstance(raw, dict):
        kind = raw.get("kind")
        if kind == "lining":
            return str(raw.get("style_id", ""))
        if kind == "wgsl" or "source" in raw:
            payload = {k: v for k, v in raw.items() if k != "kind"}
            return _WGSLSpec.from_dict(payload)
        return ShaderEffect(
            name=raw.get("name", ""),
            params=dict(raw.get("params", {})),
        )
    raise TypeError(
        "ThemeSpec.from_dict: background_shader must be dict, "
        "ShaderEffect, WGSLShaderSpec, page-lining id str, or None; "
        f"got {type(raw).__name__}"
    )


# ---------------------------------------------------------------------------
# FrameStyle & PanelFrameSet — DPG panel frame tokens
# ---------------------------------------------------------------------------
#
# DPG panels (windows, child windows, modals) are drawn as a stack of
# coloured borders, rounded corners, drop shadows, and interior padding.
# ``FrameStyle`` collects every numeric token that drives that stack into
# one place so a theme can say "thick leather border, padding 12x10,
# rounded 6 px" once and have it apply uniformly across every panel of
# that kind. ``PanelFrameSet`` is the per-panel-kind bag — a theme can
# give toolbars one frame style, modals another, etc., with a default
# fallback.


@dataclass
class FrameStyle:
    """Numeric tokens that drive a DPG panel's border / shadow / padding.

    Every value is a non-negative finite number. ``border_color`` and
    ``shadow_color`` may be ``None`` so the renderer can fall back to
    ``semantic.border`` / a derived ink-at-30 %-alpha respectively.

    Maps to DPG style vars via :func:`dpg_bridge.apply_theme_to_dpg`.
    """

    border_size: float = 1.0
    border_color: "Color | None" = None
    rounding: float = 8.0
    padding_x: int = 8
    padding_y: int = 6
    shadow_size: float = 4.0
    shadow_color: "Color | None" = None
    child_rounding: float = 6.0
    child_border_size: float = 0.5
    grip_size: float = 12.0
    grip_rounding: float = 4.0
    title_bar_height: int = 24
    # Optional hand-drawn edge stroke — when set, the renderer draws a
    # textured border (pencil / marker / brush / etc.) around the panel
    # instead of the flat ``border_color`` line. See
    # :mod:`pharos_editor.ui.theme.edge_strokes`.
    edge_stroke: Any = None

    def __post_init__(self) -> None:
        fn = "FrameStyle"
        for name in (
            "border_size",
            "rounding",
            "shadow_size",
            "child_rounding",
            "child_border_size",
            "grip_size",
            "grip_rounding",
        ):
            v = validate_non_negative_float(name, fn, getattr(self, name))
            object.__setattr__(self, name, float(v))
        for name in ("padding_x", "padding_y", "title_bar_height"):
            v = validate_non_negative_int(name, fn, getattr(self, name))
            object.__setattr__(self, name, int(v))
        for name in ("border_color", "shadow_color"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, Color):
                raise TypeError(
                    f"{fn}: {name} must be a Color or None; "
                    f"got {type(value).__name__}"
                )
        if self.edge_stroke is not None:
            # Local import — theme_spec must remain cheap to import.
            from .edge_strokes.library import EdgeStrokeStyle
            if not isinstance(self.edge_stroke, EdgeStrokeStyle):
                raise TypeError(
                    f"{fn}: edge_stroke must be EdgeStrokeStyle or None; "
                    f"got {type(self.edge_stroke).__name__}"
                )


@dataclass
class PanelFrameSet:
    """Per-panel-kind :class:`FrameStyle` bag with a default fallback.

    Themes only have to populate the kinds they care about; every
    unset kind falls through to :attr:`default`. ``for_panel("toolbar")``
    is the canonical lookup — it returns the matching slot if set,
    else :attr:`default`. Panel kinds the editor uses are: ``toolbar``,
    ``sidebar`` (inspector, outliner, theme switcher), ``viewport``,
    ``modal`` (welcome, project picker), ``code_pane``, ``status_bar``.
    """

    default: FrameStyle = field(default_factory=FrameStyle)
    toolbar: FrameStyle | None = None
    sidebar: FrameStyle | None = None
    viewport: FrameStyle | None = None
    modal: FrameStyle | None = None
    code_pane: FrameStyle | None = None
    status_bar: FrameStyle | None = None

    _KINDS: ClassVar[tuple[str, ...]] = (
        "toolbar",
        "sidebar",
        "viewport",
        "modal",
        "code_pane",
        "status_bar",
    )

    def __post_init__(self) -> None:
        fn = "PanelFrameSet"
        if not isinstance(self.default, FrameStyle):
            raise TypeError(
                f"{fn}: default must be a FrameStyle; "
                f"got {type(self.default).__name__}"
            )
        for name in self._KINDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, FrameStyle):
                raise TypeError(
                    f"{fn}: {name} must be a FrameStyle or None; "
                    f"got {type(value).__name__}"
                )

    def for_panel(self, kind: str) -> FrameStyle:
        """Return the :class:`FrameStyle` for *kind*, falling back to default.

        Unknown kinds return :attr:`default` rather than raising — a panel
        without a specific style entry is the most common case, not an
        error.
        """
        validate_non_empty_str("kind", "PanelFrameSet.for_panel", kind)
        if kind in self._KINDS:
            value = getattr(self, kind)
            if value is not None:
                return value
        return self.default


# ---------------------------------------------------------------------------
# PanelDecorConfig — hand-drawn dividers + washi-tape corner defaults
# ---------------------------------------------------------------------------


@dataclass
class PanelDecorConfig:
    """Per-theme defaults for the ``panel_decor`` renderer.

    The ``panel_decor`` renderer draws hand-drawn dividers between nested
    panels and washi-tape corner stickers on floating (dragged-out)
    windows. A ``PanelDecorConfig`` picks the default divider + corner
    style for the theme and lets themes override per panel kind.

    Divider / corner style names are stored as plain strings so this
    dataclass stays YAML-safe. The panel_decor module maps the strings
    to its own ``DividerStyle`` / ``WashiCornerStyle`` enums at draw
    time.
    """

    divider_style: str = "wavy"
    corner_style: str = "tape_pink"
    divider_thickness_px: int = 2
    corner_size_px: int = 32
    per_kind: dict[str, tuple[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "PanelDecorConfig"
        self.divider_style = validate_non_empty_str(
            "divider_style", fn, self.divider_style,
        )
        self.corner_style = validate_non_empty_str(
            "corner_style", fn, self.corner_style,
        )
        self.divider_thickness_px = validate_positive_int(
            "divider_thickness_px", fn, self.divider_thickness_px,
        )
        self.corner_size_px = validate_positive_int(
            "corner_size_px", fn, self.corner_size_px,
        )
        if not isinstance(self.per_kind, dict):
            raise TypeError(
                f"{fn}: per_kind must be a dict; "
                f"got {type(self.per_kind).__name__}"
            )
        for key, value in self.per_kind.items():
            validate_non_empty_str("per_kind key", fn, key)
            if (
                not isinstance(value, tuple)
                or len(value) != 2
                or not all(isinstance(v, str) and v for v in value)
            ):
                raise TypeError(
                    f"{fn}: per_kind[{key!r}] must be a (str, str) tuple; "
                    f"got {value!r}"
                )

    def for_panel(self, kind: str) -> tuple[str, str]:
        """Return ``(divider_style, corner_style)`` for *kind*.

        Falls back to the top-level defaults when *kind* is not present
        in :attr:`per_kind`.
        """
        validate_non_empty_str("kind", "PanelDecorConfig.for_panel", kind)
        override = self.per_kind.get(kind)
        if override is not None:
            return override
        return (self.divider_style, self.corner_style)


# ---------------------------------------------------------------------------
# Frames / decor YAML serialisation helpers
# ---------------------------------------------------------------------------
#
# ``ThemeSpec.frames`` and ``ThemeSpec.decor`` are nested dataclasses;
# these module-level helpers flatten them to YAML-safe dicts and back.
# Round-trip is lossless — every field on :class:`FrameStyle`,
# :class:`PanelFrameSet`, and :class:`PanelDecorConfig` survives a full
# ``to_dict → from_dict`` cycle. Used by :meth:`ThemeSpec.to_dict` and
# :meth:`ThemeSpec.from_dict`.


def _frames_to_dict(frames: "PanelFrameSet") -> dict[str, Any]:
    """Serialise a :class:`PanelFrameSet` to a YAML-safe dict."""

    def _fs(style: "FrameStyle | None") -> dict[str, Any] | None:
        if style is None:
            return None
        out: dict[str, Any] = {
            "border_size": style.border_size,
            "rounding": style.rounding,
            "padding_x": style.padding_x,
            "padding_y": style.padding_y,
            "shadow_size": style.shadow_size,
            "child_rounding": style.child_rounding,
            "child_border_size": style.child_border_size,
            "grip_size": style.grip_size,
            "grip_rounding": style.grip_rounding,
            "title_bar_height": style.title_bar_height,
        }
        if style.border_color is not None:
            bc = style.border_color
            out["border_color"] = [bc.r, bc.g, bc.b, bc.a]
        if style.shadow_color is not None:
            sc = style.shadow_color
            out["shadow_color"] = [sc.r, sc.g, sc.b, sc.a]
        return out

    result: dict[str, Any] = {"default": _fs(frames.default)}
    for kind in PanelFrameSet._KINDS:
        override = getattr(frames, kind)
        if override is not None:
            result[kind] = _fs(override)
    return result


def _frames_from_dict(raw: Any) -> "PanelFrameSet":
    """Rebuild a :class:`PanelFrameSet` from :func:`_frames_to_dict`."""
    if raw is None:
        return PanelFrameSet()
    if isinstance(raw, PanelFrameSet):
        return raw
    if not isinstance(raw, dict):
        raise TypeError(
            f"_frames_from_dict: frames must be a dict or "
            f"PanelFrameSet; got {type(raw).__name__}"
        )

    def _color_or_none(v: Any) -> Color | None:
        if v is None:
            return None
        if isinstance(v, Color):
            return v
        if isinstance(v, (list, tuple)) and len(v) == 4:
            return Color(int(v[0]), int(v[1]), int(v[2]), float(v[3]))
        raise TypeError(
            "_frames_from_dict: frame colour must be Color, "
            f"4-sequence, or None; got {type(v).__name__}"
        )

    def _fs(entry: Any) -> "FrameStyle | None":
        if entry is None:
            return None
        if isinstance(entry, FrameStyle):
            return entry
        if not isinstance(entry, dict):
            raise TypeError(
                "_frames_from_dict: frame entry must be a dict, "
                f"FrameStyle, or None; got {type(entry).__name__}"
            )
        kwargs: dict[str, Any] = {}
        for key in (
            "border_size", "rounding", "shadow_size",
            "child_rounding", "child_border_size",
            "grip_size", "grip_rounding",
        ):
            if key in entry:
                kwargs[key] = float(entry[key])
        for key in ("padding_x", "padding_y", "title_bar_height"):
            if key in entry:
                kwargs[key] = int(entry[key])
        if "border_color" in entry:
            kwargs["border_color"] = _color_or_none(entry["border_color"])
        if "shadow_color" in entry:
            kwargs["shadow_color"] = _color_or_none(entry["shadow_color"])
        return FrameStyle(**kwargs)

    default_style = _fs(raw.get("default")) or FrameStyle()
    overrides: dict[str, "FrameStyle | None"] = {}
    for kind in PanelFrameSet._KINDS:
        if kind in raw:
            overrides[kind] = _fs(raw[kind])
    return PanelFrameSet(default=default_style, **overrides)


def _decor_to_dict(decor: "PanelDecorConfig") -> dict[str, Any]:
    """Serialise a :class:`PanelDecorConfig` to a YAML-safe dict."""
    return {
        "divider_style": decor.divider_style,
        "corner_style": decor.corner_style,
        "divider_thickness_px": decor.divider_thickness_px,
        "corner_size_px": decor.corner_size_px,
        "per_kind": {
            k: [v[0], v[1]] for k, v in decor.per_kind.items()
        },
    }


def _decor_from_dict(raw: Any) -> "PanelDecorConfig":
    """Rebuild a :class:`PanelDecorConfig` from :func:`_decor_to_dict`."""
    if raw is None:
        return PanelDecorConfig()
    if isinstance(raw, PanelDecorConfig):
        return raw
    if not isinstance(raw, dict):
        raise TypeError(
            f"_decor_from_dict: decor must be a dict or "
            f"PanelDecorConfig; got {type(raw).__name__}"
        )
    per_kind_raw = raw.get("per_kind") or {}
    if not isinstance(per_kind_raw, dict):
        raise TypeError(
            "_decor_from_dict: decor.per_kind must be a dict; "
            f"got {type(per_kind_raw).__name__}"
        )
    per_kind: dict[str, tuple[str, str]] = {}
    for key, value in per_kind_raw.items():
        if isinstance(value, list):
            value = tuple(value)
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or not all(isinstance(v, str) and v for v in value)
        ):
            raise TypeError(
                f"_decor_from_dict: decor.per_kind[{key!r}] must be "
                f"a (str, str) pair; got {value!r}"
            )
        per_kind[key] = (value[0], value[1])
    return PanelDecorConfig(
        divider_style=str(raw.get("divider_style", "wavy")),
        corner_style=str(raw.get("corner_style", "tape_pink")),
        divider_thickness_px=int(raw.get("divider_thickness_px", 2)),
        corner_size_px=int(raw.get("corner_size_px", 32)),
        per_kind=per_kind,
    )


# ---------------------------------------------------------------------------
# ThemeSpec
# ---------------------------------------------------------------------------


@dataclass
class ThemeSpec:
    """Top-level declarative theme.

    Themes are immutable in spirit (the registry hands back the same
    instance), but the dataclass itself is mutable so themes can be
    composed at authoring time before registration.

    The ``semantic`` field is the **named contract** widget code binds
    to — switching themes is therefore a question of rebinding the
    semantic surface, not of teaching widgets which palette key to
    look up. See :class:`SemanticTokens` for the field menu.

    The four scale fields (``spacing`` / ``radius`` / ``transitions`` /
    ``z_index``) carry sensible defaults; supply custom instances when
    a theme genuinely wants a tighter or looser rhythm.
    """

    name: str
    semantic: SemanticTokens
    palette: dict[str, "Color"] = field(default_factory=dict)
    spacing: SpacingScale = field(default_factory=SpacingScale)
    radius: RadiusScale = field(default_factory=RadiusScale)
    transitions: TransitionScale = field(default_factory=TransitionScale)
    z_index: ZIndexScale = field(default_factory=ZIndexScale)
    fonts: dict[str, Font] = field(default_factory=dict)
    nine_slices: dict[str, Any] = field(default_factory=dict)
    icons: dict[str, Any] = field(default_factory=dict)
    frames: PanelFrameSet = field(default_factory=PanelFrameSet)
    decor: PanelDecorConfig = field(default_factory=PanelDecorConfig)
    # ``background_shader`` accepts either the CPU-side
    # :class:`ShaderEffect` (dispatched through the numpy helpers in
    # :mod:`shader_effects`) or the GPU-side
    # :class:`~.wgsl_backgrounds.WGSLShaderSpec` (compiled through the
    # WGSL fragment-shader hook). The union is validated in
    # ``__post_init__``; the field is declared as ``Any`` to avoid an
    # eager import cycle on ``wgsl_backgrounds``.
    background_shader: Any = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        fn = "ThemeSpec"
        self.name = validate_non_empty_str("name", fn, self.name)
        if not isinstance(self.semantic, SemanticTokens):
            raise TypeError(
                f"{fn}: semantic must be a SemanticTokens; "
                f"got {type(self.semantic).__name__}"
            )
        for scale_name, scale_type in (
            ("spacing", SpacingScale),
            ("radius", RadiusScale),
            ("transitions", TransitionScale),
            ("z_index", ZIndexScale),
        ):
            value = getattr(self, scale_name)
            if not isinstance(value, scale_type):
                raise TypeError(
                    f"{fn}: {scale_name} must be a {scale_type.__name__}; "
                    f"got {type(value).__name__}"
                )
        for bag_name, bag in (
            ("palette", self.palette),
            ("fonts", self.fonts),
            ("nine_slices", self.nine_slices),
            ("icons", self.icons),
            ("metadata", self.metadata),
        ):
            if not isinstance(bag, dict):
                raise TypeError(
                    f"{fn}: {bag_name} must be a dict; got {type(bag).__name__}"
                )
            for key in bag:
                validate_str(f"{bag_name} key", fn, key, allow_empty=False)
        if self.background_shader is not None:
            # Local import so the theme_spec module remains free of a
            # hard dependency on wgsl_backgrounds (which soft-imports
            # wgpu). Accepts the numpy-side ShaderEffect, the GPU-side
            # WGSLShaderSpec, or a page-lining id str (validated against
            # the registry so a typo fails at theme construction).
            from .wgsl_backgrounds import WGSLShaderSpec as _WGSLSpec
            bg = self.background_shader
            if isinstance(bg, str):
                from .page_linings.library import PAGE_LININGS
                if not bg:
                    raise ValueError(
                        f"{fn}: background_shader lining id must be "
                        "a non-empty string"
                    )
                if bg not in PAGE_LININGS:
                    known = ", ".join(sorted(PAGE_LININGS.keys()))
                    raise ValueError(
                        f"{fn}: background_shader lining id {bg!r} not "
                        f"registered; known ids: {known}"
                    )
            elif not isinstance(bg, (ShaderEffect, _WGSLSpec)):
                raise TypeError(
                    f"{fn}: background_shader must be a ShaderEffect, "
                    "WGSLShaderSpec, page-lining id str, or None; "
                    f"got {type(bg).__name__}"
                )
        if not isinstance(self.frames, PanelFrameSet):
            raise TypeError(
                f"{fn}: frames must be a PanelFrameSet; "
                f"got {type(self.frames).__name__}"
            )

    # ---- YAML round-trip ---------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain-Python dict (YAML/JSON safe).

        :class:`NineSlice` and :class:`SVGIcon` instances are serialised
        through their own ``to_dict`` methods; missing methods fall back
        to ``repr`` so unsupported subclasses still round-trip *something*.
        """
        return {
            "name": self.name,
            "semantic": self.semantic.to_dict(),
            "palette": {
                k: [v.r, v.g, v.b, v.a] for k, v in self.palette.items()
            },
            "spacing": {
                "xs": self.spacing.xs, "sm": self.spacing.sm,
                "md": self.spacing.md, "lg": self.spacing.lg,
                "xl": self.spacing.xl, "xxl": self.spacing.xxl,
            },
            "radius": {
                "sm": self.radius.sm, "md": self.radius.md,
                "lg": self.radius.lg, "xl": self.radius.xl,
                "pill": self.radius.pill,
            },
            "transitions": {
                "fast": self.transitions.fast,
                "normal": self.transitions.normal,
                "slow": self.transitions.slow,
            },
            "z_index": {
                "base": self.z_index.base,
                "dropdown": self.z_index.dropdown,
                "modal": self.z_index.modal,
                "toast": self.z_index.toast,
            },
            "fonts": {
                k: {"family": v.family, "size": v.size, "weight": v.weight}
                for k, v in self.fonts.items()
            },
            "nine_slices": {
                k: (v.to_dict() if hasattr(v, "to_dict") else repr(v))
                for k, v in self.nine_slices.items()
            },
            "icons": {
                k: (v.to_dict() if hasattr(v, "to_dict") else repr(v))
                for k, v in self.icons.items()
            },
            "background_shader": _serialise_background_shader(
                self.background_shader
            ),
            "frames": _frames_to_dict(self.frames),
            "decor": _decor_to_dict(self.decor),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ThemeSpec":
        """Rebuild a :class:`ThemeSpec` from :meth:`to_dict` output.

        :class:`NineSlice` / :class:`SVGIcon` entries are reconstructed
        only if the dict carries the appropriate marker keys (matching
        each class's :meth:`to_dict`); other entries pass through
        unchanged so callers can author intermediate formats.
        """
        from .nine_slice import NineSlice
        from .svg_icon import SVGIcon

        if not isinstance(data, dict):
            raise TypeError(
                f"ThemeSpec.from_dict: data must be a dict; "
                f"got {type(data).__name__}"
            )
        name = data.get("name", "")
        palette_raw = data.get("palette") or {}
        palette: dict[str, Color] = {}
        for k, v in palette_raw.items():
            if isinstance(v, Color):
                palette[k] = v
            elif isinstance(v, (list, tuple)) and len(v) == 4:
                palette[k] = Color(int(v[0]), int(v[1]), int(v[2]), float(v[3]))
            else:
                raise TypeError(
                    f"ThemeSpec.from_dict: palette[{k!r}] must be Color "
                    f"or 4-sequence; got {type(v).__name__}"
                )
        fonts_raw = data.get("fonts") or {}
        fonts: dict[str, Font] = {}
        for k, v in fonts_raw.items():
            if isinstance(v, Font):
                fonts[k] = v
            elif isinstance(v, dict):
                fonts[k] = Font(
                    family=v.get("family", "sans-serif"),
                    size=int(v.get("size", 14)),
                    weight=v.get("weight", "regular"),
                )
            else:
                raise TypeError(
                    f"ThemeSpec.from_dict: fonts[{k!r}] must be Font "
                    f"or dict; got {type(v).__name__}"
                )
        ns_raw = data.get("nine_slices") or {}
        nine_slices: dict[str, Any] = {}
        for k, v in ns_raw.items():
            if isinstance(v, NineSlice):
                nine_slices[k] = v
            elif isinstance(v, dict) and "insets" in v:
                nine_slices[k] = NineSlice.from_dict(v)
            else:
                nine_slices[k] = v
        icons_raw = data.get("icons") or {}
        icons: dict[str, Any] = {}
        for k, v in icons_raw.items():
            if isinstance(v, SVGIcon):
                icons[k] = v
            elif isinstance(v, dict) and "svg_xml" in v:
                icons[k] = SVGIcon.from_dict(v)
            else:
                icons[k] = v
        bg = data.get("background_shader")
        bg_shader = _deserialise_background_shader(bg)

        semantic_raw = data.get("semantic")
        if semantic_raw is None:
            raise TypeError(
                "ThemeSpec.from_dict: semantic is required (missing key)"
            )
        if isinstance(semantic_raw, SemanticTokens):
            semantic = semantic_raw
        elif isinstance(semantic_raw, dict):
            semantic = SemanticTokens.from_dict(semantic_raw)
        else:
            raise TypeError(
                f"ThemeSpec.from_dict: semantic must be SemanticTokens or "
                f"dict; got {type(semantic_raw).__name__}"
            )

        def _scale(key: str, scale_cls: type, default: Any) -> Any:
            raw = data.get(key)
            if raw is None:
                return default
            if isinstance(raw, scale_cls):
                return raw
            if isinstance(raw, dict):
                return scale_cls(**raw)
            raise TypeError(
                f"ThemeSpec.from_dict: {key} must be {scale_cls.__name__} or "
                f"dict; got {type(raw).__name__}"
            )

        spacing = _scale("spacing", SpacingScale, SpacingScale())
        radius = _scale("radius", RadiusScale, RadiusScale())
        transitions = _scale("transitions", TransitionScale, TransitionScale())
        z_index = _scale("z_index", ZIndexScale, ZIndexScale())

        frames = _frames_from_dict(data.get("frames"))
        decor = _decor_from_dict(data.get("decor"))

        return cls(
            name=name,
            semantic=semantic,
            palette=palette,
            spacing=spacing,
            radius=radius,
            transitions=transitions,
            z_index=z_index,
            fonts=fonts,
            nine_slices=nine_slices,
            icons=icons,
            frames=frames,
            decor=decor,
            background_shader=bg_shader,
            metadata=dict(data.get("metadata") or {}),
        )

    def to_yaml(self) -> str:
        """Serialise to a YAML string (requires ``PyYAML``)."""
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImportError(
                "ThemeSpec.to_yaml requires PyYAML: pip install pyyaml"
            ) from exc
        return yaml.safe_dump(self.to_dict(), sort_keys=False)

    @classmethod
    def from_yaml(cls, text: str) -> "ThemeSpec":
        """Parse YAML produced by :meth:`to_yaml`."""
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - defensive
            raise ImportError(
                "ThemeSpec.from_yaml requires PyYAML: pip install pyyaml"
            ) from exc
        validate_str("text", "ThemeSpec.from_yaml", text, allow_empty=False)
        data = yaml.safe_load(text)
        return cls.from_dict(data)


# Re-export the float-validator name for adjacent modules that build on
# this file (no API exposure — keeps the module self-checked).
_ = validate_finite_float


__all__ = [
    "Color",
    "Font",
    "FrameStyle",
    "Gradient",
    "Palette",
    "PanelDecorConfig",
    "PanelFrameSet",
    "RadiusScale",
    "SemanticTokens",
    "ShaderEffect",
    "SpacingScale",
    "ThemeSpec",
    "TransitionScale",
    "ZIndexScale",
]
