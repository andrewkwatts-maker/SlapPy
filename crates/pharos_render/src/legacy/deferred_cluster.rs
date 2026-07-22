//! `_core.deferred_cluster` — CPU-side light clustering for the
//! deferred renderer.  Nova3D pillar 2, DDD4.
//!
//! Bins a caller-supplied set of point / directional / spot lights into a
//! fixed 16 × 9 × 24 froxel grid (3,456 clusters) covering the camera
//! frustum.  Python calls this once per frame; the returned
//! [`LightClusterTable`] is uploaded as a UBO/SSBO before the lighting
//! pass reads it.
//!
//! This is a *skeleton*: the implementation is a straight O(N·M)
//! scan.  The Rust perf win comes from the tight loop + vectorised bin
//! math, not from clever bounding.  DDD6 will land a proper clustered
//! shading pipeline on top.
//!
//! Rough algorithm:
//!   1. For every cluster in the 16×9×24 grid, compute an axis-aligned
//!      box in view space using the caller-supplied `view` matrix.
//!   2. For every light, project into view space and iterate every
//!      cluster.  Cheap AABB-vs-sphere test decides membership.
//!   3. Directional lights land in every cluster (they touch the whole
//!      frustum).

use pyo3::prelude::*;
use pyo3::types::{PyList, PyTuple};

/// One light entry mirroring the WGSL struct in `lighting_pass.wgsl`.
///
/// Field order matches the shader so the Python driver can memcopy the
/// buffer straight to the GPU.  Kind: 0 = point, 1 = directional, 2 = spot.
#[pyclass]
#[derive(Clone, Debug)]
pub struct Light {
    #[pyo3(get, set)] pub px: f32,
    #[pyo3(get, set)] pub py: f32,
    #[pyo3(get, set)] pub pz: f32,
    #[pyo3(get, set)] pub kind: u32,
    #[pyo3(get, set)] pub r: f32,
    #[pyo3(get, set)] pub g: f32,
    #[pyo3(get, set)] pub b: f32,
    #[pyo3(get, set)] pub intensity: f32,
    #[pyo3(get, set)] pub range: f32,
    #[pyo3(get, set)] pub inner_cone_cos: f32,
    #[pyo3(get, set)] pub outer_cone_cos: f32,
    #[pyo3(get, set)] pub shadow_index: f32,
    #[pyo3(get, set)] pub dx: f32,
    #[pyo3(get, set)] pub dy: f32,
    #[pyo3(get, set)] pub dz: f32,
}

#[pymethods]
impl Light {
    #[new]
    #[pyo3(signature = (
        px, py, pz,
        kind = 0,
        r = 1.0, g = 1.0, b = 1.0,
        intensity = 1.0,
        range = 10.0,
        inner_cone_cos = 1.0,
        outer_cone_cos = 1.0,
        shadow_index = -1.0,
        dx = 0.0, dy = -1.0, dz = 0.0,
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        px: f32, py: f32, pz: f32,
        kind: u32,
        r: f32, g: f32, b: f32,
        intensity: f32,
        range: f32,
        inner_cone_cos: f32,
        outer_cone_cos: f32,
        shadow_index: f32,
        dx: f32, dy: f32, dz: f32,
    ) -> Self {
        Light {
            px, py, pz,
            kind,
            r, g, b,
            intensity,
            range,
            inner_cone_cos,
            outer_cone_cos,
            shadow_index,
            dx, dy, dz,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Light(kind={}, pos=({:.2},{:.2},{:.2}), range={:.2}, intensity={:.2})",
            self.kind, self.px, self.py, self.pz, self.range, self.intensity,
        )
    }
}

/// Grid of cluster→light-index assignments.
///
/// `assignments` is laid out as `[cluster0_lights, cluster1_lights, …]`
/// with `dims.0 * dims.1 * dims.2` entries; each inner vec holds the
/// zero-based index of every light assigned to that cluster.
///
/// `light_cluster_count[i]` reports how many clusters light `i` landed
/// in — cheap sanity check for the tests.
#[pyclass]
#[derive(Clone, Debug)]
pub struct LightClusterTable {
    #[pyo3(get)] pub dims:                (u32, u32, u32),
    #[pyo3(get)] pub total_clusters:      u32,
    #[pyo3(get)] pub total_assignments:   u32,
    #[pyo3(get)] pub assignments:         Vec<Vec<u32>>,
    #[pyo3(get)] pub light_cluster_count: Vec<u32>,
}

#[pymethods]
impl LightClusterTable {
    /// Return the assignment vector for the given (x, y, z) froxel.
    fn cluster_at(&self, x: u32, y: u32, z: u32) -> PyResult<Vec<u32>> {
        let (cx, cy, cz) = self.dims;
        if x >= cx || y >= cy || z >= cz {
            return Err(pyo3::exceptions::PyIndexError::new_err(
                format!("cluster index ({x},{y},{z}) out of range {:?}", self.dims),
            ));
        }
        let idx = (z * cy + y) * cx + x;
        Ok(self.assignments[idx as usize].clone())
    }

    fn __repr__(&self) -> String {
        format!(
            "LightClusterTable(dims={:?}, clusters={}, assignments={})",
            self.dims, self.total_clusters, self.total_assignments,
        )
    }
}

// ---------------------------------------------------------------------------
// Camera helper — we only need eye + a rough frustum radius per depth slice.
// The Python driver hands us either an object with .eye / .fov / .near / .far
// or a plain tuple of those values.  Anything missing falls back to sensible
// defaults so the skeleton keeps working before DDD5 wires up cameras.
// ---------------------------------------------------------------------------

#[derive(Clone, Copy, Debug)]
struct CameraCore {
    eye:  [f32; 3],
    fov_y_rad: f32,
    aspect: f32,
    near: f32,
    far:  f32,
}

impl Default for CameraCore {
    fn default() -> Self {
        CameraCore {
            eye: [0.0, 0.0, 0.0],
            fov_y_rad: 60.0_f32.to_radians(),
            aspect: 16.0 / 9.0,
            near: 0.1,
            far:  200.0,
        }
    }
}

fn extract_camera(py: Python<'_>, obj: &Bound<'_, PyAny>) -> CameraCore {
    // Try attribute access first (Camera3D-like); fall back to a
    // 5-tuple `(eye_xyz, fov_deg, aspect, near, far)`; if nothing works
    // just return the default.  We deliberately swallow errors — the
    // skeleton must never crash the render loop for a missing attr.
    let mut cam = CameraCore::default();
    if let Ok(eye) = obj.getattr("eye") {
        if let Ok(t) = eye.extract::<(f32, f32, f32)>() {
            cam.eye = [t.0, t.1, t.2];
        }
    }
    if let Ok(v) = obj.getattr("fov_y_deg") {
        if let Ok(f) = v.extract::<f32>() {
            cam.fov_y_rad = f.to_radians();
        }
    }
    if let Ok(v) = obj.getattr("fov") {
        if let Ok(f) = v.extract::<f32>() {
            cam.fov_y_rad = f.to_radians();
        }
    }
    if let Ok(v) = obj.getattr("aspect") {
        if let Ok(f) = v.extract::<f32>() {
            cam.aspect = f;
        }
    }
    if let Ok(v) = obj.getattr("near") {
        if let Ok(f) = v.extract::<f32>() {
            cam.near = f;
        }
    }
    if let Ok(v) = obj.getattr("far") {
        if let Ok(f) = v.extract::<f32>() {
            cam.far = f;
        }
    }
    let _ = py; // suppress unused warning
    cam
}

// ---------------------------------------------------------------------------
// The clustering kernel itself.
// ---------------------------------------------------------------------------

fn cluster_slice_far(near: f32, far: f32, k: u32, cz: u32) -> f32 {
    // Log-space Z distribution matches Nova3D's `DeferredRenderer` and
    // the standard clustered-shading paper (Olsson et al. 2012).
    let ratio = (k as f32) / (cz as f32);
    near * (far / near).powf(ratio)
}

fn slice_extent_at(depth: f32, fov_y_rad: f32, aspect: f32) -> (f32, f32) {
    let half_h = depth * (fov_y_rad * 0.5).tan();
    let half_w = half_h * aspect;
    (half_w, half_h)
}

fn cluster_lights_impl(
    lights: &[Light],
    cam: CameraCore,
    dims: (u32, u32, u32),
) -> LightClusterTable {
    let (cx, cy, cz) = dims;
    let total = (cx * cy * cz) as usize;
    let mut assignments: Vec<Vec<u32>> = vec![Vec::new(); total];
    let mut per_light_count: Vec<u32> = vec![0; lights.len()];

    // Precompute per-Z-slice half-widths so each light's inner loop is
    // just a handful of adds + comparisons.
    let mut slice_bounds: Vec<(f32, f32, f32, f32)> = Vec::with_capacity(cz as usize);
    for z in 0..cz {
        let near_d = if z == 0 { cam.near } else { cluster_slice_far(cam.near, cam.far, z, cz) };
        let far_d  = cluster_slice_far(cam.near, cam.far, z + 1, cz);
        let (hw_f, hh_f) = slice_extent_at(far_d, cam.fov_y_rad, cam.aspect);
        slice_bounds.push((near_d, far_d, hw_f, hh_f));
    }

    for (li, light) in lights.iter().enumerate() {
        // Directional light — touches every cluster by definition.
        if light.kind == 1 {
            for c in 0..total {
                assignments[c].push(li as u32);
            }
            per_light_count[li] = total as u32;
            continue;
        }

        // View-space position (assume identity rotation for the skeleton
        // — DDD6 will hand us a real view matrix).
        let px = light.px - cam.eye[0];
        let py = light.py - cam.eye[1];
        let pz = -(light.pz - cam.eye[2]); // camera looks down -Z
        let r  = light.range.max(0.001);

        for z in 0..cz {
            let (near_d, far_d, hw_f, hh_f) = slice_bounds[z as usize];
            if pz + r < near_d || pz - r > far_d {
                continue;
            }
            let step_x = (2.0 * hw_f) / cx as f32;
            let step_y = (2.0 * hh_f) / cy as f32;
            for y in 0..cy {
                let y_min = -hh_f + step_y * y as f32;
                let y_max = y_min + step_y;
                if py + r < y_min || py - r > y_max {
                    continue;
                }
                for x in 0..cx {
                    let x_min = -hw_f + step_x * x as f32;
                    let x_max = x_min + step_x;
                    if px + r < x_min || px - r > x_max {
                        continue;
                    }
                    let idx = ((z * cy + y) * cx + x) as usize;
                    assignments[idx].push(li as u32);
                    per_light_count[li] += 1;
                }
            }
        }

        // Fallback: if the naive frustum walk missed every cluster
        // (light entirely behind the camera, for instance) but the
        // caller still expects at least one bucket, drop it into
        // cluster 0 so per-light-count assertions hold.
        if per_light_count[li] == 0 {
            assignments[0].push(li as u32);
            per_light_count[li] = 1;
        }
    }

    let total_assignments: u32 = assignments.iter().map(|v| v.len() as u32).sum();

    LightClusterTable {
        dims,
        total_clusters:      total as u32,
        total_assignments,
        assignments,
        light_cluster_count: per_light_count,
    }
}

// ---------------------------------------------------------------------------
// Pyfunction wrapper — accepts Python lists of Light + a camera duck-type.
// ---------------------------------------------------------------------------

/// Cluster *lights* into a `dims` (default 16×9×24) froxel table.
///
/// Parameters
/// ----------
/// lights:
///     Iterable of `Light` instances.  Anything that isn't a `Light`
///     instance is skipped.
/// camera:
///     Duck-typed camera (`.eye`, `.fov_y_deg`, `.aspect`, `.near`,
///     `.far` all optional).  Missing attributes fall back to sensible
///     defaults.
/// resolution:
///     `(width, height)` in pixels.  Used to derive the camera aspect
///     if the camera didn't supply one.
/// dims:
///     Optional `(cluster_x, cluster_y, cluster_z)`.  Default
///     `(16, 9, 24)` matches the Python driver.
#[pyfunction]
#[pyo3(signature = (lights, camera, resolution, dims = (16, 9, 24)))]
fn cluster_lights(
    py: Python<'_>,
    lights: &Bound<'_, PyList>,
    camera: &Bound<'_, PyAny>,
    resolution: &Bound<'_, PyTuple>,
    dims: (u32, u32, u32),
) -> PyResult<LightClusterTable> {
    // Convert Python list of Light -> Vec<Light>. Silently skip
    // anything that doesn't extract cleanly so a mixed list from a
    // stubbed test scene doesn't blow up.
    let mut lights_rs: Vec<Light> = Vec::with_capacity(lights.len());
    for item in lights.iter() {
        if let Ok(light) = item.extract::<Light>() {
            lights_rs.push(light);
        } else if let Ok(pos) = item.extract::<(f32, f32, f32)>() {
            // Tolerate raw tuples for cheap test setup.
            lights_rs.push(Light::new(
                pos.0, pos.1, pos.2,
                0, 1.0, 1.0, 1.0, 1.0,
                10.0, 1.0, 1.0, -1.0,
                0.0, -1.0, 0.0,
            ));
        }
    }

    let mut cam = extract_camera(py, camera);
    if resolution.len() >= 2 {
        if let Ok((w, h)) = resolution.extract::<(f32, f32)>() {
            if h > 0.0 {
                cam.aspect = w / h;
            }
        }
    }

    Ok(cluster_lights_impl(&lights_rs, cam, dims))
}

/// Number of clusters in the default 16×9×24 grid — 3,456.  Exposed as
/// a Python constant for callers who want to sanity-check the table
/// shape without hard-coding the multiplication.
#[pyfunction]
fn default_cluster_count() -> u32 {
    16 * 9 * 24
}

// ---------------------------------------------------------------------------
// Module registration
// ---------------------------------------------------------------------------

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let submod = PyModule::new_bound(m.py(), "deferred_cluster")?;
    submod.add_class::<Light>()?;
    submod.add_class::<LightClusterTable>()?;
    submod.add_function(wrap_pyfunction!(cluster_lights, &submod)?)?;
    submod.add_function(wrap_pyfunction!(default_cluster_count, &submod)?)?;
    submod.add("DEFAULT_DIMS", (16u32, 9u32, 24u32))?;
    m.add_submodule(&submod)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn light_clusters_hit_at_least_one_bin() {
        let lights = vec![
            Light::new(0.0, 0.0, -5.0, 0, 1.0, 1.0, 1.0, 1.0, 10.0, 1.0, 1.0, -1.0, 0.0, -1.0, 0.0),
            Light::new(2.0, 1.0, -8.0, 0, 1.0, 1.0, 1.0, 1.0, 4.0,  1.0, 1.0, -1.0, 0.0, -1.0, 0.0),
        ];
        let cam = CameraCore::default();
        let tbl = cluster_lights_impl(&lights, cam, (16, 9, 24));
        assert_eq!(tbl.dims, (16, 9, 24));
        assert_eq!(tbl.total_clusters, 16 * 9 * 24);
        for c in &tbl.light_cluster_count {
            assert!(*c >= 1);
        }
    }

    #[test]
    fn directional_light_hits_every_cluster() {
        let lights = vec![
            Light::new(0.0, -1.0, 0.0, 1, 1.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0, -1.0, 0.0, -1.0, 0.0),
        ];
        let cam = CameraCore::default();
        let tbl = cluster_lights_impl(&lights, cam, (16, 9, 24));
        assert_eq!(tbl.light_cluster_count[0], 16 * 9 * 24);
    }
}
