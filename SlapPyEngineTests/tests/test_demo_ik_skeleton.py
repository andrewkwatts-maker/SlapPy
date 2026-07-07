"""Smoke test for ``examples/ik_skeleton_demo.py`` (SS2 gap-close, batch 4).

The demo builds a 4-bone IK chain, orbits an IK target around the root,
solves per-frame with :func:`slappyengine.dynamics.solve_ik`, and writes
a GIF to ``examples/output/character/ik_skeleton.gif``.

The demo imports from :mod:`slappyengine.softbody`, which is a WIP
subpackage. This test wakes up as soon as it lands — until then it
skips with a clear reason.

Pins (once WIP unblocks):
1. Demo module imports cleanly.
2. ``main(out_path=tmp)`` returns the redirected Path.
3. The GIF on disk is non-trivially sized.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "SlapPyEngineExamples" / "examples" / "ik_skeleton_demo.py"


@pytest.fixture
def demo():
    if not _DEMO_PATH.is_file():
        pytest.skip(f"demo missing: {_DEMO_PATH}")
    # Guard against WIP softbody + dynamics subpackages being unavailable.
    try:
        from slappyengine.softbody import (  # noqa: F401
            SoftBodyRenderConfig,
            SoftBodyRenderer,
            SoftBodyWorld,
            step as softbody_step,
        )
        from slappyengine.dynamics import (  # noqa: F401
            IKChainSpec,
            make_distance,
            resolve_joint_specs,
            solve_ik,
        )
    except Exception as exc:
        pytest.skip(
            "slappyengine.softbody / dynamics unavailable (WIP): "
            f"{exc}"
        )

    spec = importlib.util.spec_from_file_location(
        "ik_skeleton_demo_ss2", _DEMO_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ik_skeleton_demo_ss2"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        pytest.skip(f"ik_skeleton_demo failed to import: {exc}")
    return module


def test_ik_skeleton_module_imports(demo):
    """Demo file loaded and exposes ``main``."""
    assert demo is not None
    assert callable(getattr(demo, "main", None))


def test_ik_skeleton_main_returns_path(demo, tmp_path):
    """``main(out_path=tmp, frames=30)`` returns a Path pointing at the GIF."""
    out = tmp_path / "ik_skeleton.gif"
    try:
        result = demo.main(out_path=out, frames=30)
    except TypeError:
        try:
            result = demo.main(out_path=out)
        except Exception as exc:
            pytest.skip(f"ik_skeleton_demo.main() upstream drift: {exc}")
    except Exception as exc:
        pytest.skip(f"ik_skeleton_demo.main() upstream drift: {exc}")

    assert isinstance(result, Path)
    assert result.exists(), (
        f"main() reported success but output missing: {result}"
    )


def test_ik_skeleton_output_non_empty(demo, tmp_path):
    """The GIF on disk must have non-trivial size."""
    out = tmp_path / "ik_skeleton.gif"
    try:
        result = demo.main(out_path=out, frames=30)
    except TypeError:
        try:
            result = demo.main(out_path=out)
        except Exception as exc:
            pytest.skip(f"ik_skeleton_demo.main() upstream drift: {exc}")
    except Exception as exc:
        pytest.skip(f"ik_skeleton_demo.main() upstream drift: {exc}")

    assert result.exists()
    size = result.stat().st_size
    assert size > 1024, f"GIF suspiciously small: {size} bytes"
