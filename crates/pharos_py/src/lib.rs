//! Pharos PyO3 bindings — the `_core` cdylib Python imports.
//!
//! Thin wrapper: hosts the `#[pymodule]` entry point and a few
//! pyo3-heavy helpers (math, node_compiler, struct_layout, tile_cache).
//! Every physics/geometry kernel lives in `pharos_core`.
//!
//! Sprint 2: the CPU-side render kernels (raster, fluid_shader,
//! deferred_cluster, scene_walk, gi, ibl) moved to
//! `pharos_render::legacy` behind the `cpu-fallback` feature. This
//! crate now depends on `pharos_render` and re-registers the legacy
//! kernels through its `register` entry point. The new GPU render
//! surface (Renderer / RenderScene / Camera3D / VcrPipeline) is
//! exposed via `render_bindings`.

use pyo3::prelude::*;

// pyo3-adjacent helpers that stay in pharos_py.
mod math;
mod node_compiler;
mod struct_layout;
mod tile_cache;

// GPU render surface — thin PyO3 wrappers over pharos_render types.
mod render_bindings;

// Kernels have been migrated to pharos_core (Sprint 3). Bring their
// register() entry points into scope so the #[pymodule] init below
// stays byte-for-byte identical to the pre-Sprint-3 shape.
use pharos_core::{hull, ik_solver, material_eval, slap_format, physics, sdf_collision, pbf_solver, softbody_solver};

#[cfg(feature = "3d")]
use pharos_core::{math_3d, sdf};

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
    #[cfg(feature = "3d")]
    sdf::sdf::register(m)?;
    physics::physics::register(m)?;
    sdf_collision::sdf_collision::register(m)?;
    pbf_solver::register(m)?;
    softbody_solver::register(m)?;

    // Sprint 2: legacy CPU render kernels now live in pharos_render.
    pharos_render::legacy::register(m)?;

    // GPU render bindings — Renderer / RenderScene / Camera3D / VcrPipeline.
    render_bindings::register(m)?;
    Ok(())
}
