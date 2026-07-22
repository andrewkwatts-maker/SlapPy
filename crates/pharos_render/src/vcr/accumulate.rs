//! VCR Stage 2 — Raster + accumulate.
//!
//! Extended-frustum raster pass. See `shaders/vcr_accumulate.wgsl`.

use crate::scene::Vertex;

pub struct AccumulatePass {
    pub pipeline: wgpu::RenderPipeline,
}

impl AccumulatePass {
    pub fn new(device: &wgpu::Device, wgsl_defines: &str) -> Self {
        let src = format!(
            "{defines}{body}",
            defines = wgsl_defines,
            body = include_str!("../../shaders/vcr_accumulate.wgsl"),
        );
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("pharos_render.vcr.accumulate.shader"),
            source: wgpu::ShaderSource::Wgsl(std::borrow::Cow::Owned(src)),
        });
        let layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("pharos_render.vcr.accumulate.layout"),
            bind_group_layouts: &[],  // Sprint 7 pins explicit BGLs
            push_constant_ranges: &[],
        });
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("pharos_render.vcr.accumulate.pipeline"),
            layout: Some(&layout),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: "vs_main",
                buffers: &[Vertex::BUFFER_LAYOUT],
                compilation_options: Default::default(),
            },
            primitive: wgpu::PrimitiveState {
                topology: wgpu::PrimitiveTopology::TriangleList,
                cull_mode: None,   // extended frustum can see back faces
                ..Default::default()
            },
            depth_stencil: None,
            multisample: wgpu::MultisampleState::default(),
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: "fs_main",
                targets: &[Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba16Float,
                    blend: Some(wgpu::BlendState {
                        color: wgpu::BlendComponent {
                            src_factor: wgpu::BlendFactor::One,
                            dst_factor: wgpu::BlendFactor::One,
                            operation: wgpu::BlendOperation::Add,
                        },
                        alpha: wgpu::BlendComponent::OVER,
                    }),
                    write_mask: wgpu::ColorWrites::ALL,
                })],
                compilation_options: Default::default(),
            }),
            multiview: None,
        });
        AccumulatePass { pipeline }
    }
}
