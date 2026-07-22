//! VCR Stage 4 — Composite.
//!
//! Fullscreen-triangle raster pass. See `shaders/vcr_composite.wgsl`.

pub struct CompositePass {
    pub pipeline: wgpu::RenderPipeline,
}

impl CompositePass {
    pub fn new(device: &wgpu::Device, wgsl_defines: &str) -> Self {
        let src = format!(
            "{defines}{body}",
            defines = wgsl_defines,
            body = include_str!("../../shaders/vcr_composite.wgsl"),
        );
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("pharos_render.vcr.composite.shader"),
            source: wgpu::ShaderSource::Wgsl(std::borrow::Cow::Owned(src)),
        });
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("pharos_render.vcr.composite.layout"),
            bind_group_layouts: &[],
            push_constant_ranges: &[],
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("pharos_render.vcr.composite.pipeline"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: "vs_fullscreen",
                buffers: &[],
                compilation_options: Default::default(),
            },
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                ..Default::default()
            },
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: "fs_main",
                targets: &[Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba16Float,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            multiview: None,
        });
        CompositePass { pipeline }
    }
}
