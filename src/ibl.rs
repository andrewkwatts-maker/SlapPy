#[cfg(feature = "ibl")]
pub mod ibl {
    use pyo3::prelude::*;
    use rayon::prelude::*;
    use std::f32::consts::PI;

    // -------------------------------------------------------------------------
    // SH L2 projection helper (free function, not exposed to Python)
    // -------------------------------------------------------------------------

    /// Projects an RGBA f32 equirectangular image onto SH L2 (9 coefficients × 3 channels).
    ///
    /// Returns 27 floats laid out as [r0,g0,b0, r1,g1,b1, … r8,g8,b8].
    fn project_sh9(pixels: &[f32], width: usize, height: usize) -> Vec<f32> {
        // Each row produces a partial accumulator: 27 coefficient floats + 1 weight float.
        let row_accumulators: Vec<[f32; 28]> = (0..height)
            .into_par_iter()
            .map(|row| {
                let v = (row as f32 + 0.5) / height as f32; // [0, 1]
                let theta = v * PI;                          // polar angle [0, π]
                let sin_theta = theta.sin();
                let cos_theta = theta.cos();

                let mut acc = [0.0f32; 28]; // [coeff×27 | weight]

                for col in 0..width {
                    let u = (col as f32 + 0.5) / width as f32; // [0, 1]
                    let phi = u * 2.0 * PI;                     // azimuth [0, 2π]

                    // Cartesian direction on the unit sphere.
                    let x = sin_theta * phi.cos();
                    let y = sin_theta * phi.sin();
                    let z = cos_theta;

                    // Solid-angle weight (sin θ dθ dφ, the dθ dφ factors are
                    // equal across all samples and cancel in the normalisation).
                    let weight = sin_theta;

                    // SH L2 basis (real, Condon-Shortley convention omitted).
                    let basis: [f32; 9] = [
                        0.2821,                        // L0: Y_0^0
                        0.4886 * y,                    // L1: Y_1^-1
                        0.4886 * z,                    // L1: Y_1^0
                        0.4886 * x,                    // L1: Y_1^1
                        1.0925 * x * y,                // L2: Y_2^-2
                        1.0925 * y * z,                // L2: Y_2^-1
                        0.3153 * (3.0 * z * z - 1.0),  // L2: Y_2^0
                        1.0925 * x * z,                // L2: Y_2^1
                        0.5463 * (x * x - y * y),      // L2: Y_2^2
                    ];

                    let base = (row * width + col) * 4;
                    let r = pixels[base];
                    let g = pixels[base + 1];
                    let b = pixels[base + 2];

                    for i in 0..9 {
                        let bw = basis[i] * weight;
                        acc[i * 3]     += r * bw;
                        acc[i * 3 + 1] += g * bw;
                        acc[i * 3 + 2] += b * bw;
                    }
                    acc[27] += weight;
                }
                acc
            })
            .collect();

        // Reduce partial accumulators.
        let mut coeffs = vec![0.0f32; 27];
        let mut total_weight = 0.0f32;
        for acc in &row_accumulators {
            for i in 0..27 {
                coeffs[i] += acc[i];
            }
            total_weight += acc[27];
        }

        // Normalise.
        if total_weight > 0.0 {
            let inv = 1.0 / total_weight;
            for c in coeffs.iter_mut() {
                *c *= inv;
            }
        }

        coeffs
    }

    // -------------------------------------------------------------------------
    // IblSH
    // -------------------------------------------------------------------------

    /// SH L2 irradiance probe projected from an HDR equirectangular image.
    ///
    /// Stores 9 × [r, g, b] coefficients (27 f32 values).  Use ``to_bytes()``
    /// to obtain 108 bytes ready for direct upload as a WGPU uniform buffer.
    #[pyclass]
    pub struct IblSH {
        coeffs: Vec<f32>, // 27 floats: 9 × [r, g, b]
    }

    #[pymethods]
    impl IblSH {
        /// Project from a flat RGBA f32 pixel buffer (row-major, width × height × 4 floats).
        #[staticmethod]
        pub fn from_pixels(pixels: Vec<f32>, width: usize, height: usize) -> Self {
            IblSH {
                coeffs: project_sh9(&pixels, width, height),
            }
        }

        /// Project from a flat RGB u8 pixel buffer (converts to f32 by dividing by 255).
        ///
        /// Expects width × height × 3 bytes (RGB, no alpha channel).
        #[staticmethod]
        pub fn from_pixels_u8(pixels: Vec<u8>, width: usize, height: usize) -> Self {
            // Convert RGB u8 → RGBA f32 (alpha = 1.0, unused by projection).
            let mut rgba = Vec::with_capacity(width * height * 4);
            for chunk in pixels.chunks(3) {
                rgba.push(chunk[0] as f32 / 255.0);
                rgba.push(chunk[1] as f32 / 255.0);
                rgba.push(chunk[2] as f32 / 255.0);
                rgba.push(1.0);
            }
            IblSH {
                coeffs: project_sh9(&rgba, width, height),
            }
        }

        /// Returns 108 bytes (27 little-endian f32 values) for direct GPU upload.
        pub fn to_bytes(&self) -> Vec<u8> {
            let mut out = Vec::with_capacity(27 * 4);
            for &v in &self.coeffs {
                out.extend_from_slice(&v.to_le_bytes());
            }
            out
        }

        /// Returns the 27 SH coefficients as a Python list of floats.
        pub fn coefficients(&self) -> Vec<f32> {
            self.coeffs.clone()
        }

        /// Evaluate irradiance for a given normal direction.
        ///
        /// Returns ``(r, g, b)`` — the irradiance from this SH probe at the
        /// supplied surface normal.  The normal need not be unit-length;
        /// the function normalises internally.
        pub fn evaluate(&self, nx: f32, ny: f32, nz: f32) -> (f32, f32, f32) {
            let len = (nx * nx + ny * ny + nz * nz).sqrt().max(1e-8);
            let x = nx / len;
            let y = ny / len;
            let z = nz / len;

            let basis: [f32; 9] = [
                0.2821,
                0.4886 * y,
                0.4886 * z,
                0.4886 * x,
                1.0925 * x * y,
                1.0925 * y * z,
                0.3153 * (3.0 * z * z - 1.0),
                1.0925 * x * z,
                0.5463 * (x * x - y * y),
            ];

            let mut r = 0.0f32;
            let mut g = 0.0f32;
            let mut b = 0.0f32;
            for i in 0..9 {
                r += self.coeffs[i * 3]     * basis[i];
                g += self.coeffs[i * 3 + 1] * basis[i];
                b += self.coeffs[i * 3 + 2] * basis[i];
            }

            (r.max(0.0), g.max(0.0), b.max(0.0))
        }

        pub fn __repr__(&self) -> String {
            format!(
                "IblSH(L0=[{:.4}, {:.4}, {:.4}])",
                self.coeffs[0], self.coeffs[1], self.coeffs[2]
            )
        }
    }

    // -------------------------------------------------------------------------
    // Module registration
    // -------------------------------------------------------------------------

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<IblSH>()?;
        Ok(())
    }
}

// lib.rs: add `#[cfg(feature = "ibl")] mod ibl;` and `ibl::ibl::register(m)?`
