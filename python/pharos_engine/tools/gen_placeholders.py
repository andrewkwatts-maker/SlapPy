"""
gen_placeholders.py
Generate placeholder PNG assets for Bullet Strata and Ochema Circuit.
Uses only Pillow (PIL) — no other external dependencies.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _new(w: int, h: int, mode: str = "RGBA", bg=(0, 0, 0, 0)) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new(mode, (w, h), bg)
    draw = ImageDraw.Draw(img)
    return img, draw


def _save(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def _ring(draw: ImageDraw.ImageDraw, cx: int, cy: int, r_outer: int, r_inner: int, colour: tuple) -> None:
    """Draw a ring by drawing a filled outer circle then a filled inner circle on top."""
    draw.ellipse((cx - r_outer, cy - r_outer, cx + r_outer, cy + r_outer), fill=colour)
    draw.ellipse((cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner), fill=(0, 0, 0, 0))


def _star_points(cx: int, cy: int, r_outer: float, r_inner: float, points: int) -> list[tuple[float, float]]:
    """Return polygon vertices for a star."""
    verts = []
    for i in range(points * 2):
        angle = math.pi / points * i - math.pi / 2
        r = r_outer if i % 2 == 0 else r_inner
        verts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return verts


def _label(draw: ImageDraw.ImageDraw, text: str, img_w: int, img_h: int,
           colour=(255, 255, 255, 200), size_hint: int = 8) -> None:
    """Draw a small label centred near the bottom of the image."""
    try:
        font = ImageFont.truetype("arial.ttf", size_hint)
    except (IOError, OSError):
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (img_w - tw) // 2
    y = img_h - th - 2
    draw.text((x, y), text, fill=colour, font=font)


# ---------------------------------------------------------------------------
# Bullet Strata — sprites
# ---------------------------------------------------------------------------

def _bs_player_physical(path: Path) -> None:
    """28×40 blue armoured humanoid."""
    img, draw = _new(28, 40, "RGBA", (0, 0, 0, 0))
    W, H = 28, 40
    body_col = (30, 80, 160, 255)
    helmet_col = (60, 130, 220, 255)
    outline_col = (0, 0, 0, 255)

    # body
    draw.rectangle((6, 16, 22, 36), fill=body_col, outline=outline_col)
    # shoulders
    draw.rectangle((3, 16, 8, 24), fill=body_col, outline=outline_col)
    draw.rectangle((20, 16, 25, 24), fill=body_col, outline=outline_col)
    # legs
    draw.rectangle((7, 34, 13, 39), fill=body_col, outline=outline_col)
    draw.rectangle((15, 34, 21, 39), fill=body_col, outline=outline_col)
    # helmet
    draw.ellipse((8, 4, 20, 18), fill=helmet_col, outline=outline_col)
    # eyes
    draw.ellipse((11, 9, 14, 12), fill=(255, 255, 255, 255))
    draw.ellipse((15, 9, 18, 12), fill=(255, 255, 255, 255))
    _save(img, path)


def _bs_player_cyber(path: Path) -> None:
    """28×40 cyan wireframe humanoid."""
    img, draw = _new(28, 40, "RGBA", (0, 0, 0, 255))
    cyan = (0, 220, 255, 255)
    magenta = (255, 0, 220, 255)

    # body outline
    draw.rectangle((6, 16, 22, 36), outline=cyan, width=1)
    draw.rectangle((3, 16, 8, 24), outline=cyan, width=1)
    draw.rectangle((20, 16, 25, 24), outline=cyan, width=1)
    draw.rectangle((7, 34, 13, 39), outline=cyan, width=1)
    draw.rectangle((15, 34, 21, 39), outline=cyan, width=1)
    # helmet outline
    draw.ellipse((8, 4, 20, 18), outline=cyan, width=1)
    # cross-hatch visor detail
    draw.line((8, 11, 20, 11), fill=cyan, width=1)
    # eyes (magenta)
    draw.ellipse((11, 9, 14, 12), fill=magenta)
    draw.ellipse((15, 9, 18, 12), fill=magenta)
    _save(img, path)


def _bs_player_ruined(path: Path) -> None:
    """28×40 red cracked humanoid."""
    img, draw = _new(28, 40, "RGBA", (0, 0, 0, 0))
    body_col = (140, 20, 20, 255)
    crack_col = (60, 0, 0, 255)
    orange_eye = (255, 120, 0, 255)

    draw.rectangle((6, 16, 22, 36), fill=body_col)
    draw.rectangle((3, 16, 8, 24), fill=body_col)
    draw.rectangle((20, 16, 25, 24), fill=body_col)
    draw.rectangle((7, 34, 13, 39), fill=body_col)
    draw.rectangle((15, 34, 21, 39), fill=body_col)
    draw.ellipse((8, 4, 20, 18), fill=body_col)
    # cracks
    draw.line((10, 18, 14, 26, 12, 32), fill=crack_col, width=1)
    draw.line((16, 20, 19, 28), fill=crack_col, width=1)
    draw.line((9, 7, 12, 14), fill=crack_col, width=1)
    # eyes
    draw.ellipse((11, 9, 14, 12), fill=orange_eye)
    draw.ellipse((15, 9, 18, 12), fill=orange_eye)
    _save(img, path)


def _bs_proj_pistol(path: Path) -> None:
    """8×8 white circle on transparent."""
    img, draw = _new(8, 8)
    draw.ellipse((1, 1, 6, 6), fill=(255, 255, 255, 255))
    _save(img, path)


def _bs_proj_plasma(path: Path) -> None:
    """12×12 magenta sphere with glow."""
    img, draw = _new(12, 12, "RGBA", (0, 0, 0, 255))
    draw.ellipse((2, 2, 9, 9), fill=(220, 0, 220, 255))
    draw.ellipse((5, 5, 7, 7), fill=(255, 255, 255, 255))
    _save(img, path)


def _bs_proj_gravity(path: Path) -> None:
    """16×16 purple ring on transparent."""
    img, draw = _new(16, 16)
    # outer fill then erase centre
    draw.ellipse((1, 1, 14, 14), fill=(140, 0, 200, 255))
    draw.ellipse((4, 4, 11, 11), fill=(0, 0, 0, 0))
    _save(img, path)


def _bs_proj_orbital(path: Path) -> None:
    """24×24 gold 4-point star on black."""
    img, draw = _new(24, 24, "RGBA", (0, 0, 0, 255))
    pts = _star_points(12, 12, 11, 4, 4)
    draw.polygon(pts, fill=(255, 200, 0, 255))
    draw.ellipse((10, 10, 14, 14), fill=(255, 255, 255, 255))
    _save(img, path)


def _bs_pickup_pistol(path: Path) -> None:
    """32×32 grey gun shape."""
    img, draw = _new(32, 32, "RGBA", (40, 40, 40, 255))
    light_grey = (170, 170, 170, 255)
    # barrel
    draw.rectangle((4, 13, 24, 17), fill=light_grey)
    # body/grip
    draw.polygon([(12, 14), (22, 14), (22, 24), (14, 24)], fill=light_grey)
    # trigger guard
    draw.rectangle((15, 21, 19, 25), outline=light_grey, width=1)
    _label(draw, "PISTOL", 32, 32, colour=(200, 200, 200, 255), size_hint=7)
    _save(img, path)


def _bs_pickup_orbital(path: Path) -> None:
    """32×32 gold cannon."""
    img, draw = _new(32, 32, "RGBA", (30, 25, 10, 255))
    gold = (200, 150, 0, 255)
    # barrel
    draw.rectangle((4, 12, 22, 18), fill=gold)
    # muzzle circle
    draw.ellipse((20, 10, 28, 20), fill=gold)
    # body block
    draw.rectangle((10, 16, 24, 26), fill=gold)
    _label(draw, "ORB", 32, 32, colour=(255, 230, 100, 255), size_hint=7)
    _save(img, path)


# ---------------------------------------------------------------------------
# Bullet Strata — maps
# ---------------------------------------------------------------------------

def _bs_bg_physical(path: Path) -> None:
    """1280×720 grey brick pattern."""
    W, H = 1280, 720
    img, draw = _new(W, H, "RGB", (80, 80, 80))
    mortar = (65, 65, 65)
    BW, BH = 60, 30
    for row in range(H // BH + 1):
        y = row * BH
        offset = (BW // 2) if row % 2 else 0
        draw.line((0, y, W, y), fill=mortar, width=1)
        for col in range(-1, W // BW + 2):
            x = col * BW + offset
            draw.line((x, y, x, y + BH), fill=mortar, width=1)
    _save(img, path)


def _bs_bg_cyber(path: Path) -> None:
    """1280×720 dark blue circuit board."""
    W, H = 1280, 720
    img, draw = _new(W, H, "RGB", (5, 5, 30))
    grid_col = (0, 80, 120)
    node_col = (0, 140, 180)
    step = 40
    for x in range(0, W, step):
        draw.line((x, 0, x, H), fill=grid_col, width=1)
    for y in range(0, H, step):
        draw.line((0, y, W, y), fill=grid_col, width=1)
    # nodes at intersections
    for x in range(0, W, step):
        for y in range(0, H, step):
            draw.rectangle((x - 2, y - 2, x + 2, y + 2), fill=node_col)
    _save(img, path)


def _bs_bg_ruined(path: Path) -> None:
    """1280×720 dark red rubble with scattered ellipses."""
    W, H = 1280, 720
    img, draw = _new(W, H, "RGB", (25, 8, 8))
    rng = random.Random(42)
    rubble_cols = [
        (55, 15, 15), (45, 20, 10), (70, 25, 10),
        (35, 10, 10), (60, 30, 20), (40, 12, 12),
    ]
    for _ in range(200):
        cx = rng.randint(0, W)
        cy = rng.randint(0, H)
        rx = rng.randint(10, 60)
        ry = rng.randint(5, 30)
        col = rng.choice(rubble_cols)
        draw.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=col)
    _save(img, path)


def _bs_platform_tiles(path: Path) -> None:
    """128×32 strip of 4 tiles (each 32×32)."""
    W, H = 128, 32
    img, draw = _new(W, H, "RGB", (0, 0, 0))

    # Tile 1 — stone
    draw.rectangle((0, 0, 31, 31), fill=(100, 100, 100))
    draw.rectangle((0, 0, 31, 3), fill=(70, 70, 70))   # darker top edge

    # Tile 2 — grass/dirt
    draw.rectangle((32, 0, 63, 31), fill=(100, 70, 40))   # dirt
    draw.rectangle((32, 0, 63, 7), fill=(60, 120, 40))    # grass top

    # Tile 3 — metal plate with rivets
    draw.rectangle((64, 0, 95, 31), fill=(70, 90, 110))
    rivet_col = (110, 130, 150)
    for rx, ry in [(68, 4), (91, 4), (68, 27), (91, 27)]:
        draw.ellipse((rx - 2, ry - 2, rx + 2, ry + 2), fill=rivet_col)
    draw.rectangle((64, 0, 95, 1), fill=(90, 110, 130))

    # Tile 4 — glowing cyber
    draw.rectangle((96, 0, 127, 31), fill=(20, 20, 60))
    draw.rectangle((96, 0, 127, 2), fill=(0, 220, 255))   # cyan top edge
    draw.rectangle((96, 29, 127, 31), fill=(0, 220, 255))  # cyan bottom edge

    _save(img, path)


# ---------------------------------------------------------------------------
# Ochema Circuit — vehicles / parts
# ---------------------------------------------------------------------------

def _oc_part_cockpit(path: Path) -> None:
    """16×16 yellow dome on grey base."""
    img, draw = _new(16, 16, "RGBA", (0, 0, 0, 0))
    # base
    draw.rectangle((2, 9, 13, 14), fill=(100, 100, 110, 255))
    # dome
    draw.ellipse((3, 3, 13, 13), fill=(220, 190, 0, 255))
    # mask lower half of dome to look like half-dome
    draw.rectangle((3, 9, 13, 13), fill=(100, 100, 110, 255))
    _save(img, path)


def _oc_part_engine(path: Path) -> None:
    """16×16 orange engine block."""
    img, draw = _new(16, 16, "RGBA", (0, 0, 0, 0))
    orange = (220, 100, 20, 255)
    dark_orange = (150, 60, 10, 255)
    draw.rectangle((2, 2, 13, 13), fill=orange)
    # vents
    for vy in (4, 7, 10):
        draw.line((3, vy, 12, vy), fill=dark_orange, width=1)
    # heat shimmer dot
    draw.ellipse((11, 11, 13, 13), fill=(255, 200, 80, 255))
    _save(img, path)


def _oc_part_armor(path: Path) -> None:
    """16×16 steel-blue armour plate."""
    img, draw = _new(16, 16, "RGBA", (0, 0, 0, 0))
    mid = (80, 100, 130, 255)
    light = (110, 130, 160, 255)
    dark = (50, 70, 100, 255)
    draw.rectangle((1, 1, 14, 14), fill=mid)
    # bevel edges
    draw.line((1, 1, 14, 1), fill=light, width=1)
    draw.line((1, 1, 1, 14), fill=light, width=1)
    draw.line((14, 1, 14, 14), fill=dark, width=1)
    draw.line((1, 14, 14, 14), fill=dark, width=1)
    # darker centre panel
    draw.rectangle((4, 4, 11, 11), fill=dark)
    _save(img, path)


def _oc_part_wheel(path: Path) -> None:
    """16×16 dark rubber tyre."""
    img, draw = _new(16, 16, "RGBA", (0, 0, 0, 0))
    draw.ellipse((1, 1, 14, 14), fill=(30, 30, 30, 255))   # tyre
    draw.ellipse((3, 3, 12, 12), fill=(60, 60, 60, 255))   # inner
    draw.ellipse((5, 5, 10, 10), fill=(90, 90, 90, 255))   # hubcap
    _save(img, path)


def _oc_part_weapon(path: Path) -> None:
    """16×16 red weapon mount + barrel."""
    img, draw = _new(16, 16, "RGBA", (0, 0, 0, 0))
    dark_red = (120, 20, 20, 255)
    red = (200, 40, 40, 255)
    black = (0, 0, 0, 255)
    draw.rectangle((2, 4, 10, 12), fill=dark_red)
    # barrel pointing right
    draw.rectangle((9, 6, 14, 9), fill=red)
    # muzzle
    draw.rectangle((14, 6, 15, 9), fill=black)
    _save(img, path)


# ---------------------------------------------------------------------------
# Ochema Circuit — tracks
# ---------------------------------------------------------------------------

def _oc_track_01(path: Path) -> None:
    """1280×720 racing track top-down."""
    W, H = 1280, 720
    img, draw = _new(W, H, "RGB", (50, 50, 55))   # asphalt bg

    cx, cy = W // 2, H // 2
    # Track is a wide oval: outer and inner ellipses defining a 200px-wide band
    TRACK_W = 200
    ox, oy = 480, 260   # outer half-axes
    ix, iy = ox - TRACK_W, oy - TRACK_W  # inner half-axes

    # Draw track surface (mid-grey band)
    # Use a thick ellipse outline trick: draw filled outer, then fill inner with bg colour
    draw.ellipse((cx - ox, cy - oy, cx + ox, cy + oy), fill=(75, 75, 80))
    draw.ellipse((cx - ix, cy - iy, cx + ix, cy + iy), fill=(50, 50, 55))

    # White edge lines (track borders)
    edge_white = (220, 220, 220)
    draw.ellipse((cx - ox, cy - oy, cx + ox, cy + oy), outline=edge_white, width=3)
    draw.ellipse((cx - ix, cy - iy, cx + ix, cy + iy), outline=edge_white, width=3)

    # Yellow dashed centre line along the midpoint oval
    mx, my = (ox + ix) // 2, (oy + iy) // 2
    yellow = (220, 200, 0)
    N_DASHES = 60
    for i in range(N_DASHES):
        if i % 2 == 0:
            t0 = 2 * math.pi * i / N_DASHES
            t1 = 2 * math.pi * (i + 0.8) / N_DASHES
            pts = []
            steps = 8
            for s in range(steps + 1):
                t = t0 + (t1 - t0) * s / steps
                pts.append((cx + mx * math.cos(t), cy + my * math.sin(t)))
            if len(pts) >= 2:
                draw.line(pts, fill=yellow, width=2)

    # Start/finish zone (red on left, green on right of top of track)
    sz_x = cx - 30
    sz_y = cy - oy
    # green
    draw.rectangle((sz_x, sz_y - 2, sz_x + 30, sz_y + 10), fill=(0, 180, 0))
    # red
    draw.rectangle((sz_x - 30, sz_y - 2, sz_x, sz_y + 10), fill=(180, 0, 0))

    _save(img, path)


def _oc_track_tiles(path: Path) -> None:
    """256×64 strip of 4 tiles (each 64×64)."""
    W, H = 256, 64
    img, draw = _new(W, H, "RGB", (0, 0, 0))

    rng = random.Random(99)

    # Tile 1 — asphalt with subtle noise
    for px in range(64):
        for py in range(H):
            v = rng.randint(-4, 4)
            img.putpixel((px, py), (60 + v, 60 + v, 65 + v))

    # Tile 2 — kerb (alternating red/white 8px stripes, diagonal)
    for px in range(64, 128):
        for py in range(H):
            stripe = ((px - 64) + py) // 8
            col = (200, 0, 0) if stripe % 2 == 0 else (220, 220, 220)
            img.putpixel((px, py), col)

    # Tile 3 — dirt/gravel
    for px in range(128, 192):
        for py in range(H):
            v = rng.randint(-6, 6)
            img.putpixel((px, py), (90 + v, 70 + v, 50 + v))
    # pebble dots
    for _ in range(80):
        px = rng.randint(128, 191)
        py = rng.randint(0, H - 1)
        draw.ellipse((px - 1, py - 1, px + 1, py + 1), fill=(70, 55, 35))

    # Tile 4 — acid pool (bright green with darker bubbles)
    draw.rectangle((192, 0, 255, 63), fill=(0, 180, 20))
    for _ in range(15):
        bx = rng.randint(193, 254)
        by = rng.randint(1, 62)
        br = rng.randint(2, 6)
        draw.ellipse((bx - br, by - br, bx + br, by + br), fill=(0, 120, 10))

    _save(img, path)


# ---------------------------------------------------------------------------
# Ochema Circuit — hazards / scrap
# ---------------------------------------------------------------------------

def _oc_hazard_acid(path: Path) -> None:
    """24×24 green acid pool."""
    img, draw = _new(24, 24, "RGBA", (0, 0, 0, 0))
    draw.ellipse((2, 2, 21, 21), fill=(0, 200, 30, 220))
    rng = random.Random(7)
    for _ in range(6):
        bx = rng.randint(4, 19)
        by = rng.randint(4, 19)
        br = rng.randint(1, 3)
        draw.ellipse((bx - br, by - br, bx + br, by + br), fill=(0, 140, 20, 200))
    _save(img, path)


def _oc_hazard_turret(path: Path) -> None:
    """24×24 gun tower."""
    img, draw = _new(24, 24, "RGBA", (0, 0, 0, 0))
    dark_brown = (80, 60, 40, 255)
    dark_grey = (60, 60, 70, 255)
    grey = (100, 100, 110, 255)
    # base square
    draw.rectangle((4, 12, 20, 22), fill=dark_brown)
    # turret circle
    draw.ellipse((7, 6, 17, 16), fill=dark_grey)
    # barrel line pointing up-right
    draw.line((13, 10, 20, 4), fill=grey, width=2)
    _save(img, path)


def _oc_scrap(path: Path) -> None:
    """12×12 metallic diamond fragment."""
    img, draw = _new(12, 12, "RGBA", (0, 0, 0, 0))
    silver = (160, 160, 170, 255)
    dark_silver = (110, 110, 120, 255)
    # Diamond (rotated square)
    pts = [(6, 1), (11, 6), (6, 11), (1, 6)]
    draw.polygon(pts, fill=silver)
    # darker edges
    draw.line([pts[-1], pts[0]], fill=dark_silver, width=1)
    draw.line([pts[0], pts[1]], fill=(200, 200, 210, 255), width=1)
    draw.line([pts[1], pts[2]], fill=dark_silver, width=1)
    draw.line([pts[2], pts[3]], fill=dark_silver, width=1)
    _save(img, path)


# ---------------------------------------------------------------------------
# Main generate_all function
# ---------------------------------------------------------------------------

def generate_all(base_dir: Path | None = None) -> None:
    """
    Generate all placeholder PNG assets.

    Parameters
    ----------
    base_dir:
        Ignored — kept for API compatibility. Output paths are absolute.
    """
    BS = Path(r"H:\DaedalusSVN\Bullet Strata\assets")
    OC = Path(r"H:\DaedalusSVN\Ochema Circuit\assets")

    tasks: list[tuple] = [
        # Bullet Strata sprites
        (_bs_player_physical,  BS / "sprites" / "player_physical.png"),
        (_bs_player_cyber,     BS / "sprites" / "player_cyber.png"),
        (_bs_player_ruined,    BS / "sprites" / "player_ruined.png"),
        (_bs_proj_pistol,      BS / "sprites" / "projectile_pistol.png"),
        (_bs_proj_plasma,      BS / "sprites" / "projectile_plasma.png"),
        (_bs_proj_gravity,     BS / "sprites" / "projectile_gravity.png"),
        (_bs_proj_orbital,     BS / "sprites" / "projectile_orbital.png"),
        (_bs_pickup_pistol,    BS / "sprites" / "pickup_pistol.png"),
        (_bs_pickup_orbital,   BS / "sprites" / "pickup_orbital.png"),
        # Bullet Strata maps
        (_bs_bg_physical,      BS / "maps" / "bg_physical.png"),
        (_bs_bg_cyber,         BS / "maps" / "bg_cyber.png"),
        (_bs_bg_ruined,        BS / "maps" / "bg_ruined.png"),
        (_bs_platform_tiles,   BS / "maps" / "platform_tiles.png"),
        # Ochema Circuit vehicles/parts
        (_oc_part_cockpit,     OC / "vehicles" / "part_cockpit.png"),
        (_oc_part_engine,      OC / "vehicles" / "part_engine.png"),
        (_oc_part_armor,       OC / "vehicles" / "part_armor.png"),
        (_oc_part_wheel,       OC / "vehicles" / "part_wheel.png"),
        (_oc_part_weapon,      OC / "vehicles" / "part_weapon.png"),
        (_oc_hazard_acid,      OC / "vehicles" / "hazard_acid.png"),
        (_oc_hazard_turret,    OC / "vehicles" / "hazard_turret.png"),
        (_oc_scrap,            OC / "vehicles" / "scrap.png"),
        # Ochema Circuit tracks
        (_oc_track_01,         OC / "tracks" / "track_01.png"),
        (_oc_track_tiles,      OC / "tracks" / "track_tiles.png"),
    ]

    for fn, path in tasks:
        fn(path)
        size = path.stat().st_size
        print(f"  wrote {path}  ({size:,} bytes)")

    print(f"\nDone. {len(tasks)} files generated.")


if __name__ == "__main__":
    print("Generating placeholder PNG assets...")
    generate_all()
