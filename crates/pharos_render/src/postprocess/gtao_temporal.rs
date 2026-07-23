//! GTAO temporal reprojection pass (Nova3D S1-W7 port).
//!
//! Ping-pong reprojection of the previous frame's AO with a
//! neighbourhood-clamped exponential blend against the current frame.
//! The base compute AO pass is scheduled for a future sprint — this
//! module lands only the temporal filter that gates on it.

pub const SHADER: &str = include_str!("../../shaders/postprocess_gtao_temporal.wgsl");

#[derive(Debug, Clone, Copy)]
pub struct GtaoTemporalConfig {
    pub temporal_alpha: f32,
    pub velocity_blend: f32,
}

impl Default for GtaoTemporalConfig {
    fn default() -> Self {
        Self { temporal_alpha: 0.15, velocity_blend: 0.4 }
    }
}
