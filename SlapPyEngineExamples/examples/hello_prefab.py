"""SlapPyEngine - Hello Prefab

Minimal demo of :class:`slappyengine.prefabs.PrefabLibrary` (sprint Y3).

Spawns four baked prefabs — a wooden crate, a rubber ball, a windmill
cross, and a five-link iron chain — into a shared
:class:`slappyengine.dynamics.World`, then integrates for 120 fixed
timesteps at ``dt = 1/60``. Each frame is optionally rasterised to a
PIL image; the final frame is written to ``hello_prefab_final.png``.

The demo is intentionally headless — no dear-pygui viewport is spun
up. When invoked with ``--live`` the final PIL image is opened in the
platform image viewer via :meth:`PIL.Image.show` after the run finishes.

Run::

    PYTHONPATH=python python examples/hello_prefab.py
    PYTHONPATH=python python examples/hello_prefab.py --frames 60
    PYTHONPATH=python python examples/hello_prefab.py --live
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np

from slappyengine.dynamics import World
from slappyengine.prefabs import PrefabLibrary


# ── Demo parameters ─────────────────────────────────────────────────────────
GRAVITY: tuple[float, float] = (0.0, -9.81)
DEFAULT_DT: float = 1.0 / 60.0
DEFAULT_FRAMES: int = 120
SOLVER_ITERATIONS: int = 8
PROGRESS_EVERY: int = 20

# Spawn layout — 4 prefabs, spread across a 12-unit-wide view so nothing
# overlaps at t=0.
SPAWN_TABLE: tuple[tuple[str, tuple[float, float]], ...] = (
    ("crate",    (-4.0, 3.0)),
    ("ball",     (-1.5, 3.0)),
    ("windmill", ( 2.5, 3.0)),
    ("chain",    ( 4.5, 4.0)),
)

# Expected "entity" counts per prefab (validated by the tests). The
# convention is: rigid-single-shape prefabs (crate, ball) count as one
# entity, and per-link/per-node prefabs (chain, windmill) count each
# link / node as its own entity because that's how the editor palette
# and gameplay code think about them.
EXPECTED_ENTITY_COUNTS: dict[str, int] = {
    "crate":    1,   # one box body — single rigid entity
    "ball":     1,   # one circle body — single rigid entity
    "chain":    5,   # 5 chain links, each with its own node
    "windmill": 5,   # 1 hub + 4 arm tips
}
EXPECTED_ENTITY_COUNT: int = sum(EXPECTED_ENTITY_COUNTS.values())  # 12
# Raw node count = 4 (crate corners) + 1 (ball) + 5 (chain) + 5 (windmill).
EXPECTED_NODE_COUNT: int = 4 + 1 + 5 + 5  # = 15

# ── Render parameters ──────────────────────────────────────────────────────
RENDER_W: int = 640
RENDER_H: int = 480
VIEW_MIN: tuple[float, float] = (-7.0, -1.0)
VIEW_MAX: tuple[float, float] = ( 8.0, 6.0)
GROUND_Y: float = 0.0


# ────────────────────────────────────────────────────────────────────────────
# Simulation
# ────────────────────────────────────────────────────────────────────────────


def build_library(user_dir: Path | None = None) -> PrefabLibrary:
    """Return a :class:`PrefabLibrary` populated from the baked palette.

    A temporary user directory is used by default so the demo never
    touches ``~/.slappyengine/prefabs/`` on the developer's machine.
    """
    lib = PrefabLibrary()
    if user_dir is None:
        user_dir = Path(tempfile.mkdtemp(prefix="hello_prefab_"))
    lib.bake_defaults(user_dir=user_dir)
    # Load straight from the freshly-baked user directory so the demo
    # exercises the on-disk YAML round-trip end-to-end.
    lib.load_from_dir(user_dir)
    return lib


def build_world(
    library: PrefabLibrary | None = None,
) -> tuple[World, PrefabLibrary, dict[str, list]]:
    """Construct the world, spawn all four prefabs, return the wiring.

    Returns
    -------
    world:
        A :class:`World` with all four prefabs registered.
    library:
        The :class:`PrefabLibrary` used to spawn (either the caller-
        supplied one or a fresh library built via :func:`build_library`).
    bodies_by_name:
        ``{prefab_name: [Body, ...]}`` — the exact bodies each prefab
        appended to the world, so tests can drill into node ranges.
    """
    if library is None:
        library = build_library()

    world = World(gravity=GRAVITY)
    world.solver_iterations = SOLVER_ITERATIONS

    bodies_by_name: dict[str, list] = {}
    for name, pos in SPAWN_TABLE:
        prefab = library.get(name)
        if prefab is None:
            raise RuntimeError(
                f"hello_prefab: baked prefab {name!r} not found in library"
            )
        spawned = prefab.spawn(world, pos)
        bodies_by_name[name] = spawned
    return world, library, bodies_by_name


def _ground_clamp(world: World, ground_y: float = GROUND_Y) -> None:
    """In-place: lift any node that dropped below *ground_y* back to it."""
    ys = world.positions[:, 1]
    below = ys < ground_y
    if np.any(below):
        world.positions[below, 1] = ground_y
        world.velocities[below, 1] = 0.0


def step_world(
    world: World,
    frames: int,
    dt: float = DEFAULT_DT,
    *,
    progress_every: int = PROGRESS_EVERY,
    verbose: bool = True,
) -> None:
    """Integrate *world* for *frames* ticks with a ground clamp.

    Prints ``[STEP i/frames]`` every *progress_every* frames (and at the
    final frame) when *verbose* is True.
    """
    for f in range(frames):
        world.step(dt)
        _ground_clamp(world)
        if verbose and (f % progress_every == 0 or f == frames - 1):
            print(f"[STEP {f}/{frames}]")


# ────────────────────────────────────────────────────────────────────────────
# Pure-PIL renderer
# ────────────────────────────────────────────────────────────────────────────


def _world_to_pixel(p) -> tuple[int, int]:
    vx0, vy0 = VIEW_MIN
    vx1, vy1 = VIEW_MAX
    u = (float(p[0]) - vx0) / (vx1 - vx0)
    v = (float(p[1]) - vy0) / (vy1 - vy0)
    px = int(round(u * (RENDER_W - 1)))
    py = int(round((1.0 - v) * (RENDER_H - 1)))
    return px, py


def _render_frame_pil(world: World, bodies_by_name: dict[str, list]):
    """Rasterise the scene onto a PIL image (or a stub when PIL is missing)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # pragma: no cover - PIL is a hard dep in this repo
        return None

    img = Image.new("RGBA", (RENDER_W, RENDER_H), (14, 16, 24, 255))
    draw = ImageDraw.Draw(img)

    # Ground line.
    fy0 = _world_to_pixel([VIEW_MIN[0], GROUND_Y])[1]
    draw.line([(0, fy0), (RENDER_W - 1, fy0)], fill=(70, 80, 60, 255), width=2)

    palette = {
        "crate":    (200, 140,  60, 255),
        "ball":     ( 90, 200, 220, 255),
        "windmill": (220, 200,  90, 255),
        "chain":    (180, 180, 210, 255),
    }
    for name, bodies in bodies_by_name.items():
        colour = palette.get(name, (240, 240, 240, 255))
        for body in bodies:
            idxs = list(body.node_indices)
            for i in idxs:
                x, y = _world_to_pixel(world.positions[i])
                draw.ellipse(
                    [(x - 4, y - 4), (x + 4, y + 4)],
                    fill=colour, outline=colour,
                )
            # Connect consecutive nodes for chain / composite topology.
            if body.kind in ("chain", "box"):
                for a, b in zip(idxs[:-1], idxs[1:]):
                    p0 = _world_to_pixel(world.positions[a])
                    p1 = _world_to_pixel(world.positions[b])
                    draw.line([p0, p1], fill=colour, width=2)
    return img


def _render_frame_stub(world: World) -> np.ndarray:
    """Fallback rasterisation when PIL is unavailable: a flat RGBA array."""
    arr = np.zeros((RENDER_H, RENDER_W, 4), dtype=np.uint8)
    arr[..., 3] = 255  # opaque
    return arr


def render_final_png(
    world: World,
    bodies_by_name: dict[str, list],
    out_path: Path,
) -> Path:
    """Write the final-frame render to *out_path* (PNG)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img = _render_frame_pil(world, bodies_by_name)
    if img is None:
        # PIL missing — write the stub as raw bytes so callers still see a file.
        arr = _render_frame_stub(world)
        out_path.write_bytes(arr.tobytes())
        return out_path
    img.save(out_path)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Diagnostics
# ────────────────────────────────────────────────────────────────────────────


def _entity_count(bodies_by_name: dict[str, list]) -> int:
    """Sum the per-prefab entity count.

    Rigid single-shape prefabs (kind ``circle`` / ``box`` / ``point``)
    contribute one entity. Multi-node prefabs (``chain`` / ``composite``
    / ``rope``) contribute one entity per node so gameplay code and
    editor spawn cards can index into individual links.
    """
    total = 0
    for bodies in bodies_by_name.values():
        for body in bodies:
            if body.kind in ("chain", "composite", "rope"):
                total += int(body.node_count)
            else:
                total += 1
    return total


def summarise(
    world: World,
    bodies_by_name: dict[str, list],
    frames: int,
) -> dict:
    """Return a compact summary dict for tests / stdout."""
    total_bodies = sum(len(bs) for bs in bodies_by_name.values())
    total_nodes = int(world.positions.shape[0])
    return {
        "frames": frames,
        "prefabs_spawned": len(bodies_by_name),
        "total_bodies": total_bodies,
        "total_entities": _entity_count(bodies_by_name),
        "total_nodes": total_nodes,
        "min_y": float(world.positions[:, 1].min()),
        "max_speed": float(np.linalg.norm(world.velocities, axis=1).max()),
    }


def print_summary(summary: dict) -> None:
    print("hello_prefab summary")
    print(f"  frames             : {summary['frames']}")
    print(f"  prefabs spawned    : {summary['prefabs_spawned']}")
    print(f"  total bodies       : {summary['total_bodies']}")
    print(f"  total entities     : {summary['total_entities']}")
    print(f"  total nodes        : {summary['total_nodes']}")
    print(f"  min y (post-step)  : {summary['min_y']:.4f}")
    print(f"  max node speed     : {summary['max_speed']:.4f}")


# ────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ────────────────────────────────────────────────────────────────────────────


def _default_png_path() -> Path:
    return Path(__file__).resolve().parent / "output" / "prefab" / "hello_prefab_final.png"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hello Prefab - SlapPyEngine demo")
    parser.add_argument(
        "--frames", type=int, default=DEFAULT_FRAMES,
        help=f"number of dt=1/60 steps to integrate (default: {DEFAULT_FRAMES})",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="output PNG path (defaults to examples/output/prefab/hello_prefab_final.png)",
    )
    parser.add_argument(
        "--live", action="store_true",
        help="pop up a PIL window with the final frame after the run",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="suppress [STEP] progress prints",
    )
    return parser.parse_args(argv)


def main(
    frames: int = DEFAULT_FRAMES,
    out: Path | str | None = None,
    *,
    live: bool = False,
    verbose: bool = True,
    library: PrefabLibrary | None = None,
) -> dict:
    """Run the demo and return the summary dict for tests."""
    world, library, bodies_by_name = build_world(library=library)
    step_world(world, frames, DEFAULT_DT, verbose=verbose)
    summary = summarise(world, bodies_by_name, frames)
    print_summary(summary)

    out_path = Path(out) if out is not None else _default_png_path()
    written = render_final_png(world, bodies_by_name, out_path)
    summary["png_path"] = str(written)
    print(f"  png written to     : {written}")

    if live:
        img = _render_frame_pil(world, bodies_by_name)
        if img is not None:
            try:
                img.show(title="hello_prefab")
            except Exception as exc:  # pragma: no cover - platform-dependent
                print(f"  live viewer failed: {exc}")
    return summary


def _cli(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        main(
            frames=args.frames,
            out=args.out,
            live=args.live,
            verbose=not args.quiet,
        )
    except Exception as exc:  # pragma: no cover - defensive CLI guard
        print(f"hello_prefab: error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
