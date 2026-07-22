"""Hierarchical-hull per-pixel physics."""
from __future__ import annotations

from pharos_engine.physics.body import (
    PhysicsBody,
    make_circle_silhouette,
    make_rect_silhouette,
    silhouette_to_cells,
)
from pharos_engine.physics.boundary_exchange import BoundaryExchange
from pharos_engine.physics.ccd import position_at_toi, predict_contact_pairs, swept_aabb_overlap  # noqa: F401
from pharos_engine.physics.cell import (
    CELL_GRID_SIZE,
    CELL_PIXEL_STRUCT,
    CellGridPool,
)
from pharos_engine.physics.post_process import BloomPass, PostProcessChain, TonemapPass, default_post_process_chain  # noqa: F401
from pharos_engine.physics.shadows import AOPass, ShadowPass  # noqa: F401
from pharos_engine.physics.particles import Particle, ParticleSystem, style_for_material  # noqa: F401
from pharos_engine.physics.particle_graph import EmitterNode, ParticleGraph  # noqa: F401
from pharos_engine.physics.hull import (
    HullTree,
    NO_CELL_GRID,
    NO_PARENT,
    TIER_T0,
    TIER_T1,
    TIER_T2,
)
from pharos_engine.physics.world import (
    ContactPair,
    PhysicsWorld,
    PhysicsYaml,
    load_physics_config,
)
from pharos_engine.physics.debug_hud import DebugHUD; from pharos_engine.physics.video import VideoWriter  # noqa: E702,F401
from pharos_engine.physics.scene_loader import SceneBodySpec, SceneSpec, build_world_from_scene, load_and_build, load_scene_spec  # noqa: E501,F401
from pharos_engine.physics.event_publisher import PhysicsEventPublisher  # noqa: E402,F401
from pharos_engine.physics.profile import BenchmarkScenario, FrameTimer, baseline_scenarios, run_benchmark  # noqa: E402,F401,E501
from pharos_engine.physics.profiles import BUILTIN_PROFILES, PROFILE_DESKTOP, PROFILE_HIGH_END, PROFILE_MOBILE, PROFILE_WEB, PhysicsProfile, apply_profile, auto_detect_profile, get_profile, load_with_profile  # noqa: E402,F401,E501
from pharos_engine.physics.memory_budget import MemoryBudget, MemoryBudgetConfig, MemoryBudgetExceeded, _install_memory_section_on_physics_yaml as _install_memory_section; _install_memory_section()  # noqa: E402,E501,F401
from pharos_engine.physics.constraints import ConstraintSolver, ConstraintsConfig, DistanceConstraint, PinConstraint, WeldConstraint  # noqa: E402,E501,F401
from pharos_engine.physics.frontier import FrontierConfig, FrontierSolver  # noqa: E402,F401

__all__ = [
    "BoundaryExchange",
    "CELL_GRID_SIZE",
    "CELL_PIXEL_STRUCT",
    "CellGridPool",
    "ContactPair",
    "HullTree",
    "NO_CELL_GRID",
    "NO_PARENT",
    "PhysicsBody",
    "PhysicsWorld",
    "PhysicsYaml",
    "TIER_T0",
    "TIER_T1",
    "TIER_T2",
    "load_physics_config",
    "make_circle_silhouette",
    "make_rect_silhouette",
    "silhouette_to_cells",
]
