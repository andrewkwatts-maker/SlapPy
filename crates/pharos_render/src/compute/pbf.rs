//! PBF GPU compute pipeline — Sprint 7.
//!
//! Wraps `shaders/pbf_step.wgsl`. Four compute entry points:
//! cs_predict, cs_hash, cs_solve, cs_integrate. The scheduler runs
//! them in order N_ITERATIONS times per frame; ping-pong is handled
//! implicitly by the write-back-to-same-buffer pattern (safe because
//! each stage reads-then-writes non-overlapping fields).

pub struct PbfGpu {
    pub predict: wgpu::ComputePipeline,
    pub hash: wgpu::ComputePipeline,
    pub solve: wgpu::ComputePipeline,
    pub integrate: wgpu::ComputePipeline,
}

impl PbfGpu {
    pub fn new(device: &wgpu::Device) -> Self {
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("pharos_render.compute.pbf.shader"),
            source: wgpu::ShaderSource::Wgsl(std::borrow::Cow::Borrowed(include_str!(
                "../../shaders/pbf_step.wgsl"
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
        PbfGpu {
            predict:   make("cs_predict",   "pharos_render.compute.pbf.predict"),
            hash:      make("cs_hash",      "pharos_render.compute.pbf.hash"),
            solve:     make("cs_solve",     "pharos_render.compute.pbf.solve"),
            integrate: make("cs_integrate", "pharos_render.compute.pbf.integrate"),
        }
    }
}
