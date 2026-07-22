"""Tests for ``examples/physics_projectile_demo.py``.

These exercise the public ``run_demo()`` entry point of the demo module
and assert the expected per-material outcomes:

  * The demo actually produces a GIF on disk.
  * Glass tears more than iron, which tears more than diamond.
  * Diamond's max damage stays well below the shatter threshold.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# The demo lives under examples/ which is *not* on the Python path by
# default.  Load it from its absolute path so this test file is
# self-contained.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEMO_PATH = _REPO_ROOT / "examples" / "legacy" / "physics_projectile_demo.py"


def _load_demo_module():
    """Import (or reuse) the demo module from its path on disk."""
    name = "_demo_physics_projectile_demo"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _DEMO_PATH)
    assert spec is not None and spec.loader is not None, (
        f"Cannot locate demo at {_DEMO_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# A single shared demo run -- the demo is moderately expensive (180
# frames × per-pixel substeps), so we cache the result across tests.
@pytest.fixture(scope="module")
def demo_result(tmp_path_factory):
    demo = _load_demo_module()
    out_dir = tmp_path_factory.mktemp("projectile_demo_output")
    return demo.run_demo(output_dir=out_dir, verbose=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_demo_runs(demo_result):
    """The demo runs end-to-end and produces a GIF + key-frame PNGs."""
    assert demo_result.gif_path.exists(), (
        f"GIF was not written to {demo_result.gif_path}"
    )
    assert demo_result.gif_path.stat().st_size > 0, "GIF on disk is empty"

    # All three key-frame PNGs should exist (matching KEY_FRAMES names).
    expected = {"projectile_pre_impact", "projectile_impact", "projectile_post_impact"}
    assert expected.issubset(set(demo_result.png_paths.keys())), (
        f"Missing key-frame PNGs; got {set(demo_result.png_paths.keys())}"
    )
    for name in expected:
        p = demo_result.png_paths[name]
        assert p.exists() and p.stat().st_size > 0, f"PNG {name} missing/empty at {p}"

    # Every plate has been recorded.
    materials = {pr.material for pr in demo_result.plates}
    assert materials == {"glass", "iron", "diamond"}


def test_glass_shatters_most(demo_result):
    """Severity ordering: glass tears more than iron tears, and iron is
    more damaged than diamond.

    The brittle path of the per-cell solver routes accumulated stress
    into the tear channel.  Glass has the lowest tear strength of the
    three so it accumulates massive tear and visible fragments.  Iron
    is ductile -- it routes stress into the *damage* channel (plastic
    strain) rather than tearing -- so we compare iron's damage to
    diamond's damage to establish the rest of the ordering.  Diamond's
    tear strength is essentially infinite so it stays nearly pristine.
    """
    glass = demo_result.by_material("glass")
    iron = demo_result.by_material("iron")
    diamond = demo_result.by_material("diamond")

    # Glass tears, iron does not (iron is ductile).
    assert glass.max_tear > iron.max_tear, (
        f"Expected glass tear > iron tear; got glass={glass.max_tear:.4f} "
        f"iron={iron.max_tear:.4f}"
    )
    # Glass tears even harder than diamond does.
    assert glass.max_tear > diamond.max_tear, (
        f"Expected glass tear > diamond tear; got glass={glass.max_tear:.4f} "
        f"diamond={diamond.max_tear:.4f}"
    )
    # Iron, being softer than diamond, accumulates more plastic damage.
    assert iron.max_damage > diamond.max_damage, (
        f"Expected iron damage > diamond damage; got iron={iron.max_damage:.4f} "
        f"diamond={diamond.max_damage:.4f}"
    )
    # And glass must visibly fragment in the cell-bond field.
    assert glass.fragment_count > 1, (
        f"Glass should have fragmented; cc_label count={glass.fragment_count}"
    )


def test_diamond_survives_intact(demo_result):
    """Diamond's max damage stays well below the shatter threshold."""
    diamond = demo_result.by_material("diamond")
    # Import the threshold constant from the demo so this test stays in
    # sync if the demo author tunes it later.
    demo = _load_demo_module()
    threshold = demo.DIAMOND_DAMAGE_INTACT_THRESHOLD
    assert diamond.max_damage < threshold, (
        f"Diamond should be intact (damage<{threshold}); got {diamond.max_damage:.4f}"
    )
