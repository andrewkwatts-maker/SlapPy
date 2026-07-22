//! VCR Stage 5 (optional) — Temporal reuse.
//!
//! Reprojects the previous frame's VCR buffer through motion vectors
//! with a bilateral depth-discontinuity filter. Slots marked
//! `Persistent` survive WRS merge for stable specular highlights.

pub struct TemporalPass;
