pub mod sdf_collision {
    use pyo3::prelude::*;

    // -------------------------------------------------------------------------
    // Primitive type discriminants  (mirrors sdf.rs and WGSL PRIM_* constants)
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
    // GPU record layout  (48 bytes per primitive, matches PrimData::to_bytes)
    //
    //   offset  0: vec4<f32>  [cx, cy, cz, params[0]]
    //   offset 16: vec4<f32>  [params[1], params[2], smooth_k, params[3]]
    //   offset 32: u32        prim_type
    //   offset 36: u32        csg_op
    //   offset 40: u32        _pad0
    //   offset 44: u32        _pad1
    // -------------------------------------------------------------------------

    const RECORD_BYTES: usize = 48;

    /// Decoded view of a single primitive record.
    struct Prim {
        prim_type: u32,
        center:    [f32; 3],
        params:    [f32; 4],  // params[0..3] as stored in the GPU record
    }

    fn read_f32(data: &[u8], offset: usize) -> f32 {
        f32::from_le_bytes(data[offset..offset + 4].try_into().unwrap())
    }

    fn read_u32(data: &[u8], offset: usize) -> u32 {
        u32::from_le_bytes(data[offset..offset + 4].try_into().unwrap())
    }

    fn decode_record(record: &[u8]) -> Prim {
        // vec4 #0:  [cx, cy, cz, params[0]]
        let cx       = read_f32(record,  0);
        let cy       = read_f32(record,  4);
        let cz       = read_f32(record,  8);
        let p0       = read_f32(record, 12);
        // vec4 #1:  [params[1], params[2], smooth_k, params[3]]
        let p1       = read_f32(record, 16);
        let p2       = read_f32(record, 20);
        // smooth_k at offset 24 — not needed for collision
        let p3       = read_f32(record, 28);
        // scalars
        let prim_type = read_u32(record, 32);

        Prim {
            prim_type,
            center: [cx, cy, cz],
            params: [p0, p1, p2, p3],
        }
    }

    // -------------------------------------------------------------------------
    // SDF distance evaluators — safe Rust mirrors of the WGSL functions
    // Signed distance: negative = inside, positive = outside.
    // -------------------------------------------------------------------------

    #[inline]
    fn dist_sphere(
        px: f32, py: f32, pz: f32,
        cx: f32, cy: f32, cz: f32,
        r: f32,
    ) -> f32 {
        let dx = px - cx;
        let dy = py - cy;
        let dz = pz - cz;
        (dx * dx + dy * dy + dz * dz).sqrt() - r
    }

    #[inline]
    fn dist_box(
        px: f32, py: f32, pz: f32,
        cx: f32, cy: f32, cz: f32,
        hx: f32, hy: f32, hz: f32,
        round: f32,
    ) -> f32 {
        // Standard SDF for a rounded box centred at (cx,cy,cz).
        let qx = (px - cx).abs() - hx;
        let qy = (py - cy).abs() - hy;
        let qz = (pz - cz).abs() - hz;
        let outer = (qx.max(0.0) * qx.max(0.0)
            + qy.max(0.0) * qy.max(0.0)
            + qz.max(0.0) * qz.max(0.0))
            .sqrt();
        let inner = qx.max(qy).max(qz).min(0.0);
        outer + inner - round
    }

    #[inline]
    fn dist_cylinder(
        px: f32, py: f32, pz: f32,
        cx: f32, cy: f32, cz: f32,
        h: f32, r: f32,
    ) -> f32 {
        // Cylinder aligned to Y axis, centred at (cx,cy,cz), half-height h.
        let dx = px - cx;
        let dy = py - cy;
        let dz = pz - cz;
        let radial = (dx * dx + dz * dz).sqrt() - r;
        let axial  = dy.abs() - h;
        let outer = (radial.max(0.0) * radial.max(0.0)
            + axial.max(0.0) * axial.max(0.0))
            .sqrt();
        let inner = radial.max(axial).min(0.0);
        outer + inner
    }

    #[inline]
    fn dist_capsule(
        px: f32, py: f32, pz: f32,
        ax: f32, ay: f32, az: f32,
        bx: f32, by: f32, bz: f32,
        r: f32,
    ) -> f32 {
        // Segment A→B, point P.
        let pax = px - ax;
        let pay = py - ay;
        let paz = pz - az;
        let bax = bx - ax;
        let bay = by - ay;
        let baz = bz - az;
        let ba2 = bax * bax + bay * bay + baz * baz;
        let t = if ba2 > 0.0 {
            ((pax * bax + pay * bay + paz * baz) / ba2).clamp(0.0, 1.0)
        } else {
            0.0
        };
        let qx = pax - bax * t;
        let qy = pay - bay * t;
        let qz = paz - baz * t;
        (qx * qx + qy * qy + qz * qz).sqrt() - r
    }

    #[inline]
    fn dist_torus(
        px: f32, py: f32, pz: f32,
        cx: f32, cy: f32, cz: f32,
        r_major: f32, r_minor: f32,
    ) -> f32 {
        // Torus in the XZ plane, centred at (cx,cy,cz).
        let dx = px - cx;
        let dy = py - cy;
        let dz = pz - cz;
        let radial_xz = (dx * dx + dz * dz).sqrt();
        let qx = radial_xz - r_major;
        let qy = dy;
        (qx * qx + qy * qy).sqrt() - r_minor
    }

    #[inline]
    fn dist_plane(
        px: f32, py: f32, pz: f32,
        nx: f32, ny: f32, nz: f32,
        d: f32,
    ) -> f32 {
        // Plane: dot(P, N) - d  (N should be unit length)
        px * nx + py * ny + pz * nz - d
    }

    /// Evaluate the SDF for a single decoded primitive record.
    fn eval_prim(p: &Prim, px: f32, py: f32, pz: f32) -> f32 {
        let [cx, cy, cz] = p.center;
        let [p0, p1, p2, p3] = p.params;

        match p.prim_type {
            PRIM_SPHERE => {
                // params[0] = radius
                dist_sphere(px, py, pz, cx, cy, cz, p0)
            }
            PRIM_BOX => {
                // params = [hx, hy, hz, 0]
                dist_box(px, py, pz, cx, cy, cz, p0, p1, p2, 0.0)
            }
            PRIM_CYLINDER => {
                // params = [height, radius, _, _]
                dist_cylinder(px, py, pz, cx, cy, cz, p0, p1)
            }
            PRIM_CAPSULE => {
                // center = midpoint, params = [ba.x, ba.y, ba.z, radius]
                // Reconstruct A and B: A = center - ba/2, B = center + ba/2
                let half_bax = p0 * 0.5;
                let half_bay = p1 * 0.5;
                let half_baz = p2 * 0.5;
                let ax = cx - half_bax;
                let ay = cy - half_bay;
                let az = cz - half_baz;
                let bx = cx + half_bax;
                let by = cy + half_bay;
                let bz = cz + half_baz;
                dist_capsule(px, py, pz, ax, ay, az, bx, by, bz, p3)
            }
            PRIM_CONE => {
                // params = [height, angle, _, _]
                // Standard cone SDF aligned to +Y, apex at (cx, cy+height, cz),
                // base at y=cy, half-angle `angle` (radians).
                let dx = px - cx;
                let dy = py - cy;
                let dz = pz - cz;
                let height = p0;
                let angle  = p1;
                let sin_a = angle.sin();
                let cos_a = angle.cos();
                // Project onto the axis
                let radial = (dx * dx + dz * dz).sqrt();
                // q = (length of side component, axial component from apex)
                let qx = radial * cos_a - dy * sin_a;
                let qy = radial * sin_a + dy * cos_a;
                let l  = height / cos_a;  // slant length
                let w  = (qy - l).max(0.0);
                let outer = (qx.max(0.0) * qx.max(0.0) + w * w).sqrt();
                let inner = (-qx).max(qy - l).min(0.0);
                outer + inner
            }
            PRIM_TORUS => {
                // params = [r_major, r_minor, _, _]
                dist_torus(px, py, pz, cx, cy, cz, p0, p1)
            }
            PRIM_PLANE => {
                // center = normal (nx,ny,nz), params[0] = d
                dist_plane(px, py, pz, cx, cy, cz, p0)
            }
            PRIM_ROUNDED_BOX => {
                // params = [hx, hy, hz, round]
                dist_box(px, py, pz, cx, cy, cz, p0, p1, p2, p3)
            }
            _ => f32::MAX,  // unknown primitive — treat as infinitely far away
        }
    }

    // -------------------------------------------------------------------------
    // SdfCollider
    // -------------------------------------------------------------------------

    /// Collision query interface over an SDF scene loaded from GPU byte data.
    ///
    /// Construct with `SdfCollider()`, then call `load_bytes()` with the output
    /// of `SdfScene.to_gpu_bytes()`.  All query methods are usable immediately.
    #[pyclass]
    pub struct SdfCollider {
        /// Raw 48-byte records, one per primitive.
        data: Vec<u8>,
    }

    #[pymethods]
    impl SdfCollider {
        #[new]
        pub fn new() -> Self {
            Self { data: Vec::new() }
        }

        /// Replace the stored primitive data with `data` (output of
        /// `SdfScene.to_gpu_bytes()`).  Any partial trailing record is ignored.
        pub fn load_bytes(&mut self, data: Vec<u8>) {
            self.data = data;
        }

        /// Number of complete primitive records stored.
        pub fn prim_count(&self) -> usize {
            self.data.len() / RECORD_BYTES
        }

        /// Evaluate the scene SDF at point (px, py, pz).
        ///
        /// Returns the signed distance to the nearest surface across all
        /// primitives (union — minimum distance).
        /// Negative = inside, positive = outside.
        pub fn distance(&self, px: f32, py: f32, pz: f32) -> f32 {
            self.scene_dist(px, py, pz)
        }

        /// Compute the outward surface normal at (px, py, pz) via central
        /// differences with step h = 0.001.
        ///
        /// Returns (nx, ny, nz).  If the point is far from all geometry the
        /// returned vector still points away from the nearest surface, though it
        /// may not be unit length in degenerate configurations.
        pub fn normal(&self, px: f32, py: f32, pz: f32) -> (f32, f32, f32) {
            const H: f32 = 0.001;
            let dx = self.scene_dist(px + H, py, pz) - self.scene_dist(px - H, py, pz);
            let dy = self.scene_dist(px, py + H, pz) - self.scene_dist(px, py - H, pz);
            let dz = self.scene_dist(px, py, pz + H) - self.scene_dist(px, py, pz - H);
            let len = (dx * dx + dy * dy + dz * dz).sqrt();
            if len > 1e-10 {
                (dx / len, dy / len, dz / len)
            } else {
                (0.0, 1.0, 0.0)
            }
        }

        /// Conservative AABB overlap test.
        ///
        /// Samples the 8 corners and the centre of the AABB (9 points total).
        /// Returns `true` if any sample has a negative signed distance (inside
        /// the SDF), indicating an overlap.
        pub fn aabb_overlaps(
            &self,
            min_x: f32, min_y: f32, min_z: f32,
            max_x: f32, max_y: f32, max_z: f32,
        ) -> bool {
            let mid_x = (min_x + max_x) * 0.5;
            let mid_y = (min_y + max_y) * 0.5;
            let mid_z = (min_z + max_z) * 0.5;

            let samples: [(f32, f32, f32); 9] = [
                (min_x, min_y, min_z),
                (max_x, min_y, min_z),
                (min_x, max_y, min_z),
                (max_x, max_y, min_z),
                (min_x, min_y, max_z),
                (max_x, min_y, max_z),
                (min_x, max_y, max_z),
                (max_x, max_y, max_z),
                (mid_x, mid_y, mid_z),
            ];

            for (sx, sy, sz) in samples {
                if self.scene_dist(sx, sy, sz) < 0.0 {
                    return true;
                }
            }
            false
        }

        /// Sphere overlap test.
        ///
        /// Returns `true` if the sphere (centre, radius) intersects the SDF
        /// surface or is entirely inside it.
        pub fn sphere_overlaps(&self, cx: f32, cy: f32, cz: f32, r: f32) -> bool {
            self.scene_dist(cx, cy, cz) < r
        }

        /// Push-out displacement vector.
        ///
        /// For a point that is inside the SDF (d < 0), returns the displacement
        /// `normal * |d|` that moves it to the surface.  If the point is already
        /// outside (d >= 0) the returned vector is (0, 0, 0).
        pub fn push_out(&self, px: f32, py: f32, pz: f32) -> (f32, f32, f32) {
            let d = self.scene_dist(px, py, pz);
            if d >= 0.0 {
                return (0.0, 0.0, 0.0);
            }
            let (nx, ny, nz) = self.normal(px, py, pz);
            let depth = d.abs();
            (nx * depth, ny * depth, nz * depth)
        }
    }

    // -------------------------------------------------------------------------
    // Internal helpers (not exposed to Python)
    // -------------------------------------------------------------------------

    impl SdfCollider {
        /// Evaluate the scene SDF (union of all primitives) at (px, py, pz).
        fn scene_dist(&self, px: f32, py: f32, pz: f32) -> f32 {
            let count = self.prim_count();
            if count == 0 {
                return f32::MAX;
            }
            let mut min_d = f32::MAX;
            for i in 0..count {
                let start = i * RECORD_BYTES;
                let record = &self.data[start..start + RECORD_BYTES];
                let prim = decode_record(record);
                let d = eval_prim(&prim, px, py, pz);
                if d < min_d {
                    min_d = d;
                }
            }
            min_d
        }
    }

    // -------------------------------------------------------------------------
    // Module registration
    // -------------------------------------------------------------------------

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<SdfCollider>()?;
        Ok(())
    }
}

// lib.rs: add `mod sdf_collision;` and `sdf_collision::sdf_collision::register(m)?`
