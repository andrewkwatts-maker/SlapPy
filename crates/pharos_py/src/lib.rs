//! Pharos PyO3 bindings — the `_core` cdylib Python imports.
//!
//! Thin wrapper: hosts the `#[pymodule]` entry point and a few
//! pyo3-heavy helpers (math, node_compiler, struct_layout, tile_cache).
//! Every physics/geometry kernel lives in `pharos_core`. Render/GPU
//! kernels (raster, fluid_shader, gi, ibl, scene_walk, deferred_cluster)
//! stay here for now — Sprint 4 migrates them to `pharos_render`.

use pyo3::prelude::*;

// pyo3-adjacent helpers that stay in pharos_py for now.
mod math;
mod node_compiler;
mod struct_layout;
mod tile_cache;

// Render/GPU kernels — pending Sprint 4 migration to pharos_render.
mod raster;
mod fluid_shader;
#[cfg(feature = "3d")]
mod deferred_cluster;
#[cfg(feature = "3d")]
mod scene_walk;
#[cfg(feature = "gi")]
mod gi;
#[cfg(feature = "ibl")]
mod ibl;

// Kernels have been migrated to pharos_core (Sprint 3). Bring their
// register() entry points into scope so the #[pymodule] init below
// stays byte-for-byte identical to the pre-Sprint-3 shape.
use pharos_core::{hull, ik_solver, material_eval, slap_format, physics, sdf_collision, pbf_solver, softbody_solver};

#[cfg(feature = "3d")]
use pharos_core::{math_3d, sdf};
// `pharos_core::bvh` is re-exportable but not yet wired through _core
// (no `pub fn register` needed by Python). Sprint 11 exposes it when
// the scene_walker path in pharos_render pulls it in as a dep.

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    hull::register(m)?;
    ik_solver::register(m)?;
    material_eval::register(m)?;
    math::register(m)?;
    node_compiler::register(m)?;
    slap_format::register(m)?;
    struct_layout::register(m)?;
    tile_cache::register(m)?;
    #[cfg(feature = "3d")]
    math_3d::math_3d::register(m)?;
    #[cfg(feature = "gi")]
    gi::gi::register(m)?;
    #[cfg(feature = "3d")]
    sdf::sdf::register(m)?;
    #[cfg(feature = "ibl")]
    ibl::ibl::register(m)?;
    physics::physics::register(m)?;
    sdf_collision::sdf_collision::register(m)?;
    pbf_solver::register(m)?;
    softbody_solver::register(m)?;
    raster::register(m)?;
    fluid_shader::register(m)?;
    #[cfg(feature = "3d")]
    deferred_cluster::register(m)?;
    #[cfg(feature = "3d")]
    scene_walk::scene_walk::register(m)?;
    Ok(())
}
