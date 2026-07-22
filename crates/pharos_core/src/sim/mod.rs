//! Simulation substrate: the `Propagator` trait every dynamics kernel
//! implements, plus a lightweight `EventBus` the trait talks to.
//!
//! Sprint 4 landing. Nova3D lesson: PBF and softbody solvers grew
//! independent scheduling / advance code paths that both parameterise
//! over dt + material properties. Pulling them under a shared trait
//! makes the render side (Sprint 6+) drive them uniformly and lets
//! composite scenes (fluid + softbody + thermal) share one tick.
//!
//! ```rust
//! use pharos_core::sim::{EventBus, Propagator};
//!
//! struct StillWater;
//! impl Propagator for StillWater {
//!     fn speed_at(&self, _p: [f32; 3]) -> f32 { 0.0 }
//!     fn absorption_at(&self, _p: [f32; 3]) -> f32 { 0.02 }
//!     fn step(&mut self, _dt: f32) {}
//!     fn consume(&mut self, _bus: &mut EventBus) {}
//! }
//! ```
//!
//! Refactoring existing kernels (pbf_solver, softbody_solver) is done
//! via thin adapter structs in this module so the hot-path kernel
//! bodies stay untouched (no perf regression).

pub mod propagator;

pub use propagator::{Event, EventBus, Propagator, PropagatorStub};
