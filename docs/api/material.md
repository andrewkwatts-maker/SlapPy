<!-- handauthored: do not regenerate -->
# pharos_engine.material — API Reference

> Hand-written reference for the material subpackage.
> Covers `NodeMaterial` graph authoring, the `KNOWN_NODE_TYPES` registry,
> and the 18 node-factory functions restored in Sprint 1B. For the
> material-tag side (color-range / behavior tags consumed by
> `material_editor.py`) see [`map.py`](../../python/pharos_engine/material/map.py)
> and the in-tree [`material_catalog.md`](../material_catalog.md).


The subpackage is **lazy-loaded**: `__init__.py` registers names in
`_LAZY_MAP` and resolves them through `__getattr__`, so
`import pharos_engine` does not pull in `wgpu` or the Rust `_core`
extension until a graph is actually compiled.

Pipeline shape: build a `NodeMaterial`, call factory functions to append
`NodeDef` records, wire them up with `connect()`, optionally
`to_json()` round-trip through `from_json()`, then `compile()` to WGSL
through `_core.compile_node_graph`.

## Public surface (`__all__`)

- `NodeDef`, `NodeMaterial` — graph authoring primitives
  (`node_material.py`).
- `validate_node_graph`, `KNOWN_NODE_TYPES`, `KNOWN_PORT_TYPES` —
  graph-schema checking (`graph_schema.py`).
- `ColorRange`, `MaterialDef`, `MaterialMap` — color-range +
  behavior-tag side (`map.py`).
- 10 capitalised node factories exported via `__all__`
  (`UVNode`, `PixelColorNode`, `PixelChannelNode`, `AddNode`,
  `MultiplyNode`, `LerpNode`, `ClampNode`, `GravityWarpNode`,
  `SampleTextureNode`, `FinalColorNode`, `DiscardNode`).

> **Sprint 1B note.** The lower-case sim-field / math / output
> factories (`ReadFieldNode`, `WriteFieldNode`, `SampleSimFieldNode`,
> `SinNode`, `CosNode`, `PowNode`, `RemapNode`, `LengthNode`,
> `NormalizeNode`, `DotNode`, `NoiseNode`, `WorldPosNode`,
> `TimeNode`, `OffsetUVNode`, `ReflectUVNode`, `AccumulateNode`,
> `RayMarchNode`, `ForceOutputNode`, `ReduceOutputNode`) were
> **restored** in Sprint 1B alongside the 19 corresponding entries in
> `KNOWN_NODE_TYPES`. They are not in `__all__` (yet) but are importable
> from `pharos_engine.material.node_material` and are the canonical
> contract checked by `test_node_material_lighting_obs.py` and
> `test_nodegraph_compiler_e1.py`.

## Classes

### `NodeDef`

_dataclass — defined in `pharos_engine.material.node_material`_

One node in a material graph. `id` defaults to an 8-character hex slug
via `_gen_id()` so graphs can be built without manual id wrangling and
still round-trip stably through `to_json()` / `from_json()`.

```python
NodeDef(
    node_type: str,
    params: dict,
    id: str = <factory: 8-char hex>,
) -> None
```

- `node_type` — the kind tag; must appear in `KNOWN_NODE_TYPES` to pass
  `validate_node_graph` without a warning.
- `params` — opaque per-kind config bag; specific factories know the
  schema (e.g. `ClampNode` writes `{"min", "max"}`,
  `NoiseNode` writes `{"mode", "octaves"}`).
- `id` — stable identifier used by `NodeMaterial._edges` to address
  endpoints (`{"from_node": id, "from_port": str, ...}`).

### `NodeMaterial`

_class — defined in `pharos_engine.material.node_material`_

Ordered graph of `NodeDef` records plus a list of edges. The class is
deliberately small: it owns the topology, the JSON round-trip, the
output-mode inference, and a single bridge through to the Rust
compiler.

```python
NodeMaterial(name: str) -> None
```

#### Methods

- `node(self, node_def: NodeDef) -> NodeDef` — append a node and
  return it so callers can chain `mat.node(UVNode())` and capture the
  result for later `connect()` calls.
- `connect(self, from_node: NodeDef, from_port: str,
  to_node: NodeDef, to_port: str) -> NodeMaterial` — append an edge
  using the node `id`s; returns `self` so calls chain.
- `to_json(self) -> str` — serialise to the wire-format `{nodes, edges}`
  dict expected by `validate_node_graph` and `_core.compile_node_graph`.
- `from_json(cls, name: str, json_str: str) -> NodeMaterial` — inverse
  of `to_json`; restores `NodeDef` records with their original `id` so
  edge references stay valid.
- `compile(self) -> str` — invoke the Rust `_core.compile_node_graph`
  on the JSON; cache the result in `_compiled_wgsl`. Raises
  `RuntimeError` if the `_core` extension is not available (no WGSL
  fallback — this is a Rust-only path).

#### Attributes

- `blend: str` — composition mode; default `"normal"`. Consumed by
  the layer compositor.
- `wgsl` _(property)_ — the cached WGSL from the last `compile()`
  call, or `None`.
- `output_mode` _(property)_ — one of `"render"` (default),
  `"sim_write"`, `"force"`, `"reduce"`. Computed from the **last**
  terminal node in `_nodes` (`FinalColor` / `write_field` /
  `force_output` / `reduce_output`); empty / intermediate-only graphs
  default to `"render"`. The "last wins" rule matches
  `test_output_mode_ignores_non_terminal_nodes`.

## Factory functions

Eighteen single-purpose helpers that return a `NodeDef` with the
right `node_type` string and a sensible `params` default. Grouped by
category:

### I/O

- `UVNode()` — emit screen-space UV. Outputs `uv`.
- `PixelColorNode()` — read the current pixel's RGBA. Outputs `color`.
- `PixelChannelNode(channel: str)` — read a single channel (`"r"`,
  `"g"`, `"b"`, `"a"`) by name. Outputs `val`.
- `SampleTextureNode()` — fetch a bound texture at the input UV.
  Outputs `color`; inputs `uv`.
- `FinalColorNode()` — terminal node; takes `color` and writes it as
  the fragment output. Sets `output_mode = "render"`.
- `DiscardNode()` — terminal discard (alpha-test style); no ports.

### Math / arithmetic

- `AddNode()` — `out = a + b`.
- `MultiplyNode()` — `out = a * b`.
- `LerpNode()` — `out = mix(a, b, t)`.
- `ClampNode(min_val: float = 0.0, max_val: float = 1.0)` —
  saturate; defaults to `[0, 1]`.
- `PowNode(exponent: float = 2.0)` — power with a constant exponent
  (cheaper than a generic 2-input pow).
- `RemapNode(in_min, in_max, out_min, out_max)` — affine remap;
  defaults to identity on `[0, 1]`.
- `SinNode()` / `CosNode()` — single-input trig.
- `LengthNode()` — `||v||`.
- `NormalizeNode()` — `v / ||v||`.
- `DotNode()` — `dot(a, b)`.

### Geometry / sampling

- `WorldPosNode()` — world-space fragment position.
- `TimeNode()` — engine time (seconds since startup).
- `OffsetUVNode()` — apply a parameter offset to UV.
- `ReflectUVNode()` — mirror UV around the centre.
- `GravityWarpNode(strength: float = 2.0, radius: float = 0.3)` —
  pinch the UV toward a centre using the same falloff as
  `add_gravity_warp` in the post-process chain. Inputs `uv`, outputs
  `out_uv`.
- `NoiseNode(mode: str = "fbm", octaves: int = 4)` — procedural noise;
  `mode` selects the kernel.
- `SampleSimFieldNode(field_ref: str = "", channel: str = "")` —
  sample one channel of a named sim-field grid; works in tandem with
  `ReadFieldNode`.

### Control flow / accumulation

- `AccumulateNode(decay: float = 0.9)` — recurrent accumulator with
  exponential decay; used by accumulation-stage materials.
- `RayMarchNode(steps: int = 16, direction: tuple = (0.0, 1.0))` —
  fixed-step ray march along `direction`. Inputs `origin`, `dir`;
  outputs `hit`.

### Sim-field read / write (output stages)

- `ReadFieldNode(field: str)` — bind a named simulation field for read.
- `WriteFieldNode(field: str)` — terminal; writes the upstream value
  back into the named field. Sets `output_mode = "sim_write"`.
- `ForceOutputNode()` — terminal; emits a force into the dynamics
  layer. Sets `output_mode = "force"`.
- `ReduceOutputNode(field: str = "", op: str = "sum")` — terminal;
  reduces the upstream into a single scalar (`"sum"`, `"max"`, …) and
  writes to `field`. Sets `output_mode = "reduce"`.

## Constants

### `KNOWN_NODE_TYPES`

_frozenset[str] — defined in `pharos_engine.material.graph_schema`_

The 31-entry allow-list of node-type strings. Validation emits a
non-fatal warning for unknown types (still returns an `errors` entry,
but the graph remains constructable). Includes the 12 capitalised
classic types (`UV`, `PixelColor`, `PixelChannel`, `Add`, `Multiply`,
`Lerp`, `Clamp`, `Remap`, `GravityWarp`, `SampleTexture`, `FinalColor`,
`Discard`) plus the 19 lower-case sim-field / math / output kinds
restored in Sprint 1B (`read_field`, `write_field`, `sample_sim_field`,
`sin`, `cos`, `pow`, `remap`, `length`, `normalize`, `dot`, `noise`,
`world_pos`, `time`, `offset_uv`, `reflect_uv`, `accumulate`,
`ray_march`, `force_output`, `reduce_output`).

### `KNOWN_PORT_TYPES`

_dict[str, dict] — defined in `pharos_engine.material.graph_schema`_

Per-kind `{"inputs": [...], "outputs": [...]}` port manifest. Only the
classic node types are listed today; the lower-case sim-field kinds
are validated structurally without a port manifest entry.

## Functions

### `validate_node_graph(graph_dict: dict) -> list[str]`

_defined in `pharos_engine.material.graph_schema`_

Structural validator that returns a list of error strings (empty on
success). Catches:

- Missing top-level `nodes` / `edges` keys.
- `nodes` or `edges` not being a list.
- Per-node: non-string / empty `id`, duplicate `id`, missing or
  unknown `type` (warning), non-dict `params`.
- Per-edge: non-string `from_node` / `from_port` / `to_node` /
  `to_port`; `from_node` or `to_node` referencing an unknown id.

The validator is **schema-only** — it does not check that ports exist
on the referenced node types (that is the Rust compiler's job).

## Inner modules

- `node_material` — `NodeDef`, `NodeMaterial`, the 18 factory
  functions, the `_TERMINAL_MODES` lookup table.
- `graph_schema` — `KNOWN_NODE_TYPES`, `KNOWN_PORT_TYPES`,
  `validate_node_graph`.
- `map` — `ColorRange`, `MaterialDef`, `MaterialMap` (the
  color-range / behavior-tag side consumed by `material_editor.py`).

## Conventions

- **Lazy import.** `__init__.py` resolves names through a `_LAZY_MAP`
  + `__getattr__` so a bare `import pharos_engine` never imports the
  Rust `_core` extension.
- **Capitalised vs lowercase node types.** Classic render-path kinds
  use `PascalCase` (`UV`, `FinalColor`); sim-field / math / output
  kinds added in Sprint 1B use `snake_case` (`read_field`,
  `force_output`). The split is intentional — the lowercase names
  match the Rust factory contract one-to-one.
- **Terminal-node "last wins".** `output_mode` walks `_nodes` in
  insertion order and the last terminal kind wins, mirroring the e1
  compiler's tie-break rule. Intermediate-only graphs default to
  `"render"`.
- **Rust-only compile.** There is no Python WGSL fallback;
  `compile()` raises `RuntimeError` if `_core` is missing. The
  compiled WGSL is cached on `_compiled_wgsl` and exposed read-only
  through the `wgsl` property.

## See also

- [`../material_design.md`](../material_design.md) — `NodeMaterial`
  graph runtime, the 12+19 factory split, validation layering, and
  the Rust-only compile rationale.
- [`../material_catalog.md`](../material_catalog.md) — the
  `MaterialMap` side of the system (classification + behaviour tags
  consumed by per-pixel physics).
- [`ui_editor.md`](ui_editor.md) — `MaterialEditor` (the visual
  authoring panel) and `PropertyInspector` (the reflection panel
  softbody / fluid material editing reuses).
- [`gpu.md`](gpu.md) — `MaterialBuffer` packs the `MaterialMap` into
  a 32-byte std430 storage buffer for the per-pixel classification
  shader.
