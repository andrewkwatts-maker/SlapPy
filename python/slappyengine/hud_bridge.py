"""HUD bridge — wire LL1's :class:`HUDOverlay` into HH1's :class:`App` lifecycle.

The user's directive (2026-07-05 MM2 sprint):

    Wire LL1's HUDOverlay into HH1's App lifecycle end-to-end, plus build a
    hello_hud demo that renders a game HUD over a rotating 3D scene.

This module is the *thin glue* layer:

* :func:`mount_hud` — instantiate an :class:`HUDOverlay`, attach the default
  game HUD widgets (or the caller-supplied ones), and hook the overlay into
  the app's ``add_after_tick`` / ``add_before_frame_render`` chains so the
  HUD ticks once per frame without the caller writing any lifecycle code.
* :func:`unmount_hud` — cleanly detach; safe to call when nothing is mounted.
* :func:`default_game_hud_widgets` — return a ready-to-use list of five
  first-party widgets (HealthBar, StaminaBar, AmmoCounter, Compass,
  Crosshair) with sensible defaults so a game boots with a usable HUD.

The bridge is *renderer-agnostic*: when the app's renderer lacks the
``submit_sprite`` / ``submit_lines`` surface (the pre-HH4 stub), we wrap it
in :class:`_HUDStubRenderer` — a tiny recorder that captures every sprite /
line / text submission into a Python list so headless demos + tests can
still assert on HUD activity without a real GPU. This keeps the "2-line pip
install and render" promise: the developer just calls ``app.enable_hud()``
and a fully functional HUD appears in every trace + every frame.

Every hook records a trace event into ``app.trace`` so downstream tooling
(golden-master tests, YAML replay, sprint dashboards) can see exactly when
each HUD phase fired. Trace event kinds emitted by this module:

* ``("hud_mount", widget_count)``       — one per successful mount.
* ``("hud_unmount",)``                  — one per detach.
* ``("hud_begin_frame", dt, cmd_count)`` — every after-tick hook fire.
* ``("hud_submit", submitted_count)``   — every before-frame-render fire.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Iterable


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Stub renderer shim — used when the app's real renderer is the HH1 log-only
# stub (which has begin_frame / draw_model / end_frame but no submit_sprite).
# ---------------------------------------------------------------------------


class _HUDStubRenderer:
    """Minimal recorder that mimics the JJ1 renderer's HUD submission surface.

    HUDOverlay only calls three methods against the renderer:

    * ``submit_sprite(texture, transform_2d, tint)``
    * ``submit_lines(vertices, colors)``
    * ``submit_text(mesh, color)`` (optional — text is skipped when absent
      or the atlas is missing)

    The HH1 :class:`~slappyengine.app._StubRenderer` implements none of
    these, so we wrap it in this recorder. Every call is captured verbatim
    in :attr:`sprites` / :attr:`lines` / :attr:`texts` so tests can assert
    on HUD activity without a real GPU. The wrapped stub keeps rendering
    the 3D scene through its own ``begin_frame`` / ``draw_model`` /
    ``end_frame`` surface — we do not intercept those.
    """

    def __init__(self) -> None:
        self.sprites: list[tuple[Any, Any, tuple]] = []
        self.lines: list[tuple[Any, Any]] = []
        self.texts: list[tuple[Any, tuple]] = []

    # HUDOverlay contract — the three submission methods.
    def submit_sprite(self, texture: Any, transform_2d: Any, tint: tuple) -> None:
        self.sprites.append((texture, transform_2d, tint))

    def submit_lines(self, vertices: Any, colors: Any) -> None:
        self.lines.append((vertices, colors))

    def submit_text(self, mesh: Any, color: tuple) -> None:
        self.texts.append((mesh, color))

    # ------------------------------------------------------------------
    def clear(self) -> None:
        """Reset all recorded submissions (useful between frames in tests)."""
        self.sprites.clear()
        self.lines.clear()
        self.texts.clear()

    @property
    def total_submissions(self) -> int:
        return len(self.sprites) + len(self.lines) + len(self.texts)


# ---------------------------------------------------------------------------
# Camera2D shim — used when :mod:`slappyengine.render.camera` is unavailable
# in stripped installs. Matches the tiny surface HUDOverlay reads from.
# ---------------------------------------------------------------------------


class _HUDStubCamera2D:
    """Fallback 2D camera when the render subpackage is not importable.

    HUDOverlay stashes the camera on ``self.camera_2d`` but only reads its
    :attr:`viewport_size` in the shipped code paths; the projection is
    otherwise unused inside the overlay itself. This tiny stand-in keeps
    the bridge importable in trimmed environments (e.g. wheels that ship
    without the render subpackage).
    """

    def __init__(self, viewport_size: tuple[int, int] = (1280, 720)) -> None:
        self.viewport_size = viewport_size
        self.position: tuple[float, float] = (0.0, 0.0)
        self.zoom: float = 1.0


def _build_camera_2d(app: Any) -> Any:
    """Return a :class:`~slappyengine.render.Camera2D` bound to app's viewport.

    Falls back to :class:`_HUDStubCamera2D` when the render subpackage is
    unavailable so ``mount_hud`` still succeeds in trimmed environments.
    """
    viewport = tuple(getattr(app.config, "window_size", (1280, 720)))
    try:
        from slappyengine.render.camera import Camera2D
    except Exception as exc:  # pragma: no cover - stripped env
        logger.debug("hud_bridge: Camera2D unavailable (%s); using stub", exc)
        return _HUDStubCamera2D(viewport_size=viewport)
    return Camera2D(viewport_size=viewport)


# ---------------------------------------------------------------------------
# Default widget factories
# ---------------------------------------------------------------------------


def default_game_hud_widgets() -> list[Any]:
    """Return an instantiated list of the five default game HUD widgets.

    The widgets are laid out for a 1280x720 viewport by default:

    * :class:`HealthBar`  — top-left, red fill, HP 100/100.
    * :class:`StaminaBar` — under the health bar, green fill.
    * :class:`AmmoCounter` — under stamina, ``0 / 0`` placeholder.
    * :class:`Compass`    — top-left column, bearing 0.
    * :class:`Crosshair`  — dead centre of a 1280x720 viewport.

    Widgets are fresh instances each call so the caller can safely mutate
    fields without spooky-action-at-a-distance.
    """
    from slappyengine.ui.runtime.hud_registry import HUDRegistry

    registry = HUDRegistry()
    return [
        registry.create("health_bar",  {"value": 100.0, "max_value": 100.0}),
        registry.create("stamina_bar", {"value": 100.0, "max_value": 100.0}),
        registry.create("ammo_counter", {"current": 30, "reserve": 90, "weapon_name": "RIFLE"}),
        registry.create("compass",     {"heading_deg": 0.0}),
        registry.create("crosshair",   {"center": (640.0, 360.0)}),
    ]


# ---------------------------------------------------------------------------
# Mount / unmount
# ---------------------------------------------------------------------------


_HUD_HOOK_ATTR = "_hud_bridge_hooks"


def mount_hud(app: Any, *, widgets: Iterable[Any] | None = None) -> Any:
    """Instantiate a :class:`HUDOverlay` bound to *app* and attach widgets.

    Wires two lifecycle hooks:

    * ``after_tick(app, dt)``   → ``hud.begin_frame(dt, input_state) +
      hud.end_frame()``. We fold both phases into one hook so the widget
      draw list is fully baked *before* the render pass runs.
    * ``before_frame_render(app)`` → ``hud.submit_to_renderer()`` — pushes
      the baked draw list through the renderer's sprite / line / text
      submission surface.

    The overlay is stored on ``app._hud_overlay`` (mirroring the field
    :meth:`App.enable_hud` writes) and the paired hook callables are
    stashed on ``app._hud_bridge_hooks`` so :func:`unmount_hud` can detach
    them cleanly.

    Parameters
    ----------
    app:
        The :class:`~slappyengine.App` instance to attach to.
    widgets:
        Optional iterable of pre-instantiated widgets. When ``None`` the
        widgets from :func:`default_game_hud_widgets` are used.

    Returns
    -------
    HUDOverlay
        The newly created overlay.
    """
    if app is None:
        raise ValueError("mount_hud: app must not be None")

    # Idempotent — reuse the existing overlay if one is already mounted.
    existing = getattr(app, "_hud_overlay", None)
    if existing is not None:
        return existing

    from slappyengine.ui.runtime.hud_overlay import HUDOverlay

    # Renderer shim — HUDOverlay needs submit_sprite; wrap the stub renderer
    # in the recorder so headless demos still produce meaningful traces.
    real_renderer = getattr(app, "_renderer", None)
    if real_renderer is None or not hasattr(real_renderer, "submit_sprite"):
        hud_renderer: Any = _HUDStubRenderer()
    else:
        hud_renderer = real_renderer

    camera_2d = _build_camera_2d(app)
    overlay = HUDOverlay(renderer=hud_renderer, camera_2d=camera_2d)

    # Attach widgets — default set when caller didn't supply any.
    widget_list = list(widgets) if widgets is not None else default_game_hud_widgets()
    for widget in widget_list:
        overlay.attach(widget)

    # ------------------------------------------------------------------
    # Lifecycle hooks — wire begin_frame + end_frame into after_tick, and
    # submit_to_renderer into before_frame_render. This keeps the HUD
    # ticking once per frame in App.run() with zero extra plumbing at the
    # call site.
    # ------------------------------------------------------------------

    def _hud_after_tick(a: Any, dt: float) -> None:
        try:
            overlay.begin_frame(float(dt), input_state=None)
            overlay.end_frame()
            a.trace.append(("hud_begin_frame", float(dt), overlay.command_count))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("hud_bridge: after_tick hook raised %s", exc)

    def _hud_before_frame_render(a: Any) -> None:
        try:
            n = overlay.submit_to_renderer()
            a.trace.append(("hud_submit", int(n)))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("hud_bridge: before_frame_render hook raised %s", exc)

    app.add_after_tick(_hud_after_tick)
    app.add_before_frame_render(_hud_before_frame_render)

    setattr(app, _HUD_HOOK_ATTR, (_hud_after_tick, _hud_before_frame_render))
    app._hud_overlay = overlay
    app.trace.append(("hud_mount", len(widget_list)))
    return overlay


def unmount_hud(app: Any) -> bool:
    """Detach the HUD from *app*. Idempotent.

    Returns ``True`` when a HUD was actually detached, ``False`` when
    nothing was mounted.
    """
    if app is None:
        return False
    overlay = getattr(app, "_hud_overlay", None)
    if overlay is None:
        return False

    hooks = getattr(app, _HUD_HOOK_ATTR, None)
    if hooks is not None:
        after_tick_hook, before_render_hook = hooks
        try:
            app._after_tick.remove(after_tick_hook)
        except (ValueError, AttributeError):
            pass
        try:
            app._before_frame_render.remove(before_render_hook)
        except (ValueError, AttributeError):
            pass
        try:
            delattr(app, _HUD_HOOK_ATTR)
        except AttributeError:
            pass

    overlay.clear()
    app._hud_overlay = None
    app.trace.append(("hud_unmount",))
    return True


__all__ = [
    "mount_hud",
    "unmount_hud",
    "default_game_hud_widgets",
    "_HUDStubRenderer",
    "_HUDStubCamera2D",
]
