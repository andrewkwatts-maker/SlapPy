//! Skeletal skinning.
//!
//! Sprint 5 target. Bone-palette buffer + skinning WGSL invoked by
//! the G-buffer + forward vertex shaders when the mesh has a skeleton
//! attached.

use glam::Mat4;

#[derive(Debug, Clone)]
pub struct Skeleton {
    pub bones: Vec<Bone>,
}

#[derive(Debug, Clone)]
pub struct Bone {
    pub parent: Option<u32>,
    pub inverse_bind: Mat4,
    pub local: Mat4,
}

impl Skeleton {
    /// Flatten the current bone poses into a palette matrix array
    /// suitable for GPU upload as a storage buffer.
    pub fn bone_palette(&self) -> Vec<Mat4> {
        let mut world = Vec::with_capacity(self.bones.len());
        for bone in &self.bones {
            let parent_world = bone
                .parent
                .and_then(|p| world.get(p as usize).copied())
                .unwrap_or(Mat4::IDENTITY);
            world.push(parent_world * bone.local);
        }
        // Skinning matrix = world_pose * inverse_bind.
        world
            .iter()
            .zip(self.bones.iter())
            .map(|(w, b)| *w * b.inverse_bind)
            .collect()
    }
}
