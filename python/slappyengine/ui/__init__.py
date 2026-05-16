"""UI subpackage — lazy-loaded to avoid eager numpy/wgpu imports."""
from __future__ import annotations

__all__ = ["SceneUIEntity", "HtmlOverlay", "draw_stat_bar"]

_LAZY_MAP: dict[str, str] = {
    "SceneUIEntity": ".scene_ui",
    "HtmlOverlay":   ".html_overlay",
    "draw_stat_bar": ".hud_widgets",
}


def __getattr__(name: str):
    if name in _LAZY_MAP:
        import importlib
        try:
            mod = importlib.import_module(_LAZY_MAP[name], package=__name__)
        except ImportError:
            if name == "HtmlOverlay":
                raise AttributeError(
                    f"HtmlOverlay requires the 'editor' extra: pip install slappyengine[editor]"
                ) from None
            raise
        val = getattr(mod, name)
        globals()[name] = val
        return val

    # editor subpackage — only available with [editor] extra
    if name == "editor":
        import importlib
        mod = importlib.import_module(".editor", package=__name__)
        globals()["editor"] = mod
        return mod

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
