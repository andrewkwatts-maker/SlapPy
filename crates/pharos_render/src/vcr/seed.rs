//! VCR Stage 1 — Seed reservoirs.
//!
//! Fullscreen pass. Initialises the K-slot per-texel reservoir with
//! ray directions derived from the G-buffer's roughness + IoR + normal.
//! Sprint 6 wires the compute shader (`shaders/vcr_seed.wgsl`).

pub struct SeedPass;
