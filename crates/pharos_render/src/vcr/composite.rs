//! VCR Stage 4 — Composite.
//!
//! Reads all K slots per pixel, evaluates each sub-camera's cone
//! (mipped environment lookup or SSR fallback), sums with WRS weights,
//! applies Beer-Lambert absorption, blends over the primary G-buffer
//! shading result.

pub struct CompositePass;
