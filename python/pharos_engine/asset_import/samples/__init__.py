"""Sample assets shipped with pharos_engine.asset_import for tests + docs."""
from __future__ import annotations

from pathlib import Path

SAMPLES_DIR = Path(__file__).parent
TRIANGLE_OBJ = SAMPLES_DIR / "triangle.obj"
TRIANGLE_MTL = SAMPLES_DIR / "triangle.mtl"
TRIANGLE_MTL_OBJ = SAMPLES_DIR / "triangle_mtl.obj"

__all__ = ["SAMPLES_DIR", "TRIANGLE_MTL", "TRIANGLE_MTL_OBJ", "TRIANGLE_OBJ"]
