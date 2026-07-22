//! GPU compute — Sprint 7.
//!
//! Ports pharos_core CPU kernels (pbf_solver, softbody_solver) into
//! WGSL compute pipelines. The Rust host code owns the ping-pong
//! buffer bookkeeping; scheduling is driven by pharos_engine's
//! dispatch chooser (`pharos_engine.compute.dispatch:choose_backend`).

pub mod pbf;
pub mod softbody;

pub use pbf::PbfGpu;
pub use softbody::SoftbodyGpu;
