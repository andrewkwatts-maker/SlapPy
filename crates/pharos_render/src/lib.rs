//! Pharos render backend.
//!
//! Layered stack:
//!
//! ```text
//!     Application layer  (pharos_engine / pharos_bin)
//!             |
//!             v
//!     [Renderer]         (this crate's top-level facade)
//!             |
//!             v
//!     [Backend trait]    Wgpu impl (default)   or   Vulkan impl (ash, opt-in)
//!             |
//!             v
//!     [Pipelines]        gbuffer, forward, shadow::csm, skinning, vcr::*
//!             |
//!             v
//!     [Resources]        buffers, textures, bind groups
//! ```
//!
//! Sprint 4 lands the wgpu backend + G-buffer + basic forward pass.
//! Sprint 5 lands CSM shadows + skinning + scene walker + glTF import.
//! Sprint 6 lands VCR (Virtual Camera Reservoir) — see [`vcr`].
//! Sprint 7 wires PBF / softbody compute onto the GPU.

pub mod backend;
pub mod compute;
pub mod features;
pub mod pipeline;
pub mod resource;
pub mod scene;
pub mod shadow;
pub mod skinning;
pub mod vcr;

// Sprint 2: CPU-side render kernels moved out of pharos_py.
// Feature-gated so headless-only builds skip the pyo3 dep entirely.
#[cfg(feature = "legacy-cpu")]
pub mod legacy;

pub use backend::{Backend, BackendKind, WgpuBackend};
pub use features::RenderFeatures;
pub use pipeline::{ForwardPass, GBufferPass};
pub use scene::{Camera3D, DrawItem, Mesh, RenderScene, Vertex};

/// Facade: pick a backend, hand it a `RenderScene`, get pixels back.
///
/// ```no_run
/// use pharos_render::{Renderer, RenderScene, BackendKind};
/// let scene = RenderScene::default();
/// let mut r = Renderer::new(BackendKind::Wgpu, 1280, 720)?;
/// let pixels: Vec<u8> = r.render_to_rgba(&scene)?;
/// # Ok::<(), pharos_render::RenderError>(())
/// ```
pub struct Renderer {
    backend: Box<dyn Backend>,
    width: u32,
    height: u32,
    /// Cached feature probe. Populated at construction; every
    /// conditional path in the render backend reads from here rather
    /// than re-querying the adapter.
    features: RenderFeatures,
}

impl Renderer {
    /// Create a Renderer using the requested backend.
    pub fn new(kind: BackendKind, width: u32, height: u32) -> Result<Self, RenderError> {
        let backend: Box<dyn Backend> = match kind {
            BackendKind::Wgpu => Box::new(WgpuBackend::new(width, height)?),
            #[cfg(feature = "vulkan")]
            BackendKind::Vulkan => {
                return Err(RenderError::NotImplemented("raw vulkan backend"));
            }
            BackendKind::CpuFallback => {
                #[cfg(feature = "cpu-fallback")]
                {
                    Box::new(backend::CpuFallback::new(width, height))
                }
                #[cfg(not(feature = "cpu-fallback"))]
                {
                    return Err(RenderError::FeatureDisabled("cpu-fallback"));
                }
            }
        };
        Ok(Renderer { backend, width, height, features: RenderFeatures::baseline() })
    }

    /// Render one frame and return the composited RGBA framebuffer.
    pub fn render_to_rgba(&mut self, scene: &RenderScene) -> Result<Vec<u8>, RenderError> {
        self.backend.render_frame(scene, self.width, self.height)
    }

    pub fn size(&self) -> (u32, u32) {
        (self.width, self.height)
    }

    /// Access the cached feature probe. Conditional paths in downstream
    /// crates read from here rather than re-querying the adapter.
    pub fn features(&self) -> &RenderFeatures {
        &self.features
    }
}

/// Error type for render operations.
#[derive(Debug)]
pub enum RenderError {
    WgpuInit(String),
    WgpuSurface(String),
    FeatureDisabled(&'static str),
    NotImplemented(&'static str),
    Io(std::io::Error),
    Image(String),
}

impl std::fmt::Display for RenderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RenderError::WgpuInit(s) => write!(f, "wgpu init failed: {s}"),
            RenderError::WgpuSurface(s) => write!(f, "wgpu surface error: {s}"),
            RenderError::FeatureDisabled(s) => write!(f, "feature '{s}' is disabled at compile time"),
            RenderError::NotImplemented(s) => write!(f, "backend not implemented: {s}"),
            RenderError::Io(e) => write!(f, "IO error: {e}"),
            RenderError::Image(s) => write!(f, "image encoding error: {s}"),
        }
    }
}

impl std::error::Error for RenderError {}

impl From<std::io::Error> for RenderError {
    fn from(e: std::io::Error) -> Self { RenderError::Io(e) }
}
