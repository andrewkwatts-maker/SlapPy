//! Nova3D delta port test — Halton(2,3) jitter (S1-W8, tests/graphics/test_taa_jitter.cpp).
//!
//! Mirrors the Nova3D unit test that verifies the CPU-side Halton
//! sequence generator: samples are centred on the pixel centre,
//! bounded in [-0.5, +0.5], deterministic, and (2,3) base radical-
//! inverses give the exact reference values.

use pharos_render::postprocess::taa::{halton23, halton_base, TaaConfig, TaaQuality};

#[test]
fn halton_base_known_values() {
    // Radical inverse in base 2:
    //   H(1) = 0b.1 = 0.5
    //   H(2) = 0b.01 = 0.25
    //   H(3) = 0b.11 = 0.75
    assert!((halton_base(1, 2) - 0.5).abs()  < 1e-6);
    assert!((halton_base(2, 2) - 0.25).abs() < 1e-6);
    assert!((halton_base(3, 2) - 0.75).abs() < 1e-6);

    // Radical inverse in base 3:
    //   H(1) = 0t.1 = 1/3
    //   H(2) = 0t.2 = 2/3
    //   H(3) = 0t.01 = 1/9
    assert!((halton_base(1, 3) - (1.0 / 3.0)).abs() < 1e-6);
    assert!((halton_base(2, 3) - (2.0 / 3.0)).abs() < 1e-6);
    assert!((halton_base(3, 3) - (1.0 / 9.0)).abs() < 1e-6);
}

#[test]
fn halton23_is_pixel_centred() {
    // Sub-pixel jitter must fit inside the pixel (Nova3D centres on
    // pixel centre by subtracting 0.5 from each raw radical-inverse).
    for &[x, y] in halton23(64).iter() {
        assert!(x >= -0.5 && x < 0.5, "x={} out of range", x);
        assert!(y >= -0.5 && y < 0.5, "y={} out of range", y);
    }
}

#[test]
fn halton23_avoids_origin() {
    // 1-based indexing means the first sample is (H(1,2), H(1,3)) - 0.5
    // = (0.5, 1/3) - 0.5 = (0.0, -1/6). Never exactly (0,0), which
    // would collapse to un-jittered rendering for that frame.
    let s = halton23(1);
    assert_eq!(s.len(), 1);
    let [x, y] = s[0];
    assert!((x - 0.0).abs() < 1e-6);
    assert!((y - (-1.0 / 6.0)).abs() < 1e-6);
}

#[test]
fn halton23_is_deterministic() {
    assert_eq!(halton23(16), halton23(16));
}

#[test]
fn quality_preset_sample_counts() {
    assert_eq!(TaaConfig { quality: TaaQuality::Low,    ..Default::default() }.sample_count(), 2);
    assert_eq!(TaaConfig { quality: TaaQuality::Medium, ..Default::default() }.sample_count(), 4);
    assert_eq!(TaaConfig { quality: TaaQuality::High,   ..Default::default() }.sample_count(), 8);
    assert_eq!(TaaConfig { quality: TaaQuality::Ultra,  ..Default::default() }.sample_count(), 16);
}
