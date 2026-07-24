//! PyO3 wrappers for the pharos_render GPU surface.
//!
//! Sprint 2 exposes the four types the plan calls out: `Renderer`,
//! `RenderScene`, `Camera3D`, `VcrPipeline`. Wrappers are intentionally
//! thin — they own instances of the pharos_render types and forward
//! methods. Python-side ergonomics (repr, typed fields) come from the
//! Rust-side `#[pymethods]` block below.
//!
//! Everything registers under a `render` submodule of the top-level
//! `_core`: Python imports as `pharos_engine._core.render.Renderer`.

use pyo3::prelude::*;
use pyo3::types::PyModule;

use pharos_render::vcr::Preset;
use pharos_render::{BackendKind, Camera3D as RCamera3D, DrawItem as RDrawItem, RenderScene as RRenderScene, Renderer as RRenderer};

/// Perspective camera. Mirrors `pharos_render::Camera3D` with a Python
/// constructor and repr.
#[pyclass(name = "Camera3D", module = "pharos_engine._core.render")]
#[derive(Clone)]
pub struct PyCamera3D {
    inner: RCamera3D,
}

#[pymethods]
impl PyCamera3D {
    #[new]
    #[pyo3(signature = (
        position=(0.0, 1.5, 3.0),
        target=(0.0, 0.0, 0.0),
        up=(0.0, 1.0, 0.0),
        fov_y_deg=60.0,
        aspect=16.0 / 9.0,
        near=0.1,
        far=100.0,
    ))]
    fn new(
        position: (f32, f32, f32),
        target: (f32, f32, f32),
        up: (f32, f32, f32),
        fov_y_deg: f32,
        aspect: f32,
        near: f32,
        far: f32,
    ) -> Self {
        PyCamera3D {
            inner: RCamera3D {
                position: [position.0, position.1, position.2].into(),
                target: [target.0, target.1, target.2].into(),
                up: [up.0, up.1, up.2].into(),
                fov_y_radians: fov_y_deg.to_radians(),
                aspect,
                near,
                far,
            },
        }
    }

    #[getter]
    fn position(&self) -> (f32, f32, f32) {
        (self.inner.position.x, self.inner.position.y, self.inner.position.z)
    }
    #[getter]
    fn target(&self) -> (f32, f32, f32) {
        (self.inner.target.x, self.inner.target.y, self.inner.target.z)
    }
    #[getter]
    fn fov_y_deg(&self) -> f32 {
        self.inner.fov_y_radians.to_degrees()
    }
    #[getter]
    fn aspect(&self) -> f32 {
        self.inner.aspect
    }

    fn __repr__(&self) -> String {
        format!(
            "Camera3D(position={:?}, target={:?}, fov_y_deg={:.2}, aspect={:.4})",
            self.position(),
            self.target(),
            self.fov_y_deg(),
            self.aspect(),
        )
    }
}

/// Render scene container. Wraps `pharos_render::RenderScene`.
#[pyclass(name = "RenderScene", module = "pharos_engine._core.render")]
#[derive(Clone)]
pub struct PyRenderScene {
    inner: RRenderScene,
}

#[pymethods]
impl PyRenderScene {
    #[new]
    fn new() -> Self {
        PyRenderScene { inner: RRenderScene::default() }
    }

    #[getter]
    fn camera(&self) -> PyCamera3D {
        PyCamera3D { inner: self.inner.camera.clone() }
    }

    #[setter]
    fn set_camera(&mut self, camera: PyCamera3D) {
        self.inner.camera = camera.inner;
    }

    #[getter]
    fn item_count(&self) -> usize {
        self.inner.items.len()
    }

    /// Set the linear-space clear colour (RGBA). Rendered through the
    /// sRGB swap chain on wgpu backends.
    fn set_clear_colour(&mut self, rgba: (f32, f32, f32, f32)) {
        self.inner.clear_colour = [rgba.0, rgba.1, rgba.2, rgba.3];
    }

    /// Append one draw item to the scene.
    ///
    /// The tuple `translation = (x, y, z)` builds a translation-only
    /// model matrix (glam::Mat4::from_translation). Callers that need
    /// full rotation + scale should upload a Mat4 directly via
    /// `add_draw_item_mat4`.
    fn add_cube_at(&mut self, translation: (f32, f32, f32), scale: f32, mesh: u32, material: u32) {
        let m = glam::Mat4::from_scale_rotation_translation(
            glam::Vec3::splat(scale.max(0.001)),
            glam::Quat::IDENTITY,
            glam::Vec3::new(translation.0, translation.1, translation.2),
        );
        self.inner.items.push(RDrawItem {
            model: m,
            mesh,
            material,
        });
    }

    /// Clear the draw-item vec so the next frame starts empty.
    fn clear_items(&mut self) {
        self.inner.items.clear();
    }

    fn __repr__(&self) -> String {
        format!("RenderScene(items={}, clear={:?})", self.inner.items.len(), self.inner.clear_colour)
    }
}

/// GPU renderer facade. Wraps `pharos_render::Renderer`.
///
/// The wgpu backend requires a live GPU / device — in headless CI
/// environments without a compatible adapter, construction returns an
/// exception with the backend init error. Callers falling back to
/// software raster should use the legacy `pharos_engine._core.raster`
/// entry points.
#[pyclass(name = "Renderer", module = "pharos_engine._core.render", unsendable)]
pub struct PyRenderer {
    inner: RRenderer,
}

#[pymethods]
impl PyRenderer {
    #[new]
    #[pyo3(signature = (width, height, backend="wgpu"))]
    fn new(width: u32, height: u32, backend: &str) -> PyResult<Self> {
        let kind = match backend.to_ascii_lowercase().as_str() {
            "wgpu" => BackendKind::Wgpu,
            "cpu-fallback" | "cpu" => BackendKind::CpuFallback,
            other => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "unknown backend {other:?}; expected one of wgpu / cpu-fallback"
                )))
            }
        };
        let r = RRenderer::new(kind, width, height)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("Renderer::new: {e}")))?;
        Ok(PyRenderer { inner: r })
    }

    #[getter]
    fn size(&self) -> (u32, u32) {
        self.inner.size()
    }

    /// Render one frame and return the composited RGBA framebuffer as
    /// `bytes` (length = `width * height * 4`).
    fn render_to_rgba(&mut self, scene: &PyRenderScene) -> PyResult<Vec<u8>> {
        self.inner
            .render_to_rgba(&scene.inner)
            .map_err(|e| pyo3::exceptions::PyRuntimeError::new_err(format!("render_to_rgba: {e}")))
    }

    fn __repr__(&self) -> String {
        let (w, h) = self.inner.size();
        format!("Renderer(size=({w}x{h}))")
    }
}

/// Handle to a Virtual Camera Reservoir pipeline preset.
///
/// The real dispatch objects need a live `wgpu::Device`; the Python
/// binding exposes the preset selection + parameter introspection so
/// downstream code can construct a `Renderer` and hand it a preset.
#[pyclass(name = "VcrPipeline", module = "pharos_engine._core.render")]
#[derive(Clone, Copy)]
pub struct PyVcrPipeline {
    preset: Preset,
}

#[pymethods]
impl PyVcrPipeline {
    #[new]
    #[pyo3(signature = (preset="standard"))]
    fn new(preset: &str) -> PyResult<Self> {
        let preset = match preset.to_ascii_lowercase().as_str() {
            "off" => Preset::Off,
            "compat" => Preset::Compat,
            "standard" => Preset::Standard,
            "cinematic" => Preset::Cinematic,
            other => {
                return Err(pyo3::exceptions::PyValueError::new_err(format!(
                    "unknown VCR preset {other:?}; expected off / compat / standard / cinematic"
                )))
            }
        };
        Ok(PyVcrPipeline { preset })
    }

    #[getter]
    fn preset(&self) -> &'static str {
        match self.preset {
            Preset::Off => "off",
            Preset::Compat => "compat",
            Preset::Standard => "standard",
            Preset::Cinematic => "cinematic",
        }
    }

    #[getter]
    fn k_slots(&self) -> u32 {
        self.preset.params().k_slots
    }

    #[getter]
    fn res_scale(&self) -> f32 {
        self.preset.params().res_scale
    }

    #[getter]
    fn temporal_reuse(&self) -> bool {
        self.preset.params().temporal_reuse
    }

    fn __repr__(&self) -> String {
        format!(
            "VcrPipeline(preset={:?}, k_slots={}, res_scale={:.3}, temporal={})",
            self.preset(),
            self.k_slots(),
            self.res_scale(),
            self.temporal_reuse(),
        )
    }
}

/// Register the `render` submodule on the parent `_core` module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    let child = PyModule::new_bound(parent.py(), "render")?;
    child.add_class::<PyCamera3D>()?;
    child.add_class::<PyRenderScene>()?;
    child.add_class::<PyRenderer>()?;
    child.add_class::<PyVcrPipeline>()?;
    parent.add_submodule(&child)?;
    Ok(())
}
