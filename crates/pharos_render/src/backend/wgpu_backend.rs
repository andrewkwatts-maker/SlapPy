//! wgpu backend — the default cross-platform path.
//!
//! Sprint 4 lands: device + queue init, G-buffer offscreen target,
//! forward pass into that target, readback to CPU. No swapchain,
//! no window — headless offscreen only. Sprints 5-7 layer on CSM,
//! skinning, scene walker, VCR, GPU compute.

use crate::pipeline::{ForwardPass, GBufferPass};
use crate::scene::RenderScene;
use crate::{Backend, BackendKind, RenderError};

// -- Sprint 1 Nova3D bug intake: MRT draw-buffer caching --
//
// Nova3D bug: after the composite pass, subsequent frames silently
// dropped writes to unaffected render targets because a previous MRT
// state leaked. Every render pass must re-declare its color attachments
// and every begin_pass site must assert the attachment list is non-empty.
//
// `assert_color_attachments_present` is called at every `begin_render_pass`
// site in this crate. Panicking here catches "silent drop" bugs on the
// first frame instead of manifesting hours later as broken refraction.

/// Assert that the color attachment list passed to `begin_render_pass`
/// is not empty. Panics with a descriptive message otherwise.
pub fn assert_color_attachments_present(
    label: &'static str,
    attachments: &[Option<wgpu::RenderPassColorAttachment>],
) {
    let live = attachments.iter().filter(|a| a.is_some()).count();
    assert!(
        live > 0,
        "pharos_render: render pass '{label}' begun with no color attachments — Nova3D MRT-caching bug guard tripped"
    );
}

pub struct WgpuBackend {
    device: wgpu::Device,
    queue: wgpu::Queue,
    // Cached pipeline objects. Created lazily on first render_frame so
    // the ctor doesn't touch shader compilation cost until needed.
    gbuffer: Option<GBufferPass>,
    forward: Option<ForwardPass>,
    // Persistent readback staging buffer, resized on demand.
    readback_size: (u32, u32),
    readback: Option<wgpu::Buffer>,
}

impl WgpuBackend {
    pub fn new(_width: u32, _height: u32) -> Result<Self, RenderError> {
        let instance = wgpu::Instance::new(wgpu::InstanceDescriptor {
            backends: wgpu::Backends::PRIMARY,
            ..Default::default()
        });
        // Pick any high-performance adapter with no surface requirement.
        let adapter = pollster::block_on(instance.request_adapter(
            &wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: None,
                force_fallback_adapter: false,
            },
        ))
        .ok_or_else(|| RenderError::WgpuInit("no compatible adapter".into()))?;

        let (device, queue) = pollster::block_on(adapter.request_device(
            &wgpu::DeviceDescriptor {
                label: Some("pharos_render.device"),
                required_features: wgpu::Features::empty(),
                required_limits: wgpu::Limits::default(),
            },
            None,
        ))
        .map_err(|e| RenderError::WgpuInit(format!("request_device: {e}")))?;

        Ok(WgpuBackend {
            device,
            queue,
            gbuffer: None,
            forward: None,
            readback_size: (0, 0),
            readback: None,
        })
    }

    fn ensure_readback(&mut self, width: u32, height: u32) {
        if self.readback_size == (width, height) && self.readback.is_some() {
            return;
        }
        let bytes_per_row = round_up_align(width * 4, 256);
        let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("pharos_render.readback"),
            size: (bytes_per_row * height) as u64,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        self.readback = Some(buffer);
        self.readback_size = (width, height);
    }
}

impl Backend for WgpuBackend {
    fn kind(&self) -> BackendKind {
        BackendKind::Wgpu
    }

    fn render_frame(
        &mut self,
        scene: &RenderScene,
        width: u32,
        height: u32,
    ) -> Result<Vec<u8>, RenderError> {
        // Lazy-create pipelines.
        if self.gbuffer.is_none() {
            self.gbuffer = Some(GBufferPass::new(&self.device));
        }
        if self.forward.is_none() {
            self.forward = Some(ForwardPass::new(&self.device));
        }
        self.ensure_readback(width, height);

        // Colour target for the forward pass — RGBA8 sRGB.
        let colour = self.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("pharos_render.forward.colour"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Rgba8UnormSrgb,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
            view_formats: &[],
        });
        let colour_view = colour.create_view(&wgpu::TextureViewDescriptor::default());

        // Depth target — Depth32Float, no stencil for this pass.
        let depth = self.device.create_texture(&wgpu::TextureDescriptor {
            label: Some("pharos_render.forward.depth"),
            size: wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
            mip_level_count: 1,
            sample_count: 1,
            dimension: wgpu::TextureDimension::D2,
            format: wgpu::TextureFormat::Depth32Float,
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            view_formats: &[],
        });
        let depth_view = depth.create_view(&wgpu::TextureViewDescriptor::default());

        // Record + submit.
        let mut encoder = self
            .device
            .create_command_encoder(&wgpu::CommandEncoderDescriptor {
                label: Some("pharos_render.encoder"),
            });
        {
            let color_attachments = [Some(wgpu::RenderPassColorAttachment {
                view: &colour_view,
                resolve_target: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Clear(scene.clear_colour_wgpu()),
                    store: wgpu::StoreOp::Store,
                },
            })];
            assert_color_attachments_present("pharos_render.forward.pass", &color_attachments);
            let pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("pharos_render.forward.pass"),
                color_attachments: &color_attachments,
                depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                    view: &depth_view,
                    depth_ops: Some(wgpu::Operations {
                        load: wgpu::LoadOp::Clear(1.0),
                        store: wgpu::StoreOp::Discard,
                    }),
                    stencil_ops: None,
                }),
                timestamp_writes: None,
                occlusion_query_set: None,
            });
            // Draw items (Sprint 5 wires real vertex buffers; today we
            // just clear the scene).
            let _ = &scene.items; // silence unused-lint until Sprint 5
            drop(pass);
        }

        // Copy colour target -> readback.
        let bytes_per_row = round_up_align(width * 4, 256);
        encoder.copy_texture_to_buffer(
            wgpu::ImageCopyTexture {
                texture: &colour,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            wgpu::ImageCopyBuffer {
                buffer: self.readback.as_ref().unwrap(),
                layout: wgpu::ImageDataLayout {
                    offset: 0,
                    bytes_per_row: Some(bytes_per_row),
                    rows_per_image: Some(height),
                },
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
        self.queue.submit(std::iter::once(encoder.finish()));

        // Map + read back.
        let readback = self.readback.as_ref().unwrap();
        let slice = readback.slice(..);
        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |r| {
            let _ = tx.send(r);
        });
        self.device.poll(wgpu::Maintain::Wait);
        rx.recv()
            .map_err(|e| RenderError::WgpuSurface(format!("readback channel: {e}")))?
            .map_err(|e| RenderError::WgpuSurface(format!("map_async: {e}")))?;

        let raw = {
            let mapped = slice.get_mapped_range();
            let v = mapped.to_vec();
            // mapped goes out of scope here, releasing the map lock.
            v
        };
        readback.unmap();

        // Strip alignment padding: unpack rows of `bytes_per_row` bytes
        // into a contiguous width*4 stride.
        let stride = (width * 4) as usize;
        let padded = bytes_per_row as usize;
        let mut out = Vec::with_capacity(stride * height as usize);
        for row in 0..height as usize {
            out.extend_from_slice(&raw[row * padded..row * padded + stride]);
        }
        Ok(out)
    }
}

fn round_up_align(v: u32, align: u32) -> u32 {
    (v + align - 1) & !(align - 1)
}
