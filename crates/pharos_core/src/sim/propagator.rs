//! The `Propagator` trait — a unified abstraction over every
//! physical-substrate solver in Pharos.
//!
//! Sprint 4 target. The two existing solvers (`pbf_solver`,
//! `softbody_solver`) get thin adapter structs that implement this
//! trait without disturbing their hot-path kernel bodies. Nova3D
//! lesson: dynamics kernels that share a shape (speed field, absorption
//! field, step, event drain) fragment into independent scheduling
//! code when each has its own bespoke advance() interface — pulling
//! them under a shared trait lets the render loop drive any solver
//! uniformly.

use std::collections::VecDeque;

/// A one-way event handed from external systems (input, network,
/// scripting) into a `Propagator::consume` call.
///
/// The concrete payload stays small enough to copy — heavier updates
/// go through the direct kernel API and skip the event bus.
#[derive(Debug, Clone, PartialEq)]
pub enum Event {
    /// External impulse applied at a world-space point.
    Impulse { pos: [f32; 3], dir: [f32; 3], magnitude: f32 },
    /// Set a scalar field (temperature, pressure) at a point.
    SetScalar { pos: [f32; 3], channel: u32, value: f32 },
    /// User-defined channel; solvers ignore unknown IDs.
    Custom { id: u32, payload_f: [f32; 4], payload_u: [u32; 4] },
}

/// A drainable queue of events, owned by the driver (typically the
/// render loop). Each frame the driver pushes events from input /
/// network / scripts, then calls `Propagator::consume(&mut bus)` on
/// every active solver in turn.
#[derive(Debug, Default)]
pub struct EventBus {
    queue: VecDeque<Event>,
}

impl EventBus {
    pub fn new() -> Self {
        EventBus { queue: VecDeque::new() }
    }
    pub fn push(&mut self, e: Event) {
        self.queue.push_back(e);
    }
    pub fn pop(&mut self) -> Option<Event> {
        self.queue.pop_front()
    }
    pub fn drain(&mut self) -> impl Iterator<Item = Event> + '_ {
        self.queue.drain(..)
    }
    pub fn len(&self) -> usize {
        self.queue.len()
    }
    pub fn is_empty(&self) -> bool {
        self.queue.is_empty()
    }
}

/// The core trait every physical-substrate solver implements.
///
/// The two field queries (`speed_at`, `absorption_at`) let downstream
/// systems (render, audio, gameplay) probe the medium at a world-space
/// point without needing to know which solver owns it. `step` advances
/// the simulation by `dt` seconds. `consume` drains queued events —
/// solvers ignore events they cannot handle.
pub trait Propagator {
    /// Local propagation speed (units/sec) at world-space `pos`.
    /// For fluid solvers this is the SPH particle speed; for softbody
    /// this is the median beam velocity; for thermal it is the
    /// diffusion coefficient.
    fn speed_at(&self, pos: [f32; 3]) -> f32;

    /// Local absorption coefficient at world-space `pos`. VCR queries
    /// this in Stage 4 (composite) to apply Beer-Lambert on refracted
    /// contributions. Range: 0.0 (perfectly transparent) - infinity.
    fn absorption_at(&self, pos: [f32; 3]) -> f32;

    /// Advance the solver by `dt` seconds. Called once per frame by
    /// the driver (or once per substep in the fixed-timestep case).
    fn step(&mut self, dt: f32);

    /// Drain any queued events the bus holds. Implementations pop
    /// events they can handle and leave the rest for downstream
    /// solvers.
    fn consume(&mut self, bus: &mut EventBus);
}

/// A no-op Propagator kept in the crate for tests and to document the
/// trait's expected shape. The `pbf_solver` and `softbody_solver`
/// modules ship their own adapter impls.
#[derive(Debug, Default, Clone)]
pub struct PropagatorStub {
    pub base_speed: f32,
    pub base_absorption: f32,
    pub events_consumed: u32,
    pub steps: u32,
    pub last_dt: f32,
}

impl Propagator for PropagatorStub {
    fn speed_at(&self, _pos: [f32; 3]) -> f32 {
        self.base_speed
    }
    fn absorption_at(&self, _pos: [f32; 3]) -> f32 {
        self.base_absorption
    }
    fn step(&mut self, dt: f32) {
        self.steps += 1;
        self.last_dt = dt;
    }
    fn consume(&mut self, bus: &mut EventBus) {
        // Stub soaks every event to prove the drain contract.
        for _ in bus.drain() {
            self.events_consumed += 1;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stub_step_advances_counters() {
        let mut s = PropagatorStub { base_speed: 1.5, base_absorption: 0.1, ..Default::default() };
        s.step(0.016);
        s.step(0.016);
        assert_eq!(s.steps, 2);
        assert!((s.last_dt - 0.016).abs() < 1e-6);
        assert!((s.speed_at([0.0; 3]) - 1.5).abs() < 1e-6);
        assert!((s.absorption_at([0.0; 3]) - 0.1).abs() < 1e-6);
    }

    #[test]
    fn stub_consumes_events() {
        let mut bus = EventBus::new();
        bus.push(Event::Impulse { pos: [0.0; 3], dir: [1.0, 0.0, 0.0], magnitude: 10.0 });
        bus.push(Event::SetScalar { pos: [0.0; 3], channel: 0, value: 300.0 });
        let mut s = PropagatorStub::default();
        s.consume(&mut bus);
        assert_eq!(s.events_consumed, 2);
        assert!(bus.is_empty());
    }
}
