"""Legacy Nova3D reference. The shipping editor uses notebook_* siblings — see docs/ui_pattern_audit_2026_06_03.md."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Glassmorphism dark theme for SlapPyEngine editor
# All colour constants are (R, G, B) or (R, G, B, A) tuples in 0-255 range
# as used by DPG.
# ---------------------------------------------------------------------------

# -- Glassmorphism Palette ---------------------------------------------------
_GLASS_BG       = (18,  18,  26)        # dark navy base
_GLASS_PANEL    = (28,  28,  40)        # panel surface (semi-transparent)
_GLASS_BORDER   = (80,  80, 120, 60)   # subtle glowing border, low alpha
_GLASS_ACCENT   = (120, 160, 255)       # blue-violet accent
_GLASS_TEXT     = (220, 220, 240)       # slightly blue-tinted white
_GLASS_DIM      = (140, 140, 180)       # secondary text
_GLASS_HOVER    = (50,  50,  75)        # hover state
_GLASS_ACTIVE   = (65,  65, 100)        # active/pressed state
_VIEWPORT_BG    = (15,  15,  20)        # fully opaque viewport background

# -- Legacy aliases (used by accent/default button helpers below) ------------
_ACCENT         = _GLASS_ACCENT
_SLIDER_ACT     = (120, 170, 255)
_BG             = _GLASS_BG
_INPUT          = (41,  41,  48)
_INPUT_HOV      = (51,  51,  61)
_TEXT           = _GLASS_TEXT
_TEXT_DIS       = (115, 115, 122)
_BUTTON         = _GLASS_HOVER
_BUTTON_HOV     = _GLASS_HOVER
_BUTTON_ACT     = _GLASS_ACTIVE
_HEADER         = (56,  56,  77)
_HEADER_HOV     = (64,  64,  89)
_HEADER_ACT     = (77,  77, 102)
_TAB            = (38,  38,  46)
_TAB_HOV        = (77,  77, 102)
_TAB_ACT        = (64,  77, 140)
_SCROLL_BG      = _GLASS_BG
_SCROLL_GRAB    = (64,  64,  77)

# Keep these for any external code that references them
_SUCCESS        = (77,  191, 102)
_WARNING        = (242, 191,  64)
_ERROR          = (230,  89,  89)


def _rgba(rgb: tuple[int, int, int], a: int = 255) -> list[int]:
    """Return a 4-element RGBA list suitable for DPG theme colour calls."""
    return [rgb[0], rgb[1], rgb[2], a]


def apply_editor_theme() -> None:
    """Apply the glassmorphism dark theme globally via DPG.

    Must be called after ``dpg.create_context()`` and before
    ``dpg.create_viewport()``.
    """
    import dearpygui.dearpygui as dpg

    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            # ---- Window / background ----------------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg,           _rgba(_GLASS_BG, 200))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg,            _rgba(_GLASS_PANEL, 180))
            dpg.add_theme_color(dpg.mvThemeCol_PopupBg,            _rgba(_GLASS_PANEL, 220))

            # ---- Frame (inputs, combos …) -----------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg,            _rgba(_INPUT))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered,     _rgba(_INPUT_HOV))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive,      _rgba(_INPUT_HOV))

            # ---- Title bars --------------------------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_TitleBg,            _rgba(_GLASS_BG, 200))
            dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive,      _rgba(_GLASS_PANEL, 220))

            # ---- Buttons -----------------------------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_Button,             _rgba(_GLASS_HOVER))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,      _rgba(_GLASS_HOVER))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,       _rgba(_GLASS_ACTIVE))

            # ---- Scrollbar ---------------------------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg,        _rgba(_SCROLL_BG))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab,      _rgba(_SCROLL_GRAB))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabHovered, _rgba(_GLASS_HOVER))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabActive,  _rgba(_GLASS_ACTIVE))

            # ---- Tree / collapsing headers -----------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_Header,             _rgba(_HEADER))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered,      _rgba(_HEADER_HOV))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderActive,       _rgba(_HEADER_ACT))

            # ---- Tabs --------------------------------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_Tab,                _rgba(_TAB))
            dpg.add_theme_color(dpg.mvThemeCol_TabHovered,         _rgba(_TAB_HOV))
            dpg.add_theme_color(dpg.mvThemeCol_TabActive,          _rgba(_TAB_ACT))

            # ---- Borders / separators ----------------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_Separator,          list(_GLASS_BORDER))
            dpg.add_theme_color(dpg.mvThemeCol_Border,             [_GLASS_BORDER[0], _GLASS_BORDER[1], _GLASS_BORDER[2], 80])

            # ---- Text --------------------------------------------------------
            dpg.add_theme_color(dpg.mvThemeCol_Text,               _rgba(_GLASS_TEXT))
            dpg.add_theme_color(dpg.mvThemeCol_TextDisabled,       _rgba(_TEXT_DIS))

            # ---- Accent controls (checkmark, sliders) ------------------------
            dpg.add_theme_color(dpg.mvThemeCol_CheckMark,          _rgba(_GLASS_ACCENT))
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrab,         _rgba(_GLASS_ACCENT))
            dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive,   _rgba(_SLIDER_ACT))

            # ---- Style vars — glassmorphism rounded corners -----------------
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding,     14)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding,      12)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,      8)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarRounding,  8)
            dpg.add_theme_style(dpg.mvStyleVar_GrabRounding,       6)
            dpg.add_theme_style(dpg.mvStyleVar_TabRounding,        10)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding,       6, 4)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing,        8, 5)
            dpg.add_theme_style(dpg.mvStyleVar_IndentSpacing,      16)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding,      10, 10)

    dpg.bind_theme(global_theme)


# -- Convenience: reusable per-item accent theme (active tool button, etc.) --

_accent_button_theme: int | None = None


def get_accent_button_theme() -> int:
    """Return a cached per-item theme that renders a button with accent bg.

    Safe to call multiple times; theme is created once and reused.
    """
    global _accent_button_theme
    if _accent_button_theme is not None:
        return _accent_button_theme

    import dearpygui.dearpygui as dpg

    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button,        _rgba(_ACCENT))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, _rgba(_SLIDER_ACT))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,  _rgba(_ACCENT))
            dpg.add_theme_color(dpg.mvThemeCol_Text,          _rgba(_BG))

    _accent_button_theme = t
    return t


def get_default_button_theme() -> int:
    """Return a per-item theme that restores the standard button appearance."""
    import dearpygui.dearpygui as dpg

    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvButton):
            dpg.add_theme_color(dpg.mvThemeCol_Button,        _rgba(_BUTTON))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, _rgba(_BUTTON_HOV))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,  _rgba(_BUTTON_ACT))
            dpg.add_theme_color(dpg.mvThemeCol_Text,          _rgba(_TEXT))

    return t


# -- Viewport opaque theme (no glassmorphism for game render area) -----------

_viewport_opaque_theme: int | None = None


def get_viewport_opaque_theme() -> int:
    """Return a cached per-item theme with a fully opaque viewport background.

    Binds a solid ``_VIEWPORT_BG`` ChildBg so the game render area is never
    transparent regardless of the global glassmorphism settings.

    Safe to call multiple times; theme is created once and reused.
    """
    global _viewport_opaque_theme
    if _viewport_opaque_theme is not None:
        return _viewport_opaque_theme

    import dearpygui.dearpygui as dpg

    with dpg.theme() as t:
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, _rgba(_VIEWPORT_BG, 255))

    _viewport_opaque_theme = t
    return t


# -- Windows DWM Acrylic blur-behind ----------------------------------------

def apply_dwm_glass(hwnd_title: str) -> None:
    """Apply Windows DWM Acrylic blur-behind. No-op on non-Windows.

    Tries the Windows 11 Mica/Acrylic (DWMWA_SYSTEMBACKDROP_TYPE) path first,
    then falls back to the Windows 10 Accent Policy approach.  Any failure is
    silently swallowed so the editor degrades gracefully on unsupported
    platforms.

    Parameters
    ----------
    hwnd_title:
        The window title string used to locate the HWND via ``FindWindowW``.
    """
    import sys
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import ctypes.wintypes

        hwnd = ctypes.windll.user32.FindWindowW(None, hwnd_title)
        if not hwnd:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return

        # Try Windows 11 Mica/Acrylic (DWMWA_SYSTEMBACKDROP_TYPE = 38)
        try:
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            DWMWA_SYSTEMBACKDROP_TYPE = 38
            DWMSBT_TRANSIENTWINDOW = 3  # Acrylic

            # Enable dark mode
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                ctypes.byref(ctypes.c_int(1)), ctypes.sizeof(ctypes.c_int)
            )
            # Apply Acrylic backdrop
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(ctypes.c_int(DWMSBT_TRANSIENTWINDOW)),
                ctypes.sizeof(ctypes.c_int)
            )
            return  # success on Win11
        except Exception:
            pass

        # Fallback: Windows 10 Accent Policy blur-behind
        class ACCENTPOLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState",  ctypes.c_int),
                ("AccentFlags",  ctypes.c_int),
                ("GradientColor", ctypes.c_int),
                ("AnimationId",  ctypes.c_int),
            ]

        class WINCOMPATTR(ctypes.Structure):
            _fields_ = [
                ("Attribute",   ctypes.c_int),
                ("Data",        ctypes.c_void_p),
                ("SizeOfData",  ctypes.c_int),
            ]

        accent = ACCENTPOLICY()
        accent.AccentState = 4          # ACCENT_ENABLE_ACRYLICBLURBEHIND (Win10 1809+)
        accent.AccentFlags = 2
        accent.GradientColor = 0xCC1A1A2E  # dark navy, 80% alpha

        data = WINCOMPATTR()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.Data = ctypes.cast(ctypes.byref(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)

        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        pass  # graceful degradation on unsupported platforms
