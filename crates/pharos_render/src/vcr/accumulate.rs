//! VCR Stage 2 — Raster + accumulate.
//!
//! Extended-frustum rasterization pass. Every fragment consults the
//! reservoir and adds colour + throughput contributions when a virtual
//! sub-camera ray hits that triangle. Sprint 6 landing.

pub struct AccumulatePass;
