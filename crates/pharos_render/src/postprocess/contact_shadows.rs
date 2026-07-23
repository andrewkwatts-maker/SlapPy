//! Contact shadows pass (Nova3D S1-W5 port).
//!
//! Screen-space ray-march toward the dominant directional light with
//! an angular-radius fade for large area lights.

pub const SHADER: &str = include_str!("../../shaders/postprocess_contact_shadows.wgsl");

#[derive(Debug, Clone, Copy)]
pub struct ContactShadowsConfig {
    pub max_steps:            u32,
    pub thickness:            f32,
    pub step_size:            f32,
    pub light_angular_radius: f32,
    pub max_angle_fade:       f32,
}

impl Default for ContactShadowsConfig {
    fn default() -> Self {
        Self {
            max_steps:            24,
            thickness:            0.05,
            step_size:            1.5,
            light_angular_radius: 0.0,
            max_angle_fade:       0.4,
        }
    }
}
