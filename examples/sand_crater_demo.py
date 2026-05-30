"""Crater explosion demo — Worms-style, preset-driven.

Usage:
    python examples/sand_crater_demo.py              # sand (default)
    python examples/sand_crater_demo.py --preset mud
    python examples/sand_crater_demo.py --all        # writes one gif per preset
    python examples/sand_crater_demo.py --preset sloppy --frames 80

Built-in presets (defined in :mod:`slappyengine.physics.splatter_presets`):

* **sand**    — Worms-classic, ±45° cone, light friction
* **mud**     — sticky, narrow cone, big splats
* **sloppy**  — wet mud, very narrow cone, sticks instantly, huge splat
* **rock**    — chunky, low friction (rocks roll), grey palette
* **snow**    — wide cone, slow gravity, drifty settle, white palette

Per-frame loop:
  *  0-9   : flat ground, idle
  * 10     : explosion — carves a crater + spawns grains+chunks within
             the preset's cone, palettes, speed range
  * 11+    : particles arc; landing -> splat for chunks, single-bump for
             grains; friction slides them across the surface; settle.

Output:
    examples/output/particles/sand_crater[_<preset>].gif
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image

from slappyengine.physics.baked_terrain import (
    RegionGrid,
    bake_settled_particles,
)
from slappyengine.physics.splatter_presets import (
    PRESETS,
    SplatterPreset,
    get as get_preset,
)


W, H = 640, 360
GROUND_Y = 280
N_COLUMNS = W
BLAST_X = W // 2
BLAST_FRAME = 10
CRATER_RADIUS = 60
CRATER_DEPTH = 28


def _bg_for_preset(preset: SplatterPreset) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Sky-gradient endpoints chosen so the splatter palette pops."""
    if preset.name == "snow":
        return ((30, 38, 58), (170, 184, 210))    # blue → pale
    if preset.name in ("mud", "sloppy"):
        return ((18, 14, 8), (40, 30, 18))         # dark earthy
    if preset.name == "rock":
        return ((8, 10, 18), (30, 36, 50))         # cool grey
    return ((10, 14, 28), (40, 56, 92))            # sand default


def _ground_for_preset(preset: SplatterPreset) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Ground surface + sub-ground colours."""
    if preset.name == "snow":
        return ((232, 240, 250), (130, 150, 175))
    if preset.name in ("mud", "sloppy"):
        return ((90, 64, 32), (40, 28, 14))
    if preset.name == "rock":
        return ((130, 124, 116), (60, 56, 50))
    return ((200, 162, 90), (60, 44, 28))


def run_preset(preset: SplatterPreset, frames: int = 130) -> Path:
    rng = np.random.default_rng(2026)
    max_angle = preset.max_blast_angle_rad
    N = preset.n_particles

    # Per-pixel collision: bake_layer (H, W, 4) is the world's static
    # solid mask. alpha=255 means solid, alpha=0 means empty. No
    # heightmap — particles query the pixel they're about to enter.
    # This supports overhangs/caves naturally.
    bake_layer = np.zeros((H, W, 4), dtype=np.uint8)

    sky_top_pre, sky_bot_pre = _bg_for_preset(preset)
    ground_top_pre, ground_sub_pre = _ground_for_preset(preset)

    # Fill ground row-by-row: top row gets ground_top, rest gets sub.
    bake_layer[GROUND_Y, :, :3] = ground_top_pre
    bake_layer[GROUND_Y, :, 3] = 255
    bake_layer[GROUND_Y + 1: H, :, :3] = ground_sub_pre
    bake_layer[GROUND_Y + 1: H, :, 3] = 255

    region_grid = RegionGrid(width=W, height=H, cell_size=64)

    pos = np.zeros((N, 2), dtype=np.float32)
    vel = np.zeros((N, 2), dtype=np.float32)
    landed = np.zeros(N, dtype=bool)
    settled = np.zeros(N, dtype=bool)
    is_chunk = np.zeros(N, dtype=bool)
    radius = np.zeros(N, dtype=np.float32)
    colour = np.zeros((N, 3), dtype=np.uint8)
    bake_flag = np.zeros(N, dtype=bool)

    sky_top, sky_bot = _bg_for_preset(preset)
    grain_pal = np.asarray(preset.grain_palette, dtype=np.uint8)
    chunk_pal = np.asarray(preset.chunk_palette, dtype=np.uint8)

    def sky_gradient(arr: np.ndarray) -> None:
        for y in range(H):
            t = y / H
            arr[y, :, 0] = int(sky_top[0] + (sky_bot[0] - sky_top[0]) * t)
            arr[y, :, 1] = int(sky_top[1] + (sky_bot[1] - sky_top[1]) * t)
            arr[y, :, 2] = int(sky_top[2] + (sky_bot[2] - sky_top[2]) * t)

    def render_frame() -> Image.Image:
        arr = np.zeros((H, W, 3), dtype=np.uint8)
        sky_gradient(arr)
        # Composite the per-pixel solid mask — this IS the world.
        # ground and baked particles both live here; overhangs/caves
        # come for free since we no longer track a per-column top.
        mask = bake_layer[..., 3] > 0
        if mask.any():
            arr[mask] = bake_layer[mask, :3]
        # Stamp only LIVE (not-yet-baked) particles.
        for i in range(N):
            if bake_flag[i]:
                continue
            x = int(pos[i, 0])
            y = int(pos[i, 1])
            r = int(radius[i])
            if 0 <= x < W and 0 <= y < H:
                for dy in range(-r, r + 1):
                    for dx in range(-r, r + 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < W and 0 <= ny < H:
                            arr[ny, nx] = colour[i]
        # Caption with preset name.
        try:
            from PIL import ImageDraw
            im = Image.fromarray(arr, mode="RGB")
            d = ImageDraw.Draw(im)
            d.text((8, 8), f"preset: {preset.name}", fill=(255, 255, 255))
            d.text((8, 22),
                   f"cone±{preset.max_blast_angle_deg:.0f}°  "
                   f"g={preset.n_grains}  c={preset.n_chunks}  "
                   f"fric={preset.friction_per_sec:.2f}",
                   fill=(220, 220, 220))
            return im
        except Exception:
            return Image.fromarray(arr, mode="RGB")

    frames_out: list[Image.Image] = []
    spawned = False

    for f in range(frames):
        if f == BLAST_FRAME and not spawned:
            spawned = True
            # Per-pixel crater carve: clear alpha to 0 (empty) for every
            # pixel inside the parabolic bowl. No heightmap.
            for col in range(N_COLUMNS):
                dx = col - BLAST_X
                if abs(dx) <= CRATER_RADIUS:
                    depth = int(CRATER_DEPTH * (1.0 - (dx / CRATER_RADIUS) ** 2))
                    y0 = GROUND_Y
                    y1 = min(H, GROUND_Y + depth + 1)
                    bake_layer[y0:y1, col, 3] = 0
            is_chunk[: preset.n_chunks] = True
            is_chunk[preset.n_chunks :] = False
            for i in range(N):
                # Centered triangular spawn — biases particles toward the
                # blast centre (fewer at the rim) so the perimeter doesn't
                # accumulate spawn-position pile-up. Triangular(-R, 0, R)
                # has a peak at 0 and falls off linearly.
                start_off = float(rng.triangular(
                    -CRATER_RADIUS, 0.0, CRATER_RADIUS))
                start_x = BLAST_X + start_off
                # Spawn above the existing solid mask. Walk up from
                # GROUND_Y until we find empty space — this handles the
                # crater bowl (start_y inside the dug-out region) and
                # any future overhangs/caves naturally.
                xi = int(np.clip(start_x, 0, W - 1))
                start_y = GROUND_Y
                while start_y > 0 and bake_layer[start_y, xi, 3] == 0:
                    start_y -= 1
                start_y -= 2.0  # 2px above the first solid pixel below
                # Small colour-flavour dig (chunks read as deeper-soil).
                if is_chunk[i]:
                    dig = float(rng.uniform(0.0, CRATER_DEPTH * 0.25))
                else:
                    dig = float(rng.uniform(0.0, CRATER_DEPTH * 0.1))

                # Direction: uniform random angle within the cone
                # (Worms-classic — gives a wide, flat spray that arcs).
                # Then bias slightly toward the radial-outward direction
                # via ``direction_blend`` so rim particles tend outward,
                # centre-of-blast particles tend straight up.
                base_ang = float(rng.uniform(-max_angle, max_angle))
                # Sign of start_off picks left/right bias for the blend.
                if start_off >= 0:
                    radial_ang = max_angle * (start_off / CRATER_RADIUS)
                else:
                    radial_ang = -max_angle * (-start_off / CRATER_RADIUS)
                blend = preset.direction_blend
                final_ang = base_ang * (1.0 - blend) + radial_ang * blend
                # Clamp to cone (so direction_blend > 1.0 doesn't fly out
                # sideways).
                final_ang = max(-max_angle, min(max_angle, final_ang))
                dirx = math.sin(final_ang)
                diry = -math.cos(final_ang)

                if is_chunk[i]:
                    speed = float(rng.uniform(preset.chunk_speed_min,
                                              preset.chunk_speed_max))
                    r = int(rng.integers(preset.chunk_radius_min,
                                         preset.chunk_radius_max + 1))
                    base_col = chunk_pal[int(rng.integers(0, len(chunk_pal)))]
                else:
                    speed = float(rng.uniform(preset.grain_speed_min,
                                              preset.grain_speed_max))
                    r = int(rng.integers(preset.grain_radius_min,
                                         preset.grain_radius_max + 1))
                    base_col = grain_pal[int(rng.integers(0, len(grain_pal)))]

                # Per-particle post-blast darkening from the configured
                # range. ``scale = 1 - factor`` is multiplied into RGB.
                darken = float(rng.uniform(
                    preset.post_blast_darken_min,
                    preset.post_blast_darken_max,
                ))
                scale = max(0.0, 1.0 - darken)
                colour[i] = (
                    int(base_col[0] * scale),
                    int(base_col[1] * scale),
                    int(base_col[2] * scale),
                )

                # Edge-outward kick: extra horizontal velocity scaled by
                # rim distance. This is what blasts the edge particles
                # outward so they don't pile near the centre.
                edge_factor = start_off / CRATER_RADIUS  # -1..1
                edge_kick = edge_factor * preset.edge_outward_boost

                pos[i, 0] = start_x
                pos[i, 1] = start_y
                vel[i, 0] = dirx * speed + edge_kick
                vel[i, 1] = diry * speed
                radius[i] = float(r)
                landed[i] = False
                settled[i] = False

        dt = 1.0 / 30.0
        if spawned:
            air_mask = ~landed
            if air_mask.any():
                vel[air_mask] *= preset.air_drag_per_sec ** dt
                vel[air_mask, 1] += preset.gravity * dt
                pos[air_mask] += vel[air_mask] * dt

                for i in np.nonzero(air_mask)[0]:
                    x = int(pos[i, 0])
                    y = int(pos[i, 1])
                    if x < 0 or x >= W or y >= H:
                        landed[i] = True
                        settled[i] = True
                        continue
                    if y < 0:
                        continue  # above frame; no collision yet
                    # Velocity-aware per-pixel landing: only check
                    # collision when falling (vy >= 0). The collision is
                    # a single alpha-channel query at the particle's
                    # current pixel. Rising particles skip — they're
                    # blasting out and can't be caught by their own
                    # spawn surface. This supports overhangs/caves
                    # naturally since we never assumed monotone tops.
                    if vel[i, 1] < 0:
                        continue
                    if bake_layer[y, x, 3] > 0:
                        # Back off one pixel so we sit ON the surface
                        # rather than inside it.
                        pos[i, 1] = float(y - 1)
                        landed[i] = True
                        if is_chunk[i]:
                            # KE-based impact: above the binding
                            # threshold, the chunk DIGS instead of piling.
                            # Loose-ground multiplier doubles excess when
                            # the landing site is already below GROUND_Y.
                            vsq = float(vel[i, 0] ** 2 + vel[i, 1] ** 2)
                            ke = 0.5 * (radius[i] ** 2) * vsq
                            excess = max(0.0, ke - preset.impact_binding_ke)
                            if y > GROUND_Y:  # inside crater bowl
                                excess *= preset.impact_loose_ground_multiplier
                            # Saturating dig formula — per-chunk dig
                            # asymptotes at impact_displace_scale so a
                            # huge ejection swarm can't tunnel a single
                            # column straight through the map. ratio is
                            # excess/binding (0..inf); saturation 0..1.
                            if excess > 0:
                                ratio = excess / preset.impact_binding_ke
                                saturation = 1.0 - math.exp(-ratio * 0.6)
                                dig_px = int(round(
                                    preset.impact_displace_scale * saturation
                                ))
                            else:
                                dig_px = 0
                            # Per-pixel paint: a chunk impact stamps a
                            # disc of chunk-colour pixels at the landing
                            # point. If KE exceeds binding, the disc
                            # extends DOWN by ``dig_px`` (drilling into
                            # the loose crater bowl); otherwise it
                            # stamps a flat splat on top of the
                            # existing surface. The per-pixel mask
                            # naturally caps how tall the chunk pile
                            # can grow — chunks landing on a tall pile
                            # simply land higher up and stamp there.
                            half = int(preset.splat_radius_px)
                            cr, cg, cb = colour[i]
                            for dx in range(-half, half + 1):
                                col = x + dx
                                if not (0 <= col < W):
                                    continue
                                falloff = 1.0 - abs(dx) / (half + 1)
                                # Stamp a small vertical extent — 1px
                                # for the rim columns, up to splat_lift
                                # for the centre. Drill_px adds extra
                                # downward extent on hard impacts.
                                lift_px = max(1, int(round(
                                    preset.splat_lift_max * falloff)))
                                drill = max(0, int(round(dig_px * falloff)))
                                y_top = max(0, y - lift_px + 1)
                                y_bot = min(H - 1, y + drill)
                                bake_layer[y_top:y_bot + 1, col, 0] = cr
                                bake_layer[y_top:y_bot + 1, col, 1] = cg
                                bake_layer[y_top:y_bot + 1, col, 2] = cb
                                bake_layer[y_top:y_bot + 1, col, 3] = 255
                        else:
                            # Grains stamp a single pixel.
                            cr, cg, cb = colour[i]
                            for dx in (-1, 0, 1):
                                col = x + dx
                                if 0 <= col < W:
                                    bake_layer[y, col, 0] = cr
                                    bake_layer[y, col, 1] = cg
                                    bake_layer[y, col, 2] = cb
                                    bake_layer[y, col, 3] = 255

            slide_mask = landed & ~settled
            if slide_mask.any():
                vel[slide_mask, 0] *= preset.friction_per_sec ** dt
                vel[slide_mask, 1] = 0.0
                pos[slide_mask, 0] += vel[slide_mask, 0] * dt
                for i in np.nonzero(slide_mask)[0]:
                    x = int(pos[i, 0])
                    y = int(pos[i, 1])
                    # Per-pixel slide: walk up from current y until we
                    # find empty space, so the particle rides the local
                    # surface even over overhangs / piled chunks.
                    if 0 <= x < W:
                        while y > 0 and bake_layer[y, x, 3] > 0:
                            y -= 1
                        pos[i, 1] = float(y)
                    if abs(vel[i, 0]) < preset.settle_speed_threshold:
                        settled[i] = True
                        vel[i, 0] = 0.0

            # Per-pixel impacts already wrote into bake_layer at landing
            # time. Mark every landed-and-settled particle as baked so
            # the live render loop skips it. (No separate bake call.)
            new_baked = landed & settled & ~bake_flag
            if new_baked.any():
                bake_flag[new_baked] = True

            # Region partition — record live (= still simulating)
            # particles per cell, then transition empty-for-N-frames
            # cells to STATIC so a region tracker can skip them.
            live_mask = ~bake_flag
            if live_mask.any():
                region_grid.record_live(pos[live_mask])
            else:
                region_grid.record_live(np.zeros((0, 2), dtype=np.float32))
            region_grid.mark_static_when_idle(idle_frames=30)

        frames_out.append(render_frame())

    out_dir = Path(__file__).parent / "output" / "particles"
    out_dir.mkdir(parents=True, exist_ok=True)
    if preset.name == "sand":
        out_path = out_dir / "sand_crater.gif"
    else:
        out_path = out_dir / f"sand_crater_{preset.name}.gif"
    frames_out[0].save(
        out_path,
        save_all=True,
        append_images=frames_out[1:],
        duration=33,
        loop=0,
        optimize=False,
    )

    n_landed = int(landed.sum())
    n_settled = int(settled.sum())
    n_chunks_landed = int((landed & is_chunk).sum())
    # Per-pixel terrain stats from bake_layer alpha.
    solid = bake_layer[..., 3] > 0
    col_has_solid = solid.any(axis=0)
    top_y = np.where(col_has_solid,
                     solid.argmax(axis=0),
                     GROUND_Y).astype(np.int32)
    crater_depth = int((top_y - GROUND_Y).max(initial=0))
    pile_max = int((GROUND_Y - top_y).max(initial=0))
    print(f"[{preset.name}]")
    print(f"  wrote: {out_path}")
    print(f"  grains/chunks: {preset.n_grains}/{preset.n_chunks}  total: {N}")
    print(f"  landed: {n_landed}  settled: {n_settled}  chunks_landed: {n_chunks_landed}/{preset.n_chunks}")
    print(f"  crater max depth: {crater_depth}px   pile max: {pile_max}px")
    print(f"  cone±{preset.max_blast_angle_deg:.0f}°  friction/sec={preset.friction_per_sec:.2f}")
    print(f"  baked     : {int(bake_flag.sum())}/{N} particles -> static texture")
    print(f"  regions   : {region_grid.static_cell_count()} static, "
          f"{region_grid.active_cell_count()} active")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--preset", default="sand", choices=list(PRESETS))
    ap.add_argument("--all", action="store_true",
                    help="render one gif per preset")
    ap.add_argument("--frames", type=int, default=130)
    args = ap.parse_args()

    if args.all:
        for name in PRESETS:
            run_preset(get_preset(name), frames=args.frames)
    else:
        run_preset(get_preset(args.preset), frames=args.frames)


if __name__ == "__main__":
    main()
