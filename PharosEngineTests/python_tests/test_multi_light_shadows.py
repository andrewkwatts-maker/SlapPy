"""Tests for the multi-light extension of :class:`ShadowPass`.

These build small ``PhysicsWorld`` scenes, run a multi-light shadow pass,
and assert per-channel relationships in the output frame.  They also
verify backwards compatibility with the existing single-light
``ShadowPass`` defaults and behaviour.
"""
from __future__ import annotations

import importlib.util
import pathlib

import numpy as np

from pharos_engine.physics import (
    PhysicsWorld,
    make_circle_silhouette,
    make_rect_silhouette,
)
from pharos_engine.physics.shadows import (
    MultiLightShadowPass,
    ShadowLight,
    ShadowPass,
)


# Default screen / world geometry must match the ShadowPass defaults.
_WORLD_VIEW = (-200.0, -100.0, 200.0, 250.0)
_W = 640
_H = 360


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _blank_frame(rgb: tuple[int, int, int] = (180, 180, 180)) -> np.ndarray:
    """Return a uniform RGBA frame so darkening is easy to detect."""
    f = np.zeros((_H, _W, 4), dtype=np.uint8)
    f[..., 0] = rgb[0]
    f[..., 1] = rgb[1]
    f[..., 2] = rgb[2]
    f[..., 3] = 255
    return f


def _world_to_screen(x: float, y: float) -> tuple[int, int]:
    wx0, wy0, wx1, wy1 = _WORLD_VIEW
    sx = int((x - wx0) / (wx1 - wx0) * _W)
    sy = int((y - wy0) / (wy1 - wy0) * _H)
    return sx, sy


def _strip_brightness(
    frame: np.ndarray, cx: int, cy: int, w: int = 8, h: int = 4,
) -> float:
    """Mean RGB brightness in a small rectangle around (cx, cy)."""
    x0 = max(0, cx - w // 2)
    x1 = min(frame.shape[1], cx + w // 2)
    y0 = max(0, cy - h // 2)
    y1 = min(frame.shape[0], cy + h // 2)
    region = frame[y0:y1, x0:x1, :3].astype(np.float32)
    return float(region.mean())


def _channel_means(
    frame: np.ndarray, cx: int, cy: int, w: int = 8, h: int = 4,
) -> tuple[float, float, float]:
    """Per-channel (R, G, B) means around (cx, cy)."""
    x0 = max(0, cx - w // 2)
    x1 = min(frame.shape[1], cx + w // 2)
    y0 = max(0, cy - h // 2)
    y1 = min(frame.shape[0], cy + h // 2)
    region = frame[y0:y1, x0:x1, :3].astype(np.float32)
    return (
        float(region[..., 0].mean()),
        float(region[..., 1].mean()),
        float(region[..., 2].mean()),
    )


def _build_ball_on_ground_world() -> PhysicsWorld:
    """Single 30 px ball at (0, 0) and a wide ground rect at y=180."""
    world = PhysicsWorld()
    ball = make_circle_silhouette(30)
    world.create_body(
        silhouette=ball,
        material="steel",
        position=(0.0, 0.0),
        velocity=(0.0, 0.0),
    )
    ground = make_rect_silhouette(width=320, height=20)
    world.create_body(
        silhouette=ground,
        material="stone",
        position=(0.0, 180.0),
        velocity=(0.0, 0.0),
        fixed=True,
    )
    return world


# ---------------------------------------------------------------------------
# 1) backwards compat — no additional lights → identical legacy behaviour
# ---------------------------------------------------------------------------


def test_single_light_unchanged() -> None:
    """A ``ShadowPass`` with no ``additional_lights`` must produce the
    same output (within 1 unit per channel) as today's behaviour.
    """
    world = _build_ball_on_ground_world()
    frame = _blank_frame()

    legacy = ShadowPass(
        light_direction=(0.3, 1.0),
        shadow_length=80.0,
        opacity=0.55,
        softness_px=4.0,
    )
    extended = ShadowPass(
        light_direction=(0.3, 1.0),
        shadow_length=80.0,
        opacity=0.55,
        softness_px=4.0,
        additional_lights=[],
    )

    a = legacy.render(frame, world)
    b = extended.render(frame, world)
    diff = np.abs(a.astype(np.int32) - b.astype(np.int32))
    assert diff.max() <= 1, (
        f"max per-pixel diff between legacy and extended: {diff.max()}"
    )


# ---------------------------------------------------------------------------
# 2) two lights → two distinct dark regions
# ---------------------------------------------------------------------------


def test_two_lights_two_shadows_visible() -> None:
    """Two lights cast shadows from the ball in opposite x-directions.
    Both shadow regions on the ground should be darker than a clearly
    unshadowed reference point.
    """
    world = _build_ball_on_ground_world()
    frame = _blank_frame()

    # Light A: (+0.3, +1.0) → shadow on the +x side of the ball
    # Light B: (-0.3, +1.0) → shadow on the -x side of the ball
    pass_ = MultiLightShadowPass(
        lights=[
            ShadowLight(
                direction=(0.3, 1.0),
                length=200.0,
                opacity=0.7,
                softness=2.0,
                color=(0, 0, 0),
            ),
            ShadowLight(
                direction=(-0.3, 1.0),
                length=200.0,
                opacity=0.7,
                softness=2.0,
                color=(0, 0, 0),
            ),
        ],
    )
    out = pass_.render(frame, world)

    # For direction (±0.3, 1.0) normalised → ground (y=180) is reached at
    # t ≈ 180 / (1/sqrt(1.09)) ≈ 187, well within length=200. The shadow
    # centre lands at x ≈ ±(0.3/sqrt(1.09)) * 187 ≈ ±53.7.
    sx_pos, sy_pos = _world_to_screen(54.0, 180.0)
    sx_neg, sy_neg = _world_to_screen(-54.0, 180.0)
    # A "clearly unshadowed" reference well above the ball (no occluder
    # path reaches up there because the light direction is *downward*).
    sx_ref, sy_ref = _world_to_screen(150.0, -80.0)

    b_pos = _strip_brightness(out, sx_pos, sy_pos)
    b_neg = _strip_brightness(out, sx_neg, sy_neg)
    b_ref = _strip_brightness(out, sx_ref, sy_ref)

    assert b_pos < b_ref - 5.0, (
        f"+x shadow brightness {b_pos:.1f} not darker than ref {b_ref:.1f}"
    )
    assert b_neg < b_ref - 5.0, (
        f"-x shadow brightness {b_neg:.1f} not darker than ref {b_ref:.1f}"
    )


# ---------------------------------------------------------------------------
# 3) red-tinted shadow → R is biased high relative to G+B in the shadow
# ---------------------------------------------------------------------------


def test_red_tinted_shadow() -> None:
    """A light with color=(80, 0, 0) should darken green+blue more than
    red in its shadow region, producing a measurable red bias.
    """
    world = _build_ball_on_ground_world()
    frame = _blank_frame((180, 180, 180))

    red_light = ShadowLight(
        direction=(0.3, 1.0),
        length=200.0,
        opacity=0.8,
        softness=2.0,
        color=(80, 0, 0),
    )
    out = MultiLightShadowPass(lights=[red_light]).render(frame, world)

    # Sample the shadow centre on the ground (same geometry as legacy
    # test: light (0.3, 1.0), shadow at x = 0.3 * 180 = 54).
    sx, sy = _world_to_screen(54.0, 180.0)
    r, g, b = _channel_means(out, sx, sy)

    # Green and blue must be measurably darker than red here.
    assert r > g + 3.0, f"R={r:.1f} not biased above G={g:.1f}"
    assert r > b + 3.0, f"R={r:.1f} not biased above B={b:.1f}"
    # Sanity: still a *shadow* — G and B should be darker than the
    # untouched base (180).
    assert g < 180.0 - 3.0, f"G={g:.1f} not darker than base 180"
    assert b < 180.0 - 3.0, f"B={b:.1f} not darker than base 180"


# ---------------------------------------------------------------------------
# 4) three lights composing → darker than any one, lighter than full black
# ---------------------------------------------------------------------------


def test_three_lights_compose() -> None:
    """Three opacity-0.3 lights at slightly different directions should
    each darken the shadow zone; their combined shadow density is
    darker than any single one but not pure black.
    """
    world = _build_ball_on_ground_world()
    frame = _blank_frame((200, 200, 200))

    # All three lights point roughly downward at slightly different
    # angles so their shadows overlap near directly below the ball.
    dirs = [(0.0, 1.0), (0.1, 1.0), (-0.1, 1.0)]
    lights = [
        ShadowLight(
            direction=d,
            length=200.0,
            opacity=0.3,
            softness=4.0,
            color=(0, 0, 0),
        )
        for d in dirs
    ]

    out_all = MultiLightShadowPass(lights=lights).render(frame, world)
    out_one = MultiLightShadowPass(lights=[lights[0]]).render(frame, world)

    # Overlap zone — directly below the ball, on the ground (y ≈ 90,
    # so we're at the top of the projected fan).
    sx, sy = _world_to_screen(0.0, 80.0)

    b_all = _strip_brightness(out_all, sx, sy)
    b_one = _strip_brightness(out_one, sx, sy)

    # All three lights should produce strictly more darkening than one.
    assert b_all < b_one - 2.0, (
        f"3-light brightness {b_all:.1f} not darker than 1-light {b_one:.1f}"
    )
    # But not pure black — opacity caps at 1 - (1-0.3)^3 ≈ 0.657, so on a
    # base of 200 the floor is ~200 * (1 - 0.657) ≈ 68.6.  Stay well above 0.
    assert b_all > 30.0, f"3-light brightness {b_all:.1f} unexpectedly dark"


# ---------------------------------------------------------------------------
# 5) high softness blurs more → wider falloff
# ---------------------------------------------------------------------------


def test_high_softness_blurs_more() -> None:
    """A softness=12 light should produce a smoother / wider shadow than
    a softness=2 light cast from the same direction.
    """
    world = _build_ball_on_ground_world()
    frame = _blank_frame((180, 180, 180))

    tight = MultiLightShadowPass(
        lights=[
            ShadowLight(
                direction=(0.3, 1.0),
                length=80.0,
                opacity=0.6,
                softness=0.0,
                color=(0, 0, 0),
            ),
        ],
    ).render(frame, world)
    wide = MultiLightShadowPass(
        lights=[
            ShadowLight(
                direction=(0.3, 1.0),
                length=80.0,
                opacity=0.6,
                softness=12.0,
                color=(0, 0, 0),
            ),
        ],
    ).render(frame, world)

    # Compare max gradient along a row that straddles the shadow on the
    # ground — high softness reduces the worst-case per-pixel jump.
    _, sy_row = _world_to_screen(0.0, 180.0)
    sy_row = max(0, min(_H - 1, sy_row))
    tight_row = tight[sy_row, :, 0].astype(np.float32)
    wide_row = wide[sy_row, :, 0].astype(np.float32)
    tight_grad = float(np.abs(np.diff(tight_row)).max())
    wide_grad = float(np.abs(np.diff(wide_row)).max())
    assert wide_grad < tight_grad, (
        f"wide gradient {wide_grad:.2f} not less than tight {tight_grad:.2f}"
    )


# ---------------------------------------------------------------------------
# 6) zero lights → no-op
# ---------------------------------------------------------------------------


def test_zero_lights_is_noop() -> None:
    """``MultiLightShadowPass(lights=[])`` must return the frame unchanged."""
    world = _build_ball_on_ground_world()
    frame = _blank_frame((123, 45, 67))
    out = MultiLightShadowPass(lights=[]).render(frame, world)
    assert np.array_equal(out, frame)

    # ``None`` is equivalent to the empty list.
    out2 = MultiLightShadowPass().render(frame, world)
    assert np.array_equal(out2, frame)


# ---------------------------------------------------------------------------
# 7) existing test_shadows.py tests still pass with the extended class
# ---------------------------------------------------------------------------


def test_existing_test_shadows_still_pass_with_extended_class() -> None:
    """Import every ``test_*`` function from ``test_shadows`` and run it.

    This guarantees the extended ``ShadowPass`` remains drop-in
    compatible with the existing test suite.
    """
    here = pathlib.Path(__file__).resolve().parent
    target = here / "test_shadows.py"
    assert target.exists(), f"missing sibling test file: {target}"

    spec = importlib.util.spec_from_file_location(
        "_existing_test_shadows", str(target),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    failures: list[str] = []
    fn_names = [n for n in dir(mod) if n.startswith("test_")]
    assert fn_names, "expected to discover existing test_shadows.py tests"
    for name in fn_names:
        fn = getattr(mod, name)
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {exc!r}")
    assert not failures, (
        "the following existing tests broke under the extended ShadowPass:\n"
        + "\n".join(failures)
    )
