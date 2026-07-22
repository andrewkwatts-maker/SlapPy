"""
SlapPyEngine.split_screen
=========================

N-way split-screen viewport management.

The engine calls :attr:`SplitScreenManager.viewports` each frame and renders
the scene once per viewport using that viewport's camera.  Up to 8+ players
are supported; the default auto-layout is a grid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Viewport
# ---------------------------------------------------------------------------

@dataclass
class Viewport:
    """One player's screen region, in pixel coordinates."""

    player_id: int
    x: int          # pixel offset from the left edge of the window
    y: int          # pixel offset from the top edge of the window
    width: int
    height: int
    camera: Any     # Camera instance for this viewport (or None)
    border_color: tuple[int, int, int] = field(default_factory=lambda: (40, 40, 40))
    border_px: int = 2


# ---------------------------------------------------------------------------
# SplitScreenManager
# ---------------------------------------------------------------------------

class SplitScreenManager:
    """
    Divides the window into N player viewports.

    Basic usage::

        ss = engine.enable_split_screen(num_players=4)
        ss.set_camera(player_id=0, camera=cam0)
        ss.set_camera(player_id=1, camera=cam1)
        ss.set_camera(player_id=2, camera=cam2)
        ss.set_camera(player_id=3, camera=cam3)

    Custom layout::

        ss.set_layout([
            Viewport(0, 0,   0,   640, 360, cam0),  # top-left
            Viewport(1, 640, 0,   640, 360, cam1),  # top-right
            Viewport(2, 0,   360, 640, 360, cam2),  # bottom-left
            Viewport(3, 640, 360, 640, 360, cam3),  # bottom-right
        ])

    Auto-layout rules
    -----------------
    * 1 player  — full screen.
    * 2 players — side-by-side when landscape, top/bottom when portrait.
    * 3 players — one large panel on top, two equal panels on the bottom.
    * 4+ players — grid with ``ceil(sqrt(n))`` columns.
    """

    def __init__(
        self,
        screen_w: int,
        screen_h: int,
        num_players: int,
        cameras: list | None = None,
    ) -> None:
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.num_players = num_players
        self.viewports: list[Viewport] = []
        self._auto_layout(cameras or [None] * num_players)

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    def _auto_layout(self, cameras: list) -> None:
        """Generate viewport rects for *num_players* using the default grid."""
        n = self.num_players
        W, H = self.screen_w, self.screen_h

        if n == 1:
            rects = [(0, 0, W, H)]
        elif n == 2:
            if W >= H:
                # Landscape — side by side
                rects = [(0, 0, W // 2, H), (W // 2, 0, W - W // 2, H)]
            else:
                # Portrait — top / bottom
                rects = [(0, 0, W, H // 2), (0, H // 2, W, H - H // 2)]
        elif n == 3:
            # One large top panel, two equal bottom panels
            rects = [
                (0, 0, W, H // 2),
                (0, H // 2, W // 2, H - H // 2),
                (W // 2, H // 2, W - W // 2, H - H // 2),
            ]
        else:
            # General grid: ceil(sqrt(n)) columns
            cols = math.ceil(math.sqrt(n))
            rows = math.ceil(n / cols)
            tw = W // cols
            th = H // rows
            rects = []
            for i in range(n):
                col = i % cols
                row = i // cols
                # Last column/row may get one extra pixel to fill perfectly
                x = col * tw
                y = row * th
                w = (W - x) if col == cols - 1 else tw
                h = (H - y) if row == rows - 1 else th
                rects.append((x, y, w, h))

        self.viewports = [
            Viewport(
                player_id=i,
                x=x, y=y, width=w, height=h,
                camera=cameras[i] if i < len(cameras) else None,
            )
            for i, (x, y, w, h) in enumerate(rects)
        ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_camera(self, player_id: int, camera) -> None:
        """Assign a Camera to the viewport for *player_id*."""
        for vp in self.viewports:
            if vp.player_id == player_id:
                vp.camera = camera
                # Update the camera's viewport size to match this panel
                if camera is not None and hasattr(camera, '_viewport_size'):
                    camera._viewport_size = (vp.width, vp.height)
                return
        raise ValueError(f"No viewport for player_id={player_id!r}")

    def set_layout(self, viewports: list[Viewport]) -> None:
        """Replace the auto-generated layout with a custom list of Viewports."""
        self.viewports = viewports
        self.num_players = len(viewports)
        # Sync camera viewport sizes
        for vp in self.viewports:
            if vp.camera is not None and hasattr(vp.camera, '_viewport_size'):
                vp.camera._viewport_size = (vp.width, vp.height)

    def viewport_for_player(self, player_id: int) -> Viewport | None:
        """Return the Viewport for *player_id*, or ``None`` if not found."""
        for vp in self.viewports:
            if vp.player_id == player_id:
                return vp
        return None
