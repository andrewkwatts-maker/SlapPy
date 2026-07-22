"""Page-lining WGSL shader library.

Public surface — a library of tileable paper-stock patterns baked as
RGBA textures for :class:`~pharos_editor.ui.theme.theme_spec.ThemeSpec`
panel backgrounds.

Typical usage::

    from pharos_editor.ui.theme.page_linings import (
        PAGE_LININGS, get_lining, list_linings, render_lining,
    )

    # list registered styles
    for style_id in list_linings():
        style = get_lining(style_id)
        print(style_id, style.tile_size, style.description)

    # bake a texture
    rgba = render_lining("ruled_paper", (256, 128))
    # rgba is a (128, 256, 4) uint8 ndarray

See ``docs/api/page_lining_shaders.md`` for the full catalogue.
"""
from __future__ import annotations

from .library import (
    AAAShaderQualityPreset,
    DEFAULT_AAA_PRESET,
    LiningStyle,
    PAGE_LININGS,
    get_lining,
    iter_linings,
    list_linings,
)
from .renderer import (
    bake_lining_texture,
    has_wgpu,
    render_lining,
)


__all__ = [
    "AAAShaderQualityPreset",
    "DEFAULT_AAA_PRESET",
    "LiningStyle",
    "PAGE_LININGS",
    "bake_lining_texture",
    "get_lining",
    "has_wgpu",
    "iter_linings",
    "list_linings",
    "render_lining",
]
