//! Post-processing effects (Nova3D S1-W1 through W8 delta intake, 2026-07-23).
//!
//! Each submodule owns one screen-space effect plus its WGSL shader
//! source. The `dispatch()` helpers are thin skeletons — the wgpu
//! pass wiring lives in the render graph, which is scheduled for
//! Sprint 12. Landing the shader + config surface first lets the
//! visual-regression harness (Sprint 5) start capturing baseline
//! images before the graph rewrite.
//!
//! | Effect              | Nova3D source                     | Pharos WGSL |
//! |---------------------|-----------------------------------|-------------|
//! | Depth of field      | dof_coc.comp, dof_bokeh.comp      | postprocess_dof_*.wgsl |
//! | Motion blur         | motion_blur_{tilemax,scatter}     | postprocess_motion_blur_*.wgsl |
//! | Contact shadows     | contact_shadows.comp              | postprocess_contact_shadows.wgsl |
//! | GTAO temporal       | gtao_temporal.comp                | postprocess_gtao_temporal.wgsl |
//! | TAA resolve         | TAA.cpp (Halton 2,3 jitter)       | postprocess_taa_resolve.wgsl |

pub mod contact_shadows;
pub mod dof;
pub mod gtao_temporal;
pub mod motion_blur;
pub mod taa;

pub use contact_shadows::ContactShadowsConfig;
pub use dof::DofConfig;
pub use gtao_temporal::GtaoTemporalConfig;
pub use motion_blur::MotionBlurConfig;
pub use taa::{TaaConfig, TaaQuality, halton23};
