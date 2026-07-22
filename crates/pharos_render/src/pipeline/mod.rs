//! Render pipeline modules: G-buffer, forward, and (Sprint 6) VCR.

pub mod gbuffer;
pub mod forward;

pub use gbuffer::GBufferPass;
pub use forward::ForwardPass;

// -- Sprint 1 Nova3D bug intake: shadow bind protection --
//
// Nova3D bug: SSR + VCR composite passes clobbered texture units 4/5/6.
// Every pass in this crate that samples the shadow atlas must re-bind
// the shadow bind group before drawing — the previous pass may have
// left another bind group at this index. The wgpu equivalent of the
// GL "explicit set_bind_group" is:
//
//     pass.set_bind_group(SHADOW_BIND_GROUP_INDEX, shadow_bg, &[]);
//
// Use `rebind_shadow_atlas` at every draw-time site that samples shadows.

/// Bind-group index reserved for the shadow atlas across every pass in
/// this crate. Kept as a single SSoT so the constant cannot drift
/// between pipelines.
pub const SHADOW_BIND_GROUP_INDEX: u32 = 2;

/// Explicitly re-bind the shadow atlas bind group before any draw call
/// that samples shadows. Guards against a previous pass leaving another
/// bind group at [`SHADOW_BIND_GROUP_INDEX`].
///
/// This helper does not check whether the group was previously bound —
/// the whole point is to unconditionally re-bind so cross-pass clobbers
/// cannot cause silent shadow drops.
pub fn rebind_shadow_atlas<'a>(
    pass: &mut wgpu::RenderPass<'a>,
    shadow_bg: &'a wgpu::BindGroup,
) {
    pass.set_bind_group(SHADOW_BIND_GROUP_INDEX, shadow_bg, &[]);
}
