//! Sprint 4 SOLID refactor: exercises the `sim::Propagator` trait
//! across the stub and the two real adapters (PBF, softbody). Proves
//! the trait contract without touching the numpy kernel bodies.

use pharos_core::pbf_solver::PbfPropagator;
use pharos_core::sim::{Event, EventBus, Propagator, PropagatorStub};
use pharos_core::softbody_solver::SoftbodyPropagator;

fn assert_is_propagator<P: Propagator>(_p: &P) {}

#[test]
fn stub_implements_propagator() {
    let s = PropagatorStub::default();
    assert_is_propagator(&s);
}

#[test]
fn pbf_adapter_implements_propagator() {
    let a = PbfPropagator::default();
    assert_is_propagator(&a);
}

#[test]
fn softbody_adapter_implements_propagator() {
    let a = SoftbodyPropagator::default();
    assert_is_propagator(&a);
}

#[test]
fn pbf_adapter_consumes_impulses_leaves_scalars() {
    let mut bus = EventBus::new();
    bus.push(Event::Impulse { pos: [0.0; 3], dir: [1.0, 0.0, 0.0], magnitude: 3.0 });
    bus.push(Event::SetScalar { pos: [0.0; 3], channel: 0, value: 1.0 });
    let mut p = PbfPropagator::default();
    p.consume(&mut bus);
    assert_eq!(p.queued_impulses.len(), 1);
    // Scalar left on the bus for downstream (thermal) solvers.
    assert_eq!(bus.len(), 1);
}

#[test]
fn softbody_adapter_consumes_impulses_leaves_scalars() {
    let mut bus = EventBus::new();
    bus.push(Event::Impulse { pos: [0.0; 3], dir: [1.0, 0.0, 0.0], magnitude: 3.0 });
    bus.push(Event::Custom { id: 0, payload_f: [0.0; 4], payload_u: [0; 4] });
    let mut p = SoftbodyPropagator::default();
    p.consume(&mut bus);
    assert_eq!(p.queued_impulses.len(), 1);
    // Custom events land back on the bus.
    assert_eq!(bus.len(), 1);
}

#[test]
fn stub_step_advances_last_dt() {
    let mut s = PropagatorStub::default();
    s.step(0.008);
    s.step(0.008);
    s.step(0.008);
    assert_eq!(s.steps, 3);
    assert!((s.last_dt - 0.008).abs() < 1e-6);
}

#[test]
fn drivers_can_run_multiple_propagators_in_sequence() {
    // Prove the "one bus, many solvers" driver pattern the plan calls
    // out — each solver drains the events it can handle and leaves the
    // rest for the next.
    let mut bus = EventBus::new();
    bus.push(Event::Impulse { pos: [0.0; 3], dir: [0.0, 1.0, 0.0], magnitude: 1.0 });
    bus.push(Event::SetScalar { pos: [0.0; 3], channel: 7, value: 42.0 });

    let mut pbf = PbfPropagator::default();
    let mut sb = SoftbodyPropagator::default();

    pbf.consume(&mut bus);
    sb.consume(&mut bus);

    // Both took at most one impulse; the scalar remains for a
    // hypothetical downstream thermal solver.
    assert_eq!(pbf.queued_impulses.len(), 1);
    assert_eq!(sb.queued_impulses.len(), 0);
    assert_eq!(bus.len(), 1);
}
