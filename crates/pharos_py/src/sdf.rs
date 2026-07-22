#[cfg(feature = "3d")]
pub mod sdf {
    use pyo3::prelude::*;

    // -------------------------------------------------------------------------
    // Primitive type discriminants  (match WGSL PRIM_* constants)
    // -------------------------------------------------------------------------

    const PRIM_SPHERE:      u32 = 0;
    const PRIM_BOX:         u32 = 1;
    const PRIM_CYLINDER:    u32 = 2;
    const PRIM_CAPSULE:     u32 = 3;
    const PRIM_CONE:        u32 = 4;
    const PRIM_TORUS:       u32 = 5;
    const PRIM_PLANE:       u32 = 6;
    const PRIM_ROUNDED_BOX: u32 = 7;

    // -------------------------------------------------------------------------
    // CSG op discriminants
    // -------------------------------------------------------------------------

    const CSG_UNION:             u32 = 0;
    const CSG_SUBTRACT:          u32 = 1;
    const CSG_INTERSECT:         u32 = 2;
    const CSG_SMOOTH_UNION:      u32 = 3;
    const CSG_SMOOTH_SUBTRACT:   u32 = 4;
    const CSG_SMOOTH_INTERSECT:  u32 = 5;

    // -------------------------------------------------------------------------
    // Internal repr used by SdfScene
    // -------------------------------------------------------------------------

    #[derive(Clone)]
    struct PrimData {
        center:    [f32; 3],
        prim_type: u32,
        params:    [f32; 4],
        csg_op:    u32,
        smooth_k:  f32,
    }

    impl PrimData {
        fn to_bytes(&self) -> Vec<u8> {
            // WGSL layout (48 bytes):
            //   vec4<f32>  center_p0:  [cx, cy, cz, params[0]]
            //   vec4<f32>  params_ext: [params[1], params[2], smooth_k, params[3]]
            //   u32        prim_type
            //   u32        csg_op
            //   u32        _pad0
            //   u32        _pad1
            let mut buf = Vec::with_capacity(48);
            for &v in &[self.center[0], self.center[1], self.center[2], self.params[0]] {
                buf.extend_from_slice(&v.to_le_bytes());
            }
            for &v in &[self.params[1], self.params[2], self.smooth_k, self.params[3]] {
                buf.extend_from_slice(&v.to_le_bytes());
            }
            buf.extend_from_slice(&self.prim_type.to_le_bytes());
            buf.extend_from_slice(&self.csg_op.to_le_bytes());
            buf.extend_from_slice(&0u32.to_le_bytes());
            buf.extend_from_slice(&0u32.to_le_bytes());
            buf
        }
    }

    // -------------------------------------------------------------------------
    // SdfPrimitive
    // -------------------------------------------------------------------------

    #[pyclass]
    pub struct SdfPrimitive {
        inner: PrimData,
    }

    #[pymethods]
    impl SdfPrimitive {
        #[staticmethod]
        pub fn sphere(cx: f32, cy: f32, cz: f32, radius: f32) -> Self {
            Self {
                inner: PrimData {
                    center:    [cx, cy, cz],
                    prim_type: PRIM_SPHERE,
                    params:    [radius, 0.0, 0.0, 0.0],
                    csg_op:    CSG_UNION,
                    smooth_k:  0.0,
                },
            }
        }

        #[staticmethod]
        pub fn box_(cx: f32, cy: f32, cz: f32, hx: f32, hy: f32, hz: f32) -> Self {
            Self {
                inner: PrimData {
                    center:    [cx, cy, cz],
                    prim_type: PRIM_BOX,
                    params:    [hx, hy, hz, 0.0],
                    csg_op:    CSG_UNION,
                    smooth_k:  0.0,
                },
            }
        }

        #[staticmethod]
        pub fn cylinder(cx: f32, cy: f32, cz: f32, height: f32, radius: f32) -> Self {
            Self {
                inner: PrimData {
                    center:    [cx, cy, cz],
                    prim_type: PRIM_CYLINDER,
                    params:    [height, radius, 0.0, 0.0],
                    csg_op:    CSG_UNION,
                    smooth_k:  0.0,
                },
            }
        }

        /// `center` is the midpoint of segment AB; AB direction and length are
        /// encoded as params[0..2] = B - A, params[3] = radius.
        #[staticmethod]
        pub fn capsule(ax: f32, ay: f32, az: f32, bx: f32, by: f32, bz: f32, radius: f32) -> Self {
            let cx = (ax + bx) * 0.5;
            let cy = (ay + by) * 0.5;
            let cz = (az + bz) * 0.5;
            Self {
                inner: PrimData {
                    center:    [cx, cy, cz],
                    prim_type: PRIM_CAPSULE,
                    // params: [ba.x, ba.y, ba.z, radius]  — WGSL unpacks these
                    params:    [bx - ax, by - ay, bz - az, radius],
                    csg_op:    CSG_UNION,
                    smooth_k:  0.0,
                },
            }
        }

        #[staticmethod]
        pub fn cone(cx: f32, cy: f32, cz: f32, height: f32, angle: f32) -> Self {
            Self {
                inner: PrimData {
                    center:    [cx, cy, cz],
                    prim_type: PRIM_CONE,
                    params:    [height, angle, 0.0, 0.0],
                    csg_op:    CSG_UNION,
                    smooth_k:  0.0,
                },
            }
        }

        #[staticmethod]
        pub fn torus(cx: f32, cy: f32, cz: f32, r_major: f32, r_minor: f32) -> Self {
            Self {
                inner: PrimData {
                    center:    [cx, cy, cz],
                    prim_type: PRIM_TORUS,
                    params:    [r_major, r_minor, 0.0, 0.0],
                    csg_op:    CSG_UNION,
                    smooth_k:  0.0,
                },
            }
        }

        /// Plane defined by normal (nx, ny, nz) and signed distance `d` from origin.
        /// `center` stores the normal; params[0] = d.
        #[staticmethod]
        pub fn plane(nx: f32, ny: f32, nz: f32, d: f32) -> Self {
            Self {
                inner: PrimData {
                    center:    [nx, ny, nz],
                    prim_type: PRIM_PLANE,
                    params:    [d, 0.0, 0.0, 0.0],
                    csg_op:    CSG_UNION,
                    smooth_k:  0.0,
                },
            }
        }

        #[staticmethod]
        pub fn rounded_box(cx: f32, cy: f32, cz: f32, hx: f32, hy: f32, hz: f32, round: f32) -> Self {
            Self {
                inner: PrimData {
                    center:    [cx, cy, cz],
                    prim_type: PRIM_ROUNDED_BOX,
                    // params[3] carries the corner radius; the WGSL shader reads it
                    // from the second vec4's w component (params_ext.w).
                    params:    [hx, hy, hz, round],
                    csg_op:    CSG_UNION,
                    smooth_k:  0.0,
                },
            }
        }

        pub fn set_csg_op(&mut self, op: u32) {
            self.inner.csg_op = op;
        }

        pub fn set_smooth_k(&mut self, k: f32) {
            self.inner.smooth_k = k;
        }

        /// Serialize to 48 bytes matching the WGSL `SdfPrimitive` struct layout.
        pub fn to_bytes(&self) -> Vec<u8> {
            self.inner.to_bytes()
        }

        pub fn __repr__(&self) -> String {
            format!(
                "SdfPrimitive(type={}, csg_op={}, center=[{:.3},{:.3},{:.3}])",
                self.inner.prim_type,
                self.inner.csg_op,
                self.inner.center[0],
                self.inner.center[1],
                self.inner.center[2],
            )
        }
    }

    // -------------------------------------------------------------------------
    // SdfScene
    // -------------------------------------------------------------------------

    #[pyclass]
    pub struct SdfScene {
        primitives: Vec<PrimData>,
    }

    #[pymethods]
    impl SdfScene {
        #[new]
        pub fn new() -> Self {
            Self { primitives: Vec::new() }
        }

        pub fn add(&mut self, prim: &SdfPrimitive) {
            self.primitives.push(prim.inner.clone());
        }

        pub fn clear(&mut self) {
            self.primitives.clear();
        }

        pub fn len(&self) -> usize {
            self.primitives.len()
        }

        /// Flat byte buffer of all primitives (48 bytes each) ready for GPU upload.
        pub fn to_gpu_bytes(&self) -> Vec<u8> {
            let mut buf = Vec::with_capacity(self.primitives.len() * 48);
            for p in &self.primitives {
                buf.extend_from_slice(&p.to_bytes());
            }
            buf
        }

        pub fn __repr__(&self) -> String {
            format!("SdfScene(primitives={})", self.primitives.len())
        }
    }

    // -------------------------------------------------------------------------
    // Module registration
    // -------------------------------------------------------------------------

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<SdfPrimitive>()?;
        m.add_class::<SdfScene>()?;
        Ok(())
    }
}

// lib.rs: add `#[cfg(feature = "3d")] mod sdf;` and `sdf::sdf::register(m)?`
