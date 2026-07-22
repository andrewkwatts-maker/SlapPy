//! VCR Stage 3 — Weighted Reservoir Sampling merge.
//!
//! Compute pass. See `shaders/vcr_merge.wgsl`.

pub struct MergePass {
    pub pipeline: wgpu::ComputePipeline,
}

impl MergePass {
    pub fn new(device: &wgpu::Device, wgsl_defines: &str) -> Self {
        let src = format!(
            "{defines}{body}",
            defines = wgsl_defines,
            body = include_str!("../../shaders/vcr_merge.wgsl"),
        );
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("pharos_render.vcr.merge.shader"),
            source: wgpu::ShaderSource::Wgsl(std::borrow::Cow::Owned(src)),
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("pharos_render.vcr.merge.pipeline"),
            layout: None,
            module: &shader,
            entry_point: "cs_main",
            compilation_options: Default::default(),
        });
        MergePass { pipeline }
    }
}
