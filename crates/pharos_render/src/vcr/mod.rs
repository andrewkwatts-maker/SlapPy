//! Virtual Camera Reservoir (VCR) pipeline — Sprint 6.
//!
//! Ports Nova3D's Sprint 8 SHIP: screen-space, rasterization-based
//! unified reflection/refraction/SSS/volumetric/diffraction via a
//! K-slot per-texel reservoir. See docs/vcr_pipeline_notes.md and the
//! plan file for stage details.
//!
//! Sprint 4 skeleton files — Sprint 6 fills them in from the Nova3D
//! design doc (H:/Github/Nova3D/docs/design/vcr_pipeline.html).

pub mod config;
pub mod seed;
pub mod accumulate;
pub mod merge;
pub mod composite;
pub mod temporal;
