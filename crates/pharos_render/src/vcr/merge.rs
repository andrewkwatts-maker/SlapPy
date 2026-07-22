//! VCR Stage 3 — Weighted Reservoir Sampling merge.
//!
//! When new contributions exceed K-slot budget, this stage merges the
//! least-important slot with the new one using WRS weights. Can run
//! inline per-write or per-tile.

pub struct MergePass;
