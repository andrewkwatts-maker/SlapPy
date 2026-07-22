"""Sprint 5 visual capture harness — drives pharos-headless per matrix cell.

Reads ``tools/visual_capture/matrix.yaml`` and, for each cell in the
requested suite, invokes the ``pharos-headless`` binary with the cell's
scene / camera / preset. Saves the RGBA PNG to
``tests/visual_baseline/<cell_id>.png`` and a SHA-256 hash to
``tests/visual_baseline/<cell_id>.hash``.

When ``pharos-headless`` is not on the PATH (or the wgpu adapter fails
to bind on a headless CI runner), the harness falls back to a
deterministic synthetic PNG derived from the cell id so plumbing tests
still pass without a GPU. Downstream diff runs against real captures
will trip on any synthetic baseline (that's the point — CI without a
GPU cannot regress a visual we never captured).

Usage:

    python tools/visual_capture/run.py --suite smoke
    python tools/visual_capture/run.py --suite full --out tests/visual_baseline
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path
from typing import Any

# yaml is a first-party dep for the engine, but the harness is small
# enough that we degrade gracefully if it's missing on a bare CI runner.
try:
    import yaml
except ImportError:  # pragma: no cover - environment issue
    yaml = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[2]
MATRIX_PATH = Path(__file__).resolve().parent / "matrix.yaml"


def _load_matrix() -> dict[str, Any]:
    if yaml is None:
        raise SystemExit("PyYAML is required to run the visual harness")
    with MATRIX_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _split_cell_id(cell_id: str) -> tuple[str, str, str]:
    parts = cell_id.split("__")
    if len(parts) != 3:
        raise ValueError(f"cell id must be scene__preset__camera; got {cell_id!r}")
    return parts[0], parts[1], parts[2]


def _synthetic_png(cell_id: str, width: int = 128, height: int = 72) -> bytes:
    """Return a deterministic checkerboard PNG derived from the cell id.

    Used as a placeholder when ``pharos-headless`` is unavailable. The
    checkerboard colour is seeded by SHA-256 of the id so two runs on
    the same cell produce the same bytes (baseline hashes stay stable).
    """
    seed = hashlib.sha256(cell_id.encode("utf-8")).digest()
    r, g, b = seed[0], seed[1], seed[2]

    def _chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            checker = ((x >> 3) ^ (y >> 3)) & 1
            row.append(r if checker else max(0, r - 40))
            row.append(g if checker else max(0, g - 40))
            row.append(b if checker else max(0, b - 40))
        rows.append(bytes(row))
    idat = zlib.compress(b"".join(rows), level=6)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", idat)
        + _chunk(b"IEND", b"")
    )


def _find_headless() -> str | None:
    exe = shutil.which("pharos-headless")
    if exe:
        return exe
    for candidate in (
        ROOT / "target" / "release" / "pharos-headless",
        ROOT / "target" / "debug" / "pharos-headless",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def _capture_cell(
    cell_id: str,
    matrix: dict[str, Any],
    out_dir: Path,
    headless: str | None,
) -> tuple[Path, Path, bool]:
    scene, preset, camera = _split_cell_id(cell_id)
    scenes = matrix.get("cells", {})
    if scene not in scenes:
        raise SystemExit(f"unknown scene {scene!r} in cell {cell_id!r}")
    scene_yaml = ROOT / scenes[scene]["scene_yaml"]
    cameras = matrix.get("cameras", {})
    if camera not in cameras:
        raise SystemExit(f"unknown camera {camera!r} in cell {cell_id!r}")

    png_path = out_dir / f"{cell_id}.png"
    hash_path = out_dir / f"{cell_id}.hash"
    real_capture = False

    if headless is not None and scene_yaml.exists():
        # Real capture path. pharos-headless takes:
        #   --scene <yaml> --preset <name> --camera x,y,z --out <png>
        cam_flag = ",".join(f"{v}" for v in cameras[camera])
        cmd = [
            headless,
            "--scene", str(scene_yaml),
            "--preset", preset,
            "--camera", cam_flag,
            "--out", str(png_path),
        ]
        try:
            subprocess.run(cmd, check=True, timeout=120)
            real_capture = True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            sys.stderr.write(f"pharos-headless failed for {cell_id}: {e}\n")
            png_path.write_bytes(_synthetic_png(cell_id))
    else:
        # Fallback: deterministic synthetic PNG. This lets the plumbing
        # test (`--suite smoke` in CI) verify the harness itself works
        # without needing a live GPU adapter.
        png_path.write_bytes(_synthetic_png(cell_id))

    digest = hashlib.sha256(png_path.read_bytes()).hexdigest()
    hash_path.write_text(digest + "\n", encoding="utf-8")
    return png_path, hash_path, real_capture


def main() -> int:
    parser = argparse.ArgumentParser(description="Pharos visual capture harness")
    parser.add_argument("--suite", default="smoke", help="matrix suite to run")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "tests" / "visual_baseline",
        help="output baseline directory",
    )
    args = parser.parse_args()

    matrix = _load_matrix()
    suites = matrix.get("suites", {})
    if args.suite not in suites:
        raise SystemExit(f"unknown suite {args.suite!r}; expected one of {list(suites)}")

    args.out.mkdir(parents=True, exist_ok=True)
    headless = _find_headless()

    total = 0
    real = 0
    for cell_id in suites[args.suite]:
        _, _, real_capture = _capture_cell(cell_id, matrix, args.out, headless)
        total += 1
        real += int(real_capture)
    sys.stdout.write(
        f"visual_capture: wrote {total} cells to {args.out} "
        f"({real} real, {total - real} synthetic)\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
