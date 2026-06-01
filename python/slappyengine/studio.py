"""High-level scenario helpers — wrap world setup, rendering, GIF loops.

These helpers exist to reduce demo boilerplate without locking you in.
Every helper is additive sugar over the existing public surface — you can
still build worlds directly (``SoftBodyWorld()`` / ``FluidWorld()``), call
``step()`` / ``pbf_step()`` in a custom loop, and bring your own renderer.

The intent: a working demo in ~15 lines instead of ~50.

Typical use::

    from slappyengine.studio import softbody_stage, record
    from slappyengine.softbody import make_lattice_body

    stage = softbody_stage(view_box=(-2, -1, 2, 5))
    cube = make_lattice_body(stage.world, "stone",
                             width_cells=5, height_cells=5, cell_size=0.10,
                             position=(-0.25, 1.8))
    cube.kick(stage.world, vy=8.0, twist=-0.6)
    record(stage, frames=180, output="examples/output/glass.gif")

For a fluid + softbody scene::

    from slappyengine.studio import fluid_with_softbody_stage, record
    from slappyengine.fluid import apply_fluid_buoyancy

    stage = fluid_with_softbody_stage(view_box=(-2, 2, 2, 6),
                                      pool=dict(nx=28, ny=22, spacing=0.06,
                                                origin=(-0.84, 2.7)))
    block = make_lattice_body(stage.softbody, "wood",
                              width_cells=4, height_cells=2, cell_size=0.10,
                              position=(-0.5, stage.surface_y - 0.6))
    record(stage, frames=200, output="examples/output/buoyancy.gif",
           pre_step=lambda s: apply_fluid_buoyancy(s.fluid, s.softbody, s.dt,
                                                   body_meta=block,
                                                   surface_y=s.surface_y))
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from .media import save_frames


ViewBox = tuple[float, float, float, float]
Overlay = Callable[[Image.Image, ViewBox], Image.Image]


def output_path(name: str, demo_file: str | None = None,
                *, subdir: str | None = None, ext: str = "gif") -> Path:
    """Resolve a standard ``<root>/output/<subdir>/<name>.<ext>`` path.

    If ``demo_file`` is given (typically ``__file__``), the path is anchored
    at that file's parent directory; otherwise the current working directory
    is used. Creates parent dirs.
    """
    if demo_file is not None:
        root = Path(demo_file).resolve().parent
    else:
        root = Path.cwd()
    leaf = name if name.endswith(f".{ext}") else f"{name}.{ext}"
    parts = ["output"]
    if subdir:
        parts.append(subdir)
    out = root.joinpath(*parts) / leaf
    out.parent.mkdir(parents=True, exist_ok=True)
    return out


@dataclass
class Stage:
    """Bundle of world(s) + renderer + view + sim-step convenience.

    Construct via ``softbody_stage(...)``, ``fluid_stage(...)``,
    ``humanoid_stage(...)``, ``fluid_with_softbody_stage(...)`` or
    ``dynamics_stage(...)``. Each helper takes sensible defaults; override
    anything via kwargs.

    Attributes:
        world: primary world for stepping (softbody, fluid, or dynamics)
        softbody: optional softbody world (also stored in ``world`` when
            it's the only world)
        fluid: optional fluid world
        dynamics: optional :class:`slappyengine.dynamics.World` instance
        renderer: FluidRenderer / SoftBodyRenderer / callable render_fn
        view_box: (wx0, wy0, wx1, wy1) for the renderer
        dt: per-frame timestep (s); read by ``record``
        surface_y: water surface y if a fluid pool was pre-settled
        body_metas: handles for any bodies the Stage helper auto-spawned
        render_fn: optional callable ``(stage) -> PIL.Image`` used by
            ``record`` when no softbody/fluid renderer is present (set by
            :func:`dynamics_stage`).
    """

    world: Any = None
    softbody: Any = None
    fluid: Any = None
    dynamics: Any = None
    renderer: Any = None
    view_box: ViewBox = (-2.0, -1.0, 2.0, 5.0)
    dt: float = 1.0 / 60.0
    surface_y: float | None = None
    body_metas: dict[str, Any] = field(default_factory=dict)
    render_fn: Callable[["Stage"], Image.Image] | None = None

    def record(self, out_path: Path | str, frames: int = 120,
               *, fps: int = 30,
               render_fn: Callable[["Stage"], Image.Image] | None = None,
               step_world: bool = True,
               pre_step: Callable[["Stage"], None] | None = None,
               post_step: Callable[["Stage", int], None] | None = None,
               overlay: Overlay | None = None) -> Path:
        """Method-form of :func:`record`.

        Delegates to the module-level :func:`record` with the stage's own
        defaults. ``render_fn`` overrides any callable bound on the stage.
        """
        if render_fn is not None:
            previous = self.render_fn
            self.render_fn = render_fn
            try:
                return record(self, frames=frames, output=out_path, fps=fps,
                              step_world=step_world,
                              pre_step=pre_step, post_step=post_step,
                              overlay=overlay)
            finally:
                self.render_fn = previous
        return record(self, frames=frames, output=out_path, fps=fps,
                      step_world=step_world,
                      pre_step=pre_step, post_step=post_step, overlay=overlay)


def softbody_stage(*,
                   view_box: ViewBox = (-2.0, -1.0, 2.0, 5.0),
                   width: int = 480, height: int = 320,
                   floor_y: float | None = None,
                   gravity: tuple[float, float] | None = None,
                   contact_enabled: bool | None = None,
                   floor_friction: float | None = None,
                   **renderer_overrides: Any) -> Stage:
    """Build a softbody-only stage with a SoftBodyRenderer."""
    from .softbody import (
        SoftBodyRenderConfig, SoftBodyRenderer, SoftBodyWorld,
    )

    world = SoftBodyWorld()
    if floor_y is not None:
        world.config["floor_y"] = float(floor_y)
    if gravity is not None:
        world.config["gravity"] = list(gravity)
    if contact_enabled is not None:
        world.config["contact"]["enabled"] = bool(contact_enabled)
    if floor_friction is not None:
        world.config["floor_friction"] = float(floor_friction)

    cfg_dict = {"width": int(width), "height": int(height)}
    cfg_dict.update(renderer_overrides)
    renderer = SoftBodyRenderer(config=SoftBodyRenderConfig.from_yaml(cfg_dict))

    return Stage(world=world, softbody=world,
                  renderer=renderer, view_box=view_box,
                  dt=float(world.config["default_dt"]))


def fluid_stage(*,
                view_box: ViewBox = (-2.0, 2.0, 2.0, 6.0),
                width: int = 480, height: int = 320,
                floor_y: float | None = None,
                walls: tuple[float, float] | None = None,
                pool: dict[str, Any] | None = None,
                settle_steps: int = 0,
                **renderer_overrides: Any) -> Stage:
    """Build a fluid-only stage with a FluidRenderer.

    ``pool`` is forwarded to ``FluidWorld.add_block_of_particles`` —
    e.g. ``pool=dict(material="water", nx=28, ny=22, spacing=0.06,
    origin=(-0.84, 2.7), jitter=0.04)``.

    If ``settle_steps > 0``, the fluid is pre-stepped that many frames
    and ``stage.surface_y`` is set to the resulting top-of-pool y.
    """
    from .fluid import (
        FluidRenderConfig, FluidRenderer, FluidWorld, pbf_step,
    )

    fluid = FluidWorld()
    if floor_y is not None:
        fluid.config["floor_y"] = float(floor_y)
    if walls is not None:
        fluid.config["wall_x_min"] = float(walls[0])
        fluid.config["wall_x_max"] = float(walls[1])
    if pool is not None:
        pool_kwargs = dict(pool)
        material = pool_kwargs.pop("material", "water")
        fluid.add_block_of_particles(material, **pool_kwargs)

    surface_y: float | None = None
    for _ in range(int(settle_steps)):
        pbf_step(fluid)
    if settle_steps > 0 and fluid.particles.count > 0:
        surface_y = float(fluid.particles.pos[:, 1].min())

    cfg_dict = {"width": int(width), "height": int(height)}
    cfg_dict.update(renderer_overrides)
    renderer = FluidRenderer(config=FluidRenderConfig.from_yaml(cfg_dict))

    return Stage(world=fluid, fluid=fluid,
                  renderer=renderer, view_box=view_box,
                  dt=float(fluid.config["default_dt"]),
                  surface_y=surface_y)


def humanoid_stage(*,
                   view_box: ViewBox = (-1.5, 0.0, 1.5, 4.0),
                   width: int = 360, height: int = 480,
                   gravity: tuple[float, float] = (0.0, 0.0),
                   contact_enabled: bool = False,
                   floor_y_far_below: float = 100.0,
                   debug_show_beams: bool = True,
                   debug_show_nodes: bool = True,
                   **renderer_overrides: Any) -> Stage:
    """Build a softbody stage tuned for humanoid / kinematic IK demos.

    Defaults the world so the user controls poses (no gravity, contact off,
    floor effectively disabled). Use ``make_humanoid(stage.world, ...)`` to
    add the skeleton, then ``place_feet_on_terrain`` or ``wrap_in_flesh``
    to extend it.

    Wireframe (beams + nodes) is ON by default because humanoid skeletons
    have no texture topology registered — they would render as an empty
    background otherwise. Override either flag (or set
    ``texture_deform=True``) to swap in textured rendering.
    """
    overrides = dict(renderer_overrides)
    overrides.setdefault("debug_show_beams", debug_show_beams)
    overrides.setdefault("debug_show_nodes", debug_show_nodes)
    return softbody_stage(
        view_box=view_box, width=width, height=height,
        floor_y=floor_y_far_below,
        gravity=gravity,
        contact_enabled=contact_enabled,
        **overrides,
    )


def fluid_with_softbody_stage(*,
                              view_box: ViewBox = (-2.0, 2.0, 2.0, 6.0),
                              width: int = 480, height: int = 320,
                              floor_y: float = 6.0,
                              walls: tuple[float, float] = (-1.8, 1.8),
                              pool: dict[str, Any] | None = None,
                              settle_steps: int = 140,
                              fluid_contact: bool = False,
                              sb_contact: bool = False,
                              **renderer_overrides: Any) -> Stage:
    """Composite scene: fluid + softbody, fluid renderer (draws both).

    Defaults match the buoyancy demo: deep pool, walls in, fluid-softbody
    coupling DISABLED (use ``apply_fluid_buoyancy`` for explicit
    Archimedes). ``pool`` defaults to a water block sized for the default
    view_box.
    """
    from .fluid import (
        FluidRenderConfig, FluidRenderer, FluidWorld, pbf_step,
    )
    from .softbody import SoftBodyWorld

    fluid = FluidWorld()
    fluid.config["floor_y"] = float(floor_y)
    fluid.config["wall_x_min"] = float(walls[0])
    fluid.config["wall_x_max"] = float(walls[1])
    fluid.config["contact"]["enabled"] = bool(fluid_contact)

    if pool is None:
        pool = dict(material="water", nx=28, ny=22, spacing=0.06,
                    origin=(-0.84, 2.7), jitter=0.04)
    pool_kwargs = dict(pool)
    material = pool_kwargs.pop("material", "water")
    fluid.add_block_of_particles(material, **pool_kwargs)

    for _ in range(int(settle_steps)):
        pbf_step(fluid)
    surface_y = (float(fluid.particles.pos[:, 1].min())
                 if fluid.particles.count > 0 else None)

    sb = SoftBodyWorld()
    sb.config["floor_y"] = float(floor_y)
    sb.config["contact"]["enabled"] = bool(sb_contact)

    cfg_dict = {"width": int(width), "height": int(height)}
    cfg_dict.update(renderer_overrides)
    renderer = FluidRenderer(config=FluidRenderConfig.from_yaml(cfg_dict))

    return Stage(world=fluid, fluid=fluid, softbody=sb,
                  renderer=renderer, view_box=view_box,
                  dt=float(sb.config["default_dt"]),
                  surface_y=surface_y)


def record(stage: Stage, frames: int = 180,
           output: Path | str | None = None,
           *, fps: int = 30,
           step_world: bool = True,
           pre_step: Callable[[Stage], None] | None = None,
           post_step: Callable[[Stage, int], None] | None = None,
           overlay: Overlay | None = None) -> Path:
    """Run the sim loop ``frames`` times, render each frame, save as GIF.

    Steps the world(s) the stage carries (softbody first, then fluid, then
    dynamics if present). Captures each frame via the stage's renderer in
    ``view_box``. ``pre_step(stage)`` runs before the step (apply forces, IK,
    etc); ``post_step(stage, frame_idx)`` runs after. ``overlay`` receives the
    PIL image and view_box and returns a possibly modified image (terrain
    line, HUD overlay, etc).

    Set ``step_world=False`` for static / pose-only demos where the user
    drives every frame manually via ``pre_step`` and ``post_step`` (e.g.
    the IK-terrain demo where the humanoid is re-IK'd each frame, and the
    standing-pose demo which captures the same frame N times).

    When the stage was built by :func:`dynamics_stage`, ``stage.render_fn``
    produces each frame directly via PIL (no GPU renderer needed).

    Returns the output GIF path.
    """
    if output is None:
        out_path = Path("output.gif")
    else:
        out_path = Path(output)
        out_path.parent.mkdir(parents=True, exist_ok=True)

    pil_frames: list[Image.Image] = []
    for f in range(int(frames)):
        if pre_step is not None:
            pre_step(stage)
        if step_world:
            if stage.softbody is not None:
                from .softbody import step as softbody_step
                softbody_step(stage.softbody)
            if stage.fluid is not None:
                from .fluid import pbf_step
                pbf_step(stage.fluid)
            if stage.dynamics is not None:
                stage.dynamics.step(stage.dt)
        if post_step is not None:
            post_step(stage, f)
        # Render: prefer a callable render_fn (dynamics_stage path), then
        # fall back to the fluid / softbody numpy renderers.
        if stage.render_fn is not None:
            img = stage.render_fn(stage)
            if img.mode != "RGB":
                img = img.convert("RGB")
        elif stage.fluid is not None:
            arr = stage.renderer.render(stage.fluid, view_box=stage.view_box,
                                         softbody=stage.softbody)
            img = Image.fromarray(arr, mode="RGBA").convert("RGB")
        else:
            arr = stage.renderer.render(stage.softbody, view_box=stage.view_box)
            img = Image.fromarray(arr, mode="RGBA").convert("RGB")
        if overlay is not None:
            img = overlay(img, stage.view_box)
        pil_frames.append(img)

    save_frames(pil_frames, out_path, fps=int(fps))
    return out_path


def _default_dynamics_render(stage: Stage) -> Image.Image:
    """Default PIL renderer for :func:`dynamics_stage` frames.

    Draws every distance / hinge / spring joint as a line, every node as a
    filled disk, and the floor (``stage.body_metas['floor_y']``, if set) as
    a horizontal line. Uses ``stage.view_box`` for world->pixel mapping and
    pulls the canvas size from ``stage.body_metas['width'/'height']``
    (default 480x320).
    """
    from PIL import ImageDraw

    world = stage.dynamics
    if world is None:
        raise ValueError("dynamics_stage render_fn: stage.dynamics is None")

    meta = stage.body_metas
    width = int(meta.get("width", 480))
    height = int(meta.get("height", 320))
    bg = tuple(meta.get("bg", (12, 14, 22)))
    line_color = tuple(meta.get("line_color", (210, 220, 235)))
    node_color = tuple(meta.get("node_color", (255, 200, 120)))
    pinned_color = tuple(meta.get("pinned_color", (255, 110, 110)))
    floor_color = tuple(meta.get("floor_color", (80, 100, 60)))
    line_width = int(meta.get("line_width", 2))
    node_radius = int(meta.get("node_radius", 4))

    wx0, wy0, wx1, wy1 = stage.view_box
    if wx1 == wx0 or wy1 == wy0:
        raise ValueError(f"dynamics_stage: degenerate view_box {stage.view_box!r}")

    def to_px(x: float, y: float) -> tuple[int, int]:
        u = (float(x) - wx0) / (wx1 - wx0)
        v = (float(y) - wy0) / (wy1 - wy0)
        # Flip Y so positive-y goes up on screen (matches hello_rope /
        # hello_ragdoll conventions).
        return (int(round(u * (width - 1))),
                int(round((1.0 - v) * (height - 1))))

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)

    floor_y = meta.get("floor_y")
    if floor_y is not None:
        _, fy = to_px(0.0, float(floor_y))
        draw.line([(0, fy), (width - 1, fy)], fill=floor_color, width=2)

    positions = world.positions
    inv_masses = world.inv_masses
    if positions.shape[0] > 0:
        for joint in world.joints:
            a = int(getattr(joint, "node_a", -1))
            b = int(getattr(joint, "node_b", -1))
            if a < 0 or b < 0 or a >= positions.shape[0] or b >= positions.shape[0]:
                continue
            pa = to_px(positions[a, 0], positions[a, 1])
            pb = to_px(positions[b, 0], positions[b, 1])
            draw.line([pa, pb], fill=line_color, width=line_width)
        for i in range(positions.shape[0]):
            x, y = to_px(positions[i, 0], positions[i, 1])
            color = pinned_color if inv_masses[i] == 0.0 else node_color
            draw.ellipse(
                [(x - node_radius, y - node_radius),
                 (x + node_radius, y + node_radius)],
                fill=color,
            )

    return img


def dynamics_stage(world: Any | None = None, *,
                   gravity: tuple[float, float] = (0.0, -9.81),
                   solver_iterations: int | None = None,
                   view_box: ViewBox = (-3.0, -3.0, 3.0, 3.0),
                   width: int = 480, height: int = 320,
                   floor_y: float | None = None,
                   dt: float | None = None,
                   render_fn: Callable[[Stage], Image.Image] | None = None,
                   **render_overrides: Any) -> Stage:
    """Build a stage around a :class:`slappyengine.dynamics.World`.

    The dynamics ``World`` is the substrate for ropes, ragdolls, springs,
    motors, and IK chains. Unlike the softbody / fluid renderers, dynamics
    has no shipped GPU rasteriser — this helper wires in a pure-PIL
    fallback that draws every joint as a line and every node as a disk, so
    a one-line ``stage.record(...)`` produces a meaningful GIF.

    Parameters
    ----------
    world:
        An existing :class:`dynamics.World`. If ``None``, a fresh one is
        constructed with ``gravity`` / ``solver_iterations`` applied.
    gravity, solver_iterations:
        Applied to the world only when one is created here. Ignored when
        the caller passes a ``world``.
    view_box, width, height:
        Camera + canvas. Floor (if given) is drawn at ``floor_y`` world-y.
    floor_y:
        Stored on ``stage.body_metas`` so the default renderer paints a
        ground line. Does not affect physics.
    dt:
        Frame timestep. Defaults to ``1/60``.
    render_fn:
        Override the default PIL renderer. Receives the stage, returns a
        PIL image of size ``(width, height)``.
    render_overrides:
        Extra keys merged into ``stage.body_metas`` (consumed by the
        default renderer): ``bg``, ``line_color``, ``node_color``,
        ``pinned_color``, ``floor_color``, ``line_width``, ``node_radius``.

    Returns
    -------
    Stage
        With ``stage.dynamics`` / ``stage.world`` pointing at the World
        and ``stage.render_fn`` ready for ``stage.record(...)``.
    """
    from .dynamics import World

    if world is None:
        world = World(gravity=gravity)
        if solver_iterations is not None:
            world.solver_iterations = int(solver_iterations)

    meta: dict[str, Any] = {"width": int(width), "height": int(height)}
    if floor_y is not None:
        meta["floor_y"] = float(floor_y)
    for key in ("bg", "line_color", "node_color", "pinned_color",
                "floor_color", "line_width", "node_radius"):
        if key in render_overrides:
            meta[key] = render_overrides[key]

    return Stage(
        world=world,
        dynamics=world,
        renderer=None,
        view_box=view_box,
        dt=float(dt) if dt is not None else 1.0 / 60.0,
        body_metas=meta,
        render_fn=render_fn if render_fn is not None else _default_dynamics_render,
    )


def terrain_overlay(terrain_fn: Callable[[float], float],
                    *, color: tuple[int, int, int] = (80, 100, 60),
                    width_px: int = 3,
                    samples: int = 240) -> Overlay:
    """Build an overlay that paints a 1D terrain line over each frame.

    ``terrain_fn(x) -> y`` follows the engine convention (positive y = down).
    Use with ``record(stage, ..., overlay=terrain_overlay(my_terrain))``.
    """
    import numpy as np
    from PIL import ImageDraw

    def _overlay(img: Image.Image, view_box: ViewBox) -> Image.Image:
        wx0, wy0, wx1, wy1 = view_box
        W, H = img.size
        draw = ImageDraw.Draw(img)
        xs = np.linspace(wx0, wx1, int(samples))
        pts: list[tuple[float, float]] = []
        for x in xs:
            y = float(terrain_fn(float(x)))
            sx = (float(x) - wx0) / (wx1 - wx0) * W
            sy = (y - wy0) / (wy1 - wy0) * H
            pts.append((sx, sy))
        draw.line(pts, fill=color, width=int(width_px))
        return img

    return _overlay


def kick(world, node_slice: tuple[int, int], vx: float = 0.0, vy: float = 0.0,
         *, twist: float = 0.0) -> None:
    """Apply a uniform velocity (+ optional twist) to a node range.

    ``twist`` adds a per-node x-velocity proportional to (x - centroid_x) so
    the body picks up spin around its vertical axis. Useful for fracture
    demos where a perfectly flat impact reads as artificial.
    """
    ns, ne = node_slice
    if ne <= ns:
        return
    world.nodes.vel[ns:ne, 0] = float(vx)
    world.nodes.vel[ns:ne, 1] = float(vy)
    if twist:
        cx = float(world.nodes.pos[ns:ne, 0].mean())
        world.nodes.vel[ns:ne, 0] += (world.nodes.pos[ns:ne, 0] - cx) * float(twist)


def anchor(world, node_slice: tuple[int, int]) -> None:
    """Pin every node in the slice (fixed=True, inv_mass=0). Idempotent."""
    ns, ne = node_slice
    if ne <= ns:
        return
    world.nodes.fixed[ns:ne] = True
    world.nodes.inv_mass[ns:ne] = 0.0


def centroid(world, node_slice: tuple[int, int]) -> tuple[float, float]:
    """Geometric center of the nodes in the slice."""
    ns, ne = node_slice
    if ne <= ns:
        return (0.0, 0.0)
    cx = float(world.nodes.pos[ns:ne, 0].mean())
    cy = float(world.nodes.pos[ns:ne, 1].mean())
    return (cx, cy)


def translate(world, node_slice: tuple[int, int],
              dx: float, dy: float) -> None:
    """Shift every node in the slice by (dx, dy). Also shifts prev_pos so the
    XPBD integrator doesn't see a fictitious velocity from the displacement.
    """
    ns, ne = node_slice
    if ne <= ns:
        return
    world.nodes.pos[ns:ne, 0] += float(dx)
    world.nodes.pos[ns:ne, 1] += float(dy)
    world.nodes.prev_pos[ns:ne, 0] += float(dx)
    world.nodes.prev_pos[ns:ne, 1] += float(dy)


__all__ = [
    "Stage",
    "anchor",
    "centroid",
    "dynamics_stage",
    "fluid_stage",
    "fluid_with_softbody_stage",
    "humanoid_stage",
    "kick",
    "output_path",
    "record",
    "softbody_stage",
    "terrain_overlay",
    "translate",
]
