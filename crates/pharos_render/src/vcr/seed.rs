//! VCR Stage 1 — Seed reservoirs.
//!
//! Compute pass: for each screen pixel, read the G-buffer and initialise
//! reservoir slots with specular + refractive ray directions derived
//! from normal + roughness + IoR. See `shaders/vcr_seed.wgsl`.

pub struct SeedPass {
    pub pipeline: wgpu::ComputePipeline,
}

impl SeedPass {
    pub fn new(device: &wgpu::Device, wgsl_defines: &str) -> Self {
        let src = format!(
            "{defines}{body}",
            defines = wgsl_defines,
            body = include_str!("../../shaders/vcr_seed.wgsl"),
        );
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("pharos_render.vcr.seed.shader"),
            source: wgpu::ShaderSource::Wgsl(std::borrow::Cow::Owned(src)),
        });
        let pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("pharos_render.vcr.seed.pipeline"),
            layout: None,   // auto-derive from shader (Sprint 7 pins explicit layout)
            module: &shader,
            entry_point: "cs_main",
            compilation_options: Default::default(),
        });
        SeedPass { pipeline }
    }
}
