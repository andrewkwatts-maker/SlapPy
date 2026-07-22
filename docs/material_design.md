# pharos_engine.material — Design Reference

`pharos_engine.material` is the engine's **node-graph material authoring
system** — a small set of dataclasses (`NodeDef`, `NodeMaterial`) plus
18 factory functions that produce well-formed `NodeDef` records. The
authored graph round-trips through JSON, validates against a schema,
and compiles to WGSL via the Rust `_core.compile_node_graph` entry
point. There is **no Python WGSL fallback** — graph compilation is a
Rust-only path.

For the runtime API surface (every factory, the `NodeMaterial` methods,
the schema constants), see the companion
[API reference](api/material.md).

## Why a node graph?

The engine ships two material authoring paths:

1. **`MaterialMap`** — a flat list of `MaterialDef` records with R/G/B
   colour ranges, alpha-meaning tags, and behaviour tags. Used by the
   per-pixel physics layer (`pharos_engine.physics`) for classification:
   "this pixel is in the wood band, it floats, it burns slowly". The
   authoring surface lives in `pharos_engine.material.map` and is
   covered by [`material_catalog.md`](material_catalog.md). Visual
   editor: `MaterialEditor` (kind `material_map`).
2. **`NodeMaterial`** — a node graph that compiles to a fragment shader
   for the rendering layer. Inputs are screen-space UV, current pixel
   colour, time, world position; outputs are final colour (`render`
   mode) or a sim-field write / force / reduce (the other three
   `output_mode`s). The graph runtime is what this document covers.

The split is intentional. `MaterialMap` is a *classification* table —
it answers "what is this pixel made of?". `NodeMaterial` is a
*shader-construction* graph — it answers "given the world state, what
colour or force should this pixel produce?". The two systems coexist
without overlap.

## Graph runtime

A `NodeMaterial` is two ordered lists:

```python
@dataclass
class NodeMaterial:
    name: str
    _nodes: list[NodeDef] = field(default_factory=list)
    _edges: list[dict] = field(default_factory=list)
    blend: str = "normal"
```

The class is deliberately minimal — it owns the topology, the JSON
round-trip, the output-mode inference, and a single bridge through to
the Rust compiler. Everything else (port type checking, WGSL emission,
shader linking) is the Rust side's responsibility.

### Authoring flow

```python
mat = NodeMaterial(name="grass_wave")
uv     = mat.node(UVNode())                     # UV input
time   = mat.node(TimeNode())                   # time input
wave   = mat.node(GravityWarpNode(strength=2.0, radius=0.3))
mat.connect(uv,   "uv",  wave, "uv")
mat.connect(time, "out", wave, "time")
tex    = mat.node(SampleTextureNode())
mat.connect(wave, "out_uv", tex, "uv")
fin    = mat.node(FinalColorNode())
mat.connect(tex, "color", fin, "color")

mat.compile()              # → WGSL via Rust _core
print(mat.wgsl)            # cached compiled source
```

The factory functions (`UVNode`, `TimeNode`, `GravityWarpNode`, …) each
produce a `NodeDef` with the right `node_type` tag and a sensible
`params` default. `node()` appends it to the graph and returns the
record so it can be chained into `connect()`. Edges reference the
node's stable `id` (`8-char hex slug from _gen_id()`), so the graph can
round-trip through JSON without losing wiring.

### The 18 + 12 factory split

The Sprint 1B restoration brought the total factory count to 30:

- **12 capitalised PascalCase factories** exported via `__all__`:
  `UVNode`, `PixelColorNode`, `PixelChannelNode`, `AddNode`,
  `MultiplyNode`, `LerpNode`, `ClampNode`, `GravityWarpNode`,
  `SampleTextureNode`, `FinalColorNode`, `DiscardNode`,
  `WriteFieldNode` (terminal sim-field write).
- **19 lowercase snake_case factories** restored in Sprint 1B but not
  in `__all__` (importable from `pharos_engine.material.node_material`):
  `ReadFieldNode`, `WriteFieldNode`, `SampleSimFieldNode`, `SinNode`,
  `CosNode`, `PowNode`, `RemapNode`, `LengthNode`, `NormalizeNode`,
  `DotNode`, `NoiseNode`, `WorldPosNode`, `TimeNode`, `OffsetUVNode`,
  `ReflectUVNode`, `AccumulateNode`, `RayMarchNode`, `ForceOutputNode`,
  `ReduceOutputNode`.

The split is intentional and asserted by `test_node_material_lighting_obs.py`
and `test_nodegraph_compiler_e1.py`:

- **Capitalised** = "classic" render-path kinds. Stable, in `__all__`,
  unlikely to be renamed.
- **Lowercase** = sim-field / math / output kinds. Match the Rust
  factory contract one-to-one (`read_field`, `force_output`,
  `reduce_output`) so the compiler can look them up by name. Not in
  `__all__` because they are still considered "Sprint 1B beta" — the
  schema is stable but the surface may grow.

### `node_type` allow-list

`graph_schema.KNOWN_NODE_TYPES` is a 31-entry `frozenset` of allowed
type strings. `validate_node_graph(graph_dict)` emits a non-fatal
warning for unknown types (still returns an `errors` entry, but the
graph remains constructable). This is the schema-checking layer; the
deeper "do these ports exist on this node type?" check is the Rust
compiler's job.

The allow-list lives in Python (not in Rust) because the validator is
the editor's first line of defence — `MaterialEditor` runs it before
sending the graph to compile so an authoring mistake produces a clear
error message in the UI rather than an opaque Rust panic.

## Validation

`validate_node_graph(graph_dict) -> list[str]` is the structural
validator. It catches:

- Missing top-level `nodes` / `edges` keys.
- `nodes` or `edges` not being a list.
- Per-node: non-string / empty `id`, duplicate `id`, missing or
  unknown `type` (warning), non-dict `params`.
- Per-edge: non-string `from_node` / `from_port` / `to_node` /
  `to_port`; `from_node` or `to_node` referencing an unknown id.

The validator is **schema-only** — it does not check that ports exist
on the referenced node types. That check requires knowing the per-kind
port manifest, which today is partially in `KNOWN_PORT_TYPES` (only
the classic kinds) and fully in the Rust compiler.

Two layers exist for a reason: the Python validator runs in milliseconds
in the editor's authoring loop, while the Rust compiler runs at material
publish time. Catching topology errors early without paying for full
port-type resolution keeps the editor snappy.

## Output-mode inference

`NodeMaterial.output_mode` (property) is computed from the **last**
terminal node in `_nodes`:

| Terminal node type | `output_mode` |
|---|---|
| `FinalColorNode` | `"render"` |
| `WriteFieldNode` | `"sim_write"` |
| `ForceOutputNode` | `"force"` |
| `ReduceOutputNode` | `"reduce"` |
| (no terminal node) | `"render"` (default) |

The "last wins" rule mirrors the e1 compiler's tie-break and is pinned
by `test_output_mode_ignores_non_terminal_nodes`. Intermediate-only
graphs (e.g. a partially-built graph in the editor) default to
`"render"` so the preview pane has something to show.

Why "last" and not "first"? Authoring flow: you build the inputs and
math nodes first, then drop the terminal at the end. The last terminal
is the active output. If a graph has multiple terminals (e.g. an
abandoned `FinalColorNode` left behind during refactoring), the active
one is the one most recently added.

## JSON round-trip

`NodeMaterial.to_json() -> str` serialises to the wire format expected
by `validate_node_graph` and `_core.compile_node_graph`:

```json
{
  "name": "grass_wave",
  "nodes": [
    {"id": "a1b2c3d4", "type": "UV",          "params": {}},
    {"id": "e5f6a7b8", "type": "time",        "params": {}},
    {"id": "c9d0e1f2", "type": "GravityWarp", "params": {"strength": 2.0, "radius": 0.3}},
    {"id": "3a4b5c6d", "type": "SampleTexture","params": {}},
    {"id": "7e8f9a0b", "type": "FinalColor",  "params": {}}
  ],
  "edges": [
    {"from_node": "a1b2c3d4", "from_port": "uv",     "to_node": "c9d0e1f2", "to_port": "uv"},
    {"from_node": "e5f6a7b8", "from_port": "out",    "to_node": "c9d0e1f2", "to_port": "time"},
    {"from_node": "c9d0e1f2", "from_port": "out_uv", "to_node": "3a4b5c6d", "to_port": "uv"},
    {"from_node": "3a4b5c6d", "from_port": "color",  "to_node": "7e8f9a0b", "to_port": "color"}
  ],
  "blend": "normal"
}
```

`from_json(name, json_str)` is the inverse. `NodeDef.id` defaults to an
8-char hex slug via `_gen_id()` so graphs round-trip stably without
manual id wrangling — but if the caller supplies explicit ids
(e.g. for a content-pipeline canonical form), `from_json` preserves
them.

## Rust-only compile

`NodeMaterial.compile() -> str` invokes
`pharos_engine._core.compile_node_graph` on the JSON and caches the
result in `_compiled_wgsl`. The `wgsl` property exposes it read-only.

**There is no Python fallback.** `compile()` raises `RuntimeError` if
`_core` is unavailable. This is deliberate — the Rust compiler is the
canonical source of truth for port-type checking, WGSL emission, and
output-mode dispatch. Maintaining a Python shadow implementation would
double the test burden and introduce drift.

Authoring tools (editor, asset pipeline) that need offline schema
validation use `validate_node_graph(graph.to_dict())` instead of
`compile()` — same JSON, no Rust required.

## Lazy import

`material/__init__.py` uses `_LAZY_MAP` + `__getattr__` so a bare
`import pharos_engine` does **not** import the Rust `_core` extension or
`pharos_engine.material.node_material`. The extension only loads when a
factory is referenced (`UVNode`, `NodeMaterial`, …). This matters for:

- Headless CI without wgpu / `_core` built.
- The `[editor]` install path that doesn't ship `_core`.
- Startup latency on the engine's "import everything" smoke test.

The lazy import is asserted by
`SlapPyEngineTests/tests/test_material_lazy_import.py` — adding a
top-level import of `node_material` in `__init__.py` breaks the test.

## Performance

The graph runtime is **authoring-time**, not per-frame. Once a
`NodeMaterial` is compiled, the cached WGSL gets handed to the
renderer's pipeline-creation path and executes at native GPU
throughput. Python overhead on the authoring side:

| Operation | Cost (typical 10-node graph) |
|---|---|
| `node()` × 10 + `connect()` × 12 | ~50 µs |
| `to_json()` | ~30 µs |
| `from_json()` | ~80 µs |
| `validate_node_graph()` | ~100 µs |
| `compile()` → Rust | ~2 ms (Rust side dominates) |

Authoring tools call these in millisecond-cadence interactive loops
without breaking 60 fps. No Rust migration is planned for the Python
side — the Rust compiler already owns the hot path.

## See also

- [`api/material.md`](api/material.md) — full factory catalogue,
  `NodeMaterial` methods, schema constants.
- [`material_catalog.md`](material_catalog.md) — the `MaterialMap`
  side (classification + behaviour tags) consumed by per-pixel physics.
- [`api/ui_editor.md`](api/ui_editor.md) — `MaterialEditor` (the visual
  editor that drives the authoring surface) and `PropertyInspector`
  (the reflection panel softbody / fluid material editing reuses).
- [`api/gpu.md`](api/gpu.md) — `MaterialBuffer` packs the `MaterialMap`
  into a 32-byte std430 storage buffer for the per-pixel
  classification shader.
- [`api/post_process.md`](api/post_process.md) — `GravityWarpNode`
  reuses the same falloff curve as the post-process gravity-warp pass.
- [`post_process_design.md`](post_process_design.md) — the chain
  rendering surface graphs eventually feed into.

## References

- Carmack, J. (2009). *id Tech 5 megatexture / virtual texturing.*
  Background for "sample texture at the warped UV" patterns the
  `SampleTextureNode + GravityWarpNode` flow models.
- Blender Foundation. *Shader nodes (Cycles / EEVEE).* Reference for
  the node-graph authoring conventions this surface mirrors.
- Sprint 1B notes (`docs/sprint_1_retrospective.md`) — restoration of
  the 19 lowercase factories.
