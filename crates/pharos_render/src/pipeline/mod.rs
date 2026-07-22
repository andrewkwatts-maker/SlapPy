//! Render pipeline modules: G-buffer, forward, and (Sprint 6) VCR.

pub mod gbuffer;
pub mod forward;

pub use gbuffer::GBufferPass;
pub use forward::ForwardPass;
