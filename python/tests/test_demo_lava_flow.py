"""Tests for the lava-flow physics demo.

These exercise the wired-up ``BoundaryExchange`` thermal pass via the
``PhysicsWorld.step()`` loop and confirm the demo's authored assertions:
mass conservation, lava cooling, ice warming at the contact zone, and GIF
emission.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


# Make the example directory importable regardless of the working dir
# pytest is launched from.  The demo lives next to other examples.
_EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples" / "legacy"
if str(_EXAMPLES_DIR) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_DIR))


_IDX_DENSITY = 9
_IDX_HEAT = 12


@pytest.fixture(scope="module")
def demo_metrics():
    """Run the demo once and reuse its metrics across the test module.

    We save the GIF here (the ``test_demo_runs`` case asserts on it); the
    cooling/warming/mass tests reuse the same per-frame arrays so we do
    not pay for a 300-frame simulation more than once.
    """
    import physics_lava_flow_demo as demo

    metrics = demo.run_demo(save_gif=True)
    return metrics


def test_demo_runs(demo_metrics):
    """The demo executes end-to-end and writes its GIF."""
    out = demo_metrics["output_path"]
    assert out is not None, "demo did not return an output path"
    assert Path(out).exists(), f"expected GIF at {out}"
    assert Path(out).stat().st_size > 0, "GIF is empty"
    # Each frame must be an RGBA image (H, W, 4).
    frames = demo_metrics["frames"]
    assert len(frames) == len(demo_metrics["lava_heat"]) > 0
    assert frames[0].ndim == 3 and frames[0].shape[-1] == 4


def test_lava_cools_over_time(demo_metrics):
    """Lava max heat at frame 250 is below its initial value.

    BoundaryExchange siphons heat into the (cold) ice on contact; surface
    radiance (``emissivity``) also cools the open face.  Either way, the
    blob should be measurably cooler well before the run ends.
    """
    lava_heat = demo_metrics["lava_heat"]
    initial = demo_metrics["initial_lava_heat"]
    assert len(lava_heat) >= 251, "demo too short to assert frame 250"
    assert lava_heat[250] < initial, (
        f"lava did not cool by frame 250: start={initial} "
        f"frame250={lava_heat[250]}"
    )


def test_ice_warms_at_contact(demo_metrics):
    """Ice contact-zone max heat rises above 1.0 by frame 200.

    The ice slab starts at heat = 0 (default ``initial_heat`` for the
    ICE preset).  A non-zero reading at the contact zone proves heat
    crossed the seam via BoundaryExchange.  The spec phrasing is "by
    frame 200" — i.e. the contact-zone peak heat seen during the first
    200 frames; ice's high ``thermal_k`` smears any single-frame spike
    very quickly so we check the running peak, not the instantaneous
    sample at exactly frame 200.
    """
    ice_heat = demo_metrics["ice_heat"]
    assert len(ice_heat) >= 201, "demo too short to assert frame 200"
    peak_by_200 = max(ice_heat[: 201])
    assert peak_by_200 > 1.0, (
        f"ice did not warm via BoundaryExchange: peak over first 200 "
        f"frames was {peak_by_200}"
    )


def test_total_mass_conserved(demo_metrics):
    """Σ density × ρ_mat × cell_area is preserved within 0.1%.

    Heat exchange MUST NOT mutate the density channel (it operates on
    the heat channel only).  Any drift here flags a leak from the
    seam-exchange path into the mass integral.
    """
    total = demo_metrics["total_mass"]
    assert len(total) > 0
    m0 = total[0]
    assert m0 > 0.0, "initial world mass must be positive"
    arr = np.asarray(total, dtype=np.float64)
    drift = np.abs(arr - m0).max() / m0
    assert drift < 1e-3, (
        f"mass conservation violated: max drift {drift:.6f} "
        f"(start={m0}, min={arr.min()}, max={arr.max()})"
    )
