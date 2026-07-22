"""Soft-body vehicle demo — drop, land, throttle across the screen.

Builds a 2D BeamNG-style vehicle (chassis lattice + two wheels + suspension)
in a :class:`SoftBodyWorld`, drops it onto a slope built from an anchored
steel lattice, then applies full throttle for several seconds and renders
the whole thing to a GIF.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from pharos_engine.media import save_frames
from pharos_engine.softbody import (
    SoftBodyRenderConfig,
    SoftBodyRenderer,
    SoftBodyWorld,
    VehicleSpec,
    build_vehicle,
    make_lattice_body,
    step,
)


OUT_DIR = Path(__file__).resolve().parent / "output" / "softbody"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def _anchor_body(world: SoftBodyWorld, node_start: int, node_end: int) -> None:
    for nid in range(node_start, node_end):
        world.nodes.fixed[nid] = True
        world.nodes.inv_mass[nid] = 0.0


def main() -> Path:
    w = SoftBodyWorld()
    w.config["floor_y"] = 6.0
    # Apply the vehicle-section gravity override from softbody.yml so the
    # chassis stays planted on bumpy terrain (9.81 let the wheel impulses
    # pop the body up enough to invert; 12.0 keeps it grounded).
    w.config["gravity"] = (0.0, 12.0)

    slope = make_lattice_body(
        w, "steel", width_cells=12, height_cells=2,
        cell_size=0.20, position=(-3.0, 5.4), name="slope",
    )
    sns, sne = slope.node_slice
    for i, nid in enumerate(range(sns, sne)):
        ix = (i % 13)
        w.nodes.pos[nid, 1] += ix * 0.02
    _anchor_body(w, sns, sne)

    spec = VehicleSpec(drivetrain_mode="awd")
    veh = build_vehicle(w, spec, position=(-2.5, 0.2))

    cfg = SoftBodyRenderConfig.from_yaml({"width": 640, "height": 360})
    renderer = SoftBodyRenderer(config=cfg)

    frames = []
    dt = 1.0 / 60.0

    def view_box() -> tuple[float, float, float, float]:
        cx = float(veh.chassis_position(w)[0])
        return (cx - 4.0, -0.5, cx + 4.0, w.config["floor_y"] + 0.3)

    from PIL import Image, ImageDraw

    def _draw_sedan_overlay(img: Image.Image, vb: tuple[float, float, float, float]) -> None:
        """Paint a stylised sedan body + wheels on top of the beam render.

        Reads the chassis centroid + up-vector and the wheel-hub positions
        directly out of the softbody world so the overlay follows the
        physics exactly.
        """
        cx, cy = float(view_box()[0]), float(view_box()[1])
        x0, y0, x1, y1 = vb
        Wpx, Hpx = img.size
        def world_to_pix(p):
            px = (p[0] - x0) / (x1 - x0) * Wpx
            py = (p[1] - y0) / (y1 - y0) * Hpx
            return (int(px), int(py))

        draw = ImageDraw.Draw(img, "RGBA")

        # Chassis: averaged body bounding-box from chassis node positions.
        chassis_nodes = w.nodes.pos[veh.chassis_node_ids]
        cmin = chassis_nodes.min(axis=0)
        cmax = chassis_nodes.max(axis=0)
        cw = float(cmax[0] - cmin[0])
        ch = float(cmax[1] - cmin[1])
        cmid = (cmin + cmax) * 0.5
        up = veh.chassis_up_vector(w)
        ang = float(np.degrees(np.arctan2(up[0], -up[1])))

        # Sedan silhouette: a slightly tapered hood + cabin + boot.
        # Draw on a transparent overlay then rotate+paste.
        body_w_px = int(cw / (x1 - x0) * Wpx * 1.05)
        body_h_px = int(ch / (y1 - y0) * Hpx * 0.85)
        body_h_px = max(body_h_px, 22)
        body_w_px = max(body_w_px, 90)

        from PIL import Image as _Im
        sedan = _Im.new("RGBA", (body_w_px + 4, body_h_px + 4), (0, 0, 0, 0))
        sd = ImageDraw.Draw(sedan)
        # Main body — dark crimson sedan with subtle gradient.
        body_color = (180, 30, 30, 255)
        cabin_color = (40, 56, 76, 230)
        glass_color = (140, 195, 220, 200)
        chrome = (200, 200, 210, 255)
        # Lower body rectangle.
        sd.rounded_rectangle(
            [(2, body_h_px // 2), (body_w_px + 2, body_h_px + 2)],
            radius=body_h_px // 4, fill=body_color,
        )
        # Cabin / roof — slope down toward the trunk.
        cabin_x0 = body_w_px // 5
        cabin_x1 = body_w_px - body_w_px // 4
        roof_h = body_h_px // 2
        sd.polygon(
            [
                (cabin_x0, body_h_px // 2),
                (cabin_x0 + 12, 4),
                (cabin_x1 - 6, 4),
                (cabin_x1, body_h_px // 2),
            ],
            fill=cabin_color,
        )
        # Windshield / rear glass.
        sd.polygon(
            [
                (cabin_x0 + 4, body_h_px // 2 - 2),
                (cabin_x0 + 14, 7),
                (cabin_x0 + body_w_px // 4, 7),
                (cabin_x0 + body_w_px // 4, body_h_px // 2 - 2),
            ],
            fill=glass_color,
        )
        # Headlight + tail-light.
        sd.ellipse(
            [(body_w_px - 12, body_h_px // 2 + 4),
             (body_w_px - 4, body_h_px // 2 + 12)],
            fill=(255, 230, 140, 255),
        )
        sd.ellipse(
            [(4, body_h_px // 2 + 4),
             (12, body_h_px // 2 + 12)],
            fill=(160, 22, 22, 255),
        )
        # Chrome trim strip.
        sd.line(
            [(6, body_h_px // 2 + 1), (body_w_px - 4, body_h_px // 2 + 1)],
            fill=chrome, width=1,
        )
        sedan_rot = sedan.rotate(-ang, resample=_Im.BILINEAR, expand=False)
        cmid_px = world_to_pix(cmid)
        paste_x = cmid_px[0] - sedan_rot.width // 2
        paste_y = cmid_px[1] - sedan_rot.height // 2
        img.paste(sedan_rot, (paste_x, paste_y), sedan_rot)

        # Wheels — drawn AFTER the body so they sit in front.
        for wi, hub_id in enumerate(veh.wheel_hubs):
            hub_pos = w.nodes.pos[hub_id]
            cx, cy = world_to_pix(hub_pos)
            # Wheel radius in pixels.
            rim_ids = veh.wheel_rims[wi]
            if rim_ids.size > 0:
                rim_pos = w.nodes.pos[rim_ids]
                r_world = float(np.linalg.norm(rim_pos - hub_pos, axis=1).mean())
                r_px = max(int(r_world / (x1 - x0) * Wpx), 8)
            else:
                r_px = 12
            # Tire (black).
            draw.ellipse(
                [(cx - r_px, cy - r_px), (cx + r_px, cy + r_px)],
                fill=(18, 18, 22, 255),
            )
            # Inner rim (grey).
            r_inner = int(r_px * 0.55)
            draw.ellipse(
                [(cx - r_inner, cy - r_inner), (cx + r_inner, cy + r_inner)],
                fill=(190, 190, 200, 255),
            )
            # Hub centre.
            draw.ellipse(
                [(cx - 2, cy - 2), (cx + 2, cy + 2)],
                fill=(60, 60, 70, 255),
            )

    def _shot() -> Image.Image:
        arr = renderer.render(w, view_box=view_box())
        img = Image.fromarray(arr, mode="RGBA").convert("RGB")
        _draw_sedan_overlay(img, view_box())
        return img

    for _ in range(60):
        step(w, dt=dt)
        frames.append(_shot())

    for _ in range(360):
        veh.apply_throttle(w, throttle=1.0, dt=dt)
        step(w, dt=dt)
        frames.append(_shot())

    out = OUT_DIR / "vehicle_demo.gif"
    save_frames(frames, out, fps=30)
    print(f"wrote {out}")
    print(f"final chassis position: {veh.chassis_position(w)}")
    print(f"broken beams: {int(w.beams.broken.sum())}/{w.beams.count}")
    return out


if __name__ == "__main__":
    main()
