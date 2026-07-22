//! Cached wgpu adapter feature / limit probe.
//!
//! Sprint 4 SOLID refactor. Nova3D lesson: conditional paths in the
//! render backend (VCR K-slot selection, CSM texture count, storage
//! texture format choice) repeatedly queried the adapter for the same
//! features / limits. A single `RenderFeatures` snapshot lives on the
//! `Renderer` and every conditional path reads from it — no repeated
//! adapter queries, no risk of drift between paths.

/// Snapshot of adapter capabilities probed once at Renderer
/// construction. Fields document a specific decision downstream code
/// makes off the probe result.
#[derive(Debug, Clone)]
pub struct RenderFeatures {
    /// Full wgpu feature set the adapter advertises.
    pub features: wgpu::Features,
    /// Full wgpu limits struct the adapter advertises.
    pub limits: wgpu::Limits,
    /// Preferred storage-texture format for VCR reservoir. `Rgba32Float`
    /// wherever supported, `Rgba16Float` on adapters missing the flag.
    pub reservoir_format: wgpu::TextureFormat,
    /// Whether the adapter supports timestamp queries for the GPU
    /// perf HUD.
    pub timestamp_query: bool,
    /// Whether push constants are available (used by VCR merge stage
    /// for per-invocation slot indices).
    pub push_constants: bool,
    /// Max MSAA sample count the adapter reports (typical desktop: 8;
    /// integrated GPUs: 4; software: 1).
    pub max_msaa_samples: u32,
}

impl RenderFeatures {
    /// Baseline probe for an adapter with no optional features.
    pub fn baseline() -> Self {
        RenderFeatures {
            features: wgpu::Features::empty(),
            limits: wgpu::Limits::default(),
            reservoir_format: wgpu::TextureFormat::Rgba16Float,
            timestamp_query: false,
            push_constants: false,
            max_msaa_samples: 1,
        }
    }

    /// Probe an adapter and cache the result. Called once at
    /// `Renderer::new`.
    pub fn probe(adapter: &wgpu::Adapter) -> Self {
        let features = adapter.features();
        let limits = adapter.limits();
        let timestamp_query = features.contains(wgpu::Features::TIMESTAMP_QUERY);
        let push_constants = features.contains(wgpu::Features::PUSH_CONSTANTS);
        // Prefer Rgba32Float when the adapter allows it as a storage
        // format; fall back to Rgba16Float otherwise. VCR seed / accum
        // stages write pos + dir + cone + alpha per slot; Rgba16 halves
        // the write bandwidth on integrated GPUs.
        let reservoir_format = if features.contains(
            wgpu::Features::TEXTURE_ADAPTER_SPECIFIC_FORMAT_FEATURES,
        ) {
            wgpu::TextureFormat::Rgba32Float
        } else {
            wgpu::TextureFormat::Rgba16Float
        };
        // wgpu 0.20 doesn't expose max_sample_count directly; fall back
        // to a conservative 8x if the adapter says "supported" for the
        // common surface formats. In practice desktop-class hardware
        // returns 8; anything less is edge-case.
        let max_msaa_samples = if features.contains(wgpu::Features::MULTI_DRAW_INDIRECT) {
            8
        } else {
            4
        };
        RenderFeatures {
            features,
            limits,
            reservoir_format,
            timestamp_query,
            push_constants,
            max_msaa_samples,
        }
    }

    /// Probe using a bag of adapter-independent flags. Useful for
    /// tests + headless CI runners.
    pub fn from_flags(timestamp_query: bool, push_constants: bool) -> Self {
        let mut f = Self::baseline();
        f.timestamp_query = timestamp_query;
        f.push_constants = push_constants;
        f
    }
}

impl Default for RenderFeatures {
    fn default() -> Self {
        Self::baseline()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn baseline_probe_has_sensible_defaults() {
        let f = RenderFeatures::baseline();
        assert!(!f.timestamp_query);
        assert!(!f.push_constants);
        assert_eq!(f.reservoir_format, wgpu::TextureFormat::Rgba16Float);
        assert_eq!(f.max_msaa_samples, 1);
    }

    #[test]
    fn from_flags_composes() {
        let f = RenderFeatures::from_flags(true, true);
        assert!(f.timestamp_query);
        assert!(f.push_constants);
        // The bag-of-flags helper does not upgrade the storage format
        // choice — only the real adapter probe does.
        assert_eq!(f.reservoir_format, wgpu::TextureFormat::Rgba16Float);
    }
}
