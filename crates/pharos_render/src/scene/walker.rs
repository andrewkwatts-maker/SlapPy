//! Scene walker: turn a RenderScene into a submittable draw list.
//!
//! Pipeline:
//!
//! 1. Flatten scene items.
//! 2. Cull against the view frustum (AABB vs. 6 planes).
//! 3. Sort by material (front-to-back within opaque, back-to-front for
//!    transparent — flag comes off the material slot).
//! 4. Emit an ordered `SubmitList` the backend translates to draw calls.
//!
//! Sprint 5 lands cull + sort. Sprint 6 will add VCR-specific bucket
//! separation (reflective/refractive materials into their own bucket
//! that seeds VCR reservoirs first).

use glam::{Mat4, Vec3, Vec4};

use crate::scene::{Camera3D, DrawItem};

/// One item ready for the backend to submit.
#[derive(Debug, Clone)]
pub struct SubmitItem {
    pub model: Mat4,
    pub mesh: u32,
    pub material: u32,
    /// Sort key: lower renders first.
    pub sort_key: u64,
}

/// AABB in world space, used for frustum culling.
#[derive(Debug, Clone, Copy)]
pub struct WorldAabb {
    pub min: Vec3,
    pub max: Vec3,
}

impl WorldAabb {
    pub fn from_center_extent(c: Vec3, e: Vec3) -> Self {
        WorldAabb { min: c - e, max: c + e }
    }
}

/// Six frustum planes (near, far, left, right, top, bottom) extracted
/// from a `proj * view` matrix. Each plane is (nx, ny, nz, d) with
/// the convention that `dot(plane.xyz, p) + plane.w >= 0` means "in
/// front of the plane".
#[derive(Debug, Clone, Copy)]
pub struct Frustum {
    pub planes: [Vec4; 6],
}

impl Frustum {
    pub fn from_view_proj(vp: Mat4) -> Self {
        // Extract via Gribb & Hartmann; planes are rows of (vp).
        let m = vp.to_cols_array_2d();
        // Row-major access — glam is column-major so we transpose in place.
        let row = |r: usize| Vec4::new(m[0][r], m[1][r], m[2][r], m[3][r]);
        let mut planes = [
            row(3) + row(0),  // left
            row(3) - row(0),  // right
            row(3) + row(1),  // bottom
            row(3) - row(1),  // top
            row(3) + row(2),  // near (RH, [-1,1] clip.z or [0,1]; RH GL-ish)
            row(3) - row(2),  // far
        ];
        for p in &mut planes {
            let n = p.truncate().length();
            if n > 1e-9 {
                *p = *p / n;
            }
        }
        Frustum { planes }
    }

    pub fn contains_aabb(&self, aabb: WorldAabb) -> bool {
        for plane in &self.planes {
            // Choose the corner of the AABB furthest along the plane normal.
            let n = plane.truncate();
            let p = Vec3::new(
                if n.x >= 0.0 { aabb.max.x } else { aabb.min.x },
                if n.y >= 0.0 { aabb.max.y } else { aabb.min.y },
                if n.z >= 0.0 { aabb.max.z } else { aabb.min.z },
            );
            if n.dot(p) + plane.w < 0.0 {
                return false;
            }
        }
        true
    }
}

/// Walk an item list, cull against `camera`, sort by material, emit.
///
/// `aabb_for_item` gives the caller a chance to attach per-item AABBs
/// (from the mesh cache). Items with no AABB are considered always
/// visible (typical for skyboxes and screen-quads).
pub fn walk<F>(items: &[DrawItem], camera: &Camera3D, aabb_for_item: F) -> Vec<SubmitItem>
where
    F: Fn(&DrawItem) -> Option<WorldAabb>,
{
    let vp = camera.projection() * camera.view();
    let frustum = Frustum::from_view_proj(vp);

    let mut submit: Vec<SubmitItem> = items
        .iter()
        .filter(|item| match aabb_for_item(item) {
            Some(aabb) => frustum.contains_aabb(aabb),
            None => true,
        })
        .map(|item| {
            // Sort key: material_id in the high bits, mesh_id in the low
            // bits — draws sharing a material cluster together, cutting
            // pipeline / bind-group switches.
            let sort_key = ((item.material as u64) << 32) | (item.mesh as u64);
            SubmitItem {
                model: item.model,
                mesh: item.mesh,
                material: item.material,
                sort_key,
            }
        })
        .collect();

    submit.sort_by_key(|s| s.sort_key);
    submit
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn aabb_inside_camera_frustum_passes() {
        let camera = Camera3D::default();
        let f = Frustum::from_view_proj(camera.projection() * camera.view());
        let aabb = WorldAabb::from_center_extent(Vec3::ZERO, Vec3::splat(0.5));
        assert!(f.contains_aabb(aabb));
    }

    #[test]
    fn aabb_behind_camera_rejected() {
        let camera = Camera3D::default();
        let f = Frustum::from_view_proj(camera.projection() * camera.view());
        // Origin is at (0, 1.5, 3); a box far behind that on +Z should be culled.
        let aabb = WorldAabb::from_center_extent(Vec3::new(0.0, 0.0, 50.0), Vec3::splat(0.1));
        assert!(!f.contains_aabb(aabb));
    }
}
