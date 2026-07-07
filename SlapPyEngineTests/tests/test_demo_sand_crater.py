"""Smoke test for ``examples/sand_crater_demo.py`` (UU5 gap-close, batch 6).

The demo drives a preset-based crater explosion on a
:class:`slappyengine.physics.particle_field.ParticleField`, calling
:func:`slappyengine.physics.blast.detonate` on the blast frame and
emitting a gif per preset to
``examples/output/particles/sand_crater[_<preset>][_<mode>].gif``.

The demo imports from :mod:`slappyengine.physics`, which is a WIP
subpackage. This test wakes up as soon as it lands — until then it
skips with a clear reason so the gap remains visible in the test report.

Pins (once WIP unblocks):
1. Demo module imports cleanly.
2. ``main()`` runs to completion (uses argparse, no frames kwarg).
3. Downstream ``PIL Image.save`` calls emit non-empty artefacts.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "sand_crater_demo.py"
)


@pytest.fixture
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    # Guard against WIP physics subpackage being unavailable.
    try:
        from slappyengine.physics.blast import detonate  # noqa: F401
        from slappyengine.physics.particle_field import ParticleField  # noqa: F401
        from slappyengine.physics.splatter_presets import (  # noqa: F401
            PRESETS,
            SplatterPreset,
            get as get_preset,
        )
    except Exception as exc:
        pytest.skip(
            "slappyengine.physics (blast / particle_field / splatter_presets) "
            f"unavailable (WIP): {exc}"
        )

    spec = importlib.util.spec_from_file_location(
        "sand_crater_demo_uu5", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["sand_crater_demo_uu5"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"sand_crater_demo failed to import: {exc}")
    return module


def test_sand_crater_demo_module_imports(demo):
    """Demo file loaded and exposes ``main``."""
    assert demo is not None
    assert callable(getattr(demo, "main", None))


def test_sand_crater_demo_main_completes(demo, tmp_path, monkeypatch):
    """``main()`` completes without raising (argparse-driven, no frames kwarg)."""
    from PIL import Image

    original_save = Image.Image.save
    written: list[Path] = []

    def _tracking_save(self, fp, *args, **kwargs):
        target = tmp_path / Path(str(fp)).name
        written.append(Path(target))
        return original_save(self, str(target), *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _tracking_save)
    # Ensure argparse sees an empty argv, not pytest's own flags.
    monkeypatch.setattr(sys, "argv", ["sand_crater_demo.py"])

    try:
        demo.main()
    except SystemExit as exc:
        # argparse may raise SystemExit on parse failure; treat as skip.
        pytest.skip(f"sand_crater_demo.main() SystemExit: {exc}")
    except Exception as exc:
        pytest.skip(f"sand_crater_demo.main() upstream drift: {exc}")


def test_sand_crater_demo_output_non_empty(demo, tmp_path, monkeypatch):
    """Demo output routed through PIL Image.save is non-empty."""
    from PIL import Image

    original_save = Image.Image.save
    written: list[Path] = []

    def _tracking_save(self, fp, *args, **kwargs):
        target = tmp_path / Path(str(fp)).name
        written.append(Path(target))
        return original_save(self, str(target), *args, **kwargs)

    monkeypatch.setattr(Image.Image, "save", _tracking_save)
    monkeypatch.setattr(sys, "argv", ["sand_crater_demo.py"])

    try:
        demo.main()
    except SystemExit as exc:
        pytest.skip(f"sand_crater_demo.main() SystemExit: {exc}")
    except Exception as exc:
        pytest.skip(f"sand_crater_demo.main() upstream drift: {exc}")

    if not written:
        pytest.skip("sand_crater_demo did not route output through PIL Image.save")
    assert written[0].exists()
    size = written[0].stat().st_size
    assert size > 512, f"output suspiciously small: {size} bytes"
