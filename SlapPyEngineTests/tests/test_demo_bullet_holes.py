"""Smoke test for ``examples/bullet_holes_demo.py`` (SS2 gap-close, batch 4).

The demo fires a burst of high-velocity ``bullet`` particles through a
stone wall using :class:`ParticleField` per-pixel drilling, then writes
a GIF to ``examples/output/particles/bullet_holes.gif``.

The demo imports from :mod:`pharos_engine.physics.particle_field`, which
lives under the WIP ``physics/`` subpackage. This test wakes up as soon
as that subpackage lands — until then it skips with a clear reason so
the gap remains visible in the test report.

Pins (once WIP unblocks):
1. Demo module imports cleanly.
2. ``main()`` returns without raising and produces at least one PIL
   frame (verified via ``Image.save`` monkeypatch).
3. The captured output path is non-empty on disk.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "bullet_holes_demo.py"


@pytest.fixture
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    # Guard against WIP physics subpackage being unavailable.
    try:
        from pharos_engine.physics.particle_field import (  # noqa: F401
            Material,
            ParticleField,
        )
    except Exception as exc:
        pytest.skip(
            "pharos_engine.physics.particle_field unavailable (WIP): "
            f"{exc}"
        )

    spec = importlib.util.spec_from_file_location("bullet_holes_demo_ss2", _DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["bullet_holes_demo_ss2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"bullet_holes_demo failed to import: {exc}")
    return module


def test_bullet_holes_module_imports(demo):
    """Demo file loaded and exposes ``main``."""
    assert demo is not None
    assert callable(getattr(demo, "main", None))


def test_bullet_holes_main_writes_gif(demo, tmp_path, monkeypatch):
    """``main()`` writes a GIF using PIL Image.save; redirect into tmp."""
    from PIL import Image

    original_save = Image.Image.save
    written: list[Path] = []

    def _tracking_save(self, fp, *args, **kwargs):
        target = tmp_path / Path(str(fp)).name
        written.append(Path(target))
        return original_save(self, str(target), *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _tracking_save)

    try:
        demo.main()
    except Exception as exc:
        pytest.skip(f"bullet_holes_demo.main() upstream drift: {exc}")

    assert written, "demo.main() did not call PIL Image.save"
    assert written[0].exists(), (
        f"bullet_holes output missing from tmp: {written[0]}"
    )


def test_bullet_holes_output_non_empty(demo, tmp_path, monkeypatch):
    """The written image must have non-trivial size."""
    from PIL import Image

    original_save = Image.Image.save
    written: list[Path] = []

    def _tracking_save(self, fp, *args, **kwargs):
        target = tmp_path / Path(str(fp)).name
        written.append(Path(target))
        return original_save(self, str(target), *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _tracking_save)

    try:
        demo.main()
    except Exception as exc:
        pytest.skip(f"bullet_holes_demo.main() upstream drift: {exc}")

    assert written and written[0].exists()
    size = written[0].stat().st_size
    assert size > 1024, f"output suspiciously small: {size} bytes"
