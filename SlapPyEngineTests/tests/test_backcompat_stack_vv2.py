"""Regression tests for VV2's backwards-compat shim stack.

Follows up on UU2 (`test_event_bus_backcompat.py`) and UU3's
`docs/game_compat_2026_07_07.md` § 9.4 residual game-compat list. This
file locks in the four shims VV2 landed so downstream games (Ochema
Circuit + Bullet Strata) keep importing / running against
`slappyengine.*`:

1. ``event_bus.EventDetails`` — legacy payload-dict type alias.
2. ``config.DeformConfig`` + ``config._parse_deform`` — legacy deform
   YAML block dataclass and its parser.
3. ``config.Config.deform`` — root config field of type
   :class:`DeformConfig`.
4. ``components.DeformableLayerComponent(**legacy_kwargs)`` — swallow
   ``spring_decay`` / ``strength_map`` / ``material_preset`` /
   ``sim_mode`` / ``destroy_mode`` kwargs from Ochema's per-class deform
   loader without raising ``TypeError``.
5. ``collision_pixel.PixelCollisionPass.test(entity_a, entity_b)`` —
   legacy 2-entity class-level form that drives a CPU alpha-overlap
   check when no GPU context is available.

If any of these regress, downstream games break at collection time. Do
NOT remove without a v1.0 deprecation cycle. (VV2)
"""
from __future__ import annotations

import dataclasses
import numpy as np
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Item 1 — event_bus.EventDetails
# ---------------------------------------------------------------------------

def test_event_bus_event_details_importable():
    """`from slappyengine.event_bus import EventDetails` resolves."""
    from slappyengine.event_bus import EventDetails
    # It is a type alias for dict[str, Any]. We do not lock the exact
    # generic form so future refactors can widen without breaking us,
    # but it must be usable as a type hint and behave dict-shaped.
    assert EventDetails is not None
    # Ensure a plain dict is a valid "instance" for downstream annotators.
    payload: EventDetails = {"speed": 42.0, "gear": 3}  # type: ignore[valid-type]
    assert payload["speed"] == 42.0


# ---------------------------------------------------------------------------
# Item 2 — config.DeformConfig + _parse_deform
# ---------------------------------------------------------------------------

def test_deform_config_defaults_match_legacy_yaml():
    """DeformConfig() reports F1-era defaults for every legacy field."""
    from slappyengine.config import DeformConfig
    dc = DeformConfig()
    assert dc.sim_mode == "collision_triggered"
    assert dc.decay_mode == "curve"
    assert dc.spring_decay == pytest.approx(0.94)
    assert dc.material_preset == "metal"
    assert dc.crack_mode == "none"
    assert dc.destroy_mode == "persist"
    assert dc.physics_coupling == "isolated"
    assert dc.repair_mode == "event_only"
    assert dc.sim_frequency == "every_frame"
    assert dc.n_frames_skip == 4
    assert dc.budget_ms_per_frame == pytest.approx(2.0)
    assert "Deform.Impact" in dc.emit_events
    assert "Deform.Destroyed" in dc.emit_events
    assert len(dc.emit_events) == 6
    assert dc.critical_damage_threshold == pytest.approx(0.3)
    # decay_curve is a list of [time_s, rate] pairs.
    for time_s, rate in dc.decay_curve:
        assert 0.0 <= time_s <= 10.0
        assert 0.0 < rate <= 1.0


def test_parse_deform_maps_partial_dict_and_keeps_defaults():
    """_parse_deform overrides supplied keys, keeps defaults for the rest."""
    from slappyengine.config import DeformConfig, _parse_deform
    raw = {
        "sim_mode": "always_on",
        "spring_decay": 0.88,
        "crack_mode": "radial",
        "crack_count": 3,
        "critical_damage_threshold": 0.2,
    }
    dc = _parse_deform(raw)
    defaults = DeformConfig()

    assert dc.sim_mode == "always_on"
    assert dc.spring_decay == pytest.approx(0.88)
    assert dc.crack_mode == "radial"
    assert dc.crack_count == 3
    assert dc.critical_damage_threshold == pytest.approx(0.2)
    # Unspecified fields retain defaults.
    assert dc.destroy_mode == defaults.destroy_mode
    assert dc.repair_mode == defaults.repair_mode
    assert dc.material_preset == defaults.material_preset


def test_parse_deform_empty_dict_all_defaults():
    from slappyengine.config import DeformConfig, _parse_deform
    dc = _parse_deform({})
    d = DeformConfig()
    assert dc.sim_mode == d.sim_mode
    assert dc.spring_decay == pytest.approx(d.spring_decay)
    assert dc.crack_mode == d.crack_mode
    assert dc.destroy_mode == d.destroy_mode


# ---------------------------------------------------------------------------
# Item 3 — Config.deform field
# ---------------------------------------------------------------------------

def test_config_has_deform_field_typed_as_deform_config():
    """Root Config exposes a `deform: DeformConfig` field."""
    from slappyengine.config import Config, DeformConfig
    fields = {f.name: f for f in dataclasses.fields(Config)}
    assert "deform" in fields
    field = fields["deform"]
    # dataclass fields may report the type as a string when __future__
    # annotations is active — accept either form.
    assert field.type is DeformConfig or "DeformConfig" in str(field.type)


# ---------------------------------------------------------------------------
# Item 4 — DeformableLayerComponent legacy kwargs
# ---------------------------------------------------------------------------

def test_deformable_layer_component_swallows_legacy_kwargs():
    """Ochema's per-class deform kwargs (spring_decay etc.) don't raise."""
    from slappyengine.components import DeformableLayerComponent
    comp = DeformableLayerComponent(
        layer=None,
        elastic_threshold=70.0,
        spring_decay=0.88,
        strength_map=None,
        material_preset="rubber",
        sim_mode="always_on",
        destroy_mode="fragment",
    )
    # Legacy kwargs are exposed as plain attributes so downstream code
    # that reads them post-construction still works.
    assert comp.elastic_threshold == pytest.approx(70.0)
    assert comp.spring_decay == pytest.approx(0.88)
    assert comp.material_preset == "rubber"
    assert comp.sim_mode == "always_on"
    assert comp.destroy_mode == "fragment"
    assert comp.strength_map is None


def test_deformable_layer_component_legacy_defaults():
    """Omitting legacy kwargs falls back to F1-era defaults."""
    from slappyengine.components import DeformableLayerComponent
    comp = DeformableLayerComponent(layer=None)
    assert comp.spring_decay == pytest.approx(0.94)
    assert comp.material_preset == "metal"
    assert comp.sim_mode == "collision_triggered"
    assert comp.destroy_mode == "persist"


# ---------------------------------------------------------------------------
# Item 5 — PixelCollisionPass.test(entity_a, entity_b) legacy classmethod form
# ---------------------------------------------------------------------------

def _make_entity_with_layer(width: int, height: int, filled: bool = True,
                            position: tuple[float, float] = (0.0, 0.0)):
    """Mirror of Ochema `tests/test_p5_physics.py::_make_entity_with_layer`."""
    entity = MagicMock()
    layer = MagicMock()
    alpha = 255 if filled else 0
    layer._image_data = np.full((height, width, 4),
                                [100, 100, 100, alpha], dtype=np.uint8)
    entity.layers = [layer]
    entity.position = position
    entity.z = 0.0
    return entity


def test_pixel_collision_pass_class_level_2_arg_hit():
    """Legacy PixelCollisionPass.test(a, b) returns hit=True on full overlap."""
    from slappyengine.collision_pixel import PixelCollisionPass
    a = _make_entity_with_layer(64, 64, filled=True, position=(0.0, 0.0))
    b = _make_entity_with_layer(64, 64, filled=True, position=(0.0, 0.0))
    result = PixelCollisionPass.test(a, b)
    assert result.hit is True
    assert result.contact_pixels > 0


def test_pixel_collision_pass_class_level_2_arg_no_hit():
    """Legacy PixelCollisionPass.test(a, b) returns hit=False when far apart."""
    from slappyengine.collision_pixel import PixelCollisionPass
    a = _make_entity_with_layer(32, 32, filled=True, position=(0.0, 0.0))
    b = _make_entity_with_layer(32, 32, filled=True, position=(5000.0, 5000.0))
    result = PixelCollisionPass.test(a, b)
    assert result.hit is False
    assert result.contact_pixels == 0


def test_pixel_collision_pass_normal_is_unit_vector_on_hit():
    """When a hit is reported the contact normal has unit magnitude."""
    import math
    from slappyengine.collision_pixel import PixelCollisionPass
    a = _make_entity_with_layer(64, 64, filled=True, position=(0.0, 0.0))
    b = _make_entity_with_layer(64, 64, filled=True, position=(30.0, 0.0))
    result = PixelCollisionPass.test(a, b)
    if result.hit:
        mag = math.hypot(*result.normal)
        assert mag == pytest.approx(1.0, abs=0.1)


def test_pixel_collision_pass_transparent_layers_no_hit():
    """Two fully-transparent layers report no contact."""
    from slappyengine.collision_pixel import PixelCollisionPass
    a = _make_entity_with_layer(64, 64, filled=False, position=(0.0, 0.0))
    b = _make_entity_with_layer(64, 64, filled=False, position=(0.0, 0.0))
    result = PixelCollisionPass.test(a, b)
    assert result.hit is False


def test_pixel_collision_pass_instance_gpu_form_still_returns_result():
    """Modern instance form `pass_.test(gpu, ...)` still routes to _test_gpu.

    Without a real GPU context it degrades to the no-contact fallback,
    which is what the modern smoke tests already assert.
    """
    from slappyengine.collision_pixel import PixelCollisionPass
    pass_ = PixelCollisionPass()
    # Empty rects + None textures — should not raise, returns a result.
    result = pass_.test(None, None, (0, 0, 0, 0), None, (0, 0, 0, 0))
    assert hasattr(result, "hit")
    assert result.hit is False
