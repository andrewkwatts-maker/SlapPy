//! Render scene: what a backend needs to draw a frame.
//!
//! Deliberately minimal. Physics/animation/scripting live in
//! pharos_core + Python; scenes hand this crate an already-transformed
//! list of drawables.

pub mod walker;
pub use walker::{Frustum, SubmitItem, WorldAabb, walk};

use glam::{Mat4, Vec3, Vec4};
use serde::{Deserialize, Serialize};

/// Perspective camera. Row-major matrices are exposed via [`view`] and
/// [`projection`] for the render backend to upload into a UBO.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Camera3D {
    pub position: Vec3,
    pub target: Vec3,
    pub up: Vec3,
    pub fov_y_radians: f32,
    pub aspect: f32,
    pub near: f32,
    pub far: f32,
}

impl Default for Camera3D {
    fn default() -> Self {
        Camera3D {
            position: Vec3::new(0.0, 1.5, 3.0),
            target: Vec3::ZERO,
            up: Vec3::Y,
            fov_y_radians: 60.0_f32.to_radians(),
            aspect: 16.0 / 9.0,
            near: 0.1,
            far: 100.0,
        }
    }
}

impl Camera3D {
    pub fn view(&self) -> Mat4 {
        Mat4::look_at_rh(self.position, self.target, self.up)
    }
    pub fn projection(&self) -> Mat4 {
        Mat4::perspective_rh(self.fov_y_radians, self.aspect, self.near, self.far)
    }
}

/// A single mesh: vertices + indices + material.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Mesh {
    pub vertices: Vec<Vertex>,
    pub indices: Vec<u32>,
    pub material_index: u32,
}

#[repr(C)]
#[derive(Debug, Clone, Copy, PartialEq, bytemuck::Pod, bytemuck::Zeroable, Serialize, Deserialize)]
pub struct Vertex {
    pub position: [f32; 3],
    pub normal: [f32; 3],
    pub uv: [f32; 2],
    pub tangent: [f32; 4],
}

impl Vertex {
    pub const BUFFER_LAYOUT: wgpu::VertexBufferLayout<'static> = wgpu::VertexBufferLayout {
        array_stride: std::mem::size_of::<Vertex>() as u64,
        step_mode: wgpu::VertexStepMode::Vertex,
        attributes: &wgpu::vertex_attr_array![
            0 => Float32x3,   // position
            1 => Float32x3,   // normal
            2 => Float32x2,   // uv
            3 => Float32x4,   // tangent
        ],
    };
}

/// One item to draw: transform + mesh handle + material handle.
///
/// The backend keeps a mesh/material cache keyed by these handles;
/// scene loading warms the cache once and each frame just references
/// existing GPU resources.
#[derive(Debug, Clone)]
pub struct DrawItem {
    pub model: Mat4,
    pub mesh: u32,
    pub material: u32,
}

/// Full scene handed to `Backend::render_frame`.
#[derive(Debug, Clone, Default)]
pub struct RenderScene {
    pub camera: Camera3D,
    pub items: Vec<DrawItem>,
    /// Linear-space clear colour (RGBA). Rendered through the sRGB
    /// swap chain in the wgpu backend.
    pub clear_colour: [f32; 4],
}

impl RenderScene {
    pub fn clear_colour_wgpu(&self) -> wgpu::Color {
        wgpu::Color {
            r: self.clear_colour[0] as f64,
            g: self.clear_colour[1] as f64,
            b: self.clear_colour[2] as f64,
            a: self.clear_colour[3] as f64,
        }
    }
}

/// Camera + scene-wide constants uploaded once per frame into a UBO
/// bound at group 0, binding 0 of every material shader.
#[repr(C)]
#[derive(Debug, Clone, Copy, bytemuck::Pod, bytemuck::Zeroable)]
pub struct FrameUniforms {
    pub view: [[f32; 4]; 4],
    pub proj: [[f32; 4]; 4],
    pub view_proj: [[f32; 4]; 4],
    pub camera_position: Vec4,
}

impl FrameUniforms {
    pub fn from_camera(c: &Camera3D) -> Self {
        let view = c.view();
        let proj = c.projection();
        FrameUniforms {
            view: view.to_cols_array_2d(),
            proj: proj.to_cols_array_2d(),
            view_proj: (proj * view).to_cols_array_2d(),
            camera_position: (c.position, 1.0).into(),
        }
    }
}
