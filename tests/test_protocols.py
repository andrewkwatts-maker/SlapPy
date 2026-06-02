"""Coverage for the three structural-type Protocols introduced in Round 3.

The protocols formalise long-standing duck types across the public API:

* :class:`slappyengine.dynamics.WorldLike` — dual surface for
  ``dynamics.World`` / ``softbody.SoftBodyWorld`` accepted by IK,
  joint-spec resolution, and the studio dynamics stage.
* :class:`slappyengine.studio.Renderable` — per-frame ``render(frame)``
  shape for the ``Stage.render_fn`` slot and third-party renderers.
* :class:`slappyengine.post_process.PostProcessParams` — ``pack_params()
  -> bytes`` for ``PARAMS_LAYOUT``-driven post-process passes (so the
  executor's UBO splice helper can type-check non-base-class passes).

Each Protocol is marked ``@runtime_checkable`` so :func:`isinstance` is
authoritative for the structural match. The tests below exercise:

* the canonical implementations (``World``, ``BloomPass``, …) match
  the Protocol via ``isinstance``;
* lookalike anonymous classes implementing the required attributes are
  accepted (structural, not nominal);
* incomplete lookalikes are rejected.
"""
from __future__ import annotations

import numpy as np
from PIL import Image

from slappyengine.dynamics import (
    DynamicsWorldLike,
    World,
    WorldLike,
)
from slappyengine.post_process import PostProcessParams
from slappyengine.post_process.bloom import BloomPass
from slappyengine.post_process.outline import OutlinePass
from slappyengine.post_process.tonemap import TonemapPass
from slappyengine.studio import Renderable, Stage, dynamics_stage


# ---------------------------------------------------------------------------
# WorldLike / DynamicsWorldLike
# ---------------------------------------------------------------------------


def test_worldlike_canonical_dynamics_world_matches() -> None:
    """The shipped :class:`World` is the reference implementation."""
    w = World()
    assert isinstance(w, WorldLike)
    assert isinstance(w, DynamicsWorldLike)


def test_worldlike_lookalike_with_only_gravity_matches() -> None:
    """The minimal-surface Protocol only requires ``gravity``."""

    class MinimalWorld:
        def __init__(self) -> None:
            self.gravity = (0.0, -9.81)

    assert isinstance(MinimalWorld(), WorldLike)


def test_worldlike_object_missing_gravity_is_rejected() -> None:
    """Without ``gravity`` the structural check fails."""

    class NotAWorld:
        positions = np.zeros((0, 2))

    assert not isinstance(NotAWorld(), WorldLike)


def test_dynamicsworldlike_requires_positions_step_joints() -> None:
    """The stricter Protocol enforces the dynamics-substrate surface."""

    class HalfWorld:
        def __init__(self) -> None:
            self.gravity = (0.0, -9.81)
            self.positions = np.zeros((0, 2), dtype=np.float64)
            # No `inv_masses`, no `joints`, no `step` — must fail.

    assert isinstance(HalfWorld(), WorldLike)
    assert not isinstance(HalfWorld(), DynamicsWorldLike)


def test_dynamicsworldlike_lookalike_matches() -> None:
    """Any object exposing the four DynamicsWorldLike attrs matches."""

    class FullWorld:
        def __init__(self) -> None:
            self.gravity = np.asarray((0.0, -9.81))
            self.positions = np.zeros((0, 2), dtype=np.float64)
            self.inv_masses = np.zeros((0,), dtype=np.float64)
            self.joints: list = []

        def step(self, dt: float) -> None:
            pass

    assert isinstance(FullWorld(), DynamicsWorldLike)


def test_worldlike_used_by_solve_ik_and_dynamics_stage() -> None:
    """End-to-end: ``solve_ik`` accepts a :class:`World` (WorldLike)."""
    from slappyengine.dynamics import IKChainSpec, solve_ik

    w = World()
    # Build a tiny 3-node chain at (0,0), (1,0), (2,0).
    for x in (0.0, 1.0, 2.0):
        w.add_node((x, 0.0), mass=1.0)
    spec = IKChainSpec(node_indices=[0, 1, 2], target=(2.0, 0.5))
    # Mutates positions; we only care that the call succeeds (it accepts
    # WorldLike).
    solve_ik(spec, w, iterations=5)
    # dynamics_stage also accepts a DynamicsWorldLike-shaped object.
    stage = dynamics_stage(world=w)
    assert stage.dynamics is w


# ---------------------------------------------------------------------------
# Renderable
# ---------------------------------------------------------------------------


def test_renderable_numpy_lookalike_matches() -> None:
    """Object with ``render(frame) -> ndarray`` satisfies the protocol."""

    class NumpyRenderer:
        def render(self, frame: int) -> np.ndarray:
            return np.zeros((8, 8, 4), dtype=np.uint8)

    r = NumpyRenderer()
    assert isinstance(r, Renderable)
    arr = r.render(0)
    assert isinstance(arr, np.ndarray)


def test_renderable_pil_lookalike_matches() -> None:
    """Object returning a PIL.Image also satisfies the protocol."""

    class PILRenderer:
        def render(self, frame: int) -> Image.Image:
            return Image.new("RGB", (4, 4), (0, 0, 0))

    r = PILRenderer()
    assert isinstance(r, Renderable)
    img = r.render(0)
    assert isinstance(img, Image.Image)


def test_renderable_missing_render_method_is_rejected() -> None:
    """Bare object — no ``render`` — fails the structural check."""

    class Bare:
        pass

    assert not isinstance(Bare(), Renderable)


def test_renderable_exported_from_studio_module() -> None:
    """``Renderable`` is in ``slappyengine.studio.__all__``."""
    from slappyengine import studio

    assert "Renderable" in studio.__all__


def test_renderable_used_with_stage_render_fn_slot() -> None:
    """Adapter Renderable -> ``Stage.render_fn`` callable round-trip.

    The ``render_fn`` slot itself is a callable; a Renderable adapter
    closes over the per-frame call. This documents the canonical bridge.
    """

    class CountingRenderer:
        def __init__(self) -> None:
            self.frames: int = 0

        def render(self, frame: int) -> Image.Image:
            self.frames += 1
            return Image.new("RGB", (8, 8), (0, 0, 0))

    renderer = CountingRenderer()
    assert isinstance(renderer, Renderable)
    # Adapter: turn the Renderable into the Stage.render_fn callable shape.
    stage = Stage(render_fn=lambda s: renderer.render(0))
    assert stage.render_fn is not None
    stage.render_fn(stage)
    assert renderer.frames == 1


# ---------------------------------------------------------------------------
# PostProcessParams
# ---------------------------------------------------------------------------


def test_post_process_params_canonical_passes_match() -> None:
    """Shipped passes (Bloom, Tonemap, Outline) satisfy the protocol."""
    bp = BloomPass()
    tp = TonemapPass()
    op = OutlinePass()
    for pass_ in (bp, tp, op):
        assert isinstance(pass_, PostProcessParams), (
            f"{type(pass_).__name__} should satisfy PostProcessParams"
        )


def test_post_process_params_pack_returns_bytes_and_matches_legacy() -> None:
    """``pack_params`` is a byte-for-byte alias for ``params_to_bytes``."""
    bp = BloomPass()
    raw = bp.pack_params()
    assert isinstance(raw, bytes)
    assert raw == bp.params_to_bytes()
    assert len(raw) > 0


def test_post_process_params_lookalike_matches() -> None:
    """Third-party pass with only ``pack_params`` satisfies the protocol."""

    class CustomPass:
        def pack_params(self) -> bytes:
            return b"\x00\x00\x00\x00"

    assert isinstance(CustomPass(), PostProcessParams)


def test_post_process_params_missing_method_is_rejected() -> None:
    """Object without ``pack_params`` fails the structural check."""

    class Bare:
        def something_else(self) -> bytes:
            return b""

    assert not isinstance(Bare(), PostProcessParams)


def test_post_process_params_exported_from_post_process_package() -> None:
    """``PostProcessParams`` is publicly importable + in __all__."""
    from slappyengine import post_process

    assert "PostProcessParams" in post_process.__all__
    # Lazy-loadable.
    assert post_process.PostProcessParams is PostProcessParams
