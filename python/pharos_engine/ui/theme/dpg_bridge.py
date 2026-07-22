"""Dear PyGui bridge for :class:`ThemeSpec`.

Translates the declarative :class:`~pharos_engine.ui.theme.theme_spec.ThemeSpec`
into a live Dear PyGui ``theme`` resource. The translation maps every
:class:`~pharos_engine.ui.theme.theme_spec.FrameStyle` token onto the
matching ``mvStyleVar_*`` and every relevant
:class:`~pharos_engine.ui.theme.theme_spec.SemanticTokens` colour onto the
matching ``mvThemeCol_*`` constant.

Soft-import policy
------------------
``dearpygui`` is **not** a hard runtime dependency of the engine; the
editor surface is optional and the headless test runner cannot import it.
This module catches the import failure and substitutes a *headless stub*
that records every call. Callers (and tests) can introspect what would
have been emitted via :func:`apply_theme_to_dpg` without DPG installed.

Public surface
--------------

* :func:`apply_theme_to_dpg` — build (and apply) a DPG theme resource
  from a :class:`ThemeSpec`. Returns the DPG theme tag (an ``int``) so
  callers can bind it to a window manually if needed.
* :func:`get_last_dpg_payload` — last-resort introspection: returns the
  payload dict that was handed to the DPG layer on the most recent
  successful :func:`apply_theme_to_dpg` call. Test-only.
"""
from __future__ import annotations

from typing import Any

from .theme_spec import Color, FrameStyle, SemanticTokens, ThemeSpec


# ---------------------------------------------------------------------------
# Soft DPG import + stub
# ---------------------------------------------------------------------------


class _DPGStub:
    """Headless stand-in for ``dearpygui.dearpygui``.

    The real module exposes ``add_theme`` / ``add_theme_color`` /
    ``add_theme_style`` / ``bind_theme`` plus a sea of ``mvThemeCol_*`` /
    ``mvStyleVar_*`` constants. We mirror just enough of that surface
    for :func:`apply_theme_to_dpg` to run end-to-end and return a deterministic
    integer "tag" so callers (and tests) can treat the result uniformly.
    """

    # Theme-colour constants we use. Values are arbitrary unique ints —
    # the real DPG values differ; we never round-trip these to a live
    # DPG context, so any unique sentinel works.
    mvThemeCol_Text = 1
    mvThemeCol_WindowBg = 2
    mvThemeCol_ChildBg = 3
    mvThemeCol_Border = 4
    mvThemeCol_Button = 5
    mvThemeCol_ButtonHovered = 6
    mvThemeCol_ButtonActive = 7
    mvThemeCol_FrameBg = 8
    mvThemeCol_TitleBg = 9
    mvThemeCol_TitleBgActive = 10

    mvStyleVar_WindowBorderSize = 101
    mvStyleVar_WindowRounding = 102
    mvStyleVar_WindowPadding = 103
    mvStyleVar_ChildRounding = 104
    mvStyleVar_ChildBorderSize = 105
    mvStyleVar_GrabMinSize = 106
    mvStyleVar_GrabRounding = 107
    mvStyleVar_FrameRounding = 108
    mvStyleVar_FrameBorderSize = 109

    mvAll = 0

    def __init__(self) -> None:
        # Simple monotonically-rising tag generator.
        self._next_tag = 1_000_000
        # Last-built payload for introspection from tests.
        self.last_payload: dict[str, Any] | None = None

    # ---- theme resource lifecycle -----------------------------------------

    def add_theme(self) -> int:
        tag = self._next_tag
        self._next_tag += 1
        return tag

    def add_theme_component(self, item_type: int, parent: int) -> int:
        tag = self._next_tag
        self._next_tag += 1
        return tag

    def add_theme_color(
        self, target: int, value: tuple[int, int, int, int], parent: int
    ) -> int:
        tag = self._next_tag
        self._next_tag += 1
        return tag

    def add_theme_style(
        self,
        target: int,
        x: float,
        y: float = -1.0,
        *,
        parent: int,
    ) -> int:
        tag = self._next_tag
        self._next_tag += 1
        return tag

    def bind_theme(self, theme_tag: int) -> None:
        return None


try:  # pragma: no cover - exercised only when dearpygui is installed
    from dearpygui import dearpygui as _real_dpg  # type: ignore[import-not-found]

    _REAL_DPG: Any | None = _real_dpg
    _HAS_DPG = True
except Exception:  # pragma: no cover - default headless path
    _REAL_DPG = None
    _HAS_DPG = False

_STUB_DPG = _DPGStub()

# ``_DPG_CONTEXT_READY`` is flipped to ``True`` once a caller has
# explicitly notified the bridge that a Dear PyGui context is alive.
# We can't safely probe DPG ourselves (every "is a context up" probe
# segfaults on Windows before ``create_context`` runs), so we rely on
# the editor shell to flip the flag after ``dpg.create_context()`` and
# clear it after ``dpg.destroy_context()``. Until that happens the
# bridge always falls through to the stub.
_DPG_CONTEXT_READY: bool = False


def mark_dpg_context_ready(ready: bool = True) -> None:
    """Tell the bridge that ``dpg.create_context`` has run (or unrun).

    Call ``mark_dpg_context_ready(True)`` immediately after
    ``dpg.create_context()`` and ``mark_dpg_context_ready(False)``
    after ``dpg.destroy_context()``. Until the first ``True`` flip,
    :func:`apply_theme_to_dpg` quietly routes to the headless stub so
    boot-time theme work never crashes the process.
    """
    global _DPG_CONTEXT_READY
    _DPG_CONTEXT_READY = bool(ready)


def _active_dpg() -> Any:
    """Return the live ``dearpygui`` module if context is up, else the stub."""
    if _HAS_DPG and _REAL_DPG is not None and _DPG_CONTEXT_READY:
        return _REAL_DPG
    return _STUB_DPG


# Module-level alias kept for backward compatibility — every read goes
# through the proxy below so the stub-vs-real choice is resolved on
# each call rather than baked at import time.
class _DPGProxy:
    """Attribute-forwarding proxy so ``_DPG.add_theme()`` routes correctly."""

    def __getattr__(self, name: str) -> Any:
        return getattr(_active_dpg(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(_active_dpg(), name, value)


_DPG: Any = _DPGProxy()


# ---------------------------------------------------------------------------
# Last-payload tracker
# ---------------------------------------------------------------------------


_LAST_PAYLOAD: dict[str, Any] | None = None


def get_last_dpg_payload() -> dict[str, Any] | None:
    """Return the most recent payload handed to the DPG layer.

    Useful for tests that need to assert that a theme switch produced
    the expected colour / style-var mapping without spinning up DPG.
    Returns ``None`` when no theme has been applied yet (or the bridge
    has been reset).
    """
    return _LAST_PAYLOAD


def _reset_last_dpg_payload_for_tests() -> None:
    """Internal: clear the last-payload tracker. Test-only."""
    global _LAST_PAYLOAD
    _LAST_PAYLOAD = None


# ---------------------------------------------------------------------------
# Mapping helpers
# ---------------------------------------------------------------------------


def _ink_shadow_color(semantic: SemanticTokens) -> Color:
    """Default shadow colour: ``text_primary`` at 30 % alpha."""
    ink = semantic.text_primary
    return Color(ink.r, ink.g, ink.b, 0.3)


def _build_color_map(semantic: SemanticTokens) -> dict[int, tuple[int, int, int, int]]:
    """Map :class:`SemanticTokens` to DPG ``mvThemeCol_*`` values."""
    return {
        _DPG.mvThemeCol_WindowBg: semantic.background.as_rgba_tuple(),
        _DPG.mvThemeCol_ChildBg: semantic.surface.as_rgba_tuple(),
        _DPG.mvThemeCol_Border: semantic.border.as_rgba_tuple(),
        _DPG.mvThemeCol_Text: semantic.text_primary.as_rgba_tuple(),
        _DPG.mvThemeCol_Button: semantic.primary.as_rgba_tuple(),
        _DPG.mvThemeCol_ButtonHovered: semantic.surface_hover.as_rgba_tuple(),
        _DPG.mvThemeCol_ButtonActive: semantic.accent.as_rgba_tuple(),
        _DPG.mvThemeCol_FrameBg: semantic.surface.as_rgba_tuple(),
        _DPG.mvThemeCol_TitleBg: semantic.surface.as_rgba_tuple(),
        _DPG.mvThemeCol_TitleBgActive: semantic.primary.as_rgba_tuple(),
    }


def _build_style_pairs(frame: FrameStyle) -> list[tuple[int, float, float]]:
    """Map a :class:`FrameStyle` onto DPG ``mvStyleVar_*`` values."""
    return [
        (_DPG.mvStyleVar_WindowBorderSize, frame.border_size, -1.0),
        (_DPG.mvStyleVar_WindowRounding, frame.rounding, -1.0),
        (_DPG.mvStyleVar_WindowPadding,
         float(frame.padding_x), float(frame.padding_y)),
        (_DPG.mvStyleVar_ChildRounding, frame.child_rounding, -1.0),
        (_DPG.mvStyleVar_ChildBorderSize, frame.child_border_size, -1.0),
        (_DPG.mvStyleVar_GrabMinSize, frame.grip_size, -1.0),
        (_DPG.mvStyleVar_GrabRounding, frame.grip_rounding, -1.0),
        (_DPG.mvStyleVar_FrameRounding, frame.rounding, -1.0),
        (_DPG.mvStyleVar_FrameBorderSize, frame.border_size, -1.0),
    ]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def apply_theme_to_dpg(theme: ThemeSpec, *, bind: bool = True) -> int:
    """Build and (optionally) bind a Dear PyGui theme from *theme*.

    The default :class:`FrameStyle` from ``theme.frames.default`` drives
    the global window border / rounding / padding / grip tokens; the
    per-kind entries (``toolbar``, ``sidebar``, …) are recorded into the
    last-payload dict for callers that want to bind them onto specific
    windows.

    Parameters
    ----------
    theme:
        The :class:`ThemeSpec` to apply.
    bind:
        Whether to call ``bind_theme`` after the resource is built.
        Defaults to ``True`` so the editor picks up the change
        immediately; set to ``False`` in tests that just want the build
        side-effect.

    Returns
    -------
    int
        The DPG theme tag. With the headless stub the tag is just a
        monotonically-rising integer; with the real DPG it is the tag
        returned by ``add_theme``.

    Raises
    ------
    TypeError
        If *theme* is not a :class:`ThemeSpec`.
    """
    global _LAST_PAYLOAD
    if not isinstance(theme, ThemeSpec):
        raise TypeError(
            "apply_theme_to_dpg: theme must be a ThemeSpec; "
            f"got {type(theme).__name__}"
        )

    semantic = theme.semantic
    frame = theme.frames.default

    theme_tag = _DPG.add_theme()
    component_tag = _DPG.add_theme_component(_DPG.mvAll, parent=theme_tag)

    colors = _build_color_map(semantic)
    color_tags: dict[int, int] = {}
    for target, value in colors.items():
        color_tags[target] = _DPG.add_theme_color(
            target, value, parent=component_tag
        )

    style_pairs = _build_style_pairs(frame)
    style_tags: list[int] = []
    for target, x, y in style_pairs:
        style_tags.append(
            _DPG.add_theme_style(target, x, y, parent=component_tag)
        )

    # Per-panel-kind frame payloads — recorded so callers / tests can
    # introspect how each panel kind would be styled if it had its own
    # DPG theme resource bound to it.
    panel_payloads: dict[str, dict[str, Any]] = {}
    panel_frames = theme.frames
    for kind in ("toolbar", "sidebar", "viewport", "modal",
                 "code_pane", "status_bar"):
        kind_frame = panel_frames.for_panel(kind)
        panel_payloads[kind] = {
            "border_size": kind_frame.border_size,
            "rounding": kind_frame.rounding,
            "padding_x": kind_frame.padding_x,
            "padding_y": kind_frame.padding_y,
            "shadow_size": kind_frame.shadow_size,
            "child_rounding": kind_frame.child_rounding,
            "child_border_size": kind_frame.child_border_size,
            "grip_size": kind_frame.grip_size,
            "grip_rounding": kind_frame.grip_rounding,
            "title_bar_height": kind_frame.title_bar_height,
            "border_color": (
                kind_frame.border_color.as_rgba_tuple()
                if kind_frame.border_color is not None
                else semantic.border.as_rgba_tuple()
            ),
            "shadow_color": (
                kind_frame.shadow_color.as_rgba_tuple()
                if kind_frame.shadow_color is not None
                else _ink_shadow_color(semantic).as_rgba_tuple()
            ),
        }

    payload = {
        "theme_name": theme.name,
        "theme_tag": theme_tag,
        "component_tag": component_tag,
        "color_tags": color_tags,
        "style_tags": style_tags,
        "colors": colors,
        "style_pairs": style_pairs,
        "panel_payloads": panel_payloads,
        "headless": not _HAS_DPG,
    }
    _LAST_PAYLOAD = payload
    if hasattr(_DPG, "last_payload"):
        _DPG.last_payload = payload  # stub-only convenience

    if bind:
        try:
            _DPG.bind_theme(theme_tag)
        except Exception:  # pragma: no cover - defensive
            pass

    return int(theme_tag)


def build_panel_theme(theme: ThemeSpec, kind: str) -> int | None:
    """Build a per-kind DPG theme handle and return its tag.

    Resolves ``theme.frames.for_panel(kind)`` and emits a *small*
    theme resource that overrides the window-border / window-rounding
    / window-padding tokens for the matching window. Callers bind the
    returned tag onto a single window via ``dpg.bind_item_theme``.

    Returns ``None`` when DPG isn't ready (no context, missing module)
    so callers can treat the result as "no per-window override".

    Parameters
    ----------
    theme:
        The :class:`ThemeSpec` to derive the per-kind frame from.
    kind:
        Panel kind passed through to ``theme.frames.for_panel(kind)``.
        Unknown kinds resolve to ``theme.frames.default``.
    """
    if not isinstance(theme, ThemeSpec):
        raise TypeError(
            "build_panel_theme: theme must be a ThemeSpec; "
            f"got {type(theme).__name__}"
        )
    validate_non_empty_str("kind", "build_panel_theme", kind)
    frame: FrameStyle = theme.frames.for_panel(kind)
    semantic: SemanticTokens = theme.semantic

    dpg = _active_dpg()
    try:
        theme_tag = dpg.add_theme()
        component_tag = dpg.add_theme_component(dpg.mvAll, parent=theme_tag)
        border = (
            frame.border_color.as_rgba_tuple()
            if frame.border_color is not None
            else semantic.border.as_rgba_tuple()
        )
        try:
            dpg.add_theme_color(
                dpg.mvThemeCol_Border, border, parent=component_tag,
            )
            dpg.add_theme_color(
                dpg.mvThemeCol_WindowBg,
                semantic.surface.as_rgba_tuple(),
                parent=component_tag,
            )
            dpg.add_theme_color(
                dpg.mvThemeCol_TitleBg,
                semantic.surface.as_rgba_tuple(),
                parent=component_tag,
            )
            dpg.add_theme_color(
                dpg.mvThemeCol_TitleBgActive,
                semantic.primary.as_rgba_tuple(),
                parent=component_tag,
            )
        except Exception:
            pass
        try:
            dpg.add_theme_style(
                dpg.mvStyleVar_WindowBorderSize,
                frame.border_size,
                -1.0,
                parent=component_tag,
            )
            dpg.add_theme_style(
                dpg.mvStyleVar_WindowRounding,
                frame.rounding,
                -1.0,
                parent=component_tag,
            )
            dpg.add_theme_style(
                dpg.mvStyleVar_WindowPadding,
                float(frame.padding_x),
                float(frame.padding_y),
                parent=component_tag,
            )
        except Exception:
            pass
        return int(theme_tag)
    except Exception:
        return None


# Local import of ``validate_non_empty_str`` — kept at the bottom so
# the helper is co-located with its sole new caller and the existing
# import block at the top of the file stays unchanged.
from pharos_engine._validation import validate_non_empty_str  # noqa: E402


__all__ = [
    "apply_theme_to_dpg",
    "build_panel_theme",
    "get_last_dpg_payload",
    "mark_dpg_context_ready",
]
