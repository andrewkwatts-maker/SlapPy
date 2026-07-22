//! Sprint 4 SOLID refactor: `RenderFeatures` probe contract.
//!
//! Exercises the cached feature probe without a live wgpu adapter.
//! Runtime probing against a real adapter happens in the visual
//! regression harness (Sprint 5) — here we verify the API contract
//! (baseline is sensible, `from_flags` composes, format choice stays
//! stable across probes).

use pharos_render::RenderFeatures;

#[test]
fn baseline_probe_reports_sensible_defaults() {
    let f = RenderFeatures::baseline();
    assert!(!f.timestamp_query);
    assert!(!f.push_constants);
    assert_eq!(f.reservoir_format, wgpu::TextureFormat::Rgba16Float);
    // Baseline max MSAA is 1 (software / integrated GPU worst-case).
    assert_eq!(f.max_msaa_samples, 1);
}

#[test]
fn from_flags_composes_over_baseline() {
    let f = RenderFeatures::from_flags(true, true);
    assert!(f.timestamp_query);
    assert!(f.push_constants);
    // Format choice remains at baseline — the flag helper does not
    // upgrade storage format; only a real adapter probe does that.
    assert_eq!(f.reservoir_format, wgpu::TextureFormat::Rgba16Float);
}

#[test]
fn baseline_is_default() {
    let a = RenderFeatures::default();
    let b = RenderFeatures::baseline();
    assert_eq!(a.reservoir_format, b.reservoir_format);
    assert_eq!(a.max_msaa_samples, b.max_msaa_samples);
    assert_eq!(a.timestamp_query, b.timestamp_query);
    assert_eq!(a.push_constants, b.push_constants);
}
