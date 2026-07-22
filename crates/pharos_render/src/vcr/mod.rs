//! Virtual Camera Reservoir (VCR) pipeline — Sprint 6 ports Nova3D's
//! Sprint 8 SHIP into Pharos.
//!
//! Unifies reflection, refraction, subsurface, volumetric, and
//! diffraction into a single K-slot-per-texel reservoir rasterized
//! into a 3D storage texture. See `docs/vcr_pipeline_notes.md` and
//! the plan file for stage details.
//!
//! Public flow (all six stages live in submodules):
//!
//! 1. [`seed::SeedPass`]       fills reservoir from G-buffer
//! 2. [`accumulate::AccumulatePass`] extended-frustum raster + contribute
//! 3. [`merge::MergePass`]     WRS drop of least-important slots
//! 4. [`composite::CompositePass`] sum + env cube + Beer-Lambert output
//! 5. [`temporal::TemporalPass`]  optional prev-frame reproject (Standard+)
//!
//! Choose a [`config::Preset`] and hand the pass builders the injected
//! WGSL define block via [`config::wgsl_define_block`] so every shader
//! sees the same K, resolution scale, and thresholds.

pub mod config;
pub mod seed;
pub mod accumulate;
pub mod merge;
pub mod composite;
pub mod temporal;

pub use config::{Preset, PresetParams, Precision, wgsl_define_block};
pub use seed::SeedPass;
pub use accumulate::AccumulatePass;
pub use merge::MergePass;
pub use composite::CompositePass;
pub use temporal::TemporalPass;

/// Bundle of the five pass objects. One `VcrPipeline` per (device,
/// preset) combination; the render loop calls dispatch/draw methods
/// on each stage in order.
pub struct VcrPipeline {
    pub preset: config::Preset,
    pub params: config::PresetParams,
    pub seed: SeedPass,
    pub accumulate: AccumulatePass,
    pub merge: MergePass,
    pub composite: CompositePass,
    pub temporal: Option<TemporalPass>,
}

impl VcrPipeline {
    pub fn new(device: &wgpu::Device, preset: config::Preset) -> Self {
        let params = preset.params();
        let defines = config::wgsl_define_block(params);
        VcrPipeline {
            preset,
            params,
            seed: SeedPass::new(device, &defines),
            accumulate: AccumulatePass::new(device, &defines),
            merge: MergePass::new(device, &defines),
            composite: CompositePass::new(device, &defines),
            temporal: if params.temporal_reuse {
                Some(TemporalPass::new(device, &defines))
            } else {
                None
            },
        }
    }
}
