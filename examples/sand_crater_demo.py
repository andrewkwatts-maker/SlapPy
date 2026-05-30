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


def _slump_step(
    bake_layer: np.ndarray,
    *,
    rng: np.random.Generator,
    fall_prob: float,
    slump_angle_deg: float,
    protect_y_above: int,
) -> None:
    """One frame of falling-sand / angle-of-repose update.

    For every solid pixel ABOVE ``protect_y_above`` (so the original
    sub-ground stays put), check support directly below. If empty,
    fall with probability ``fall_prob``. Otherwise check diagonal
    support — if the neighbour column is significantly lower (steeper
    than ``slump_angle_deg``), slump sideways into it.
    """
    Hh, Ww, _ = bake_layer.shape
    solid = bake_layer[..., 3] > 0
    y_start = max(0, protect_y_above - 1)
    max_step = max(1, int(round(math.tan(
        math.radians(min(89.0, slump_angle_deg))))))
    # Per-frame fall rate is heavily damped — fall_prob is the
    # *eventual* probability, not the per-frame one. Scale so even
    # zero-cohesion (rock, sand) needs ~20 frames to settle, giving
    # the user time to see the pile form before slump erases it.
    frame_fall = min(1.0, fall_prob * 0.08)
    side_fall = frame_fall * 0.4
    # Random fall mask for all candidate pixels.
    for y in range(y_start, 0, -1):
        row = solid[y]
        if not row.any():
            continue
        # Empty pixel directly below → vertical fall.
        below_empty = ~solid[y + 1] if y + 1 < Hh else np.zeros(Ww, bool)
        # Choose which pixels to fall this frame.
        fall = row & below_empty
        if fall.any() and frame_fall > 0.0:
            roll = rng.random(Ww) < frame_fall
            fall &= roll
            if fall.any():
                idx = np.where(fall)[0]
                bake_layer[y + 1, idx] = bake_layer[y, idx]
                bake_layer[y, idx, 3] = 0
                solid[y + 1, idx] = True
                solid[y, idx] = False
        # Sideways slump: pixel has support below but a neighbour column
        # is much lower → slide diagonally.
        if side_fall > 0.0 and y + max_step < Hh:
            still = solid[y] & ~below_empty
            # left neighbour lower
            left_lower = np.zeros(Ww, bool)
            left_lower[1:] = (
                still[1:]
                & ~solid[y + 1, :-1]
                & ~solid[y, :-1]
            )
            right_lower = np.zeros(Ww, bool)
            right_lower[:-1] = (
                still[:-1]
                & ~solid[y + 1, 1:]
                & ~solid[y, 1:]
            )
            slump_l = left_lower & (rng.random(Ww) < side_fall)
            slump_r = right_lower & (rng.random(Ww) < side_fall)
            if slump_l.any():
                idx = np.where(slump_l)[0]
                bake_layer[y, idx - 1] = bake_layer[y, idx]
                bake_layer[y, idx, 3] = 0
                solid[y, idx - 1] = True
                solid[y, idx] = False
            if slump_r.any():
                idx = np.where(slump_r)[0]
                bake_layer[y, idx + 1] = bake_layer[y, idx]
                bake_layer[y, idx, 3] = 0
                solid[y, idx + 1] = True
                solid[y, idx] = False


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
                # Uniform spawn across crater radius — gives the wide
                # natural pile the original (heightmap) version had.
                # Triangular spawn buried particles in the crater bowl
                # and starved the rim pile.
                start_off = float(rng.uniform(
                    -CRATER_RADIUS, CRATER_RADIUS))
                start_x = BLAST_X + start_off
                # Spawn just above the ORIGINAL ground level so all
                # particles start from the same band. (Walking up
                # through the now-empty crater mask drove start_y to
                # y=0 — that's why particles appeared to fall from the
                # top of the screen.)
                start_y = float(GROUND_Y - 2)
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
                    if vel[i, 1] < 0:
                        continue
                    # Swept collision: a fast-falling chunk may move
                    # several pixels per frame. Scan the column from
                    # last-frame y to current y for any solid pixel —
                    # otherwise we tunnel through 1-pixel layers and
                    # the chunk vanishes into the deep sub-ground.
                    prev_y = int(pos[i, 1] - vel[i, 1] * dt)
                    hit_y = -1
                    for yi in range(max(0, prev_y), min(H, y + 1)):
                        if bake_layer[yi, x, 3] > 0:
                            hit_y = yi
                            break
                    if hit_y >= 0:
                        y = hit_y
                        pos[i, 1] = float(y - 1)
                        landed[i] = True
                        if is_chunk[i]:
                            # KE-driven impact = drill + ejecta ONLY.
                            # The chunk's own body bakes at SETTLE time
                            # (after sliding) via bake_settled_particles
                            # — that way sliding particles end up in
                            # the bake layer where they actually stop,
                            # not where they first hit ground.
                            vsq = float(vel[i, 0] ** 2 + vel[i, 1] ** 2)
                            ke = 0.5 * (radius[i] ** 2) * vsq
                            excess = max(0.0, ke - preset.impact_binding_ke)
                            if y > GROUND_Y:  # inside crater bowl
                                excess *= preset.impact_loose_ground_multiplier
                            if excess > 0:
                                ratio = excess / preset.impact_binding_ke
                                drive = 1.0 - math.exp(-ratio * 0.6)
                                drill_px = int(round(
                                    preset.impact_drill_max_px * drive))
                            else:
                                drill_px = 0
                            cr, cg, cb = colour[i]
                            splat_half = int(preset.splat_radius_px)
                            drill_half = max(0, int(round(
                                splat_half * preset.impact_drill_width_factor)))
                            # ── Drill (down): narrow column ──────────
                            drilled_pixels = 0
                            for dx in range(-drill_half, drill_half + 1):
                                col = x + dx
                                if not (0 <= col < W):
                                    continue
                                fall = 1.0 - abs(dx) / (drill_half + 1)
                                d = int(round(drill_px * fall))
                                if d <= 0:
                                    continue
                                y_top = y
                                y_bot = min(H - 1, y + d)
                                bake_layer[y_top:y_bot + 1, col, 0] = cr
                                bake_layer[y_top:y_bot + 1, col, 1] = cg
                                bake_layer[y_top:y_bot + 1, col, 2] = cb
                                bake_layer[y_top:y_bot + 1, col, 3] = 255
                                drilled_pixels += (y_bot - y_top + 1)
                            # ── Conserved rim ejecta: the drilled
                            # volume gets redistributed to the surface
                            # splat above the impact (NOT the chunk's
                            # body — that bakes at settle time). With
                            # impact_eject_gain=1.0 the total visible
                            # material delta is zero on drilled impacts.
                            if drilled_pixels > 0:
                                ejected = drilled_pixels * preset.impact_eject_gain
                                row_budget = ejected / max(1, 2 * splat_half + 1)
                                for dx in range(-splat_half, splat_half + 1):
                                    col = x + dx
                                    if not (0 <= col < W):
                                        continue
                                    falloff = 1.0 - abs(dx) / (splat_half + 1)
                                    lift_px = int(round(
                                        row_budget * falloff))
                                    if lift_px <= 0:
                                        continue
                                    y_top = max(0, y - lift_px)
                                    y_bot = min(H - 1, y - 1)
                                    bake_layer[y_top:y_bot + 1, col, 0] = cr
                                    bake_layer[y_top:y_bot + 1, col, 1] = cg
                                    bake_layer[y_top:y_bot + 1, col, 2] = cb
                                    bake_layer[y_top:y_bot + 1, col, 3] = 255
                        # Grains and chunk bodies bake at SETTLE time —
                        # see bake_settled_particles below. Nothing more
                        # to do at landing.

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
                    # Per-particle settle jitter on the threshold so
                    # particles stop over a band of frames, not all at
                    # once. Keeps the bake looking organic.
                    jitter = preset.settle_jitter
                    if jitter > 0.0:
                        threshold = preset.settle_speed_threshold * (
                            1.0 + float(rng.uniform(-jitter, jitter)))
                    else:
                        threshold = preset.settle_speed_threshold
                    if abs(vel[i, 0]) < threshold:
                        settled[i] = True
                        vel[i, 0] = 0.0

            # Settle-time bake: stamp each settled particle's BODY into
            # the bake layer at its FINAL position (post-slide). With
            # bake_radius_override=0, each particle = 1 pixel = 1 unit
            # of mass, so total bake mass tracks particle count instead
            # of (2r+1)² per particle (which over-grew the pile).
            bake_settled_particles(
                pos=pos, radius=radius, colour=colour,
                landed=landed, settled=settled,
                bake_flag=bake_flag, terrain_rgba=bake_layer,
                bake_radius_override=preset.bake_radius_override,
            )

            # ── Slump / collapse pass for non-cohesive materials ──
            # Per-pixel cellular update: every solid pixel with empty
            # space directly below "falls" by 1 with probability
            # (1 - cohesion). Adds a 45° / configurable angle of repose
            # so chunks pile naturally instead of growing rigid towers.
            # Skipped entirely when cohesion >= 1.0 (cost-free for mud).
            if preset.cohesion < 1.0:
                _slump_step(
                    bake_layer,
                    rng=rng,
                    fall_prob=1.0 - preset.cohesion,
                    slump_angle_deg=preset.slump_angle_deg,
                    protect_y_above=GROUND_Y + CRATER_DEPTH + 8,
                )

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
