//! Motion-blur pass (Nova3D S1-W3/W4 port — McGuire et al. 2012).
//!
//! Two dispatches:
//! 1. Tile-max velocity reduction (NxN pixels → 1 tile-max vector),
//!    then a 3x3 neighbour dilation of the tile buffer.
//! 2. Per-pixel scatter-as-gather along the dominant motion vector,
//!    jittered per pixel.

pub const TILEMAX_SHADER: &str = include_str!("../../shaders/postprocess_motion_blur_tilemax.wgsl");
pub const SCATTER_SHADER: &str = include_str!("../../shaders/postprocess_motion_blur_scatter.wgsl");

#[derive(Debug, Clone, Copy)]
pub struct MotionBlurConfig {
    pub tile_size:      u32,
    pub num_samples:    u32,
    pub shutter_angle:  f32,
    pub velocity_scale: f32,
}

impl Default for MotionBlurConfig {
    fn default() -> Self {
        Self {
            tile_size:      16,
            num_samples:    12,
            shutter_angle:  0.5,
            velocity_scale: 1.0,
        }
    }
}
