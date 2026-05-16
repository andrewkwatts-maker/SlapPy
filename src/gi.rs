#[cfg(feature = "gi")]
pub mod gi {
    use pyo3::prelude::*;

    // -------------------------------------------------------------------------
    // CascadeLevel  (internal, not exposed to Python)
    // -------------------------------------------------------------------------

    /// Probe grid layout for one cascade level.
    struct CascadeLevel {
        probe_count_x: u32,
        probe_count_y: u32,
        spacing_px: u32,    // world-space pixels between probes
        rays_per_probe: u32,
    }

    // -------------------------------------------------------------------------
    // RadianceCascadeManager
    // -------------------------------------------------------------------------

    /// Manages probe grid allocation and update scheduling for radiance cascade GI.
    ///
    /// Each cascade level doubles the probe spacing and quarters the ray count
    /// relative to the previous level, matching the standard RC formulation:
    ///
    ///   level 0 → spacing = base_spacing,      rays = base_rays
    ///   level 1 → spacing = base_spacing * 2,  rays = base_rays / 4
    ///   level N → spacing = base_spacing << N,  rays = base_rays >> (N*2)
    ///
    /// Update scheduling uses a round-robin scheme where finer (lower-index)
    /// levels refresh more frequently: level 0 updates every frame, level 1
    /// every 2 frames, level 2 every 4 frames, etc.
    #[pyclass]
    pub struct RadianceCascadeManager {
        screen_width:  u32,
        screen_height: u32,
        num_cascades:  u32,
        base_spacing:  u32,  // cascade 0 probe spacing (e.g. 8px)
        base_rays:     u32,  // cascade 0 rays per probe (e.g. 512)
        levels:        Vec<CascadeLevel>,
        dirty:         bool, // set true when screen resized or config changed
        frame_idx:     u64,
    }

    #[pymethods]
    impl RadianceCascadeManager {
        /// Create a new manager.
        ///
        /// Args:
        ///     screen_width:  Render target width in pixels.
        ///     screen_height: Render target height in pixels.
        ///     num_cascades:  Number of cascade levels (typically 4–6).
        ///     base_spacing:  Probe spacing for cascade 0 in pixels (e.g. 8).
        ///     base_rays:     Ray count per probe for cascade 0 (e.g. 512).
        #[new]
        pub fn new(
            screen_width: u32,
            screen_height: u32,
            num_cascades: u32,
            base_spacing: u32,
            base_rays: u32,
        ) -> Self {
            let mut mgr = RadianceCascadeManager {
                screen_width,
                screen_height,
                num_cascades,
                base_spacing,
                base_rays,
                levels: Vec::new(),
                dirty: true,
                frame_idx: 0,
            };
            mgr._rebuild_levels();
            mgr
        }

        /// Notify the manager that the render target has been resized.
        ///
        /// This rebuilds the probe grid for every cascade level and marks
        /// the manager dirty so the caller can re-allocate GPU textures.
        pub fn resize(&mut self, width: u32, height: u32) {
            self.screen_width = width;
            self.screen_height = height;
            self.dirty = true;
            self._rebuild_levels();
        }

        /// Return probe grid info for every cascade level.
        ///
        /// Each entry is a tuple ``(probe_count_x, probe_count_y, spacing_px, rays_per_probe)``.
        pub fn level_info(&self) -> Vec<(u32, u32, u32, u32)> {
            self.levels
                .iter()
                .map(|l| (l.probe_count_x, l.probe_count_y, l.spacing_px, l.rays_per_probe))
                .collect()
        }

        /// Width of the probe atlas texture for `cascade` (probe_count_x * 4).
        ///
        /// The factor of 4 allocates one column per SH L1 coefficient band
        /// (R, G, B channels of the 4 L0+L1 coefficients laid side-by-side).
        /// Returns 0 for an out-of-range cascade index.
        pub fn probe_texture_width(&self, cascade: usize) -> u32 {
            self.levels.get(cascade).map(|l| l.probe_count_x * 4).unwrap_or(0)
        }

        /// Height of the probe atlas texture for `cascade` (probe_count_y).
        ///
        /// Returns 0 for an out-of-range cascade index.
        pub fn probe_texture_height(&self, cascade: usize) -> u32 {
            self.levels.get(cascade).map(|l| l.probe_count_y).unwrap_or(0)
        }

        /// Advance the internal frame counter and return which cascade level
        /// should be updated this frame.
        ///
        /// Scheduling policy: level 0 updates every frame, level 1 every
        /// 2 frames, level N every 2^N frames (round-robin via trailing-zeros
        /// of the frame counter).  The result is clamped to `num_cascades - 1`
        /// so it is always a valid level index.
        ///
        /// Clears the `dirty` flag as a side effect (the caller is assumed to
        /// act on it before calling `advance_frame`).
        pub fn advance_frame(&mut self) -> u32 {
            self.frame_idx += 1;
            self.dirty = false;
            // trailing_zeros gives 0 for odd frames (level 0), 1 when divisible
            // by 2 but not 4 (level 1), etc.
            let update_level = self
                .frame_idx
                .trailing_zeros()
                .min(self.num_cascades.saturating_sub(1));
            update_level
        }

        /// True if the probe grid needs to be re-allocated (after construction
        /// or a `resize` call).  Cleared by `advance_frame`.
        pub fn is_dirty(&self) -> bool {
            self.dirty
        }

        /// Current frame counter (incremented by every `advance_frame` call).
        pub fn frame_index(&self) -> u64 {
            self.frame_idx
        }

        /// Number of cascade levels this manager was configured with.
        pub fn num_cascades(&self) -> u32 {
            self.num_cascades
        }

        pub fn __repr__(&self) -> String {
            format!(
                "RadianceCascadeManager({}x{}, cascades={}, base_spacing={}, base_rays={}, frame={})",
                self.screen_width,
                self.screen_height,
                self.num_cascades,
                self.base_spacing,
                self.base_rays,
                self.frame_idx,
            )
        }
    }

    impl RadianceCascadeManager {
        /// Rebuild the `levels` vector from the current screen size and config.
        ///
        /// Called on construction and after every `resize`.  Not exposed to
        /// Python (leading underscore naming matches the codebase convention
        /// for internal helpers surfaced as pub(crate) or plain `fn`).
        fn _rebuild_levels(&mut self) {
            self.levels.clear();
            for i in 0..self.num_cascades {
                let spacing = self.base_spacing * (1u32 << i); // 8, 16, 32, 64 …
                let rays = self.base_rays >> (i * 2);           // 512, 128, 32, 8 …
                let count_x = (self.screen_width + spacing - 1) / spacing;
                let count_y = (self.screen_height + spacing - 1) / spacing;
                self.levels.push(CascadeLevel {
                    probe_count_x: count_x,
                    probe_count_y: count_y,
                    spacing_px: spacing,
                    rays_per_probe: rays.max(1),
                });
            }
        }
    }

    // -------------------------------------------------------------------------
    // Module registration
    // -------------------------------------------------------------------------

    pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_class::<RadianceCascadeManager>()?;
        Ok(())
    }
}
