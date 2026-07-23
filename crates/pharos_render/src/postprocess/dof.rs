//! Depth-of-field pass (Nova3D S1-W1/W2 port).
//!
//! Two-stage: per-pixel Circle-of-Confusion in view space, then a
//! Vogel-disc bokeh gather with 3x3 CoC dilation. Config surface
//! mirrors Nova3D's `DepthOfField.hpp` API — the wgpu binding lives
//! in the render graph (Sprint 12).

pub const COC_SHADER: &str = include_str!("../../shaders/postprocess_dof_coc.wgsl");
pub const BOKEH_SHADER: &str = include_str!("../../shaders/postprocess_dof_bokeh.wgsl");

/// Physically-tuned thin-lens depth-of-field configuration.
///
/// Defaults chosen for a 50mm full-frame portrait lens.
#[derive(Debug, Clone, Copy)]
pub struct DofConfig {
    pub focal_distance: f32,
    pub focal_length:   f32,
    pub aperture:       f32,
    pub sensor_height:  f32,
    pub max_coc_pixels: f32,
    pub num_rings:      u32,
}

impl Default for DofConfig {
    fn default() -> Self {
        Self {
            focal_distance: 2.5,
            focal_length:   0.05,
            aperture:       2.8,
            sensor_height:  0.024,
            max_coc_pixels: 24.0,
            num_rings:      4,
        }
    }
}

impl DofConfig {
    /// Aperture diameter derived from focal length and f-stop.
    pub fn aperture_diameter(&self) -> f32 {
        self.focal_length / self.aperture
    }
}
