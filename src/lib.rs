use pyo3::prelude::*;

mod hull;
mod ik_solver;
mod material_eval;
mod math;
mod node_compiler;
mod slap_format;
mod struct_layout;
mod tile_cache;

#[cfg(feature = "3d")]
mod math_3d;
#[cfg(feature = "3d")]
mod bvh;
#[cfg(feature = "3d")]
mod sdf;

#[cfg(feature = "gi")]
mod gi;

#[cfg(feature = "ibl")]
mod ibl;

mod physics;
mod sdf_collision;

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
    Ok(())
}
