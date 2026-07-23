//! Temporal Anti-Aliasing (Nova3D S1-W8 port).
//!
//! CPU-side Halton(2,3) jitter generator + quality preset + resolve-
//! shader binding. Sub-pixel jitter is applied to the projection
//! matrix each frame; the resolve pass reprojects & clamps history.

pub const RESOLVE_SHADER: &str = include_str!("../../shaders/postprocess_taa_resolve.wgsl");

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TaaQuality {
    Low,
    Medium,
    High,
    Ultra,
}

#[derive(Debug, Clone, Copy)]
pub struct TaaConfig {
    pub quality:          TaaQuality,
    pub temporal_alpha:   f32,
    pub jitter_scale:     f32,
    pub velocity_reject:  f32,
}

impl Default for TaaConfig {
    fn default() -> Self {
        Self {
            quality:         TaaQuality::High,
            temporal_alpha:  0.1,
            jitter_scale:    1.0,
            velocity_reject: 0.03,
        }
    }
}

impl TaaConfig {
    pub fn sample_count(&self) -> usize {
        match self.quality {
            TaaQuality::Low    => 2,
            TaaQuality::Medium => 4,
            TaaQuality::High   => 8,
            TaaQuality::Ultra  => 16,
        }
    }
}

/// One value of the radical-inverse Halton sequence for a given base.
///
/// Ports Nova3D's `HaltonBase()` (engine/graphics/TAA.cpp @ fbf134c).
/// `index` is 1-based to avoid the (0,0) origin sample.
pub fn halton_base(mut index: u32, base: u32) -> f32 {
    debug_assert!(base >= 2);
    let mut f: f32 = 1.0;
    let mut r: f32 = 0.0;
    let base_f = base as f32;
    while index > 0 {
        f /= base_f;
        r += f * (index % base) as f32;
        index /= base;
    }
    r
}

/// Build `count` Halton(2,3) jitter samples centred on the pixel
/// centre (i.e. each component lives in [-0.5, +0.5]).
///
/// Ports Nova3D's `BuildHaltonSequence()`.
pub fn halton23(count: usize) -> Vec<[f32; 2]> {
    (1..=count as u32)
        .map(|i| [halton_base(i, 2) - 0.5, halton_base(i, 3) - 0.5])
        .collect()
}
