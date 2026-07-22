// Nova3D pillar 5 — batched scene-graph transform walk (Rust hot path).
//
// Given a topologically-sorted array of local transforms and a
// parallel parent-index array (-1 for roots), compute each node's
// 4x4 world matrix.  The Python `SceneNode` implementation is the
// correctness baseline; this kernel accelerates batched updates
// (e.g. animation ticks over thousands of bones / rigged parts).

#[cfg(feature = "3d")]
pub mod scene_walk {
    use pyo3::prelude::*;
    use pyo3::types::PyList;

    // -------------------------------------------------------------------------
    // Transform3D — mirror of Python dataclass, exposed for interop
    // -------------------------------------------------------------------------

    #[pyclass]
    #[derive(Clone, Copy, Debug)]
    pub struct Transform3D {
        #[pyo3(get, set)]
        pub px: f32,
        #[pyo3(get, set)]
        pub py: f32,
        #[pyo3(get, set)]
        pub pz: f32,
        #[pyo3(get, set)]
        pub rx: f32,
        #[pyo3(get, set)]
        pub ry: f32,
        #[pyo3(get, set)]
        pub rz: f32,
        #[pyo3(get, set)]
        pub sx: f32,
        #[pyo3(get, set)]
        pub sy: f32,
        #[pyo3(get, set)]
        pub sz: f32,
    }

    #[pymethods]
    impl Transform3D {
        #[new]
        #[pyo3(signature = (px=0.0, py=0.0, pz=0.0, rx=0.0, ry=0.0, rz=0.0, sx=1.0, sy=1.0, sz=1.0))]
        pub fn new(
            px: f32, py: f32, pz: f32,
            rx: f32, ry: f32, rz: f32,
            sx: f32, sy: f32, sz: f32,
        ) -> Self {
            Self { px, py, pz, rx, ry, rz, sx, sy, sz }
        }
    }

    // -------------------------------------------------------------------------
    // Matrix helpers (row-major 4x4 stored as [f32; 16], row-first)
    // -------------------------------------------------------------------------

    fn identity() -> [f32; 16] {
        [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
    }

    fn transform_to_matrix(t: &Transform3D) -> [f32; 16] {
        let (cx, sx) = (t.rx.cos(), t.rx.sin());
        let (cy, sy) = (t.ry.cos(), t.ry.sin());
        let (cz, sz) = (t.rz.cos(), t.rz.sin());

        // R = Rz * Ry * Rx (XYZ intrinsic Euler)
        let r00 = cz * cy;
        let r01 = cz * sy * sx - sz * cx;
        let r02 = cz * sy * cx + sz * sx;
        let r10 = sz * cy;
        let r11 = sz * sy * sx + cz * cx;
        let r12 = sz * sy * cx - cz * sx;
        let r20 = -sy;
        let r21 = cy * sx;
        let r22 = cy * cx;

        [
            r00 * t.sx, r01 * t.sy, r02 * t.sz, t.px,
            r10 * t.sx, r11 * t.sy, r12 * t.sz, t.py,
            r20 * t.sx, r21 * t.sy, r22 * t.sz, t.pz,
            0.0,        0.0,        0.0,        1.0,
        ]
    }

    fn matmul(a: &[f32; 16], b: &[f32; 16]) -> [f32; 16] {
        let mut out = [0.0f32; 16];
        for i in 0..4 {
            for j in 0..4 {
                let mut s = 0.0f32;
                for k in 0..4 {
                    s += a[i * 4 + k] * b[k * 4 + j];
                }
                out[i * 4 + j] = s;
            }
        }
        out
    }

    // -------------------------------------------------------------------------
    // walk_transforms — the actual hot path
    // -------------------------------------------------------------------------

    /// Compute world matrices for a batch of transforms.
    ///
    /// * `local_transforms` — nodes in ANY order (each references parent by index)
    /// * `parent_indices`   — parallel array, -1 for roots
    ///
    /// Naive O(N) two-pass:
    ///   1. Topological sort by walking parent chains
    ///   2. Propagate world matrices in topological order
    #[pyfunction]
    pub fn walk_transforms(
        py: Python<'_>,
        local_transforms: Vec<Transform3D>,
        parent_indices: Vec<i32>,
    ) -> PyResult<PyObject> {
        let n = local_transforms.len();
        if parent_indices.len() != n {
            return Err(pyo3::exceptions::PyValueError::new_err(
                "local_transforms and parent_indices must have the same length",
            ));
        }

        // Pass 1: topological sort (root-to-leaf).  Cycle-safe via depth cap.
        let mut order: Vec<usize> = Vec::with_capacity(n);
        let mut depth: Vec<i32> = vec![-1; n];
        for i in 0..n {
            if depth[i] >= 0 { continue; }
            // Compute depth by walking parent chain
            let mut chain: Vec<usize> = Vec::new();
            let mut cursor: i32 = i as i32;
            let mut hops = 0;
            while cursor >= 0 && depth[cursor as usize] < 0 {
                if hops > n {
                    return Err(pyo3::exceptions::PyValueError::new_err(
                        "cycle detected in parent_indices",
                    ));
                }
                chain.push(cursor as usize);
                cursor = parent_indices[cursor as usize];
                hops += 1;
            }
            let base = if cursor >= 0 { depth[cursor as usize] } else { -1 };
            for (k, &idx) in chain.iter().rev().enumerate() {
                depth[idx] = base + 1 + k as i32;
            }
        }

        let mut indexed: Vec<(usize, i32)> = (0..n).map(|i| (i, depth[i])).collect();
        indexed.sort_by_key(|&(_, d)| d);
        for (i, _) in indexed {
            order.push(i);
        }

        // Pass 2: propagate world matrices in topological order
        let mut world: Vec<[f32; 16]> = vec![identity(); n];
        for &i in &order {
            let local_m = transform_to_matrix(&local_transforms[i]);
            let parent = parent_indices[i];
            world[i] = if parent < 0 {
                local_m
            } else {
                matmul(&world[parent as usize], &local_m)
            };
        }

        // Marshal into a Python list of length-16 lists
        let py_list = PyList::empty_bound(py);
        for m in world.iter() {
            let row = PyList::new_bound(py, m.iter().copied());
            py_list.append(row)?;
        }
        Ok(py_list.into())
    }

    // -------------------------------------------------------------------------
    // Register
    // -------------------------------------------------------------------------

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        let submod = PyModule::new_bound(m.py(), "scene_walk")?;
        submod.add_class::<Transform3D>()?;
        submod.add_function(wrap_pyfunction!(walk_transforms, &submod)?)?;
        m.add_submodule(&submod)?;
        Ok(())
    }
}
