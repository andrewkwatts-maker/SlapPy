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
from .theme_spec import (
    Color,
    Font,
    Gradient,
    Palette,
    RadiusScale,
    SemanticTokens,
    ShaderEffect,
    SpacingScale,
    ThemeSpec,
    TransitionScale,
    ZIndexScale,
)

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
    return _ACTIVE


def list_registered_themes() -> list[str]:
    """Return a sorted list of every registered theme name."""
    return sorted(_REGISTRY)


def _reset_registry_for_tests() -> None:
    """Internal: clear the registry. Test-only escape hatch."""
    global _ACTIVE
    _REGISTRY.clear()
    _ACTIVE = None


__all__ = [
    "Color",
    "Font",
    "Gradient",
    "NineSlice",
    "Palette",
    "RadiusScale",
    "SemanticTokens",
    "ShaderEffect",
    "SpacingScale",
    "SVGIcon",
    "ThemeSpec",
    "TransitionScale",
    "ZIndexScale",
    "apply_theme",
    "dot_grid",
    "frosted_panel",
    "get_active_theme",
    "glass_blur",
    "highlighter_stroke",
    "list_registered_themes",
    "noise_glitter",
    "paper_shadow",
    "parchment",
    "register_theme",
    "ruled_paper",
    "watercolor_wash",
]
