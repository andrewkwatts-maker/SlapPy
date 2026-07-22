"""Hierarchical-hull per-pixel physics."""
from __future__ import annotations

from slappyengine.physics.body import (
    PhysicsBody,
    make_circle_silhouette,
    make_rect_silhouette,
    silhouette_to_cells,
)
from slappyengine.physics.boundary_exchange import BoundaryExchange
from slappyengine.physics.ccd import position_at_toi, predict_contact_pairs, swept_aabb_overlap  # noqa: F401
from slappyengine.physics.cell import (
    CELL_GRID_SIZE,
    CELL_PIXEL_STRUCT,
    CellGridPool,
)
from slappyengine.physics.post_process import BloomPass, PostProcessChain, TonemapPass, default_post_process_chain  # noqa: F401
from slappyengine.physics.shadows import AOPass, ShadowPass  # noqa: F401
from slappyengine.physics.particles import Particle, ParticleSystem, style_for_material  # noqa: F401
from slappyengine.physics.particle_graph import EmitterNode, ParticleGraph  # noqa: F401
from slappyengine.physics.hull import (
    HullTree,
    NO_CELL_GRID,
    NO_PARENT,
    TIER_T0,
    TIER_T1,
    TIER_T2,
)
from slappyengine.physics.world import (
    ContactPair,
    PhysicsWorld,
    PhysicsYaml,
    load_physics_config,
)
from slappyengine.physics.debug_hud import DebugHUD; from slappyengine.physics.video import VideoWriter  # noqa: E702,F401
from slappyengine.physics.scene_loader import SceneBodySpec, SceneSpec, build_world_from_scene, load_and_build, load_scene_spec  # noqa: E501,F401
from slappyengine.physics.event_publisher import PhysicsEventPublisher  # noqa: E402,F401
from slappyengine.physics.profile import BenchmarkScenario, FrameTimer, baseline_scenarios, run_benchmark  # noqa: E402,F401,E501
from slappyengine.physics.profiles import BUILTIN_PROFILES, PROFILE_DESKTOP, PROFILE_HIGH_END, PROFILE_MOBILE, PROFILE_WEB, PhysicsProfile, apply_profile, auto_detect_profile, get_profile, load_with_profile  # noqa: E402,F401,E501
from slappyengine.physics.memory_budget import MemoryBudget, MemoryBudgetConfig, MemoryBudgetExceeded, _install_memory_section_on_physics_yaml as _install_memory_section; _install_memory_section()  # noqa: E402,E501,F401
from slappyengine.physics.constraints import ConstraintSolver, ConstraintsConfig, DistanceConstraint, PinConstraint, WeldConstraint  # noqa: E402,E501,F401
from slappyengine.physics.frontier import FrontierConfig, FrontierSolver  # noqa: E402,F401

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
