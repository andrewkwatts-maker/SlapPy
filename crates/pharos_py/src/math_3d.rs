#[cfg(feature = "3d")]
pub mod math_3d {
    use pyo3::prelude::*;

    // -------------------------------------------------------------------------
    // Vec3
    // -------------------------------------------------------------------------

    #[pyclass]
    #[derive(Clone, Copy, Debug)]
    pub struct Vec3 {
        #[pyo3(get, set)]
        pub x: f32,
        #[pyo3(get, set)]
        pub y: f32,
        #[pyo3(get, set)]
        pub z: f32,
    }

    #[pymethods]
    impl Vec3 {
        #[new]
        pub fn new(x: f32, y: f32, z: f32) -> Self {
            Self { x, y, z }
        }

        pub fn dot(&self, other: Vec3) -> f32 {
            self.x * other.x + self.y * other.y + self.z * other.z
        }

        pub fn cross(&self, other: Vec3) -> Vec3 {
            Vec3 {
                x: self.y * other.z - self.z * other.y,
                y: self.z * other.x - self.x * other.z,
                z: self.x * other.y - self.y * other.x,
            }
        }

        pub fn length(&self) -> f32 {
            (self.x * self.x + self.y * self.y + self.z * self.z).sqrt()
        }

        pub fn normalize(&self) -> Vec3 {
            let len = self.length();
            if len == 0.0 {
                Vec3 { x: 0.0, y: 0.0, z: 0.0 }
            } else {
                Vec3 {
                    x: self.x / len,
                    y: self.y / len,
                    z: self.z / len,
                }
            }
        }

        pub fn add(&self, other: Vec3) -> Vec3 {
            Vec3 {
                x: self.x + other.x,
                y: self.y + other.y,
                z: self.z + other.z,
            }
        }

        pub fn sub(&self, other: Vec3) -> Vec3 {
            Vec3 {
                x: self.x - other.x,
                y: self.y - other.y,
                z: self.z - other.z,
            }
        }

        pub fn mul(&self, scalar: f32) -> Vec3 {
            Vec3 {
                x: self.x * scalar,
                y: self.y * scalar,
                z: self.z * scalar,
            }
        }

        pub fn __add__(&self, other: Vec3) -> Vec3 {
            self.add(other)
        }

        pub fn __sub__(&self, other: Vec3) -> Vec3 {
            self.sub(other)
        }

        pub fn __mul__(&self, scalar: f32) -> Vec3 {
            self.mul(scalar)
        }

        pub fn __neg__(&self) -> Vec3 {
            Vec3 {
                x: -self.x,
                y: -self.y,
                z: -self.z,
            }
        }

        pub fn __repr__(&self) -> String {
            format!("Vec3({}, {}, {})", self.x, self.y, self.z)
        }
    }

    // -------------------------------------------------------------------------
    // Vec4
    // -------------------------------------------------------------------------

    #[pyclass]
    #[derive(Clone, Copy, Debug)]
    pub struct Vec4 {
        #[pyo3(get, set)]
        pub x: f32,
        #[pyo3(get, set)]
        pub y: f32,
        #[pyo3(get, set)]
        pub z: f32,
        #[pyo3(get, set)]
        pub w: f32,
    }

    #[pymethods]
    impl Vec4 {
        #[new]
        pub fn new(x: f32, y: f32, z: f32, w: f32) -> Self {
            Self { x, y, z, w }
        }

        pub fn dot(&self, other: Vec4) -> f32 {
            self.x * other.x + self.y * other.y + self.z * other.z + self.w * other.w
        }

        pub fn length(&self) -> f32 {
            (self.x * self.x + self.y * self.y + self.z * self.z + self.w * self.w).sqrt()
        }

        pub fn normalize(&self) -> Vec4 {
            let len = self.length();
            if len == 0.0 {
                Vec4 { x: 0.0, y: 0.0, z: 0.0, w: 0.0 }
            } else {
                Vec4 {
                    x: self.x / len,
                    y: self.y / len,
                    z: self.z / len,
                    w: self.w / len,
                }
            }
        }

        pub fn __repr__(&self) -> String {
            format!("Vec4({}, {}, {}, {})", self.x, self.y, self.z, self.w)
        }
    }

    // -------------------------------------------------------------------------
    // Mat4x4  (column-major storage; rows indexed as data[col][row])
    // -------------------------------------------------------------------------
    //
    // Internal layout: `cols[c][r]` — column-major so that the raw bytes match
    // what WGSL / wgpu expect for a mat4x4<f32>.
    //
    // Exposed to Python as a flat list of 16 f32s via `data()`, also
    // column-major, ready for direct GPU upload.

    #[pyclass]
    #[derive(Clone, Copy, Debug)]
    pub struct Mat4x4 {
        /// Column-major: `cols[col][row]`
        cols: [[f32; 4]; 4],
    }

    impl Mat4x4 {
        /// Construct from column arrays (internal helper, not exposed to Python).
        fn from_cols(cols: [[f32; 4]; 4]) -> Self {
            Self { cols }
        }

        /// Matrix multiply (self * rhs), both column-major.
        fn mat_mul(a: &Mat4x4, b: &Mat4x4) -> Mat4x4 {
            let mut result = [[0.0f32; 4]; 4];
            for col in 0..4 {
                for row in 0..4 {
                    let mut sum = 0.0f32;
                    for k in 0..4 {
                        sum += a.cols[k][row] * b.cols[col][k];
                    }
                    result[col][row] = sum;
                }
            }
            Mat4x4::from_cols(result)
        }
    }

    #[pymethods]
    impl Mat4x4 {
        /// 4×4 identity matrix.
        #[staticmethod]
        pub fn identity() -> Mat4x4 {
            Mat4x4::from_cols([
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ])
        }

        /// Translation matrix: T(v).
        #[staticmethod]
        pub fn from_translation(v: Vec3) -> Mat4x4 {
            Mat4x4::from_cols([
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
                [v.x, v.y, v.z, 1.0],
            ])
        }

        /// Non-uniform scale matrix: S(v).
        #[staticmethod]
        pub fn from_scale(v: Vec3) -> Mat4x4 {
            Mat4x4::from_cols([
                [v.x, 0.0, 0.0, 0.0],
                [0.0, v.y, 0.0, 0.0],
                [0.0, 0.0, v.z, 0.0],
                [0.0, 0.0, 0.0, 1.0],
            ])
        }

        /// Rotation matrix from a unit quaternion.
        #[staticmethod]
        pub fn from_rotation(q: Quaternion) -> Mat4x4 {
            q.to_mat4()
        }

        /// Matrix multiplication: `self * other`.
        pub fn mul(&self, other: Mat4x4) -> Mat4x4 {
            Mat4x4::mat_mul(self, &other)
        }

        /// Transform a point (applies translation): returns `self * (x,y,z,1)` as Vec3.
        pub fn transform_point(&self, v: Vec3) -> Vec3 {
            let x = self.cols[0][0] * v.x + self.cols[1][0] * v.y + self.cols[2][0] * v.z + self.cols[3][0];
            let y = self.cols[0][1] * v.x + self.cols[1][1] * v.y + self.cols[2][1] * v.z + self.cols[3][1];
            let z = self.cols[0][2] * v.x + self.cols[1][2] * v.y + self.cols[2][2] * v.z + self.cols[3][2];
            Vec3 { x, y, z }
        }

        /// Transform a direction (ignores translation): returns `self * (x,y,z,0)` as Vec3.
        pub fn transform_direction(&self, v: Vec3) -> Vec3 {
            let x = self.cols[0][0] * v.x + self.cols[1][0] * v.y + self.cols[2][0] * v.z;
            let y = self.cols[0][1] * v.x + self.cols[1][1] * v.y + self.cols[2][1] * v.z;
            let z = self.cols[0][2] * v.x + self.cols[1][2] * v.y + self.cols[2][2] * v.z;
            Vec3 { x, y, z }
        }

        /// Transpose of this matrix.
        pub fn transpose(&self) -> Mat4x4 {
            let mut result = [[0.0f32; 4]; 4];
            for col in 0..4 {
                for row in 0..4 {
                    result[row][col] = self.cols[col][row];
                }
            }
            Mat4x4::from_cols(result)
        }

        /// Flat 16-element list, column-major, ready for GPU upload.
        pub fn data(&self) -> Vec<f32> {
            let mut out = Vec::with_capacity(16);
            for col in &self.cols {
                for &v in col {
                    out.push(v);
                }
            }
            out
        }

        pub fn __repr__(&self) -> String {
            format!(
                "Mat4x4([{:.3}, {:.3}, {:.3}, {:.3}, \
                         {:.3}, {:.3}, {:.3}, {:.3}, \
                         {:.3}, {:.3}, {:.3}, {:.3}, \
                         {:.3}, {:.3}, {:.3}, {:.3}])",
                self.cols[0][0], self.cols[1][0], self.cols[2][0], self.cols[3][0],
                self.cols[0][1], self.cols[1][1], self.cols[2][1], self.cols[3][1],
                self.cols[0][2], self.cols[1][2], self.cols[2][2], self.cols[3][2],
                self.cols[0][3], self.cols[1][3], self.cols[2][3], self.cols[3][3],
            )
        }
    }

    // -------------------------------------------------------------------------
    // Quaternion  (x, y, z, w) — Hamilton convention
    // -------------------------------------------------------------------------

    #[pyclass]
    #[derive(Clone, Copy, Debug)]
    pub struct Quaternion {
        #[pyo3(get, set)]
        pub x: f32,
        #[pyo3(get, set)]
        pub y: f32,
        #[pyo3(get, set)]
        pub z: f32,
        #[pyo3(get, set)]
        pub w: f32,
    }

    #[pymethods]
    impl Quaternion {
        /// Identity quaternion (no rotation).
        #[staticmethod]
        pub fn identity() -> Quaternion {
            Quaternion { x: 0.0, y: 0.0, z: 0.0, w: 1.0 }
        }

        /// Build a quaternion from an axis-angle rotation.
        /// `axis` should be a unit vector; `radians` is the rotation angle.
        #[staticmethod]
        pub fn from_axis_angle(axis: Vec3, radians: f32) -> Quaternion {
            let half = radians * 0.5;
            let s = half.sin();
            let n = axis.normalize();
            Quaternion {
                x: n.x * s,
                y: n.y * s,
                z: n.z * s,
                w: half.cos(),
            }
        }

        /// Build a quaternion from intrinsic Euler angles (X then Y then Z rotations).
        #[staticmethod]
        pub fn from_euler_xyz(roll: f32, pitch: f32, yaw: f32) -> Quaternion {
            // Half angles
            let (sr, cr) = ((roll * 0.5).sin(), (roll * 0.5).cos());
            let (sp, cp) = ((pitch * 0.5).sin(), (pitch * 0.5).cos());
            let (sy, cy) = ((yaw * 0.5).sin(), (yaw * 0.5).cos());

            // Combine: Q_z * Q_y * Q_x  (intrinsic XYZ == extrinsic ZYX)
            Quaternion {
                w: cr * cp * cy + sr * sp * sy,
                x: sr * cp * cy - cr * sp * sy,
                y: cr * sp * cy + sr * cp * sy,
                z: cr * cp * sy - sr * sp * cy,
            }
        }

        /// Return a unit-length copy of this quaternion.
        pub fn normalize(&self) -> Quaternion {
            let len = (self.x * self.x + self.y * self.y + self.z * self.z + self.w * self.w).sqrt();
            if len == 0.0 {
                Quaternion::identity()
            } else {
                Quaternion {
                    x: self.x / len,
                    y: self.y / len,
                    z: self.z / len,
                    w: self.w / len,
                }
            }
        }

        /// Hamilton product: `self * other`.
        pub fn mul(&self, other: Quaternion) -> Quaternion {
            Quaternion {
                w: self.w * other.w - self.x * other.x - self.y * other.y - self.z * other.z,
                x: self.w * other.x + self.x * other.w + self.y * other.z - self.z * other.y,
                y: self.w * other.y - self.x * other.z + self.y * other.w + self.z * other.x,
                z: self.w * other.z + self.x * other.y - self.y * other.x + self.z * other.w,
            }
        }

        /// Conjugate (inverse rotation for unit quaternions).
        pub fn conjugate(&self) -> Quaternion {
            Quaternion { x: -self.x, y: -self.y, z: -self.z, w: self.w }
        }

        /// Convert to a column-major 4×4 rotation matrix.
        pub fn to_mat4(&self) -> Mat4x4 {
            let q = self.normalize();
            let (x, y, z, w) = (q.x, q.y, q.z, q.w);

            let x2 = x + x;
            let y2 = y + y;
            let z2 = z + z;

            let xx = x * x2;
            let xy = x * y2;
            let xz = x * z2;
            let yy = y * y2;
            let yz = y * z2;
            let zz = z * z2;
            let wx = w * x2;
            let wy = w * y2;
            let wz = w * z2;

            // Column-major: cols[col][row]
            Mat4x4::from_cols([
                [1.0 - (yy + zz),   xy + wz,         xz - wy,         0.0],
                [xy - wz,           1.0 - (xx + zz), yz + wx,         0.0],
                [xz + wy,           yz - wx,         1.0 - (xx + yy), 0.0],
                [0.0,               0.0,             0.0,             1.0],
            ])
        }

        pub fn __mul__(&self, other: Quaternion) -> Quaternion {
            self.mul(other)
        }

        pub fn __repr__(&self) -> String {
            format!("Quaternion({}, {}, {}, {})", self.x, self.y, self.z, self.w)
        }
    }

    // -------------------------------------------------------------------------
    // Module registration
    // -------------------------------------------------------------------------

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<Vec3>()?;
        m.add_class::<Vec4>()?;
        m.add_class::<Mat4x4>()?;
        m.add_class::<Quaternion>()?;
        Ok(())
    }
}
