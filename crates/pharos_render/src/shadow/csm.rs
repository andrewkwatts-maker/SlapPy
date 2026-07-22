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

// -- Sprint 1 Nova3D bug intake --

/// Polygon-offset factor for the shadow depth pass.
///
/// Sprint 1 bump: Nova3D shipped `2.0` and hit banded acne on receivers
/// with orthographic sun frustum. Empirical fix in Nova3D commit intake
/// was `factor = 4.0`, `units = 8.0`.
pub const SHADOW_DEPTH_BIAS_FACTOR: f32 = 4.0;

/// Polygon-offset units for the shadow depth pass.
pub const SHADOW_DEPTH_BIAS_UNITS: f32 = 8.0;

/// Depth bias state used by every shadow depth pipeline.
///
/// `slope_scale` maps to the polygon-offset factor; `constant` maps to
/// the polygon-offset units. `clamp` is 0.0 (no clamp).
pub fn shadow_depth_bias_state() -> wgpu::DepthBiasState {
    wgpu::DepthBiasState {
        constant: SHADOW_DEPTH_BIAS_UNITS as i32,
        slope_scale: SHADOW_DEPTH_BIAS_FACTOR,
        clamp: 0.0,
    }
}

/// Error returned by shadow-subsystem texture creation.
#[derive(Debug)]
pub enum ShadowInitError {
    ValidationError(String),
}

impl std::fmt::Display for ShadowInitError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ShadowInitError::ValidationError(s) => write!(f, "shadow atlas validation: {s}"),
        }
    }
}

impl std::error::Error for ShadowInitError {}

/// Create the shadow atlas texture with an explicit wgpu validation
/// error scope draining before / after the call.
///
/// Sprint 1 Nova3D bug intake: `glGetError` drained stale GL errors that
/// caused the whole shadow subsystem to silently disable on init. wgpu
/// surfaces validation via `push_error_scope` / `pop_error_scope`; this
/// helper wraps the creation, drains any prior scope error, and returns
/// a typed error instead of silently swallowing it.
pub fn create_shadow_atlas(
    device: &wgpu::Device,
    cfg: &CsmConfig,
) -> Result<wgpu::Texture, ShadowInitError> {
    // Drain any prior validation scope so a stale error does not attach
    // to this creation. Matches the Nova3D "flush glGetError before
    // subsystem init" pattern.
    device.push_error_scope(wgpu::ErrorFilter::Validation);
    let atlas = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("pharos_render.shadow.csm.atlas"),
        size: wgpu::Extent3d {
            width: cfg.texel_size,
            height: cfg.texel_size,
            depth_or_array_layers: cfg.cascade_count,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: wgpu::TextureFormat::Depth32Float,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::TEXTURE_BINDING,
        view_formats: &[],
    });
    let scope_error = pollster::block_on(device.pop_error_scope());
    if let Some(err) = scope_error {
        return Err(ShadowInitError::ValidationError(format!("{err}")));
    }
    Ok(atlas)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shadow_depth_bias_matches_intake() {
        // Nova3D fix bumped factor from 2.0 -> 4.0 and units from 4.0 -> 8.0.
        assert_eq!(SHADOW_DEPTH_BIAS_FACTOR, 4.0);
        assert_eq!(SHADOW_DEPTH_BIAS_UNITS, 8.0);
        let state = shadow_depth_bias_state();
        assert_eq!(state.slope_scale, 4.0);
        assert_eq!(state.constant, 8);
        assert_eq!(state.clamp, 0.0);
    }
}
