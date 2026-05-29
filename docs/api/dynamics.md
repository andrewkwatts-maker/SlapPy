# slappyengine.dynamics — API Reference

> Auto-generated. Re-run `python scripts/gen_subpackage_api_docs.py`.
> Do not hand-edit — every entry below comes from runtime introspection
> (`inspect.signature`, `inspect.getdoc`, `dataclasses.fields`).


Unified dynamics primitives layered on top of the XPBD substrate.

## Classes

### `Body`

_dataclass — defined in `slappyengine.dynamics.body`_

Generic body record.

#### Constructor signature

```python
Body(kind: 'str' = 'lattice', parameters: 'dict[str, Any]' = <factory>, node_offset: 'int' = 0, node_count: 'int' = 0, label: 'str' = '') -> None
```

#### Fields

- `kind: str` — default `'lattice'`
- `label: str` — default `''`
- `node_count: int` — default `0`
- `node_offset: int` — default `0`
- `parameters: dict[str, Any]` — default factory

### `BoneSpec`

_dataclass — defined in `slappyengine.dynamics.ragdoll`_

One bone in a ragdoll skeleton.

#### Constructor signature

```python
BoneSpec(parent_idx: 'int' = -1, length: 'float' = 1.0, mass: 'float' = 1.0, angle_limit: 'tuple[float, float]' = (-3.141592653589793, 3.141592653589793), direction: 'tuple[float, float]' = (0.0, -1.0), label: 'str' = '') -> None
```

#### Fields

- `angle_limit: tuple[float, float]` — default `(-3.141592653589793, 3.141592653589793)`
- `direction: tuple[float, float]` — default `(0.0, -1.0)`
- `label: str` — default `''`
- `length: float` — default `1.0`
- `mass: float` — default `1.0`
- `parent_idx: int` — default `-1`

#### Raises

- `ValueError` — If ``length <= 0``, ``mass <= 0``, ``angle_limit`` is mis-shaped or has ``min > max``, or ``direction`` is mis-shaped.

### `IKChainSpec`

_dataclass — defined in `slappyengine.dynamics.ik`_

Description of a kinematic chain + target point.

#### Constructor signature

```python
IKChainSpec(node_indices: 'list[int]', target: 'tuple[float, float]', fixed_root: 'bool' = True, params: 'dict[str, Any]' = <factory>) -> None
```

#### Fields

- `fixed_root: bool` — default `True`
- `node_indices: list[int]`
- `params: dict[str, Any]` — default factory
- `target: tuple[float, float]`

#### Raises

- `TypeError` — If ``node_indices`` is not a sequence or ``params`` is not a dict.
- `ValueError` — If ``node_indices`` is empty, contains negatives or non-ints, or ``target`` is not a finite 2-tuple.

### `JointSpec`

_dataclass — defined in `slappyengine.dynamics.joint`_

Generic two-node constraint.

#### Constructor signature

```python
JointSpec(kind: 'str', node_a: 'int', node_b: 'int', rest_length: 'float' = 0.0, stiffness: 'float' = 1000000000.0, damping: 'float' = 0.02, params: 'dict[str, Any]' = <factory>, break_force: 'float' = inf, enabled: 'bool' = True) -> None
```

#### Fields

- `break_force: float` — default `inf`
- `damping: float` — default `0.02`
- `enabled: bool` — default `True`
- `kind: str`
- `node_a: int`
- `node_b: int`
- `params: dict[str, Any]` — default factory
- `rest_length: float` — default `0.0`
- `stiffness: float` — default `1000000000.0`

#### Raises

- `TypeError` — If ``kind`` is not a ``str`` or ``params`` is not a ``dict``.
- `ValueError` — If ``kind`` is not one of the seven documented values, ``node_a`` equals ``node_b``, ``rest_length`` is negative, ``stiffness`` is not strictly positive, ``damping`` is outside ``[0, 1]``, or ``break_force`` is not strictly positive.

### `Material`

_dataclass — defined in `slappyengine.dynamics.material`_

Bulk physical parameters for a :class:`Body`.

#### Constructor signature

```python
Material(name: 'str' = 'default', density: 'float' = 1000.0, stiffness: 'float' = 1000000.0, damping: 'float' = 0.05, restitution: 'float' = 0.2, friction: 'float' = 0.5, breaking_strain: 'float' = inf, properties: 'dict[str, Any]' = <factory>) -> None
```

#### Fields

- `breaking_strain: float` — default `inf`
- `damping: float` — default `0.05`
- `density: float` — default `1000.0`
- `friction: float` — default `0.5`
- `name: str` — default `'default'`
- `properties: dict[str, Any]` — default factory
- `restitution: float` — default `0.2`
- `stiffness: float` — default `1000000.0`

### `MotorSpec`

_dataclass — defined in `slappyengine.dynamics.motor`_

Pure-data record for a motor joint.

#### Constructor signature

```python
MotorSpec(hub: 'int', rim_a: 'int', rim_b: 'int', target_omega: 'float', max_torque: 'float', radius: 'float' = 0.0, axis: 'tuple[float, float]' = (1.0, 0.0), stiffness: 'float' = 100000000.0, damping: 'float' = 0.02, params: 'dict[str, Any]' = <factory>) -> None
```

#### Fields

- `axis: tuple[float, float]` — default `(1.0, 0.0)`
- `damping: float` — default `0.02`
- `hub: int`
- `max_torque: float`
- `params: dict[str, Any]` — default factory
- `radius: float` — default `0.0`
- `rim_a: int`
- `rim_b: int`
- `stiffness: float` — default `100000000.0`
- `target_omega: float`

### `RagdollSpec`

_dataclass — defined in `slappyengine.dynamics.ragdoll`_

Skeleton description for :func:`build_ragdoll`.

#### Constructor signature

```python
RagdollSpec(bones: 'list[BoneSpec]' = <factory>, joints: 'list[JointSpec]' = <factory>, stiffness: 'float' = 5000000.0, damping: 'float' = 0.05) -> None
```

#### Fields

- `bones: list[BoneSpec]` — default factory
- `damping: float` — default `0.05`
- `joints: list[JointSpec]` — default factory
- `stiffness: float` — default `5000000.0`

#### Raises

- `TypeError` — If ``bones`` or ``joints`` is not a list, or any entry is wrong type.
- `ValueError` — If ``bones`` is empty, any bone references a non-existent parent index, ``stiffness <= 0``, or ``damping`` is outside ``[0, 1]``.

### `RopeSpec`

_dataclass — defined in `slappyengine.dynamics.rope`_

Description of a rope between two anchor points.

#### Constructor signature

```python
RopeSpec(node_count: 'int', total_length: 'float', mass_per_node: 'float' = 0.1, stiffness: 'float' = 1000000.0, damping: 'float' = 0.05, bend_stiffness: 'float' = 0.0, anchor_a_pinned: 'bool' = True, anchor_b_pinned: 'bool' = False, params: 'dict[str, Any]' = <factory>) -> None
```

#### Fields

- `anchor_a_pinned: bool` — default `True`
- `anchor_b_pinned: bool` — default `False`
- `bend_stiffness: float` — default `0.0`
- `damping: float` — default `0.05`
- `mass_per_node: float` — default `0.1`
- `node_count: int`
- `params: dict[str, Any]` — default factory
- `stiffness: float` — default `1000000.0`
- `total_length: float`

#### Raises

- `TypeError` — If ``params`` is not a ``dict``.
- `ValueError` — If ``node_count < 2``, ``total_length <= 0``, ``mass_per_node <= 0``, ``stiffness <= 0``, ``damping`` is outside ``[0, 1]``, or ``bend_stiffness`` is negative.

### `SoftBodyWorld`

_class — defined in `slappyengine.dynamics.world`_

Container of nodes + bodies + joints with a single :meth:`step` loop.

#### Constructor signature

```python
SoftBodyWorld(gravity: 'tuple[float, float]' = (0.0, -9.81)) -> 'None'
```

#### Methods

- `add_joint(self, joint: 'Any') -> 'Any'`
- `add_node(self, pos: 'tuple[float, float]', mass: 'float' = 1.0) -> 'int'` — Append a node, returning its absolute index. ``mass == 0`` pins it.
- `add_nodes(self, positions: 'np.ndarray', masses: 'np.ndarray | float' = 1.0) -> 'tuple[int, int]'` — Bulk-append nodes. Returns ``(offset, count)``.
- `register_body(self, body: 'Any') -> 'Any'`
- `step(self, dt: 'float') -> 'None'` — Integrate one frame using XPBD-style position projection.

### `SpringSpec`

_dataclass — defined in `slappyengine.dynamics.spring`_

Pure-data record for a spring; resolves to ``JointSpec(kind='spring')``.

#### Constructor signature

```python
SpringSpec(node_a: int, node_b: int, rest_length: float, stiffness: float = 1000000.0, damping: float = 0.05, params: dict[str, typing.Any] = <factory>) -> None
```

#### Fields

- `damping: float` — default `0.05`
- `node_a: int`
- `node_b: int`
- `params: dict` — default factory
- `rest_length: float`
- `stiffness: float` — default `1000000.0`

### `World`

_class — defined in `slappyengine.dynamics.world`_

Container of nodes + bodies + joints with a single :meth:`step` loop.

#### Constructor signature

```python
World(gravity: 'tuple[float, float]' = (0.0, -9.81)) -> 'None'
```

#### Methods

- `add_joint(self, joint: 'Any') -> 'Any'`
- `add_node(self, pos: 'tuple[float, float]', mass: 'float' = 1.0) -> 'int'` — Append a node, returning its absolute index. ``mass == 0`` pins it.
- `add_nodes(self, positions: 'np.ndarray', masses: 'np.ndarray | float' = 1.0) -> 'tuple[int, int]'` — Bulk-append nodes. Returns ``(offset, count)``.
- `register_body(self, body: 'Any') -> 'Any'`
- `step(self, dt: 'float') -> 'None'` — Integrate one frame using XPBD-style position projection.

## Functions

### `build_ragdoll(spec: 'RagdollSpec', world, anchor_pos: 'tuple[float, float]', pin_root: 'bool' = False) -> 'Body'`

_defined in `slappyengine.dynamics.ragdoll`_

Spawn nodes + joints for the ragdoll skeleton.

#### Raises

- `TypeError` — If ``spec`` is not a :class:`RagdollSpec`, ``world`` is not compatible, or ``anchor_pos`` is not a 2-sequence.
- `ValueError` — If ``anchor_pos`` contains non-finite values, or any bone references a parent that has not been built yet (legacy guard kept for safety).

### `build_rope(spec: 'RopeSpec', world, anchor_a: 'tuple[float, float]', anchor_b: 'tuple[float, float]') -> 'Body'`

_defined in `slappyengine.dynamics.rope`_

Spawn nodes + joints describing the rope.

#### Raises

- `TypeError` — If ``spec`` is not a :class:`RopeSpec`, ``world`` is not a compatible world object, or the anchors are not 2-sequences.
- `ValueError` — If anchor entries are non-finite or ``anchor_a == anchor_b``.

### `estimate_effective_damping(damping: 'float', iters: 'int') -> 'float'`

_defined in `slappyengine.dynamics.world`_

Effective per-step damping ratio after N iterations of multiplicative per-iter damping.

### `make_motor(hub: 'int', rim_a: 'int', rim_b: 'int', target_omega: 'float', max_torque: 'float', radius: 'float' = 0.0, axis: 'tuple[float, float]' = (1.0, 0.0), stiffness: 'float' = 100000000.0, damping: 'float' = 0.02) -> 'JointSpec'`

_defined in `slappyengine.dynamics.motor`_

Construct a motor :class:`JointSpec` between hub and the two rim nodes.

#### Raises

- `TypeError` — If any index is not int-coercible, or ``axis`` is not a 2-sequence.
- `ValueError` — If indices are negative, the hub coincides with a rim, the two rims coincide, ``target_omega`` is non-finite, ``max_torque <= 0``, ``radius < 0``, ``stiffness <= 0``, or ``damping`` is outside ``[0, 1]``.

### `make_spring(node_a: int, node_b: int, rest_length: float, stiffness: float = 1000000.0, damping: float = 0.05) -> slappyengine.dynamics.joint.JointSpec`

_defined in `slappyengine.dynamics.spring`_

Build a spring constraint between two nodes.

#### Raises

- `TypeError` — If ``node_a`` or ``node_b`` is not int-coercible.
- `ValueError` — If indices are negative or equal, ``rest_length < 0``, ``stiffness <= 0``, or ``damping`` is outside ``[0, 1]``.

### `resolve_joint(joint: 'JointSpec', world: "'World'", dt: 'float') -> 'float'`

_defined in `slappyengine.dynamics.joint`_

Dispatch a joint to its XPBD projection. Returns correction magnitude.

### `solve_ik(spec: 'IKChainSpec', world, iterations: 'int' = 10, tolerance: 'float' = 0.01) -> 'bool'`

_defined in `slappyengine.dynamics.ik`_

Solve the chain toward the target using CCD.

#### Raises

- `TypeError` — If ``spec`` is not an :class:`IKChainSpec` or ``world`` is not a compatible world object.
- `ValueError` — If ``iterations <= 0`` or ``tolerance <= 0``.

## Constants

### `KIND_PARAM_KEYS`

_dict — defined in `slappyengine.dynamics`_

Value: `{'distance': set(), 'spring': set(), 'weld': {'rest_offset'}, 'ball': set(), ...`

### `OVERDAMPING_THRESHOLD`

_float — defined in `slappyengine.dynamics`_

Value: `0.5`

## Inner modules

- `slappyengine.dynamics.body`
- `slappyengine.dynamics.ik`
- `slappyengine.dynamics.joint`
- `slappyengine.dynamics.material`
- `slappyengine.dynamics.motor`
- `slappyengine.dynamics.ragdoll`
- `slappyengine.dynamics.rope`
- `slappyengine.dynamics.spring`
- `slappyengine.dynamics.world`
