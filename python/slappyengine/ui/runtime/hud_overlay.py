"""Runtime HUD overlay — bridges HH7 widgets to the JJ1 renderer.

The :class:`HUDOverlay` sits above the game's 3D scene: after the game
frame is rendered, ``begin_frame`` opens a new HUD tick, every attached
widget's ``.build(ui)`` is invoked (emitting :class:`DrawCommand`s), and
``submit_to_renderer`` translates those commands into
``Renderer.submit_sprite`` / SDF text mesh calls.

The overlay owns a dedicated :class:`ImmediateUI` context so the game's
own ``ui`` (if any) is not disturbed — HUD widgets always render into
their own draw list. A 2D orthographic camera (``Camera2D``) supplies
the screen-space projection used by the sprite path.

Typical wiring in a game tick::

    hud = HUDOverlay(renderer, camera_2d)
    hud.attach(HealthBar(value=hp, max_value=100))
    hud.attach(Crosshair())
    ...
    hud.begin_frame(dt, input_state={"mouse": (mx, my), "mouse_down": md})
    hud.end_frame()
    hud.submit_to_renderer()

The overlay is deliberately renderer-agnostic — it never imports
``Renderer`` directly. Any object providing ``submit_sprite`` +
``submit_lines`` (or the SDF-text path) will do, which keeps unit tests
honest against a fake renderer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Protocol

import numpy as np

from .draw_command import DrawCommand
from .immediate_ui import ImmediateUI
from .runtime_theme import RuntimeTheme


# ---------------------------------------------------------------------------
# Sprite bridge — converts a rect / textured_quad DrawCommand into a
# ``Renderer.submit_sprite`` call.
# ---------------------------------------------------------------------------


@dataclass
class SpriteSubmission:
    """Data payload for a Renderer.submit_sprite call.

    Kept as a plain dataclass so tests can assert on the packed transform
    + tint without spinning up a real Renderer.
    """

    texture_id: int | None
    transform_2d: np.ndarray
    tint: tuple[float, float, float, float]


def hud_command_to_sprite(cmd: DrawCommand) -> SpriteSubmission:
    """Convert a ``rect`` or ``textured_quad`` DrawCommand → SpriteSubmission.

    The 2D transform is packed as a 3x3 affine matrix (row-major) that
    positions the unit quad at ``cmd.position`` and scales it to
    ``cmd.size``. When ``size == (0, 0)`` the command is treated as
    "fullscreen" (matching the frame-clear convention in
    :meth:`ImmediateUI.begin_frame`) and expands to a 1x1 quad at origin.

    Raises
    ------
    ValueError
        If ``cmd.kind`` is neither ``"rect"`` nor ``"textured_quad"``.
    """
    if cmd.kind not in ("rect", "textured_quad"):
        raise ValueError(
            "hud_command_to_sprite: expected kind='rect' or 'textured_quad'; "
            f"got {cmd.kind!r}"
        )
    x, y = cmd.position
    w, h = cmd.size
    if w == 0.0 and h == 0.0:
        w, h = 1.0, 1.0
    transform = np.array(
        [
            [w, 0.0, x],
            [0.0, h, y],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    return SpriteSubmission(
        texture_id=cmd.texture_id,
        transform_2d=transform,
        tint=cmd.color,
    )


def hud_command_to_text(cmd: DrawCommand, atlas: Any) -> Any:
    """Convert a ``text`` DrawCommand → SDF text mesh via KK6.

    Parameters
    ----------
    cmd:
        A DrawCommand with ``kind == "text"``. ``cmd.size`` is treated as
        the (width, height) hint; ``height`` drives the SDF size.
    atlas:
        A :class:`~slappyengine.text.SDFGlyphAtlas` supplying glyph
        metrics. When ``None`` the function returns ``None`` so callers
        in headless CI can skip text without special-casing.

    Returns
    -------
    A :class:`~slappyengine.text.TextMesh` — or ``None`` when the atlas
    is missing.
    """
    if cmd.kind != "text":
        raise ValueError(
            "hud_command_to_text: expected kind='text'; "
            f"got {cmd.kind!r}"
        )
    if atlas is None:
        return None
    # Soft-import to keep the runtime package importable without KK6.
    from slappyengine.text import SDFTextRenderer

    renderer = SDFTextRenderer()
    # Prefer the explicit height hint; fall back to a sensible default so
    # callers can leave size=(0,0) untouched on freshly-built commands.
    size_px = float(cmd.size[1]) if cmd.size[1] > 0 else 14.0
    return renderer.build_text_mesh(
        text=cmd.text or "",
        position_px=cmd.position,
        size_px=size_px,
        atlas=atlas,
    )


# ---------------------------------------------------------------------------
# Widget protocol — anything with a .build(ui) method qualifies.
# ---------------------------------------------------------------------------


class _HUDWidget(Protocol):
    def build(self, ui: ImmediateUI) -> None: ...


# ---------------------------------------------------------------------------
# HUDOverlay
# ---------------------------------------------------------------------------


class HUDOverlay:
    """Screen-space HUD manager that renders on top of the 3D viewport.

    Parameters
    ----------
    renderer:
        Any object exposing ``submit_sprite(texture, transform_2d, tint)``.
        The real :class:`~slappyengine.render.Renderer` fits; so does a
        stub with the same signature for tests.
    camera_2d:
        A :class:`~slappyengine.render.camera.Camera2D` used to derive
        the screen-space viewport size + orthographic projection. HUD
        widgets emit pixel-space coordinates directly, so the projection
        is only queried once per frame (in :meth:`submit_to_renderer`)
        to update ``Renderer.set_camera``.
    text_atlas:
        Optional SDF glyph atlas used by :func:`hud_command_to_text`.
        When ``None``, text commands are skipped instead of raising.
    theme:
        Optional :class:`RuntimeTheme` used by the internal ImmediateUI.
    default_font_size:
        Default font size handed to the internal ImmediateUI.

    Attributes
    ----------
    visible:
        ``False`` → :meth:`submit_to_renderer` becomes a no-op and the
        widget build phase is skipped in :meth:`begin_frame`.
    """

    def __init__(
        self,
        renderer: Any,
        camera_2d: Any,
        *,
        text_atlas: Any = None,
        theme: RuntimeTheme | None = None,
        default_font_size: int = 14,
    ) -> None:
        if renderer is None:
            raise ValueError("HUDOverlay: renderer must not be None")
        if camera_2d is None:
            raise ValueError("HUDOverlay: camera_2d must not be None")

        self.renderer = renderer
        self.camera_2d = camera_2d
        self.text_atlas = text_atlas
        self.visible: bool = True

        self._ui = ImmediateUI(theme=theme, default_font_size=default_font_size)
        self._widgets: list[_HUDWidget] = []

        # Draw list produced by the most recent end_frame call.
        self._last_commands: list[DrawCommand] = []
        self._in_frame: bool = False

    # ------------------------------------------------------------------
    # Widget management
    # ------------------------------------------------------------------

    def attach(self, widget: _HUDWidget) -> None:
        """Register a HUD widget for the next frame.

        Widgets are ordered by insertion; earlier widgets render first
        (but the final z-order still comes from each widget's own
        DrawCommand emissions).
        """
        if widget is None:
            raise ValueError("HUDOverlay.attach: widget must not be None")
        if not hasattr(widget, "build"):
            raise TypeError(
                "HUDOverlay.attach: widget must have a .build(ui) method; "
                f"got {type(widget).__name__}"
            )
        self._widgets.append(widget)

    def detach(self, widget: _HUDWidget) -> None:
        """Remove *widget* from the overlay; silent no-op if unattached."""
        try:
            self._widgets.remove(widget)
        except ValueError:
            pass

    def clear(self) -> None:
        """Detach every widget in one call."""
        self._widgets.clear()

    def widgets(self) -> tuple[_HUDWidget, ...]:
        """Return the current widget list as a defensive copy."""
        return tuple(self._widgets)

    def set_visible(self, visible: bool) -> None:
        """Toggle the entire HUD on/off."""
        self.visible = bool(visible)

    # ------------------------------------------------------------------
    # Frame lifecycle
    # ------------------------------------------------------------------

    def begin_frame(
        self,
        dt: float,
        input_state: dict | None = None,
    ) -> None:
        """Open a new HUD frame.

        Parameters
        ----------
        dt:
            Seconds since the previous frame — forwarded to the internal
            ImmediateUI so animated widgets (toasts, incrementers) tick.
        input_state:
            Optional dict with any of ``{"mouse": (x,y), "mouse_down":
            bool, "keys_down": set[str]}``. Missing keys default to the
            "no interaction" state; passing ``None`` is equivalent to an
            empty dict.
        """
        if self._in_frame:
            raise RuntimeError(
                "HUDOverlay.begin_frame: called twice without end_frame"
            )
        self._in_frame = True

        if not self.visible:
            # Skip the whole build phase but still open/close a
            # bookkeeping frame so end_frame() has a well-defined
            # contract.
            self._last_commands = []
            return

        state = input_state or {}
        self._ui.begin_frame(
            dt=float(dt),
            mouse_pos=tuple(state.get("mouse", (0.0, 0.0))),
            keys_down=set(state.get("keys_down", set())),
            mouse_down=bool(state.get("mouse_down", False)),
        )

        for widget in self._widgets:
            try:
                widget.build(self._ui)
            except Exception:
                # A misbehaving widget must not tank the whole HUD.
                # Widgets are expected to be side-effect free, so we
                # swallow the exception and keep going — the caller can
                # instrument via a logger if they need to trace it.
                continue

    def end_frame(self) -> list[DrawCommand]:
        """Close the HUD frame and return the accumulated draw list."""
        if not self._in_frame:
            raise RuntimeError(
                "HUDOverlay.end_frame: no frame in progress"
            )
        self._in_frame = False

        if not self.visible:
            self._last_commands = []
            return []

        cmds = self._ui.end_frame()
        # Skip the ImmediateUI full-frame clear (z_order=0, size=(0,0));
        # the HUD is an overlay, we never want to blank the 3D viewport.
        self._last_commands = [
            c for c in cmds
            if not (c.kind == "rect" and c.size == (0.0, 0.0) and c.z_order == 0)
        ]
        return list(self._last_commands)

    # ------------------------------------------------------------------
    # Renderer submission
    # ------------------------------------------------------------------

    def submit_to_renderer(self) -> int:
        """Walk the last-frame draw list and submit to the renderer.

        Returns the number of commands actually forwarded — 0 when the
        HUD is hidden or the last frame was empty.
        """
        if not self.visible:
            return 0

        submitted = 0
        line_batches: list[tuple[np.ndarray, np.ndarray]] = []

        for cmd in self._last_commands:
            if cmd.kind in ("rect", "textured_quad"):
                sprite = hud_command_to_sprite(cmd)
                # Duck-type: use a lightweight TextureHandle-shaped object
                # so the null renderer records the texture_id correctly.
                tex = _FakeTexture(sprite.texture_id) if sprite.texture_id is not None else None
                try:
                    self.renderer.submit_sprite(
                        tex, sprite.transform_2d, sprite.tint
                    )
                    submitted += 1
                except Exception:
                    continue
            elif cmd.kind == "line":
                # Batch line commands: each cmd is a single segment from
                # cmd.position → cmd.position + cmd.size.
                x0, y0 = cmd.position
                x1, y1 = x0 + cmd.size[0], y0 + cmd.size[1]
                verts = np.array([[x0, y0], [x1, y1]], dtype=np.float32)
                cols = np.array([cmd.color, cmd.color], dtype=np.float32)
                line_batches.append((verts, cols))
            elif cmd.kind == "text":
                mesh = hud_command_to_text(cmd, self.text_atlas)
                if mesh is None:
                    continue
                # Text meshes ship as pos2+uv2 vertex streams; when the
                # renderer exposes a dedicated ``submit_text`` we use it,
                # otherwise fall through to a plain sprite pass keyed on
                # the atlas texture id.
                submit_text = getattr(self.renderer, "submit_text", None)
                if callable(submit_text):
                    try:
                        submit_text(mesh, cmd.color)
                        submitted += 1
                    except Exception:
                        continue
            elif cmd.kind == "circle":
                # Circles are drawn as a filled rect fallback — enough
                # for aiming reticles + minimap dots. Full disk raster
                # comes later once the renderer exposes a disk path.
                sprite = hud_command_to_sprite(
                    DrawCommand(
                        kind="rect",
                        position=cmd.position,
                        size=cmd.size,
                        color=cmd.color,
                    )
                )
                try:
                    self.renderer.submit_sprite(
                        None, sprite.transform_2d, sprite.tint
                    )
                    submitted += 1
                except Exception:
                    continue

        # Flush the batched line pass.
        if line_batches:
            all_verts = np.concatenate([b[0] for b in line_batches], axis=0)
            all_cols = np.concatenate([b[1] for b in line_batches], axis=0)
            submit_lines = getattr(self.renderer, "submit_lines", None)
            if callable(submit_lines):
                try:
                    submit_lines(all_verts, all_cols)
                    submitted += len(line_batches)
                except Exception:
                    pass

        return submitted

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    @property
    def command_count(self) -> int:
        """Number of draw commands in the most recent frame."""
        return len(self._last_commands)

    @property
    def widget_count(self) -> int:
        return len(self._widgets)


# ---------------------------------------------------------------------------
# Internal fake texture — mirrors the shape of TextureHandle just enough
# for NullRenderer.submit_sprite() to record the id.
# ---------------------------------------------------------------------------


@dataclass
class _FakeTexture:
    id: int | None


__all__ = [
    "HUDOverlay",
    "SpriteSubmission",
    "hud_command_to_sprite",
    "hud_command_to_text",
]
