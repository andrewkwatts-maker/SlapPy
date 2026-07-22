//! Cascaded Shadow Maps.
//!
//! Sprint 5 target. Four cascades sampling depth into a
//! Depth32Float-array of 2048x2048 slices; sample point picks the
//! smallest cascade whose frustum contains the shaded fragment.

use glam::{Mat4, Vec3};

/// Parameters describing one CSM cascade slice.
#[derive(Debug, Clone, Copy)]
pub struct CascadeSlice {
    pub near: f32,
    pub far: f32,
    pub view_proj: Mat4,
}

#[derive(Debug, Clone)]
pub struct CsmConfig {
    pub cascade_count: u32,      // usually 4
    pub texel_size: u32,         // 2048 default
    pub split_lambda: f32,       // 0.0 uniform, 1.0 logarithmic; PRACTICAL: 0.5
    pub sun_direction: Vec3,
}

impl Default for CsmConfig {
    fn default() -> Self {
        CsmConfig {
            cascade_count: 4,
            texel_size: 2048,
            split_lambda: 0.5,
            sun_direction: Vec3::new(-0.4, -1.0, -0.3).normalize(),
        }
    }
}

/// Compute cascade split points using PSSM (parallel-split shadow maps).
/// Returns `cascade_count` (near, far) pairs.
pub fn split_cascades(cfg: &CsmConfig, camera_near: f32, camera_far: f32) -> Vec<(f32, f32)> {
    let mut splits = Vec::with_capacity(cfg.cascade_count as usize);
    let ratio = camera_far / camera_near;
    let mut last = camera_near;
    for i in 1..=cfg.cascade_count {
        let si = i as f32 / cfg.cascade_count as f32;
        let log_split = camera_near * ratio.powf(si);
        let uni_split = camera_near + (camera_far - camera_near) * si;
        let split = cfg.split_lambda * log_split + (1.0 - cfg.split_lambda) * uni_split;
        splits.push((last, split));
        last = split;
    }
    splits
}
