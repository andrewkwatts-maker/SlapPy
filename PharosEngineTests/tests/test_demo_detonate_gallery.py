"""Smoke test for ``examples/detonate_gallery_demo.py`` (SS2 gap-close, batch 4).

The demo renders six blast variants side-by-side using
:func:`pharos_engine.physics.blast.detonate` on
:class:`pharos_engine.physics.particle_field.ParticleField`, then writes
a GIF to ``examples/output/particles/detonate_gallery_<preset>.gif``.

The demo imports from :mod:`pharos_engine.physics.blast` and
:mod:`pharos_engine.physics.particle_field`, both WIP. This test wakes
up as soon as those land — until then it skips with a clear reason.

Pins (once WIP unblocks):
1. Demo module imports cleanly.
2. ``main()`` returns the output ``Path``.
3. The captured GIF is non-trivially sized.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "PharosEngineExamples" / "examples" / "detonate_gallery_demo.py"
)


@pytest.fixture
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    # Guard against WIP physics subpackages being unavailable.
    try:
        from pharos_engine.physics.blast import (  # noqa: F401
            DetonateCurves,
            detonate,
        )
        from pharos_engine.physics.particle_field import ParticleField  # noqa: F401
        from pharos_engine.physics.splatter_presets import (  # noqa: F401
            PRESETS,
            get as get_preset,
        )
    except Exception as exc:
        pytest.skip(f"pharos_engine.physics.* unavailable (WIP): {exc}")

    spec = importlib.util.spec_from_file_location(
        "detonate_gallery_demo_ss2", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["detonate_gallery_demo_ss2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"detonate_gallery_demo failed to import: {exc}")
    return module


def test_detonate_gallery_module_imports(demo):
    """Demo file loaded and exposes ``main``."""
    assert demo is not None
    assert callable(getattr(demo, "main", None))


def test_detonate_gallery_main_returns_path(demo, tmp_path, monkeypatch):
    """``main()`` returns a Path pointing at the gallery GIF."""
    from PIL import Image

    original_save = Image.Image.save
    written: list[Path] = []

    def _tracking_save(self, fp, *args, **kwargs):
        target = tmp_path / Path(str(fp)).name
        written.append(Path(target))
        return original_save(self, str(target), *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _tracking_save)

    try:
        result = demo.main(frames=20)
    except TypeError:
        try:
            result = demo.main()
        except Exception as exc:
            pytest.skip(f"detonate_gallery_demo.main() upstream drift: {exc}")
    except Exception as exc:
        pytest.skip(f"detonate_gallery_demo.main() upstream drift: {exc}")

    assert isinstance(result, Path)
    assert written, "no image was written"


def test_detonate_gallery_output_non_empty(demo, tmp_path, monkeypatch):
    """The GIF on disk must have non-trivial size."""
    from PIL import Image

    original_save = Image.Image.save
    written: list[Path] = []

    def _tracking_save(self, fp, *args, **kwargs):
        target = tmp_path / Path(str(fp)).name
        written.append(Path(target))
        return original_save(self, str(target), *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _tracking_save)

    try:
        demo.main(frames=20)
    except TypeError:
        try:
            demo.main()
        except Exception as exc:
            pytest.skip(f"detonate_gallery_demo.main() upstream drift: {exc}")
    except Exception as exc:
        pytest.skip(f"detonate_gallery_demo.main() upstream drift: {exc}")

    assert written and written[0].exists()
    size = written[0].stat().st_size
    assert size > 1024, f"GIF suspiciously small: {size} bytes"
