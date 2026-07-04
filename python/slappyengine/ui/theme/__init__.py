"""Theme primitives — nine-slice, SVG icons, procedural shader effects.

This subpackage owns the *foundation* that any concrete SlapPyEngine UI
theme builds on. It deliberately ships **no theme content** — only the
primitives. The accompanying theme content (e.g. the upcoming
"TeenGirl Notebook" pack) lives in a sibling module that imports from
here.

Design priorities (per the v0.3 PRIMITIVE-infrastructure brief):

* **Nine-slice for borders** — small patterns scale to any size.
* **SVG for icons** — vector authoring → zero asset-size cost at any DPI.
* **Procedural / shader for backgrounds + effects** — no PNG bake.

Total on-disk theme asset budget: **< 100 KB**. None of the primitives
here hold reference textures themselves; all of them generate
``np.uint8`` RGBA arrays on demand.

Public surface
--------------

.. code-block:: python

    from slappyengine.ui.theme import (
        Color, Font, NineSlice, Palette, ShaderEffect, SVGIcon, ThemeSpec,
        apply_theme, get_active_theme, register_theme,
    )

The registry holds every :class:`ThemeSpec` ever registered and
remembers which one is *active*. :func:`apply_theme` swaps the active
theme by name; :func:`get_active_theme` returns the current one.
"""
from __future__ import annotations

from .nine_slice import NineSlice
from .shader_effects import (
    dot_grid,
    frosted_panel,
    glass_blur,
    highlighter_stroke,
    noise_glitter,
    paper_shadow,
    parchment,
    ruled_paper,
    watercolor_wash,
)
from .svg_icon import SVGIcon
from .dpg_bridge import apply_theme_to_dpg
from .declarative import (
    DeclarativeTheme,
    DeclarativeThemeError,
    NAMED_COLORS,
    load_declarative,
)
from .theme_spec import (
    Color,
    Font,
    FrameStyle,
    Gradient,
    Palette,
    PanelDecorConfig,
    PanelFrameSet,
    RadiusScale,
    SemanticTokens,
    ShaderEffect,
    SpacingScale,
    ThemeSpec,
    TransitionScale,
    ZIndexScale,
)
from .user_themes import (
    UserThemeError,
    UserThemeStore,
    bake_default_themes,
)
from .wgsl_backgrounds import (
    BUILTIN_BACKGROUNDS,
    WGSLBackgroundTicker,
    WGSLShaderSpec,
    compile_wgsl_background,
    has_wgpu,
    resolve_background,
)
from .edge_strokes import (
    EDGE_STROKES,
    EdgeStrokeStyle,
    bake_stroke_texture,
    render_stroke_border,
)
from .edge_strokes import get_stroke as get_edge_stroke
from .edge_strokes import list_strokes as list_edge_strokes

from slappyengine._validation import validate_non_empty_str


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


_REGISTRY: dict[str, ThemeSpec] = {}
_ACTIVE: ThemeSpec | None = None


def register_theme(theme: ThemeSpec) -> None:
    """Register *theme* under its name.

    Re-registering an existing name overwrites the previous entry.

    Raises
    ------
    TypeError
        If *theme* is not a :class:`ThemeSpec`.
    """
    if not isinstance(theme, ThemeSpec):
        raise TypeError(
            "register_theme: theme must be a ThemeSpec; "
            f"got {type(theme).__name__}"
        )
    _REGISTRY[theme.name] = theme


def get_active_theme() -> ThemeSpec:
    """Return the currently active :class:`ThemeSpec`.

    Raises
    ------
    LookupError
        If no theme has been activated via :func:`apply_theme` yet.
    """
    if _ACTIVE is None:
        raise LookupError(
            "get_active_theme: no theme active — call apply_theme(name) first"
        )
    return _ACTIVE


def apply_theme(theme_name: str) -> ThemeSpec:
    """Swap the active theme to the one registered under *theme_name*.

    Returns the resolved :class:`ThemeSpec` so callers can chain a
    follow-up render call inline.

    Raises
    ------
    LookupError
        If no theme with that name has been registered.
    """
    global _ACTIVE
    name = validate_non_empty_str("theme_name", "apply_theme", theme_name)
    if name not in _REGISTRY:
        raise LookupError(
            f"apply_theme: no theme named {name!r} registered "
            f"(known: {sorted(_REGISTRY)})"
        )
    _ACTIVE = _REGISTRY[name]
    # DPG bridge: rebuild the DPG theme handle whenever a theme is
    # applied. Soft-fails when DPG isn't installed (headless tests).
    try:
        apply_theme_to_dpg(_ACTIVE)
    except Exception:  # pragma: no cover - defensive: bridge soft-fails
        pass
    # WGSL background hook: eagerly bake the panel background so the
    # editor picks up the new texture on the very next frame. The bake
    # is cached on the ThemeSpec instance so subsequent lookups skip
    # the compile step. Soft-fails when the shader/wgpu path is missing.
    try:
        if _ACTIVE.background_shader is not None:
            baked = resolve_background(_ACTIVE.background_shader)
            # Store on the ThemeSpec as a private attribute — kept
            # underscore-prefixed so YAML round-trips ignore it.
            _ACTIVE.__dict__["_baked_background"] = baked
    except Exception:  # pragma: no cover - defensive: bake soft-fails
        pass
    return _ACTIVE


def get_baked_background():
    """Return the last-baked WGSL/ShaderEffect background as an ndarray.

    Returns ``None`` when no theme is active, when the active theme has
    no ``background_shader``, or when the last bake failed. The editor
    calls this on each panel-draw to source the panel-background
    texture without re-running the shader.
    """
    if _ACTIVE is None:
        return None
    return _ACTIVE.__dict__.get("_baked_background")


def list_registered_themes() -> list[str]:
    """Return a sorted list of every registered theme name."""
    return sorted(_REGISTRY)


def _reset_registry_for_tests() -> None:
    """Internal: clear the registry. Test-only escape hatch."""
    global _ACTIVE
    _REGISTRY.clear()
    _ACTIVE = None


__all__ = [
    "BUILTIN_BACKGROUNDS",
    "Color",
    "DeclarativeTheme",
    "DeclarativeThemeError",
    "EDGE_STROKES",
    "EdgeStrokeStyle",
    "Font",
    "FrameStyle",
    "Gradient",
    "NAMED_COLORS",
    "NineSlice",
    "Palette",
    "PanelFrameSet",
    "RadiusScale",
    "SemanticTokens",
    "ShaderEffect",
    "SpacingScale",
    "SVGIcon",
    "ThemeSpec",
    "TransitionScale",
    "WGSLBackgroundTicker",
    "WGSLShaderSpec",
    "ZIndexScale",
    "apply_theme",
    "apply_theme_to_dpg",
    "bake_stroke_texture",
    "compile_wgsl_background",
    "dot_grid",
    "frosted_panel",
    "get_active_theme",
    "get_baked_background",
    "get_edge_stroke",
    "glass_blur",
    "has_wgpu",
    "highlighter_stroke",
    "list_edge_strokes",
    "list_registered_themes",
    "load_declarative",
    "noise_glitter",
    "paper_shadow",
    "parchment",
    "register_theme",
    "render_stroke_border",
    "resolve_background",
    "ruled_paper",
    "watercolor_wash",
]
