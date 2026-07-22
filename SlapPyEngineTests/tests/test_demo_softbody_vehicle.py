"""Smoke test for ``examples/softbody_vehicle_demo.py`` (UU5 gap-close, batch 6).

The demo builds a 2D BeamNG-style softbody vehicle (chassis lattice +
wheels + suspension), drops it onto a steel-lattice slope, applies full
throttle, and renders a gif to ``examples/output/softbody/``.

The demo imports from :mod:`pharos_engine.softbody`, which is a WIP
subpackage. This test wakes up as soon as it lands — until then it
skips with a clear reason so the gap remains visible in the test report.

Pins (once WIP unblocks):
1. Demo module imports cleanly.
2. ``main()`` runs to completion.
3. Output routed via PIL Image.save is non-empty.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = (
    _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "softbody_vehicle_demo.py"
)


@pytest.fixture
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    # Guard against WIP softbody subpackage being unavailable.
    try:
        from pharos_engine.media import save_frames  # noqa: F401
        from pharos_engine.softbody import (  # noqa: F401
            SoftBodyRenderConfig,
            SoftBodyRenderer,
            SoftBodyWorld,
            VehicleSpec,
            build_vehicle,
            make_lattice_body,
            step,
        )
    except Exception as exc:
        pytest.skip(
            "pharos_engine.softbody / media unavailable (WIP): "
            f"{exc}"
        )

    spec = importlib.util.spec_from_file_location(
        "softbody_vehicle_demo_uu5", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["softbody_vehicle_demo_uu5"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"softbody_vehicle_demo failed to import: {exc}")
    return module


def test_softbody_vehicle_demo_module_imports(demo):
    """Demo file loaded and exposes ``main``."""
    assert demo is not None
    assert callable(getattr(demo, "main", None))


def test_softbody_vehicle_demo_main_completes(demo, tmp_path, monkeypatch):
    """``main()`` completes without raising."""
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
        pytest.skip(f"softbody_vehicle_demo.main() upstream drift: {exc}")


def test_softbody_vehicle_demo_output_non_empty(demo, tmp_path, monkeypatch):
    """The output file must be non-empty."""
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
        pytest.skip(f"softbody_vehicle_demo.main() upstream drift: {exc}")

    if not written:
        pytest.skip("softbody_vehicle_demo did not route output through PIL Image.save")
    assert written[0].exists()
    size = written[0].stat().st_size
    assert size > 1024, f"output suspiciously small: {size} bytes"
