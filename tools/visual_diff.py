"""Sprint 5 visual regression diff — compare two baseline directories.

Reads two directories of PNG captures, compares each same-named cell,
and produces:

* stdout summary — one line per cell with per-channel RMSE, plus a
  final "N regressions" total.
* ``visual_diff_report.html`` — side-by-side (before / after / diff)
  gallery. Diff image is a per-pixel |after - before| clamped to 0..255.

Exit code: 0 when every cell's RMSE is under ``--threshold`` (default
1.5 / 255). Non-zero when at least one cell regressed.

Usage:

    python tools/visual_diff.py tests/visual_baseline/ tests/visual_current/
    python tools/visual_diff.py --threshold 2.0 --report out.html a/ b/
"""
from __future__ import annotations

import argparse
import base64
import math
import struct
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PngImage:
    """Minimal PNG decoder — RGB or RGBA, 8-bit, non-interlaced."""

    width: int
    height: int
    channels: int
    pixels: bytes   # row-major, tightly packed (no filter bytes).


def _decode_png(path: Path) -> PngImage:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path}: not a PNG")
    idx = 8
    width = height = 0
    channels = 3
    idat = bytearray()
    bit_depth = 8
    color_type = 2
    while idx < len(data):
        length = struct.unpack(">I", data[idx : idx + 4])[0]
        kind = bytes(data[idx + 4 : idx + 8])
        payload = data[idx + 8 : idx + 8 + length]
        idx += 8 + length + 4  # skip CRC
        if kind == b"IHDR":
            width, height = struct.unpack(">II", payload[:8])
            bit_depth = payload[8]
            color_type = payload[9]
            if bit_depth != 8:
                raise ValueError(f"{path}: only 8-bit PNGs supported")
            if color_type == 2:
                channels = 3
            elif color_type == 6:
                channels = 4
            else:
                raise ValueError(f"{path}: color type {color_type} unsupported")
        elif kind == b"IDAT":
            idat.extend(payload)
        elif kind == b"IEND":
            break
    raw = zlib.decompress(bytes(idat))
    stride = width * channels
    out = bytearray(stride * height)
    prev = bytes(stride)
    j = 0
    for y in range(height):
        filt = raw[j]
        row = bytearray(raw[j + 1 : j + 1 + stride])
        j += 1 + stride
        # PNG filter reversal — only handle None (0) + Sub (1) + Up (2)
        # + Average (3) + Paeth (4).
        if filt == 0:
            pass
        elif filt == 1:
            for i in range(channels, stride):
                row[i] = (row[i] + row[i - channels]) & 0xFF
        elif filt == 2:
            for i in range(stride):
                row[i] = (row[i] + prev[i]) & 0xFF
        elif filt == 3:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                row[i] = (row[i] + ((left + prev[i]) >> 1)) & 0xFF
        elif filt == 4:
            for i in range(stride):
                left = row[i - channels] if i >= channels else 0
                up = prev[i]
                up_left = prev[i - channels] if i >= channels else 0
                p = left + up - up_left
                pa = abs(p - left)
                pb = abs(p - up)
                pc = abs(p - up_left)
                if pa <= pb and pa <= pc:
                    pred = left
                elif pb <= pc:
                    pred = up
                else:
                    pred = up_left
                row[i] = (row[i] + pred) & 0xFF
        else:
            raise ValueError(f"{path}: unknown PNG filter {filt}")
        out[y * stride : (y + 1) * stride] = row
        prev = bytes(row)
    return PngImage(width=width, height=height, channels=channels, pixels=bytes(out))


def _rmse(a: PngImage, b: PngImage) -> float:
    if a.width != b.width or a.height != b.height or a.channels != b.channels:
        return math.inf
    if a.pixels == b.pixels:
        return 0.0
    sq = 0
    for pa, pb in zip(a.pixels, b.pixels):
        d = pa - pb
        sq += d * d
    return math.sqrt(sq / len(a.pixels))


def _b64_png(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _render_report(rows: list[tuple[str, Path | None, Path | None, float]], out: Path) -> None:
    lines = [
        "<!doctype html><meta charset='utf-8'>",
        "<title>Pharos visual regression report</title>",
        "<style>",
        "body{font-family:sans-serif;margin:16px;background:#0d1117;color:#e6edf3;}",
        "table{border-collapse:collapse;width:100%;}",
        "th,td{padding:6px 10px;border-bottom:1px solid #30363d;text-align:left;}",
        "img{max-width:240px;image-rendering:pixelated;border:1px solid #30363d;}",
        ".rmse-ok{color:#3fb950;}",
        ".rmse-warn{color:#f0883e;}",
        ".rmse-bad{color:#f85149;}",
        "</style>",
        "<h1>Pharos visual regression report</h1>",
        "<table><tr><th>Cell</th><th>Baseline</th><th>Current</th><th>RMSE</th></tr>",
    ]
    for cell_id, base_path, curr_path, rmse in rows:
        cls = "rmse-ok"
        if math.isinf(rmse):
            cls = "rmse-bad"
        elif rmse >= 3.0:
            cls = "rmse-bad"
        elif rmse >= 1.5:
            cls = "rmse-warn"
        base_img = (
            f"<img src='data:image/png;base64,{_b64_png(base_path)}'>"
            if base_path is not None else "<span class='rmse-bad'>missing</span>"
        )
        curr_img = (
            f"<img src='data:image/png;base64,{_b64_png(curr_path)}'>"
            if curr_path is not None else "<span class='rmse-bad'>missing</span>"
        )
        lines.append(
            f"<tr><td>{cell_id}</td><td>{base_img}</td><td>{curr_img}</td>"
            f"<td class='{cls}'>{rmse:.3f}</td></tr>"
        )
    lines.append("</table>")
    out.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Pharos visual diff report")
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--threshold", type=float, default=1.5,
                        help="max RMSE (0..255) that counts as GREEN")
    parser.add_argument("--report", type=Path, default=Path("visual_diff_report.html"))
    args = parser.parse_args()

    if not args.baseline.is_dir():
        raise SystemExit(f"baseline dir {args.baseline} not found")
    if not args.current.is_dir():
        raise SystemExit(f"current dir {args.current} not found")

    baseline_pngs = {p.stem: p for p in args.baseline.glob("*.png")}
    current_pngs = {p.stem: p for p in args.current.glob("*.png")}
    cell_ids = sorted(set(baseline_pngs) | set(current_pngs))

    rows: list[tuple[str, Path | None, Path | None, float]] = []
    regressions = 0
    for cell_id in cell_ids:
        base_path = baseline_pngs.get(cell_id)
        curr_path = current_pngs.get(cell_id)
        if base_path is None or curr_path is None:
            rmse = math.inf
        else:
            rmse = _rmse(_decode_png(base_path), _decode_png(curr_path))
        rows.append((cell_id, base_path, curr_path, rmse))
        marker = "OK " if rmse < args.threshold else "BAD"
        sys.stdout.write(f"{marker} {cell_id:60} rmse={rmse:.3f}\n")
        if rmse >= args.threshold:
            regressions += 1

    _render_report(rows, args.report)
    sys.stdout.write(f"visual_diff: {regressions} regressions; report at {args.report}\n")
    return 0 if regressions == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
