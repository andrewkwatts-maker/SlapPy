"""Layer-ordering invariant for humanoid flesh wrapping.

`wrap_in_flesh` must order each beam's endpoints so that ``node_a`` has
the layer >= ``node_b``. Damage classifiers attribute a broken beam by
``nodes.layer[node_a]``, so muscle↔skin beams must be labelled by the
skin endpoint (layer 2), and bone↔muscle beams by the muscle endpoint
(layer 1) — not by the underlying bone.

If this invariant is violated, all flesh damage collapses onto the bone
layer and the per-layer destruction breakdown is meaningless.
"""
from __future__ import annotations

import numpy as np

from slappyengine.dynamics import make_humanoid, wrap_in_flesh
from slappyengine.softbody import SoftBodyWorld


def test_flesh_beams_node_a_has_higher_or_equal_layer():
    w = SoftBodyWorld()
    skel = make_humanoid(w, root_position=(0.0, 1.0))
    beam_start_before_flesh = w.beams.count
    wrap_in_flesh(w, skel, muscle_offset=0.10, skin_offset=0.18)
    beam_end = w.beams.count
    assert beam_end > beam_start_before_flesh, (
        "wrap_in_flesh should append at least one beam"
    )

    a = w.beams.node_a[beam_start_before_flesh:beam_end].astype(np.int64)
    b = w.beams.node_b[beam_start_before_flesh:beam_end].astype(np.int64)
    layer_a = w.nodes.layer[a]
    layer_b = w.nodes.layer[b]
    # Invariant: node_a's layer >= node_b's layer for every flesh beam.
    assert np.all(layer_a >= layer_b), (
        f"flesh beam endpoints not layer-ordered: "
        f"violations={int((layer_a < layer_b).sum())} of {len(layer_a)} beams"
    )


def test_flesh_beams_cover_all_three_layers():
    """Sanity: after wrap_in_flesh, the new beams should classify into
    at least muscle (1) and skin (2) when labelled by ``layer[node_a]``."""
    w = SoftBodyWorld()
    skel = make_humanoid(w, root_position=(0.0, 1.0))
    beam_start = w.beams.count
    wrap_in_flesh(w, skel, muscle_offset=0.10, skin_offset=0.18)
    beam_end = w.beams.count

    a = w.beams.node_a[beam_start:beam_end].astype(np.int64)
    layers = set(int(la) for la in w.nodes.layer[a].tolist())
    # Bone↔muscle beams classify as muscle (1); muscle↔skin beams as skin (2).
    # Bone-only beams are NOT created by wrap_in_flesh, so layer 0 may or may
    # not appear depending on whether the SoA preserved it — but layers 1 and
    # 2 MUST be present.
    assert 1 in layers, f"no muscle-labelled flesh beam: layers={layers}"
    assert 2 in layers, f"no skin-labelled flesh beam: layers={layers}"
