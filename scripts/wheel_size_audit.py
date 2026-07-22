"""Sprint 10 wheel-size audit.

Verifies the built wheels satisfy the plan's per-package size ceilings::

    pharos-engine   <=  5 MB
    pharos-editor   <= 20 MB

Usage::

    python scripts/wheel_size_audit.py dist/
    python scripts/wheel_size_audit.py dist/pharos_engine-0.3.0.tar.gz  # single file

Exit 0 when every wheel found is under its ceiling; non-zero when any
wheel exceeds.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


LIMITS_MB: dict[str, float] = {
    "pharos-engine": 5.0,
    "pharos_engine": 5.0,
    "pharos-editor": 20.0,
    "pharos_editor": 20.0,
}


def _package_key(name: str) -> str | None:
    stem = name.split("-")[0].lower()
    return stem if stem in LIMITS_MB else None


def _iter_wheels(target: Path):
    if target.is_file():
        yield target
        return
    for pattern in ("*.whl", "*.tar.gz"):
        for p in sorted(target.glob(pattern)):
            yield p


def main() -> int:
    parser = argparse.ArgumentParser(description="Pharos wheel-size audit")
    parser.add_argument("target", type=Path, help="dist/ directory or a single wheel")
    args = parser.parse_args()

    if not args.target.exists():
        raise SystemExit(f"target not found: {args.target}")

    over: list[tuple[str, float, float]] = []
    total = 0
    for wheel in _iter_wheels(args.target):
        total += 1
        pkg = _package_key(wheel.name)
        if pkg is None:
            print(f"[skip] {wheel.name}: no limit registered")
            continue
        limit_mb = LIMITS_MB[pkg]
        size_mb = wheel.stat().st_size / (1024 * 1024)
        marker = "OK " if size_mb <= limit_mb else "BAD"
        print(f"{marker} {wheel.name:50s}  {size_mb:7.2f} MB  (<= {limit_mb:5.1f} MB)")
        if size_mb > limit_mb:
            over.append((wheel.name, size_mb, limit_mb))

    if total == 0:
        raise SystemExit("no wheels or sdists found under the target")

    if over:
        print(f"\nwheel_size_audit: {len(over)} wheel(s) exceed their per-package ceiling")
        return 1
    print("\nwheel_size_audit: all wheels within ceilings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
