//! Sprint 1 Nova3D critical-bug intake regression tests.
//!
//! Seven fixes ported from Nova3D shipped-code intake. Each test below
//! asserts the guard is in place. Rust-side fixes get runtime checks;
//! shader-side fixes get compile-time source-content checks (WGSL
//! validation is exercised at pipeline-build time in the running
//! backend, but we verify the source strings carry the guard).

// -- Fix 1: MRT draw-buffer caching --

use std::panic::AssertUnwindSafe;

#[test]
fn fix1_mrt_assertion_helper_exists() {
    // The helper must panic when handed an empty attachment list.
    // Wrap in AssertUnwindSafe because RenderPassColorAttachment's
    // &TextureView is not UnwindSafe on its own.
    let empty: [Option<wgpu::RenderPassColorAttachment>; 0] = [];
    let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
        pharos_render::backend::wgpu_backend::assert_color_attachments_present(
            "sprint1.fix1.empty",
            &empty,
        );
    }));
    assert!(result.is_err(), "empty MRT list must panic");
}

#[test]
fn fix1_mrt_all_none_panics() {
    let all_none: [Option<wgpu::RenderPassColorAttachment>; 3] = [None, None, None];
    let result = std::panic::catch_unwind(AssertUnwindSafe(|| {
        pharos_render::backend::wgpu_backend::assert_color_attachments_present(
            "sprint1.fix1.all_none",
            &all_none,
        );
    }));
    assert!(result.is_err(), "all-None MRT list must panic");
}

// -- Fix 2: error-scope drain around shadow init --

#[test]
fn fix2_shadow_error_type_shape() {
    // The typed error must exist and Display cleanly.
    let e = pharos_render::shadow::csm::ShadowInitError::ValidationError(
        "sample".into(),
    );
    let msg = format!("{e}");
    assert!(msg.contains("shadow atlas"));
    assert!(msg.contains("sample"));
}

// -- Fix 3: degenerate TBN guard (gbuffer + forward) --

const GBUFFER_WGSL: &str = include_str!("../shaders/gbuffer.wgsl");
const FORWARD_WGSL: &str = include_str!("../shaders/forward.wgsl");

#[test]
fn fix3_gbuffer_has_guarded_tbn() {
    assert!(GBUFFER_WGSL.contains("fn guarded_tbn("));
    assert!(GBUFFER_WGSL.contains("PHAROS_TBN_EPS"));
    assert!(GBUFFER_WGSL.contains("length(t_in)"));
    assert!(GBUFFER_WGSL.contains("length(b_in)"));
}

#[test]
fn fix3_forward_has_guarded_tbn() {
    assert!(FORWARD_WGSL.contains("fn guarded_tbn("));
    assert!(FORWARD_WGSL.contains("PHAROS_TBN_EPS"));
}

// -- Fix 4: shadow bind protection --

#[test]
fn fix4_shadow_bind_group_index_pinned() {
    assert_eq!(pharos_render::pipeline::SHADOW_BIND_GROUP_INDEX, 2);
}

#[test]
fn fix4_rebind_helper_public() {
    // Compile-time proof: reference the helper as an item. If it were
    // removed or renamed the test file would fail to compile.
    let _f = pharos_render::pipeline::rebind_shadow_atlas;
}

// -- Fix 5: SSR fallback halo fix --

const VCR_COMPOSITE_WGSL: &str = include_str!("../shaders/vcr_composite.wgsl");

#[test]
fn fix5_composite_has_lit_colour_fallback() {
    assert!(
        VCR_COMPOSITE_WGSL.contains("lit_colour"),
        "vcr_composite.wgsl must sample lit_colour as SSR fallback"
    );
    assert!(
        VCR_COMPOSITE_WGSL.contains("ssr_fallback"),
        "vcr_composite.wgsl must bind an ssr_fallback variable"
    );
    assert!(
        VCR_COMPOSITE_WGSL.contains("reflected_sum = ssr_fallback"),
        "vcr_composite.wgsl must assign the fallback into reflected_sum \
         when total_weight is zero — else the Nova3D dark-halo bug returns"
    );
}

// -- Fix 6: VCR shader helper unification --

const VCR_COMMON_WGSL: &str = include_str!("../shaders/vcr_common.wgsl");
const VCR_SEED_WGSL: &str = include_str!("../shaders/vcr_seed.wgsl");

#[test]
fn fix6_pack_helpers_live_in_common() {
    assert!(VCR_COMMON_WGSL.contains("fn packOctU16("));
    assert!(VCR_COMMON_WGSL.contains("fn unpackOctU16("));
    assert!(VCR_COMMON_WGSL.contains("fn octEncode("));
    assert!(VCR_COMMON_WGSL.contains("fn octDecode("));
}

#[test]
fn fix6_seed_does_not_redefine_helpers() {
    // Prevent divergent duplicates in per-stage shaders. seed.wgsl must
    // not re-declare packOctU16 / unpackOctU16 — the SSoT is common.
    assert!(
        !VCR_SEED_WGSL.contains("fn packOctU16("),
        "vcr_seed.wgsl must not redefine packOctU16 — SSoT lives in vcr_common.wgsl"
    );
    assert!(
        !VCR_SEED_WGSL.contains("fn unpackOctU16("),
        "vcr_seed.wgsl must not redefine unpackOctU16 — SSoT lives in vcr_common.wgsl"
    );
}

// -- Fix 7: shadow polygon-offset bump --

#[test]
fn fix7_shadow_bias_bumped() {
    assert_eq!(
        pharos_render::shadow::csm::SHADOW_DEPTH_BIAS_FACTOR, 4.0,
        "Nova3D shipped 2.0; Pharos bumps to 4.0"
    );
    assert_eq!(
        pharos_render::shadow::csm::SHADOW_DEPTH_BIAS_UNITS, 8.0,
        "Nova3D shipped 4.0; Pharos bumps to 8.0"
    );
    let state = pharos_render::shadow::csm::shadow_depth_bias_state();
    assert_eq!(state.slope_scale, 4.0);
    assert_eq!(state.constant, 8);
}
