"""Projectile-vs-armor penetration demo.

Three high-velocity steel projectiles fire horizontally at three armor
plates: ``glass``, ``iron``, and ``diamond``.  Each plate's per-cell
deformation simulator reacts according to its material:

  * **Glass**  — brittle, low tear strength → shatters into fragments.
  * **Iron**   — ductile → dents (plastic strain accumulates) but stays
    connected.
  * **Diamond** — extreme stiffness + tear strength → bounces the
    projectile off with negligible damage.

Run::

    python examples/physics_projectile_demo.py

Outputs (in ``examples/output/``):
  * ``physics_projectile_demo.gif`` — full run animation.
  * ``projectile_pre_impact.png``  — frame 20 (in flight).
  * ``projectile_impact.png``      — frame 60 (at peak contact).
  * ``projectile_post_impact.png`` — frame 120 (debris settled).

A ``run_demo()`` function is provided so the test suite can drive the
same scenario without spawning a subprocess.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image

from slappyengine.physics import (
    PhysicsWorld,
    PhysicsYaml,
    load_physics_config,
    make_circle_silhouette,
    make_rect_silhouette,
)
from slappyengine.physics.cc_label import connected_components
from slappyengine.physics.particles import ParticleSystem
from slappyengine.physics.particle_graph import ParticleGraph
from slappyengine.physics.post_process import default_post_process_chain
from slappyengine.physics.render import (
    PhysicsRenderer,
    PointLight,
    RenderConfig,
)


# ---------------------------------------------------------------------------
# Scenario constants — kept at module scope so tests can introspect them.
# ---------------------------------------------------------------------------

PLATE_MATERIALS: tuple[str, str, str] = ("glass", "iron", "diamond")
PLATE_Y_OFFSETS: tuple[float, float, float] = (-40.0, 20.0, 80.0)
PLATE_X: float = 50.0
PLATE_WIDTH: int = 80
PLATE_HEIGHT: int = 24

PROJECTILE_X: float = -260.0
PROJECTILE_DIAMETER: int = 12
PROJECTILE_VELOCITY: tuple[float, float] = (300.0, 0.0)
PROJECTILE_MATERIAL: str = "steel"

# Plate mass/inertia is auto-derived from the cell density × material rho.
# The demo wants "heavy armor" behaviour (plates recoil only a little) so
# we multiply both after creation; cell-level damage is unaffected.
PLATE_MASS_MULTIPLIER: float = 2.0

WORLD_BOUNDS: tuple[float, float, float, float] = (-300.0, -100.0, 300.0, 250.0)
FRAME_COUNT: int = 180

# Below this damage value diamond is considered "intact".
DIAMOND_DAMAGE_INTACT_THRESHOLD: float = 0.3

# Key frame indices we snapshot as PNG.
KEY_FRAMES: dict[str, int] = {
    "projectile_pre_impact": 20,
    "projectile_impact": 60,
    "projectile_post_impact": 120,
}


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class PlateResult:
    """Per-plate summary returned by :func:`run_demo`."""
    material: str
    impact_frame: int | None  # first frame a contact was registered
    impact_impulse_peak: float  # peak contact penetration depth observed
    max_damage: float
    max_tear: float
    fragment_count: int  # cc_label.connected_components on the cell field

    @property
    def shattered(self) -> bool:
        return self.fragment_count > 1


@dataclass
class DemoResult:
    """Aggregate result returned by :func:`run_demo`."""
    plates: list[PlateResult]
    gif_path: Path
    png_paths: dict[str, Path] = field(default_factory=dict)

    def by_material(self, name: str) -> PlateResult:
        for p in self.plates:
            if p.material == name:
                return p
        raise KeyError(f"No plate result for material '{name}'")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_world() -> tuple[PhysicsWorld, list, list]:
    """Build the PhysicsWorld + bodies for the demo.

    Returns ``(world, plates, projectiles)`` where ``plates`` and
    ``projectiles`` are parallel lists of :class:`PhysicsBody` -- same
    ordering as :data:`PLATE_MATERIALS`.
    """
    # Start from the on-disk config but override gravity → 0 so projectiles
    # fly straight regardless of distance.
    config: PhysicsYaml = load_physics_config()
    config.world.gravity = (0.0, 0.0)

    world = PhysicsWorld(config=config, world_bounds=WORLD_BOUNDS)

    plates = []
    projectiles = []
    for material, dy in zip(PLATE_MATERIALS, PLATE_Y_OFFSETS):
        plate = world.create_body(
            silhouette=make_rect_silhouette(PLATE_WIDTH, PLATE_HEIGHT),
            material=material,
            position=(PLATE_X, dy),
            velocity=(0.0, 0.0),
            fixed=False,
        )
        # Make plates "armor-heavy" so they recoil only slightly on impact
        # without being fully static (fixed=False is still required so the
        # cell field sees per-pixel motion).  We scale mass + inertia by a
        # large factor — the rigid recoil is reduced ∝ 1/mass, but cell
        # damage is still driven by the contact normal force.
        plate_hid = plate.root_hull_id
        world.hulls.mass[plate_hid] *= PLATE_MASS_MULTIPLIER
        world.hulls.inertia[plate_hid] *= PLATE_MASS_MULTIPLIER
        plates.append(plate)

        ball = world.create_body(
            silhouette=make_circle_silhouette(PROJECTILE_DIAMETER),
            material=PROJECTILE_MATERIAL,
            position=(PROJECTILE_X, dy),
            velocity=PROJECTILE_VELOCITY,
            fixed=False,
        )
        projectiles.append(ball)

    return world, plates, projectiles


def _build_renderer() -> PhysicsRenderer:
    cfg = RenderConfig(
        width=640,
        height=360,
        world_view=(WORLD_BOUNDS[0], WORLD_BOUNDS[1], WORLD_BOUNDS[2], WORLD_BOUNDS[3]),
        lights=[
            PointLight(position=(-150.0, -80.0), color=(255, 235, 200),
                       intensity=1.8, radius=400.0),
            PointLight(position=( 200.0,  20.0), color=(180, 200, 255),
                       intensity=1.2, radius=350.0),
        ],
        ambient_intensity=0.35,
        enable_normal_map=True,
        normal_curvature_bias=0.4,
    )
    return PhysicsRenderer(config=cfg)


def _fragment_count(body) -> int:
    """How many connected components does this body's cell field have now?"""
    cells = body.cells
    if cells is None:
        return 0
    density = cells[..., 9]
    bond_e = cells[..., 14]
    bond_s = cells[..., 15]
    _labels, n = connected_components(density, bond_e, bond_s)
    return int(n)


def _save_png(frame_rgba: np.ndarray, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame_rgba, mode="RGBA").save(path)
    return path


# ---------------------------------------------------------------------------
# Public entry-point used by both the CLI and the test suite.
# ---------------------------------------------------------------------------

def run_demo(
    output_dir: str | Path | None = None,
    frame_count: int = FRAME_COUNT,
    verbose: bool = True,
) -> DemoResult:
    """Run the projectile-vs-armor demo end-to-end.

    Parameters
    ----------
    output_dir:
        Directory to write GIF + PNGs into.  Defaults to
        ``<repo>/examples/output``.
    frame_count:
        Number of frames to simulate + render.  Default 180.
    verbose:
        Print the final summary report when ``True``.
    """
    out = Path(output_dir) if output_dir is not None else (
        Path(__file__).resolve().parent / "output"
    )
    out.mkdir(parents=True, exist_ok=True)

    world, plates, projectiles = _build_world()
    renderer = _build_renderer()
    particles = ParticleSystem(gravity=(0.0, 0.0), air_drag=0.9, max_particles=2048)
    # Layered, composable particle look: bright sparks + drifting smoke
    # on the iron plate, shards + glitter mist on the glass plate.  The
    # diamond plate gets the legacy material-driven emission only, so
    # the visual contrast between "rich" (graph) and "plain" (legacy)
    # is obvious in the demo.
    particle_graph = ParticleGraph()
    for em in ParticleGraph.preset_iron_impact():
        particle_graph.add(em)
    for em in ParticleGraph.preset_glass_shatter():
        particle_graph.add(em)
    post_chain = default_post_process_chain()

    # Per-plate trackers
    n = len(plates)
    impact_frame: list[int | None] = [None] * n
    impact_peak: list[float] = [0.0] * n
    max_damage: list[float] = [0.0] * n
    max_tear: list[float] = [0.0] * n

    plate_hids = [p.root_hull_id for p in plates]
    proj_hids = [b.root_hull_id for b in projectiles]
    pair_index = {(plate_hids[i], proj_hids[i]): i for i in range(n)} | \
                 {(proj_hids[i], plate_hids[i]): i for i in range(n)}

    frames: list[np.ndarray] = []
    png_paths: dict[str, Path] = {}
    dt = world.config.world.default_dt

    for frame_idx in range(frame_count):
        contacts = world.step()

        # Record contacts that involve a projectile vs its own plate.
        for c in contacts:
            if c.b < 0:
                continue  # wall contact
            idx = pair_index.get((c.a, c.b))
            if idx is None:
                continue
            if impact_frame[idx] is None:
                impact_frame[idx] = frame_idx
            if c.depth > impact_peak[idx]:
                impact_peak[idx] = float(c.depth)

        # Per-plate field maxima — updated every frame so we catch
        # the peaks even if they decay before we sample at the end.
        for i, plate in enumerate(plates):
            cells = plate.cells
            if cells is None:
                continue
            dmg = float(cells[..., 8].max())
            tr = float(cells[..., 11].max())
            if dmg > max_damage[i]:
                max_damage[i] = dmg
            if tr > max_tear[i]:
                max_tear[i] = tr

        # Visual: legacy material-driven emission for any contact (this
        # gives the diamond plate its default white shatter look), THEN
        # layer in the composable ParticleGraph so iron contacts get
        # sparks + smoke and glass contacts get shards + glitter.
        particles.emit_from_contacts(
            contacts,
            world=world,
            body_lookup=world._body_for_hull,
            intensity_scale=1.5,
        )
        particle_graph.emit_for_contact(
            particles,
            contacts,
            world=world,
            body_lookup=world._body_for_hull,
        )
        particles.step(dt)

        # Render → particles overlay → post-process bloom/tonemap.
        frame = renderer.render(world)
        particles.render(frame, world_view=renderer.config.world_view)
        frame = post_chain.apply(frame)
        frames.append(frame)

        # Stash PNGs at key frames.
        for name, key_idx in KEY_FRAMES.items():
            if frame_idx == key_idx:
                png_paths[name] = _save_png(frame, out / f"{name}.png")

    gif_path = out / "physics_projectile_demo.gif"
    renderer.save_gif(frames, gif_path, fps=30)

    # Final post-run fragmentation count (after debris has had a chance
    # to fully separate).
    fragments = [_fragment_count(plate) for plate in plates]

    plate_results = [
        PlateResult(
            material=PLATE_MATERIALS[i],
            impact_frame=impact_frame[i],
            impact_impulse_peak=impact_peak[i],
            max_damage=max_damage[i],
            max_tear=max_tear[i],
            fragment_count=fragments[i],
        )
        for i in range(n)
    ]

    result = DemoResult(plates=plate_results, gif_path=gif_path, png_paths=png_paths)

    if verbose:
        _print_report(result)

    return result


def _print_report(result: DemoResult) -> None:
    glass = result.by_material("glass")
    iron = result.by_material("iron")
    diamond = result.by_material("diamond")

    print()
    print("=" * 64)
    print(" Projectile-vs-armor demo report")
    print("=" * 64)
    print(f"Glass:   shattered into {glass.fragment_count} fragments "
          f"(max damage {glass.max_damage:.3f}, max tear {glass.max_tear:.3f}, "
          f"impact frame {glass.impact_frame}).")
    print(f"Iron:    dented (max damage {iron.max_damage:.3f}, "
          f"max tear {iron.max_tear:.3f}, fragments {iron.fragment_count}, "
          f"impact frame {iron.impact_frame}).")

    if diamond.max_damage < DIAMOND_DAMAGE_INTACT_THRESHOLD:
        verdict = (f"intact (max damage {diamond.max_damage:.3f} "
                   f"< threshold {DIAMOND_DAMAGE_INTACT_THRESHOLD}).")
    else:
        verdict = (f"DAMAGED (max damage {diamond.max_damage:.3f} "
                   f">= threshold {DIAMOND_DAMAGE_INTACT_THRESHOLD}).")
    print(f"Diamond: {verdict}")

    print()
    print(f"GIF:   {result.gif_path}")
    for name, p in result.png_paths.items():
        print(f"PNG:   {p}")
    print("=" * 64)


if __name__ == "__main__":
    run_demo()
