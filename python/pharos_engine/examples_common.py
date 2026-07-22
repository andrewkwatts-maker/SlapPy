"""Shared CLI plumbing for ``examples/hello_*.py`` demos.

Most demos in :mod:`examples` parse the same four flags (``--frames``,
``--no-gif``, ``--out``, ``--seed``) and run one of two branches: render
+ save GIF, or step-only smoke. This module factors that pattern out so
demos can drop ~15 lines of boilerplate apiece.

Typical use::

    from pathlib import Path

    from pharos_engine import studio
    from pharos_engine.examples_common import (
        build_demo_arg_parser, record_or_smoke,
    )

    DEFAULT_FRAMES = 120

    def build_stage() -> studio.Stage:
        return studio.dynamics_stage(...)

    def _cli(argv: list[str] | None = None) -> int:
        parser = build_demo_arg_parser(
            "Hello Foo - Pharos Engine demo",
            default_frames=DEFAULT_FRAMES,
        )
        args = parser.parse_args(argv)
        record_or_smoke(
            build_stage(),
            args,
            default_out=Path(__file__).parent / "output" / "foo" / "hello_foo.gif",
        )
        return 0

    if __name__ == "__main__":
        raise SystemExit(_cli())

Two output-style conventions are supported:

* **GIF default (``--no-gif`` opt-out)** — what most newer demos use
  (``hello_ragdoll``, ``humanoid_ik_terrain_demo``, etc). ``--no-gif``
  forces the smoke / step-only branch; without it the demo records a GIF.
* **PNG opt-in (``--render``)** — what the dynamics-era hellos use
  (``hello_rope``, ``hello_motor``, ``hello_spring``, ...). ``--render``
  flips the demo into render-and-save mode; without it the demo just
  prints a summary.

Both flags are added unconditionally; demos pick which one to read.
Helper :func:`should_record` collapses the two into a single boolean.

The helper is deliberately tiny — it owns argument parsing, output-path
defaulting (with parent dir creation), and the record/smoke fork. It does
NOT own world / stage construction; demos keep their own ``build_world``
or ``build_stage`` functions.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable


__all__ = [
    "build_demo_arg_parser",
    "record_or_smoke",
    "should_record",
    "resolve_out_path",
]


def build_demo_arg_parser(
    description: str,
    *,
    default_frames: int = 120,
    default_seed: int | None = None,
    default_out: Path | str | None = None,
) -> argparse.ArgumentParser:
    """Return an ``argparse.ArgumentParser`` pre-loaded with the demo flags.

    Args:
        description: top-level ``--help`` description string.
        default_frames: default value for ``--frames`` (demos override per
            their physical horizon — e.g. 120 for rope, 180 for ragdoll).
        default_seed: default value for ``--seed``. ``None`` (the default)
            means "no seed" - the demo's own RNG/initial-conditions logic
            runs unconstrained. Demos that want reproducible runs override.
        default_out: default value for ``--out`` (Path or str). ``None``
            means "the demo resolves its own default", which is the common
            case - :func:`resolve_out_path` honours that.

    Returns:
        ``argparse.ArgumentParser`` with ``--frames``, ``--no-gif``,
        ``--render``, ``--out``, and ``--seed`` added.

    Notes:
        * ``--no-gif`` and ``--render`` are both store-true flags so
          existing CLI invocations stay byte-identical. Demos pick which
          to honour via :func:`should_record`.
        * ``--out`` is typed as ``Path`` so demos can call ``.suffix``
          and ``.parent.mkdir(...)`` without re-typing.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "--frames", type=int, default=int(default_frames),
        help=(
            "number of dt=1/60 steps to integrate "
            f"(default: {int(default_frames)})"
        ),
    )
    parser.add_argument(
        "--no-gif", action="store_true",
        help="skip GIF capture (smoke-test mode; pairs well with --frames 5)",
    )
    parser.add_argument(
        "--render", action="store_true",
        help=(
            "force render-and-save mode (PNG single frame when --out ends "
            "in .png, GIF otherwise). Equivalent to dropping --no-gif."
        ),
    )
    parser.add_argument(
        "--out", type=Path, default=Path(default_out) if default_out else None,
        help="output path (.png writes a single frame, anything else a GIF)",
    )
    parser.add_argument(
        "--seed", type=int, default=default_seed,
        help="RNG seed for demos with stochastic initial conditions",
    )
    return parser


def should_record(args: argparse.Namespace) -> bool:
    """Collapse ``--no-gif`` / ``--render`` into a single record-or-not flag.

    Precedence rules (matches the legacy per-demo logic):

    * ``--render`` wins if present (forces record).
    * Otherwise ``--no-gif`` disables recording.
    * Otherwise record (the conventional default).
    """
    if getattr(args, "render", False):
        return True
    return not bool(getattr(args, "no_gif", False))


def resolve_out_path(
    args: argparse.Namespace,
    default_out: Path | str,
) -> Path:
    """Return ``args.out`` if provided, otherwise ``default_out``.

    Always returns a :class:`pathlib.Path`. Parent directories are
    created (``mkdir(parents=True, exist_ok=True)``) so callers don't
    need a separate guard before writing.
    """
    out_path = Path(args.out) if getattr(args, "out", None) is not None else Path(default_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return out_path


def record_or_smoke(
    stage: Any,
    args: argparse.Namespace,
    default_out: Path | str,
    *,
    fps: int = 30,
    step_world: bool = True,
    pre_step: Callable[[Any], None] | None = None,
    post_step: Callable[[Any, int], None] | None = None,
    overlay: Any | None = None,
) -> Path | None:
    """Either record the stage to a GIF or run a frame-by-frame smoke loop.

    The fork is driven by :func:`should_record`:

    * **Record branch**: calls ``stage.record(out, frames=args.frames,
      ...)``. The returned ``Path`` is propagated back to the caller.
    * **Smoke branch**: emulates ``record`` without the rasterise / save
      cost - steps the stage's world(s) ``args.frames`` times and invokes
      any ``pre_step`` / ``post_step`` hooks per frame. Returns ``None``.

    ``stage`` must quack like :class:`pharos_engine.studio.Stage` - it
    needs a ``.record(...)`` method for the record branch and either
    ``.world.step(dt)`` / ``.softbody`` / ``.fluid`` / ``.dynamics``
    attributes for the smoke branch (the same attributes the
    :func:`pharos_engine.studio.record` loop steps).

    Args:
        stage: a :class:`pharos_engine.studio.Stage` (or duck-equivalent).
        args: parsed CLI namespace from :func:`build_demo_arg_parser`.
        default_out: where to write the GIF if ``args.out`` is unset.
        fps: GIF frame rate (record branch only).
        step_world: forwarded to ``stage.record``; also disables the
            world step in the smoke branch when ``False`` (useful for
            pose-only demos where ``post_step`` rebuilds every frame).
        pre_step, post_step, overlay: forwarded to ``stage.record``;
            ``pre_step`` and ``post_step`` also run in the smoke branch
            so any IK or pose logic stays exercised.

    Returns:
        The GIF path written in the record branch, or ``None`` in the
        smoke branch.
    """
    if should_record(args):
        out_path = resolve_out_path(args, default_out)
        return stage.record(
            out_path,
            frames=int(args.frames),
            fps=int(fps),
            step_world=step_world,
            pre_step=pre_step,
            post_step=post_step,
            overlay=overlay,
        )

    # Smoke branch: step the stage without rendering or saving.
    frames = int(args.frames)
    dt = float(getattr(stage, "dt", 1.0 / 60.0))
    for f in range(frames):
        if pre_step is not None:
            pre_step(stage)
        if step_world:
            sb = getattr(stage, "softbody", None)
            fluid = getattr(stage, "fluid", None)
            dyn = getattr(stage, "dynamics", None)
            if sb is not None:
                from .softbody import step as softbody_step
                softbody_step(sb)
            if fluid is not None:
                from .fluid import pbf_step
                pbf_step(fluid)
            if dyn is not None:
                dyn.step(dt)
            # Fallback for stages that aren't studio.Stage: try .world.step
            if sb is None and fluid is None and dyn is None:
                world = getattr(stage, "world", None)
                if world is not None and hasattr(world, "step"):
                    world.step(dt)
        if post_step is not None:
            post_step(stage, f)
    return None
