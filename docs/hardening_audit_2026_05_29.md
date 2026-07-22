# Phase-B/C Subpackage Hardening Audit — 2026-05-29

Branch: `hardening-input-validation`

## Scope

This audit covers the new Phase B / B+ / C subpackages exposed via the public
`pharos_engine.*` namespace. For each public function and class constructor we
record the expected input contract and any silent-bad-input bugs found during
the audit.

Engineering policy: validate at the system boundary (every public entry
point), trust internal calls. Internal helpers (anything prefixed with `_` or
inside a builder) are NOT re-validated.

Out of scope (per task brief): `softbody/`, `fluid/`, `lighting/`, `audio/`,
`editor/`, `post_process/`, top-level `__init__.py`.

## Inventory

### `pharos_engine.topology`

| Entry point | Inputs | Contract |
|---|---|---|
| `connected_components(n_nodes, edges, active=None, node_mask=None)` | `n_nodes: int`, `edges: np.ndarray (E,2) int`, `active: np.ndarray (E,) bool`, `node_mask: np.ndarray (n_nodes,) bool` | `n_nodes >= 0`; `edges` is a numpy array of shape `(E, 2)`; edge indices in `[0, n_nodes)`; `active.shape == (E,)`; `node_mask.shape == (n_nodes,)` |
| `connected_components_grid(density, bond_e, bond_s, density_threshold, bond_threshold)` | three 2-D ndarrays, two scalars | all three arrays same shape and 2-D; thresholds finite |

### `pharos_engine.numerics`

| Entry point | Inputs | Contract |
|---|---|---|
| `vcycle_poisson(rhs, mask=None, iters_per_level=2, levels=3, n_cycles=1, omega=1.5, coarse_iters=8, initial=None, smooth_pre=None, smooth_post=None)` | `rhs: np.ndarray (H,W)`, optional `mask` / `initial`, scalar tuning knobs | rhs is `np.ndarray`, 2-D; mask/initial match rhs shape; iters_per_level ≥ 0; levels ≥ 1; n_cycles ≥ 1; coarse_iters ≥ 0; omega finite |
| `sor_smooth(p, rhs, iters=20, omega=1.0)` | two ndarrays, two scalars | p / rhs are ndarrays of matching shape, 2-D; iters ≥ 0 |
| `compute_residual(p, rhs)` | two ndarrays | p / rhs are ndarrays of matching shape, 2-D |

### `pharos_engine.zones`

| Entry point | Inputs | Contract |
|---|---|---|
| `RectZone(name, x, y, w, h, material=None, on_enter=None, on_exit=None)` | dataclass | `w > 0`, `h > 0`; `name` non-empty str |
| `ThresholdZone(... threshold, hysteresis=0.05, ...)` | dataclass | `w/h > 0`; `hysteresis >= 0`; `strength_scale >= 0` |
| `ZoneManager.add(zone)` | RectZone | zone is RectZone (or subclass) |
| `ZoneManager.update(positions)` | dict or iterable of `(eid, (x, y))` | each position is a 2-tuple of finite floats |
| `ZoneManager.update_threshold(name, value)` | name str, value float | name str, value finite float |

### `pharos_engine.thermal`

| Entry point | Inputs | Contract |
|---|---|---|
| `HeatField(grid, conductivity=1.0, diffusivity=0.1)` | ndarray + 2 scalars | grid is `np.ndarray`, 2-D, ≥ 2×2; conductivity ≥ 0; diffusivity in `(0, 1]` |
| `HeatField.step(dt, *, boundary='periodic', substeps=None)` | scalar + str + optional int | dt > 0; boundary in `{"periodic", "clamp"}`; substeps ≥ 1 if given |
| `HeatField.exchange_with(other, contact_pairs, dt=1.0, conductivity=None)` | HeatField + iterable + scalars | other is HeatField; dt > 0; conductivity > 0 if given |
| `exchange_two_regions(t_a, m_a, k_a, t_b, m_b, k_b, dt)` | 7 scalars | all finite floats; dt ≥ 0 |

### `pharos_engine.iso.combat`

| Entry point | Inputs | Contract |
|---|---|---|
| `Attacker(pos, damage, reach, team='player')` | dataclass | `damage >= 0`, `reach >= 0`, `pos` is 2-tuple of finite floats |
| `Defender(pos, hp, team='enemy')` | dataclass | `pos` is 2-tuple of finite floats; `hp` finite |
| `resolve_attack(attacker, defender)` | two dataclasses | attacker is Attacker; defender is Defender |
| `WaveSpec(count, spawn_points, hp_each, interval, delay=0.0)` | dataclass | `count >= 0`; if `count > 0` then `len(spawn_points) >= 1`; `hp_each > 0`; `interval >= 0`; `delay >= 0` |
| `WaveSchedule(waves)` | list of `WaveSpec` | waves is iterable of WaveSpec; every spec passes WaveSpec contract |
| `WaveSchedule.tick(dt)` | scalar | dt finite float |

### `pharos_engine.dynamics`

| Entry point | Inputs | Contract |
|---|---|---|
| `Body(kind, parameters, node_offset, node_count, label)` | dataclass | `node_offset >= 0`, `node_count >= 0` |
| `Material(name, density, stiffness, damping, restitution, friction, breaking_strain)` | dataclass | density > 0; stiffness ≥ 0; damping in [0, 1]; restitution in [0, 1]; friction ≥ 0; breaking_strain > 0 |
| `JointSpec(kind, node_a, node_b, ...)` | dataclass | `kind` in `KIND_PARAM_KEYS`; node_a, node_b ≥ 0 ints; rest_length ≥ 0; stiffness ≥ 0; damping in [0, 1] |
| `make_spring(node_a, node_b, rest_length, stiffness=1e6, damping=0.05)` | scalars | both nodes ≥ 0; rest_length ≥ 0; stiffness ≥ 0; damping in [0, 1] |
| `make_motor(hub, rim_a, rim_b, target_omega, max_torque, ...)` | scalars | all node indices ≥ 0; max_torque ≥ 0 |
| `RopeSpec(node_count, total_length, ...)` | dataclass | `node_count > 1`; `total_length > 0`; `mass_per_node > 0`; `stiffness ≥ 0`; `damping in [0, 1]`; `bend_stiffness ≥ 0` |
| `build_rope(spec, world, anchor_a, anchor_b)` | spec + world + 2 tuples | spec is RopeSpec; anchors are 2-tuples of finite floats; world has `add_nodes` / `add_joint` / `register_body` |
| `BoneSpec(parent_idx, length, mass, angle_limit, direction, label)` | dataclass | `length > 0`; `mass > 0`; `angle_limit` 2-tuple `min <= max`; `direction` 2-tuple |
| `RagdollSpec(bones, joints, stiffness, damping)` | dataclass | every bone passes BoneSpec contract; every bone's `parent_idx` is in `[-1, len(bones))` and points strictly earlier in the list; root bone has parent_idx=-1 |
| `build_ragdoll(spec, world, anchor_pos, pin_root=False)` | spec + world + tuple | spec is RagdollSpec; `len(spec.bones) >= 1`; every joint refers to a valid bone index; anchor_pos is 2-tuple of finite floats |
| `IKChainSpec(node_indices, target, fixed_root, params)` | dataclass | `len(node_indices) >= 2`; every index ≥ 0; `target` is finite 2-tuple |
| `solve_ik(spec, world, iterations=10, tolerance=0.01)` | spec + world + scalars | spec is IKChainSpec; `iterations > 0`; `tolerance > 0` |
| `World(gravity)` | tuple | gravity is 2-tuple of finite floats |
| `World.add_node(pos, mass=1.0)` | tuple + scalar | pos 2-tuple; mass ≥ 0 finite |
| `World.add_nodes(positions, masses=1.0)` | ndarray + scalar or ndarray | positions is `(N, 2)` ndarray; masses scalar or `(N,)` array |
| `World.step(dt)` | scalar | dt > 0 finite |

## Bugs found in positive paths

The following pre-hardening behaviours silently accepted invalid input and
produced nonsense rather than raising. These are the highest-value
hardening wins — they would have been silent corruptors at runtime:

1. **`zones.RectZone` accepted negative or zero `w` / `h`.** A negative
   rect always returned `False` from `contains_point` because the half-open
   check `x <= px < x + w` is unsatisfiable when `w < 0`. Threshold/enter
   events would never fire — pure silent broken state.
2. **`zones.ZoneManager.update` accepted `(x,)` length-1 tuples.** It
   raised an `IndexError` from `pos[1]` deep inside the loop, but only
   *after* having mutated some occupancy maps. Now it validates the shape
   up front.
3. **`thermal.HeatField.step(dt=-1)` silently returned with no error**
   (the legacy code had `if dt <= 0: return`). For a public boundary
   that's a contract bug: negative dt is a coding error, not a no-op.
   Now it raises.
4. **`thermal.HeatField.step` accepted any string for `boundary`** —
   it raised but the message was an internal helper trace. Already
   validates explicitly; the validation message is now precise.
5. **`iso.combat.resolve_attack` accepted `damage < 0`** — a negative
   damage would silently *heal* the defender. Now `Attacker.__post_init__`
   refuses.
6. **`iso.combat.resolve_attack` accepted `reach < 0`** — the distance
   check always failed (`dist > reach` is always true when reach is
   negative) so the attacker could never hit; silently broken.
7. **`iso.combat.WaveSpec` accepted `count > 0` with empty
   `spawn_points`** — would later `ZeroDivisionError` from
   `spawned % len(spawn_points)` inside the tick loop. Now refuses on
   construction.
8. **`iso.combat.WaveSpec` accepted `interval < 0`** — would make
   `next_spawn_at` regress and emit spawns indefinitely (off-by-design).
   Now refuses.
9. **`dynamics.RopeSpec.node_count == 1`** — the builder divided
   `total_length / (n - 1)` and produced `inf` segment length. Now the
   spec validates `node_count > 1` on construction.
10. **`dynamics.build_rope` accepted `total_length <= 0`** — silently
    spawned a zero-length rope with overlapping nodes. Now `RopeSpec`
    refuses on construction.
11. **`dynamics.RagdollSpec` accepted forward references** — a bone
    whose `parent_idx > bone_index` would raise a vague
    `"references parent not yet built"` mid-build. Now the spec is
    rejected up front with a precise message.
12. **`dynamics.solve_ik` accepted `iterations <= 0`** — old code
    silently clamped to 1 via `max(1, iterations)`. That's a "default to
    safe value" fallback we explicitly want to remove for boundary
    inputs.
13. **`dynamics.solve_ik` accepted `tolerance <= 0`** — the loop ran
    its full iteration budget every time because `dist < tolerance`
    could never be true. Silent waste of cycles.
14. **`numerics.vcycle_poisson` accepted `rhs` as a Python list** —
    relied on duck-typing through `.ndim`. Now refuses non-ndarray.

## Modules touched

- `python/pharos_engine/topology/__init__.py`
- `python/pharos_engine/numerics/__init__.py`
- `python/pharos_engine/zones/__init__.py`
- `python/pharos_engine/thermal/__init__.py`
- `python/pharos_engine/iso/combat.py`
- `python/pharos_engine/dynamics/rope.py`
- `python/pharos_engine/dynamics/ragdoll.py`
- `python/pharos_engine/dynamics/ik.py`
- `python/pharos_engine/dynamics/spring.py`
- `python/pharos_engine/dynamics/motor.py`
- `python/pharos_engine/dynamics/material.py`
- `python/pharos_engine/dynamics/world.py`

## New tests

- `python/tests/test_hardening_topology.py`
- `python/tests/test_hardening_numerics.py`
- `python/tests/test_hardening_zones.py`
- `python/tests/test_hardening_thermal.py`
- `SlapPyEngineTests/tests/test_hardening_iso_combat.py`
- `SlapPyEngineTests/tests/test_hardening_dynamics.py`
