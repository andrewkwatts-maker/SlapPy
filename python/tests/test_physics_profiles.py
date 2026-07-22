"""Tests for pharos_engine.physics.profiles."""
from __future__ import annotations

import copy

import pytest

from pharos_engine.physics.profiles import (
    BUILTIN_PROFILES,
    PROFILE_DESKTOP,
    PROFILE_HIGH_END,
    PROFILE_MOBILE,
    PROFILE_WEB,
    PhysicsProfile,
    apply_profile,
    auto_detect_profile,
    get_profile,
    load_with_profile,
)
from pharos_engine.physics.world import PhysicsYaml, load_physics_config


def test_all_4_builtins_exist():
    """The four built-in profiles must be registered under their canonical names."""
    assert set(BUILTIN_PROFILES.keys()) == {"desktop", "mobile", "web", "high_end"}
    for prof in BUILTIN_PROFILES.values():
        assert isinstance(prof, PhysicsProfile)


def test_get_profile_returns_correct_object():
    assert get_profile("desktop") is PROFILE_DESKTOP
    assert get_profile("mobile") is PROFILE_MOBILE
    assert get_profile("web") is PROFILE_WEB
    assert get_profile("high_end") is PROFILE_HIGH_END


def test_get_profile_unknown_raises():
    with pytest.raises(KeyError):
        get_profile("nonexistent")


def test_apply_profile_overrides_yaml_settings():
    base = load_physics_config()
    out = apply_profile(base, PROFILE_MOBILE)
    assert out.world.substeps == 2
    assert out.hull.initial_hull_capacity == 64
    assert out.hull.initial_cell_grid_capacity == 16
    assert out.hull.settle_frames == 15
    assert out.gpu.enabled is False
    assert out.boundary_exchange.enabled is True
    assert out.ccd_speed_threshold == pytest.approx(100.0)
    assert out.active_profile == "mobile"


def test_apply_profile_does_not_mutate_input():
    base = load_physics_config()
    snapshot = copy.deepcopy(base)
    _ = apply_profile(base, PROFILE_HIGH_END)
    # Every relevant field on the original must be unchanged.
    assert base.world.substeps == snapshot.world.substeps
    assert base.hull.initial_hull_capacity == snapshot.hull.initial_hull_capacity
    assert base.hull.initial_cell_grid_capacity == snapshot.hull.initial_cell_grid_capacity
    assert base.hull.settle_frames == snapshot.hull.settle_frames
    assert base.gpu.enabled == snapshot.gpu.enabled
    assert base.boundary_exchange.enabled == snapshot.boundary_exchange.enabled
    # The threshold attribute should NOT leak onto the original object.
    assert not hasattr(base, "ccd_speed_threshold")


def test_apply_profile_accepts_string_name():
    base = load_physics_config()
    out = apply_profile(base, "web")
    assert out.world.substeps == 2
    assert out.boundary_exchange.enabled is False
    assert out.gpu.enabled is True


def test_auto_detect_returns_some_profile():
    prof = auto_detect_profile()
    assert isinstance(prof, PhysicsProfile)
    assert prof in BUILTIN_PROFILES.values()


def test_auto_detect_respects_env_override(monkeypatch):
    monkeypatch.setenv("SLAPPY_PHYSICS_PROFILE", "high_end")
    assert auto_detect_profile() is PROFILE_HIGH_END
    monkeypatch.setenv("SLAPPY_PHYSICS_PROFILE", "mobile")
    assert auto_detect_profile() is PROFILE_MOBILE
    # Unknown override falls through to the heuristic (which returns desktop
    # or mobile depending on the host) — just assert it returns *something*.
    monkeypatch.setenv("SLAPPY_PHYSICS_PROFILE", "garbage")
    assert auto_detect_profile() in BUILTIN_PROFILES.values()


def test_yaml_profile_section_parses():
    """The shipped physics.yml exposes a profile.active entry."""
    import yaml
    from pharos_engine.physics.world import _find_physics_yml

    path = _find_physics_yml()
    assert path is not None, "config/physics.yml must be discoverable"
    with open(path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    assert "profile" in raw
    assert raw["profile"].get("active") == "desktop"


def test_load_with_profile_helper():
    out = load_with_profile("mobile")
    assert isinstance(out, PhysicsYaml)
    assert out.world.substeps == 2
    assert out.gpu.enabled is False
    assert out.active_profile == "mobile"


def test_load_with_profile_defaults_to_yaml_section():
    """With no explicit name, load_with_profile reads physics.yml's profile.active."""
    out = load_with_profile()
    # config/physics.yml ships with active: "desktop".
    assert out.active_profile == "desktop"
    assert out.world.substeps == PROFILE_DESKTOP.substeps


def test_load_with_profile_auto(monkeypatch):
    """Passing "auto" triggers auto-detection."""
    monkeypatch.setenv("SLAPPY_PHYSICS_PROFILE", "high_end")
    out = load_with_profile("auto")
    assert out.active_profile == "high_end"
