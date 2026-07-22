//! VCR Stage 5 (optional) — Temporal reuse.
//!
//! Compute pass. See `shaders/vcr_temporal.wgsl`.

pub struct TemporalPass {
    pub pipeline: wgpu::ComputePipeline,
}

impl TemporalPass {
    pub fn new(device: &wgpu::Device, wgsl_defines: &str) -> Self {
        let src = format!(
            "{defines}{body}",
            defines = wgsl_defines,
            body = include_str!("../../shaders/vcr_temporal.wgsl"),
        );
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("pharos_render.vcr.temporal.shader"),
            source: wgpu::ShaderSource::Wgsl(std::borrow::Cow::Owned(src)),
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("pharos_render.vcr.temporal.pipeline"),
            layout: None,
            module: &shader,
            entry_point: "cs_main",
            compilation_options: Default::default(),
        });
        TemporalPass { pipeline }
    }
}
