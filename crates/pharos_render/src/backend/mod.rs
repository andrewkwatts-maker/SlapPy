//! Backend abstraction: a Renderer picks one of these at construction.
//!
//! The default is Wgpu (cross-platform: Vulkan on Linux/Windows/Android,
//! Metal on macOS/iOS, D3D12 on Windows). The Vulkan variant is
//! opt-in for low-level compute paths that VCR uses. CpuFallback is
//! opt-in for headless CI runners with no GPU.

use crate::scene::RenderScene;
use crate::RenderError;

pub mod wgpu_backend;
pub use wgpu_backend::WgpuBackend;

#[cfg(feature = "vulkan")]
pub mod vulkan_backend;
#[cfg(feature = "vulkan")]
pub use vulkan_backend::VulkanBackend;

#[cfg(feature = "cpu-fallback")]
pub mod cpu_fallback;
#[cfg(feature = "cpu-fallback")]
pub use cpu_fallback::CpuFallback;

/// Which backend to construct.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BackendKind {
    Wgpu,
    #[cfg(feature = "vulkan")]
    Vulkan,
    CpuFallback,
}

/// Uniform interface every backend implements.
///
/// The trait is intentionally small: hand it a scene, get pixels back.
/// Each backend owns its own resource cache — the trait does not expose
/// GPU-specific handles.
pub trait Backend {
    /// Kind marker, primarily for logging + telemetry.
    fn kind(&self) -> BackendKind;

    /// Render one frame of `scene` at `width` x `height`. Returns an
    /// RGBA8 buffer of length `width * height * 4`, sRGB colour space.
    fn render_frame(
        &mut self,
        scene: &RenderScene,
        width: u32,
        height: u32,
    ) -> Result<Vec<u8>, RenderError>;
}
