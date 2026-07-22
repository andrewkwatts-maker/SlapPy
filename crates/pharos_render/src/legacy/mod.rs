//! Legacy CPU-side render kernels.
//!
//! Sprint 2 migration target: raster / fluid_shader / deferred_cluster /
//! scene_walk / gi / ibl live here now, gated behind the `cpu-fallback`
//! feature so headless CI runners (and downstream games that still
//! reach for the numpy-facing shader helpers) keep working. Every
//! kernel exposes a `pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()>`
//! entry point that `pharos_py` re-registers under the `_core` module.
//!
//! The GPU replacements live under `crates/pharos_render/src/{backend,
//! compute, pipeline, scene, shadow, vcr}`. Once every downstream game
//! has switched to the wgpu / VCR paths, this module — and the
//! `cpu-fallback` feature — retires.

pub mod raster;
pub mod fluid_shader;
pub mod deferred_cluster;
pub mod scene_walk;
pub mod gi;
pub mod ibl;

use pyo3::prelude::*;

/// Re-register every legacy CPU kernel under the caller's PyModule.
///
/// Called from `pharos_py::_core` when the `cpu-fallback` feature is on.
/// Each submodule's `register` gates itself further on `3d` / `gi` /
/// `ibl` where relevant.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    raster::register(m)?;
    fluid_shader::register(m)?;
    #[cfg(feature = "3d")]
    deferred_cluster::register(m)?;
    #[cfg(feature = "3d")]
    scene_walk::scene_walk::register(m)?;
    #[cfg(feature = "gi")]
    gi::gi::register(m)?;
    #[cfg(feature = "ibl")]
    ibl::ibl::register(m)?;
    Ok(())
}
