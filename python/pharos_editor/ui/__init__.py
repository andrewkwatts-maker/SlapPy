"""UI subpackage — lazy-loaded to avoid eager numpy/wgpu imports."""
from __future__ import annotations

__all__ = ["HtmlOverlay", "SceneUIEntity", "draw_stat_bar"]

_LAZY_MAP: dict[str, str] = {
    "HtmlOverlay":   ".html_overlay",
    "SceneUIEntity": ".scene_ui",
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
                    f"HtmlOverlay requires the 'editor' extra: pip install Pharos Engine[editor]"
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

    # theme subpackage — PRIMITIVE infrastructure (always available)
    if name == "theme":
        import importlib
        mod = importlib.import_module(".theme", package=__name__)
        globals()["theme"] = mod
        return mod

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
