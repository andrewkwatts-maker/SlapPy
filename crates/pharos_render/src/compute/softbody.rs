//! Softbody XPBD GPU compute pipeline — Sprint 7.
//!
//! Three entry points: cs_predict, cs_solve_beams, cs_integrate. The
//! solver scheduler runs solve_beams N_ITERATIONS times between
//! predict and integrate.

pub struct SoftbodyGpu {
    pub predict: wgpu::ComputePipeline,
    pub solve_beams: wgpu::ComputePipeline,
    pub integrate: wgpu::ComputePipeline,
}

impl SoftbodyGpu {
    pub fn new(device: &wgpu::Device) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("pharos_render.compute.softbody.shader"),
            source: wgpu::ShaderSource::Wgsl(std::borrow::Cow::Borrowed(include_str!(
                "../../shaders/softbody_step.wgsl"
            ))),
        });
        let make = |entry: &str, label: &str| {
            device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
                label: Some(label),
                layout: None,
                module: &shader,
                entry_point: entry,
                compilation_options: Default::default(),
            })
        };
        SoftbodyGpu {
            predict:     make("cs_predict",     "pharos_render.compute.softbody.predict"),
            solve_beams: make("cs_solve_beams", "pharos_render.compute.softbody.solve_beams"),
            integrate:   make("cs_integrate",   "pharos_render.compute.softbody.integrate"),
        }
    }
}
