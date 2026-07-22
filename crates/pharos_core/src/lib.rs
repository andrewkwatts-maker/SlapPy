//! Pharos core kernels.
//!
//! Physics, fluid, softbody, geometry, IK, and material-eval kernels.
//! Compiled as `rlib` so pharos_py can re-export them under the
//! `_core` cdylib. Each module owns its `#[pyfunction]`s and
//! `#[pyclass]`es and provides a `pub fn register(m)` entry point that
//! pharos_py calls from its `#[pymodule]` init.
//!
//! Rendering kernels (raster, fluid_shader, gi, ibl, scene_walk,
//! deferred_cluster) live in `pharos_render` (Sprint 4+).

pub mod hull;
pub mod ik_solver;
pub mod material_eval;
pub mod slap_format;

pub mod physics;
pub mod sdf_collision;

// Untracked-in-lib.rs-until-now pure-Rust kernels (checkpoint files).
// They ship the Tier-10 full-step CPU paths.
pub mod pbf_solver;
pub mod softbody_solver;

// Sprint 4 SOLID refactor: shared simulation substrate.
pub mod sim;

// 3D geometry kernels — gated behind the `3d` feature.
#[cfg(feature = "3d")]
pub mod math_3d;
#[cfg(feature = "3d")]
pub mod bvh;
#[cfg(feature = "3d")]
pub mod sdf;
