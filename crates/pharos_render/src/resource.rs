//! GPU resource cache — meshes, textures, materials, bind groups.
//!
//! Sprint 4 stub. Sprint 5 wires the mesh upload path when the
//! scene walker starts submitting geometry.

use std::collections::HashMap;

/// Slot handles used by [`crate::scene::DrawItem`] to reference cached
/// GPU resources without exposing wgpu handles to callers.
pub type MeshId = u32;
pub type MaterialId = u32;
pub type TextureId = u32;

#[derive(Default)]
pub struct ResourceCache {
    pub meshes: HashMap<MeshId, wgpu::Buffer>,
    pub materials: HashMap<MaterialId, MaterialSlot>,
    pub textures: HashMap<TextureId, wgpu::Texture>,
}

pub struct MaterialSlot {
    pub base_colour: [f32; 4],
    pub metallic: f32,
    pub roughness: f32,
    pub ior: f32,
    pub absorption: [f32; 3],
    pub base_colour_texture: Option<TextureId>,
    pub normal_texture: Option<TextureId>,
}
