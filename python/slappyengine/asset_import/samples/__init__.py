"""Sample assets shipped with slappyengine.asset_import for tests + docs."""
from __future__ import annotations

from pathlib import Path

SAMPLES_DIR = Path(__file__).parent
TRIANGLE_OBJ = SAMPLES_DIR / "triangle.obj"

__all__ = ["SAMPLES_DIR", "TRIANGLE_OBJ"]
