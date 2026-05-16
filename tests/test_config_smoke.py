"""Smoke test: load_engine_config() must parse every YAML section without error."""
import os
import pytest

# Point the loader at the repo config/ regardless of cwd
os.environ.setdefault(
    "SLAPPY_CONFIG_DIR",
    str(__import__("pathlib").Path(__file__).resolve().parent.parent / "config"),
)

from playslap.config import load_engine_config


def test_config_smoke():
    cfg = load_engine_config()

    # --- originally present sections ---
    assert cfg.window.width == 800
    assert cfg.rendering.texture_format == "bgra8unorm"
    assert cfg.residency.vram_budget_mb == 512
    assert cfg.compute.workgroup_size_x == 16
    assert cfg.physics.default_dt == pytest.approx(0.016667)
    assert cfg.tags.max_bits == 32
    assert cfg.materials.auto_dispatch is True

    # --- new rendering fields ---
    assert cfg.rendering.backend == "auto"
    assert cfg.rendering.power_preference == "high_performance"

    # --- sprint sections ---
    assert cfg.z_height.parallax_enabled is True
    assert cfg.pixel_physics.gravity == pytest.approx(98.0)
    assert cfg.fluid_sim.enabled is False
    assert cfg.fluid_sim.lod_mode == "exp"
    assert cfg.net.enabled is False
    assert cfg.net.max_players == 8
    assert cfg.lighting.enabled is True
    assert cfg.lighting.max_point_lights == 16
    assert cfg.lighting.radiance_cascades is False
    assert cfg.lighting.clustered_lighting is True
    assert cfg.lighting.cluster_tile_size == 8
    assert cfg.lighting.max_lights_per_tile == 64
    assert cfg.input.default_player0 == "wasd"
    assert cfg.split_screen.enabled is False
    assert cfg.split_screen.border_px == 2

    print("Config OK")
