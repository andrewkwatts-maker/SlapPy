# slappyengine.dynamics — Design Reference

`slappyengine.dynamics` is the unified primitive set that sits on top of the
engine's XPBD substrate. It generalises the older softbody-specific
`BodyMeta` / `VehicleSpec` / `WheelSpec` triumvirate into a small composable
type system — a single `JointSpec` with seven *kinds*, plus authoring helpers
(`RopeSpec`, `RagdollSpec`, `IKChainSpec`) that resolve down to the same two
constraint primitives the solver already knows how to project.

This document is the canonical "what do I reach for, and why does it work?"
reference. It does not duplicate per-field API docs (those live next to the
dataclasses in `python/slappyengine/dynamics/`); it explains the *shape* of the
abstraction, the underlying solver, the choices between primitives, and the
failure modes you should plan for.

## Foundation: XPBD

The substrate is Extended Position-Based Dynamics — Macklin et al. 2016,
*"XPBD: Position-Based Simulation of Compliant Constrained Dynamics"*. XPBD
replaces classical stiffness/damping forces with a Lagrange-multiplier
position projection that converges to an exact constraint at the end of each
substep. Practically every `JointSpec.kind` in this package is a thin
wrapper around the canonical XPBD distance projection used by `_project_distance`
in `python/slappyengine/dynamics/joint.py`:

```text
C       = |x_a - x_b| - L
∇C_a    =  n
∇C_b    = -n
α̂       = 1 / (k · dt²)
Δλ      = -(C + α̂ λ) / (w_a + w_b + α̂)
Δx_a    =  w_a · Δλ · n
Δx_b    = -w_b · Δλ · n
```

The compliance term `α̂ = 1 / (k · dt²)` is what makes XPBD attractive as a
game-engine substrate. Unlike force-based springs the projection is stable at
arbitrarily high stiffness — there is no explicit timestep limit imposed by the
constraint, because as `k → ∞` the compliance collapses to zero and the
projection reduces to the classic *hard* PBD constraint. The 2016 paper's
contribution is the multiplier-based reformulation that decouples the
effective stiffness from the iteration count, so 8 inner iterations
(`World.solver_iterations = 8`, see `world.py:37`) behave consistently across
a wide range of constraint stiffnesses.

What the solver gives you: stable convergence at high stiffness, decoupled
behaviour vs timestep, no per-frame energy explosion. What it does *not* give
you: exact energy conservation (a damping coefficient of 0 still leaks
amplitude — see `test_spring_oscillates_and_damps` for the round-off
attenuation note), no incompressibility (that lives in the PBF fluid code, not
here), and no explicit angular state. The angular hinge limit
(`_project_angle`) is a numpy extension built atop the same node array, not a
real rigid-body angular variable — it works by computing the signed angle
between two anchor-relative vectors and nudging the free endpoints
tangentially when the angle leaves the declared `[min_angle, max_angle]` band.

## The seven JointSpec kinds

All seven kinds share the `JointSpec` dataclass (`joint.py:50`); the only
difference between them is which `params` keys they read and which subset of
projections they invoke. The schema is enumerated machine-readably in
`KIND_PARAM_KEYS`:

| Kind        | Use for                          | Constraint type                                   | Cost | Stable at high stiffness? |
|-------------|----------------------------------|---------------------------------------------------|------|---------------------------|
| `distance`  | Rigid rods, lattice bonds         | Distance                                          | O(1) | Yes                       |
| `spring`    | Suspension, soft tethers          | Distance (with author-tuned softer defaults)      | O(1) | Yes                       |
| `weld`      | Glued joints, fixed rest offset   | Distance, defaults to very stiff                  | O(1) | Yes                       |
| `ball`      | Free-rotation pivot               | Distance @ 0 rest length                          | O(1) | Yes                       |
| `hinge`     | Door, knee, elbow                 | Distance + angular limit                          | O(1) | Yes — see notes           |
| `motor`     | Wheel hub, rotating turret        | Two distances (hub→rim) + tangential impulse      | O(1) | Mostly                    |
| `prismatic` | Piston, slider                    | Distance along axis + perpendicular cancel        | O(1) | Yes                       |

Default stiffness on the `JointSpec` dataclass is `1.0e9` and default damping
is `0.02` (see `joint.py:77-78`). Author-facing builders override these:
`make_spring` writes `stiffness=1.0e6, damping=0.05`; `make_motor` writes
`stiffness=1.0e8, damping=0.02`. `RopeSpec` and `RagdollSpec` default to
`1.0e6` and `5.0e6` respectively. None of the differences are kernel-level —
they are parameter choices captured in the builder.

Notes on the trickier kinds:

- **`hinge` stability** is bounded by the `_project_angle` step size. The
  routine multiplies the angular error by `0.5 * stiffness` (clamped to
  `[0, 1]`) per iteration, so a tight rotation limit combined with a high
  stiffness coefficient can over-shoot on the first iteration. In practice
  the ragdoll builder writes `stiffness=spec.stiffness * 0.2` for hinge
  joints (`ragdoll.py:132`) precisely to avoid this — pass through the same
  multiplier in custom hinges if you see jitter at the limit boundary.
- **`motor` torque clamping** uses `max_torque` as a velocity-delta cap, not
  a true torque. The solver clamps `|Δv|` per substep to `max_torque * dt`
  (see `joint.py:285`). That means a motor with `max_torque=0` is a *free*
  hub — no spin authority at all — and a motor with very large
  `target_omega` plus small `max_torque` ramps up over many substeps rather
  than snapping to speed. The motor also bails to a pure distance projection
  if its `params['hub']` was mis-keyed (`joint.py:244`) — typos silently
  disable the spin, never NaN.
- **`prismatic` axis normalisation** is mandatory. The resolver calls
  `axis_v / np.linalg.norm(axis_v)` and bails out on near-zero axes
  (`joint.py:301`). The `[min, max]` slot is interpreted relative to the
  *signed* projection of `(b - a)` onto the axis; the perpendicular drift is
  cancelled stiffly every iteration.

## Composite primitives

The three composite primitives below are pure authoring layers: they build
`JointSpec` instances and node clusters, then register a single `Body` record
covering the new nodes. They contain *no* new solver code.

### RopeSpec

`RopeSpec` (`rope.py:20`) lays `node_count` nodes linearly between two
anchors, joined by `n - 1` distance joints of length
`total_length / (node_count - 1)`. When `bend_stiffness > 0` it also
adds `n - 2` *bend* joints spanning every (i, i+2) triple with a rest length
of `2 * segment_len`. Folding the rope compresses that diagonal, so the bend
joint resists the fold while still living inside the distance kernel — no new
constraint type required.

Tradeoffs:

- **`node_count` vs `total_length`.** Density (nodes per metre) is what sets
  rendering smoothness and collision resolution; the test harness uses 20
  nodes / 4 m (`test_rope_builds_expected_node_count`) for a visibly
  smooth catenary, 8 nodes / 2 m (`_build_toy_rope`) for cheap demo work.
- **`bend_stiffness`.** Zero gives an ideal *cable*. Non-zero biases toward
  rod-like behaviour — useful for pendulum chains or stiff hoses. The bend
  joint shares the rope's `damping` coefficient.
- **Catenary as a sanity check.** A symmetric pinned-both-ends rope under
  gravity should produce a `y_mid < y_anchor` droop with mirror symmetry
  along the long axis. `test_rope_droops_into_catenary` codifies this
  (5 m rope spanning 4 m at 240 Hz for 10 simulated seconds, MSE between
  left and right halves under 0.05). If your rope deviates from that
  shape there is almost certainly a damping or stiffness mis-config.

### RagdollSpec

`RagdollSpec` (`ragdoll.py:44`) decodes a tree of `BoneSpec` records into
node clusters joined by distance constraints. Each bone is a single
parent→child segment whose endpoints are added to the world as numbered
nodes; sibling bones share the parent endpoint, so the tree topology emerges
automatically from `parent_idx` references.

For every non-root bone, the builder also emits a `hinge` joint that pins the
child relative to the *grand*parent endpoint with the bone's declared
`angle_limit`. The hinge stiffness is scaled to `spec.stiffness * 0.2`
(`ragdoll.py:132`) — soft enough to avoid jitter at the limit, stiff enough
to resemble a real ball-and-socket constraint.

The common humanoid topology in the test suite (`test_dynamics_ragdoll.py`)
is 6 bones: torso (root) plus head, left leg, right leg, left arm, right arm,
giving 7 total nodes (root anchor + 6 child endpoints). The angle limits used
there — `(-0.6, 0.6)` for the head, `(-0.5, 0.5)` for legs, `(-0.8, 0.8)` for
arms — give roughly humanoid mobility while keeping the solver well inside
the `_project_angle` step's stable band.

### IKChainSpec

`solve_ik` (`ik.py:32`) is a Cyclic Coordinate Descent solver. CCD walks the
chain from the second-to-last joint back toward the root, rotating each
joint to align the tip with the target. It is the simplest IK algorithm that
"just works" in 2D, and it converges much faster than FABRIK or Jacobian-
based methods for short chains. The tradeoff: CCD is greedy, so it has no
notion of natural pose preservation — chains that need to honour a rest
configuration should run CCD *and* a set of pose-preserving distance
constraints in the same `World.step`.

Convergence properties:

- **Default iterations.** `solve_ik(..., iterations=10, tolerance=0.01)`
  hits convergence on a 4-node chain with reach 3.0 to a target at radius
  ~2.12 (`test_ik_converges_for_reachable_target`) within tolerance.
- **Failure modes.** Unreachable targets cause the chain to straighten
  toward the target axis; `solve_ik` returns `False` without raising
  (`test_ik_returns_false_for_unreachable_target`). Degenerate
  configurations — pivot vectors of zero length — are silently skipped
  (`ik.py:64`).
- **`fixed_root=True`** (the default) protects `node_indices[0]` from
  rotation. Verified by `test_ik_root_pin_preserved`.
- **Return value.** `True` when the tip ends within `tolerance` of the
  target, `False` otherwise. No exception path. Callers must check the
  return value if "did it actually reach?" is gameplay-significant.

## Choosing between primitives

| Goal                              | Use                                                                |
|-----------------------------------|--------------------------------------------------------------------|
| Static rigid object               | `Body` with no joints, `mass=0` nodes (pinned)                     |
| Bouncing solid body               | Lattice of nodes with `JointSpec(kind="distance")` per edge        |
| Hanging cable                     | `RopeSpec` with `bend_stiffness=0`                                 |
| Pendulum chain                    | `RopeSpec` with high `bend_stiffness`                              |
| Articulated character             | `RagdollSpec`                                                      |
| Inverse kinematic arm             | `IKChainSpec` + distance joints for rest pose                      |
| Vehicle suspension                | `SpringSpec` between chassis node and wheel hub node               |
| Rotating wheel                    | `MotorSpec` between hub and rim nodes                              |
| Door / single-axis hinge          | `JointSpec(kind="hinge")` with `params={"anchor": ..., ...}`       |
| Piston / slider                   | `JointSpec(kind="prismatic")` with `params={"axis": ..., ...}`     |
| Two glued bodies                  | `JointSpec(kind="weld")` with `stiffness=1e9`                      |
| Free 2-body pivot                 | `JointSpec(kind="ball")`                                           |

When in doubt, pick the simpler primitive: a vehicle suspension *can* be
expressed as a hinge with a soft angular spring, but a `SpringSpec` between
chassis and wheel is one line shorter and has half as many failure modes.

## Solver internals

Every `JointSpec.kind` resolves to one of two XPBD primitives the existing
solver handles — both are implemented in `joint.py`:

1. **`_project_distance(world, a, b, rest_length, stiffness, damping, dt)`**
   (`joint.py:88`). The canonical XPBD distance projection. Computes
   `C = |x_a - x_b| - L`, derives the compliance term `α̂ = 1 / (k * dt²)`,
   and applies the multiplier-weighted position correction along the unit
   separation vector. The damping coefficient (in `[0, 1]`, clamped) is
   applied as a scalar multiplier on the correction magnitude — strictly
   *position-level* damping, not a true viscous force, but cheap and stable.

2. **`_project_angle(world, anchor, a, b, min_angle, max_angle, stiffness)`**
   (`joint.py:133`). An iterative hinge primitive added in pure numpy when
   the upstream solver lacked it. Computes the signed angle between
   `anchor→a` and `anchor→b`; when it leaves the declared band, it rotates
   each free endpoint half the violation in opposite directions so the
   angle returns to range. Pinned nodes (`inv_mass == 0`) are skipped.

The per-kind dispatchers compose these:

| Kind        | What `resolve()` does                                                                       |
|-------------|---------------------------------------------------------------------------------------------|
| `distance`  | One `_project_distance` call between `node_a` and `node_b`.                                 |
| `spring`    | Identical to `distance` — the *behaviour* difference is the builder's softer defaults.      |
| `weld`      | Identical to `distance`; convention is to set `stiffness=1.0e9` (the dataclass default).    |
| `ball`      | `_project_distance` with `rest_length=0` regardless of the field value.                     |
| `hinge`     | `_project_distance` (holds rest length) **plus** `_project_angle` (clamps to band).         |
| `motor`     | Two `_project_distance` calls (`hub→rim_a`, `hub→rim_b`) **plus** a tangential velocity push capped by `max_torque * dt`. |
| `prismatic` | Stiff perpendicular-component cancel **plus** an axis-projection clamp into `[min, max]`.   |

Dispatch is a single dict lookup (`_DISPATCH` in `joint.py:334`); unknown
kinds raise `ValueError` (`joint.py:349`). The dispatch function returns the
correction magnitude, and the wrapper `resolve()` disables the joint when
that magnitude exceeds `break_force` — that is the breakable-bond hook the
ragdoll and rope builders inherit for free.

The composite primitives (`RopeSpec`, `RagdollSpec`) never write to the
solver kernels directly. They write `JointSpec` records into
`world.joints`, and the unified `World.step` (`world.py:86`) iterates the
joint list `solver_iterations` times (default 8) calling `resolve()` on each
enabled joint. The IK solver is the only primitive that mutates positions
*outside* the step loop — it is a kinematic positioning tool, not a
dynamics constraint.

## Compatibility notes

The plan at `C:/Users/Andrew/.claude/plans/ok-we-were-working-reactive-valley.md`
calls for the legacy softbody types to become thin re-exports of the new
unified types. The intended bridge:

| Legacy type / call                                          | New equivalent                                                                |
|-------------------------------------------------------------|-------------------------------------------------------------------------------|
| `softbody.world.BodyMeta`                                   | `dynamics.Body` (with `kind="lattice"`).                                      |
| `softbody.vehicle.VehicleSpec`, `WheelSpec`, `build_vehicle`| Kept as authoring wrappers; internals resolve wheels to `make_motor` + `make_spring`. The public signatures of `build_vehicle` and `apply_drivetrain_torque` are stable. |
| `softbody.body_builders.make_layered_creature`              | Continues to work; the cross-layer beams it emits become `JointSpec(kind="distance")` records with finite `break_force`. |
| `softbody.world.SoftBodyWorld`                              | Alias of `dynamics.World` (`world.py:123`). Both names refer to the same class so legacy callers keep working. |
| Top-level `slappyengine.build_vehicle`, `VehicleSpec`, `WheelSpec` | Re-exports from `slappyengine/__init__.py`; resolve to the same wrappers above. The Ochema-side import path does not change. |

Migration posture: the **legacy names stay**, but their guts increasingly
delegate to the unified backend. New code should reach for
`slappyengine.dynamics` directly; legacy code does not need touching to keep
working. The `SoftBodyWorld = World` alias at the bottom of
`dynamics/world.py` is the most explicit form of this contract — if you read
old code that talks to a `SoftBodyWorld`, it is now talking to a
`dynamics.World`, no shim layer in between.

## Failure modes and how to detect them

XPBD is *very* well behaved compared to force-based simulators, but there
are a small number of failure modes worth planning for:

- **NaN positions (solver instability).** Almost always caused by zero or
  near-zero edge vectors that produce a divide-by-zero in `_project_distance`.
  The kernel guards against this with `if d < 1e-12: return 0.0`
  (`joint.py:113`) but a chain of zero-length bones can still propagate
  garbage through `_project_angle`. The standard sentinel: every dynamics
  test ends with `assert not np.isnan(w.positions).any()` and
  `assert not np.isnan(w.velocities).any()`. Reproduce by feeding
  `RopeSpec(total_length=0.0)` and watch the position array explode.
  Recovery: reset offending nodes to their `prev_positions`, or rebuild the
  body from spec.

- **Joint blow-up (never converges).** When the configured stiffness is so
  high that a single iteration over-corrects past the rest length, the
  constraint can ping-pong indefinitely. Symptoms: position oscillation at
  amplitude equal to the over-correction step, persisting across many
  frames. Detect by tracking the correction magnitude returned by
  `resolve()` — sustained values close to the dataclass default
  `break_force=inf` indicate a runaway. Mitigation: lower `stiffness`,
  raise `solver_iterations`, or set an explicit `break_force` so the joint
  disables itself rather than blowing up the rest of the body.

- **Compound objects falling apart at high speed.** A motor + spring vehicle
  travelling faster than `motor.radius / dt` per substep will see the rim
  nodes skip past their stable hub orbit. The motor resolver caps tangential
  velocity at `max_torque * dt` but does not cap *radial* drift, so a very
  fast spin combined with a soft `stiffness` can break the hub-rim
  distance. Mitigation: enforce a maximum chassis speed in gameplay code,
  or raise the motor `stiffness` (the dataclass default `1.0e8` is intended
  precisely for this).

- **Mis-keyed `params` dict.** The solver reads `params.get(key, default)`
  so a typo silently disables the feature rather than crashing — see the
  motor's `hub == joint.node_a` fallback at `joint.py:244`. This is by
  design; the catch is that you will not get a stack trace pointing at
  the typo. Use `KIND_PARAM_KEYS` to validate (every joint test does this
  — see `test_motor_builder_writes_expected_keys`).

## Performance characteristics

Per-step cost is `O(nodes) + O(joints * solver_iterations)`. The default
`solver_iterations = 8` is set in `World.__init__` (`world.py:37`).
Concrete numbers from the test harness on the current machine
(numpy 2.x, Python 3.13, CPU only — no Rust port for the dynamics path yet):

| Scenario                                     | Wall time, 60 steps | Steps / s |
|----------------------------------------------|---------------------|-----------|
| 100-node rope, 8 iterations                  | 226 ms              | 265       |
| 6-bone humanoid ragdoll, 8 iterations        | 38 ms               | 1579      |
| Single motor pair (3 nodes), 8 iterations    | 11 ms               | 5560      |

(Measured with the `_build_toy_*` helpers in
`tests/test_dynamics_unified_step.py` and a `time.perf_counter` wrapper.)

The dynamics path is currently *pure Python + numpy*; no Rust port has
landed for the joint solvers. The hot loop is `World.step` →
`resolve(joint, world, dt)` → one or two numpy primitives per call. For
small worlds (under ~50 joints) this is GIL-friendly and fast enough to be
invisible against rendering cost; for >100 joints it is the dominant
frame-time cost and is the obvious next Rust target if the engine's
existing Rust kernel pattern proves portable to constraint-projection
work.

Two cheap wins exist short of porting:

- Raise `solver_iterations` only on bodies that need it. The rope test
  uses 16 iterations to get a clean catenary; nothing else in the test
  suite needs more than 12.
- Pre-disable broken joints (`joint.enabled = False`) rather than
  removing them. The skip is one bool check (`world.py:109`) versus an
  O(joints) list rebuild.

## See also

- `python/tests/test_dynamics_*.py` — usage examples and behavioural specs.
- `examples/hello_rope.py`, `examples/hello_ragdoll.py` — minimal demos
  (where present in the working tree).
- `docs/softbody_design.md` — the legacy lattice/vehicle interface;
  `dynamics` is the unifying generalisation.
- Macklin, Müller, Chentanez (2016) — *"XPBD: Position-Based Simulation of
  Compliant Constrained Dynamics."* The substrate paper.
- Aristidou, Lasenby, Chrysanthou, Shamir (2018) — *"Inverse Kinematics
  Techniques in Computer Graphics: A Survey."* Reference for CCD vs
  FABRIK choice.
